# Self-Building Brain

The Brain can change this dashboard's own source code. You describe a change in
plain language, Gemini writes it, and the result arrives as a pull request on
GitHub with CI attached. You merge it, and the deployment that follows is the
dashboard modifying itself.

This document explains the loop, the guardrails, and what it is honestly good at.

## The loop

```text
Brain page, Self-build panel
        |  "Add a widget showing my three largest single-name exposures"
        v
POST /api/brain/code/propose            (backend/server.py)
        |
        v
backend/code_agent.py
        |
        +-- 1. Read the repository through the GitHub API at main's head commit
        |        - full file map
        |        - full text of the ~8 files most likely to matter
        |
        +-- 2. Ask Gemini for a change plan, constrained by a JSON schema
        |        (Google AI Studio, generateContent with responseSchema)
        |
        +-- 3. Validate every proposed path and edit
        |        write allowlist, size caps, secret scan, unique anchors
        |
        +-- 4. Apply the edits to the real file contents from GitHub
        |
        +-- 5. Commit to a new branch and open a pull request
        v
GitHub Actions (.github/workflows/ci.yml)
        |  tsc -b, eslint, vite build, every backend/test_*.py
        v
You review the diff and merge
        |
        v
Vercel redeploys the frontend, Render redeploys the backend
```

Steps 1, 4, and 5 all go through `backend/github_client.py`, which speaks the
GitHub REST API directly. The running server never writes to its own filesystem —
Render's disk is ephemeral, and a process that rewrites its own source in place
has no audit trail and no way back.

## Setup

1. Create a **fine-grained** GitHub personal access token, scoped to this
   repository only, with exactly two permissions:
   - Contents: read and write
   - Pull requests: read and write
2. Set these on the Render service (or `backend/.env` locally):
   ```text
   BRAIN_GITHUB_TOKEN=github_pat_...
   BRAIN_GITHUB_REPO=m1erny/dashboard_analytics
   BRAIN_CODE_MODEL=gemini-3.5-flash
   BRAIN_CODE_THINKING_LEVEL=high
   ```
3. Reload the Brain page. The Self-build panel reports `available: true` once
   both GitHub and the Google AI Studio key are configured.

`GET /api/brain/code/status` returns the same information as JSON, including the
active guardrails, without calling GitHub.

## The model matters more than anything else here

Brain answers run on `gemini-3.5-flash-lite` with minimal thinking, which is the
right trade for retrieval-grounded prose. Writing TypeScript that compiles on the
first try is a different job. `BRAIN_CODE_MODEL` is therefore separate and
defaults to `gemini-3.5-flash` with `thinkingLevel: high`. Point it at the
strongest coding model your key can reach.

Expect roughly this, and calibrate:

| Request | Realistic outcome |
| --- | --- |
| Copy tone, colour, label, or layout in an existing widget | Usually right first time |
| New widget built from an existing `/api` route | Often right, sometimes needs one follow-up |
| New widget plus the backend route that feeds it | Two-file change; review the maths closely |
| Anything touching `risk.py` maths or rebalance accounting | Do not delegate this |

## Guardrails

**Reading is broader than writing.** The agent is shown `package.json` and
`AGENTS.md` so it writes code that fits the project, but it cannot change them.

Writable: `src/`, `backend/`, `docs/`, `public/`, plus `README.md` and
`index.html` at the root, restricted to text extensions.

Never writable:

| Path | Why |
| --- | --- |
| `backend/portfolios/**` | The performance audit trail. `AGENTS.md` is explicit that this is accounting data, not config. |
| `.github/**` | CI is the thing checking the agent's work. It does not get to edit its own exam. |
| `.claude/**`, any dotfile | Agent instructions and environment files. |
| `package.json`, `package-lock.json`, `backend/requirements.txt` | A new dependency is new third-party code in your build. Opt in with `BRAIN_CODE_ALLOW_DEPENDENCIES`. |
| `vite.config.ts`, `tsconfig*.json`, `eslint.config.js`, `tailwind.config.js`, `postcss.config.js`, `vercel.json` | Build and deploy configuration. |
| `AGENTS.md` | The house rules it is being held to. |
| `backend/code_agent.py`, `backend/github_client.py` | The guardrails themselves. Opt in with `BRAIN_CODE_ALLOW_SELF_EDIT`. |

Per-proposal limits: at most 12 files, 120 KB per file, 400 KB total, and at most
5 open proposals at a time (`BRAIN_CODE_MAX_OPEN_PROPOSALS`) so a stuck retry
loop cannot flood the repository.

