"""Checks for the ESPI issuer-name map: how it is filled, and how it is protected.

The map decides which holdings get searched for regulatory filings, so two
failures matter more than any feature: losing a name the owner picked, and
attributing one company's filing to a different holding. Most of what follows
pins those two.
"""

import asyncio
import json
import sys

import espi_sources
import server

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        FAILED.append(name)


class FakeStore:
    """A brain store whose reads can be made to fail, counting every write."""

    def __init__(self, settings=None, read_raises=False):
        self.settings = dict(settings or {})
        self.read_raises = read_raises
        self.writes = []

    def get_setting(self, key):
        if self.read_raises:
            raise RuntimeError("supabase read timed out")
        return self.settings.get(key)

    def set_setting(self, key, value):
        clean = str(value or "").strip()
        if not clean:
            raise ValueError("key and value are required")
        self.writes.append((key, clean))
        self.settings[key] = clean


BOOK = {
    "LPP.WA": {"weight": 0.075, "type": "Long", "currency": "PLN", "country": "POL", "sector": "Cons. Cyclical"},
    "BDX.WA": {"weight": 0.05, "type": "Short", "currency": "PLN", "country": "POL", "sector": "Industrials"},
    "SPR.WA": {"weight": 0.075, "type": "Long", "currency": "PLN", "country": "POL", "sector": "Technology"},
    "ETFBW20TR.WA": {"weight": 0.075, "type": "Short", "currency": "PLN", "country": "POL", "sector": "Index/ETF"},
    "META": {"weight": 0.1, "type": "Long", "currency": "USD", "country": "USA", "sector": "Comm. Services"},
}

TEN_NAMES = {
    "LPP.WA": "LPP", "BDX.WA": "BUDIMEX SA", "SPR.WA": "SPYROSOFT S.A.",
}


class Patched:
    """Swap module globals for the duration of a block, then put them back."""

    def __init__(self, **values):
        self.values = values
        self.previous = {}

    def __enter__(self):
        for name, value in self.values.items():
            self.previous[name] = getattr(server, name)
            setattr(server, name, value)
        return self

    def __exit__(self, *_):
        for name, value in self.previous.items():
            setattr(server, name, value)
        return False


class FakeRisk:
    @staticmethod
    def get_all_position_configs(portfolio="main"):
        return BOOK


def run(coro):
    return asyncio.run(coro)


print("Book split")
with Patched(risk=FakeRisk()):
    tickers, excluded = server._espi_book_tickers("main")
check("only Polish holdings are considered", tickers == ["BDX.WA", "LPP.WA", "SPR.WA"], tickers)
check("an index tracker is excluded, not called unresolved", excluded == ["ETFBW20TR.WA"], excluded)


print("A name must be a name")
check("a blank name is rejected", not server._usable_issuer_name("BDX.WA", "  "))
check("the ticker itself is rejected", not server._usable_issuer_name("BDX.WA", "BDX.WA"))
check("case does not smuggle it through", not server._usable_issuer_name("BDX.WA", "bdx.wa"))
# The guard must be an exact comparison, never a length floor: LPP is a real
# three-character issuer name identical to its own ticker root.
check("a genuinely short name survives", server._usable_issuer_name("LPP.WA", "LPP"))
check("a normal name survives", server._usable_issuer_name("BDX.WA", "BUDIMEX SA"))


print("An unreadable cache never overwrites stored names")
store = FakeStore({server.ESPI_ISSUER_NAMES_SETTING: json.dumps(TEN_NAMES)}, read_raises=True)
with Patched(risk=FakeRisk(), brain_store=store):
    state = run(server._espi_issuer_names(store, "main"))
check("the read failure is reported, not swallowed", bool(state["cacheError"]), state)
check("no names are claimed from a failed read", state["names"] == {}, state["names"])
check("nothing was written", store.writes == [], store.writes)

# The job is the only thing that can write after a provider lookup, so it is the
# path that could destroy the map. It must refuse to run on an unreadable cache.
resolver_calls = []


def counting_resolver(tickers):
    resolver_calls.append(list(tickers))
    return {t: f"RESOLVED {t}" for t in tickers}, {}


server.espi_issuer_job.update({"running": False})
with Patched(risk=FakeRisk(), brain_store=store, _resolve_issuer_names_from_market=counting_resolver):
    run(server._run_espi_issuer_lookup_job("main"))
check("the lookup job refuses to run on an unreadable cache", store.writes == [], store.writes)
check("and does not call the provider either", resolver_calls == [], resolver_calls)
check("the stored map is untouched",
      json.loads(store.settings[server.ESPI_ISSUER_NAMES_SETTING]) == TEN_NAMES)


print("Partial progress is saved as it happens")
store = FakeStore({})
resolver_calls.clear()


