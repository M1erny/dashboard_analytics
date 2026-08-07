"""Backfill upload dates onto already-indexed sources.

The Drive folder crawl did not request createdTime until recently, so every
source indexed before that has no upload date. Re-syncing would fix it, but a
re-sync re-downloads and re-extracts every file to recover one timestamp per
document.

This lists Drive once, matches by driveFileId, and merges the dates into source
metadata. No downloads, no re-extraction, no chunk churn.
"""

from typing import Any

from drive_indexer import FOLDER_MIME_TYPE


def backfill_drive_dates(
    store: Any,
    client: Any,
    *,
    folder_id: str,
    limit_files: int = 20_000,
    force: bool = False,
) -> dict[str, Any]:
    """Merge Drive createdTime/modifiedTime into indexed sources.

    Only sources missing the date are touched unless force is set, so a repeat
    run over an already-backfilled library is cheap and writes nothing.
    """
    drive_files = client.iter_files(folder_id, limit_files=limit_files)
    by_id: dict[str, dict[str, Any]] = {
        str(item.get("id")): item
        for item in drive_files
        if item.get("id") and item.get("mimeType") != FOLDER_MIME_TYPE
    }

    updated = 0
    already_dated = 0
    unmatched = 0
    missing_from_drive = 0
    examined = 0

    for source in store.source_content_stats():
        metadata = source.get("metadata") or {}
        drive_file_id = metadata.get("driveFileId")
        if not drive_file_id:
            unmatched += 1
            continue

        examined += 1
        if metadata.get("uploadedAt") and not force:
            already_dated += 1
            continue

        drive_file = by_id.get(str(drive_file_id))
        if drive_file is None:
            # Indexed once, since deleted or moved out of the folder. Its text is
            # still searchable, so this is worth reporting rather than hiding.
            missing_from_drive += 1
            continue

        updates: dict[str, Any] = {}
        if drive_file.get("createdTime"):
            updates["uploadedAt"] = drive_file["createdTime"]
        if drive_file.get("modifiedTime") and (force or not metadata.get("modifiedAt")):
            updates["modifiedAt"] = drive_file["modifiedTime"]
        if not updates:
            continue

        store.update_source_metadata(int(source["id"]), updates)
        updated += 1

    return {
        "folderId": folder_id,
        "driveFiles": len(by_id),
        "driveSources": examined,
        "updated": updated,
        "alreadyDated": already_dated,
        "missingFromDrive": missing_from_drive,
        "nonDriveSources": unmatched,
        "message": _message(updated, already_dated, missing_from_drive),
    }


def _message(updated: int, already_dated: int, missing_from_drive: int) -> str:
    if not updated and not already_dated:
        return "No Drive sources were found to date. Run Sync Drive first."
    parts = [f"Dated {updated} source(s)"]
    if already_dated:
        parts.append(f"{already_dated} already had an upload date")
    if missing_from_drive:
        parts.append(f"{missing_from_drive} indexed source(s) are no longer in the Drive folder")
    return ". ".join(parts) + "."