Every write is scanned for anything that looks like an API key, GitHub token,
private key, or database URL with a password, and rejected if found.

### Be clear about what the allowlist is worth

The path allowlist stops a *single* proposal from touching protected files. It is
not a security boundary against a determined model, because a merged pull request
can change anything — including, next time round, the allowlist itself. The real
gate is that **you** merge. Keep it that way: read the diff.

## Full-file writes versus anchored edits

A model that only saw part of a file will happily "return the full file" and
delete the rest. So the agent tracks which files it received complete:

- `write` — the entire final file. Allowed for new files, and for existing files
  the model was given in full.
- `replace` — a unique `find` anchor and its replacement, applied server-side to
  the real file contents. The anchor must appear exactly once, or the change is
  rejected rather than guessed at. This is how large files like
  `backend/server.py` (~190 KB, far past the context budget) get edited safely.
- `delete` — only for files that exist.

Several `replace` edits to one file stack into a single commit write, so
"import the component and render it" is one atomic change.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/brain/code/status` | Configuration and active guardrails |
| `POST` | `/api/brain/code/propose` | Plan a change; `openPullRequest: false` previews the diff without pushing |
| `GET` | `/api/brain/code/proposals` | Open self-build pull requests |
| `GET` | `/api/brain/code/proposals/{number}` | CI state, individual checks, changed files |
| `POST` | `/api/brain/code/proposals/{number}/merge` | Squash-merge, refused unless `BRAIN_CODE_ALLOW_MERGE=true` and checks are green |

The merge endpoint additionally refuses any pull request whose head branch is not
under `brain/self-build/`, so it cannot be pointed at a human's work.

## Why there is no fully autonomous loop

Everything needed for one is here: the agent writes code, CI judges it, and the
merge endpoint can merge on green. Wiring "merge whatever passes" is a few lines.
It is deliberately not wired, for two reasons.

First, green CI is a weak signal for this repository. `tsc`, ESLint, and the test
suites catch broken code; they do not catch a widget that renders a plausible
number computed the wrong way. On a portfolio dashboard, a confidently wrong
number is worse than a crash — a crash you notice.

Second, auto-merge removes the only step where a human sees the change before it
becomes the thing you make decisions from.

If you still want it, `BRAIN_CODE_ALLOW_MERGE=true` gives you a one-click merge
button on green proposals in the dashboard. That keeps the click, and the click is
the point.

## Writing good requests

Name the file or widget you mean, say where it goes, and say where the numbers
come from:

> Add a card to `src/components/dashboard/` showing the three largest single-name
> exposures as a share of gross, using `/api/portfolio/allocation`. Put it above
> the returns heatmap in `Dashboard.tsx` and match `MoatWidget.tsx`'s styling.

That gets a usable pull request far more often than "show my biggest positions".
Use **Preview diff** first — it runs the model and validators but pushes nothing,
so a bad plan costs you a few seconds and no repository noise.

## When a proposal fails

The panel shows the backend's actual reason. The common ones:

| Message | Meaning |
| --- | --- |
| `is outside the writable roots` | The model tried to change a protected file. Rephrase toward what you actually want changed. |
| `does not appear in the current file` | The anchor was stale or reformatted. Retry; the agent re-reads `main` each run. |
| `was not supplied in full, so it cannot be rewritten` | Correct refusal on a large file. Ask for a narrower change. |
| `not valid JSON ... truncated` | The plan exceeded the output budget. Raise `BRAIN_CODE_MAX_OUTPUT_TOKENS` or split the request. |
| `The agent declined this request` | The model judged it unsafe or impossible under the rules and said why. Usually it is right. |
| `pull requests are already open` | Clear the backlog first. |

## Files

| File | Role |
| --- | --- |
| `backend/code_agent.py` | Context selection, prompting, validation, diffing, proposal assembly |
| `backend/github_client.py` | GitHub REST: trees, blobs, commits, refs, pull requests, checks, merge |
| `backend/gemini_client.py` | `generate_json` — schema-constrained generation with a per-call model override |
| `backend/test_code_agent.py` | Guardrail tests: allowlist, validator, anchored replacement |
| `src/components/BrainSelfBuild.tsx` | The Self-build panel on the Brain page |
| `src/lib/brainApi.ts` | Shared backend base URL and error decoding |
| `.github/workflows/ci.yml` | The gate: types, lint, build, backend tests |
