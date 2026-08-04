"""Minimal GitHub REST client for the Brain's self-build loop.

The Brain never writes to the running server's filesystem. It writes to a Git
branch and opens a pull request, so every change the AI makes to this dashboard
arrives as a reviewable diff with CI attached.
"""

import base64
import os
import re
from typing import Any

import httpx


GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_REPO = "m1erny/dashboard_analytics"
DEFAULT_BASE_BRANCH = "main"
DEFAULT_TIMEOUT = 30.0
SELF_BUILD_BRANCH_PREFIX = "brain/self-build"
TEXT_MODE = "100644"


def _safe_github_error(error: Exception, token: str | None = None) -> str:
    text = str(error)
    if isinstance(error, httpx.HTTPStatusError) and error.response is not None:
        body = error.response.text[:400]
        message = ""
        try:
            payload = error.response.json()
            if isinstance(payload, dict):
                message = str(payload.get("message") or "")
        except ValueError:
            message = ""
        text = f"GitHub returned HTTP {error.response.status_code}: {message or body}"

    if token:
        text = text.replace(token, "<redacted>")
    text = re.sub(r"gh[pousr]_[A-Za-z0-9]{10,}", "<redacted>", text)
    text = re.sub(r"github_pat_[A-Za-z0-9_]{10,}", "<redacted>", text)
    return text[:600]


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        repo: str | None = None,
        base_branch: str | None = None,
        timeout: float | None = None,
    ):
        self.token = (
            token
            or os.environ.get("BRAIN_GITHUB_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
        )
        self.repo = (repo or os.environ.get("BRAIN_GITHUB_REPO") or DEFAULT_REPO).strip().strip("/")
        self.base_branch = (
            base_branch
            or os.environ.get("BRAIN_GITHUB_BASE_BRANCH")
            or DEFAULT_BASE_BRANCH
        ).strip()
        self.timeout = timeout or DEFAULT_TIMEOUT

    @property
    def configured(self) -> bool:
        return bool(self.token and "/" in self.repo)

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "repo": self.repo,
            "baseBranch": self.base_branch,
            "branchPrefix": SELF_BUILD_BRANCH_PREFIX,
            "tokenEnv": "BRAIN_GITHUB_TOKEN or GITHUB_TOKEN",
            "repoUrl": f"https://github.com/{self.repo}" if "/" in self.repo else None,
        }

    def _require_config(self) -> str:
        if not self.token:
            raise RuntimeError(
                "GitHub token is not configured. Set BRAIN_GITHUB_TOKEN to a fine-grained "
                "token with Contents and Pull requests write access."
            )
        if "/" not in self.repo:
            raise RuntimeError(
                f"BRAIN_GITHUB_REPO must look like owner/repo, got: {self.repo}"
            )
        return self.token

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        token = self._require_config()
        url = path if path.startswith("http") else f"{GITHUB_API_BASE}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": "InvestmentBrainSelfBuild/1.0",
        }
        with httpx.Client(timeout=self.timeout) as client:
            try:
                response = client.request(method, url, headers=headers, **kwargs)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"GitHub request timed out after {self.timeout:.0f}s") from exc
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(_safe_github_error(exc, token)) from exc
            if response.status_code == 204 or not response.content:
                return None
            return response.json()

    def repo_info(self) -> dict[str, Any]:
        data = self._request("GET", f"/repos/{self.repo}")
        return {
            "fullName": data.get("full_name"),
            "defaultBranch": data.get("default_branch"),
            "private": data.get("private"),
            "permissions": data.get("permissions") or {},
            "htmlUrl": data.get("html_url"),
        }

    def branch_head(self, branch: str | None = None) -> str:
        ref = branch or self.base_branch
        data = self._request("GET", f"/repos/{self.repo}/git/ref/heads/{ref}")
        sha = ((data or {}).get("object") or {}).get("sha")
        if not sha:
            raise RuntimeError(f"Could not resolve the head commit of branch {ref}")
        return str(sha)

    def commit_tree_sha(self, commit_sha: str) -> str:
        data = self._request("GET", f"/repos/{self.repo}/git/commits/{commit_sha}")
        sha = ((data or {}).get("tree") or {}).get("sha")
        if not sha:
            raise RuntimeError(f"Commit {commit_sha[:7]} did not report a tree")
        return str(sha)

    def list_tree(self, ref: str | None = None) -> list[dict[str, Any]]:
        """Return every blob in the repo at ref (a branch name or commit sha)."""
        candidate = str(ref or self.base_branch)
        commit_sha = (
            candidate
            if re.fullmatch(r"[0-9a-f]{40}", candidate)
            else self.branch_head(candidate)
        )
        tree_sha = self.commit_tree_sha(commit_sha)
        data = self._request(
            "GET",
            f"/repos/{self.repo}/git/trees/{tree_sha}",
            params={"recursive": "1"},
        ) or {}
        entries = [
            {
                "path": str(entry.get("path")),
                "size": int(entry.get("size") or 0),
                "sha": str(entry.get("sha") or ""),
            }
            for entry in (data.get("tree") or [])
            if entry.get("type") == "blob" and entry.get("path")
        ]
        if data.get("truncated"):
            raise RuntimeError(
                "GitHub truncated the repository tree, so the file map would be incomplete. "
                "Narrow the repository or raise this with the maintainer."
            )
        return entries

    def read_file(self, path: str, ref: str | None = None) -> str | None:
        """Return decoded UTF-8 file contents, or None when the path does not exist."""
        params = {"ref": ref or self.base_branch}
        try:
            data = self._request("GET", f"/repos/{self.repo}/contents/{path}", params=params)
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        if not isinstance(data, dict) or data.get("type") != "file":
            return None
        content = data.get("content") or ""
        encoding = data.get("encoding")
        if encoding != "base64":
            return str(content)
        try:
            return base64.b64decode(content).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    def create_branch(self, branch: str, from_sha: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repos/{self.repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": from_sha},
        ) or {}

    def create_blob(self, contents: str) -> str:
        data = self._request(
            "POST",
            f"/repos/{self.repo}/git/blobs",
            json={"content": contents, "encoding": "utf-8"},
        ) or {}
        sha = data.get("sha")
        if not sha:
            raise RuntimeError("GitHub did not return a blob sha")
        return str(sha)

    def commit_files(
        self,
        *,
        branch: str,
        parent_sha: str,
        files: list[dict[str, Any]],
        message: str,
    ) -> dict[str, Any]:
        """Commit writes and deletes onto branch in a single commit.

        files entries are {path, action: write|delete, contents}. The tree is
        built against the parent commit's tree so untouched files are preserved.
        """
        if not files:
            raise ValueError("Nothing to commit")

        base_tree = self.commit_tree_sha(parent_sha)
        tree_entries: list[dict[str, Any]] = []
        for change in files:
            path = str(change.get("path") or "").strip()
            if not path:
                raise ValueError("A change is missing its path")
            if change.get("action") == "delete":
                tree_entries.append({"path": path, "mode": TEXT_MODE, "type": "blob", "sha": None})
                continue
            blob_sha = self.create_blob(str(change.get("contents") or ""))
            tree_entries.append({"path": path, "mode": TEXT_MODE, "type": "blob", "sha": blob_sha})

        tree = self._request(
            "POST",
            f"/repos/{self.repo}/git/trees",
            json={"base_tree": base_tree, "tree": tree_entries},
        ) or {}
        tree_sha = tree.get("sha")
        if not tree_sha:
            raise RuntimeError("GitHub did not return a tree sha")

        commit = self._request(
            "POST",
            f"/repos/{self.repo}/git/commits",
            json={"message": message, "tree": tree_sha, "parents": [parent_sha]},
        ) or {}
        commit_sha = commit.get("sha")
        if not commit_sha:
            raise RuntimeError("GitHub did not return a commit sha")

        self._request(
            "PATCH",
            f"/repos/{self.repo}/git/refs/heads/{branch}",
            json={"sha": commit_sha, "force": False},
        )
        return {"commitSha": str(commit_sha), "treeSha": str(tree_sha), "branch": branch}

    def open_pull_request(
        self,
        *,
        title: str,
        head: str,
        body: str,
        base: str | None = None,
        draft: bool = False,
    ) -> dict[str, Any]:
        data = self._request(
            "POST",
            f"/repos/{self.repo}/pulls",
            json={
                "title": title[:250],
                "head": head,
                "base": base or self.base_branch,
                "body": body[:60000],
                "draft": draft,
            },
        ) or {}
        return self._public_pull_request(data)

    def add_labels(self, number: int, labels: list[str]) -> None:
        if not labels:
            return
        self._request(
            "POST",
            f"/repos/{self.repo}/issues/{number}/labels",
            json={"labels": labels},
        )

    def list_pull_requests(
        self,
        *,
        state: str = "open",
        head_prefix: str | None = SELF_BUILD_BRANCH_PREFIX,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            f"/repos/{self.repo}/pulls",
            params={"state": state, "per_page": min(max(limit, 1), 100), "sort": "created", "direction": "desc"},
        ) or []
        pulls = [self._public_pull_request(item) for item in data if isinstance(item, dict)]
        if head_prefix:
            pulls = [pull for pull in pulls if str(pull.get("headRef") or "").startswith(head_prefix)]
        return pulls[:limit]

    def pull_request(self, number: int) -> dict[str, Any]:
        data = self._request("GET", f"/repos/{self.repo}/pulls/{number}") or {}
        return self._public_pull_request(data)

    def pull_request_files(self, number: int, limit: int = 100) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            f"/repos/{self.repo}/pulls/{number}/files",
            params={"per_page": min(max(limit, 1), 100)},
        ) or []
        return [
            {
                "path": item.get("filename"),
                "status": item.get("status"),
                "additions": item.get("additions"),
                "deletions": item.get("deletions"),
            }
            for item in data
            if isinstance(item, dict)
        ]

    def pull_request_checks(self, number: int) -> dict[str, Any]:
        """Summarise CI for a PR head as a single state plus the individual runs."""
        pull = self.pull_request(number)
        head_sha = pull.get("headSha")
        if not head_sha:
            return {"state": "unknown", "checks": [], "pullRequest": pull}

        checks: list[dict[str, Any]] = []
        combined = self._request("GET", f"/repos/{self.repo}/commits/{head_sha}/status") or {}
        for item in combined.get("statuses") or []:
            checks.append(
                {
                    "name": item.get("context"),
                    "state": item.get("state"),
                    "url": item.get("target_url"),
                    "kind": "status",
                }
            )
        runs = self._request(
            "GET",
            f"/repos/{self.repo}/commits/{head_sha}/check-runs",
            params={"per_page": 50},
        ) or {}
        for item in runs.get("check_runs") or []:
            conclusion = item.get("conclusion")
            state = conclusion or ("pending" if item.get("status") != "completed" else "unknown")
            checks.append(
                {
                    "name": item.get("name"),
                    "state": state,
                    "url": item.get("html_url"),
                    "kind": "check_run",
                }
            )

        return {
            "state": _aggregate_check_state(checks),
            "checks": checks,
            "pullRequest": pull,
        }

    def merge_pull_request(
        self,
        number: int,
        *,
        method: str = "squash",
        commit_title: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"merge_method": method}
        if commit_title:
            payload["commit_title"] = commit_title[:250]
        data = self._request("PUT", f"/repos/{self.repo}/pulls/{number}/merge", json=payload) or {}
        return {
            "merged": bool(data.get("merged")),
            "sha": data.get("sha"),
            "message": data.get("message"),
        }

    @staticmethod
    def _public_pull_request(data: dict[str, Any]) -> dict[str, Any]:
        head = data.get("head") or {}
        return {
            "number": data.get("number"),
            "title": data.get("title"),
            "state": data.get("state"),
            "draft": data.get("draft"),
            "url": data.get("html_url"),
            "headRef": head.get("ref"),
            "headSha": head.get("sha"),
            "baseRef": (data.get("base") or {}).get("ref"),
            "createdAt": data.get("created_at"),
            "updatedAt": data.get("updated_at"),
            "mergedAt": data.get("merged_at"),
            "merged": bool(data.get("merged")),
            "mergeable": data.get("mergeable"),
            "mergeableState": data.get("mergeable_state"),
            "changedFiles": data.get("changed_files"),
            "additions": data.get("additions"),
            "deletions": data.get("deletions"),
        }


FAILING_CHECK_STATES = {"failure", "error", "timed_out", "cancelled", "action_required", "startup_failure"}
PASSING_CHECK_STATES = {"success", "neutral", "skipped"}


def _aggregate_check_state(checks: list[dict[str, Any]]) -> str:
    """Collapse many checks into one state, worst-case first."""
    states = {str(check.get("state") or "").lower() for check in checks}
    if not states:
        return "none"
    if states & FAILING_CHECK_STATES:
        return "failing"
    if "pending" in states or "queued" in states or "in_progress" in states:
        return "pending"
    if states <= PASSING_CHECK_STATES:
        return "passing"
    return "unknown"
