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
- Lets the Brain write its own code: a plain-language request becomes a reviewed pull request.

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
                 +--> Self-Build Agent
                          |
                          +--> Gemini writes the code change
                          +--> GitHub API opens a pull request
                          +--> GitHub Actions gates it, you merge it
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
BRAIN_LLM_MODEL=gemini-3.7-flash
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
BRAIN_DRIVE_MAX_BYTES=67108864
BRAIN_DRIVE_MAX_PDF_PAGES=0
BRAIN_DRIVE_MAX_EXTRACTED_CHARS=0
BRAIN_PDF_EXTRACTION_TIMEOUT_SECONDS=600
```

`0` means unlimited for the two extraction limits, and it is the default. See [Ingestion Coverage](#ingestion-coverage).

Self-build variables, required only if you want the Brain to write its own code:

```text
BRAIN_GITHUB_TOKEN=github_pat_...
BRAIN_GITHUB_REPO=m1erny/dashboard_analytics
BRAIN_GITHUB_BASE_BRANCH=main
BRAIN_CODE_MODEL=gemini-3.7-flash
BRAIN_CODE_THINKING_LEVEL=high
BRAIN_CODE_MAX_OUTPUT_TOKENS=32000
BRAIN_CODE_TIMEOUT_SECONDS=240
BRAIN_CODE_CONTEXT_FILES=8
BRAIN_CODE_MAX_OPEN_PROPOSALS=5
BRAIN_CODE_ALLOW_DEPENDENCIES=false
BRAIN_CODE_ALLOW_SELF_EDIT=false
BRAIN_CODE_ALLOW_MERGE=false
```

The GitHub token must be fine-grained, scoped to this repository only, with Contents and Pull requests write access and nothing else. See [Self-Build](#self-build).

Frontend override for development:

```text
VITE_BRAIN_API_URL=http://127.0.0.1:8000
```

Without `VITE_BRAIN_API_URL`, the Brain frontend can default to the hosted Render backend so localhost still uses the production Drive/Supabase setup.

### Model Selection

The Brain generates with **Gemini 3.7 Flash** and embeds with **gemini-embedding-001**.

Retrieval does the heavy lifting before the model is called: hybrid search, deep source expansion, the pinned reference layer, and the live portfolio context all arrive pre-assembled and pre-ranked. What is left is disciplined writing over supplied evidence. 3.7 Flash brings a 1M-token input window, which is what the pinned full-document path wants, at a higher price and a higher floor on reasoning time than the Flash-Lite it replaced — see the cost note below.

- `BRAIN_LLM_MODEL` selects the generation model. `gemini-3.5-flash-lite` is the cheaper, faster fallback if answer latency matters more than depth.
- `BRAIN_LLM_THINKING_LEVEL` accepts `minimal`, `low`, `medium`, or `high`, and applies to any `gemini-3.*` model. An unrecognized value falls back to `minimal`. Higher levels reason longer and draw on the output allowance, so raise `BRAIN_ANALYSIS_TIMEOUT_SECONDS` alongside them.
- **3.7 Flash rejects `minimal`.** The client maps a `minimal` request onto `low` for models that do not accept it, so the setting stays meaningful across the family instead of failing validation. `/api/brain/llm/status` reports both the requested level and the one actually sent.
- `BRAIN_LLM_THINKING_BUDGET` is the older numeric-budget form, used only for pre-3.x models. It is inert while any `gemini-3.*` model is selected.
- **Cost.** 3.7 Flash is a paid tier above Flash-Lite: $0.75 per 1M input tokens and $3.75 per 1M output through 31 December 2026, doubling to $1.50 / $7.50 on 1 January 2027. That matters most on the full-document path, where `BRAIN_FULL_CONTEXT_TOTAL_MAX_CHARS` of 800,000 is roughly 200k input tokens — about $0.15 of input for a single question. Lower that cap, or keep fewer files pinned, if the bill is the constraint.
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

### Market data snapshot

Yahoo Finance throttles shared hosting IPs (HTTP 429), and Render's free tier restarts with an empty memory. So the market frames behind `/api/metrics` are also saved to Supabase as one compressed setting per portfolio (`market.snapshot.v1.<portfolio>`, about 1.4 MB), and every metrics response carries a `dataStatus` saying where its data came from:

- `source: "yahoo"` - this process fetched live.
- `source: "snapshot", stale: false` - served from a snapshot younger than `MARKET_SNAPSHOT_FRESH_SECONDS` (default 3 h); Yahoo was not called.
- `source: "snapshot", stale: true` - the live fetch failed and the last good frames were served instead.

The dashboard shows which of those three it is, without a click: a badge beside the update time in the header reads `Live`, `Snapshot <date>`, or `Snapshot <date> (behind)`, its hover text spells out the selection rule, and the status bar carries `LIVE` / `SNAP` / `BEHIND`.

Note that `stale: true` and "behind" are deliberately different questions. `stale` says only that the refresh failed; whether the *figures* are out of date depends on the newest market date they contain. Markets are shut most of the time, so a snapshot taken at the last close holds exactly what a successful fetch would have returned. The UI escalates to amber, and shows a banner, only when `asOf` is more than `CURRENT_WITHIN_DAYS` (4 calendar days, enough to span a long weekend) behind - that is, when whole sessions are missing. A failed refresh over current data is reported quietly in the badge's hover text instead.

When Yahoo throttles the host, the fetch stops at the first 429 and the host leaves Yahoo alone for `YF_RATE_LIMIT_COOLDOWN_SECONDS` (default 10 min) instead of retrying every ticker three times.

**Scheduled refresh.** `.github/workflows/market-snapshot.yml` runs `backend/refresh_market_snapshot.py` every two hours on weekdays from a GitHub runner and writes the snapshot to the same database, so the web host serves fresh data without calling Yahoo itself. It needs one repository secret: `DATABASE_URL`, the same Supabase connection string the backend uses on Render (Settings -> Secrets and variables -> Actions); the workflow passes `--require-remote` so a missing secret fails the run rather than writing to a runner's disk. Run the script by hand the same way, from `backend/`, to refresh the snapshot from your own machine; without `DATABASE_URL` it writes to the local SQLite store and says so. Trigger it once by hand from the Actions tab after adding the secret; the dashboard picks the snapshot up within five minutes.

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
GET  /api/brain/drive/coverage
POST /api/brain/drive/backfill-dates
GET  /api/brain/code/status
POST /api/brain/code/propose
GET  /api/brain/code/proposals
GET  /api/brain/code/proposals/{number}
POST /api/brain/code/proposals/{number}/merge
```

