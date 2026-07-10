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

## Product Shape: A Research Conversation, Not a Control Panel

The primary interface should be one persistent research thread. The analyst asks a question, sees the conclusion, opens the exact evidence used, and follows up without having to rebuild the context each time.

```text
Question
-> retrieve evidence by meaning and exact terms
-> expand the strongest relevant files around the matches
-> produce an attributable answer
-> show sources directly beneath that answer
-> continue the same line of work
```

The dashboard should keep Drive connection, sync, embedding coverage, source search, and source acquisition in a compact library rail. Those are important operations, but they should not compete with the research conversation.

The chat-first interface now follows this shape:

- one composer with a ticker and a question
- threaded follow-ups that receive fresh retrieval, not only chat history
- source cards beneath each answer, with direct Drive/source links where available
- a compact library rail for status, search, Drive sync, embedding backfill, and official-source acquisition
- source acquisition stays separate from analysis: acquire -> index -> embed -> ask

### Persistent Reference Layer

The analyst can select up to six indexed Drive sources as a standing reference layer. This is for durable frameworks, books, long-running theses, and mental models that should shape the reasoning across every company question.

```text
Selected Drive files
        |
        v
Stored once in Brain settings
        |
        v
For every question, retrieve one relevant passage per selected file
        |
        v
Add a bounded framework layer to the model context
```

The Brain does not paste entire books into every prompt. Each selected source contributes one semantically relevant passage; if its embedding is unavailable, it falls back to an anchor passage. This keeps the reference layer useful, attributable, and fast.

Reference sources are lenses, not automatic evidence about a company. The model is instructed to label them as `[R1]`, `[R2]`, and so on when they materially influence the reasoning, and to surface tension between the framework and current company-specific evidence.

### Editable System Prompt

The Brain also has one persistent, editable system prompt. It is stored in the Brain settings database and sent to Gemini through its native `systemInstruction` field for every answer. This is where the investor defines the analytical posture, writing style, skepticism, preferred decision framework, and how strongly the model should challenge a thesis.

```text
System prompt                 -> how the Brain reasons and communicates
Persistent reference sources  -> the frameworks available in its context
Retrieved company evidence    -> the facts relevant to the current question
Conversation thread           -> what has already been discussed
```

The system prompt should define behavior, not duplicate large source material. Put books, frameworks, and durable research in the reference layer so they remain attributable and can supply query-relevant passages.

### What Retrieval Does Today

The answer endpoint uses hybrid retrieval instead of treating vector and keyword search as mutually exclusive:

```text
query embedding -> pgvector semantic candidates
query terms     -> Postgres full-text candidates
                         \ /
              reciprocal-rank fusion
                         |
             top evidence passages
                         |
        expand the two strongest source files
                         |
                 Gemini answer + citations
```

Reciprocal-rank fusion matters because it does not compare incompatible vector and full-text scores. A passage ranked highly by both methods gets a meaningful boost; an exact filing reference is not discarded merely because vector search returned broader thematic material.

The source expansion step now reads nearby chunks from the two strongest files rather than answering from one isolated snippet. It is deliberately bounded so a normal question remains fast and the answer stays auditable.

## Better Brain Roadmap

The next architecture should be built as five explicit layers. The goal is to make the system increasingly useful without turning it into an opaque autonomous trader.

### 1. Research Coordinator

This is the chat-facing layer. It decides which read-only tools to use for a question and reports what it did.

```text
Classify question
-> resolve company / issuer / ticker
-> retrieve documents, frameworks, and prior decisions
-> decide whether a deep-file read is warranted
-> answer with confidence, evidence, and open questions
```

It should expose a small, human-readable activity line in the thread, such as:

```text
Semantic search: 8 passages
Exact search: 4 passages
Read deeply: 2 files
Answer based on: 5 cited sources
```

Do not make the model silently choose a financial conclusion. Its job is to assemble evidence, explain the inference, identify contradiction, and say what is missing.

### 2. Research Index

