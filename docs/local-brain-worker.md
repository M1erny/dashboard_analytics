# Local Brain Worker

This is the self-use architecture for a powerful investment brain:

```text
Local Google Drive synced folder
        -> local worker on your PC
        -> text extraction, chunking, embeddings
        -> Supabase Postgres + pgvector
        -> Render backend search/API
        -> Vercel dashboard
```

The web app should not parse large PDFs. The local worker does that heavy work on your computer, then uploads the searchable memory layer to Supabase.

## Why This Is Better Than Render Indexing

- Your raw files stay in Google Drive / local disk.
- Render does not run out of memory extracting PDFs.
- Supabase stores the searchable brain: metadata, chunks, embeddings, and memories.
- The dashboard can search the brain from anywhere because it reads Supabase through the backend.
- You can rebuild the brain from the original files if the database ever needs to be recreated.

## Setup

1. Copy the example env file:

```powershell
Copy-Item backend\.env.local-brain.example backend\.env
```

2. Edit `backend\.env` locally and set:

```text
DATABASE_URL=your Supabase Postgres pooler URL
GOOGLE_AI_API_KEY=your Google AI Studio key
BRAIN_LOCAL_LIBRARY_DIR=your local Google Drive synced folder
```

`backend\.env` is ignored by git. Do not commit real secrets.

3. Install Python dependencies if needed:

```powershell
python -m pip install -r backend\requirements.txt
```

## Run

Check connection and counts:

```powershell
.\run_local_brain_worker.ps1 -Mode status
```

Index a first local batch and embed missing chunks:

```powershell
.\run_local_brain_worker.ps1 -Mode all
```

Index only:

```powershell
.\run_local_brain_worker.ps1 -Mode index
```

Embed only:

```powershell
.\run_local_brain_worker.ps1 -Mode embed
```

Run a bigger local batch:

```powershell
.\run_local_brain_worker.ps1 -Mode all -ChangedFilesLimit 100 -EmbedMaxChunks 1000 -MaxBytes 500MB
```

Keep it running every 30 minutes:

```powershell
.\run_local_brain_worker.ps1 -Mode all -WatchMinutes 30
```

## Automatic Background Sync

The online dashboard cannot directly execute PowerShell on your computer. Browser security blocks websites from running local scripts.

For self-use, the practical solution is a Windows scheduled task. It keeps the Supabase brain fresh while your PC is on:

```text
new/changed Drive file appears locally
        -> scheduled local worker run
        -> chunks + embeddings go to Supabase
        -> website can search them
```

Install autosync:

```powershell
.\install_local_brain_autosync.ps1 -IntervalMinutes 15 -RunNow
```

If Windows blocks Task Scheduler registration for your user, the installer falls back to a hidden per-user startup loop. The behavior is the same while you are logged into Windows: it runs autosync every `IntervalMinutes`.

The default autosync is conservative:

```text
changed files per run:  10
max file size:          50 MB
max PDF pages:          300
max extracted chars:    750,000
embedding chunks/run:   500
```

Logs are written to:

```text
outputs/local_brain_autosync.log
outputs/local_brain_autosync_loop.log
```

Remove autosync:

```powershell
.\uninstall_local_brain_autosync.ps1
```

If you need a bigger one-off run, use `run_local_brain_worker.ps1` manually rather than making the scheduled task aggressive.

## Defaults

The local worker is intentionally stronger than the Render importer:

```text
max file size:          250 MB
max PDF pages:          2000
max extracted chars:    5,000,000
changed files per run:  25
embedding batch:        250 chunks
```

Lower these if your PC runs out of memory. Raise them when you want to digest a large book/report.

## What Gets Stored

The worker stores:

- source record with title, path metadata, file hash, and preview
- full extracted text chunks in `chunks`
- stable hashes so unchanged files are skipped
- embeddings in the `embedding vector(3072)` column after embedding

The original files remain in Google Drive/local disk.

## Important Limitations

- The cloud dashboard cannot open arbitrary local files from your PC. It sees the indexed text/chunks in Supabase.
- If `GOOGLE_AI_API_KEY` is missing or rejected, indexing still works but embeddings are blocked.
- Scanned PDFs may need OCR later; current extraction uses `pypdf`.
- Large spreadsheets and slide decks are not first-class yet.

## Operational Advice

For self-use, the best flow is:

```text
Daily/weekly: run the local worker
After adding research: run Mode all
Before deep analysis: run Mode embed if coverage is low
Monthly: export/back up Supabase
```

This keeps Render lightweight and makes your own computer the ingestion engine.