def flaky_resolver(tickers):
    resolver_calls.append(list(tickers))
    ticker = tickers[0]
    if ticker == "LPP.WA":
        return {}, {ticker: "provider said nothing"}
    return {ticker: f"NAME {ticker}"}, {}


server.espi_issuer_job.update({"running": False})
with Patched(risk=FakeRisk(), brain_store=store, _resolve_issuer_names_from_market=flaky_resolver):
    run(server._run_espi_issuer_lookup_job("main"))
saved = json.loads(store.settings[server.ESPI_ISSUER_NAMES_SETTING])
check("every ticker was attempted one at a time", len(resolver_calls) == 3, resolver_calls)
check("the two that answered were kept", sorted(saved) == ["BDX.WA", "SPR.WA"], saved)
check("the one that failed is absent", "LPP.WA" not in saved, saved)
# Saving per name rather than at the end is what survives a process killed mid-job.
name_writes = [w for w in store.writes if w[0] == server.ESPI_ISSUER_NAMES_SETTING]
check("names were written as they arrived", len(name_writes) == 2, name_writes)
meta = json.loads(store.settings[server.ESPI_ISSUER_META_SETTING])
check("the failure is recorded with a reason", meta["LPP.WA"]["lastError"] == "provider said nothing", meta)
check("a success records its source", meta["BDX.WA"]["source"] == "provider", meta)


print("A failed lookup is not retried immediately")
resolver_calls.clear()
server.espi_issuer_job.update({"running": False})
with Patched(risk=FakeRisk(), brain_store=store, _resolve_issuer_names_from_market=flaky_resolver):
    run(server._run_espi_issuer_lookup_job("main"))
check("the cooling-down ticker is not asked about again", resolver_calls == [], resolver_calls)

# ...but a stale failure is retried.
stale = json.loads(store.settings[server.ESPI_ISSUER_META_SETTING])
stale["LPP.WA"]["at"] = "2020-01-01T00:00:00Z"
store.settings[server.ESPI_ISSUER_META_SETTING] = json.dumps(stale)
resolver_calls.clear()
server.espi_issuer_job.update({"running": False})
with Patched(risk=FakeRisk(), brain_store=store, _resolve_issuer_names_from_market=flaky_resolver):
    run(server._run_espi_issuer_lookup_job("main"))
check("an old failure is retried", resolver_calls == [["LPP.WA"]], resolver_calls)


print("Only one lookup runs at a time")
server.espi_issuer_job.update({"running": True})
with Patched(risk=FakeRisk(), brain_store=FakeStore({})):
    check("a second queue attempt is refused", server._queue_espi_issuer_lookup("main") is False)
server.espi_issuer_job.update({"running": False})


print("Verification separates one issuer from two")
listing_html = open("fixtures/espi_listing.html", encoding="utf-8").read()


def fixture_get(url):
    return listing_html


def verify(name, get=fixture_get):
    original = espi_sources.fetch_listing

    def patched(query=None, start=None, end=None, max_pages=1, timeout=0, get_=None, **kwargs):
        return original(query=query, start=start, end=end, max_pages=1, timeout=timeout, get=get)

    espi_sources.fetch_listing = patched
    try:
        return run(server._verify_issuer_name(name))
    finally:
        espi_sources.fetch_listing = original


checked = verify("SYNEKTIK S.A.")
check("a real issuer is found", checked["filings"] == 2, checked)
check("and is unambiguous", checked["ambiguous"] is False, checked)
check("the canonical PAP string comes back", checked["canonical"] == "SYNEKTIK S.A.", checked)

checked = verify("SANWIL")
# Storing the PAP string rather than the typed one is the whole point: it is what
# match_ticker will compare filings against later.
check("a partial name resolves to the PAP spelling", checked["canonical"] == "SANWIL HOLDING SA", checked)

checked = verify("BUDIMEX")
check("a name with no filings says so", checked["filings"] == 0, checked)
check("and offers no canonical form", checked["canonical"] is None, checked)

# The assertion that matters most. issuer_matches accepts a four-character
# prefix, so one typed name can match two different companies; a bare count of
# "2 filings" would look clean while half the rows were the wrong issuer.
two_issuers = [
    {"issuer": "BUDIMEX SA", "subject": "Raport", "date": "2026-08-21", "nodeId": "1", "url": "u1"},
    {"issuer": "BUDIMEX NIERUCHOMOŚCI SA", "subject": "Raport", "date": "2026-08-20", "nodeId": "2", "url": "u2"},
]
original_fetch = espi_sources.fetch_listing
espi_sources.fetch_listing = lambda *a, **k: {"entries": two_issuers, "pagesRead": 1, "truncated": False}
try:
    checked = run(server._verify_issuer_name("BUDIMEX"))
finally:
    espi_sources.fetch_listing = original_fetch
