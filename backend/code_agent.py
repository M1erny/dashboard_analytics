"""The Brain's self-build agent: turn a plain-language request into a pull request.

The loop is deliberately narrow. Gemini proposes file changes, this module
validates them against a write allowlist, applies them to the real file contents
fetched from GitHub, commits them to a fresh branch, and opens a pull request.
Nothing merges without a human, and CI runs on every proposal.
"""

import difflib
import os
import re
import time
from typing import Any

from github_client import SELF_BUILD_BRANCH_PREFIX, GitHubClient


# Where the agent may write. Reading is broader than writing on purpose: the
# model needs to see package.json and AGENTS.md to write code that fits, but it
# must not be able to change them.
WRITABLE_ROOTS = ("src/", "backend/", "docs/", "public/")
WRITABLE_ROOT_FILES = frozenset({"README.md", "index.html"})

# Accounting data, CI definitions, dependency manifests, and deploy config stay
# under human control. backend/portfolios is the performance audit trail.
PROTECTED_PREFIXES = ("backend/portfolios/", "node_modules/", "dist/", "build/")
PROTECTED_PATHS = frozenset(
    {
        "AGENTS.md",
        "vercel.json",
        "vite.config.ts",
        "tsconfig.json",
        "tsconfig.app.json",
        "tsconfig.node.json",
        "eslint.config.js",
        "postcss.config.js",
        "tailwind.config.js",
        "backend/validate_portfolio_history.py",
    }
)

# Editing these would let a proposal widen its own allowlist. A merged pull
# request can still change anything, so this is defence in depth, not a wall.
GUARDRAIL_PATHS = frozenset({"backend/code_agent.py", "backend/github_client.py"})

# New dependencies mean new third-party code in the build, so they need an
# explicit opt-in even though the files live in writable roots.
DEPENDENCY_PATHS = frozenset({"package.json", "package-lock.json", "backend/requirements.txt"})

WRITABLE_EXTENSIONS = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".mjs", ".css", ".md", ".py", ".html", ".svg", ".json", ".txt", ".sql"}
)
CONTEXT_EXTENSIONS = WRITABLE_EXTENSIONS

ANCHOR_CONTEXT_PATHS = (
    "AGENTS.md",
    "package.json",
    "src/App.tsx",
)

MAX_REQUEST_CHARS = 4000
MAX_CHANGED_FILES = 12
MAX_FILE_CHARS = 120_000
MAX_TOTAL_CHANGE_CHARS = 400_000
DEFAULT_CONTEXT_FILES = 8
DEFAULT_CONTEXT_CHARS = 220_000
DEFAULT_CONTEXT_FILE_CHARS = 70_000
DEFAULT_MAX_OUTPUT_TOKENS = 32_000
DEFAULT_CODE_MODEL = "gemini-3.5-flash"
DEFAULT_CODE_THINKING_LEVEL = "high"
DEFAULT_MAX_OPEN_PROPOSALS = 5
DEFAULT_PLAN_TIMEOUT = 240.0

SECRET_PATTERNS = (
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "a Google API key"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "a GitHub token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "a GitHub token"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "an API secret"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"postgres(?:ql)?://[^\s:]+:[^\s@]+@"), "a database password"),
)

STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "into", "from", "when", "then", "than",
        "should", "would", "could", "please", "make", "add", "also", "but", "not", "can",
        "you", "are", "was", "were", "have", "has", "had", "its", "it's", "there", "their",
        "some", "any", "all", "new", "use", "using", "used", "want", "need", "like", "show",
        "shows", "display", "dashboard", "brain", "app", "code", "change", "changes",
    }
)

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "rationale": {"type": "string"},
        "commitMessage": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "followUps": {"type": "array", "items": {"type": "string"}},
        "unsupported": {"type": "string"},
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "action": {"type": "string", "enum": ["write", "replace", "delete"]},
                    "reason": {"type": "string"},
                    "contents": {"type": "string"},
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                },
                "required": ["path", "action", "reason"],
                "propertyOrdering": ["path", "action", "reason", "find", "replace", "contents"],
            },
        },
    },
    "required": ["summary", "rationale", "commitMessage", "files"],
    "propertyOrdering": [
        "summary",
        "rationale",
        "commitMessage",
        "unsupported",
        "risks",
        "followUps",
        "files",
    ],
}