The Research Agent needs Google Drive OAuth with both read and `drive.file` write permission. If Drive was connected before agent import existed, reconnect Drive once from the Brain page so Google grants the new write scope. If uploads fail during token refresh, remove stale `GOOGLE_DRIVE_REFRESH_TOKEN` / `GOOGLE_REFRESH_TOKEN` values from Render (they override the database-managed OAuth token), then reconnect using the same Google OAuth client ID, secret, and redirect URI.

Detailed architecture notes are in:

```text
docs/investment-brain-architecture.md
docs/local-brain-worker.md
docs/brain-ui.md
docs/self-building-brain.md
docs/drive-ingestion-coverage.md
docs/period-book-analytics.md
docs/beta-correlation-and-backward-analysis.md
docs/benchmark-currency.md
docs/roadmap.md
```

## Ingestion Coverage

Extraction is unlimited by default. Previously a PDF was cut at page 40 and any file at 250,000 characters, and nothing said so — a truncated filing still answers questions, just from the fraction that fit. Both caps are gone, along with the hard ceilings that silently overruled the environment variables meant to raise them.

`.xlsx` and `.pptx` are now extracted, using only the standard library so `requirements.txt` stays untouched. Decks yield speaker notes as well as slide text.

Native Google files export differently as a result. **A Google Sheet exported as CSV contains only its first tab**, so Sheets now export as `.xlsx` and Slides as `.pptx` rather than plain text. If you keep multi-tab models in Drive, the Brain has only ever read their first sheet.

