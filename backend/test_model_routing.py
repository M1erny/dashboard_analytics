"""Checks how a question is routed to a model, and what may be chosen.

Two tiers exist because a chat answer is read while you wait and a code proposal
is acted on. The routing has to be selectable from the dashboard without letting
the selection become a way to point requests somewhere other than Gemini.
"""

import json

import gemini_client
import server
from gemini_client import IMPORTANT_TIER, STANDARD_TIER, GeminiClient, clean_model_id


# --- a model id goes into the request path, so it is validated ---------------
assert clean_model_id("gemini-3.7-flash") == "gemini-3.7-flash"
# Google returns names as "models/x"; both spellings must resolve to the same id.
assert clean_model_id("models/gemini-3.7-flash") == "gemini-3.7-flash"
assert clean_model_id("  gemini-3.7-flash  ") == "gemini-3.7-flash"
for bad in (
    "../../v1beta/models/other",        # would climb out of the models path
    "gemini-3.7-flash:generateContent", # would append a second method
    "gemini-3.7-flash?key=leak",        # would inject a query parameter
    "gemini flash",
    "https://evil.example/models/x",
    "",
    None,
    "x" * 200,
):
    try:
        clean_model_id(bad)
    except ValueError:
        continue
    raise AssertionError(f"{bad!r} should have been refused as a model id")


# --- tier defaults ----------------------------------------------------------
client = GeminiClient(api_key="test-key", generation_model="gemini-3.7-flash")
defaults = client.routing_defaults()
assert defaults[STANDARD_TIER]["model"] == "gemini-3.7-flash"
# With no important model configured, the important tier is the same model
# thinking harder. Inventing the name of a larger model would 404 on first use.
assert defaults[IMPORTANT_TIER]["model"] == "gemini-3.7-flash"
assert defaults[IMPORTANT_TIER]["thinkingLevel"] == "high"
# 3.7 rejects MINIMAL, so the standard tier's stated level is what it will take.
assert defaults[STANDARD_TIER]["thinkingLevel"] in gemini_client.VALID_THINKING_LEVELS
assert defaults[STANDARD_TIER]["thinkingLevel"] != "minimal"


# --- a saved choice beats the environment, and says so ----------------------
resolved = server._merge_model_routing({})
for tier in (STANDARD_TIER, IMPORTANT_TIER):
    assert resolved[tier]["source"] == "environment", resolved

saved = server._merge_model_routing({IMPORTANT_TIER: {"model": "gemini-3.7-flash", "thinkingLevel": "medium"}})
assert saved[IMPORTANT_TIER]["source"] == "saved"
assert saved[IMPORTANT_TIER]["thinkingLevel"] == "medium"
# One tier being chosen must not drag the other off its default.
assert saved[STANDARD_TIER]["source"] == "environment"


# --- a broken setting falls back rather than raising ------------------------
for raw in (None, "", "not json", "[]", '{"standard": "gemini"}', '{"standard": {}}'):
    assert server._parse_model_routing(raw) == {}, raw

# A stored model that would escape the models path is dropped, not honoured.
assert server._parse_model_routing(json.dumps({"standard": {"model": "../../evil"}})) == {}
# An unknown thinking level is dropped while a valid model in the same entry survives.
mixed = server._parse_model_routing(json.dumps({"standard": {"model": "gemini-3.7-flash", "thinkingLevel": "ludicrous"}}))
assert mixed == {"standard": {"model": "gemini-3.7-flash"}}, mixed
# An unknown tier is ignored entirely.
assert server._parse_model_routing(json.dumps({"turbo": {"model": "gemini-3.7-flash"}})) == {}


# --- the tier a request asks for --------------------------------------------
assert server._resolve_task_tier("important") == IMPORTANT_TIER
assert server._resolve_task_tier("IMPORTANT") == IMPORTANT_TIER
assert server._resolve_task_tier("standard") == STANDARD_TIER
# An older client sending nothing, or a typo, gets the fast path rather than an error.
for value in (None, "", "deep", "expensive", "  "):
    assert server._resolve_task_tier(value) == STANDARD_TIER, value


# --- the catalogue keeps only what can actually answer a question ----------
class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, params=None):
        self.requests.append((url, dict(params or {})))
        return FakeResponse(self.pages.pop(0))


pages = [
    {
        "models": [
            {"name": "models/gemini-3.7-flash", "displayName": "Gemini 3.7 Flash",
             "supportedGenerationMethods": ["generateContent", "countTokens"],
             "inputTokenLimit": 1048576, "outputTokenLimit": 65536},
            {"name": "models/gemini-embedding-001", "displayName": "Embedding",
             "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/../escape", "supportedGenerationMethods": ["generateContent"]},
            "not-a-dict",
        ],
        "nextPageToken": "page-2",
    },
    {"models": [{"name": "models/aardvark-1", "supportedGenerationMethods": ["generateContent"]}]},
]
fake = FakeHttpClient(pages)
real_client = gemini_client.httpx.Client
gemini_client.httpx.Client = lambda **_: fake
try:
    models = client.list_models()
finally:
    gemini_client.httpx.Client = real_client

ids = [model["id"] for model in models]
# Embedding-only and malformed entries are gone; paging was followed.
assert ids == ["aardvark-1", "gemini-3.7-flash"], ids
assert len(fake.requests) == 2
assert fake.requests[1][1]["pageToken"] == "page-2"
flash = next(model for model in models if model["id"] == "gemini-3.7-flash")
assert flash["label"] == "Gemini 3.7 Flash"
assert flash["usesThinkingLevel"] is True
assert flash["inputTokenLimit"] == 1048576

print("Model routing checks passed.")
