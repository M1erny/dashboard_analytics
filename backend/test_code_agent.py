"""Guardrail checks for the Brain's self-build agent.

These cover the parts that decide whether a machine-written change is allowed to
reach a branch at all: the write allowlist, the plan validator, and anchored
replacements against real file contents.
"""

import code_agent


TREE = [
    {"path": "AGENTS.md", "size": 1200, "sha": "a1"},
    {"path": "README.md", "size": 18000, "sha": "a2"},
    {"path": "package.json", "size": 1170, "sha": "a3"},
    {"path": "src/App.tsx", "size": 900, "sha": "a4"},
    {"path": "src/components/Dashboard.tsx", "size": 40000, "sha": "a5"},
    {"path": "src/components/dashboard/FxExposureWidget.tsx", "size": 8000, "sha": "a6"},
    {"path": "src/components/dashboard/MoatWidget.tsx", "size": 7000, "sha": "a7"},
    {"path": "backend/server.py", "size": 190000, "sha": "a8"},
    {"path": "backend/portfolios/main.json", "size": 4000, "sha": "a9"},
    {"path": "backend/test_calculations.py", "size": 9000, "sha": "b1"},
    {"path": ".github/workflows/portfolio-history.yml", "size": 600, "sha": "b2"},
    {"path": "donkey.ico", "size": 84567, "sha": "b3"},
]

EXISTING = {entry["path"] for entry in TREE}


class FakeGitHub:
    """Stands in for GitHubClient, serving fixed file contents."""

    base_branch = "main"

    def __init__(self, files: dict[str, str]):
        self.files = dict(files)
        self.reads: list[str] = []

    def read_file(self, path: str, ref: str | None = None) -> str | None:
        self.reads.append(path)
        return self.files.get(path)


def expect_error(fragment: str, func, *args, **kwargs) -> str:
    try:
        func(*args, **kwargs)
    except ValueError as error:
        message = str(error)
        assert fragment.lower() in message.lower(), f"expected {fragment!r} in {message!r}"
        return message
    raise AssertionError(f"expected a ValueError mentioning {fragment!r}")


# --- Write allowlist -------------------------------------------------------

assert code_agent.check_writable_path("src/components/dashboard/CashWidget.tsx") == "src/components/dashboard/CashWidget.tsx"
assert code_agent.check_writable_path("./backend/server.py") == "backend/server.py"
assert code_agent.check_writable_path("docs/new-widget.md") == "docs/new-widget.md"
assert code_agent.check_writable_path("README.md") == "README.md"

expect_error("traversal", code_agent.check_writable_path, "../../etc/passwd")
expect_error("traversal", code_agent.check_writable_path, "./../src/App.tsx")
expect_error("absolute", code_agent.check_writable_path, "/etc/hosts")
expect_error("forward slashes", code_agent.check_writable_path, "src\\App.tsx")
expect_error("dot-directories", code_agent.check_writable_path, ".github/workflows/deploy.yml")
expect_error("dot-directories", code_agent.check_writable_path, "backend/.env")
expect_error("not writable", code_agent.check_writable_path, "public/logo.png")
expect_error("protected directory", code_agent.check_writable_path, "backend/portfolios/main.json")
expect_error("protected", code_agent.check_writable_path, "AGENTS.md")
expect_error("protected", code_agent.check_writable_path, "vite.config.ts")
expect_error("outside the writable roots", code_agent.check_writable_path, "convert_icon.py")

# Dependency manifests and the guardrail modules need an explicit opt-in.
expect_error("dependency manifest", code_agent.check_writable_path, "package.json")
assert code_agent.check_writable_path("package.json", allow_dependencies=True) == "package.json"
expect_error("guardrails", code_agent.check_writable_path, "backend/code_agent.py")
assert code_agent.check_writable_path("backend/code_agent.py", allow_self_edit=True) == "backend/code_agent.py"

# --- Secret scanning -------------------------------------------------------

