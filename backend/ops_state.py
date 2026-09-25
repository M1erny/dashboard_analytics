"""Operational state that has to outlive the process.

Render's free tier sleeps after idling and restarts on every deploy, and each
restart used to reset every job record to "Idle": a Drive sync that died halfway
looked like one that never ran, and a Yahoo cooldown was forgotten, so the first
request after a restart asked Yahoo again straight away. These records are small,
change rarely, and are what the health view reports, so they live in the brain
store under ops.* keys, next to the settings it already holds.

Writes are best effort. The store being down must never fail the job whose
progress is being recorded; the error is returned so the caller can surface it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

OPS_PREFIX = "ops.state.v1."
# Lists that can run to thousands of rows. The count survives; the rows do not.
_UNBOUNDED_LIST_FIELDS = ("results",)
_TRIMMED_LIST_FIELDS = ("errors",)
_TRIM_TO = 5


def key(name: str) -> str:
    return OPS_PREFIX + name


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def for_storage(state: dict[str, Any]) -> dict[str, Any]:
    """A copy of a job record small enough to write on every transition."""
    clean: dict[str, Any] = {}
    for field, value in (state or {}).items():
        if field in _UNBOUNDED_LIST_FIELDS and isinstance(value, list):
            clean[f"{field}Count"] = len(value)
            continue
        if field in _TRIMMED_LIST_FIELDS and isinstance(value, list):
            clean[f"{field}Count"] = len(value)
            clean[field] = value[:_TRIM_TO]
            continue
        clean[field] = value
    clean["persistedAt"] = _utc_now_iso()
    return clean


def save(store: Any, name: str, state: dict[str, Any]) -> str | None:
    """Write one record. Returns None on success, or a short reason on failure."""
    if store is None or not hasattr(store, "set_setting"):
        return "no brain store"
    try:
        store.set_setting(key(name), json.dumps(for_storage(state), default=str, separators=(",", ":")))
        return None
    except Exception as exc:  # recorded, not raised: see module docstring
        text = str(exc).strip()
        return (text.splitlines()[0] if text else type(exc).__name__)[:200]


def load(store: Any, name: str) -> dict[str, Any] | None:
    if store is None or not hasattr(store, "get_setting"):
        return None
    try:
        raw = store.get_setting(key(name))
    except Exception:
        return None
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def restore_job(target: dict[str, Any], saved: dict[str, Any] | None) -> bool:
    """Fold a saved record into a live job dict at startup. True if anything was restored.

    A record saved as running cannot still be running: this process just started.
    It is restored as interrupted, with its last known progress, rather than as
    "Idle", which would read as though the job had never been started.
    """
    if not saved:
        return False
    for field, value in saved.items():
        if field in _UNBOUNDED_LIST_FIELDS:
            continue
        target[field] = value
    if saved.get("running"):
        target["running"] = False
        target["interrupted"] = True
        progress = str(saved.get("message") or "").strip()
        target["message"] = (
            f"Interrupted by a backend restart; it had been running since {saved.get('startedAt') or 'an unknown time'}."
            + (f" Last progress: {progress}" if progress else "")
        )
    else:
        target.setdefault("interrupted", False)
    target["restoredFrom"] = saved.get("persistedAt")
    return True
