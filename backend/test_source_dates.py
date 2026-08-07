"""Checks for searching indexed sources by date.

Three producers write these timestamps in three ISO-8601 shapes, and a bare date
has to mean the whole day at both ends. Both are the kind of thing that appears
to work until the one query where it matters returns a short list that looks
complete.
"""

import tempfile
from pathlib import Path

import source_dates
from brain_store import BrainStore


# --- Bound normalisation ---------------------------------------------------

assert source_dates.normalize_bound("2026-08-04", end_of_day=False) == "2026-08-04T00:00:00"
assert source_dates.normalize_bound("2026-08-04", end_of_day=True) == "2026-08-04T23:59:59"
assert source_dates.normalize_bound("2026-08-04T13:30:00Z", end_of_day=True) == "2026-08-04T13:30:00"
assert source_dates.normalize_bound("2026-08-04T13:30", end_of_day=False) == "2026-08-04T13:30:00"
assert source_dates.normalize_bound("2026-08-04T13:30", end_of_day=True) == "2026-08-04T13:30:59"
assert source_dates.normalize_bound("2026-08-04 13:30:00", end_of_day=False) == "2026-08-04T13:30:00"
assert source_dates.normalize_bound("", end_of_day=False) is None
assert source_dates.normalize_bound(None, end_of_day=True) is None

for junk in ("last tuesday", "04/08/2026", "2026", "yesterday"):
    try:
        source_dates.normalize_bound(junk, end_of_day=False)
    except ValueError as error:
        assert "Could not read" in str(error)
    else:
        raise AssertionError(f"expected {junk!r} to be rejected")

# Different producers, same comparable prefix. This is the whole point.
drive_style = source_dates.comparable("2026-08-04T21:05:00.000Z")
brain_style = source_dates.comparable("2026-08-04T21:05:00.123456+00:00")
assert drive_style == brain_style == "2026-08-04T21:05:00"

# --- Field mapping ---------------------------------------------------------

assert source_dates.metadata_key("uploaded") == "uploadedAt"
assert source_dates.metadata_key("modified") == "modifiedAt"
assert source_dates.metadata_key("indexed") == "indexedAt"
assert source_dates.metadata_key(None) == "uploadedAt", "uploaded is the default"
try:
    source_dates.metadata_key("created")
except ValueError as error:
    assert "Unsupported date field" in str(error)
else:
    raise AssertionError("expected an unknown date field to be rejected")

# --- Range matching --------------------------------------------------------

uploaded = {"metadata": {"uploadedAt": "2026-06-02T12:30:00.000Z"}}
assert source_dates.matches_range(uploaded, after="2026-06-01", before="2026-06-30")
assert source_dates.matches_range(uploaded, before="2026-06-02"), "a bare date must cover its whole day"
assert source_dates.matches_range(uploaded, after="2026-06-02"), "and at the other end too"
assert not source_dates.matches_range(uploaded, after="2026-06-03")
assert not source_dates.matches_range(uploaded, before="2026-06-01")

undated = {"metadata": {"modifiedAt": "2026-06-02T12:30:00.000Z"}}
assert not source_dates.matches_range(undated, after="2026-01-01"), "no upload date means excluded by default"
assert source_dates.matches_range(undated, after="2026-01-01", include_undated=True)
assert source_dates.matches_range(undated, date_field="modified", after="2026-06-01")


# --- Against a real store --------------------------------------------------

FILES = [
    ("jan.pdf", "2026-01-15T09:00:00.000Z", "2026-02-01T09:00:00.000Z"),
    ("jun.pdf", "2026-06-02T12:30:00.000Z", "2026-06-02T12:30:00.000Z"),
    ("aug.pdf", "2026-08-04T21:05:00.000Z", "2026-08-05T08:00:00.000Z"),
]

with tempfile.TemporaryDirectory() as directory:
    store = BrainStore(Path(directory) / "dates.db")
    for index, (name, uploaded_at, modified_at) in enumerate(FILES):
        store.upsert_file_source(
            title=name,
            body=f"contents of {name} covering exposure and drawdown",
            tags=["google-drive"],
            metadata={
                "fileIdentity": f"drive:{index}",
                "fileHash": f"hash-{index}",
                "driveFileId": f"file-{index}",
                "fileName": name,
                "uploadedAt": uploaded_at,
                "modifiedAt": modified_at,
                # Written by the Brain, so a different ISO shape on purpose.
                "indexedAt": "2026-08-06T23:00:00.123456+00:00",
            },
        )
    # Indexed before the crawl captured createdTime: no upload date at all.
    store.upsert_file_source(
        title="legacy.pdf",
        body="older indexed file with no upload date",
        tags=["google-drive"],
        metadata={
            "fileIdentity": "drive:legacy",
            "fileHash": "hash-legacy",
            "driveFileId": "file-legacy",
            "fileName": "legacy.pdf",
            "modifiedAt": "2026-03-01T00:00:00.000Z",
        },
    )

    def titles(**kwargs) -> list[str]:
        return [source["title"] for source in store.list_sources(**kwargs)]

    assert titles() == ["aug.pdf", "jun.pdf", "jan.pdf", "legacy.pdf"], titles()
    assert titles(sort="oldest") == ["jan.pdf", "jun.pdf", "aug.pdf", "legacy.pdf"], (
        "undated sources sort last in both directions rather than heading the list"
    )

    assert titles(uploaded_after="2026-06-01") == ["aug.pdf", "jun.pdf"]
    assert titles(uploaded_before="2026-06-02") == ["jun.pdf", "jan.pdf"], (
        "a bare 'before' date must include files uploaded during that day"
    )
    assert titles(uploaded_after="2026-01-16", uploaded_before="2026-08-04") == ["aug.pdf", "jun.pdf"]
    assert titles(uploaded_after="2027-01-01") == []

    # Undated sources are excluded from a dated query unless asked for.
    assert "legacy.pdf" not in titles(uploaded_after="2026-01-01")
    assert "legacy.pdf" in titles(uploaded_after="2026-01-01", include_undated=True)

    # Switching field changes which files match, and rescues the undated one.
    assert titles(date_field="modified", uploaded_after="2026-02-01", uploaded_before="2026-03-01") == [
        "legacy.pdf",
        "jan.pdf",
    ]
    # The three Drive files share an indexed date written in the Brain's own
    # +00:00 shape, which still has to compare against a bare date. legacy.pdf
    # has no indexed date and so drops out.
    assert sorted(titles(date_field="indexed", uploaded_after="2026-08-06")) == [
        "aug.pdf",
        "jan.pdf",
        "jun.pdf",
    ], titles(date_field="indexed", uploaded_after="2026-08-06")

    # Free text and a date range compose.
    assert titles(query="drawdown", uploaded_after="2026-06-01") == ["aug.pdf", "jun.pdf"]
    assert titles(query="drawdown", uploaded_after="2026-08-01") == ["aug.pdf"]

    # An unusable date reaches the caller as a clear error, not an empty list.
    try:
        store.list_sources(uploaded_after="whenever")
    except ValueError as error:
        assert "Could not read" in str(error)
    else:
        raise AssertionError("expected an unparseable bound to raise")

print("Source date search checks passed.")
