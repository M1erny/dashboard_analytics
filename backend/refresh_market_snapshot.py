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
import os
import sys
import time
from urllib.parse import urlparse

import risk
import market_snapshot
from brain_store import create_brain_store


class ConfigError(Exception):
    """A problem with the environment, worth stating in one line rather than a traceback."""


NO_DATABASE_URL_HELP = (
    "DATABASE_URL is not set. Copy the connection string from Render "
    "(service -> Environment) and set it first:\n"
    "  PowerShell:  $env:DATABASE_URL = 'postgresql://user:password@host:6543/postgres?sslmode=require'\n"
    "  bash:        export DATABASE_URL='postgresql://user:password@host:6543/postgres?sslmode=require'"
)


def check_database_url(require_remote: bool = False) -> str | None:
    """Fail early, and in words, on a DATABASE_URL that cannot possibly connect.

    Without this the first sign of trouble is psycopg resolving the hostname,
    which happens after the whole market fetch has already run and which reports
    a placeholder like "postgresql://..." as `UnicodeError: label empty or too
    long` from the IDNA codec - forty lines of traceback for a value that was
    never filled in.

    An unset variable is not an error: create_brain_store then writes to the
    local SQLite file, which is what someone running the whole dashboard on their
    own machine wants. It is only an error under --require-remote, which the
    scheduled workflow passes so that a missing repository secret fails the run
    instead of quietly filling a runner's disk that is thrown away minutes later.
    """
    raw = (os.environ.get("BRAIN_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not raw:
        if require_remote:
            raise ConfigError(NO_DATABASE_URL_HELP)
        return None

    try:
        parsed = urlparse(raw)
    except ValueError as ex:
        # urlsplit rejects a "[" anywhere in the netloc outright, because it reads
        # it as the start of an IPv6 literal. That is precisely the shape of
        # Supabase's unedited "[YOUR-PASSWORD]", so the most common mistake of all
        # never reaches the password check below.
        if any(ch in raw for ch in "[]"):
            raise ConfigError(PLACEHOLDER_PASSWORD_HELP) from ex
        raise ConfigError(
            "DATABASE_URL could not be parsed as a URL. Look for a stray space, or a "
            "character in the password that has to be percent-encoded (& -> %26, @ -> %40, / -> %2F)."
        ) from ex

    if parsed.scheme not in ("postgresql", "postgres"):
        raise ConfigError(
            f"DATABASE_URL must start with postgresql:// or postgres://, got {parsed.scheme or raw[:20]!r}."
        )

    try:
        host = parsed.hostname or ""
    except ValueError as ex:
        raise ConfigError(f"DATABASE_URL host could not be read: {ex}") from ex

    if not host or any(not label for label in host.split(".")):
        raise ConfigError(
            f"DATABASE_URL has no usable host (found {host or '(empty)'!r}). "
            "This is what a placeholder looks like - paste the real connection string, "
            "not the example with the dots in it."
        )

    try:
        password = parsed.password or ""
    except ValueError as ex:
        raise ConfigError(f"DATABASE_URL password could not be read: {type(ex).__name__}.") from ex

    if looks_like_placeholder(password):
        raise ConfigError(PLACEHOLDER_PASSWORD_HELP)
    return raw


PLACEHOLDER_PASSWORD_HELP = (
    "DATABASE_URL still has a stand-in where the password belongs, so it cannot connect. "
    "Supabase hands out the string with [YOUR-PASSWORD] in it and that has to be replaced "
    "with the real password.\n"
    "Avoid retyping it into a template: read it in at a prompt instead, which also keeps it "
    "out of your shell history.\n"
    "  PowerShell:  $env:DATABASE_URL = Read-Host 'connection string'\n"
    "  bash:        read -rs DATABASE_URL && export DATABASE_URL"
)


# Supabase's own connection-string panel hands out "[YOUR-PASSWORD]", and every
# set of instructions ever written has its own stand-in. None of them connect, and
# the resulting "password authentication failed" says nothing about why.
PLACEHOLDER_WORDS = {
    "password", "yourpassword", "your-password", "your_password",
    "changeme", "secret", "replace_with_password", "nowe_haslo", "haslo",
    "putyourpasswordhere", "xxx", "todo",
}


def looks_like_placeholder(password: str) -> bool:
    value = (password or "").strip()
    if not value:
        return False
    # Bracket characters cannot appear unencoded in a URL password, so their
    # presence means the template was never filled in.
    if any(ch in value for ch in "[]<>{}"):
        return True
    return value.lower().replace(" ", "") in PLACEHOLDER_WORDS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--portfolio", default="main")
    parser.add_argument("--dry-run", action="store_true", help="fetch and encode, do not write")
    parser.add_argument(
        "--require-remote",
        action="store_true",
        help="fail unless DATABASE_URL is set (the scheduled workflow uses this)",
    )
    args = parser.parse_args()

    # Open the store before fetching. Connecting costs a second; the fetch costs
    # a minute and 1.2 MB, and throwing that away over a typo in a password is
    # the difference between a quick correction and a slow one.
    store = None
    if not args.dry_run:
        try:
            remote = check_database_url(require_remote=args.require_remote)
            store = create_brain_store()
        except ConfigError as ex:
            print(f"Configuration problem, nothing fetched:\n{ex}")
            return 1
        except Exception as ex:
            print(f"Could not open the database, nothing fetched: {type(ex).__name__}: {ex}")
            if "password authentication failed" in str(ex).lower():
                print(
                    "\nThe host answered, so the address is right and only the password is wrong. Two usual causes:\n"
                    "  - it is still a stand-in rather than the real password;\n"
                    "  - it contains a character that has to be percent-encoded in a URL:\n"
                    "      &  ->  %26      @  ->  %40      /  ->  %2F\n"
                    "      #  ->  %23      :  ->  %3A      %  ->  %25\n"
                    "    Resetting the password in Supabase and taking the generated one avoids this,\n"
                    "    since those are alphanumeric and need no encoding."
                )
            return 1
        label = getattr(store, "database_label", type(store).__name__)
        if remote:
            print(f"Connected to {label}.")
        else:
            print(
                f"DATABASE_URL is not set, so this writes to the local store at {label}.\n"
                "The hosted dashboard will NOT see this snapshot. Set DATABASE_URL to feed it."
            )

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
        print("Dry run: nothing written.")
        return 0

    label = getattr(store, "database_label", type(store).__name__)
    store.set_setting(market_snapshot.setting_key(args.portfolio), text)
    print(f"Saved {market_snapshot.setting_key(args.portfolio)} to {label}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
