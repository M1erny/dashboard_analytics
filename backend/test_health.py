"""The health view and the durable job state behind it.

Almost every serious defect here was silent: an index that never existed, an
empty download cached as data, synced files never embedded, a scheduler dropping
runs, a restart resetting every job to "Idle". These checks pin the rules that
turn those facts into a visible verdict, and the persistence that lets the facts
survive a restart in the first place.
"""

import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

import health
import ops_state

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        FAILED.append(name)


# A Wednesday afternoon, inside the hours the refresh job is scheduled for.
NOW = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
SATURDAY = datetime(2026, 9, 26, 14, 0, tzinfo=timezone.utc)
iso = lambda dt: dt.isoformat()

print("\n=== Market data ===")
c = health.check_market_data(None, None, 0, NOW)
check("nothing computed and no snapshot is unknown, with an action", c["status"] == "unknown" and c["action"])
c = health.check_market_data({"stale": False, "source": "yahoo", "asOf": "2026-09-22"}, None, 0, NOW)
check("a live fetch of yesterday's close is ok", c["status"] == "ok", c["summary"])
c = health.check_market_data(None, {"asOf": "2026-09-22"}, 0, NOW)
check("a fresh process falls back to the snapshot's market date", c["status"] == "ok" and c["detail"]["asOf"] == "2026-09-22")
c = health.check_market_data({"stale": True, "source": "snapshot", "asOf": "2026-09-22", "message": "boom"}, None, 0, NOW)
check("a failed refresh over current data is a warning, not a failure", c["status"] == "warn" and "current" in c["summary"], c["summary"])
c = health.check_market_data({"stale": True, "asOf": "2026-09-22"}, None, 480, NOW)
check("a Yahoo cooldown is reported with the wait", c["status"] == "warn" and "8 min" in c["summary"], c["summary"])
c = health.check_market_data({"stale": True, "asOf": "2026-09-10"}, None, 0, NOW)
check("data missing whole sessions fails", c["status"] == "fail" and "13 days" in c["summary"], c["summary"])

print("\n=== Snapshot refresh ===")
window = 8 * 3600
check("no metadata yet is unknown", health.check_snapshot_refresh(None, window, NOW)["status"] == "unknown")
c = health.check_snapshot_refresh({"fetchedAt": iso(NOW - timedelta(hours=3)), "writer": "github-actions"}, window, NOW)
check("written three hours ago by the job is ok, and names the writer", c["status"] == "ok" and "github-actions" in c["summary"], c["summary"])
c = health.check_snapshot_refresh({"fetchedAt": iso(NOW - timedelta(hours=20)), "writer": "github-actions"}, window, NOW)
check("twenty hours on a weekday afternoon means the scheduler missed runs", c["status"] == "warn" and c["action"], c["summary"])
c = health.check_snapshot_refresh({"fetchedAt": iso(SATURDAY - timedelta(hours=40)), "writer": "github-actions"}, window, SATURDAY)
check("the same gap on a Saturday is expected, not a warning", c["status"] == "ok", c["summary"])
c = health.check_snapshot_refresh({"fetchedAt": iso(NOW - timedelta(days=5)), "writer": "local"}, window, NOW)
check("five days fails", c["status"] == "fail")

print("\n=== Vector index, embeddings, LLM ===")
check("SQLite needs no vector index", health.check_vector_index(None)["status"] == "ok")
check("a built index is ok", health.check_vector_index({"status": "ok"})["status"] == "ok")
check("a building index is a warning", health.check_vector_index({"status": "building"})["status"] == "warn")
c = health.check_vector_index({"status": "failed", "error": "type halfvec does not exist"})
check("a failed index fails, carries the reason, and says what to do", c["status"] == "fail" and "halfvec" in c["summary"] and "pgvector" in c["action"], c["summary"])
check("an empty library is ok", health.check_embeddings({"total": 0, "missing": 0}, {})["status"] == "ok")
check("a 1% backlog is below the bar", health.check_embeddings({"total": 10_000, "missing": 100}, {})["status"] == "ok")
c = health.check_embeddings({"total": 12_524, "missing": 490}, {})
check("the reported 490 of 12,524 backlog warns with the action", c["status"] == "warn" and c["action"] == "Embed missing passages", c["summary"])
check("a backlog with the job running is ok", health.check_embeddings({"total": 12_524, "missing": 490}, {"running": True})["status"] == "ok")
check("unreadable coverage is unknown", health.check_embeddings(None, {})["status"] == "unknown")
check("no Gemini key fails with the variable to set", health.check_llm(False)["status"] == "fail" and "GOOGLE_AI_API_KEY" in health.check_llm(False)["action"])

print("\n=== Jobs ===")
job = lambda **k: health._check_job("drive_sync", "Drive sync", k, failure_prefix="Drive sync stopped")
check("never run is ok", job()["status"] == "ok")
check("running is ok", job(running=True, startedAt="t")["status"] == "ok")
check("interrupted by a restart warns and says to start it again", job(interrupted=True, message="Interrupted")["status"] == "warn" and job(interrupted=True)["action"])
check("a stopped job fails", job(message="Drive sync stopped: token expired", finishedAt="t")["status"] == "fail")
check("finished with errors warns", job(message="done", finishedAt="t", errors=[1, 2])["status"] == "warn")
check("finished cleanly is ok", job(message="12 indexed", finishedAt="t")["status"] == "ok")