SYSTEM_INSTRUCTION = """You are the self-build agent for a private portfolio analytics dashboard.
You receive a plain-language request from the dashboard owner and you answer with source changes
to this repository. Your answer becomes a real pull request, so it must compile and it must be
small enough for a human to review.

Stack: React 19 + TypeScript + Vite + TailwindCSS v4 + Recharts + lucide-react on the frontend,
Python 3.12 + FastAPI on the backend. The frontend talks to the backend over the /api routes in
backend/server.py.

Hard rules:
- Only change files you were told are writable. Never touch accounting data, CI, dependency
  manifests, or build configuration.
- Never add a dependency that is not already in package.json or backend/requirements.txt. Build
  what you need from what is already there.
- Keep TypeScript strict-mode clean: annotate props, no unused imports, no `any` where a real
  type is available. Match the file's existing style, naming, and Tailwind class conventions.
- Prefer the `replace` action with a unique `find` anchor. Only use `write` for a brand new file,
  or for an existing file whose complete contents you were given.
- For `write`, `contents` must be the entire final file, not a fragment and not a diff.
- For `replace`, `find` must appear exactly once in the current file. Include enough surrounding
  lines to make it unique, and keep indentation byte-exact.
- Do not invent API routes, fields, or helper functions. If you need backend data that does not
  exist, add the route in backend/server.py as part of the same change.
- Never write secrets, tokens, or connection strings into source.
- Wire up what you build. A new component that nothing renders is not a completed request.

If the request cannot be done safely under these rules, return an empty `files` array and explain
why in `unsupported`. An honest refusal is better than a broken pull request."""


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def code_agent_settings() -> dict[str, Any]:
    return {
        "model": (os.environ.get("BRAIN_CODE_MODEL") or DEFAULT_CODE_MODEL).strip(),
        "thinkingLevel": (os.environ.get("BRAIN_CODE_THINKING_LEVEL") or DEFAULT_CODE_THINKING_LEVEL).strip().lower(),
        "maxOutputTokens": _env_int("BRAIN_CODE_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS),
        "contextFiles": _env_int("BRAIN_CODE_CONTEXT_FILES", DEFAULT_CONTEXT_FILES),
        "contextChars": _env_int("BRAIN_CODE_CONTEXT_CHARS", DEFAULT_CONTEXT_CHARS),
        "planTimeoutSeconds": _env_float("BRAIN_CODE_TIMEOUT_SECONDS", DEFAULT_PLAN_TIMEOUT),
        "maxOpenProposals": _env_int("BRAIN_CODE_MAX_OPEN_PROPOSALS", DEFAULT_MAX_OPEN_PROPOSALS),
        "allowDependencies": _env_flag("BRAIN_CODE_ALLOW_DEPENDENCIES"),
        "allowSelfEdit": _env_flag("BRAIN_CODE_ALLOW_SELF_EDIT"),
        "allowMerge": _env_flag("BRAIN_CODE_ALLOW_MERGE"),
        "writableRoots": list(WRITABLE_ROOTS) + sorted(WRITABLE_ROOT_FILES),
        "protectedPaths": sorted(PROTECTED_PATHS | GUARDRAIL_PATHS | DEPENDENCY_PATHS),
        "protectedPrefixes": list(PROTECTED_PREFIXES) + [".github/", ".claude/"],
        "maxChangedFiles": MAX_CHANGED_FILES,
    }


def _extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def check_writable_path(
    path: str,
    *,
    allow_dependencies: bool = False,
    allow_self_edit: bool = False,
) -> str:
    """Return the normalised path, or raise ValueError explaining the refusal."""
    raw = (path or "").strip()
    if not raw:
        raise ValueError("A change is missing its path.")
    if "\\" in raw:
        raise ValueError(f"Use forward slashes in paths: {raw}")
    if ".." in raw:
        raise ValueError(f"Path traversal is not allowed: {raw}")
    clean = raw[2:] if raw.startswith("./") else raw
    if clean.startswith("/"):
        raise ValueError(f"Absolute paths are not allowed: {raw}")
    if clean.endswith("/"):
        raise ValueError(f"Path is a directory, not a file: {raw}")

    segments = clean.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError(f"Path traversal is not allowed: {raw}")
    if any(segment.startswith(".") for segment in segments):
        raise ValueError(f"Dotfiles and dot-directories are not writable: {raw}")

    extension = _extension(clean)
    if extension not in WRITABLE_EXTENSIONS:
        raise ValueError(f"File type {extension or '(none)'} is not writable: {clean}")

    if clean in GUARDRAIL_PATHS and not allow_self_edit:
        raise ValueError(
            f"{clean} defines the self-build guardrails and is protected. "
            "Set BRAIN_CODE_ALLOW_SELF_EDIT=true to allow it."
        )
    if clean in DEPENDENCY_PATHS:
        if not allow_dependencies:
            raise ValueError(
                f"{clean} is a dependency manifest and is protected. "
                "Set BRAIN_CODE_ALLOW_DEPENDENCIES=true to allow it."
            )
        return clean

    if clean in PROTECTED_PATHS:
        raise ValueError(f"{clean} is protected and cannot be changed by the self-build agent.")
    if any(clean.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        raise ValueError(f"{clean} is inside a protected directory and cannot be changed.")

    if clean in WRITABLE_ROOT_FILES:
        return clean
    if any(clean.startswith(root) for root in WRITABLE_ROOTS):
        return clean
    raise ValueError(
        f"{clean} is outside the writable roots ({', '.join(WRITABLE_ROOTS)}) "
        f"and the writable root files ({', '.join(sorted(WRITABLE_ROOT_FILES))})."
    )


def scan_for_secrets(path: str, contents: str) -> None:
    for pattern, label in SECRET_PATTERNS:
        if pattern.search(contents):
            raise ValueError(f"{path} looks like it contains {label}. Secrets belong in environment variables.")


def _request_tokens(request: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", request.lower())
    seen: list[str] = []
    for word in words:
        if word in STOPWORDS or word in seen:
            continue
        seen.append(word)
    return seen[:40]


def _context_candidate(entry: dict[str, Any]) -> bool:
    path = entry["path"]
    if _extension(path) not in CONTEXT_EXTENSIONS:
        return False
    if any(segment.startswith(".") for segment in path.split("/")):
        return False
    if any(path.startswith(prefix) for prefix in ("node_modules/", "dist/", "backend/portfolios/", "backend/brain_library/")):
        return False
    if "/" not in path and path not in {"README.md", "index.html", "package.json", "AGENTS.md"}:
        return False
    return True


def score_context_file(path: str, tokens: list[str]) -> float:
    lower = path.lower()
    stem = lower.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    score = 0.0
    for token in tokens:
        if token in stem:
            score += 6.0
        elif token in lower:
            score += 3.0
    if lower.startswith("src/components/"):
        score += 1.5
    if lower.startswith("src/") or lower == "backend/server.py":
        score += 0.75
    if stem.startswith("test_") or stem.startswith("debug_"):
        score -= 4.0
    if lower.endswith(".md") and not lower.startswith("docs/"):
        score -= 1.0
    return score


def select_context_files(
    tree: list[dict[str, Any]],
    request: str,
    *,
    limit: int = DEFAULT_CONTEXT_FILES,
) -> list[str]:
    """Pick the files most likely to matter for this request, anchors first."""
    tokens = _request_tokens(request)
    by_path = {entry["path"]: entry for entry in tree if _context_candidate(entry)}

    selected: list[str] = [path for path in ANCHOR_CONTEXT_PATHS if path in by_path]
    scored = sorted(
        (
            (score_context_file(path, tokens), -entry.get("size", 0), path)
            for path, entry in by_path.items()
            if path not in selected
        ),
        reverse=True,
    )
    for score, _negative_size, path in scored:
        if len(selected) >= max(limit, len(ANCHOR_CONTEXT_PATHS)):
            break
        if score <= 0:
            continue
        selected.append(path)

    # A request that matches nothing by name still needs somewhere to start.
    if len(selected) <= len(ANCHOR_CONTEXT_PATHS):
        for fallback in ("src/components/Dashboard.tsx", "backend/server.py", "src/components/InvestmentBrainChat.tsx"):
            if fallback in by_path and fallback not in selected:
                selected.append(fallback)
            if len(selected) >= limit:
                break
    return selected


def build_repo_context(
    github: GitHubClient,
    tree: list[dict[str, Any]],
    request: str,
    *,
    ref: str,
    limit: int = DEFAULT_CONTEXT_FILES,
    total_chars: int = DEFAULT_CONTEXT_CHARS,
    max_file_chars: int = DEFAULT_CONTEXT_FILE_CHARS,
) -> dict[str, Any]:
    """Fetch the selected files and record which ones arrived complete.

    A truncated file must not be rewritten wholesale, so the caller needs to know
    exactly which paths the model saw in full.
    """
    paths = select_context_files(tree, request, limit=limit)
    files: list[dict[str, Any]] = []
    complete_paths: set[str] = set()
    budget = total_chars

    for path in paths:
        if budget <= 0:
            break
        contents = github.read_file(path, ref=ref)
        if contents is None:
            continue
        allowance = min(max_file_chars, budget)
        truncated = len(contents) > allowance
        body = contents[:allowance]
        budget -= len(body)
        if not truncated:
            complete_paths.add(path)
        files.append({"path": path, "contents": body, "truncated": truncated, "chars": len(contents)})

    return {
        "files": files,
        "completePaths": complete_paths,
        "requestedPaths": paths,
    }


def _repo_map(tree: list[dict[str, Any]], limit: int = 400) -> str:
    paths = sorted(entry["path"] for entry in tree if _context_candidate(entry))
    if len(paths) > limit:
        hidden = len(paths) - limit
        paths = paths[:limit] + [f"... {hidden} more files"]
    return "\n".join(paths)


def build_plan_prompt(
    request: str,
    context: dict[str, Any],
    tree: list[dict[str, Any]],
    *,
    house_rules: str | None = None,
    notes: str | None = None,
) -> str:
    settings = code_agent_settings()
    sections: list[str] = []
    sections.append(f"# Owner request\n\n{request.strip()}")
    if notes:
        sections.append(f"# Extra context from the Brain\n\n{notes.strip()[:4000]}")
    if house_rules:
        sections.append(f"# House rules from AGENTS.md\n\n{house_rules.strip()[:6000]}")

    sections.append(
        "# Write permissions\n\n"
        f"Writable roots: {', '.join(WRITABLE_ROOTS)}\n"
        f"Writable root files: {', '.join(sorted(WRITABLE_ROOT_FILES))}\n"
        f"Protected paths: {', '.join(settings['protectedPaths'])}\n"
        f"Protected directories: {', '.join(settings['protectedPrefixes'])}\n"
        f"Maximum files in one change: {MAX_CHANGED_FILES}"
    )
    sections.append(f"# Repository files\n\n{_repo_map(tree)}")

    complete_paths = context.get("completePaths") or set()
    file_blocks: list[str] = []
    for item in context.get("files", []):
        path = item["path"]
        note = (
            "complete file, safe to rewrite with `write`"
            if path in complete_paths
            else f"TRUNCATED at {len(item['contents'])} of {item['chars']} characters — use `replace` only"
        )
        extension = _extension(path).lstrip(".") or "text"
        file_blocks.append(f"## {path} ({note})\n\n```{extension}\n{item['contents']}\n```")
    sections.append("# Current source\n\n" + "\n\n".join(file_blocks))

    sections.append(
        "# Your answer\n\n"
        "Return JSON matching the provided schema. `commitMessage` is a single imperative line "
        "under 72 characters. `summary` is one or two sentences the owner will read in the pull "
        "request. Every entry in `files` needs a `reason` naming what it accomplishes."
    )
    return "\n\n".join(sections)


def validate_plan(
    plan: dict[str, Any],
    *,
    complete_paths: set[str],
    existing_paths: set[str],
    allow_dependencies: bool = False,
    allow_self_edit: bool = False,
) -> list[dict[str, Any]]:
    """Return the accepted changes, or raise ValueError naming the first problem."""
    if not isinstance(plan, dict):
        raise ValueError("The model did not return a change plan object.")

    raw_changes = plan.get("files")
    if not isinstance(raw_changes, list) or not raw_changes:
        unsupported = str(plan.get("unsupported") or "").strip()
        if unsupported:
            raise ValueError(f"The agent declined this request: {unsupported}")
        raise ValueError("The model returned no file changes.")
    if len(raw_changes) > MAX_CHANGED_FILES:
        raise ValueError(
            f"The plan changes {len(raw_changes)} files, above the {MAX_CHANGED_FILES} file limit."
        )

    changes: list[dict[str, Any]] = []
    total_chars = 0
    seen_write_or_delete: set[str] = set()

    for raw in raw_changes:
        if not isinstance(raw, dict):
            raise ValueError("A change entry is not an object.")
        action = str(raw.get("action") or "").strip().lower()
        if action not in {"write", "replace", "delete"}:
            raise ValueError(f"Unsupported action: {action or '(missing)'}")

        path = check_writable_path(
            str(raw.get("path") or ""),
            allow_dependencies=allow_dependencies,
            allow_self_edit=allow_self_edit,
        )

        if action == "delete":
            if path not in existing_paths:
                raise ValueError(f"Cannot delete {path} because it does not exist.")
            if path in seen_write_or_delete:
                raise ValueError(f"{path} appears twice in the plan.")
            seen_write_or_delete.add(path)
            changes.append({"path": path, "action": "delete", "reason": str(raw.get("reason") or "")})
            continue

        if action == "write":
            contents = raw.get("contents")
            if not isinstance(contents, str) or not contents.strip():
                raise ValueError(f"The write for {path} has no contents.")
            if len(contents) > MAX_FILE_CHARS:
                raise ValueError(
                    f"{path} would be {len(contents)} characters, above the {MAX_FILE_CHARS} limit."
                )
            if path in existing_paths and path not in complete_paths:
                raise ValueError(
                    f"{path} was not supplied in full, so it cannot be rewritten with `write`. "
                    "The agent must use `replace` for this file."
                )
            if path in seen_write_or_delete:
                raise ValueError(f"{path} appears twice in the plan.")
            scan_for_secrets(path, contents)
            seen_write_or_delete.add(path)
            total_chars += len(contents)
            changes.append(
                {
                    "path": path,
                    "action": "write",
                    "contents": contents,
                    "reason": str(raw.get("reason") or ""),
                }
            )
            continue

        find = raw.get("find")
        replacement = raw.get("replace")
        if not isinstance(find, str) or not find:
            raise ValueError(f"The replace for {path} has no `find` anchor.")
        if not isinstance(replacement, str):
            raise ValueError(f"The replace for {path} has no `replace` text.")
        if path not in existing_paths:
            raise ValueError(f"Cannot replace inside {path} because it does not exist. Use `write`.")
        if len(replacement) > MAX_FILE_CHARS:
            raise ValueError(f"The replacement for {path} is larger than the {MAX_FILE_CHARS} character limit.")
        scan_for_secrets(path, replacement)
        total_chars += len(replacement)
        changes.append(
            {
                "path": path,
                "action": "replace",
                "find": find,
                "replace": replacement,
                "reason": str(raw.get("reason") or ""),
            }
        )

    if total_chars > MAX_TOTAL_CHANGE_CHARS:
        raise ValueError(
            f"The plan writes {total_chars} characters, above the {MAX_TOTAL_CHANGE_CHARS} limit."
        )
    return changes


def apply_changes(
    github: GitHubClient,
    changes: list[dict[str, Any]],
    *,
    ref: str,
) -> list[dict[str, Any]]:
    """Resolve replace anchors against the real files and return commit-ready writes.

    Replacements are applied in plan order, so several edits to one file stack.
    """
    current: dict[str, str | None] = {}
    resolved: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def read(path: str) -> str | None:
        if path not in current:
            current[path] = github.read_file(path, ref=ref)
        return current[path]

    for change in changes:
        path = change["path"]
        if path not in resolved:
            order.append(path)

        if change["action"] == "delete":
            resolved[path] = {"path": path, "action": "delete", "reason": change.get("reason", "")}
            continue

        if change["action"] == "write":
            before = read(path) or ""
            resolved[path] = {
                "path": path,
                "action": "write",
                "contents": change["contents"],
                "before": before,
                "reason": change.get("reason", ""),
            }
            continue

        entry = resolved.get(path)
        before = entry["contents"] if entry and entry.get("action") == "write" else read(path)
        if before is None:
            raise ValueError(f"Cannot replace inside {path} because it could not be read.")
        occurrences = before.count(change["find"])
        if occurrences == 0:
            raise ValueError(
                f"The `find` anchor for {path} does not appear in the current file. "
                "The agent's copy of the file is stale or the anchor was reformatted."
            )
        if occurrences > 1:
            raise ValueError(
                f"The `find` anchor for {path} appears {occurrences} times. "
                "The anchor must be unique."
            )
        updated = before.replace(change["find"], change["replace"], 1)
        original = entry.get("before") if entry else read(path)
        resolved[path] = {
            "path": path,
            "action": "write",
            "contents": updated,
            "before": original if original is not None else before,
            "reason": change.get("reason", ""),
        }

    applied = [resolved[path] for path in order]
    for item in applied:
        if item["action"] != "write":
            continue
        # The cap bounds what the agent writes, not how big an existing file is.
        # backend/server.py is already past MAX_FILE_CHARS, and editing it by
        # anchor is exactly what the replace action is for.
        growth = len(item["contents"]) - len(item.get("before") or "")
        if growth > MAX_FILE_CHARS:
            raise ValueError(
                f"{item['path']} would grow by {growth} characters, "
                f"above the {MAX_FILE_CHARS} limit for a single change."
            )
    return applied


def change_diff(item: dict[str, Any], *, max_lines: int = 400) -> str:
    if item["action"] == "delete":
        return f"--- a/{item['path']}\n+++ /dev/null"
    before = (item.get("before") or "").splitlines(keepends=True)
    after = (item.get("contents") or "").splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"a/{item['path']}" if before else "/dev/null",
            tofile=f"b/{item['path']}",
            n=3,
        )
    )
    if len(diff) > max_lines:
        diff = diff[:max_lines] + [f"... diff truncated after {max_lines} lines\n"]
    return "".join(diff)


def _slug(text: str, limit: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:limit].rstrip("-") or "change")