The index should become source-aware rather than only chunk-aware.

```text
Source record
  -> document summary
  -> section/chapter summaries
  -> passages/chunks
  -> embeddings
  -> entities, dates, tickers, filing period, author, source quality
```

Next data additions:

- source-level summaries to improve ranking and browsing
- page and section anchors for PDFs, not just chunk ordinals
- OCR status and extraction quality for scanned files
- normalized company/ticker/entity tables so `META`, Meta Platforms, and historical names resolve together
- document version and file hash history, so an updated filing or note is traceable
- embedding model/version stored per passage, allowing re-indexing without ambiguity

For large libraries, continue doing extraction and embedding on the local worker, with Supabase as the shared retrieval index. Render should answer questions and run small agent jobs, not parse a large book library in memory.

### 3. Retrieval Planner

Hybrid retrieval is the first step. The next planner should use several cheap passes before a deep read:

```text
company/entity match
-> recency and source-quality filters
-> semantic + keyword ranking
-> rerank top 20 passages
-> select 2-4 source files for deeper reading
-> assemble a bounded evidence pack
```

Useful ranking signals:

- direct ticker/company match
- official filing or primary source over commentary
- document date and reporting period
- semantic relevance
- exact term relevance
- whether the passage supports or contradicts the current thesis
- your own source-quality rating

Add a reranker only after source coverage is strong. It is a quality improvement, not a substitute for complete and well-provenanced data.

### 4. Investment Log

The old free-form “memory” screen should not return. Replace it with a deliberate, auditable investment log that the chat can create from a conversation when you approve it.

Each record should answer one specific question:

```text
Company / theme
Decision: liked, passed, bought, reduced, sold, monitoring
Why now
Key assumptions
Disconfirming evidence
What changes my mind
Evidence links
Decision date and effective portfolio date
```

This makes the second brain personal without creating a vague bucket of notes. Later, the chat can answer: “Why did I pass on this in 2025?” or “Which assumptions have changed since I added the position?” and cite both the old decision and the new evidence.

### 5. Acquisition Agent

The current agent can find official SEC material and import a public URL. Build outward from a strict plan-and-confirm model:

```text
task -> proposed sources -> user approves import -> Drive -> index -> embeddings -> available in chat
```

Priority connectors, in order:

1. SEC/EDGAR filings and earnings exhibits
2. company investor-relations pages, allowlisted per company/domain
3. earnings-call transcripts only where the license permits storage
4. trusted web research with provenance and a visible source-quality label

Every acquired item needs the original URL, retrieval date, hash, Drive link, source type, and import status. The agent should not overwrite your Drive organisation or store a copyrighted third-party source unless its terms allow it.

## What Not To Add Yet

- autonomous trading or portfolio changes
- automatic “memories” inferred from every chat answer
- broad web crawling without domain, licensing, and provenance controls
- a large multi-agent framework before retrieval quality and the investment log are reliable

Those features create a lot of motion but little trustworthy investing edge. The order should be: high-quality sources -> retrieval -> transparent reasoning -> decision history -> carefully scoped acquisition agents.

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

## Preferred Self-Use Build: Local Brain Worker

For this project, the best near-term architecture is the local worker path:

```text
Google Drive synced folder on local PC
        |
        v
backend/local_brain_worker.py
        |
        v
Extract text, chunk, hash, embed
        |
        v
Supabase Postgres + pgvector
        |
        v
Render API + Vercel dashboard
```

This is better than asking Render to parse the library because Render memory is limited and PDF extraction can use far more RAM than the file size suggests. The local PC can do the heavy ingestion work, while Render remains a lightweight search and analysis API.

Runbook:

```powershell
Copy-Item backend\.env.local-brain.example backend\.env
python -m pip install -r backend\requirements.txt
.\run_local_brain_worker.ps1 -Mode status
.\run_local_brain_worker.ps1 -Mode all
```

Detailed instructions are in:

```text
docs/local-brain-worker.md
```

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

## Research Agent Layer

