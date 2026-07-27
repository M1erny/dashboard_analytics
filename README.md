# Institutional Portfolio Dashboard

Private portfolio analytics dashboard with a Python/FastAPI backend, a React/Vite frontend, and an Investment Brain powered by Google Drive, Supabase Postgres, pgvector, and Gemini.

The dashboard is built for one main job: show portfolio performance, risk, exposure, attribution, rebalancing continuity, and source-backed investment research in one place.

## What It Does

- Tracks realised long/short portfolio performance in USD.
- Calculates YTD return, alpha, beta, volatility, drawdown, Sharpe, correlations, VaR/CVaR, and stress results.
- Preserves portfolio continuity across rebalances, so old and new position periods remain part of YTD history.
- Reconciles gross security contribution, estimated financing impact, and net realised return.
- Provides portfolio exports and investor-facing PNG/report views.
- Includes an Investment Brain for semantic search and company analysis over your own files.

## Architecture

```text
React / Vite dashboard
        |
        v
FastAPI backend on Render
        |
        +--> portfolio analytics / yfinance / risk engine
        |
        +--> Investment Brain API
                 |
                 +--> Google Drive API for source files
                 +--> Supabase Postgres + pgvector for text chunks and embeddings
                 +--> Gemini for embeddings and analysis
                 +--> Research Agent for trusted source acquisition
```

The browser does not read arbitrary files from your computer. Production Brain data comes from Google Drive through the Drive API, then lands in Supabase as metadata, extracted text chunks, and embeddings.

## Tech Stack

Backend:

- Python 3.12+
- FastAPI
- pandas, numpy, scipy, yfinance
- psycopg, pgvector on Supabase
- Google Drive API
- Google AI Studio / Gemini

Frontend:

- React 19
- TypeScript
- Vite
- TailwindCSS
- Recharts
- Lucide React

## Local Setup

Install backend dependencies:

```powershell
cd backend
python -m pip install -r requirements.txt
cd ..
```

Install frontend dependencies:

```powershell
npm install
```

Run backend:

```powershell
cd backend
python server.py
```

Run frontend:

```powershell
npm run dev
```

Open:

```text
http://127.0.0.1:5176
```

The Vite dev server proxies `/api` to the local backend at `http://127.0.0.1:8000`.

## Environment Variables

Do not commit secrets. Put local secrets in `backend/.env`; that file is ignored by git.

Minimum Brain variables:

```text
DATABASE_URL=postgresql://...
GOOGLE_AI_API_KEY=...
GOOGLE_DRIVE_FOLDER_ID=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_OAUTH_REDIRECT_URI=https://dashboard-eo6k.onrender.com/api/brain/drive/oauth/callback
```

Optional Brain variables:

```text
BRAIN_LLM_MODEL=gemini-3.5-flash-lite
BRAIN_LLM_THINKING_LEVEL=minimal
BRAIN_EMBEDDING_MODEL=gemini-embedding-001
GOOGLE_DRIVE_REFRESH_TOKEN=...
BRAIN_SEARCH_TIMEOUT_SECONDS=18
BRAIN_SEMANTIC_MIN_SCORE=0.66
BRAIN_ANALYSIS_TIMEOUT_SECONDS=24
BRAIN_DEEP_SOURCE_FILES=3
BRAIN_EMBEDDING_TIMEOUT_SECONDS=15
BRAIN_INDEX_TIMEOUT_SECONDS=240
BRAIN_FULL_CONTEXT_MAX_CHARS_PER_SOURCE=250000
BRAIN_FULL_CONTEXT_TOTAL_MAX_CHARS=800000
BRAIN_FULL_CONTEXT_GENERATION_TIMEOUT_SECONDS=45
BRAIN_CONVERSATION_SAVE_TIMEOUT_SECONDS=25
BRAIN_AGENT_USER_AGENT=InvestmentBrainResearchAgent/1.0; your-email@example.com
```

Frontend override for development:

```text
VITE_BRAIN_API_URL=http://127.0.0.1:8000
```

Without `VITE_BRAIN_API_URL`, the Brain frontend can default to the hosted Render backend so localhost still uses the production Drive/Supabase setup.

### Model Selection

The Brain generates with **Gemini 3.5 Flash-Lite** and embeds with **gemini-embedding-001**.