Still bounded: 64 MB per file, because the downloader holds the whole file in memory. Still missing: OCR, so a scan with no text layer yields nothing.

To measure what actually landed:

```text
GET /api/brain/drive/coverage
```

or the **Drive coverage** panel on the Brain page. It lists Drive live and joins it against the store, reporting exact percentages for files, PDF pages, and embedded chunks, plus an explicitly-labelled *estimate* for token volume — the size of a document never read can only be inferred from its byte count. Every file is classified, so the gap is itemised rather than assumed.

Files indexed under the old caps stay truncated until a forced re-sync: `POST /api/brain/index/drive/start {"force": true}`. Details, including how to get to 100%, are in `docs/drive-ingestion-coverage.md`.

### Searching files by date

`GET /api/brain/sources` filters and sorts indexed files by date, and the **Files by date** panel on the Brain page drives it:

```text
GET /api/brain/sources?dateField=uploaded&after=2026-01-01&before=2026-06-30&sort=oldest
```

Three dates answer different questions, and `dateField` picks which one you mean:

| `dateField` | Meaning |
| --- | --- |
| `uploaded` (default) | When the file appeared in Drive (`createdTime`) |
| `modified` | When it last changed (`modifiedTime`) |
| `indexed` | When the Brain read it |

`after` and `before` take `YYYY-MM-DD` or a full ISO timestamp. A bare date covers the whole day at both ends, so `before=2026-08-04` includes files uploaded during the 4th.

The folder crawl did not request `createdTime` until recently, so anything indexed before that has no upload date. Those files are excluded from a dated query rather than silently included, and the response says how many were left out. Fix it without a full re-sync:

```text
POST /api/brain/drive/backfill-dates
```

That lists Drive once and merges the dates into existing sources. No downloads, no re-extraction. The panel offers it as a button whenever undated files show up.

## Self-Build

The Brain can change this dashboard's own source. You describe a change on the Brain page, Gemini writes it, and it arrives as a pull request on GitHub with CI attached. Merging it is what makes the change live — that step is yours.

```text
Self-build panel  ->  POST /api/brain/code/propose
                            |
                            +--> read the repo through the GitHub API
                            +--> Gemini returns a schema-constrained change plan
                            +--> validate paths, sizes, secrets, edit anchors
                            +--> commit to brain/self-build/... and open a PR
                            |
                      GitHub Actions: tsc, eslint, vite build, backend tests
                            |
                      you review the diff and merge  ->  Vercel + Render redeploy
```

The running server never rewrites its own files. Render's disk is ephemeral, and a process that edits its own source in place leaves no audit trail and no way back. Every change goes through Git.

**Setup.** Create a fine-grained GitHub PAT scoped to this repository only, with Contents write and Pull requests write. Set `BRAIN_GITHUB_TOKEN` and `BRAIN_GITHUB_REPO` on Render, then reload the Brain page.

**The coding model is separate on purpose.** `BRAIN_LLM_MODEL` stays on Flash-Lite for research answers; `BRAIN_CODE_MODEL` should point at the strongest coding model your key can reach. Writing TypeScript that compiles is not the same task as writing prose over retrieved evidence.

**What it will not touch.** `backend/portfolios/**` (the accounting audit trail), `.github/**`, dependency manifests, build and deploy config, `AGENTS.md`, and its own guardrail modules. Per proposal: at most 12 files, 400 KB total, 5 open proposals at a time. Writes are scanned for keys, tokens, and passworded connection strings.

That allowlist stops one proposal from touching protected files. It is not a boundary against a determined model, because a merged pull request can change anything — including the allowlist. The real gate is that you merge. Read the diff.

**Preview first.** `openPullRequest: false` (the **Preview diff** button) runs the model and every validator but pushes nothing, so a bad plan costs seconds instead of repository noise.

