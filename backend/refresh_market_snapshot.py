"""Fetch the portfolio's market data once and save it as the dashboard's snapshot.

Run on a schedule from GitHub Actions (see .github/workflows/market-snapshot.yml)
with DATABASE_URL pointing at the same Postgres the server uses. The server then
serves this snapshot while it is fresh and only calls Yahoo itself when it is
not, so the web host - whose shared IP Yahoo throttles - makes almost no
requests of its own. Nothing here bypasses anything: it is the same ~50
downloads, made once every couple of hours from one place instead of on every
page load from a throttled one.

Exit codes: 0 saved, 2 Yahoo throttled the runner, 1 anything else.
"""

import argparse
import sys
import time

import risk
import market_snapshot
from brain_store import create_brain_store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--portfolio", default="main")
    parser.add_argument("--dry-run", action="store_true", help="fetch and encode, do not write")
    args = parser.parse_args()

    started = time.time()
    try:
        raw_prices, fx_rates, volume_data = risk.fetch_data(args.portfolio)
    except risk.MarketDataRateLimited as ex:
        print(f"Yahoo throttled the runner: {ex}")
        return 2
    usd_prices = risk.normalize_to_base_currency(raw_prices, fx_rates, args.portfolio)
    if usd_prices is None or usd_prices.empty or len(usd_prices) < 2:
        print("Download returned no usable prices; nothing saved.")
        return 1

    as_of = market_snapshot.market_as_of(usd_prices)
    fetched_at = time.time()
    text = market_snapshot.encode((usd_prices, fx_rates, volume_data, raw_prices), as_of, fetched_at)
    print(
        f"Fetched {usd_prices.shape[1]} series x {usd_prices.shape[0]} rows "
        f"(as of {as_of}) in {fetched_at - started:.0f}s; snapshot {len(text) // 1024} KB."
    )
    if len(text) > market_snapshot.MAX_BYTES:
        print("Snapshot exceeds the size cap; not saved.")
        return 1
    if args.dry_run:
        return 0

    store = create_brain_store()
    label = getattr(store, "database_label", type(store).__name__)
    store.set_setting(market_snapshot.setting_key(args.portfolio), text)
    print(f"Saved {market_snapshot.setting_key(args.portfolio)} to {label}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
