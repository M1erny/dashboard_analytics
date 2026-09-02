"""Checks that a failed market-data download cannot blank the dashboard.

yfinance does not raise when it is rate limited; it returns an empty frame. The
cache used to store that frame like any other result, which pinned the failure
for the whole TTL and handed the same blank data to every other endpoint reading
it. These checks pin the two properties that stop that: an empty fetch is never
stored, and a previously good snapshot is served in its place.
"""

import sys

import pandas as pd

import server

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        FAILED.append(name)


def good_frame():
    return pd.DataFrame(
        {"AAPL": [100.0, 101.0, 102.0]},
        index=pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-06"]),
    )


ONE_ROW = pd.DataFrame({"AAPL": [100.0]}, index=pd.to_datetime(["2026-01-02"]))


class FakeRisk:
    """Stands in for the risk module, serving a scripted sequence of fetches."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = 0

    def fetch_data(self, portfolio_name="main"):
        self.calls += 1
        frame = self.frames.pop(0) if self.frames else pd.DataFrame()
        return frame, pd.DataFrame(), pd.DataFrame()

    def normalize_to_base_currency(self, raw_prices, fx_rates, portfolio_name):
        return raw_prices


def with_fake_risk(frames, body):
    original_risk = server.risk
    original_cache = server._data_cache
    fake = FakeRisk(frames)
    server.risk = fake
    server._data_cache = {}
    try:
        return body(fake)
    finally:
        server.risk = original_risk
        server._data_cache = original_cache


print("\n=== Market data cache: failed fetches ===")


def two_forced_fetches(fake):
    return server._get_cached_market_data(force=True), server._get_cached_market_data(force=True)


first, second = with_fake_risk([good_frame(), pd.DataFrame()], two_forced_fetches)
check(
    "a good fetch is returned as usual",
    len(first[0]) == 3,
    f"got {first[0].shape}",
)
check(
    "an empty fetch serves the previous snapshot",
    len(second[0]) == 3,
    f"got {second[0].shape}",
)

_, single_row = with_fake_risk([good_frame(), ONE_ROW], two_forced_fetches)
check(
    "a one-row frame counts as a failed fetch, not as data",
    len(single_row[0]) == 3,
    f"got {single_row[0].shape}",
)


def expire(portfolio_name="main"):
    """Age the cached entry past the TTL, as the passage of time would."""
    server._data_cache[portfolio_name]["timestamp"] -= server.CACHE_TTL + 1


def retry_after_failure(fake):
    server._get_cached_market_data(force=True)
    stamp_after_success = server._data_cache["main"]["timestamp"]

    expire()
    failed = server._get_cached_market_data(force=False)
    stamp_after_failure = server._data_cache["main"]["timestamp"] + server.CACHE_TTL + 1

    # Still expired, so this refetches rather than serving the failure.
    recovered = server._get_cached_market_data(force=False)
    return failed, recovered, fake.calls, stamp_after_success == stamp_after_failure


(failed, recovered, calls, stamp_held) = with_fake_risk(
    [good_frame(), pd.DataFrame(), good_frame()], retry_after_failure
)
check(
    "a failed fetch does not refresh the cache timestamp",
    stamp_held,
    "the failure marked the stale snapshot as fresh",
)
check(
    "an empty fetch is not stored, so the next request retries",
    calls == 3,
    f"fetch_data called {calls} times, expected 3",
)
check(
    "the stale snapshot covers the failure",
    len(failed[0]) == 3,
    f"got {failed[0].shape}",
)
check(
    "the retry's data is served once it succeeds",
    len(recovered[0]) == 3,
    f"got {recovered[0].shape}",
)


def cold_start(fake):
    return server._get_cached_market_data(force=True), fake.calls


(cold, cold_calls) = with_fake_risk([pd.DataFrame()], cold_start)
check(
    "with nothing cached the empty frame is still returned, not an exception",
    cold[0].empty and cold_calls == 1,
    f"empty={cold[0].empty} calls={cold_calls}",
)

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s): {', '.join(FAILED)}")
    sys.exit(1)
print("All market data cache checks passed.")