check("a prefix matching two companies is called ambiguous", checked["ambiguous"] is True, checked)
check("and both are named with their counts",
      checked["matchedIssuers"] == {"BUDIMEX SA": 1, "BUDIMEX NIERUCHOMOŚCI SA": 1}, checked)
check("no canonical form is offered when it is ambiguous", checked["canonical"] is None, checked)

check("a four-character name is flagged as too short", verify("BEST")["shortName"] is True)
check("a longer name is not", verify("SYNEKTIK S.A.")["shortName"] is False)


print("Candidates come from real filings")
candidates = espi_sources.issuer_candidates(espi_sources.parse_listing(listing_html))
check("one entry per distinct issuer", len(candidates) == 28, len(candidates))
check("the most-filed issuer is first", candidates[0]["filings"] == 2, candidates[0])
# The raw PAP string, not its normalised form: the normalised form matches nothing.
check("the raw PAP spelling is preserved",
      any(c["name"] == "SYNEKTIK S.A." for c in candidates))
check("each candidate carries a filing to recognise it by",
      all(c.get("sampleNodeId") and c.get("sampleUrl") and c.get("latestDate") for c in candidates))

print("The ticker-root marker states a fact, not a verdict")
check("LPP starts with LPP", espi_sources.candidate_starts_with_root("LPP SA", "LPP.WA"))
check("AGORA starts with AGO", espi_sources.candidate_starts_with_root("AGORA S.A.", "AGO.WA"))
# It is silent where the ticker is an abbreviation rather than a prefix.
check("BUDIMEX does not start with BDX", not espi_sources.candidate_starts_with_root("BUDIMEX SA", "BDX.WA"))
check("BENEFIT SYSTEMS does not start with BFT", not espi_sources.candidate_starts_with_root("BENEFIT SYSTEMS S.A.", "BFT.WA"))
# And it does fire on SPRINT for SPR.WA, which is Spyrosoft. That is why the
# marker is named for what it literally tests and must be labelled the same way.
check("it fires on SPRINT for SPR, so the label must say 'starts with'",
      espi_sources.candidate_starts_with_root("SPRINT S.A.", "SPR.WA"))


print("The digest stops short instead of losing finished work")
calls = []


def slow_get(url):
    calls.append(url)
    return listing_html


ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0, 100.0])
result = espi_sources.digest_for_holdings(
    {"AAA.WA": "SYNEKTIK S.A.", "BBB.WA": "SANWIL HOLDING SA", "CCC.WA": "ZAMET SA"},
    espi_sources.date(2026, 8, 21),
    espi_sources.date(2026, 8, 21),
    max_pages=1,
    get=slow_get,
    deadline_seconds=50.0,
    now=lambda: next(ticks),
)
check("the first issuer was queried", result["queriedTickers"] == ["AAA.WA"], result["queriedTickers"])
check("the rest are reported as not queried, not as silent zeros",
      sorted(result["failures"]) == ["BBB.WA", "CCC.WA"], result["failures"])
check("and the reason says so", all("not queried" in r for r in result["failures"].values()), result["failures"])
check("the deadline is announced", result["deadlineHit"] is True, result)
check("the finished issuer's filings survive", len(result["entries"]) == 2, result["entries"])


print("Names harvested from the quality crawl")
store = FakeStore({})
positions = [
    {"ticker": "LPP.WA", "name": "LPP SA"},
    {"ticker": "BDX.WA", "name": "BDX.WA"},          # provider said nothing; this is the ticker
    {"ticker": "SPR.WA"},                             # the error branch emits no name at all
    {"ticker": "META", "name": "Meta Platforms, Inc."},
]
with Patched(risk=FakeRisk(), brain_store=store):
    run(server._harvest_issuer_names_from_quality(positions, "main"))
saved = json.loads(store.settings[server.ESPI_ISSUER_NAMES_SETTING])
check("a real name is kept for free", saved == {"LPP.WA": "LPP SA"}, saved)
# Storing "BDX.WA" would remove BDX from the unresolved list, stop anything
# retrying it, and turn a visible gap into a permanent silent zero.
check("the ticker-as-name is not stored", "BDX.WA" not in saved, saved)
check("a missing name key does not crash the harvest", "SPR.WA" not in saved, saved)
check("a non-Polish holding is ignored", "META" not in saved, saved)

# A stored name always wins: a background crawl must not outrank a picked name.
store = FakeStore({server.ESPI_ISSUER_NAMES_SETTING: json.dumps({"LPP.WA": "LPP"})})
with Patched(risk=FakeRisk(), brain_store=store):
    run(server._harvest_issuer_names_from_quality([{"ticker": "LPP.WA", "name": "LPP SA"}], "main"))
check("an existing name is never overwritten by the harvest", store.writes == [], store.writes)


if FAILED:
    print(f"\n{len(FAILED)} ESPI issuer check(s) failed.")
    sys.exit(1)
print("\nAll ESPI issuer-name checks passed.")
