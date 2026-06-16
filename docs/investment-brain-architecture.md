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
Local Brain Indexer on your computer
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

So the dashboard should not directly fetch random local files. Instead, a local indexer should watch an approved folder, process the files, and upload structured/searchable outputs to the brain database.

Example watched folder:

```text
G:/My Drive/Investment Brain/
```

Google Drive for desktop should keep this folder available offline or mirrored locally, so the indexer sees real files rather than placeholders.

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

The current dashboard has the first version of the Investment Brain page and a SQLite-backed backend memory/search API.

Current capability:

- manual memories
- memory types: liked, passed, megatrend, framework, question
- source ingestion through `POST /api/brain/ingest/text`
- deterministic chunking with stable content hashes
- searchable `chunks` table prepared for future embeddings
- SQLite FTS keyword search
- local browser fallback
- Vercel frontend routing

Current limitations:

- no PDF upload yet
- no local folder indexer yet
- no embeddings yet
- no Postgres/pgvector yet
- SQLite on Render is not enough for permanent production memory unless backed by persistent disk

Current API spine:

```text
GET    /api/brain/status
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

1. Add Postgres connection support in the backend.
2. Add pgvector tables for chunks and embeddings.
3. Add a sources and chunks ingestion API.
4. Build a local Brain Indexer that watches the Google Drive folder.
5. Extract PDF text and page references.
6. Add file and chunk hashes so re-indexing is incremental.
7. Generate summaries and embeddings through an AI API.
8. Add source citation views in the dashboard.
9. Add why-I-liked / why-I-passed / why-I-sold company memory.
10. Add backups and export tools.

## Principle

The brain should never be just a chatbot. It should be a durable investing memory system:

- source-backed
- searchable
- personal
- auditable
- rebuildable
- portable
