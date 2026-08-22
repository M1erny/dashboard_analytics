"""The reasoning config has to match the model, or every answer costs a rejected call.

Gemini 3 models configure reasoning with `thinkingLevel`; older ones use a numeric
`thinkingBudget`. The family gate used to be the literal string "gemini-3.5", so
pointing the Brain at a 3.7 model sent it the legacy budget field, took a 400, and
only then retried without any thinking config — two round trips per answer, and
nothing on screen to say so. 3.7 Flash additionally rejects MINIMAL, which 3.5
accepts, so "as little thinking as possible" has to be mapped rather than passed
through.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gemini_client
from gemini_client import GeminiClient, resolve_thinking_level, uses_thinking_level

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        FAILURES.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  [FAIL] {name} {detail}")


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}


def _fake_client_factory(captured):
    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, params=None, json=None):
            captured.append({"url": url, "payload": json})
            return _FakeResponse()

    return _FakeClient


def sent_generation_config(model, thinking_level=None):
    """The generationConfig the client would actually put on the wire."""
    captured = []
    real_client = gemini_client.httpx.Client
    gemini_client.httpx.Client = _fake_client_factory(captured)
    try:
        client = GeminiClient(api_key="test-key", generation_model=model)
        if thinking_level is None:
            client.generate_text("question")
        else:
            # generate_text has no per-call level; _generate is the shared payload
            # builder both public entry points route through, and the thing under test.
            client._generate("question", thinking_level=thinking_level)
    finally:
        gemini_client.httpx.Client = real_client
    check(f"{model} issued exactly one request", len(captured) == 1, f"{len(captured)} requests")
    return captured[0]["payload"]["generationConfig"], captured[0]["url"]


def main():
    print("=" * 70)
    print("GEMINI MODEL CONFIG")
    print("=" * 70)

    # 1. The configured default. Asserted on the constant, not on an instance: a
    #    BRAIN_LLM_MODEL in the environment legitimately overrides the instance.
    check(
        "the default generation model is 3.7 Flash",
        gemini_client.DEFAULT_GENERATION_MODEL == "gemini-3.7-flash",
        gemini_client.DEFAULT_GENERATION_MODEL,
    )
    check(
        "the embedding model is untouched",
        gemini_client.DEFAULT_EMBEDDING_MODEL == "gemini-embedding-001",
        gemini_client.DEFAULT_EMBEDDING_MODEL,
    )

    # 2. The family gate covers the family, not one release.
    for model in ("gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.9-flash"):
        check(f"{model} uses thinkingLevel", uses_thinking_level(model))
    for model in ("gemini-2.0-flash", "gemini-1.5-pro", "gemini-embedding-001", "", "gemini-30-flash"):
        check(f"{model or '<empty>'} does not use thinkingLevel", not uses_thinking_level(model))

    # 3. MINIMAL is mapped only where it is not accepted.
    check("3.7 maps minimal to low", resolve_thinking_level("gemini-3.7-flash", "minimal") == "low")
    check("3.5 keeps minimal", resolve_thinking_level("gemini-3.5-flash-lite", "minimal") == "minimal")
    for level in ("low", "medium", "high"):
        check(f"3.7 passes {level} through", resolve_thinking_level("gemini-3.7-flash", level) == level)
        check(f"3.5 passes {level} through", resolve_thinking_level("gemini-3.5-flash", level) == level)
    check("an unknown level falls back, then maps", resolve_thinking_level("gemini-3.7-flash", "turbo") == "low")
    check("an empty level falls back, then maps", resolve_thinking_level("gemini-3.7-flash", "") == "low")
    check("None falls back on 3.5", resolve_thinking_level("gemini-3.5-flash", None) == "minimal")
    check("levels are sent lower-case", resolve_thinking_level("gemini-3.7-flash", "HIGH") == "high")

    # 4. What actually reaches the wire — the regression this exists to stop.
    config, url = sent_generation_config("gemini-3.7-flash")
    thinking = config.get("thinkingConfig") or {}
    check("3.7 is sent a thinkingLevel", "thinkingLevel" in thinking, str(thinking))
    check("3.7 is NOT sent the legacy thinkingBudget", "thinkingBudget" not in thinking, str(thinking))
    check("and that level is one 3.7 accepts", thinking.get("thinkingLevel") == "low", str(thinking))
    check("the model appears in the URL", "gemini-3.7-flash:generateContent" in url, url)

    config, _ = sent_generation_config("gemini-3.5-flash-lite")
    thinking = config.get("thinkingConfig") or {}
    check("3.5 still gets minimal", thinking.get("thinkingLevel") == "minimal", str(thinking))

    config, _ = sent_generation_config("gemini-3.7-flash", thinking_level="high")
    check(
        "an explicit level survives to the wire",
        (config.get("thinkingConfig") or {}).get("thinkingLevel") == "high",
        str(config.get("thinkingConfig")),
    )

    # A pre-3 model must still get the numeric budget form.
    config, _ = sent_generation_config("gemini-2.0-flash")
    thinking = config.get("thinkingConfig") or {}
    check("a pre-3 model gets thinkingBudget", "thinkingBudget" in thinking, str(thinking))
    check("and not a thinkingLevel", "thinkingLevel" not in thinking, str(thinking))

    # 5. Status reports both the requested level and the one actually sent, so a
    #    mapped value is visible rather than silently different from the setting.
    status = GeminiClient(api_key="test-key", generation_model="gemini-3.7-flash").status()
    check("status reports the effective level", status.get("thinkingLevel") == "low", str(status))
    check(
        "status also reports what was requested",
        status.get("thinkingLevelRequested") == gemini_client.DEFAULT_THINKING_LEVEL,
        str(status),
    )
    check("status names the model", status.get("generationModel") == "gemini-3.7-flash", str(status))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for failure in FAILURES:
            print(f"  - {failure}")
        sys.exit(1)
    print("All Gemini model config checks passed.")


if __name__ == "__main__":
    main()