def build_branch_name(request: str, summary: str | None = None) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"{SELF_BUILD_BRANCH_PREFIX}/{stamp}-{_slug(summary or request)}"


def build_pull_request_body(
    *,
    request: str,
    plan: dict[str, Any],
    applied: list[dict[str, Any]],
    model: str,
    base_sha: str,
    context_paths: list[str],
) -> str:
    lines: list[str] = []
    lines.append("## What the owner asked for")
    lines.append("")
    lines.append("> " + request.strip().replace("\n", "\n> "))
    lines.append("")
    lines.append("## What this change does")
    lines.append("")
    lines.append(str(plan.get("summary") or "No summary was returned.").strip())
    rationale = str(plan.get("rationale") or "").strip()
    if rationale:
        lines.append("")
        lines.append("## Why this way")
        lines.append("")
        lines.append(rationale)

    lines.append("")
    lines.append("## Files")
    lines.append("")
    lines.append("| File | Action | Reason |")
    lines.append("| --- | --- | --- |")
    for item in applied:
        reason = str(item.get("reason") or "").replace("|", "\\|").replace("\n", " ")
        action = "delete" if item["action"] == "delete" else ("create" if not item.get("before") else "edit")
        lines.append(f"| `{item['path']}` | {action} | {reason[:180]} |")

    risks = [str(risk).strip() for risk in (plan.get("risks") or []) if str(risk).strip()]
    if risks:
        lines.append("")
        lines.append("## Risks the agent flagged")
        lines.append("")
        lines.extend(f"- {risk}" for risk in risks)

    follow_ups = [str(item).strip() for item in (plan.get("followUps") or []) if str(item).strip()]
    if follow_ups:
        lines.append("")
        lines.append("## Follow-ups")
        lines.append("")
        lines.extend(f"- {item}" for item in follow_ups)

    lines.append("")
    lines.append("## Review notes")
    lines.append("")
    lines.append(
        "This pull request was written by the Investment Brain self-build agent from the request "
        "quoted above. Nothing was merged automatically. Accounting data, CI, dependency "
        "manifests, and build configuration are outside the agent's write allowlist."
    )
    lines.append("")
    lines.append(f"- Model: `{model}`")
    lines.append(f"- Base commit: `{base_sha[:7]}`")
    lines.append(f"- Files the agent read: {', '.join(f'`{path}`' for path in context_paths) or 'none'}")
    lines.append("")
    lines.append("_Generated by the Investment Brain self-build agent._")
    return "\n".join(lines)