expect_error("Google API key", code_agent.scan_for_secrets, "src/x.ts", "const key = 'AIza" + "B" * 35 + "';")
expect_error("database password", code_agent.scan_for_secrets, "src/x.ts", "postgresql://user:hunter2@db.example.com:5432/x")
code_agent.scan_for_secrets("src/x.ts", "const key = import.meta.env.VITE_API_URL;")

# --- Context selection -----------------------------------------------------

selected = code_agent.select_context_files(TREE, "Add an FX exposure widget next to the moat widget", limit=8)
assert "src/components/dashboard/FxExposureWidget.tsx" in selected
assert "src/components/dashboard/MoatWidget.tsx" in selected
assert "AGENTS.md" in selected and "src/App.tsx" in selected
assert "backend/portfolios/main.json" not in selected
assert "donkey.ico" not in selected
assert ".github/workflows/portfolio-history.yml" not in selected

# A request that matches nothing by filename still gets somewhere to start.
vague = code_agent.select_context_files(TREE, "make it look nicer please", limit=6)
assert "src/components/Dashboard.tsx" in vague

# Tests and debug scripts are ranked below real source.
assert code_agent.score_context_file("backend/test_calculations.py", ["calculations"]) < code_agent.score_context_file(
    "backend/server.py", ["server"]
)

# --- Context assembly flags truncated files --------------------------------

github = FakeGitHub(
    {
        "AGENTS.md": "# Agent Instructions\n",
        "package.json": '{"name": "dashboard"}\n',
        "src/App.tsx": "export default function App() { return null; }\n",
        "backend/server.py": "x = 1\n" * 40_000,
    }
)
context = code_agent.build_repo_context(
    github,
    TREE,
    "change the server routes",
    ref="deadbeef",
    limit=4,
    total_chars=50_000,
    max_file_chars=1_000,
)
truncated = {item["path"]: item["truncated"] for item in context["files"]}
assert truncated["backend/server.py"] is True
assert truncated["AGENTS.md"] is False
assert "backend/server.py" not in context["completePaths"]
assert "AGENTS.md" in context["completePaths"]

# --- Plan validation -------------------------------------------------------

expect_error("no file changes", code_agent.validate_plan, {"files": []}, complete_paths=set(), existing_paths=EXISTING)
expect_error(
    "declined this request",
    code_agent.validate_plan,
    {"files": [], "unsupported": "This needs a new charting dependency."},
    complete_paths=set(),
    existing_paths=EXISTING,
)
expect_error(
    "above the",
    code_agent.validate_plan,
    {"files": [{"path": f"src/f{i}.ts", "action": "write", "contents": "x", "reason": "r"} for i in range(20)]},
    complete_paths=set(),
    existing_paths=EXISTING,
)

# A partially seen file cannot be rewritten wholesale.
expect_error(
    "cannot be rewritten",
    code_agent.validate_plan,
    {"files": [{"path": "backend/server.py", "action": "write", "contents": "print(1)", "reason": "r"}]},
    complete_paths=set(),
    existing_paths=EXISTING,
)

# A brand new file is a legitimate write even though nothing was seen.
new_file_plan = {
    "summary": "s",
    "rationale": "r",
    "commitMessage": "Add a cash widget",
    "files": [
        {
            "path": "src/components/dashboard/CashWidget.tsx",
            "action": "write",
            "contents": "export const CashWidget = () => null;\n",
            "reason": "New widget",
        }
    ],
}
accepted = code_agent.validate_plan(new_file_plan, complete_paths=set(), existing_paths=EXISTING)
assert len(accepted) == 1 and accepted[0]["action"] == "write"

