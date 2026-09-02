"""Checks that a failed market-data download cannot blank the dashboard.

yfinance does not raise when it is rate limited; it returns an empty frame and
records the 429 per ticker. Three things used to turn that into a total outage:
the empty frame was cached for the whole TTL, every failed ticker was retried
three times (a hundred-plus doomed requests, minutes long, on the event loop),
and a restarted process had nothing to fall back on. These checks pin the
behaviour that replaces it: a throttle is detected and ends the fetch at once,
the host is left alone for a cooldown, the last good frames are served from
memory or from the saved snapshot with honest provenance, and an empty result is
never stored as data.
"""

import logging
import sys
import time

import pandas as pd

import risk
import server

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        FAILED.append(name)


def good_frame(last="2026-01-06"):
    return pd.DataFrame(
        {"AAPL": [100.0, 101.0, 102.0], "CDR.WA": [200.0, 199.5, 201.25]},
        index=pd.to_datetime(["2026-01-02", "2026-01-03", last]),
    )


ONE_ROW = pd.DataFrame({"AAPL": [100.0]}, index=pd.to_datetime(["2026-01-02"]))


class FakeRisk:
    """Stands in for the risk module, serving a scripted sequence of fetches.

    An entry may be a frame (returned), an exception instance (raised), or the
    string "rate_limited" (raises MarketDataRateLimited like the guard does).
    """

    MarketDataRateLimited = risk.MarketDataRateLimited

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def fetch_data(self, portfolio_name="main"):
        self.calls += 1
        item = self.script.pop(0) if self.script else pd.DataFrame()
        if isinstance(item, str) and item == "rate_limited":
            raise risk.MarketDataRateLimited(600)
        if isinstance(item, Exception):
            raise item
        return item, pd.DataFrame({"PLNUSD=X": [0.25, 0.25, 0.26]}, index=item.index) if len(item) == 3 else pd.DataFrame(), item * 0 + 1000

    def normalize_to_base_currency(self, raw_prices, fx_rates, portfolio_name):
        return raw_prices

    def rate_limit_remaining(self):
        return 0.0


class FakeStore:
    def __init__(self, settings=None, read_raises=False, write_raises=False):
        self.settings = dict(settings or {})
        self.read_raises = read_raises
        self.write_raises = write_raises
        self.writes = []

    def get_setting(self, key):
        if self.read_raises:
            raise RuntimeError("store read failed")
        return self.settings.get(key)

    def set_setting(self, key, value):
        if self.write_raises:
            raise RuntimeError("store write failed")
        self.writes.append((key, value))
        self.settings[key] = value


def with_fakes(script, body, store=None):
    saved = (server.risk, server._data_cache, server.brain_store, dict(server._market_data_status), dict(server._market_snapshot_written))
    fake = FakeRisk(script)
    server.risk = fake
    server._data_cache = {}
    server.brain_store = store
    server._market_data_status = {}
    server._market_snapshot_written = {}
    try:
        return body(fake)
    finally:
        server.risk, server._data_cache, server.brain_store, status, written = saved
        server._market_data_status = status
        server._market_snapshot_written = written


def expire(portfolio_name="main"):
    """Age the cached entry past the TTL, as the passage of time would."""
    server._data_cache[portfolio_name]["timestamp"] -= server.CACHE_TTL + 1


# --------------------------------------------------------------------------- guard
print("\n=== Yahoo rate-limit guard (risk.py) ===")

risk.clear_rate_limit()
check(
    "yfinance's per-ticker 429 record is recognised",
    risk.download_errors_rate_limited({"CADUSD=X": "YFRateLimitError('Too Many Requests. Rate limited. Try after a while.')"}),
)
check(
    "an ordinary download error is not mistaken for a throttle",
    not risk.download_errors_rate_limited({"XYZ": "YFTzMissingError('No timezone found')"}),
)
check("no cooldown is pending initially", risk.rate_limit_remaining() == 0)

