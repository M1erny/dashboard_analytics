# Investment Brain Architecture Notes

These notes capture the long-term direction for the synthetic investment brain: a system that can read your books, PDFs, frameworks, company notes, decisions, and world-model assumptions, then use them as context when analyzing companies.

## North Star

Build a durable memory layer for investing that understands:

- why a company was liked, passed, bought, sold, or paused
- your long-running beliefs and megatrends, such as urbanization
- your frameworks for management quality, moats, incentives, capital allocation, valuation, and risk
- source evidence from books, PDFs, filings, notes, and research
- your personal style of reasoning, not just generic AI output

The system should become a retrievable context engine for company analysis.

## Preferred Hybrid Architecture

Use a hybrid setup rather than trying to store everything inside Vercel, Render, or the browser.

```text
Google Drive synced folder / local archive
        |
        v
Google Drive API indexer or local Brain Indexer
        |
        v
Text extraction, OCR, chunking, hashes, summaries, embeddings
        |
        v
Postgres + pgvector brain database
        |
        v
Render backend API
        |
        v
Vercel dashboard
```

Why this is the best middle path:

- raw files can stay in Google Drive and on your own computer
- the dashboard stays available in the cloud
- search is fast because the app queries an index, not raw PDFs every time
- the original files remain rebuildable source material
- the setup can scale toward 1TB+ without putting giant files in a database
- it avoids depending on only one provider for lifelong memory

## Important Browser Limitation

A normal cloud website cannot freely read files from your computer. Browser security blocks that.

So the dashboard should not directly fetch random local files. The intended production path is:

```text
Google Drive folder -> Drive API -> Render backend -> Supabase/Postgres + pgvector
```

Local folder indexing is disabled by default and should be treated only as an explicit development escape hatch.
The Brain frontend defaults to the Render backend unless `VITE_BRAIN_API_URL` or `VITE_API_URL` is explicitly set.

## What The Brain Indexer Creates

The indexer should not send only a short description to AI. It should create multiple layers.

```text
PDF / book / note
-> extracted raw text
-> chunks
-> summaries
-> embeddings / vectors
-> metadata
-> personal memory links
```

### Raw Text

The exact extracted text from the file. This is the source of truth and should be preserved where practical.

### Chunks

Smaller text units, usually around 500 to 1,500 tokens. The AI should not read a whole book for every question. It should retrieve the few most relevant chunks.

### Embeddings / Vectors

Embeddings are numerical fingerprints of meaning. They let the system find relevant ideas even when the question uses different words.

Example:

```text
Query: "long-term city infrastructure winners"
Relevant chunk: "urbanization increases demand for elevators, utilities, transit, logistics, and energy resilience"
```

Vectors are for retrieval, not for final reasoning by themselves.

### Summaries

Summaries should exist at multiple levels:

- file summary
- chapter or section summary
- chunk summary
- investment relevance summary

Summaries help browsing, ranking, and fast context building.

### Metadata

Every chunk should carry source metadata.

```text
source_file: "Poor Charlie's Almanack.pdf"
page: 52
author: "Charlie Munger"
topic: "incentives"
tags: ["mental-models", "management", "behavior"]
hash: "stable file/chunk hash"
created_at: timestamp
```

Metadata makes the brain auditable and lets the dashboard cite sources.

### Personal Memory Links

This is the most important layer for making the system yours.

Examples:

```text
This supports my urbanization megatrend.
This connects to why I passed Company X.
This belongs to my management quality framework.
This changes how I think about capital intensity.
```

The system should connect source knowledge to your actual investment decisions.

## Storage Plan For 1TB+

Do not put original PDFs/books/files directly in Postgres, Render, or Vercel.

Recommended split:

```text
Original files -> Google Drive, local SSD/NAS, optional object storage backup
Extracted text -> object storage or database, depending on size
Chunks -> Postgres
Embeddings -> Postgres + pgvector
Memories/decisions -> Postgres
Source metadata -> Postgres
Cold backups -> Backblaze B2, Cloudflare R2, S3 Glacier, or local drives
```

For "memory for life", keep more than one copy:

- Google Drive copy
- local SSD or NAS copy
- database backups
- optional cold cloud backup

No single provider should be the only copy of the brain.

## Company Analysis Flow

When analyzing a company, the brain should:

```text
Company / ticker / question
-> retrieve relevant manual memories
-> retrieve relevant source chunks by vector search
-> retrieve relevant frameworks and megatrends
-> retrieve previous decisions about similar companies
-> assemble a context pack
-> ask AI to analyze using that context
-> save the new decision and reasoning back into memory
```

The final output should include:

- thesis
- anti-thesis
- key assumptions
- relevant sources
- valuation considerations
- risks
- what would change the mind
- why the company was liked, passed, or monitored

## Current App State