The Brain now has the first source-acquisition agent. This is separate from Ask Brain:

```text
Acquire source -> save source -> index chunks -> embed -> retrieve -> analyze
```

Current agent abilities:

- paste a public URL and import it into the Brain
- upload the imported document into Google Drive under `Agent Downloads`
- extract text, chunk it, and upsert it into Supabase/Postgres
- queue embedding backfill after import
- find official SEC candidates for public-company result/filing tasks
- run a first guarded loop that imports the top trusted official source

Guardrails:

- only public `http` and `https` URLs are downloadable
- private, loopback, local, multicast, and reserved network addresses are rejected
- the official-source path is allowlisted to SEC domains
- repeated imports use stable URL/file hashes so unchanged sources are skipped
- changed sources replace prior chunks for the same file identity rather than double-counting

Near-term v2 architecture should split the Brain into four lanes:

```text
1. Source acquisition
   URL import, official filing finder, Drive upload, provenance log

2. Indexing and embedding
   extraction, chunking, summaries, pgvector embeddings, source hashes

3. Retrieval planner
   semantic search, keyword fallback, source expansion, full-file deep dives

4. Decision memory
   why liked / passed / sold, what changed, assumptions, links to evidence
```

The agent should remain auditable: every downloaded source needs an original URL, Drive link when available, timestamp, file hash, chunks, and source cards in the UI.

## Current App State

The current dashboard has the first version of the Investment Brain page with local SQLite fallback and production Postgres/pgvector storage.

Current capability:

- manual memories
- memory types: liked, passed, megatrend, framework, question
- source ingestion through `POST /api/brain/ingest/text`
- Google Drive API folder indexing through `POST /api/brain/index/drive`
- Google Drive OAuth connection through `GET /api/brain/drive/auth-url`
- Research Agent URL import through `POST /api/brain/agent/import-url`
- Official SEC source discovery through `POST /api/brain/agent/find-official-sources`
- guarded source import loop through `POST /api/brain/agent/run`
- deterministic chunking with stable content hashes
- idempotent Drive indexing using stable Drive file IDs and revision hashes
- idempotent agent imports using stable source URL and file hashes
- Drive/API extraction for txt, md, csv, json, html, docx, Google Docs/Sheets/Slides exports, and pdf when `pypdf` is installed
- searchable `chunks` table with embedding backfill
- Gemini API client through `GOOGLE_AI_API_KEY` or `GEMINI_API_KEY`
- embedding backfill through `POST /api/brain/embeddings/backfill`
- SQLite-based cosine semantic search for embedded chunks
- company analysis through `POST /api/brain/analyze-company`
- SQLite FTS keyword search
- production Postgres/pgvector storage when `DATABASE_URL` or `BRAIN_DATABASE_URL` is configured
- standalone local Brain Worker through `backend/local_brain_worker.py`
- Windows launcher through `run_local_brain_worker.ps1`
- Vercel frontend routing

Current limitations:

- no browser-side PDF upload yet
- Drive scanning is manual from the dashboard unless a scheduled Render job is added later
- the Research Agent currently starts with SEC official sources; broader web search should be added behind trusted-domain guardrails
- embeddings require a Google AI Studio API key and an explicit backfill run
- Supabase/Postgres requires a private database connection string, not only the public Supabase project URL
- local folder indexing is disabled by default; the cloud backend should read Google Drive through the Drive API, not files from your personal computer
- the local worker can index local synced Drive files into Supabase, but the cloud dashboard cannot directly open arbitrary local files from your PC

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

Agent source import requires the Drive OAuth token to include read access and `https://www.googleapis.com/auth/drive.file`. Reconnect Drive once after this feature is deployed if the previous token was read-only.

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
GET    /api/brain/references
PUT    /api/brain/references
GET    /api/brain/system-prompt
PUT    /api/brain/system-prompt
POST   /api/brain/agent/import-url
POST   /api/brain/agent/find-official-sources
POST   /api/brain/agent/run
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