risk.note_rate_limit(now=1000.0)
check(
    "noting a throttle starts the cooldown",
    abs(risk.rate_limit_remaining(now=1000.0) - risk.RATE_LIMIT_COOLDOWN_SECONDS) < 1e-6,
)
check(
    "the cooldown runs out",
    risk.rate_limit_remaining(now=1000.0 + risk.RATE_LIMIT_COOLDOWN_SECONDS + 1) == 0,
)

# During the cooldown fetch_data must not touch Yahoo at all.
original_download = risk.yf.download
download_calls = {"n": 0}


def counting_download(*args, **kwargs):
    download_calls["n"] += 1
    return pd.DataFrame()


risk.yf.download = counting_download
try:
    risk.note_rate_limit()
    raised = None
    try:
        risk.fetch_data("main")
    except risk.MarketDataRateLimited as ex:
        raised = ex
    check("fetch_data fails fast during the cooldown", raised is not None)
    check("and makes no request while doing so", download_calls["n"] == 0, f"{download_calls['n']} calls")
    check(
        "the error names the wait in minutes",
        raised is not None and "min" in str(raised) and raised.retry_after > 0,
        str(raised),
    )

    # A throttled bulk download ends the fetch instead of starting the retry loop.
    # yfinance 1.x reports per-ticker failures only through its logger, in exactly
    # the form the Render log shows; the guard has to read that.
    def throttled_download(*args, **kwargs):
        download_calls["n"] += 1
        logging.getLogger("yfinance").error("\n1 Failed download:")
        logging.getLogger("yfinance").error("['CADUSD=X']: YFRateLimitError('Too Many Requests. Rate limited. Try after a while.')")
        return pd.DataFrame()

    risk.yf.download = throttled_download
    risk.clear_rate_limit()
    raised = None
    try:
        risk._guarded_download(["CADUSD=X"], start="2026-01-01")
    except risk.MarketDataRateLimited as ex:
        raised = ex
    check("a throttled batch, reported only via the log, raises from the guard", raised is not None)
    check("and arms the cooldown", risk.rate_limit_remaining() > 0)
    check("the guard made exactly one request", download_calls["n"] == 1, f"{download_calls['n']} calls")

    # Other failures logged by yfinance are not throttles and pass through.
    def failing_download(*args, **kwargs):
        logging.getLogger("yfinance").error("['ZZZZ']: YFTzMissingError('possibly delisted; no timezone found')")
        return pd.DataFrame()

    risk.yf.download = failing_download
    risk.clear_rate_limit()
    frame = risk._guarded_download(["ZZZZ"], start="2026-01-01")
    check("a delisted ticker does not trip the guard", frame.empty and risk.rate_limit_remaining() == 0)

    # A throttle raised as an exception (e.g. from the crumb fetch) is the same event.
    def raising_download(*args, **kwargs):
        raise RuntimeError("YFRateLimitError: Too Many Requests. Rate limited. Try after a while.")

    risk.yf.download = raising_download
    raised = None
    try:
        risk._guarded_download(["AAPL"], start="2026-01-01")
    except risk.MarketDataRateLimited as ex:
        raised = ex
    check("a throttle raised as an exception is caught the same way", raised is not None and risk.rate_limit_remaining() > 0)
    check("the capture handler is detached afterwards", not any(isinstance(h, risk._YahooLogCapture) for h in logging.getLogger("yfinance").handlers))

    # The whole of fetch_data, against the real portfolio config: a throttled bulk
    # download must end it in one request, not ~45 tickers x 3 retries x 1 s.
    risk.yf.download = throttled_download
    risk.clear_rate_limit()
    download_calls["n"] = 0
    started = time.time()
    raised = None
    try:
        risk.fetch_data("main")
    except risk.MarketDataRateLimited as ex:
        raised = ex
    elapsed = time.time() - started
    check("fetch_data stops at the throttled bulk download", raised is not None)
    check("with a single request, no retry loop", download_calls["n"] == 1, f"{download_calls['n']} calls")
    check("and returns in well under a second", elapsed < 2.0, f"{elapsed:.2f}s")