**There is no auto-merge.** Everything needed for one is present, and it is deliberately not wired: `tsc` and the test suites catch broken code, not a widget that renders a plausible number computed the wrong way. On a portfolio dashboard a confidently wrong number is worse than a crash. `BRAIN_CODE_ALLOW_MERGE=true` adds a one-click merge button for green proposals, which keeps the click.

Full details, failure modes, and how to write requests that work: `docs/self-building-brain.md`.

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

## Book Analytics Over Time

The Book Analytics strip answers "best and worst in Q2" and any other window, not just year to date. Period buttons sit in the strip header.

It works because `calculate_segmented_ytd` already builds a cumulative per-ticker contribution matrix, chained across every rebalance snapshot and rebased at each seam onto one basis, so a window is a subtraction and quarters sum back to the year exactly. That matrix was computed on every request and discarded; nothing about how performance is calculated changed.

Three properties decide what the numbers mean, and all three are stated in the payload:

- **Windows are half-open.** A period is anchored on the last session *before* it opens. Anchoring Q2 on 1 April rather than 31 March silently discards 1 April's return.
- **Contributions are denominated in year-opening capital.** That is what makes windows additive; a Q3 figure reads "percent of January capital", not "percent return during Q3".
- **They are gross of financing**, so they reconcile to the gross YTD return, never the net one.

Concentration needed new state, since only current drifted weights were kept. The segment loop already computes `weight * relative_price` per position per date, which *is* the drifted weight, so `position_weight_history` captures it — a new output only, changing no existing calculation.

Standard windows (`ytd`, `qtd`, `mtd`, `sinceRebalance`, `q1`-`q4`, `h1`/`h2`, months, `r30d`, `r90d`) ride along with `/api/metrics`. Anything else:

```text
GET /api/book-analytics?period=custom&start=2026-05-04&end=2026-05-29
```

The position count changes between periods, which is correct: a book rebalanced mid-year held different names in Q1 and Q3. Full details, including a NaN trap that was live on the current book, are in `docs/period-book-analytics.md`.

### Looking backwards, and which beta is which

A period must name its year to mean a past one — `q2-2026`, `2027`, `2026-03`. Bare `q2` always resolves against the latest year in the data.

```text
GET /api/book-analytics?period=q2-2026
```

A historical window rebuilds the contribution history from that year's opening, based on the prior year's final close exactly as the live path is, and uses the book that was live then rather than today's. It returns a warning when no snapshot precedes that year, since the opening book was then inferred rather than read from the ledger. Five years of prices are downloaded every run and the snapshot ledger is permanent, so the ingredients survive.

Headline risk metrics — beta, correlation, volatility, Sharpe, drawdown, VaR — remain year-to-date only. `calculate_risk_metrics` takes no window parameter, and half-parameterising it is how a number ends up computed over one window and labelled with another.

There are two portfolio return series with different meanings: a static replay of today's book over the full download window, and the rebalance-aware segmented series. **The dashboard displays the rebalance-aware one.** The static series is not rendered; it appears in the CLI report and as a stress-test fallback, which now carries `betaSource` so a fallback estimate can be labelled. Details in `docs/beta-correlation-and-backward-analysis.md`.

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
$env:PYTHONDONTWRITEBYTECODE='1'; python -m py_compile backend\server.py backend\drive_indexer.py backend\brain_agent.py backend\brain_store.py backend\brain_store_postgres.py backend\gemini_client.py backend\github_client.py backend\code_agent.py backend\office_extract.py backend\drive_coverage.py backend\source_dates.py backend\drive_dates.py
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
python test_price_gap_recovery.py
python test_code_agent.py
python test_office_extract.py
python test_drive_coverage.py
python test_ingestion_limits.py
python test_source_dates.py
python test_book_analytics.py
```

`.github/workflows/ci.yml` runs all of the above on every pull request, plus `tsc -b`, ESLint, and `vite build`. That workflow is what gates a self-build proposal, so keep it green.

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