print("\n=== Assembly ===")
report = health.assemble([health.check_llm(True), health.check_vector_index({"status": "building"}), health.check_llm(False)], now=NOW)
check("overall status is the worst check", report["status"] == "fail")
check("issues list only warn and fail, worst first", [i["status"] for i in report["issues"]] == ["fail", "warn"], str(report["issues"]))
check("an all-ok report has no issues", health.assemble([health.check_llm(True)], now=NOW)["issueCount"] == 0)

print("\n=== Durable job state ===")
big = {"running": True, "startedAt": "2026-09-25T10:00:00Z", "message": "42 of 900 files",
       "results": list(range(900)), "errors": list(range(12))}
stored = ops_state.for_storage(big)
check("results are reduced to a count", "results" not in stored and stored["resultsCount"] == 900)
check("errors are trimmed but counted", len(stored["errors"]) == 5 and stored["errorsCount"] == 12)
check("the stored record is small", len(json.dumps(stored)) < 400, str(len(json.dumps(stored))))

target = {"running": False, "message": "Idle", "results": []}
ops_state.restore_job(target, stored)
check("a job saved as running comes back as interrupted, not running", target["running"] is False and target["interrupted"] is True)
check("with its last progress in the message", "42 of 900 files" in target["message"] and "restart" in target["message"])
check("and without clobbering the live results list", target["results"] == [])
done = {"running": False, "finishedAt": "t", "message": "12 indexed"}
target = {"running": False, "message": "Idle"}
ops_state.restore_job(target, ops_state.for_storage(done))
check("a finished job comes back finished", target["message"] == "12 indexed" and target["interrupted"] is False)
check("nothing saved restores nothing", ops_state.restore_job({}, None) is False)


class BrokenStore:
    def set_setting(self, key, value): raise RuntimeError("supabase write timed out\nstack...")
    def get_setting(self, key): raise RuntimeError("down")


check("a failing store write returns its reason instead of raising", ops_state.save(BrokenStore(), "x", {}) == "supabase write timed out")
check("a failing read loads nothing", ops_state.load(BrokenStore(), "x") is None)
check("no store is reported, not crashed on", ops_state.save(None, "x", {}) == "no brain store")

print("\n=== Server: restore after restart, persist on transitions ===")
import server
from brain_store import BrainStore

store = BrainStore(db_path=os.path.join(tempfile.mkdtemp(), "brain.db"))
saved = (server.brain_store, dict(server.drive_index_job), dict(server.embedding_backfill_job), server.risk._rate_limited_until)
server.brain_store = store
try:
    ops_state.save(store, "drive_index", {"running": True, "startedAt": "2026-09-25T09:00:00Z", "message": "300 of 1200"})
    ops_state.save(store, "yahoo_cooldown", {"until": time.time() + 300})
    server.risk._rate_limited_until = 0.0
    restored = server._restore_ops_state_sync()
    check("a sync killed mid-run is restored as interrupted", server.drive_index_job["interrupted"] and "300 of 1200" in server.drive_index_job["message"], server.drive_index_job["message"])
    check("the Yahoo cooldown survives the restart", restored.get("yahoo_cooldown") and server.risk.rate_limit_remaining() > 250)
    check("the public projection exposes it", server._public_drive_job()["interrupted"] is True)

    async def run_sync():
        saved_index = server.index_drive_folder
        server.index_drive_folder = lambda store, **k: {"folderId": "f", "summary": {"indexed": 0, "skipped": 1, "errors": 0, "deferred": 0, "found": 1}, "counts": {}, "results": [{"x": 1}] * 50}
        try:
            await server._run_drive_index_job(folder_id="f", limit_files=10, max_bytes=1024, changed_files_limit=None, force=False, embed_after_sync=False)
        finally:
            server.index_drive_folder = saved_index

    asyncio.run(run_sync())
    after = ops_state.load(store, "drive_index")
    check("a finished sync is persisted as finished, clearing the interruption",
          after and after["running"] is False and after.get("interrupted") is False and after["finishedAt"], str(after))
    check("without its per-file results", after and "results" not in after and after.get("resultsCount") == 50)
finally:
    server.brain_store, drive_state, embed_state, server.risk._rate_limited_until = saved
    server.drive_index_job.clear(); server.drive_index_job.update(drive_state)
    server.embedding_backfill_job.clear(); server.embedding_backfill_job.update(embed_state)

print("\n=== Snapshot freshness default ===")
if "MARKET_SNAPSHOT_FRESH_SECONDS" not in os.environ:
    check("a snapshot is served without calling Yahoo for eight hours by default",
          server.MARKET_SNAPSHOT_FRESH_SECONDS == 8 * 3600, str(server.MARKET_SNAPSHOT_FRESH_SECONDS))

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s): {', '.join(FAILED)}")
    sys.exit(1)
print("All health and ops-state checks passed.")
