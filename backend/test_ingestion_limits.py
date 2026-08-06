"""The no-truncation contract for the ingestion path.

The Brain is meant to hold every word of every supported file. That property is
easy to lose one clamp at a time, and the failure is silent: a capped document
still answers questions, just from whichever fraction happened to fit. These
tests pin the contract so a future change has to break them on purpose.
"""

import io
import os
import zipfile

import brain_indexer
import drive_indexer


def expect_untruncated(label: str, metadata: dict, produced: str, original: str) -> None:
    assert metadata.get("truncated") is False, f"{label} reported truncation at default settings"
    assert len(produced) >= len(original) * 0.99, (
        f"{label} kept {len(produced)} of {len(original)} characters at default settings"
    )


# --- Defaults are unlimited ------------------------------------------------

assert drive_indexer.DEFAULT_MAX_PDF_PAGES == 0, "Drive PDF page cap must default to unlimited"
assert drive_indexer.DEFAULT_MAX_EXTRACTED_CHARS == 0, "Drive character cap must default to unlimited"
assert brain_indexer.DEFAULT_LOCAL_MAX_PDF_PAGES == 0, "local PDF page cap must default to unlimited"
assert brain_indexer.DEFAULT_LOCAL_MAX_EXTRACTED_CHARS == 0, "local character cap must default to unlimited"

# The byte cap is deliberately a real number: download_file holds the whole file
# in memory. It must stay generous enough for a long filing.
assert drive_indexer.DEFAULT_MAX_BYTES >= 32 * 1024 * 1024, "Drive byte cap is too small for real filings"


# --- No hard ceiling may override an operator ------------------------------

# A ceiling inside a min() silently overrules whatever the env var asks for, so
# a very large request must survive intact.
os.environ["BRAIN_DRIVE_MAX_PDF_PAGES"] = "99999"
os.environ["BRAIN_DRIVE_MAX_EXTRACTED_CHARS"] = "99999999"
try:
    resolved_pages = max(0, drive_indexer._env_int("BRAIN_DRIVE_MAX_PDF_PAGES", drive_indexer.DEFAULT_MAX_PDF_PAGES) or 0)
    resolved_chars = max(0, drive_indexer._env_int("BRAIN_DRIVE_MAX_EXTRACTED_CHARS", drive_indexer.DEFAULT_MAX_EXTRACTED_CHARS) or 0)
    assert resolved_pages == 99999, f"a page ceiling clipped the request to {resolved_pages}"
    assert resolved_chars == 99999999, f"a character ceiling clipped the request to {resolved_chars}"
finally:
    del os.environ["BRAIN_DRIVE_MAX_PDF_PAGES"]
    del os.environ["BRAIN_DRIVE_MAX_EXTRACTED_CHARS"]


# --- Extraction keeps everything at default settings -----------------------

BIG_TEXT = ("Realised contribution reconciles to the financing line. " * 12_000).encode("utf-8")
assert len(BIG_TEXT) > 600_000

text, meta = drive_indexer.extract_drive_file_text(BIG_TEXT, ".txt")
expect_untruncated("plain text", meta, text, BIG_TEXT.decode("utf-8"))

BIG_HTML = b"<html><body>" + b"<p>Gross exposure held at 140 percent through the rebalance.</p>" * 12_000 + b"</body></html>"
text, meta = drive_indexer.extract_drive_file_text(BIG_HTML, ".html")
assert meta["truncated"] is False
assert len(text) > 500_000, f"HTML extraction kept only {len(text)} characters"

# An explicit cap must still work, and must admit to itself.
text, meta = drive_indexer.extract_drive_file_text(BIG_TEXT, ".txt", max_extracted_chars=1_000)
assert meta["truncated"] is True and len(text) == 1_000

# The old plain-text truncation flag compared byte length against a character
# limit, so a multi-byte document reported truncation that never happened.
accented = ("wartość ".encode("utf-8") * 200)
text, meta = drive_indexer.extract_drive_file_text(accented, ".txt", max_extracted_chars=100_000)
assert meta["truncated"] is False, "byte length must not be compared against a character cap"


# --- OOXML formats are reachable end to end --------------------------------

for extension in (".xlsx", ".pptx", ".docx", ".pdf"):
    assert extension in brain_indexer.SUPPORTED_EXTENSIONS, f"{extension} missing from the allowlist"

MIME_FOR = drive_indexer.MIME_EXTENSION_MAP
assert MIME_FOR["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"] == ".xlsx"
assert MIME_FOR["application/vnd.openxmlformats-officedocument.presentationml.presentation"] == ".pptx"

# A .xlsx uploaded to Drive must route to the workbook extractor, not be rejected.
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w") as archive:
    archive.writestr(
        "xl/worksheets/sheet1.xml",
        '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row><c t="inlineStr"><is><t>Gross exposure</t></is></c></row></sheetData></worksheet>',
    )

text, meta = drive_indexer.extract_drive_file_text(buffer.getvalue(), ".xlsx")
assert "Gross exposure" in text and meta["extractor"] == "xlsx-xml"


# --- Native Workspace files export without losing content ------------------

exports = drive_indexer.GOOGLE_WORKSPACE_EXPORTS
# A Sheet exported as CSV keeps only its first tab.
assert exports["application/vnd.google-apps.spreadsheet"][1] == ".xlsx", "Sheets must export as xlsx to keep every tab"
# A deck exported as plain text loses every speaker note.
assert exports["application/vnd.google-apps.presentation"][1] == ".pptx", "Slides must export as pptx to keep notes"
for mime_type, (_export_mime, extension) in exports.items():
    assert extension in brain_indexer.SUPPORTED_EXTENSIONS, f"{mime_type} exports to unsupported {extension}"


# --- The API must not undercut the indexer ---------------------------------

try:
    import server
except Exception as error:  # pragma: no cover - server needs the full stack
    server = None
    print(f"(skipping API ceiling checks: {error})")

if server is not None:
    sync = server.BrainDriveIndexRequest()
    assert sync.maxBytes >= drive_indexer.DEFAULT_MAX_BYTES, "the sync request caps bytes below the indexer's own limit"
    assert sync.limitFiles >= 20_000, "the sync request would strand files in a large folder"
    assert sync.changedFilesLimit and sync.changedFilesLimit >= 1000, (
        "a small per-run file limit strands files without saying so"
    )

    embed = server.BrainEmbeddingBackfillStartRequest()
    assert embed.maxChunks >= 100_000, "embedding a fully indexed library must not need repeated clicks"
    assert embed.batchSize >= 16

    # The coverage report must measure against the same byte limit the sync uses.
    assert server.DRIVE_SYNC_MAX_BYTES == drive_indexer.DEFAULT_MAX_BYTES

print("Ingestion no-truncation contract checks passed.")