expect_error(
    "does not exist",
    code_agent.validate_plan,
    {"files": [{"path": "src/components/Missing.tsx", "action": "replace", "find": "a", "replace": "b", "reason": "r"}]},
    complete_paths=set(),
    existing_paths=EXISTING,
)
expect_error(
    "does not exist",
    code_agent.validate_plan,
    {"files": [{"path": "src/components/Missing.tsx", "action": "delete", "reason": "r"}]},
    complete_paths=set(),
    existing_paths=EXISTING,
)
expect_error(
    "appears twice",
    code_agent.validate_plan,
    {
        "files": [
            {"path": "src/App.tsx", "action": "write", "contents": "a", "reason": "r"},
            {"path": "src/App.tsx", "action": "write", "contents": "b", "reason": "r"},
        ]
    },
    complete_paths={"src/App.tsx"},
    existing_paths=EXISTING,
)

# --- Anchored replacement --------------------------------------------------

APP_SOURCE = """import Dashboard from './components/Dashboard';

export default function App() {
    return <Dashboard />;
}
"""

github = FakeGitHub({"src/App.tsx": APP_SOURCE})
changes = code_agent.validate_plan(
    {
        "files": [
            {
                "path": "src/App.tsx",
                "action": "replace",
                "find": "    return <Dashboard />;",
                "replace": "    return <Dashboard compact />;",
                "reason": "Pass the new prop",
            }
        ]
    },
    complete_paths={"src/App.tsx"},
    existing_paths=EXISTING,
)
applied = code_agent.apply_changes(github, changes, ref="deadbeef")
assert len(applied) == 1
assert "compact" in applied[0]["contents"]
assert applied[0]["before"] == APP_SOURCE

# Two replacements on one file stack into a single write.
stacked = code_agent.apply_changes(
    FakeGitHub({"src/App.tsx": APP_SOURCE}),
    code_agent.validate_plan(
        {
            "files": [
                {
                    "path": "src/App.tsx",
                    "action": "replace",
                    "find": "import Dashboard from './components/Dashboard';",
                    "replace": "import Dashboard from './components/Dashboard';\nimport { CashWidget } from './components/dashboard/CashWidget';",
                    "reason": "Import the widget",
                },
                {
                    "path": "src/App.tsx",
                    "action": "replace",
                    "find": "    return <Dashboard />;",
                    "replace": "    return <><Dashboard /><CashWidget /></>;",
                    "reason": "Render the widget",
                },
            ]
        },
        complete_paths={"src/App.tsx"},
        existing_paths=EXISTING,
    ),
    ref="deadbeef",
)
assert len(stacked) == 1
assert "CashWidget" in stacked[0]["contents"]
assert stacked[0]["contents"].count("import Dashboard") == 1
assert stacked[0]["before"] == APP_SOURCE

# A stale or ambiguous anchor is refused rather than guessed at.
expect_error(
    "does not appear",
    code_agent.apply_changes,
    FakeGitHub({"src/App.tsx": APP_SOURCE}),
    [{"path": "src/App.tsx", "action": "replace", "find": "return <Sidebar />;", "replace": "x", "reason": "r"}],
    ref="deadbeef",
)
expect_error(
    "appears 2 times",
    code_agent.apply_changes,
    FakeGitHub({"src/App.tsx": "const a = 1;\nconst a = 1;\n"}),
    [{"path": "src/App.tsx", "action": "replace", "find": "const a = 1;", "replace": "const a = 2;", "reason": "r"}],
    ref="deadbeef",
)

# --- Diff preview and branch naming ---------------------------------------

diff = code_agent.change_diff(applied[0])
assert "-    return <Dashboard />;" in diff
assert "+    return <Dashboard compact />;" in diff

created = code_agent.change_diff({"path": "src/New.tsx", "action": "write", "before": "", "contents": "export const x = 1;\n"})
assert "/dev/null" in created

branch = code_agent.build_branch_name("Add a cash widget to the dashboard", "Add a cash drag widget")
assert branch.startswith("brain/self-build/")
assert "add-a-cash-drag-widget" in branch

# --- Pull request body ----------------------------------------------------

body = code_agent.build_pull_request_body(
    request="Add a cash drag widget",
    plan={"summary": "Adds a widget.", "rationale": "Because.", "risks": ["Untested against live data."]},
    applied=applied,
    model="gemini-3.5-flash",
    base_sha="0123456789abcdef",
    context_paths=["src/App.tsx"],
)
assert "Add a cash drag widget" in body
assert "Untested against live data." in body
assert "`src/App.tsx`" in body
assert "Nothing was merged automatically" in body