finally:
    risk.yf.download = original_download
    risk.clear_rate_limit()


# --------------------------------------------------------------------- memory cache
print("\n=== Market data cache: failed fetches ===")


def two_forced_fetches(fake):
    return server._get_cached_market_data(force=True), server._get_cached_market_data(force=True)


first, second = with_fakes([good_frame(), pd.DataFrame()], two_forced_fetches)
check("a good fetch is returned as usual", len(first[0]) == 3, f"got {first[0].shape}")
check("an empty fetch serves the previous snapshot", len(second[0]) == 3, f"got {second[0].shape}")

_, single_row = with_fakes([good_frame(), ONE_ROW], two_forced_fetches)
check("a one-row frame counts as a failed fetch, not as data", len(single_row[0]) == 3, f"got {single_row[0].shape}")


def rate_limited_after_success(fake):
    server._get_cached_market_data(force=True)
    fresh = server.market_data_status("main")
    served = server._get_cached_market_data(force=True)
    return fresh, served, server.market_data_status("main")


fresh, served, status = with_fakes([good_frame(), "rate_limited"], rate_limited_after_success)
check("a successful fetch reports fresh data with its market date", fresh["stale"] is False and fresh["asOf"] == "2026-01-06", str(fresh))
check("a throttled fetch serves the previous frames", len(served[0]) == 3, f"got {served[0].shape}")
check(
    "and reports them as stale, rate limited, with the retry wait",
    status["stale"] is True and status["reason"] == "rate_limited" and status["retryAfterSeconds"] == 600 and status["asOf"] == "2026-01-06",
    str(status),
)


def crash_after_success(fake):
    server._get_cached_market_data(force=True)
    served = server._get_cached_market_data(force=True)
    return served, server.market_data_status("main")


served, status = with_fakes([good_frame(), ConnectionError("dns failed")], crash_after_success)
check("a fetch that raises serves the previous frames instead of a 500", len(served[0]) == 3, f"got {served[0].shape}")
check("and says why", status["reason"] == "fetch_error" and "dns failed" in (status["message"] or ""), str(status))


def retry_after_failure(fake):
    server._get_cached_market_data(force=True)
    stamp_after_success = server._data_cache["main"]["timestamp"]
    expire()
    failed = server._get_cached_market_data(force=False)
    stamp_after_failure = server._data_cache["main"]["timestamp"] + server.CACHE_TTL + 1
    recovered = server._get_cached_market_data(force=False)
    return failed, recovered, fake.calls, stamp_after_success == stamp_after_failure, server.market_data_status("main")


(failed, recovered, calls, stamp_held, status) = with_fakes([good_frame(), pd.DataFrame(), good_frame("2026-01-07")], retry_after_failure)
check("a failed fetch does not refresh the cache timestamp", stamp_held, "the failure marked the stale snapshot as fresh")
check("an empty fetch is not stored, so the next request retries", calls == 3, f"fetch_data called {calls} times, expected 3")
check("the stale snapshot covers the failure", len(failed[0]) == 3, f"got {failed[0].shape}")
check("the retry's data is served once it succeeds", len(recovered[0]) == 3, f"got {recovered[0].shape}")
check("and the status returns to fresh", status["stale"] is False and status["asOf"] == "2026-01-07", str(status))


def cold_start(fake):
    return server._get_cached_market_data(force=True), fake.calls, server.market_data_status("main")


(cold, cold_calls, status) = with_fakes(["rate_limited"], cold_start)
check("with nothing cached and no snapshot, empty frames come back, not an exception", cold[0].empty and cold_calls == 1)
check("and the status says there is nothing to show", status["stale"] is True and status["asOf"] is None and status["reason"] == "rate_limited", str(status))


