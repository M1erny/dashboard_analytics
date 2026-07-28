import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PORTFOLIO_DIR = Path(__file__).with_name("portfolios")
DEFAULT_PORTFOLIO = "main"
VALID_DIRECTIONS = {"Long", "Short"}
VALID_TIMINGS = {"effective_open", "post_session"}
REQUIRED_POSITION_FIELDS = {"weight", "type", "currency", "country", "sector"}


def snapshot_fingerprint(snapshot: Any) -> str:
    """Stable hash of one frozen snapshot: its date and every position field.

    AGENTS.md forbids rewriting a past snapshot, but the field-level checks in this
    file cannot see an edit that keeps the shape valid. A snapshot's sector was in
    fact silently changed on four tickers once, and this guard existed to catch it.
    """
    payload = {
        "date": snapshot.get("date"),
        "positions": snapshot.get("positions") or {},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def frozen_lock_path(portfolio: str) -> Path:
    return PORTFOLIO_DIR / f"{portfolio}.frozen.lock.json"


def build_frozen_lock(snapshots: list[Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "description": (
            "sha256 of each frozen snapshot's date and positions. Regenerate ONLY with "
            "'python backend/validate_portfolio_history.py <portfolio> --write-lock' and only "
            "when a snapshot change is intentional and explained in the commit message."
        ),
        "snapshots": {
            str(snapshot.get("date")): snapshot_fingerprint(snapshot)
            for snapshot in snapshots
            if isinstance(snapshot, dict)
        },
    }


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_date(value: Any, field_name: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field_name} must be a non-empty YYYY-MM-DD string")
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        errors.append(f"{field_name} must use YYYY-MM-DD format: {value!r}")
        return None


def validate_positions(positions: Any, context: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(positions, dict) or not positions:
        errors.append(f"{context} must be a non-empty object of ticker positions")
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for ticker, info in positions.items():
        ticker_context = f"{context}.{ticker}"
        if not isinstance(ticker, str) or not ticker.strip():
            errors.append(f"{context} contains an empty ticker")
            continue
        if not isinstance(info, dict):
            errors.append(f"{ticker_context} must be an object")
            continue

        missing = REQUIRED_POSITION_FIELDS.difference(info)
        if missing:
            errors.append(f"{ticker_context} missing fields: {', '.join(sorted(missing))}")

        weight = info.get("weight")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            errors.append(f"{ticker_context}.weight must be numeric")
        elif weight < 0:
            errors.append(f"{ticker_context}.weight must be non-negative")

        direction = info.get("type")
        if direction not in VALID_DIRECTIONS:
            errors.append(f"{ticker_context}.type must be Long or Short")

        for field in ("currency", "country", "sector"):
            value = info.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{ticker_context}.{field} must be a non-empty string")

        normalized[ticker] = info

    return normalized


def exposure_summary(positions: dict[str, dict[str, Any]]) -> dict[str, float]:
    long_exp = 0.0
    short_exp = 0.0
    for info in positions.values():
        weight = float(info.get("weight") or 0.0)
        if info.get("type") == "Short":
            short_exp += weight
        else:
            long_exp += weight

    return {
        "long": long_exp,
        "short": short_exp,
        "gross": long_exp + short_exp,
        "net": long_exp - short_exp,
    }


def validate_portfolio_history(portfolio: str = DEFAULT_PORTFOLIO) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    main_path = PORTFOLIO_DIR / f"{portfolio}.json"
    ledger_path = PORTFOLIO_DIR / f"{portfolio}.rebalances.json"

    if not main_path.exists():
        return [f"Missing active portfolio file: {main_path}"], warnings
    if not ledger_path.exists():
        return [f"Missing rebalance ledger file: {ledger_path}"], warnings

    try:
        active_config = load_json(main_path)
    except json.JSONDecodeError as exc:
        return [f"{main_path} is invalid JSON: {exc}"], warnings

    try:
        ledger = load_json(ledger_path)
    except json.JSONDecodeError as exc:
        return [f"{ledger_path} is invalid JSON: {exc}"], warnings

    active_positions = validate_positions(active_config, f"{portfolio}.json", errors)

    if not isinstance(ledger, dict):
        errors.append(f"{ledger_path.name} must be a JSON object")
        return errors, warnings

    if ledger.get("mode") != "dated_snapshots":
        errors.append(f"{ledger_path.name}.mode must be dated_snapshots")

    active_date = parse_date(
        ledger.get("activeConfigEffectiveDate"),
        f"{ledger_path.name}.activeConfigEffectiveDate",
        errors,
    )
    active_timing = ledger.get("activeConfigExecutionTiming")
    if active_timing not in VALID_TIMINGS:
        errors.append(
            f"{ledger_path.name}.activeConfigExecutionTiming must be one of: "
            f"{', '.join(sorted(VALID_TIMINGS))}"
        )

    if not isinstance(ledger.get("activeConfigLabel"), str) or not ledger.get("activeConfigLabel", "").strip():
        errors.append(f"{ledger_path.name}.activeConfigLabel must describe the active book")

    snapshots = ledger.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        errors.append(f"{ledger_path.name}.snapshots must be a non-empty array")
        snapshots = []

    previous_date: datetime | None = None
    frozen_tickers: set[str] = set()
    snapshot_dates: list[datetime] = []
    for index, snapshot in enumerate(snapshots):
        context = f"{ledger_path.name}.snapshots[{index}]"
        if not isinstance(snapshot, dict):
            errors.append(f"{context} must be an object")
            continue

        snap_date = parse_date(snapshot.get("date"), f"{context}.date", errors)
        if snap_date is not None:
            snapshot_dates.append(snap_date)
            if previous_date is not None and snap_date <= previous_date:
                errors.append(f"{context}.date must be strictly after the previous snapshot")
            previous_date = snap_date
            if active_date is not None and snap_date >= active_date:
                errors.append(f"{context}.date must be before activeConfigEffectiveDate")

        label = snapshot.get("label")
        if not isinstance(label, str) or not label.strip():
            errors.append(f"{context}.label must describe the frozen book")

        timing = snapshot.get("executionTiming", "effective_open")
        if timing not in VALID_TIMINGS:
            errors.append(f"{context}.executionTiming must be one of: {', '.join(sorted(VALID_TIMINGS))}")

        positions = validate_positions(snapshot.get("positions"), f"{context}.positions", errors)
        frozen_tickers.update(positions.keys())

    if active_date is not None and snapshot_dates and snapshot_dates[0].year > active_date.year:
        warnings.append("First frozen snapshot starts after the active year; YTD continuity may be incomplete")

    lock_path = frozen_lock_path(portfolio)
    if lock_path.exists():
        try:
            lock = load_json(lock_path)
        except json.JSONDecodeError as exc:
            lock = None
            errors.append(f"{lock_path.name} is invalid JSON: {exc}")
        if isinstance(lock, dict):
            expected = lock.get("snapshots") or {}
            actual = build_frozen_lock(snapshots)["snapshots"]
            for date, digest in sorted(expected.items()):
                if date not in actual:
                    errors.append(
                        f"Frozen snapshot {date} is in {lock_path.name} but missing from the ledger; "
                        "a preserved book must not be deleted"
                    )
                elif actual[date] != digest:
                    errors.append(
                        f"Frozen snapshot {date} was modified (fingerprint {actual[date][:12]} != "
                        f"locked {digest[:12]}). AGENTS.md requires a new dated entry instead of "
                        f"rewriting history. If the change is deliberate, rerun with --write-lock "
                        f"and say why in the commit message."
                    )
            for date in sorted(set(actual).difference(expected)):
                warnings.append(f"Frozen snapshot {date} is not yet locked; rerun with --write-lock")
    elif snapshots:
        warnings.append(
            f"No {lock_path.name} present, so silent edits to frozen snapshots cannot be detected. "
            "Create it with --write-lock"
        )

    exited_tickers = sorted(frozen_tickers.difference(active_positions.keys()))
    if not exited_tickers:
        warnings.append("No exited tickers appear in the ledger; verify old books are really preserved")

    exposure = exposure_summary(active_positions)
    if exposure["gross"] <= 0:
        errors.append("Active portfolio gross exposure must be positive")
    if exposure["gross"] > 5.0:
        warnings.append(f"Active gross exposure is high: {exposure['gross']:.2%}")

    return errors, warnings


def write_frozen_lock(portfolio: str) -> int:
    ledger_path = PORTFOLIO_DIR / f"{portfolio}.rebalances.json"
    if not ledger_path.exists():
        print(f"Missing rebalance ledger file: {ledger_path}")
        return 1
    ledger = load_json(ledger_path)
    snapshots = ledger.get("snapshots") if isinstance(ledger, dict) else None
    if not isinstance(snapshots, list) or not snapshots:
        print(f"{ledger_path.name}.snapshots must be a non-empty array")
        return 1

    lock = build_frozen_lock(snapshots)
    lock_path = frozen_lock_path(portfolio)
    with lock_path.open("w", encoding="utf-8") as handle:
        json.dump(lock, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"Wrote {lock_path.name} with {len(lock['snapshots'])} frozen snapshot fingerprint(s):")
    for date, digest in sorted(lock["snapshots"].items()):
        print(f"  {date}  {digest}")
    return 0


def main() -> int:
    args = [arg for arg in sys.argv[1:]]
    write_lock = "--write-lock" in args
    positional = [arg for arg in args if not arg.startswith("--")]
    portfolio = positional[0] if positional else DEFAULT_PORTFOLIO

    if write_lock:
        return write_frozen_lock(portfolio)

    errors, warnings = validate_portfolio_history(portfolio)

    if errors:
        print("Portfolio history validation failed:")
        for error in errors:
            print(f"  - {error}")
        if warnings:
            print("\nWarnings:")
            for warning in warnings:
                print(f"  - {warning}")
        return 1

    print(f"Portfolio history validation passed for {portfolio}.")
    for warning in warnings:
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