# --- Size caps bound what is written, not what already exists --------------

BIG_SERVER = "# server\n" + ("x = 1\n" * 50_000)
assert len(BIG_SERVER) > code_agent.MAX_FILE_CHARS

# An anchored edit to an already-oversized file is the whole point of `replace`.
edited = code_agent.apply_changes(
    FakeGitHub({"backend/server.py": BIG_SERVER}),
    [{"path": "backend/server.py", "action": "replace", "find": "# server", "replace": "# server v2", "reason": "r"}],
    ref="deadbeef",
)
assert edited[0]["contents"].startswith("# server v2")
assert len(edited[0]["contents"]) == len(BIG_SERVER) + 3

# Growth beyond the cap in one change is still refused.
expect_error(
    "would grow by",
    code_agent.apply_changes,
    FakeGitHub({"backend/server.py": BIG_SERVER}),
    [
        {
            "path": "backend/server.py",
            "action": "replace",
            "find": "# server",
            "replace": "# server" + ("y" * (code_agent.MAX_FILE_CHARS + 10)),
            "reason": "r",
        }
    ],
    ref="deadbeef",
)


# --- Full pipeline ---------------------------------------------------------


class PipelineGitHub(FakeGitHub):
    """FakeGitHub plus the write side, recording what would reach GitHub."""

    repo = "m1erny/dashboard_analytics"

    def __init__(self, files: dict[str, str], open_proposals: int = 0):
        super().__init__(files)
        self.open_proposals = open_proposals
        self.calls: list[tuple] = []
        self.pr_body = ""

    def list_pull_requests(self, **kwargs):
        self.calls.append(("list_pull_requests",))
        return [{"number": n} for n in range(self.open_proposals)]

    def branch_head(self, branch=None):
        return "a" * 40

    def list_tree(self, ref=None):
        return [{"path": path, "size": len(body), "sha": "s"} for path, body in self.files.items()]

    def create_branch(self, branch, sha):
        self.calls.append(("create_branch", branch))

    def commit_files(self, *, branch, parent_sha, files, message):
        self.calls.append(("commit_files", [(item["path"], item["action"]) for item in files]))
        for change in files:
            if change["action"] == "delete":
                self.files.pop(change["path"], None)
            else:
                self.files[change["path"]] = change["contents"]
        return {"commitSha": "b" * 40}

    def open_pull_request(self, *, title, head, body, base=None, draft=False):
        self.calls.append(("open_pull_request", title))
        self.pr_body = body
        return {"number": 42, "title": title, "url": "https://example.invalid/pull/42", "headRef": head}

    def add_labels(self, number, labels):
        self.calls.append(("add_labels", number))


class FakeGemini:
    def __init__(self, plan: dict):
        self.plan = plan
        self.prompt = ""
        self.kwargs: dict = {}

    def generate_json(self, prompt, **kwargs):
        self.prompt = prompt
        self.kwargs = kwargs
        return self.plan


REPO_FILES = {
    "AGENTS.md": "# Agent Instructions\n\nPortfolio history is accounting data.\n",
    "package.json": '{"dependencies": {"recharts": "^3.6.0"}}\n',
    "src/App.tsx": APP_SOURCE,
    "src/components/Dashboard.tsx": "export default function Dashboard() { return null; }\n",
    "backend/server.py": BIG_SERVER,
}