# ------------------------------------------------------------------- snapshot store
print("\n=== Market data snapshot: persistence across restarts ===")

data = (good_frame(), pd.DataFrame({"PLNUSD=X": [0.25, 0.25, 0.26]}, index=good_frame().index), good_frame() * 0 + 1000, good_frame())
encoded = server.encode_market_snapshot(data, "2026-01-06", 1_700_000_000.0)
decoded, as_of, fetched_at = server.decode_market_snapshot(encoded)
check("a snapshot round-trips its prices exactly", decoded[0].equals(data[0]), str(decoded[0]))
check("and its FX, volume and original-currency frames", decoded[1].equals(data[1]) and decoded[3].equals(data[3]) and (decoded[2].values == data[2].values).all())
check("keeping the market date and fetch time", as_of == "2026-01-06" and fetched_at == "2023-11-14T22:13:20Z", f"{as_of} {fetched_at}")
check("the index comes back as datetimes", str(decoded[0].index.dtype).startswith("datetime64"), str(decoded[0].index.dtype))
check("it is compact text", isinstance(encoded, str) and len(encoded) < 4000, f"{len(encoded)} chars")


def persist_once_per_day(fake):
    server._get_cached_market_data(force=True)
    server._get_cached_market_data(force=True)
    server._get_cached_market_data(force=True)
    return server.brain_store.writes


store = FakeStore()
writes = with_fakes([good_frame(), good_frame(), good_frame("2026-01-07")], persist_once_per_day, store=store)
keys = [k for k, _ in writes]
check("a good fetch saves the snapshot", len(writes) >= 1 and keys[0] == "market.snapshot.v1.main", str(keys))
check("the same market date is not saved twice; a new one is", len(writes) == 2, f"{len(writes)} writes")

failing_store = FakeStore(write_raises=True)
served = with_fakes([good_frame()], lambda fake: server._get_cached_market_data(force=True), store=failing_store)
check("a failing store does not fail the request", len(served[0]) == 3)


def cold_start_from_snapshot(fake):
    served = server._get_cached_market_data(force=True)
    status = server.market_data_status("main")
    stamp = server._data_cache["main"]["timestamp"]
    # Second request: still throttled, must serve the same snapshot without
    # needing the store again, and must have tried Yahoo again.
    again = server._get_cached_market_data(force=False)
    return served, status, stamp, again, fake.calls


seeded = FakeStore({"market.snapshot.v1.main": encoded})
served, status, stamp, again, calls = with_fakes(["rate_limited", "rate_limited"], cold_start_from_snapshot, store=seeded)
check("a cold process throttled by Yahoo serves the saved snapshot", len(served[0]) == 3 and list(served[0].columns) == ["AAPL", "CDR.WA"], f"got {served[0].shape}")
check("and labels it: stale, rate limited, dated", status["stale"] is True and status["reason"] == "rate_limited" and status["asOf"] == "2026-01-06" and status["fetchedAt"] == "2023-11-14T22:13:20Z", str(status))
check("the snapshot is stored as already expired so the next request retries", stamp == 0, f"timestamp {stamp}")
check("the next request did retry Yahoo and served the snapshot again", calls == 2 and len(again[0]) == 3, f"calls={calls}")

broken = FakeStore({"market.snapshot.v1.main": "not-a-snapshot"})
served, status = with_fakes(["rate_limited"], lambda fake: (server._get_cached_market_data(force=True), server.market_data_status("main")), store=broken)
check("a corrupt snapshot is skipped, not fatal", served[0].empty and status["asOf"] is None)

unreadable = FakeStore(read_raises=True)
served = with_fakes(["rate_limited"], lambda fake: server._get_cached_market_data(force=True), store=unreadable)
check("an unreadable store is skipped, not fatal", served[0].empty)

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s): {', '.join(FAILED)}")
    sys.exit(1)
print("All market data cache checks passed.")