Flash-Lite is the deliberate default rather than a cost compromise. Retrieval does the heavy lifting before the model is called: hybrid search, deep source expansion, the pinned reference layer, and the live portfolio context all arrive pre-assembled and pre-ranked. What is left is disciplined writing over supplied evidence, and a fast model keeps the ask/answer loop short enough to iterate on.

- `BRAIN_LLM_MODEL` selects the generation model. `gemini-3.5-flash` is the drop-in upgrade for questions that need more reasoning than speed.
- `BRAIN_LLM_THINKING_LEVEL` accepts `minimal`, `low`, `medium`, or `high`, and applies only to `gemini-3.5*` models. An unrecognized value falls back to `minimal`. Higher levels reason longer and draw on the output allowance, so raise `BRAIN_ANALYSIS_TIMEOUT_SECONDS` alongside them.
- `BRAIN_LLM_THINKING_BUDGET` is the older numeric-budget form, used only for non-3.5 models. It is inert while a `gemini-3.5*` model is selected.
- If Google rejects the thinking configuration, the request is retried once without it. An unsupported model or level degrades to a plain call instead of failing the answer.
- `BRAIN_EMBEDDING_MODEL` should be treated as fixed. Vectors from different embedding models are not comparable, so changing it invalidates the library and requires a full backfill with `force=true`.

Generation timeouts do not come from the Gemini client. `BRAIN_ANALYSIS_TIMEOUT_SECONDS` governs normal answers and `BRAIN_FULL_CONTEXT_GENERATION_TIMEOUT_SECONDS` governs answers with pinned full documents.

### Retrieval And Answer Tuning

`BRAIN_SEMANTIC_MIN_SCORE` rejects weak nearest-neighbor matches before they enter an answer. Keep the default unless retrieval diagnostics show a consistent false-negative or false-positive pattern; exact keyword search remains active either way.

If the floor rejects everything *and* exact search also finds nothing, the Brain does not answer from an empty context. It keeps the closest few passages, labels them in the prompt as below the confidence floor, and instructs the model to state the evidence gap before interpreting anything. The count is reported as `retrieval.weakSemanticFallback`, and the chat flags the answer as an evidence gap rather than a finding.

`BRAIN_ANALYSIS_TIMEOUT_SECONDS` is a ceiling on the model's writing window, not an added delay — a fast answer still returns immediately. It is bounded to 5-60s and applies only when no full-document sources are pinned.

`BRAIN_DEEP_SOURCE_FILES` (1-5) sets how many distinct files are read around the strongest semantic hits. Each extra file costs one serialized Supabase round trip.

## Cache Behavior

The dashboard uses short-lived caches for responsiveness without treating cached market or research data as permanent truth:

- Portfolio metrics and raw market inputs are cached in the backend for five minutes per portfolio/cost tier. `force=true` refreshes them immediately.
- Brain status is cached for 15 seconds to avoid repeatedly querying Supabase while the page loads.
- The Brain keeps a small versioned in-memory cache of reconstructed pinned documents. A source update changes the cache key, so new indexing invalidates the relevant document automatically.
- The Brain page restores its last healthy status, Drive connection, pinned sources, and system prompt from browser session storage for up to 15 minutes, then refreshes from the backend in the background.

These are performance caches only. Supabase remains the durable source of Brain data, and a Render restart simply starts the in-memory caches fresh.

## Investment Brain

The Brain is a retrieval system, not just a chatbot.

Current flow:

```text
Google Drive file
-> Drive API indexer
-> extracted text
-> chunks with stable hashes
-> Gemini embeddings
-> Supabase Postgres + pgvector
-> semantic search / source expansion
-> Gemini company analysis
```

Portfolio-aware question routing:

```text
Question
-> deterministic market-data intent check
-> research/framework question: dated target-book outline only (no Yahoo refresh)
-> momentum/volume/performance/risk/action question: shared live dashboard metrics
-> Gemini receives clearly separated security returns, side-adjusted momentum,
   realised contribution, completed-session volume diagnostics, and Drive evidence
```

Agent acquisition flow:

```text
URL or official-source task
-> guarded public download
-> text extraction and canonical Markdown conversion
-> optional Markdown upload into Agent Downloads
-> chunking
-> Supabase source/chunk upsert
-> embedding backfill queue
```

Main Brain capabilities:

- Chat-first research threads with follow-up context and attached source evidence.
- Hybrid company retrieval: pgvector semantic search plus full-text exact search, fused before analysis.
- Deep source expansion around the strongest matched passages before Gemini answers.
- Explicit weak-evidence handling: when nothing clears the relevance floor, the answer reports the gap instead of manufacturing confidence.
- Persistent reference layer: select up to six indexed Drive sources that supply a relevant framework passage to every answer.
- Full-document context: select up to four indexed files whose entire extracted text is included in every answer, with explicit per-file and total context caps.
- Editable system prompt stored with the Brain and sent to Gemini as a native system instruction.
- Google Drive OAuth connection.
- Drive folder sync.
- Research Agent URL import into Drive + Supabase, with HTML/PDF/DOCX content normalized to an auditable Markdown source before Drive upload.
- Official SEC source finder for public-company filings and earnings exhibits.
- PDF, DOCX, Google Docs/Sheets/Slides exports, TXT, Markdown, CSV, JSON, and HTML extraction.
- Chunk storage with stable file and chunk hashes.
- Full-text keyword search.
- pgvector cosine semantic search.
- Source-backed Ask Brain company analysis.
- Question-routed portfolio context: the target book is always known, while Yahoo market data is fetched only for questions that require it.
- Completed-session volume/momentum screen with relative volume, abnormal-volume z-score, adverse/favourable-day volume, OBV pressure, dollar liquidity, trend, acceleration, and explicit long/short handling.
- Separate rankings for raw calendar-YTD security return, side-adjusted return, realised YTD contribution, and contribution since the latest rebalance.
- Follow-up questions in the same Brain thread.
- Automatic Google Drive transcript saving after every completed exchange.
- Source references when Drive metadata is available.

### Durable conversation transcripts

Each browser thread receives a stable ID. After Gemini completes an exchange, the backend creates or updates one file under:

```text
GOOGLE_DRIVE_FOLDER_ID/Investment Brain/Conversations/
```

The file is Markdown with Obsidian-compatible YAML front matter. Every exchange contains the readable user/assistant transcript, direct source links, model and embedding names, the system-prompt hash and deduplicated snapshot, portfolio market date, retrieval diagnostics, and a JSON context manifest for future analytics. Retrieved passages are retained in the manifest with bounded text fields; complete books and reports stay canonical in their original Drive files and are referenced by source/file ID instead of being copied into every conversation.

Conversation files are deliberately excluded from the Drive retrieval index. This prevents the Brain from treating its previous generated answers as independent research evidence and creating a self-reinforcing retrieval loop.

`threadId` keeps follow-ups in one file and `exchangeId` makes retries idempotent. Autosave failures never discard the answer: the API returns an `autosave` status and the Brain UI shows either a direct Drive link or an actionable failure state. A single transcript is capped at 25 MB so a runaway thread cannot exhaust Drive or Render memory.

The **Saved threads** panel lists these Drive transcripts and can reconstruct a thread from its exchange manifests. Resuming restores the prior user/assistant messages as conversational context; new questions rerun retrieval against the current indexed research instead of treating old AI output as source evidence.

Useful endpoints:

```text
GET  /api/brain/status
GET  /api/brain/index/drive/status
GET  /api/brain/index/drive/files
POST /api/brain/index/drive/start
GET  /api/brain/embeddings/status
POST /api/brain/embeddings/backfill
POST /api/brain/embeddings/backfill/start
GET  /api/brain/search
GET  /api/brain/search/semantic
POST /api/brain/analyze-company
GET  /api/brain/portfolio-outline
GET  /api/brain/portfolio-context
GET  /api/brain/references
PUT  /api/brain/references
GET  /api/brain/full-context
PUT  /api/brain/full-context
GET  /api/brain/system-prompt
PUT  /api/brain/system-prompt
GET  /api/brain/conversations
GET  /api/brain/conversations/{thread_id}
POST /api/brain/agent/import-url
POST /api/brain/agent/find-official-sources
POST /api/brain/agent/run
```

The Research Agent needs Google Drive OAuth with both read and `drive.file` write permission. If Drive was connected before agent import existed, reconnect Drive once from the Brain page so Google grants the new write scope. If uploads fail during token refresh, remove stale `GOOGLE_DRIVE_REFRESH_TOKEN` / `GOOGLE_REFRESH_TOKEN` values from Render (they override the database-managed OAuth token), then reconnect using the same Google OAuth client ID, secret, and redirect URI.

Detailed architecture notes are in:

```text
docs/investment-brain-architecture.md
docs/local-brain-worker.md
```

## Supabase Security

The Brain tables live in the Supabase `public` schema, but browser clients should not access them directly.

Security migrations:

```text
backend/migrations/001_supabase_brain_pgvector.sql
backend/migrations/002_enable_brain_rls.sql
backend/migrations/003_add_missing_embedding_index.sql
```

Current security posture:

- Row-Level Security is enabled on all Brain tables.
- Public `anon` and `authenticated` table grants are revoked.
- The dashboard uses the Render backend, which connects through the private Postgres connection string.
- Do not expose `DATABASE_URL` or service credentials in the frontend.
- The Research Agent downloads only public HTTP(S) URLs and rejects private/local network addresses.

Brain tables:

```text
memories
sources
chunks
ideas
theses
edges
brain_settings
brain_index
```

Quick SQL audit:

```sql
SELECT c.relname, c.relrowsecurity
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname = 'public'
ORDER BY c.relname;
```

There should be no direct grants for `anon` or `authenticated`:

```sql
SELECT grantee, table_name, privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'public'
  AND grantee IN ('anon', 'authenticated');
```

## Local Brain Worker

For large libraries, use the local worker instead of asking Render to parse everything. This keeps heavy PDF extraction on your computer while still writing chunks and embeddings to Supabase.

```powershell
python -m pip install -r backend\requirements.txt
.\run_local_brain_worker.ps1 -Mode status
.\run_local_brain_worker.ps1 -Mode all
```

More detail:

```text
docs/local-brain-worker.md
```

## Performance Methodology

- Primary return, drawdown, beta, volatility, and alpha cards use the dated, rebalance-aware YTD net NAV path.
- Position attribution is deliberately gross security contribution; it reconciles to gross return, then estimated carry reconciles gross return to net return.
- Current weights and long/short exposure are drifted against estimated net NAV, so financing drag is reflected in the displayed leverage.
- The five-year current-book replay remains available as a labelled scenario. It is not represented as realised portfolio history.
- Financing is an estimate using segment-opening margin debt and mark-to-market short borrow. Broker cash, fees, and borrow ledgers are required for broker-exact NAV.

## Portfolio Data And Rebalancing

Portfolio state is stored in backend portfolio JSON/config files. The analytics engine is designed to preserve continuity:

- exited positions remain in historical contribution where relevant
- new positions start contributing from their effective date
- existing positions carry forward unless explicitly changed
- YTD metrics remain based on the full year path, not only the latest portfolio snapshot
- since-last-rebalance metrics are shown separately from YTD total contribution

This separation is important: changing the book should not erase what happened earlier in the year.

## Verification

Backend syntax check:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python -m py_compile backend\server.py backend\drive_indexer.py backend\brain_agent.py backend\brain_store.py backend\brain_store_postgres.py backend\gemini_client.py
```

Backend tests. These are plain assertion scripts, not pytest files, so each one is run directly and prints its own pass line:

```powershell
cd backend
$env:PYTHONIOENCODING='utf-8'
python test_brain_retrieval_edges.py
python test_brain_conversations.py
python test_brain_portfolio_context.py
python test_brain_agent_search.py
python test_brain_agent_markdown.py
python test_calculations.py
python test_rebalancing.py
python test_historical_diagnostics.py
python test_portfolio_history_guard.py
```

`PYTHONIOENCODING` matters: without it `test_calculations.py` exits non-zero on a `UnicodeEncodeError` while printing its results to a non-UTF-8 Windows console, which looks like a failing assertion but is not one.

Frontend build:

```powershell
npm run build
```

`npm run lint` reports pre-existing errors inside `dexter-agent/`, a separate sub-project. Only new entries under `src/` are regressions.

Brain health:

```text
GET https://dashboard-eo6k.onrender.com/api/brain/status
```

Expected healthy signs:

- `state` is `ready`
- `storage` is `postgres_pgvector`
- `vectorSearch` is `pgvector_cosine`
- `embeddings.missing` is `0` after backfill
- `embeddings.coverage` is `1.0` after backfill

## Deployment Notes

- Frontend is designed for Vercel.
- Backend is designed for Render.
- Supabase stores Brain metadata, text chunks, embeddings, and search indexes.
- Google Drive stores the original files.
- Original PDFs/books should not be stored directly in Postgres.

## License

Private / proprietary.
