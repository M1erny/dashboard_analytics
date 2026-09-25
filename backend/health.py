"""One answer to "is anything wrong right now?", assembled from facts the backend
already holds.

Almost every serious defect this project has had was silent: an index that was
never created, an empty download cached as data, synced files never embedded, a
scheduler dropping runs. Each was recorded somewhere, or could have been, and
none of it reached a screen. This module turns those facts into a short list of
checks, each with a status, a sentence a person can act on, and, where there is
one, the action. It does no I/O: the endpoint gathers the inputs and this decides,
so every rule below is testable on plain dictionaries.

Statuses, in order of severity: ok < unknown < warn < fail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SEVERITY = {"ok": 0, "unknown": 1, "warn": 2, "fail": 3}
# Same threshold the dashboard uses for "(behind)": whole sessions are missing.
BEHIND_AFTER_DAYS = 4
# Below this share of unembedded passages, the backlog is noise, not a gap.
EMBEDDING_GAP_WARN_SHARE = 0.02


def _check(name: str, status: str, summary: str, *, action: str | None = None, detail: dict | None = None) -> dict:
    return {"name": name, "status": status, "summary": summary, "action": action, "detail": detail or {}}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age_hours(value: Any, now: datetime) -> float | None:
    parsed = _parse_time(value)
    return None if parsed is None else max(0.0, (now - parsed).total_seconds() / 3600)


def _market_date_age_days(as_of: Any, now: datetime) -> int | None:
    try:
        market_date = datetime.strptime(str(as_of), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return (now.date() - market_date).days


def check_market_data(market_status: dict | None, snapshot_meta: dict | None, cooldown_seconds: float, now: datetime) -> dict:
    """Are the numbers on the dashboard current, and is the refresh path healthy?"""
    status = market_status or {}
    as_of = status.get("asOf") or (snapshot_meta or {}).get("asOf")
    age_days = _market_date_age_days(as_of, now)
    detail = {"asOf": as_of, "source": status.get("source"), "reason": status.get("reason"),
              "cooldownSeconds": round(cooldown_seconds) if cooldown_seconds else 0}
    if as_of is None:
        return _check("market_data", "unknown", "No market data has been computed since the backend started, and no saved snapshot was found.",
                      action="Open the dashboard once, or run the Market snapshot refresh workflow.", detail=detail)
    if age_days is not None and age_days > BEHIND_AFTER_DAYS:
        return _check("market_data", "fail", f"Market data is from {as_of}, {age_days} days ago: whole sessions are missing.",
                      action="Run the Market snapshot refresh workflow, or refresh from your own machine.", detail=detail)
    if cooldown_seconds > 0:
        minutes = max(1, round(cooldown_seconds / 60))
        return _check("market_data", "warn", f"Figures are current (market date {as_of}), but Yahoo is rate-limiting the host; it is retried in about {minutes} min.",
                      detail=detail)
    if status.get("stale"):
        return _check("market_data", "warn", f"Figures are current (market date {as_of}), but the last live refresh failed: {status.get('message') or status.get('reason')}.",
                      detail=detail)
    return _check("market_data", "ok", f"Market data current as of {as_of}.", detail=detail)


def check_snapshot_refresh(snapshot_meta: dict | None, fresh_window_seconds: float, now: datetime) -> dict:
    """Is something (the scheduled job, the backend, a local run) keeping the snapshot fresh?"""
    if not snapshot_meta:
        return _check("snapshot_refresh", "unknown", "No saved market snapshot metadata yet. It is written with the next successful refresh.",
                      action="Run the Market snapshot refresh workflow once.")
    fetched_at = snapshot_meta.get("fetchedAt")
    age = _age_hours(fetched_at, now)
    writer = snapshot_meta.get("writer") or "unknown"
    detail = {"fetchedAt": fetched_at, "writer": writer, "ageHours": None if age is None else round(age, 1),
              "freshWindowHours": round(fresh_window_seconds / 3600, 1)}
    if age is None:
        return _check("snapshot_refresh", "unknown", "The saved snapshot has no readable fetch time.", detail=detail)
    window_h = fresh_window_seconds / 3600
    weekday_session_hours = now.weekday() < 5 and 6 <= now.hour <= 23
    if age > 24 * BEHIND_AFTER_DAYS:
        return _check("snapshot_refresh", "fail", f"The saved snapshot was last written {age / 24:.1f} days ago (by {writer}).",
                      action="Check the Market snapshot refresh workflow in GitHub Actions.", detail=detail)
    if weekday_session_hours and age > 2 * window_h:
        return _check("snapshot_refresh", "warn",
                      f"The snapshot was last written {age:.0f} h ago (by {writer}); the scheduled refresh has missed its recent runs.",
                      action="Run the workflow by hand; GitHub's scheduler drops runs.", detail=detail)
    return _check("snapshot_refresh", "ok", f"Snapshot written {age:.1f} h ago by {writer}.", detail=detail)


def check_vector_index(vector_index: dict | None) -> dict:
    if vector_index is None:
        return _check("vector_index", "ok", "Local SQLite store: no vector index needed.")
    state = vector_index.get("status")
    detail = dict(vector_index)
    if state == "ok":
        return _check("vector_index", "ok", "Vector index in place; semantic search uses it.", detail=detail)
    if state in ("pending", "building"):
        return _check("vector_index", "warn", "Vector index is being built; semantic search scans until it is ready.", detail=detail)
    return _check("vector_index", "fail",
                  f"Vector index {state or 'unknown'}: {vector_index.get('error') or 'no reason recorded'}. Semantic search scans every row and times out on a large library.",
                  action="If the error mentions halfvec, upgrade the pgvector extension in Supabase (0.7 or newer).", detail=detail)


def check_embeddings(stats: dict | None, embedding_job: dict | None) -> dict:
    if not stats:
        return _check("embeddings", "unknown", "Embedding coverage could not be read.")
    total = int(stats.get("total") or 0)
    missing = int(stats.get("missing") or 0)
    detail = {"total": total, "missing": missing}
    if total == 0 or missing == 0:
        return _check("embeddings", "ok", f"All {total:,} passages are embedded.", detail=detail)
    if (embedding_job or {}).get("running"):
        return _check("embeddings", "ok", f"{missing:,} of {total:,} passages still to embed; embedding is running.", detail=detail)
    share = missing / total
    status = "warn" if share >= EMBEDDING_GAP_WARN_SHARE else "ok"
    return _check("embeddings", status, f"{missing:,} of {total:,} passages are not embedded, so semantic search cannot see them.",
                  action="Embed missing passages" if status == "warn" else None, detail=detail)


def _check_job(name: str, label: str, job: dict | None, *, failure_prefix: str) -> dict:
    job = job or {}
    message = str(job.get("message") or "")
    detail = {k: job.get(k) for k in ("startedAt", "finishedAt", "interrupted", "restoredFrom", "message")}
    if job.get("running"):
        return _check(name, "ok", f"{label} is running since {job.get('startedAt')}.", detail=detail)
    if job.get("interrupted"):
        return _check(name, "warn", message or f"{label} was interrupted by a restart.", action=f"Start {label.lower()} again.", detail=detail)
    if message.startswith(failure_prefix):
        return _check(name, "fail", message, detail=detail)
    errors = job.get("errors") or []
    if errors:
        return _check(name, "warn", f"{label} finished with {len(errors)} error(s): {message}", detail=detail)
    if not job.get("finishedAt"):
        return _check(name, "ok", f"{label} has not run since the backend started.", detail=detail)
    return _check(name, "ok", f"{label}: {message}", detail=detail)


def check_llm(configured: bool) -> dict:
    if configured:
        return _check("llm", "ok", "Gemini is configured.")
    return _check("llm", "fail", "Gemini is not configured, so the Brain cannot embed or answer.",
                  action="Set GOOGLE_AI_API_KEY on Render.")


def check_ops_persistence(errors: dict[str, str]) -> dict:
    if not errors:
        return _check("ops_persistence", "ok", "Job state is being saved.")
    names = ", ".join(sorted(errors))
    return _check("ops_persistence", "warn", f"Could not save job state ({names}); a restart would forget it.",
                  detail={"errors": dict(errors)})


def assemble(checks: list[dict], *, now: datetime) -> dict:
    worst = max(checks, key=lambda c: SEVERITY.get(c["status"], 1)) if checks else None
    overall = worst["status"] if worst else "unknown"
    issues = [c for c in checks if SEVERITY.get(c["status"], 1) >= SEVERITY["warn"]]
    issues.sort(key=lambda c: -SEVERITY[c["status"]])
    return {
        "status": overall,
        "checkedAt": now.isoformat(),
        "issueCount": len(issues),
        "issues": [{"name": c["name"], "status": c["status"], "summary": c["summary"], "action": c["action"]} for c in issues],
        "checks": checks,
    }