WIDGET_PLAN = {
    "summary": "Adds a cash drag widget and renders it in App.",
    "rationale": "App.tsx is where the shell lives.",
    "commitMessage": "Add a cash drag widget to the dashboard shell",
    "risks": ["The percentage is computed client side."],
    "files": [
        {
            "path": "src/components/dashboard/CashDragWidget.tsx",
            "action": "write",
            "reason": "New widget",
            "contents": "export const CashDragWidget = () => <div>cash</div>;\n",
        },
        {
            "path": "src/App.tsx",
            "action": "replace",
            "reason": "Import the widget",
            "find": "import Dashboard from './components/Dashboard';",
            "replace": "import Dashboard from './components/Dashboard';\nimport { CashDragWidget } from './components/dashboard/CashDragWidget';",
        },
        {
            "path": "src/App.tsx",
            "action": "replace",
            "reason": "Render the widget",
            "find": "    return <Dashboard />;",
            "replace": "    return <><Dashboard /><CashDragWidget /></>;",
        },
        {
            "path": "backend/server.py",
            "action": "replace",
            "reason": "Note the new route",
            "find": "# server",
            "replace": "# server (cash exposed)",
        },
    ],
}

pipeline_github = PipelineGitHub(dict(REPO_FILES))
pipeline_gemini = FakeGemini(WIDGET_PLAN)
result = code_agent.propose_code_change(
    pipeline_github,
    pipeline_gemini,
    request="Add a cash drag widget to the dashboard and render it in App.",
    open_pull_request=True,
)

# The prompt has to carry the house rules, the file map, and the truncation flag.
assert "Portfolio history is accounting data" in pipeline_gemini.prompt
assert "# Repository files" in pipeline_gemini.prompt
assert "src/App.tsx (complete file" in pipeline_gemini.prompt
assert "TRUNCATED" in pipeline_gemini.prompt
assert pipeline_gemini.kwargs["response_schema"] is code_agent.PLAN_SCHEMA
assert pipeline_gemini.kwargs["model"] == code_agent.DEFAULT_CODE_MODEL

# Two edits to one file become one commit write; the oversized file is edited in place.
committed = dict(next(call[1] for call in pipeline_github.calls if call[0] == "commit_files"))
assert committed == {
    "src/components/dashboard/CashDragWidget.tsx": "write",
    "src/App.tsx": "write",
    "backend/server.py": "write",
}, committed
assert pipeline_github.files["src/App.tsx"].count("import Dashboard") == 1
assert "CashDragWidget" in pipeline_github.files["src/App.tsx"]
assert pipeline_github.files["backend/server.py"].startswith("# server (cash exposed)")

assert result["action"] == "pull_request_opened"
assert result["branch"].startswith("brain/self-build/")
assert result["pullRequest"]["number"] == 42
assert {change["action"] for change in result["changes"]} == {"create", "edit"}
assert any("+import { CashDragWidget }" in change["diff"] for change in result["changes"])
assert "Nothing was merged automatically" in pipeline_github.pr_body

# Preview mode must not push or mutate anything.
preview_github = PipelineGitHub(dict(REPO_FILES))
preview = code_agent.propose_code_change(
    preview_github,
    FakeGemini(WIDGET_PLAN),
    request="Add a cash drag widget to the dashboard and render it in App.",
    open_pull_request=False,
)
assert preview["action"] == "previewed"
assert "pullRequest" not in preview
assert preview_github.calls == []
assert preview_github.files["src/App.tsx"] == APP_SOURCE
assert len(preview["changes"]) == 3

# A protected path is refused before a branch is created.
blocked_github = PipelineGitHub(dict(REPO_FILES))
expect_error(
    "protected directory",
    code_agent.propose_code_change,
    blocked_github,
    FakeGemini({**WIDGET_PLAN, "files": [{"path": "backend/portfolios/main.json", "action": "write", "reason": "r", "contents": "{}"}]}),
    request="Rewrite the portfolio book for me",
)
assert [call[0] for call in blocked_github.calls] == ["list_pull_requests"]

# The open-proposal ceiling stops a retry loop from flooding the repository.
expect_error(
    "already open",
    code_agent.propose_code_change,
    PipelineGitHub(dict(REPO_FILES), open_proposals=5),
    FakeGemini(WIDGET_PLAN),
    request="Add one more widget please",
)

print("Self-build agent guardrail checks passed.")