The current dashboard has the first version of the Investment Brain page with local SQLite fallback and production Postgres/pgvector storage.

Current capability:

- manual memories
- memory types: liked, passed, megatrend, framework, question
- source ingestion through `POST /api/brain/ingest/text`
- Google Drive API folder indexing through `POST /api/brain/index/drive`
- Google Drive OAuth connection through `GET /api/brain/drive/auth-url`
- deterministic chunking with stable content hashes
- idempotent Drive indexing using stable Drive file IDs and revision hashes
- Drive/API extraction for txt, md, csv, json, html, docx, Google Docs/Sheets/Slides exports, and pdf when `pypdf` is installed
- searchable `chunks` table with embedding backfill
- Gemini API client through `GOOGLE_AI_API_KEY` or `GEMINI_API_KEY`
- embedding backfill through `POST /api/brain/embeddings/backfill`
- SQLite-based cosine semantic search for embedded chunks
- company analysis through `POST /api/brain/analyze-company`
- SQLite FTS keyword search
- production Postgres/pgvector storage when `DATABASE_URL` or `BRAIN_DATABASE_URL` is configured
- Vercel frontend routing

Current limitations:

- no browser-side PDF upload yet
- Drive scanning is manual from the dashboard unless a scheduled Render job is added later
- embeddings require a Google AI Studio API key and an explicit backfill run
- Supabase/Postgres requires a private database connection string, not only the public Supabase project URL
- local folder indexing is disabled by default; the cloud backend should read Google Drive through the Drive API, not files from your personal computer

## Google Drive API Store

The configured Drive folder is:

```text
https://drive.google.com/drive/folders/1DkFRs5oCdPt8j-3Z-vfR8BnG4y8Eqdc5
```

Render environment variables:

```text
GOOGLE_DRIVE_FOLDER_ID=1DkFRs5oCdPt8j-3Z-vfR8BnG4y8Eqdc5
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_OAUTH_REDIRECT_URI=https://dashboard-eo6k.onrender.com/api/brain/drive/oauth/callback
```

Optional unattended sync:

```text
GOOGLE_DRIVE_REFRESH_TOKEN=...
```

If `GOOGLE_DRIVE_REFRESH_TOKEN` is omitted, the dashboard can open the OAuth consent URL and save the refresh token into the brain database after approval.

Drive sync stores:

- Drive file ID, name, relative path, MIME type, modified time, and web link
- extracted text preview in `sources`
- chunked full text in `chunks`
- stable chunk hashes for idempotent re-indexing
- embeddings after `POST /api/brain/embeddings/backfill`

Raw PDFs/books remain in Google Drive. The database stores metadata, extracted text, chunks, and embeddings.

## Supabase Production Store

The current Supabase project URL is:

```text
https://narvifqyqcsukuavyoik.supabase.co
```

That URL is public routing information. The backend needs the private Postgres connection string in Render:

```text
DATABASE_URL=postgresql://...
```

When `DATABASE_URL` or `BRAIN_DATABASE_URL` is present, the Render backend uses Postgres/pgvector as the brain store. Without it, the backend falls back to local SQLite for development.

The production store creates and uses:

- `memories` for manual decisions, passes, likes, frameworks, and trends
- `sources` for files, books, notes, and extracted source records
- `chunks` for searchable text pieces and `vector(3072)` Gemini embeddings
- `brain_index` for Postgres full-text keyword search
- pgvector cosine search for semantic retrieval

Schema file:

```text
backend/migrations/001_supabase_brain_pgvector.sql
```

Current API spine:

```text
GET    /api/brain/status
GET    /api/brain/index/drive/status
GET    /api/brain/drive/auth-url
GET    /api/brain/drive/oauth/callback
POST   /api/brain/index/drive
GET    /api/brain/llm/status
POST   /api/brain/embeddings/backfill
GET    /api/brain/search/semantic
POST   /api/brain/analyze-company
POST   /api/brain/memories
GET    /api/brain/memories
DELETE /api/brain/memories/:id
POST   /api/brain/sources
GET    /api/brain/sources
DELETE /api/brain/sources/:id
POST   /api/brain/ingest/text
POST   /api/brain/sources/:id/chunks
GET    /api/brain/chunks
GET    /api/brain/sources/:id/chunks
GET    /api/brain/search
```

## Next Build Steps

1. Add scheduled Drive sync or a queue worker.
2. Improve PDF page references and add OCR for scanned documents.
3. Add source-level summaries and memory extraction through the Gemini API.
4. Add source citation views in the dashboard.
5. Add why-I-liked / why-I-passed / why-I-sold company memory.
6. Add backups and export tools.

## Principle

The brain should never be just a chatbot. It should be a durable investing memory system:

- source-backed
- searchable
- personal
- auditable
- rebuildable
- portable