def propose_code_change(
    github: GitHubClient,
    gemini: Any,
    *,
    request: str,
    notes: str | None = None,
    open_pull_request: bool = True,
    context_limit: int | None = None,
) -> dict[str, Any]:
    """Plan, validate, and (optionally) push a self-build change as a pull request."""
    clean_request = (request or "").strip()
    if not clean_request:
        raise ValueError("Describe the change you want before running the self-build agent.")
    if len(clean_request) > MAX_REQUEST_CHARS:
        raise ValueError(f"Keep the request under {MAX_REQUEST_CHARS} characters.")

    settings = code_agent_settings()
    timings: dict[str, Any] = {}

    if open_pull_request and settings["maxOpenProposals"] > 0:
        open_proposals = github.list_pull_requests(state="open", limit=100)
        if len(open_proposals) >= settings["maxOpenProposals"]:
            raise ValueError(
                f"{len(open_proposals)} self-build pull requests are already open, at the "
                f"{settings['maxOpenProposals']} limit. Review or close them first."
            )

    started = time.perf_counter()
    base_sha = github.branch_head(github.base_branch)
    tree = github.list_tree(base_sha)
    existing_paths = {entry["path"] for entry in tree}
    context = build_repo_context(
        github,
        tree,
        clean_request,
        ref=base_sha,
        limit=context_limit or settings["contextFiles"],
        total_chars=settings["contextChars"],
    )
    timings["contextMs"] = round((time.perf_counter() - started) * 1000, 1)

    house_rules = next(
        (item["contents"] for item in context["files"] if item["path"] == "AGENTS.md"),
        None,
    )
    prompt = build_plan_prompt(
        clean_request,
        context,
        tree,
        house_rules=house_rules,
        notes=notes,
    )

    plan_started = time.perf_counter()
    plan = gemini.generate_json(
        prompt,
        response_schema=PLAN_SCHEMA,
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.15,
        max_output_tokens=settings["maxOutputTokens"],
        timeout_seconds=settings["planTimeoutSeconds"],
        model=settings["model"],
        thinking_level=settings["thinkingLevel"],
    )
    timings["planMs"] = round((time.perf_counter() - plan_started) * 1000, 1)

    changes = validate_plan(
        plan,
        complete_paths=set(context["completePaths"]),
        existing_paths=existing_paths,
        allow_dependencies=settings["allowDependencies"],
        allow_self_edit=settings["allowSelfEdit"],
    )
    applied = apply_changes(github, changes, ref=base_sha)

    preview = [
        {
            "path": item["path"],
            "action": "delete" if item["action"] == "delete" else ("create" if not item.get("before") else "edit"),
            "reason": item.get("reason", ""),
            "diff": change_diff(item),
        }
        for item in applied
    ]
    result: dict[str, Any] = {
        "request": clean_request,
        "summary": str(plan.get("summary") or "").strip(),
        "rationale": str(plan.get("rationale") or "").strip(),
        "risks": [str(risk) for risk in (plan.get("risks") or [])],
        "followUps": [str(item) for item in (plan.get("followUps") or [])],
        "model": settings["model"],
        "baseBranch": github.base_branch,
        "baseSha": base_sha,
        "contextPaths": context["requestedPaths"],
        "changes": preview,
        "timings": timings,
    }

    if not open_pull_request:
        result["action"] = "previewed"
        result["message"] = f"Planned {len(preview)} file change(s). No branch was pushed."
        return result

    commit_message = str(plan.get("commitMessage") or "").strip().splitlines()[0] if plan.get("commitMessage") else ""
    if not commit_message:
        commit_message = f"Self-build: {clean_request[:60]}"
    branch = build_branch_name(clean_request, commit_message)

    push_started = time.perf_counter()
    github.create_branch(branch, base_sha)
    commit = github.commit_files(
        branch=branch,
        parent_sha=base_sha,
        files=[
            {"path": item["path"], "action": item["action"], "contents": item.get("contents", "")}
            for item in applied
        ],
        message=f"{commit_message}\n\nRequested through the Investment Brain:\n{clean_request[:1500]}",
    )
    pull = github.open_pull_request(
        title=commit_message[:200],
        head=branch,
        body=build_pull_request_body(
            request=clean_request,
            plan=plan,
            applied=applied,
            model=settings["model"],
            base_sha=base_sha,
            context_paths=context["requestedPaths"],
        ),
    )
    try:
        github.add_labels(int(pull["number"]), ["brain-self-build"])
    except RuntimeError:
        # A missing label is not worth failing a good pull request over.
        pass
    timings["pushMs"] = round((time.perf_counter() - push_started) * 1000, 1)

    result["action"] = "pull_request_opened"
    result["branch"] = branch
    result["commitSha"] = commit.get("commitSha")
    result["pullRequest"] = pull
    result["message"] = (
        f"Opened pull request #{pull.get('number')} with {len(preview)} file change(s). "
        "CI runs on the branch; merge it yourself to make the change live."
    )
    return result
