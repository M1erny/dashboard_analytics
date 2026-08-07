"""Date filtering for indexed sources.

Three different dates get called "the date" of a file, and they answer different
questions:

- uploaded: when the file appeared in Drive (Drive's createdTime)
- modified: when it last changed (Drive's modifiedTime)
- indexed:  when the Brain read it

They live in source metadata as ISO-8601 strings written by different producers,
so their formats differ: Drive sends `2026-08-04T21:05:00.000Z` while the Brain
writes `2026-08-04T21:05:00.123456+00:00`. Comparing those as raw strings works
by luck until it doesn't, so every comparison here is done on the first 19
characters, `YYYY-MM-DDTHH:MM:SS`, which both formats share exactly.
"""

import re
from typing import Any


DATE_FIELDS = {
    "uploaded": "uploadedAt",
    "modified": "modifiedAt",
    "indexed": "indexedAt",
}
DEFAULT_DATE_FIELD = "uploaded"
COMPARABLE_LENGTH = 19

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?")


def metadata_key(date_field: str | None) -> str:
    """Map a public field name to the metadata key that holds it."""
    key = (date_field or DEFAULT_DATE_FIELD).strip().lower()
    if key not in DATE_FIELDS:
        raise ValueError(
            f"Unsupported date field: {date_field}. Use one of {', '.join(sorted(DATE_FIELDS))}."
        )
    return DATE_FIELDS[key]


def normalize_bound(value: str | None, *, end_of_day: bool) -> str | None:
    """Normalise a user-supplied bound to a 19-character comparable prefix.

    A bare date means the whole day, so `before=2026-08-04` has to include
    everything up to 23:59:59 on the 4th. Truncating it to `2026-08-04` instead
    would silently exclude that entire day.
    """
    raw = (value or "").strip()
    if not raw:
        return None

    if _DATE_ONLY.match(raw):
        return f"{raw}T23:59:59" if end_of_day else f"{raw}T00:00:00"

    if not _DATE_TIME.match(raw):
        raise ValueError(
            f"Could not read {raw!r} as a date. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS."
        )

    normalized = raw.replace(" ", "T")[:COMPARABLE_LENGTH]
    if len(normalized) == 16:  # minute precision, no seconds
        normalized += ":59" if end_of_day else ":00"
    return normalized


def comparable(value: Any) -> str | None:
    """Reduce a stored timestamp to the prefix used for comparisons."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().replace(" ", "T")[:COMPARABLE_LENGTH]


def source_date(source: dict[str, Any], date_field: str | None = None) -> str | None:
    """Read the requested date off a source, or None when it was never captured."""
    metadata = source.get("metadata") if isinstance(source, dict) else None
    if not isinstance(metadata, dict):
        return None
    return metadata.get(metadata_key(date_field))


def matches_range(
    source: dict[str, Any],
    *,
    date_field: str | None = None,
    after: str | None = None,
    before: str | None = None,
    include_undated: bool = False,
) -> bool:
    """Whether a source falls inside the requested window.

    A source with no date for the requested field is excluded by default. A file
    the Brain has no upload date for is not a file that was uploaded on some
    unknown-but-matching day; it is a gap, and silently keeping it would make an
    empty result look like a complete one.
    """
    value = comparable(source_date(source, date_field))
    if value is None:
        return include_undated

    low = normalize_bound(after, end_of_day=False)
    high = normalize_bound(before, end_of_day=True)
    if low and value < low:
        return False
    if high and value > high:
        return False
    return True
