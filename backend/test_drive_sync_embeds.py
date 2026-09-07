"""A Drive sync must leave its new passages embedded, not merely indexed.

An indexed passage without an embedding is reachable by exact words only. Agent
imports queue the embedding backfill when they finish; the Drive sync did not,
so every synced file stayed half-searchable until someone pressed Embed Missing,
and answers reported "N of M passages are still unembedded" after each sync.
These checks pin the hook and the conditions under which it must stay quiet.
"""

import asyncio
import sys
from types import SimpleNamespace

import server

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        FAILED.append(name)


class Recorder:
    """Stands in for _run_embedding_backfill_job; records the call, does nothing."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)

        async def _noop():
            return None

        return _noop()


def run_sync(*, indexed, embed_after_sync=True, embed_max_chunks=5_000, gemini_configured=True, backfill_running=False, raises=None):
    saved = (server.brain_store, server.index_drive_folder, server.gemini_client,
             server._run_embedding_backfill_job, dict(server.embedding_backfill_job), dict(server.drive_index_job))
    recorder = Recorder()

    def fake_index(store, **kwargs):
        if raises:
            raise raises
        return {"folderId": "f", "folderUrl": None, "summary": {"indexed": indexed, "skipped": 0, "errors": 0, "deferred": 0, "found": indexed}, "counts": {}, "results": []}

    server.brain_store = object()
    server.index_drive_folder = fake_index
    server.gemini_client = SimpleNamespace(configured=gemini_configured)
    server._run_embedding_backfill_job = recorder
    server.embedding_backfill_job["running"] = backfill_running
    try:
        asyncio.run(server._run_drive_index_job(
            folder_id=None, limit_files=10, max_bytes=1024 * 1024, changed_files_limit=None, force=False,
            embed_after_sync=embed_after_sync, embed_max_chunks=embed_max_chunks,
        ))
        return recorder.calls, dict(server.drive_index_job)
    finally:
        (server.brain_store, server.index_drive_folder, server.gemini_client,
         server._run_embedding_backfill_job, backfill_state, drive_state) = saved
        server.embedding_backfill_job.clear(); server.embedding_backfill_job.update(backfill_state)
        server.drive_index_job.clear(); server.drive_index_job.update(drive_state)


print("\n=== Drive sync queues the embedding backfill ===")

req = server.BrainDriveIndexRequest()
check("embedding after a sync is on by default", req.embedAfterSync is True)
check("the default chunk budget covers a real sync, not a handful", req.embedMaxChunks >= 1_000, str(req.embedMaxChunks))

calls, job = run_sync(indexed=3)
check("a sync that indexed files queues the backfill", len(calls) == 1 and job.get("embeddingQueued") is True, f"calls={calls} job={job.get('embeddingQueued')}")
check("with the requested budget, not the agent-import cap of 500", calls and calls[0]["max_chunks"] == 5_000, str(calls))
check("in the same small batches the agent import uses", calls and calls[0]["batch_size"] == 5 and calls[0]["force"] is False)
check("and says so in the job message", "queued" in (job.get("message") or "").lower(), job.get("message"))
check("the job itself finished cleanly", job.get("running") is False and job.get("finishedAt"))

calls, job = run_sync(indexed=0)
check("a sync that indexed nothing does not queue anything", calls == [] and job.get("embeddingQueued") is False)

calls, job = run_sync(indexed=3, embed_after_sync=False)
check("the flag turns it off", calls == [] and job.get("embeddingQueued") is False)

calls, job = run_sync(indexed=3, gemini_configured=False)
check("no provider: the sync still succeeds and the message points at Embed Missing",
      calls == [] and job.get("embeddingQueued") is False and "Embed Missing" in (job.get("message") or ""), job.get("message"))

calls, job = run_sync(indexed=3, backfill_running=True)
check("a backfill already running is not doubled", calls == [] and job.get("embeddingQueued") is False)

calls, job = run_sync(indexed=3, raises=RuntimeError("drive down"))
check("a failed sync queues nothing and reports the failure", calls == [] and "Drive sync stopped" in (job.get("message") or ""), job.get("message"))

# The agent-import path keeps its own, smaller cap.
saved = (server.gemini_client, server._run_embedding_backfill_job, dict(server.embedding_backfill_job))
rec = Recorder()
server.gemini_client = SimpleNamespace(configured=True); server._run_embedding_backfill_job = rec; server.embedding_backfill_job["running"] = False
try:
    async def _drive():
        return server._queue_embedding_after_import(60), server._queue_embedding_after_import(9_999), server._queue_embedding_after_import(9_999, cap=100_000)
    a, b, c = asyncio.run(_drive())
finally:
    server.gemini_client, server._run_embedding_backfill_job, state = saved
    server.embedding_backfill_job.clear(); server.embedding_backfill_job.update(state)
check("agent import: 60 passes through", a and rec.calls[0]["max_chunks"] == 60)
check("agent import: still capped at 500", b and rec.calls[1]["max_chunks"] == 500)
check("drive sync: the higher cap lets a large sync through", c and rec.calls[2]["max_chunks"] == 9_999)
check("the public job projection carries embeddingQueued", "embeddingQueued" in server._public_drive_job())

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s): {', '.join(FAILED)}")
    sys.exit(1)
print("All Drive-sync embedding checks passed.")
