# Drive Ingestion And Coverage

Two questions this document answers: does the Brain hold all of a document, and
how would you know?

Both used to have uncomfortable answers. A PDF was cut at page 40, any file was
cut at 250,000 characters, spreadsheets and decks had no extractor at all, and
nothing in the dashboard said so. A truncated filing still answers questions —
it just answers them from the fraction that happened to fit.

## What is unlimited now

| Limit | Was | Now |
| --- | --- | --- |
| PDF pages per file (Drive) | 40 | unlimited |
| Characters per file (Drive) | 250,000 | unlimited |
| PDF pages per file (local library) | 2,000 | unlimited |
| Characters per file (local library) | 5,000,000 | unlimited |
| Env ceiling on page count | `min(…, 250)` | none |
| Env ceiling on character count | `min(…, 1,000,000)` | none |
| Files scanned per sync | 2,000 | 20,000 |
| Changed files per sync run | 20 | 2,000 |
| Chunks per embedding run | 500 | 100,000 |

`0` means unlimited for both extraction limits, and it is the default. The hard
ceilings inside the old `min()` clamps mattered as much as the defaults: they
silently overruled anyone who set the environment variable higher.

## What is still bounded, and why

**64 MB per file** (`BRAIN_DRIVE_MAX_BYTES`). `download_file` holds the whole
file in memory before extraction, so an unbounded download takes the Render
instance down rather than skipping one file. This is a real number instead of a
guess, and anything over it is *reported* by the coverage endpoint rather than
quietly dropped.

**~10 MB per Workspace export**, imposed by Google, not by this code. A very
large native Sheet cannot be exported at all; it shows up as an error in the
sync results.

**No OCR.** A scanned PDF with no text layer yields nothing. This is a missing
capability, not a limit that can be raised, and the coverage report calls it out
as `never_indexed_no_text` instead of counting the file as indexed.

**Embedding text is capped at 24,000 characters per chunk** by
`gemini_client.embed_text`. A chunk is ~900 words, so this never binds in
practice. Note that it affects only the vector: the chunk text itself is stored
in full and remains reachable by keyword search and full-document context.

## New formats

`.xlsx` and `.pptx` are extracted by `backend/office_extract.py` using nothing
but `zipfile` and `ElementTree`. That matters beyond tidiness:
`backend/requirements.txt` is outside the self-build agent's write allowlist, so
a dependency-free extractor is one the Brain can extend on its own later.

- **Workbooks** flatten to tab-separated rows, one sheet after another, with
  shared strings, inline strings, and cached formula results resolved.
- **Decks** yield slide text *and speaker notes*, which is usually where the
  actual argument lives.

### Native Google files export differently now

| Type | Was | Now | Why |
| --- | --- | --- | --- |
| Google Docs | `text/plain` | `text/plain` | Nothing was being lost |
| Google Sheets | `text/csv` | `.xlsx` | **A CSV export contains only the first tab.** Every other tab was invisible. |
| Google Slides | `text/plain` | `.pptx` | A plain-text export drops every speaker note |

The Sheets change is the one worth knowing about. If you keep multi-tab models
in Drive, the Brain has only ever read their first sheet.

Still unsupported: `.doc`, `.xls`, `.ppt` (the pre-2007 binary formats), Apple
iWork files, and images. These need either a dependency or OCR.

## Measuring coverage

```text
GET /api/brain/drive/coverage
```

Also the **Drive coverage** panel on the Brain page. It lists your Drive folder
live and joins it against what the store actually holds, so it is a measurement
rather than a restatement of what the last sync claimed.

It reports four percentages, and it separates the ones it counted from the one
it guessed:

| Metric | Exact? | Meaning |
| --- | --- | --- |
| `filesPercent` | exact | Files fully indexed, over files that count |
| `pdfPagesPercent` | exact | Pages read over pages that exist, across all indexed PDFs |
| `embeddedChunksPercent` | exact | Chunks with an embedding. Un-embedded chunks are invisible to semantic search |
| `tokensPercentEstimate` | **estimated** | Share of your library's text the Brain holds |

The token number is an estimate for an unavoidable reason: the size of a
document that was never read can only be inferred from its byte count. Where the
Brain *did* read a file and was cut short, the missing tail is arithmetic rather
than a guess — a PDF stopped at page 40 of 200 records both numbers, so the
report knows it holds a fifth of that document. Files in that state are marked
`estimateBasis: "page_ratio"`; genuinely unread files are marked
`"byte_ratio"` and should be read as order-of-magnitude only.

Every file is classified:

| Status | Meaning |
| --- | --- |
| `indexed_complete` | Fully in the Brain |
| `indexed_truncated` | Indexed, but cut short. Re-sync with `force` to pull the rest |
| `never_indexed_not_synced` | Supported and pending. Run Sync Drive |
| `never_indexed_unsupported` | No extractor exists |
| `never_indexed_too_large` | Over the per-file byte limit |
| `never_indexed_no_text` | Extracted to nothing, almost always a scan without OCR |
| `excluded_transcript` | Your own Brain transcripts, deliberately kept out of retrieval |

Transcripts are excluded from the denominator, so saving conversations to Drive
does not inflate your coverage number.

## Getting to 100%

1. **Sync Drive.** With the raised limits one run handles 2,000 changed files
   instead of 20. Repeat until `never_indexed_not_synced` is zero.
2. **Force a re-sync** to replace documents indexed under the old caps. An
   unchanged file is skipped by revision hash, so a truncated one stays
   truncated until forced:
   ```text
   POST /api/brain/index/drive/start  {"force": true}
   ```
   This re-downloads and re-extracts everything, which takes a while. It is the
   only way to convert `indexed_truncated` into `indexed_complete`.
3. **Embed.** More indexed text means more chunks, and a chunk without an
   embedding is invisible to semantic search. Watch `embeddedChunksPercent`.
4. **Re-measure.** The remaining gap is now real: unsupported formats and scans
   without OCR.

## Environment variables

```text
BRAIN_DRIVE_MAX_BYTES=67108864            # per file; cannot be disabled (memory)
BRAIN_DRIVE_MAX_PDF_PAGES=0               # 0 = unlimited
BRAIN_DRIVE_MAX_EXTRACTED_CHARS=0         # 0 = unlimited
BRAIN_LOCAL_MAX_PDF_PAGES=0
BRAIN_LOCAL_MAX_EXTRACTED_CHARS=0
BRAIN_PDF_EXTRACTION_TIMEOUT_SECONDS=600  # 0 = no timeout; local library path
BRAIN_POSTGRES_STATEMENT_TIMEOUT_MS=12000 # raise if coverage times out on a large library
```

The PDF timeout is worth understanding: it guards against a malformed file
hanging the worker, and it used to be 90 seconds — tuned for a 40 page cap.
Reading every page of a 300 page filing legitimately takes longer, and a stale
timeout would have turned "unlimited" into "nothing indexed at all".

## Tests

| File | Pins |
| --- | --- |
| `backend/test_ingestion_limits.py` | The no-truncation contract: unlimited defaults, no hard ceilings, Workspace export formats, API ceilings not undercutting the indexer |
| `backend/test_office_extract.py` | The OOXML parsers, against hand-built archives |
| `backend/test_drive_coverage.py` | Classification, exact vs estimated percentages, the arithmetic behind the missing-tail estimate |

`test_ingestion_limits.py` is the one that matters most. It exists so that a
future change — by a person or by the self-build agent — has to break the
no-truncation promise on purpose rather than by accident.
