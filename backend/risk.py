import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
from scipy.stats import skew, kurtosis


# ==========================================
# 1. CONFIGURATION: Define Your Portfolio
# ==========================================
import json
import os
import re
from urllib.request import Request, urlopen

def load_portfolio_config(name="main"):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "portfolios", f"{name}.json")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: Portfolio config {name}.json not found. Falling back to main.json")
        default_path = os.path.join(base_dir, "portfolios", "main.json")
        with open(default_path, 'r', encoding='utf-8') as f:
            return json.load(f)


def load_rebalance_plan(name="main"):
    """Load optional dated portfolio snapshots used for rebalanced YTD accounting."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    plan_path = os.path.join(base_dir, "portfolios", f"{name}.rebalances.json")
    if not os.path.exists(plan_path):
        return None

    with open(plan_path, 'r', encoding='utf-8') as f:
        plan = json.load(f)

    if not isinstance(plan, dict):
        print(f"Warning: Rebalance plan {name}.rebalances.json is not an object. Ignoring.")
        return None

    return plan


def get_rebalance_snapshots(name="main", active_config=None):
    """Return sorted dated snapshots, including the live config if it has an effective date."""
    plan = load_rebalance_plan(name)
    if not plan:
        return []

    snapshots = []
    for snap in plan.get("snapshots", []):
        if not isinstance(snap, dict):
            continue
        date = snap.get("date")
        positions = snap.get("positions")
        if not date or not isinstance(positions, dict) or not positions:
            continue
        snapshots.append({
            "date": str(date),
            "label": snap.get("label", "Portfolio snapshot"),
            "source": snap.get("source", "snapshot"),
            "executionTiming": snap.get("executionTiming", "effective_open"),
            "positions": positions,
        })

    active_date = plan.get("activeConfigEffectiveDate")
    if active_date and active_config:
        snapshots.append({
            "date": str(active_date),
            "label": plan.get("activeConfigLabel", "Current target book"),
            "source": "active_config",
            "executionTiming": plan.get("activeConfigExecutionTiming", "effective_open"),
            "positions": active_config,
        })

    return sorted(snapshots, key=lambda snap: pd.Timestamp(snap["date"]))


def get_all_position_configs(name="main"):
    """Union current config and all rebalance snapshots so exited names still download."""
    active_config = load_portfolio_config(name)
    combined = {}
    for snap in get_rebalance_snapshots(name, active_config):
        combined.update(snap["positions"])
    combined.update(active_config)
    return combined


def get_effective_portfolio_config(name="main", as_of=None):
    """Return the book active on a given date. Defaults to today."""
    active_config = load_portfolio_config(name)
    snapshots = get_rebalance_snapshots(name, active_config)
    if not snapshots:
        return active_config

    as_of_ts = pd.Timestamp(as_of if as_of is not None else datetime.now()).tz_localize(None)
    effective = None
    for snap in snapshots:
        if pd.Timestamp(snap["date"]) <= as_of_ts:
            effective = snap
        else:
            break

    return (effective or snapshots[0])["positions"]


PORTFOLIO_CONFIG = load_portfolio_config("main")

# Global constants for the engine

BENCHMARK = 'SPY'
BENCHMARK_WIG = 'ETFBW20TR.WA'  # Beta ETF WIG20TR PCIF-Investment Certificates
BENCHMARK_MSCI = 'URTH'     # iShares MSCI World ETF
WATCHLIST_FX = ['USDPLN=X', 'EURPLN=X', 'EURUSD=X', 'DKKEUR=X', 'JPYUSD=X'] # Pairs to track
BASE_CURRENCY = 'USD'
LOOKBACK_YEARS = 5.2
ANNUAL_FACTOR = 252

# Cost of Carry Assumptions (Retail Broker Estimate)
MARGIN_RATE = 0.12  # 12.0% typical retail margin rate (e.g., Schwab/Fidelity)
BORROW_FEE = 0.025  # 2.5% estimated retail hard-to-borrow blended fee



def _finite_float(value):
    try:
        if value is None:
            return None
        number = float(value)
        if not np.isfinite(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def _fast_info_value(fast_info, key):
    try:
        return _finite_float(fast_info.get(key))
    except Exception:
        return None


def _parse_market_number(value):
    if value is None:
        return None
    cleaned = (
        str(value)
        .replace("\xa0", "")
        .replace(" ", "")
        .replace("%", "")
        .replace("+", "")
        .replace(",", ".")
    )
    return _finite_float(cleaned)


def fetch_warsaw_latest_quote(ticker, min_date=None):
    """Fetch a current Warsaw quote when Yahoo has a blank newest bar."""
    if not str(ticker).upper().endswith(".WA"):
        return None

    symbol = str(ticker).upper().split(".")[0]
    url = f"https://www.biznesradar.pl/notowania/{symbol}"
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=5) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception as ex:
        print(f"  Warsaw backup quote failed for {ticker}: {ex}")
        return None

    price_match = re.search(r'itemprop=["\']price["\']\s+content=["\']([^"\']+)["\']', html)
    if price_match is None:
        price_match = re.search(r'class=["\']q_ch_act["\'][^>]*>\s*([^<]+)\s*<', html)

    price = _parse_market_number(price_match.group(1) if price_match else None)
    if price is None or price <= 0:
        return None

    previous_match = re.search(r'class=["\']q_ch_prev["\'][^>]*>\s*([^<]+)\s*<', html)
    change_match = re.search(r'itemprop=["\']priceChangePercent["\']\s+content=["\']([^"\']+)["\']', html)
    time_match = re.search(r'itemprop=["\']quoteTime["\']\s+content=["\']([^"\']+)["\']', html)

    quote_dt = None
    quote_epoch = _finite_float(time_match.group(1) if time_match else None)
    if quote_epoch is not None:
        try:
            quote_dt = datetime.fromtimestamp(quote_epoch)
        except (OverflowError, OSError, ValueError):
            quote_dt = None

    if min_date is not None and quote_dt is not None:
        min_ts = pd.Timestamp(min_date).tz_localize(None)
        if pd.Timestamp(quote_dt).tz_localize(None).date() < min_ts.date():
            print(f"  Warsaw backup quote for {ticker} is stale ({quote_dt.date()}); skipping.")
            return None

    return {
        "price": price,
        "previous_close": _parse_market_number(previous_match.group(1) if previous_match else None),
        "change_pct": _parse_market_number(change_match.group(1) if change_match else None),
        "quote_time": quote_dt,
        "source": "BiznesRadar",
        "url": url,
    }


def select_latest_patch_price(last_price, previous_close, regular_previous_close, open_val=None, volume_val=None, qtype=None, market_quote=None):
    """Choose the safest price for a missing newest row."""
    last_price = _finite_float(last_price)
    previous_close = _finite_float(previous_close)
    regular_previous_close = _finite_float(regular_previous_close)
    open_val = _finite_float(open_val)
    volume_val = _finite_float(volume_val)

    reference_close = regular_previous_close if regular_previous_close and regular_previous_close > 0 else previous_close

    if market_quote:
        market_price = _finite_float(market_quote.get("price"))
        if market_price and market_price > 0:
            return market_price, market_quote.get("source", "market quote")

    if last_price and last_price > 0:
        if reference_close and reference_close > 0:
            diff_pct = abs(last_price - reference_close) / reference_close
            is_stale_indicator = (
                qtype == "MUTUALFUND" or
                open_val is None or
                volume_val == 0
            )
            if diff_pct > 0.15 and is_stale_indicator:
                return reference_close, "regularMarketPreviousClose"
        return last_price, "Yahoo fast_info lastPrice"

    if reference_close and reference_close > 0:
        return reference_close, "regularMarketPreviousClose"

    return None, None




# ==========================================
# 2. DATA ENGINE: Fetch & Normalize
# ==========================================
def fetch_data(portfolio_name="main"):
    PORTFOLIO_CONFIG = get_all_position_configs(portfolio_name)
    print("--- 1. Initializing Data Download ---")
    
    tickers = list(PORTFOLIO_CONFIG.keys())
    tickers.append(BENCHMARK)
    tickers.append(BENCHMARK_WIG)   # Polish WIG
    tickers.append(BENCHMARK_MSCI)  # MSCI World
    
    # Identify unique currencies
    currencies = list(set([item['currency'] for item in PORTFOLIO_CONFIG.values()]))
    fx_pairs = []
    for curr in currencies:
        if curr != BASE_CURRENCY:
            fx_pairs.append(f"{curr}{BASE_CURRENCY}=X")

    # Add Watchlist FX
    for fx in WATCHLIST_FX:
        if fx not in fx_pairs:
            fx_pairs.append(fx)
    
    start_date = (datetime.now() - timedelta(days=LOOKBACK_YEARS*365)).strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    print(f"Fetching stock data for {len(tickers)} tickers from {start_date} to {end_date}...")
    stock_raw = yf.download(tickers, start=start_date, end=end_date, auto_adjust=True, threads=True)
    print(f"Stock Raw Shape: {stock_raw.shape}")
    if stock_raw.empty:
         print("WARNING: Stock Raw is EMPTY!")
    
    # --- Recovery logic for failed stock downloads ---
    def get_ticker_series(df, t):
        if df.empty:
            return pd.Series()
        if isinstance(df.columns, pd.MultiIndex):
            for price_col in ['Close', 'Adj Close']:
                if (price_col, t) in df.columns:
                    return df[(price_col, t)].dropna()
        else:
            if t in df.columns:
                return df[t].dropna()
        return pd.Series()

    failed_tickers = []
    for t in tickers:
        series = get_ticker_series(stock_raw, t)
        if series.empty:
            failed_tickers.append(t)

    if failed_tickers:
        print(f"Failed to fetch {len(failed_tickers)} tickers in bulk: {failed_tickers}. Retrying individually...")
        import time
        for t in failed_tickers:
            print(f"Retrying single download for stock: {t}")
            for attempt in range(3):
                try:
                    single_raw = yf.download([t], start=start_date, end=end_date, auto_adjust=True, threads=False, progress=False)
                    if not single_raw.empty:
                        valid_series = get_ticker_series(single_raw, t)
                        if not valid_series.empty:
                            if stock_raw.empty:
                                stock_raw = single_raw.copy()
                            else:
                                for col in single_raw.columns:
                                    stock_raw[col] = single_raw[col]
                            print(f"Successfully recovered stock ticker: {t} on attempt {attempt + 1}")
                            break
                        else:
                            print(f"Attempt {attempt+1}: Data downloaded but valid series is empty for {t}")
                    else:
                        print(f"Attempt {attempt+1}: Returned empty DataFrame for {t}")
                except Exception as ex:
                    print(f"Error recovering stock ticker {t} (attempt {attempt + 1}): {ex}")
                time.sleep(1)

    # --- Patch latest row NaNs using fast_info lastPrice (handling WSE/international update delays) ---
    print("Checking for latest date NaNs to patch with fast_info...")
    for t in tickers:
        try:
            series = get_ticker_series(stock_raw, t)
            if not series.empty:
                last_date = stock_raw.index[-1]
                is_nan_val = True
                if isinstance(stock_raw.columns, pd.MultiIndex):
                    for price_col in ['Close', 'Adj Close']:
                        if (price_col, t) in stock_raw.columns:
                            val = stock_raw.loc[last_date, (price_col, t)]
                            if pd.isna(val):
                                is_nan_val = True
                                break
                            else:
                                is_nan_val = False
                else:
                    if t in stock_raw.columns:
                        is_nan_val = pd.isna(stock_raw.loc[last_date, t])
                    else:
                        is_nan_val = True

                if is_nan_val:
                    ticker_obj = yf.Ticker(t)
                    fast_info = ticker_obj.fast_info
                    market_quote = fetch_warsaw_latest_quote(t, min_date=last_date)
                    patch_price, patch_source = select_latest_patch_price(
                        last_price=_fast_info_value(fast_info, 'lastPrice'),
                        previous_close=_fast_info_value(fast_info, 'previousClose'),
                        regular_previous_close=_fast_info_value(fast_info, 'regularMarketPreviousClose'),
                        open_val=_fast_info_value(fast_info, 'open'),
                        volume_val=_fast_info_value(fast_info, 'lastVolume'),
                        qtype=fast_info.get('quoteType'),
                        market_quote=market_quote,
                    )
                    if patch_price is not None:

                        if isinstance(stock_raw.columns, pd.MultiIndex):
                            for price_col in ['Close', 'Adj Close']:
                                if (price_col, t) in stock_raw.columns:
                                    stock_raw.loc[last_date, (price_col, t)] = patch_price
                        else:
                            if t in stock_raw.columns:
                                stock_raw.loc[last_date, t] = patch_price
                        print(f"  Patched latest NaN price for {t} with: {patch_price} ({patch_source})")
        except Exception as ex:
            print(f"  Failed to patch latest price for {t}: {ex}")

    # Handle Data Structure (MultiIndex vs Single)
    if isinstance(stock_raw.columns, pd.MultiIndex):
        try:
            stock_data = stock_raw['Close'].ffill() # Fallback to prev close
            volume_data = stock_raw['Volume'].fillna(0)
        except KeyError:
             stock_data = stock_raw.xs('Close', axis=1, level=0, drop_level=True).ffill()
             volume_data = stock_raw.xs('Volume', axis=1, level=0, drop_level=True).fillna(0)
    elif 'Close' in stock_raw.columns:
         stock_data = stock_raw['Close'].ffill()
         volume_data = stock_raw['Volume'].fillna(0)
    else:
        stock_data = stock_raw.ffill()
        # Use dummy volume if missing (should not happen with standard downloads)
        volume_data = pd.DataFrame(1, index=stock_raw.index, columns=stock_raw.columns)
        
    print(f"Fetching FX rates for: {fx_pairs}...")
    fx_raw = yf.download(fx_pairs, start=start_date, auto_adjust=True, threads=True)
    
    # --- Recovery logic for failed FX downloads ---
    def get_fx_series(df, fx_t):
        if df.empty:
            return pd.Series()
        if isinstance(df.columns, pd.MultiIndex):
            for price_col in ['Close', 'Adj Close']:
                if (price_col, fx_t) in df.columns:
                    return df[(price_col, fx_t)].dropna()
        else:
            if fx_t in df.columns:
                return df[fx_t].dropna()
        return pd.Series()

    failed_fx = []
    for fx_t in fx_pairs:
        series = get_fx_series(fx_raw, fx_t)
        if series.empty:
            failed_fx.append(fx_t)

    if failed_fx:
        print(f"Failed to fetch {len(failed_fx)} FX pairs in bulk: {failed_fx}. Retrying individually...")
        import time
        for fx_t in failed_fx:
            print(f"Retrying single download for FX: {fx_t}")
            for attempt in range(3):
                try:
                    single_raw = yf.download([fx_t], start=start_date, auto_adjust=True, threads=False, progress=False)
                    if not single_raw.empty:
                        valid_series = get_fx_series(single_raw, fx_t)
                        if not valid_series.empty:
                            if fx_raw.empty:
                                fx_raw = single_raw.copy()
                            else:
                                for col in single_raw.columns:
                                    fx_raw[col] = single_raw[col]
                            print(f"Successfully recovered FX: {fx_t} on attempt {attempt + 1}")
                            break
                        else:
                            print(f"Attempt {attempt+1}: Data downloaded but valid series is empty for FX {fx_t}")
                    else:
                        print(f"Attempt {attempt+1}: Returned empty DataFrame for FX {fx_t}")
                except Exception as ex:
                    print(f"Error recovering FX {fx_t} (attempt {attempt + 1}): {ex}")
                time.sleep(1)

    if isinstance(fx_raw.columns, pd.MultiIndex):
        try:
            fx_data = fx_raw['Close'].ffill()
        except KeyError:
             fx_data = fx_raw.xs('Close', axis=1, level=0, drop_level=True).ffill()
    elif 'Close' in fx_raw.columns:
         fx_data = fx_raw['Close'].ffill()
    else:
         fx_data = fx_raw.ffill()

    return stock_data, fx_data, volume_data


def normalize_to_base_currency(stock_df, fx_df, portfolio_name="main"):
    PORTFOLIO_CONFIG = get_all_position_configs(portfolio_name)
    print("--- 2. Normalizing Currencies to USD ---")
    normalized_df = stock_df.copy()
    
    for ticker, info in PORTFOLIO_CONFIG.items():
        if ticker not in normalized_df.columns:
            print(f"Warning: Data for {ticker} not found (Might be new or delisted). Skipping.")
            continue
            
        currency = info['currency']
        if currency == BASE_CURRENCY:
            continue 
            
        fx_ticker = f"{currency}{BASE_CURRENCY}=X"
        
        if fx_ticker in fx_df.columns:
            fx_series = fx_df[fx_ticker].reindex(normalized_df.index).ffill()
            normalized_df[ticker] = normalized_df[ticker] * fx_series
        else:
            print(f"Error: FX data missing for {currency}. Calculations for {ticker} might be wrong.")
            
    return normalized_df

# ==========================================
# 3. RISK CALCULATOR
# ==========================================
# Helper for calculating dynamic "YTD" start dates
def get_period_params(portfolio_name):
    """
    Returns (period_label, start_date_str). 
    Defaults to the start of the current year.
    """
    current_year = datetime.now().year
    return "YTD", f"{current_year}-01-01"


def calculate_exposure_stats(portfolio_config):
    total_long_weight = 0.0
    total_short_weight = 0.0

    for info in portfolio_config.values():
        weight = float(info.get('weight', 0) or 0)
        if info.get('type', 'Long') == 'Long':
            total_long_weight += weight
        else:
            total_short_weight += weight

    return {
        'long': total_long_weight,
        'short': total_short_weight,
        'gross': total_long_weight + total_short_weight,
        'net': total_long_weight - total_short_weight,
    }


def calculate_daily_financing_drag(portfolio_config, margin_rate, borrow_fee):
    exposure = calculate_exposure_stats(portfolio_config)
    net_debit = max(0, exposure['long'] - 1.0)
    daily_margin_cost = (net_debit * margin_rate) / 360
    daily_borrow_cost = (exposure['short'] * borrow_fee) / 360
    return daily_margin_cost + daily_borrow_cost


def calculate_segment_financing_values(
    segment_index,
    segment_gross_curve,
    long_market_value_factors,
    short_market_value_factors,
    net_start_value,
    margin_rate,
    borrow_fee,
):
    """Build a net segment NAV using fixed opening margin debt and live short notional.

    Position returns are already a buy-and-hold curve for the dated book. Margin
    debt is therefore held in dollars from the segment opening, while stock borrow
    is charged on the average mark-to-market short notional over each calendar
    interval. This remains an estimate until broker cash and borrow ledgers are
    connected, but it avoids treating financing as a constant percentage of a
    changing NAV.
    """
    net_values = pd.Series(np.nan, index=segment_index, dtype=float)
    direct_costs = pd.Series(0.0, index=segment_index, dtype=float)
    if len(segment_index) == 0:
        return net_values, direct_costs

    net_values.iloc[0] = float(net_start_value)
    opening_long_notional = float(net_start_value) * max(0.0, float(long_market_value_factors.iloc[0]))
    opening_margin_principal = max(0.0, opening_long_notional - float(net_start_value))
    calendar_days = segment_index.to_series().diff().dt.days.fillna(0).clip(lower=0)

    for idx in range(1, len(segment_index)):
        days = float(calendar_days.iloc[idx])
        previous_short = max(0.0, float(short_market_value_factors.iloc[idx - 1]))
        current_short = max(0.0, float(short_market_value_factors.iloc[idx]))
        average_short_notional = float(net_start_value) * (previous_short + current_short) / 2.0

        margin_cost = opening_margin_principal * float(margin_rate) * days / 360.0
        borrow_cost = average_short_notional * float(borrow_fee) * days / 360.0
        direct_cost = margin_cost + borrow_cost
        direct_costs.iloc[idx] = direct_cost

        gross_pnl = float(net_start_value) * (
            float(segment_gross_curve.iloc[idx]) - float(segment_gross_curve.iloc[idx - 1])
        )
        net_values.iloc[idx] = net_values.iloc[idx - 1] + gross_pnl - direct_cost

    return net_values, direct_costs


def get_rebalance_start_index(price_index, snap_ts, execution_timing="effective_open"):
    """Return the price row used as the base for a dated rebalance."""
    timing = str(execution_timing or "effective_open").lower()
    if timing in {"post_session", "after_close", "close"}:
        return max(0, min(len(price_index) - 1, price_index.searchsorted(snap_ts, side="right") - 1))
    return max(0, min(len(price_index) - 1, price_index.searchsorted(snap_ts) - 1))


def calculate_drawdown_series(value_series):
    """Running-peak drawdown. A new high resets drawdown to zero."""
    values = value_series.astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return pd.Series(dtype=float)

    running_max = values.cummax().replace(0, np.nan)
    drawdown = (values - running_max) / running_max
    return drawdown.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def value_series_from_returns(returns_series, start_index=None, start_value=1.0):
    """Compound returns into a value curve with an optional base value row."""
    returns = returns_series.astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    values = start_value * (1.0 + returns).cumprod()

    if start_index is None:
        return values

    if isinstance(values.index, pd.DatetimeIndex) or isinstance(start_index, pd.Timestamp):
        base_index = pd.DatetimeIndex([pd.Timestamp(start_index)])
    else:
        base_index = pd.Index([start_index])

    base = pd.Series([float(start_value)], index=base_index)
    combined = pd.concat([base, values])
    return combined[~combined.index.duplicated(keep="first")]


def calculate_beta(portfolio_returns, benchmark_returns):
    """OLS beta using sample covariance and sample benchmark variance."""
    aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1).dropna()
    if len(aligned) < 2:
        return np.nan

    port = aligned.iloc[:, 0]
    bench = aligned.iloc[:, 1]
    benchmark_variance = np.var(bench, ddof=1)
    if benchmark_variance <= 0 or pd.isna(benchmark_variance):
        return np.nan

    return float(np.cov(port, bench)[0][1] / benchmark_variance)


def calculate_sortino_ratio(daily_returns, annual_risk_free_rate):
    """Annualised Sortino using all observations and downside deviation vs cash."""
    returns = pd.Series(daily_returns, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if returns.empty:
        return 0.0

    safe_rate = max(float(annual_risk_free_rate or 0.0), -0.999999)
    daily_cash_rate = np.expm1(np.log1p(safe_rate) / ANNUAL_FACTOR)
    excess_returns = returns - daily_cash_rate
    downside = np.minimum(excess_returns, 0.0)
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))) * np.sqrt(ANNUAL_FACTOR))
    annualised_excess_return = float(np.mean(excess_returns) * ANNUAL_FACTOR)
    return annualised_excess_return / downside_deviation if downside_deviation > 0 else 0.0


def calculate_compounded_capm_alpha(portfolio_returns, benchmark_returns, beta, annual_risk_free_rate):
    """Return period CAPM alpha by compounding daily expected and realised returns."""
    aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if aligned.empty or pd.isna(beta):
        return 0.0, 0.0

    safe_rate = max(float(annual_risk_free_rate or 0.0), -0.999999)
    daily_cash_rate = np.expm1(np.log1p(safe_rate) / ANNUAL_FACTOR)
    portfolio_daily = aligned.iloc[:, 0]
    benchmark_daily = aligned.iloc[:, 1]
    expected_daily = daily_cash_rate + float(beta) * (benchmark_daily - daily_cash_rate)

    realised_period_return = float((1.0 + portfolio_daily).prod() - 1.0)
    expected_period_return = float((1.0 + expected_daily).prod() - 1.0)
    return realised_period_return - expected_period_return, expected_period_return


def calculate_batting_stats(contribution_row):
    """Ticker-level batting stats from cumulative contribution at a date.

    Only names that have actually produced a return day count. A position added by a
    post_session rebalance already has a contribution cell on the rebalance date, but
    its first return day is the next session, so its contribution is exactly 0.0.
    Leaving those in the denominator counts them as losses they have not had yet and
    prints a one-day collapse in hit rate at every dated rebalance.
    """
    clean = contribution_row.dropna()
    traded = clean[clean != 0.0]
    positions_count = int(len(traded))
    winners_count = int((traded > 0).sum())
    losers_count = int((traded < 0).sum())
    total_gains = float(traded[traded > 0].sum()) if positions_count else 0.0
    total_losses = float(abs(traded[traded < 0].sum())) if positions_count else 0.0

    if positions_count == 0:
        batting_average = np.nan
    else:
        batting_average = winners_count / positions_count

    if total_losses > 0:
        profit_factor = total_gains / total_losses
    elif total_gains > 0:
        profit_factor = np.inf
    else:
        profit_factor = 0.0

    return {
        "battingAverage": float(batting_average) if not pd.isna(batting_average) else np.nan,
        "winnersCount": winners_count,
        "losersCount": losers_count,
        "positionsCount": positions_count,
        "profitFactor": float(profit_factor) if not np.isinf(profit_factor) else np.inf,
    }


def build_historical_diagnostics(portfolio_value_series, benchmark_returns, contribution_history=None, min_beta_periods=14):
    """Build per-date YTD diagnostics from the same value stream used for reported metrics."""
    if portfolio_value_series is None or portfolio_value_series.empty:
        return []

    values = portfolio_value_series.astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return []

    portfolio_returns = values.pct_change().dropna()
    benchmark_aligned = benchmark_returns.reindex(portfolio_returns.index).dropna() if benchmark_returns is not None else pd.Series(dtype=float)
    portfolio_aligned = portfolio_returns.reindex(benchmark_aligned.index).dropna()
    benchmark_aligned = benchmark_aligned.reindex(portfolio_aligned.index).dropna()
    portfolio_aligned = portfolio_aligned.reindex(benchmark_aligned.index).dropna()
    drawdown = calculate_drawdown_series(values)
    rows = []

    for date in values.index:
        ret_slice = portfolio_returns.loc[portfolio_returns.index <= date]
        variance = float(ret_slice.var(ddof=1)) if len(ret_slice) > 1 else np.nan
        volatility = float(np.sqrt(variance * ANNUAL_FACTOR)) if not pd.isna(variance) and variance >= 0 else np.nan

        beta = np.nan
        if len(portfolio_aligned) >= min_beta_periods and date in portfolio_aligned.index:
            port_slice = portfolio_aligned.loc[portfolio_aligned.index <= date]
            bench_slice = benchmark_aligned.loc[benchmark_aligned.index <= date]
            if len(port_slice) >= min_beta_periods:
                beta = calculate_beta(port_slice, bench_slice)

        batting = {
            "battingAverage": np.nan,
            "winnersCount": 0,
            "losersCount": 0,
            "positionsCount": 0,
            "profitFactor": 0.0,
        }
        if contribution_history is not None and not contribution_history.empty and date in contribution_history.index:
            batting = calculate_batting_stats(contribution_history.loc[date])

        rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "portfolio": float(values.loc[date]),
            "drawdown": float(drawdown.loc[date]) if date in drawdown.index else 0.0,
            "variance": variance,
            "volatility": volatility,
            "beta": beta,
            **batting,
        })

    return rows


def calculate_segmented_ytd(
    ytd_prices_filled,
    portfolio_name,
    active_config,
    ytd_calc_start,
    margin_rate,
    borrow_fee,
):
    """Chain YTD performance across dated portfolio snapshots.

    By default, a rebalance date is treated as the first session where the new
    book is live, so it uses the prior close as its base. If a snapshot has
    executionTiming="post_session", the same date is treated as the close used
    for the rebalance, and the new book begins earning returns after that close.
    """
    snapshots = get_rebalance_snapshots(portfolio_name, active_config)
    if not snapshots or ytd_prices_filled.empty:
        return None

    price_index = ytd_prices_filled.index
    last_date = price_index[-1]
    ytd_start_ts = pd.Timestamp(ytd_calc_start)

    active_snapshots = []
    for snap in snapshots:
        snap_ts = pd.Timestamp(snap["date"])
        if snap_ts <= last_date:
            active_snapshots.append({**snap, "ts": snap_ts})

    if not active_snapshots:
        return None

    if active_snapshots[0]["ts"] > ytd_start_ts:
        active_snapshots.insert(0, {
            "date": ytd_calc_start,
            "label": "YTD opening book",
            "source": "fallback",
            "executionTiming": "effective_open",
            "positions": active_config,
            "ts": ytd_start_ts,
        })

    for snap in active_snapshots:
        snap["start_idx"] = get_rebalance_start_index(
            price_index,
            snap["ts"],
            snap.get("executionTiming", "effective_open"),
        )

    portfolio_val_series_gross = pd.Series(index=price_index, dtype=float)
    portfolio_val_series_net = pd.Series(index=price_index, dtype=float)
    long_daily_ret = pd.Series(0.0, index=price_index)
    short_daily_ret = pd.Series(0.0, index=price_index)

    gross_start_value = 1.0
    net_start_value = 1.0
    position_contributions = {}
    ytd_longs_contrib = 0.0
    ytd_shorts_contrib = 0.0
    ytd_direct_financing_cost = 0.0
    current_weights = {}
    rebalance_events = []
    all_segment_tickers = sorted({ticker for snap in active_snapshots for ticker in snap.get("positions", {}).keys()})
    contribution_history = pd.DataFrame(np.nan, index=price_index, columns=all_segment_tickers)
    cumulative_position_contributions = {}
    latest_segment_position_contributions = {}
    latest_segment_position_contributions_ytd_basis = {}
    latest_segment_start_date = None

    for idx, snap in enumerate(active_snapshots):
        start_idx = snap["start_idx"]

        if idx + 1 < len(active_snapshots):
            end_idx = max(start_idx, active_snapshots[idx + 1]["start_idx"])
        else:
            end_idx = len(price_index) - 1

        segment_index = price_index[start_idx:end_idx + 1]
        if len(segment_index) == 0:
            continue

        positions = snap["positions"]
        base_prices = ytd_prices_filled.loc[segment_index[0]]
        rel_prices = ytd_prices_filled.loc[segment_index].divide(base_prices).replace([np.inf, -np.inf], np.nan)

        segment_contrib_curve = pd.Series(0.0, index=segment_index)
        segment_long_curve = pd.Series(0.0, index=segment_index)
        segment_short_curve = pd.Series(0.0, index=segment_index)
        segment_long_market_value_factors = pd.Series(0.0, index=segment_index)
        segment_short_market_value_factors = pd.Series(0.0, index=segment_index)
        segment_position_curves = {}

        for ticker, info in positions.items():
            if ticker not in rel_prices.columns:
                continue

            weight = float(info.get('weight', 0) or 0)
            if weight == 0:
                continue

            direction = 1 if info.get('type', 'Long') == 'Long' else -1
            relative_price = rel_prices[ticker].fillna(1.0)
            asset_cum_ret = relative_price - 1.0
            position_curve = weight * direction * asset_cum_ret
            segment_contrib_curve += position_curve
            segment_position_curves[ticker] = position_curve

            if direction == 1:
                segment_long_curve += position_curve
                segment_long_market_value_factors += weight * relative_price
            else:
                segment_short_curve += position_curve
                segment_short_market_value_factors += weight * relative_price

            final_contrib = float(gross_start_value * position_curve.iloc[-1])
            position_contributions[ticker] = position_contributions.get(ticker, 0.0) + final_contrib
            if direction == 1:
                ytd_longs_contrib += final_contrib
            else:
                ytd_shorts_contrib += final_contrib

        segment_gross_curve = (1.0 + segment_contrib_curve).clip(lower=0.000001)
        segment_gross_values = gross_start_value * segment_gross_curve

        segment_drag = calculate_daily_financing_drag(positions, margin_rate, borrow_fee)
        opening_exposure = calculate_exposure_stats(positions)
        segment_net_values, segment_direct_financing_costs = calculate_segment_financing_values(
            segment_index,
            segment_gross_curve,
            segment_long_market_value_factors,
            segment_short_market_value_factors,
            net_start_value,
            margin_rate,
            borrow_fee,
        )
        segment_net_daily_ret = segment_net_values.pct_change().fillna(0.0)
        segment_financing_cost = float(segment_direct_financing_costs.sum())
        segment_financing_impact = float(
            net_start_value * segment_gross_curve.iloc[-1] - segment_net_values.iloc[-1]
        )
        ytd_direct_financing_cost += segment_financing_cost

        portfolio_val_series_gross.loc[segment_index] = segment_gross_values
        portfolio_val_series_net.loc[segment_index] = segment_net_values

        for ticker, prior_contribution in cumulative_position_contributions.items():
            contribution_history.loc[segment_index, ticker] = prior_contribution
        for ticker, position_curve in segment_position_curves.items():
            prior_contribution = cumulative_position_contributions.get(ticker, 0.0)
            contribution_history.loc[segment_index, ticker] = prior_contribution + gross_start_value * position_curve

        previous_segment_value = segment_gross_curve.shift(1).replace(0, np.nan)
        # Assign only the rows where diff() is defined. A segment's first row has no
        # prior row inside the segment, and under post_session execution that row IS
        # the seam day already written by the previous segment. Filling it with 0.0
        # erased a real trading day from the long/short split, which is why
        # longOnlyBeta + shortOnlyBeta no longer summed to the portfolio beta.
        # The series are initialised to 0.0, so the very first date stays 0.0.
        segment_return_index = segment_index[1:]
        if len(segment_return_index):
            long_daily_ret.loc[segment_return_index] = (
                (segment_long_curve.diff() / previous_segment_value)
                .reindex(segment_return_index)
                .fillna(0.0)
            )
            short_daily_ret.loc[segment_return_index] = (
                (segment_short_curve.diff() / previous_segment_value)
                .reindex(segment_return_index)
                .fillna(0.0)
            )

        exposure = opening_exposure
        rebalance_events.append({
            "date": segment_index[0].strftime('%Y-%m-%d'),
            "effectiveDate": snap["date"],
            "label": snap.get("label", "Portfolio snapshot"),
            "source": snap.get("source", "snapshot"),
            "executionTiming": snap.get("executionTiming", "effective_open"),
            "longExposure": exposure['long'],
            "shortExposure": exposure['short'],
            "grossExposure": exposure['gross'],
            "netExposure": exposure['net'],
            "positionCount": len(positions),
            "dailyFinancingDrag": float(segment_drag),
            "annualFinancingCost": float(segment_drag * 360),
            "segmentFinancingCost": segment_financing_cost,
            "segmentFinancingImpact": segment_financing_impact,
            "cumulativeFinancingCost": float(ytd_direct_financing_cost),
            "cumulativeFinancingImpact": float(segment_gross_values.iloc[-1] - segment_net_values.iloc[-1]),
            "grossStartValue": float(gross_start_value),
            "grossEndValue": float(segment_gross_values.iloc[-1]),
            "netStartValue": float(net_start_value),
            "netEndValue": float(segment_net_values.iloc[-1]),
        })

        if idx == len(active_snapshots) - 1:
            current_weights = {}
            final_net_curve = float(segment_net_values.iloc[-1] / net_start_value) if net_start_value else 0.0
            latest_segment_start_date = segment_index[0].strftime('%Y-%m-%d')
            for ticker, info in positions.items():
                weight = float(info.get('weight', 0) or 0)
                if ticker in rel_prices.columns and final_net_curve > 0:
                    rel_final = rel_prices[ticker].iloc[-1]
                    current_weights[ticker] = float(weight * rel_final / final_net_curve) if not pd.isna(rel_final) else weight
                else:
                    current_weights[ticker] = weight
            for ticker, position_curve in segment_position_curves.items():
                latest_segment_position_contributions[ticker] = float(position_curve.iloc[-1])
                latest_segment_position_contributions_ytd_basis[ticker] = float(gross_start_value * position_curve.iloc[-1])

        gross_start_value = float(segment_gross_values.iloc[-1])
        net_start_value = float(segment_net_values.iloc[-1])
        for ticker in contribution_history.columns:
            if not pd.isna(contribution_history.loc[segment_index[-1], ticker]):
                cumulative_position_contributions[ticker] = float(contribution_history.loc[segment_index[-1], ticker])

    portfolio_val_series_gross = portfolio_val_series_gross.ffill().dropna()
    portfolio_val_series_net = portfolio_val_series_net.ffill().dropna()
    contribution_history = contribution_history.reindex(portfolio_val_series_net.index).ffill()

    if portfolio_val_series_gross.empty or portfolio_val_series_net.empty:
        return None

    current_config = active_snapshots[-1]["positions"]
    return {
        "portfolio_val_series_gross": portfolio_val_series_gross,
        "portfolio_val_series": portfolio_val_series_net,
        "ytd_return_gross": float(portfolio_val_series_gross.iloc[-1] - 1.0),
        "ytd_return": float(portfolio_val_series_net.iloc[-1] - 1.0),
        "ytd_financing_cost": float(portfolio_val_series_gross.iloc[-1] - portfolio_val_series_net.iloc[-1]),
        "ytd_direct_financing_cost": float(ytd_direct_financing_cost),
        "annual_financing_cost": float(calculate_daily_financing_drag(current_config, margin_rate, borrow_fee) * 360),
        "ytd_longs_contrib": ytd_longs_contrib,
        "ytd_shorts_contrib": ytd_shorts_contrib,
        "position_contributions": position_contributions,
        "position_contribution_history": contribution_history,
        "latest_segment_position_contributions": latest_segment_position_contributions,
        "latest_segment_position_contributions_ytd_basis": latest_segment_position_contributions_ytd_basis,
        "latest_segment_start_date": latest_segment_start_date,
        "current_weights": current_weights,
        "rebalance_events": rebalance_events,
        "long_daily_ret": long_daily_ret.reindex(portfolio_val_series_net.index).fillna(0.0),
        "short_daily_ret": short_daily_ret.reindex(portfolio_val_series_net.index).fillna(0.0),
    }

# ==========================================
# 3. RISK CALCULATOR (ADVANCED)
# ==========================================
def calculate_risk_metrics(price_df, volume_df=None, fx_df=None, margin_rate=MARGIN_RATE, borrow_fee=BORROW_FEE, portfolio_name="main"):
    PORTFOLIO_CONFIG = get_effective_portfolio_config(portfolio_name)
    print("--- 3. Calculating Advanced Risk Metrics ---")
    
    # Defensive copy to avoid mutating shared cached data
    price_df = price_df.copy()
    
    if price_df.empty or len(price_df) < 2:
        print("Error: Insufficient price data.")
        return None
        
    # Use dropna(how='all') to only drop rows where ALL values are NaN
    # This prevents dropping rows where just some tickers are missing
    returns_df = price_df.pct_change().dropna(how='all')
    
    if returns_df.empty or len(returns_df) < 2:
        print("Error: Insufficient returns data after pct_change.")
        return None
    
    if BENCHMARK not in returns_df.columns:
        print(f"Critical Error: Benchmark {BENCHMARK} data missing.")
        return None

    benchmark_ret = returns_df[BENCHMARK]
    
    # --- 0.5. CASH RISK-FREE PROXY (^IRX) ---
    try:
        # A cash-like rate is appropriate for Sharpe, Sortino and CAPM excess
        # return. A 10-year yield is not a realised YTD cash return.
        irx = yf.Ticker("^IRX")
        irx_hist = irx.history(period="5d")
        if not irx_hist.empty:
            rf_rate = irx_hist['Close'].iloc[-1] / 100.0
            print(f"DEBUG: Using ^IRX cash proxy: {rf_rate:.4%}")
        else:
            rf_rate = 0.04
            print("Warning: ^IRX data unavailable. Defaulting Rf to 4%.")
    except Exception as e:
        print(f"Error fetching ^IRX: {e}. Defaulting Rf to 4%.")
        rf_rate = 0.04
    
    # --- 1. PREPARE PORTFOLIO RETURNS ---
    # Construct a weighted portfolio return series
    portfolio_daily_ret = pd.Series(0.0, index=returns_df.index)
    long_only_ret = pd.Series(0.0, index=returns_df.index)
    short_only_ret = pd.Series(0.0, index=returns_df.index)
    
    # Track Gross Exposure for Leverage Calc
    total_long_weight = 0
    total_short_weight = 0
    
    active_tickers = []
    
    # We need to normalize weights to 100% of invested capital for some metrics,
    # but for risk attribution, we use the actual exposure weights.
    
    for ticker, info in PORTFOLIO_CONFIG.items():
        if ticker in returns_df.columns:
            weight = info['weight']
            direction = 1 if info['type'] == 'Long' else -1
            
            if direction == 1: total_long_weight += weight
            else: total_short_weight += weight
            
            # If ticker didn't exist yet (return is 0), it contributes 0.
            # This implicitly assumes "Cash" was held instead.
            # Use fillna(0) to ensure missing returns (incomplete data) don't poison the whole portfolio series
            ticker_contrib = returns_df[ticker].fillna(0.0) * weight * direction
            portfolio_daily_ret += ticker_contrib
            
            # Accumulate into long/short sub-portfolios
            if direction == 1:
                long_only_ret += returns_df[ticker].fillna(0.0) * weight
            else:
                short_only_ret += returns_df[ticker].fillna(0.0) * weight * (-1)  # Short P&L
            
            active_tickers.append(ticker)

    # --- 1.5 LEVERAGE COST (DRAG) ---
    # Daily Cost = (Net Debit * Margin / 360) + (Gross Short * Borrow / 360)
    # Net Debit = Max(0, Long Exposure - 1.0) -> Assuming 1.0 is our Equity
    
    net_debit = max(0, total_long_weight - 1.0)
    daily_margin_cost = (net_debit * margin_rate) / 360
    daily_borrow_cost = (total_short_weight * borrow_fee) / 360
    total_daily_drag = daily_margin_cost + daily_borrow_cost
    
    # Net Returns (After Cost)
    portfolio_gross_ret = portfolio_daily_ret.copy()
    
    # Account for weekends and holidays using calendar days between trading days
    days_elapsed = portfolio_daily_ret.index.to_series().diff().dt.days.fillna(1).clip(lower=1)
    daily_drag_series = total_daily_drag * days_elapsed
    
    portfolio_daily_ret = portfolio_gross_ret - daily_drag_series
    portfolio_net_ret = portfolio_daily_ret

    # --- 2. CORE METRICS (use GROSS returns so historical metrics don't vary by cost tier) ---
    # Beta (Robust Calculation) — uses gross returns
    valid_mask = ~(np.isnan(portfolio_gross_ret) | np.isnan(benchmark_ret))
    clean_port = portfolio_gross_ret[valid_mask]
    clean_bench = benchmark_ret[valid_mask]
    
    if len(clean_bench) > 1:
        covariance = np.cov(clean_port, clean_bench)[0][1]
        market_variance = np.var(clean_bench, ddof=1)
        portfolio_beta = covariance / market_variance if market_variance > 0 else 0
    else:
        portfolio_beta = 0
    
    # --- 2.1 Sub-portfolio Betas (Long-only and Short-only vs benchmark) ---
    long_only_beta = 0
    short_only_beta = 0
    
    if len(clean_bench) > 1 and market_variance > 0:
        # Long-only beta: how much market risk does the long book carry?
        clean_long = long_only_ret[valid_mask]
        long_only_beta = np.cov(clean_long, clean_bench)[0][1] / market_variance
        
        # Short-only beta: how much market risk does the short book carry?
        # Note: short_only_ret is already the P&L (negative of stock return × weight),
        # so a positive beta here means the short book moves WITH the market 
        # (i.e., the shorts are correlated, providing a hedge when they go down).
        clean_short = short_only_ret[valid_mask]
        short_only_beta = np.cov(clean_short, clean_bench)[0][1] / market_variance
    
    # Volatility (Annualized) — uses gross returns, sample std
    daily_vol = np.std(portfolio_gross_ret, ddof=1)
    annual_vol = daily_vol * np.sqrt(ANNUAL_FACTOR)
    
    # Returns (Annualized) — uses gross returns
    avg_daily_ret = np.mean(portfolio_gross_ret)
    annual_ret = avg_daily_ret * ANNUAL_FACTOR
    
    # Sharpe Ratio (Dynamic Rf)
    sharpe_ratio = (annual_ret - rf_rate) / annual_vol if annual_vol > 0 else 0
    
    # Sortino uses target downside deviation across every observation, rather
    # than the standard deviation of negative days only.
    sortino_ratio = calculate_sortino_ratio(portfolio_gross_ret, rf_rate)
    
    # --- 3. TAIL RISK ---
    # Rolling 1-Month Standard Deviation (Annualized)
    rolling_window = 21  # ~1 month of trading days
    if len(portfolio_daily_ret) >= rolling_window:
        rolling_1m_vol = portfolio_daily_ret.iloc[-rolling_window:].std() * np.sqrt(ANNUAL_FACTOR)
    else:
        rolling_1m_vol = annual_vol  # Fallback: use overall vol if not enough data
    
    # CVaR 95% (Expected Shortfall) - Average of losses exceeding 5th percentile
    # Safeguard: check for empty or all-NaN data
    valid_returns = portfolio_daily_ret.dropna()
    if len(valid_returns) > 0:
        var_95 = np.percentile(valid_returns, 5)
        cvar_95 = valid_returns[valid_returns <= var_95].mean()
    else:
        var_95 = 0
        cvar_95 = 0

    
    # Max Drawdown
    cum_ret = value_series_from_returns(portfolio_daily_ret, start_index=price_df.index[0])
    drawdown = calculate_drawdown_series(cum_ret)
    max_drawdown = drawdown.min()

    # --- 4. RISK ATTRIBUTION (MCTR) ---
    # Marginal Contribution to Total Risk
    # Formula: MCTR_i = (Cov(R_i, R_p) / Std(R_p)) * Weight_i
    
    risk_contribution = {}
    total_risk_sum = 0
    
    if daily_vol > 0:
        for ticker in active_tickers:
            info = PORTFOLIO_CONFIG[ticker]
            weight = info['weight']
            direction = 1 if info['type'] == 'Long' else -1 # Directional weight
            signed_weight = weight * direction
            
            asset_ret = returns_df[ticker]
            # Covariance between Asset and Portfolio (Robust to NaNs)
            valid_mask = ~(np.isnan(asset_ret) | np.isnan(portfolio_daily_ret))
            clean_asset = asset_ret[valid_mask]
            clean_port = portfolio_daily_ret[valid_mask]
            
            if len(clean_asset) > 1:
                cov_asset_port = np.cov(clean_asset, clean_port)[0][1]
            else:
                cov_asset_port = 0
            
            # Marginal Contribution to Volatility
            mctr = (cov_asset_port * signed_weight) / daily_vol
            
            # Percent contribution to total volatility
            pct_contribution = mctr / daily_vol
            
            risk_contribution[ticker] = {
                'MCTR': mctr,
                'Pct_Risk': pct_contribution,
                'Weight': signed_weight
            }
            total_risk_sum += mctr
            
    # --- 4.4 Rolling Volatility ---
    # Rolling 1-Month Volatility (Annualized)
    rolling_vol_series = portfolio_daily_ret.rolling(window=21).std()
    rolling_1m_vol = rolling_vol_series.iloc[-1] * np.sqrt(ANNUAL_FACTOR) if not rolling_vol_series.empty else 0
    
    bench_rolling_vol_series = benchmark_ret.rolling(window=21).std()
    bench_rolling_1m_vol = bench_rolling_vol_series.iloc[-1] * np.sqrt(ANNUAL_FACTOR) if not bench_rolling_vol_series.empty else 0

    # --- 4.5 CAPM Metrics (Jensen's Alpha) ---
    # Alpha = Rp - (Rf_long + Beta * (Rm - Rf_long))
    # We need annualized benchmark return for this
    avg_bench_ret = np.mean(benchmark_ret)
    annual_bench_ret = avg_bench_ret * ANNUAL_FACTOR
    
    expected_return = rf_rate + portfolio_beta * (annual_bench_ret - rf_rate)
    jensens_alpha = annual_ret - expected_return
    
    # Metadata for transparency
    calc_start_date = returns_df.index[0].strftime('%Y-%m-%d')
    calc_end_date = returns_df.index[-1].strftime('%Y-%m-%d')
    period_years = (returns_df.index[-1] - returns_df.index[0]).days / 365.25

    # --- 5. YTD METRICS ---
    period_label, ytd_calc_start = get_period_params(portfolio_name)
    
    # Standard YTD Logic: Return = (Current_Price - Prev_Year_Close) / Prev_Year_Close
    # To implement this, we need to include the last data point from the previous year in our "YTD Series"
    # or explicitly fetch that "base price".
    
    # Check timezone again to be safe
    if hasattr(price_df.index, 'tz'):
        price_df.index = price_df.index.tz_localize(None)
    if hasattr(benchmark_ret.index, 'tz'):
        benchmark_ret.index = benchmark_ret.index.tz_localize(None)

    # Pre-fill prices to handle holidays (e.g. if Dec 31 is holiday for some tickers)
    # This ensures we get the last available price from previous year as the base.
    price_df_filled = price_df.ffill()

    # Find the index of the first date >= current_year
    # We want to slice from [prev_date : end]
    # This effectively makes the "YTD Stream" start at the Prev Year Close (Day 0)
    
    # Fallback default
    ytd_prices = pd.DataFrame() 
    ytd_benchmark = benchmark_ret[benchmark_ret.index >= ytd_calc_start]
    
    # Try to find the insertion point
    # Search for the first index that is >= ytd_calc_start
    # using searchsorted on the index
    try:
        start_idx_loc = price_df.index.searchsorted(pd.Timestamp(ytd_calc_start))
        if start_idx_loc > 0:
            # Include the previous day (Year-End Close)
            # We use the FILLED dataframe so we get Dec 30 price on the Dec 31 row if needed
            ytd_prices = price_df_filled.iloc[start_idx_loc-1 :]
            
        # Do the same for benchmark returns -> wait, benchmark is returns.
        # For benchmark, if we have returns, the "YTD Return" is usually sum/prod of returns starting Jan 2.
        # But for consistency in the "Growth Chart" starting at 0%, we usually just cumulate from Jan 1.
        # However, if we want to align the chart:
        # Day 0 (Dec 31): Val = 1.0
        # Day 1 (Jan 2): Val = 1.0 * (1 + r_jan2)
        # So we just need the returns from >= Jan 1.
        
        # But the user asked for "standard calculation" for performance.
        # If we just sum returns from Jan 2, that IS (P_curr / P_prev_close) - 1.
        # So for Benchmark *Returns* Series, we don't need to change the slice (it should start Jan 2).
        # We only need to be careful if we are comparing price series.
        pass
    except Exception as e:
        print(f"Error adjusting YTD Start Date: {e}")
        # Fallback to current year start is already set
        ytd_prices = price_df_filled[price_df_filled.index >= ytd_calc_start]
        pass

    if not ytd_prices.empty and len(ytd_prices) > 1:
        # --- BUY & HOLD SIMULATION ---
        # Normalize prices to start at 1.0
        # This "Start" is now effectively Dec 31st (Price_0)
        # Note: ytd_prices is already filled from history, but let's ffill forward too if any holes remain?
        ytd_prices_filled = ytd_prices.ffill() 
        ytd_rel_prices = ytd_prices_filled / ytd_prices_filled.iloc[0]
        
        segmented_ytd = calculate_segmented_ytd(
            ytd_prices_filled,
            portfolio_name,
            PORTFOLIO_CONFIG,
            ytd_calc_start,
            margin_rate,
            borrow_fee,
        )

        if segmented_ytd:
            portfolio_val_series_gross = segmented_ytd["portfolio_val_series_gross"]
            portfolio_val_series = segmented_ytd["portfolio_val_series"]
            ytd_return_gross = segmented_ytd["ytd_return_gross"]
            ytd_return = segmented_ytd["ytd_return"]
            ytd_financing_cost = segmented_ytd["ytd_financing_cost"]
            ytd_direct_financing_cost = segmented_ytd["ytd_direct_financing_cost"]
            annual_financing_cost = segmented_ytd["annual_financing_cost"]
            ytd_longs_contrib = segmented_ytd["ytd_longs_contrib"]
            ytd_shorts_contrib = segmented_ytd["ytd_shorts_contrib"]
            ytd_position_contributions = segmented_ytd["position_contributions"]
            ytd_position_contribution_history = segmented_ytd["position_contribution_history"]
            since_rebalance_position_contributions = segmented_ytd["latest_segment_position_contributions"]
            since_rebalance_position_contributions_ytd_basis = segmented_ytd["latest_segment_position_contributions_ytd_basis"]
            latest_rebalance_start_date = segmented_ytd["latest_segment_start_date"]
            ytd_current_weights = segmented_ytd["current_weights"]
            rebalance_events = segmented_ytd["rebalance_events"]
        else:
            # Calculate Value Series
            portfolio_val_series = pd.Series(0.0, index=ytd_rel_prices.index)
            ytd_position_contributions = {}
            ytd_position_contribution_history = pd.DataFrame(np.nan, index=ytd_rel_prices.index, columns=active_tickers)
            since_rebalance_position_contributions = {}
            since_rebalance_position_contributions_ytd_basis = {}
            latest_rebalance_start_date = ytd_rel_prices.index[0].strftime('%Y-%m-%d') if len(ytd_rel_prices.index) else None
            ytd_current_weights = {}
            rebalance_events = []

            ytd_longs_contrib = 0
            ytd_shorts_contrib = 0

            # NOTE: If ytd_prices includes Dec 31, then ytd_rel_prices[0] is 1.0 by definition.
            # The code below calculates contribution based on (Price_t / Price_0 - 1).
            # At t=0 (Dec 31), Price_t=Price_0 => Contrib = 0.
            # This correctly starts the chart at 0% (Value 1.0) on Dec 31.

            for ticker in active_tickers:
                info = PORTFOLIO_CONFIG[ticker]
                weight = info['weight']
                direction = 1 if info['type'] == 'Long' else -1

                # Check if ticker exists
                if ticker in ytd_rel_prices.columns:
                    asset_cum_ret = ytd_rel_prices[ticker] - 1

                    # Position Contribution
                    position_contrib = weight * direction * asset_cum_ret
                    portfolio_val_series += position_contrib.fillna(0)
                    ytd_position_contribution_history[ticker] = position_contrib

                    # Final Contribution (for summary)
                    final_contrib = position_contrib.iloc[-1]
                    if not pd.isna(final_contrib):
                        ytd_position_contributions[ticker] = float(final_contrib)
                        since_rebalance_position_contributions[ticker] = float(final_contrib)
                        since_rebalance_position_contributions_ytd_basis[ticker] = float(final_contrib)
                        if direction == 1:
                            ytd_longs_contrib += final_contrib
                        else:
                            ytd_shorts_contrib += final_contrib

            # Add initial base (1.0) to raw gross curve
            portfolio_val_series_gross = portfolio_val_series + 1.0
            ytd_trading_days = max(0, len(portfolio_val_series_gross) - 1)
            ytd_return_gross = portfolio_val_series_gross.iloc[-1] - 1.0 if not portfolio_val_series_gross.empty else 0.0

            if total_daily_drag != 0:
                # Calculate calendar days elapsed
                if len(portfolio_val_series_gross) > 1:
                    ytd_calendar_days = (portfolio_val_series_gross.index[-1] - portfolio_val_series_gross.index[0]).days
                else:
                    ytd_calendar_days = ytd_trading_days

                ytd_direct_financing_cost = ytd_calendar_days * total_daily_drag
                annual_financing_cost = total_daily_drag * 360

                # Derive gross daily returns from the Buy & Hold curve
                ytd_portfolio_daily_ret_gross = portfolio_val_series_gross.pct_change().fillna(0)

                # Create exact Net Portfolio Curve by subtracting daily drag (calendar adjusted) and compounding
                ytd_days_elapsed = ytd_portfolio_daily_ret_gross.index.to_series().diff().dt.days.fillna(1).clip(lower=1)
                ytd_daily_drag_series = total_daily_drag * ytd_days_elapsed
                ytd_portfolio_daily_ret_net = ytd_portfolio_daily_ret_gross - ytd_daily_drag_series

                # Override to start at 0.0 (returns series padding)
                ytd_portfolio_daily_ret_net.iloc[0] = 0.0

                portfolio_val_series = (1 + ytd_portfolio_daily_ret_net).cumprod()
                ytd_return = portfolio_val_series.iloc[-1] - 1.0
                ytd_financing_cost = float(portfolio_val_series_gross.iloc[-1] - portfolio_val_series.iloc[-1])

            else:
                # NO DRAG SCENARIO
                ytd_financing_cost = 0.0
                ytd_direct_financing_cost = 0.0
                annual_financing_cost = 0.0
                portfolio_val_series = portfolio_val_series_gross
                ytd_return = ytd_return_gross

            final_net_value = float(portfolio_val_series.iloc[-1]) if not portfolio_val_series.empty else 1.0
            ytd_current_weights = {}
            for ticker in active_tickers:
                if ticker not in ytd_rel_prices.columns:
                    continue
                info = PORTFOLIO_CONFIG[ticker]
                weight = float(info.get('weight', 0) or 0)
                final_rel = ytd_rel_prices[ticker].iloc[-1]
                if not pd.isna(final_rel) and final_net_value > 0:
                    ytd_current_weights[ticker] = float(weight * final_rel / final_net_value)

        benchmark_ytd = (1 + ytd_benchmark).prod() - 1.0

        # Derive Daily Returns for Vol/Beta/Sharpe consistency directly from the true Net curve
        ytd_portfolio_daily_ret = portfolio_val_series.pct_change().dropna()
        
        # Align benchmark
        ytd_benchmark_aligned = ytd_benchmark.reindex(ytd_portfolio_daily_ret.index).dropna()
        ytd_portfolio_daily_ret = ytd_portfolio_daily_ret.loc[ytd_benchmark_aligned.index]

        # YTD Beta
        if not ytd_benchmark_aligned.empty and np.var(ytd_benchmark_aligned, ddof=1) > 0:
            ytd_beta = calculate_beta(ytd_portfolio_daily_ret, ytd_benchmark_aligned)
            if pd.isna(ytd_beta):
                ytd_beta = 0.0
            ytd_correlation = np.corrcoef(ytd_portfolio_daily_ret, ytd_benchmark_aligned)[0][1]
            
            # YTD Beta History (Expanding Window)
            ytd_beta_history = pd.Series(index=ytd_benchmark_aligned.index, dtype=float)
            for i in range(2, len(ytd_benchmark_aligned) + 1):
                if i >= 14: # Minimum sample size filter to avoid massive math anomalies early in the year
                    port_slice = ytd_portfolio_daily_ret.iloc[:i]
                    bench_slice = ytd_benchmark_aligned.iloc[:i]
                    beta_val = calculate_beta(port_slice, bench_slice)
                    ytd_beta_history.iloc[i-1] = beta_val if not pd.isna(beta_val) else 0.0
                else:
                    ytd_beta_history.iloc[i-1] = np.nan
        else:
            ytd_beta = 0
            ytd_correlation = 0
            ytd_beta_history = pd.Series()
            
        # YTD Sub-portfolio Betas
        ytd_long_only_beta = 0
        ytd_short_only_beta = 0
        
        if not ytd_benchmark_aligned.empty and np.var(ytd_benchmark_aligned, ddof=1) > 0:
            segmented_long_ret = segmented_ytd.get("long_daily_ret") if segmented_ytd else None
            segmented_short_ret = segmented_ytd.get("short_daily_ret") if segmented_ytd else None
            ytd_long_source = segmented_long_ret if segmented_long_ret is not None else long_only_ret
            ytd_short_source = segmented_short_ret if segmented_short_ret is not None else short_only_ret

            ytd_long_aligned = ytd_long_source.reindex(ytd_benchmark_aligned.index).fillna(0)
            ytd_long_only_beta = np.cov(ytd_long_aligned, ytd_benchmark_aligned)[0][1] / np.var(ytd_benchmark_aligned, ddof=1)
            
            ytd_short_aligned = ytd_short_source.reindex(ytd_benchmark_aligned.index).fillna(0)
            ytd_short_only_beta = np.cov(ytd_short_aligned, ytd_benchmark_aligned)[0][1] / np.var(ytd_benchmark_aligned, ddof=1)
            
        # Risk Efficiency -> YTD Sharpe (sample std)
        ytd_vol = np.std(ytd_portfolio_daily_ret, ddof=1) * np.sqrt(ANNUAL_FACTOR) if len(ytd_portfolio_daily_ret) > 1 else 0
        ytd_sortino = calculate_sortino_ratio(ytd_portfolio_daily_ret, rf_rate)

        if len(ytd_portfolio_daily_ret) >= 20:
            ytd_var_95 = float(np.percentile(ytd_portfolio_daily_ret, 5))
            ytd_cvar_95 = float(ytd_portfolio_daily_ret[ytd_portfolio_daily_ret <= ytd_var_95].mean())
        else:
            ytd_var_95 = np.nan
            ytd_cvar_95 = np.nan

        ytd_rolling_1m_vol = (
            float(ytd_portfolio_daily_ret.iloc[-21:].std(ddof=1) * np.sqrt(ANNUAL_FACTOR))
            if len(ytd_portfolio_daily_ret) >= 21 else ytd_vol
        )
        
        # Determine Annualized Returns
        ytd_ann_ret = np.mean(ytd_portfolio_daily_ret) * ANNUAL_FACTOR
        bench_ytd_ann_ret = np.mean(ytd_benchmark) * ANNUAL_FACTOR

        ytd_sharpe = (ytd_ann_ret - rf_rate) / ytd_vol if ytd_vol > 0 else 0
        
        # Benchmark YTD Sharpe (sample std)
        bench_ytd_vol = np.std(ytd_benchmark, ddof=1) * np.sqrt(ANNUAL_FACTOR) if len(ytd_benchmark) > 1 else 0
        bench_ytd_sharpe = (bench_ytd_ann_ret - rf_rate) / bench_ytd_vol if bench_ytd_vol > 0 else 0
        bench_ytd_rolling_1m_vol = (
            float(ytd_benchmark_aligned.iloc[-21:].std(ddof=1) * np.sqrt(ANNUAL_FACTOR))
            if len(ytd_benchmark_aligned) >= 21 else bench_ytd_vol
        )
        
        # Realised observations used for beta and compounded period alpha.
        # Annualised arithmetic alpha complements the compounded period alpha.
        ytd_expected_return = rf_rate + ytd_beta * (bench_ytd_ann_ret - rf_rate)
        ytd_alpha = ytd_ann_ret - ytd_expected_return
        
        # Compound daily CAPM expectations over the realised return observations.
        # Formula: α = Rp - [Rf_long + β × (Rm - Rf_long)]
        ytd_alpha_raw, ytd_capm_expected_return = calculate_compounded_capm_alpha(
            ytd_portfolio_daily_ret,
            ytd_benchmark_aligned,
            ytd_beta,
            rf_rate,
        )

        # Benchmark Historical Sharpe (sample std)
        bench_ann_vol = np.std(benchmark_ret, ddof=1) * np.sqrt(ANNUAL_FACTOR) if len(benchmark_ret) > 1 else 0
        bench_hist_sharpe = (annual_bench_ret - rf_rate) / bench_ann_vol if bench_ann_vol > 0 else 0
        
        # YTD Max Drawdown (Portfolio)
        ytd_drawdown = calculate_drawdown_series(portfolio_val_series)
        ytd_max_drawdown = ytd_drawdown.min()

        # YTD Max Drawdown (Benchmark)
        # Note: ytd_benchmark is typically daily returns, construct value index first
        # We did this earlier for alignment? No, ytd_benchmark is the slice of returns.
        if not ytd_benchmark.empty and not portfolio_val_series.empty:
            ytd_benchmark_curve_returns = ytd_benchmark.reindex(portfolio_val_series.index).fillna(0.0)
            ytd_benchmark_curve_returns.iloc[0] = 0.0
            ytd_bench_idx = value_series_from_returns(ytd_benchmark_curve_returns)
            ytd_bench_drawdown = calculate_drawdown_series(ytd_bench_idx)
            ytd_bench_max_drawdown = ytd_bench_drawdown.min()
        else:
            ytd_bench_max_drawdown = 0.0

        # --- 5.1 FX WATCHLIST YTD ---
        fx_watchlist_data = {}
        if fx_df is not None:
            for fx_ticker in WATCHLIST_FX:
                try:
                    if fx_ticker in fx_df.columns:
                        series = fx_df[fx_ticker]
                        # Fix TZ if needed
                        if hasattr(series.index, 'tz') and series.index.tz is not None:
                            series.index = series.index.tz_localize(None)

                        if not series.empty:
                            curr_val = series.iloc[-1]
                            # Find start val (close of prev year)
                            start_idx = series.index.searchsorted(pd.Timestamp(ytd_calc_start))
                            if start_idx > 0:
                                start_val = series.iloc[start_idx - 1]
                                ytd_fx = (curr_val - start_val) / start_val
                                fx_watchlist_data[fx_ticker] = ytd_fx
                            elif start_idx == 0:
                                start_val = series.iloc[0]
                                ytd_fx = (curr_val - start_val) / start_val
                                fx_watchlist_data[fx_ticker] = ytd_fx
                except Exception as e:
                     print(f"Error calc FX YTD for {fx_ticker}: {e}")

        # PLN Return (USD Return + FX Change)
        # Reuse fx_df data instead of making another API call
        try:
            if fx_df is not None and 'USDPLN=X' in fx_df.columns:
                pln_series = fx_df['USDPLN=X'].dropna()
                
                if not pln_series.empty:
                    # Normalize timezone
                    if hasattr(pln_series.index, 'tz') and pln_series.index.tz is not None:
                        pln_series.index = pln_series.index.tz_localize(None)
                    
                    target_start_date = ytd_prices.index[0]
                    idx_loc = pln_series.index.searchsorted(target_start_date)
                    
                    if idx_loc < len(pln_series) and pln_series.index[idx_loc] == target_start_date:
                        pln_start_val = pln_series.iloc[idx_loc]
                    elif idx_loc > 0:
                        pln_start_val = pln_series.iloc[idx_loc-1]
                    else:
                        pln_start_val = pln_series.iloc[0]
                    
                    pln_end_val = pln_series.iloc[-1]
                    fx_ytd_change = (pln_end_val - pln_start_val) / pln_start_val
                    ytd_return_pln = (1 + ytd_return) * (1 + fx_ytd_change) - 1
                else:
                    ytd_return_pln = ytd_return
            else:
                ytd_return_pln = ytd_return
                
        except Exception as e:
            print(f"Error calculating PLN return: {e}")
            ytd_return_pln = ytd_return
        
        # WIG YTD
        if BENCHMARK_WIG in returns_df.columns:
            wig_ret = returns_df[BENCHMARK_WIG]
            if hasattr(wig_ret.index, 'tz') and wig_ret.index.tz is not None:
                wig_ret.index = wig_ret.index.tz_localize(None)
            # Use same logic? Benchmarks are returns streams here, not prices.
            # So just summing returns from Jan 1 is correct.
            ytd_wig = wig_ret[wig_ret.index >= ytd_calc_start]
            wig_ytd = (1 + ytd_wig).prod() - 1 if not ytd_wig.empty else 0
        else:
            wig_ytd = 0
            
        # MSCI World YTD
        if BENCHMARK_MSCI in returns_df.columns:
            msci_ret = returns_df[BENCHMARK_MSCI]
            if hasattr(msci_ret.index, 'tz') and msci_ret.index.tz is not None:
                msci_ret.index = msci_ret.index.tz_localize(None)
            ytd_msci = msci_ret[msci_ret.index >= ytd_calc_start]
            msci_ytd = (1 + ytd_msci).prod() - 1 if not ytd_msci.empty else 0
        else:
            msci_ytd = 0
            
        # Longs/Shorts Contribution was already accumulated efficiently in the main YTD loop above.
        ytd_historical_diagnostics = build_historical_diagnostics(
            portfolio_val_series,
            ytd_benchmark,
            ytd_position_contribution_history,
        )
        ytd_period_info = {
            'Start_Date': portfolio_val_series.index[0].strftime('%Y-%m-%d'),
            'End_Date': portfolio_val_series.index[-1].strftime('%Y-%m-%d'),
            'Years': round((portfolio_val_series.index[-1] - portfolio_val_series.index[0]).days / 365.25, 2),
        }
        
    else:
        ytd_return = 0.0
        ytd_return_gross = 0.0
        benchmark_ytd = 0.0
        ytd_beta = 0.0
        ytd_correlation = 0.0
        ytd_financing_cost = 0.0
        ytd_direct_financing_cost = 0.0
        annual_financing_cost = 0.0
        ytd_sharpe = 0.0
        ytd_sortino = 0.0
        bench_ytd_sharpe = 0.0
        ytd_vol = 0.0
        bench_ytd_vol = 0.0
        ytd_rolling_1m_vol = 0.0
        bench_ytd_rolling_1m_vol = 0.0
        ytd_var_95 = np.nan
        ytd_cvar_95 = np.nan
        bench_hist_sharpe = 0.0
        ytd_return_pln = 0.0
        wig_ytd = 0.0
        msci_ytd = 0.0
        ytd_longs_contrib = 0.0
        ytd_shorts_contrib = 0.0
        ytd_max_drawdown = 0.0
        ytd_bench_max_drawdown = 0.0
        ytd_alpha = 0.0
        ytd_alpha_raw = 0.0
        ytd_capm_expected_return = 0.0
        ytd_long_only_beta = 0.0
        ytd_short_only_beta = 0.0
        ytd_beta_history = pd.Series()
        portfolio_val_series_gross = pd.Series(dtype=float)
        portfolio_val_series = pd.Series(dtype=float)
        ytd_benchmark_aligned = pd.Series(dtype=float)
        ytd_position_contributions = {}
        ytd_position_contribution_history = pd.DataFrame()
        since_rebalance_position_contributions = {}
        since_rebalance_position_contributions_ytd_basis = {}
        latest_rebalance_start_date = None
        ytd_historical_diagnostics = []
        ytd_current_weights = {}
        rebalance_events = []
        ytd_period_info = {
            'Start_Date': ytd_calc_start,
            'End_Date': ytd_calc_start,
            'Years': 0.0,
        }

    # --- 6. VOLUME WEIGHTED CORRELATION (Past 1 Year) ---
    vol_weighted_corr = pd.DataFrame()
    if volume_df is not None and not volume_df.empty:
        try:
            print("Calculating Volume Weighted Correlation Matrix...")
            # Filter for last 1 year (252 trading days)
            one_year_ago = price_df.index[-1] - pd.Timedelta(days=365)
            
            # Align slices
            sub_rets = returns_df[returns_df.index >= one_year_ago]
            # Reindex aligned volume and prices
            sub_vol = volume_df.reindex(sub_rets.index).fillna(0)
            sub_prices = price_df.reindex(sub_rets.index).ffill()
            
            # Use active tickers only involved in portfolio
            calc_tickers = [t for t in active_tickers if t in sub_rets.columns and t in sub_vol.columns]
            
            # Calculate Dollar Volume = Price * Volume
            dv_df = sub_prices[calc_tickers] * sub_vol[calc_tickers]
            
            # Initialize Matrix
            n = len(calc_tickers)
            vw_corr_mat = np.eye(n)
            
            # Pairwise Calculation
            for i in range(n):
                for j in range(i + 1, n):
                    t1, t2 = calc_tickers[i], calc_tickers[j]
                    
                    r1 = sub_rets[t1].values
                    r2 = sub_rets[t2].values
                    dv1 = dv_df[t1].values
                    dv2 = dv_df[t2].values
                    
                    # Weights: Geometric mean of Dollar Volumes
                    w = np.sqrt(dv1 * dv2)
                    w_sum = np.sum(w)
                    
                    if w_sum != 0:
                        w_norm = w / w_sum
                        mu1 = np.sum(r1 * w_norm)
                        mu2 = np.sum(r2 * w_norm)
                        cov = np.sum(w_norm * (r1 - mu1) * (r2 - mu2))
                        var1 = np.sum(w_norm * (r1 - mu1)**2)
                        var2 = np.sum(w_norm * (r2 - mu2)**2)
                        
                        if var1 > 0 and var2 > 0:
                            corr_val = cov / np.sqrt(var1 * var2)
                        else:
                            corr_val = 0
                        
                        vw_corr_mat[i, j] = corr_val
                        vw_corr_mat[j, i] = corr_val

            vol_weighted_corr = pd.DataFrame(vw_corr_mat, index=calc_tickers, columns=calc_tickers)
            
        except Exception as e:
            print(f"Error calculating Volume Weighted Correlation: {e}")
            vol_weighted_corr = pd.DataFrame()

    with open("debug_risk.txt", "a") as f:
        f.write(f"DEBUG: YTD Return (Cum): {ytd_return:.4%}\n")

    # --- 9. FX WATCHLIST METRICS ---
    fx_watchlist_metrics = {}
    if fx_df is not None and not fx_df.empty:
        try:
            curr_year_start = pd.Timestamp(ytd_calc_start)
            for fx_ticker in WATCHLIST_FX:
                if fx_ticker in fx_df.columns:
                    series = fx_df[fx_ticker].dropna()
                    if series.empty: continue
                    if hasattr(series.index, 'tz') and series.index.tz is not None:
                        series.index = series.index.tz_localize(None)
                    
                    current_val = series.iloc[-1]
                    idx_start = series.index.searchsorted(curr_year_start)
                    
                    if idx_start > 0:
                        start_val = series.iloc[idx_start - 1]
                        ytd_perf = (current_val - start_val) / start_val
                    elif idx_start == 0:
                        start_val = series.iloc[0]
                        ytd_perf = (current_val - start_val) / start_val
                    else:
                        ytd_perf = 0.0
                    
                    # Clean Name
                    clean_name = fx_ticker.replace("=X", "").replace("-", "/")
                    if len(clean_name) == 6 and "/" not in clean_name:
                         clean_name = f"{clean_name[:3]}/{clean_name[3:]}"
                    
                    fx_watchlist_metrics[clean_name] = ytd_perf
        except Exception as e:
            print(f"Error calculating FX metrics: {e}")

    # --- 10. TALEB METRICS (Kurtosis, Skew, Fat Tail) ---
    try:
        # Fisher Kurtosis (Normal = 0 via scipy default? No, scipy pearson is 3, fisher is 0. 
        # default fisher=True in scipy.stats.kurtosis)
        if not portfolio_daily_ret.empty:
             clean_ret = portfolio_daily_ret.dropna()
             port_kurtosis = kurtosis(clean_ret, fisher=True)
             port_skew = skew(clean_ret)
        else:
             port_kurtosis = 0
             port_skew = 0
        
        # Fat Tail Score: Simple heuristic
        # High Kurtosis (>1) + Negative Skew (<-0.5) = Turkey Risk
        risk_score = 0
        if port_kurtosis > 1.0: risk_score += 1
        if port_kurtosis > 3.0: risk_score += 1 # Very fat tails
        if port_skew < -0.5: risk_score += 1
        if port_skew < -1.5: risk_score += 2 # Severe negative skew
        
        fat_tail_rating = "Low"
        if risk_score >= 4: fat_tail_rating = "CRITICAL (Turkey)"
        elif risk_score >= 2: fat_tail_rating = "Moderate"
        
    except Exception as e:
        print(f"Error calculating Taleb metrics: {e}")
        port_kurtosis, port_skew, fat_tail_rating = 0, 0, "Error"
    
    # --- 11. INSIDER DATA ---
    # Removed for performance
    
    # --- 12. CONVEXITY METRICS (YTD Only) ---
    if not portfolio_val_series_gross.empty and not ytd_benchmark_aligned.empty and len(ytd_benchmark_aligned) >= 2:
        ytd_portfolio_gross_aligned = portfolio_val_series_gross.pct_change().dropna().reindex(ytd_benchmark_aligned.index).fillna(0)
        convexity_metrics = calculate_convexity_metrics(ytd_portfolio_gross_aligned, ytd_benchmark_aligned)
    else:
        convexity_metrics = None

    # --- 12b. ENRICH SCATTER DATA WITH PER-DAY CONTRIBUTORS ---
    # For every scatter point add top-3 positive and top-3 negative ticker contributions
    # so the frontend tooltip can display "who drove the move that day".
    if convexity_metrics and convexity_metrics.get('Scatter_Data'):
        # pre-build a tz-naive index lookup from returns_df for fast .at[] access
        ret_idx_set = set(returns_df.index)
        enriched = []
        for point in convexity_metrics['Scatter_Data']:
            date_str, bench_r, port_r = point[0], point[1], point[2]
            top3, bot3 = [], []
            try:
                date_ts = pd.Timestamp(date_str)
                if date_ts in ret_idx_set:
                    contrib_list = []
                    portfolio_config = get_effective_portfolio_config(portfolio_name, date_ts)
                    for tkr, cfg in portfolio_config.items():
                        if tkr not in returns_df.columns:
                            continue
                        w = cfg.get('weight', 0)
                        if not w:
                            continue
                        d = 1 if cfg.get('type', 'Long') == 'Long' else -1
                        r = returns_df.at[date_ts, tkr]
                        if pd.isna(r):
                            continue
                        c = w * d * float(r)
                        contrib_list.append({
                            't': tkr,
                            'c': round(c, 5),    # contribution to portfolio (decimal)
                            'r': round(float(r), 5)  # raw stock price move (decimal)
                        })
                    contrib_list.sort(key=lambda x: x['c'], reverse=True)
                    top3 = contrib_list[:3]
                    bot3 = sorted(
                        [x for x in contrib_list if x['c'] < 0],
                        key=lambda x: x['c']
                    )[:3]
            except Exception as ex:
                print(f"Warning: could not enrich scatter point {date_str}: {ex}")
            enriched.append({'d': date_str, 'b': bench_r, 'p': port_r, 'top': top3, 'bot': bot3})
        convexity_metrics['Scatter_Data'] = enriched
        
    momentum_metrics = calculate_momentum_metrics(returns_df, portfolio_name=portfolio_name)
    
    return {
        'Taleb_Metrics': {
            'Kurtosis': port_kurtosis,
            'Skewness': port_skew,
            'Fat_Tail_Rating': fat_tail_rating
        },
        # 'Insider_Data': {}, 
        'Beta': portfolio_beta,
        'Long_Only_Beta': long_only_beta,
        'Short_Only_Beta': short_only_beta,
        'Annual_Return': annual_ret,
        'Annual_Vol': annual_vol,
        'Sharpe': sharpe_ratio,
        'Sortino': sortino_ratio,
        'Rolling_1M_Vol': rolling_1m_vol,
        'Benchmark_Rolling_1M_Vol': bench_rolling_1m_vol,
        'CVaR_95': cvar_95,
        'VaR_95': var_95,
        'Max_Drawdown': max_drawdown,
        'Jensens_Alpha': jensens_alpha,
        'Period_Info': {
            'Start_Date': calc_start_date,
            'End_Date': calc_end_date,
            'Years': round(period_years, 1)
        },
        'YTD_Return': ytd_return,
        'YTD_Annual_Return': ytd_ann_ret if 'ytd_ann_ret' in locals() else 0.0,
        'Benchmark_YTD': benchmark_ytd,
        'YTD_Beta': ytd_beta,
        'YTD_Correlation': ytd_correlation,
        'YTD_Long_Only_Beta': ytd_long_only_beta if 'ytd_long_only_beta' in locals() else 0,
        'YTD_Short_Only_Beta': ytd_short_only_beta if 'ytd_short_only_beta' in locals() else 0,
        'YTD_Sharpe': ytd_sharpe,
        'YTD_Sortino': ytd_sortino,
        'Benchmark_YTD_Sharpe': bench_ytd_sharpe,
        'YTD_Vol': ytd_vol,
        'Benchmark_YTD_Vol': bench_ytd_vol,
        'YTD_Rolling_1M_Vol': ytd_rolling_1m_vol,
        'Benchmark_YTD_Rolling_1M_Vol': bench_ytd_rolling_1m_vol,
        'YTD_VaR_95': ytd_var_95,
        'YTD_CVaR_95': ytd_cvar_95,
        'Benchmark_Hist_Sharpe': bench_hist_sharpe,
        'YTD_Return_PLN': ytd_return_pln,
        'WIG_YTD': wig_ytd,
        'MSCI_YTD': msci_ytd,
        'Period_Label': period_label,
        'YTD_Period_Info': ytd_period_info,
        'YTD_Longs_Contrib': ytd_longs_contrib,
        'YTD_Shorts_Contrib': ytd_shorts_contrib,
        'YTD_Security_Gross_Contribution': ytd_return_gross,
        'YTD_Alpha': ytd_alpha,
        'YTD_Alpha_Raw': ytd_alpha_raw,
        'YTD_CAPM_Expected_Return': ytd_capm_expected_return,
        'YTD_Max_Drawdown': ytd_max_drawdown,
        'Benchmark_YTD_Max_Drawdown': ytd_bench_max_drawdown,
        'YTD_Financing_Cost': ytd_financing_cost,
        'YTD_Direct_Financing_Cost': ytd_direct_financing_cost,
        'YTD_Return_Gross': ytd_return_gross,
        'Annual_Financing_Cost': annual_financing_cost,
        'Current_Book_Scenario': {
            'scope': 'Static current-target-weight replay; not realised portfolio history',
            'period': {
                'startDate': calc_start_date,
                'endDate': calc_end_date,
                'years': round(period_years, 1),
            },
            'beta': portfolio_beta,
            'annualReturn': annual_ret,
            'annualVolatility': annual_vol,
            'sharpe': sharpe_ratio,
            'sortino': sortino_ratio,
            'maxDrawdown': max_drawdown,
            'var95Daily': var_95,
            'cvar95Daily': cvar_95,
        },
        'Performance_Methodology': {
            'realisedScope': 'Dated rebalance snapshots chained into USD net NAV',
            'contributionScope': 'Gross security contribution before financing',
            'financingScope': 'Estimated margin and borrow carry; broker ledger not connected',
        },
        'Returns_Stream': portfolio_daily_ret,
        'Net_Stream': portfolio_net_ret, 
        'Benchmark_Stream': benchmark_ret, 
        'Drawdown_Stream': drawdown,
        'Risk_Attribution': risk_contribution,
        'Correlation_Matrix': returns_df.corr(),
        'Volume_Weighted_Correlation': vol_weighted_corr,
        'Leverage_Stats': {
            'Long_Exp': total_long_weight,
            'Short_Exp': total_short_weight,
            'Gross_Exp': total_long_weight + total_short_weight,
            'Net_Exp': total_long_weight - total_short_weight,
            'Daily_Drag': total_daily_drag
        },
        'Fx_Watchlist': fx_watchlist_metrics,
        'YTD_Stream': portfolio_val_series if 'portfolio_val_series' in locals() else None,
        'YTD_Gross_Stream': portfolio_val_series_gross if 'portfolio_val_series_gross' in locals() else None,
        'YTD_Benchmark_Stream': ytd_benchmark if 'ytd_benchmark' in locals() else None,
        'YTD_Beta_History': ytd_beta_history if 'ytd_beta_history' in locals() else None,
        'YTD_Position_Contributions': ytd_position_contributions if 'ytd_position_contributions' in locals() else {},
        'YTD_Position_Contribution_History': ytd_position_contribution_history if 'ytd_position_contribution_history' in locals() else pd.DataFrame(),
        'Since_Rebalance_Position_Contributions': since_rebalance_position_contributions if 'since_rebalance_position_contributions' in locals() else {},
        'Since_Rebalance_Position_Contributions_YTD_Basis': since_rebalance_position_contributions_ytd_basis if 'since_rebalance_position_contributions_ytd_basis' in locals() else {},
        'Latest_Rebalance_Start_Date': latest_rebalance_start_date if 'latest_rebalance_start_date' in locals() else None,
        'YTD_Historical_Diagnostics': ytd_historical_diagnostics if 'ytd_historical_diagnostics' in locals() else [],
        'YTD_Current_Weights': ytd_current_weights if 'ytd_current_weights' in locals() else {},
        'Rebalance_Events': rebalance_events if 'rebalance_events' in locals() else [],
        'Rebalance_Mode': 'dated_snapshots' if rebalance_events else 'static',
        'Convexity_Metrics': convexity_metrics,
        'Momentum_Metrics': momentum_metrics
    }

def calculate_momentum_metrics(returns_df, portfolio_name="main"):
    """Calculate Relative Strength vs regional benchmarks and 1-month vs 1-year Correlation surges."""
    PORTFOLIO_CONFIG = get_effective_portfolio_config(portfolio_name)
    try:
        # Timeframes
        recent_21d = returns_df.iloc[-21:] if len(returns_df) >= 21 else returns_df
        recent_252d = returns_df.iloc[-252:] if len(returns_df) >= 252 else returns_df
        
        # 1. Relative Strength vs Regional Benchmark
        rs_data = []
        for tkr, cfg in PORTFOLIO_CONFIG.items():
            if tkr not in recent_21d.columns:
                continue
            
            # Determine benchmark
            country = cfg.get('country', 'USA')
            if country == 'USA':
                bmk = BENCHMARK
            elif country == 'POL':
                bmk = BENCHMARK_WIG
            else:
                bmk = BENCHMARK_MSCI
                
            if bmk not in recent_21d.columns:
                continue
                
            # Compute 21d compounded return
            tkr_ret = (1 + recent_21d[tkr]).prod() - 1
            bmk_ret = (1 + recent_21d[bmk]).prod() - 1
            
            rs_data.append({
                'ticker': tkr,
                'rs': round(float(tkr_ret - bmk_ret), 4),
                'stock_ret': round(float(tkr_ret), 4),
                'bmk_ret': round(float(bmk_ret), 4),
                'bmk': bmk
            })
            
        rs_data.sort(key=lambda x: x['rs'], reverse=True)
        top_rs = rs_data[:3]
        bot_rs = list(reversed(rs_data[-3:])) if len(rs_data) >= 3 else rs_data
        
        # 2. Correlation Surge
        # Only use active portfolio tickers
        active_tkrs = [t for t in PORTFOLIO_CONFIG.keys() if t in returns_df.columns]
        
        corr_1m = recent_21d[active_tkrs].corr()
        corr_1y = recent_252d[active_tkrs].corr()
        
        surges = []
        for i in range(len(active_tkrs)):
            for j in range(i + 1, len(active_tkrs)):
                t1 = active_tkrs[i]
                t2 = active_tkrs[j]
                
                c1m = corr_1m.loc[t1, t2]
                c1y = corr_1y.loc[t1, t2]
                
                if pd.isna(c1m) or pd.isna(c1y):
                    continue
                    
                delta = c1m - c1y
                
                # Filter: must be positively correlated now > 0.4 to be considered a strong directional link
                if c1m > 0.4:
                    surges.append({
                        't1': t1,
                        't2': t2,
                        'delta': round(float(delta), 4),
                        'c1m': round(float(c1m), 4),
                        'c1y': round(float(c1y), 4)
                    })
                    
        surges.sort(key=lambda x: x['delta'], reverse=True)
        top_surges = surges[:3]
        
        return {
            'top_rs': top_rs,
            'bot_rs': bot_rs,
            'all_rs': rs_data,
            'corr_surges': top_surges,
            'methodology': {
                'source': 'Yahoo Finance adjusted close via yfinance',
                'currencyBasis': 'USD-converted adjusted prices for portfolio comparability',
                'relativeStrength': '21-session security total return minus regional benchmark total return',
            },
        }
    except Exception as ex:
        print(f"Error calculating momentum metrics: {ex}")
        return None

def calculate_convexity_metrics(portfolio_ret, benchmark_ret):
    """Calculate portfolio convexity: capture ratios, quadratic regression, scatter data.
    
    A convex portfolio gains more when the market goes up and loses less when it goes down.
    This is captured by:
      - Upside Capture > Downside Capture (spread > 0)
      - Positive quadratic coefficient (β₂ > 0) in port = α + β₁·bench + β₂·bench²
    """
    print("--- 4a. Calculating Convexity Metrics ---")
    
    result = {
        'Upside_Capture': 0,
        'Downside_Capture': 0,
        'Capture_Spread': 0,
        'Quadratic_Coeffs': [0, 0, 0],  # [β₂, β₁, α]
        'R_Squared': 0,
        'Scatter_Data': [],
        'Is_Convex': False,
    }
    
    # Align and clean
    valid_mask = ~(np.isnan(portfolio_ret) | np.isnan(benchmark_ret))
    clean_port = portfolio_ret[valid_mask].values
    clean_bench = benchmark_ret[valid_mask].values
    clean_dates = portfolio_ret[valid_mask].index  # keep dates aligned
    
    if len(clean_bench) < 10:
        print("Warning: Insufficient data for convexity analysis (need at least 10 days)")
        return result
    
    # --- 1. CAPTURE RATIOS ---
    up_days = clean_bench > 0
    down_days = clean_bench < 0
    
    if np.sum(up_days) > 3 and np.sum(down_days) > 3:
        # Upside Capture = avg(port on up days) / avg(bench on up days)
        avg_port_up = np.mean(clean_port[up_days])
        avg_bench_up = np.mean(clean_bench[up_days])
        upside_capture = avg_port_up / avg_bench_up if avg_bench_up != 0 else 0
        
        # Downside Capture = avg(port on down days) / avg(bench on down days)
        avg_port_down = np.mean(clean_port[down_days])
        avg_bench_down = np.mean(clean_bench[down_days])
        downside_capture = avg_port_down / avg_bench_down if avg_bench_down != 0 else 0
        
        result['Upside_Capture'] = upside_capture
        result['Downside_Capture'] = downside_capture
        result['Capture_Spread'] = upside_capture - downside_capture
    
    # --- 2. REGRESSIONS (Quadratic & Linear) ---
    # Fit Quadratic: port_ret = α + β₁·bench_ret + β₂·bench_ret²
    # np.polyfit returns [β₂, β₁, α] for degree=2
    # Fit Linear: port_ret = α + β₁·bench_ret
    # np.polyfit returns [β₁, α] for degree=1
    try:
        quad_coeffs = np.polyfit(clean_bench, clean_port, 2)
        lin_coeffs = np.polyfit(clean_bench, clean_port, 1)
        
        result['Quadratic_Coeffs'] = quad_coeffs.tolist()
        result['Linear_Coeffs'] = lin_coeffs.tolist()
        
        # R² calculation for quadratic
        predicted = np.polyval(quad_coeffs, clean_bench)
        ss_res = np.sum((clean_port - predicted) ** 2)
        ss_tot = np.sum((clean_port - np.mean(clean_port)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        result['R_Squared'] = r_squared
        
        # Positive β₂ means convex (gains accelerate, losses decelerate)
        result['Is_Convex'] = quad_coeffs[0] > 0
        
    except Exception as e:
        print(f"Warning: Regressions failed: {e}")
    
    # --- 3. SCATTER DATA (subsample for payload size) ---
    max_points = 500
    if len(clean_bench) > max_points:
        indices = np.random.choice(len(clean_bench), max_points, replace=False)
        indices.sort()
        scatter_bench = clean_bench[indices]
        scatter_port = clean_port[indices]
        scatter_dates = [clean_dates[i].strftime('%Y-%m-%d') for i in indices]
    else:
        scatter_bench = clean_bench
        scatter_port = clean_port
        scatter_dates = [d.strftime('%Y-%m-%d') for d in clean_dates]
    
    # Each point: [date, benchRet, portRet]
    result['Scatter_Data'] = [[d, float(b), float(p)] for d, b, p in zip(scatter_dates, scatter_bench.tolist(), scatter_port.tolist())]
    
    return result


def stress_test_portfolio(metrics):
    """Stress test with beta-only, alpha-neutral, and alpha-included lenses.

    Risk stress should not treat recent intercept/alpha as structural downside
    protection. The primary non-linear impact is therefore alpha-neutral:
    daily portfolio move = beta_1 * market + beta_2 * market^2. The fitted
    model including alpha is still returned as context, but it is not the
    headline risk number.
    """
    print("--- 4b. Running Non-Linear Stress Tests ---")
    if metrics is None: return {}
    
    # Use YTD Beta for linear estimate to match the YTD quadratic model
    beta = metrics.get('YTD_Beta', metrics['Beta'])
    convexity = metrics.get('Convexity_Metrics')
    
    scenarios = {
        'Market Crash (-10%)': -0.10,
        'Market Correction (-5%)': -0.05,
        'Market Rally (+5%)': 0.05,
        'Market Surge (+10%)': 0.10
    }
    
    results = {}
    
    # Get quadratic coefficients if available
    has_quadratic = (convexity is not None and 
                     convexity.get('Quadratic_Coeffs') and
                     convexity['R_Squared'] > 0.01)
    
    coeffs = None

    if has_quadratic:
        coeffs = convexity['Quadratic_Coeffs']  # [β₂, β₁, α]

    def compound_daily_return(daily_ret, days):
        # Avoid invalid compounding if a regression extrapolates below -100%.
        daily_ret = max(float(daily_ret), -0.99)
        return (1 + daily_ret) ** days - 1

    for name, mkt_move in scenarios.items():
        # The regression was fit on daily observations. Use enough steps to
        # keep each benchmark shock near 1% in magnitude, then compound.
        stress_days = max(1, int(np.ceil(abs(np.log1p(mkt_move)) / 0.01)))
        daily_market_move = np.expm1(np.log1p(mkt_move) / stress_days)

        linear_daily = beta * daily_market_move
        linear_est = compound_daily_return(linear_daily, stress_days)
        
        if has_quadratic and coeffs is not None:
            curve_coeff, slope_coeff, intercept = coeffs
            alpha_neutral_daily = (curve_coeff * daily_market_move ** 2) + (slope_coeff * daily_market_move)
            fitted_with_alpha_daily = alpha_neutral_daily + intercept
            alpha_neutral_est = compound_daily_return(alpha_neutral_daily, stress_days)
            fitted_with_alpha_est = compound_daily_return(fitted_with_alpha_daily, stress_days)
        else:
            curve_coeff = 0.0
            slope_coeff = beta
            intercept = 0.0
            alpha_neutral_daily = linear_daily
            fitted_with_alpha_daily = linear_daily
            alpha_neutral_est = linear_est
            fitted_with_alpha_est = linear_est
        
        results[name] = {
            'linear': linear_est,
            'nonlinear': alpha_neutral_est,
            'alpha_neutral': alpha_neutral_est,
            'fitted_with_alpha': fitted_with_alpha_est,
            'shape_effect': alpha_neutral_est - linear_est,
            'alpha_effect': fitted_with_alpha_est - alpha_neutral_est,
            'market_move': mkt_move,
            'stress_days': stress_days,
            'daily_market_move': daily_market_move,
            'alpha_neutral_daily': alpha_neutral_daily,
            'fitted_with_alpha_daily': fitted_with_alpha_daily,
            'model_curve': curve_coeff,
            'model_slope': slope_coeff,
            'model_intercept': intercept
        }
    
    return results

def run_monte_carlo(metrics, num_sims=1000, days=60):
    print(f"--- 5. Running Monte Carlo Simulation ({num_sims} paths, {days} days) ---")
    if metrics is None: return None
    
    annual_vol = metrics['Annual_Vol']
    # Geometric Brownian Motion Parameters
    # drift = r - 0.5 * sigma^2
    rf_rate = 0.04 
    dt = 1/252
    
    drift = rf_rate - 0.5 * annual_vol**2
    
    # Simulation: S_t = S_0 * exp((mu - 0.5*sigma^2)*t + sigma*W_t)
    # We simulate daily returns then cumulate
    
    # Z is a matrix of random normal variables (num_sims, days)
    Z = np.random.normal(0, 1, (num_sims, days))
    
    # Daily Returns
    daily_returns = np.exp(drift * dt + annual_vol * np.sqrt(dt) * Z)
    
    # Path Generation (Cumulative Product)
    price_paths = np.zeros((num_sims, days + 1))
    price_paths[:, 0] = 1.0 # Start at 1.0
    
    for t in range(1, days + 1):
        price_paths[:, t] = price_paths[:, t-1] * daily_returns[:, t-1]
        
    return price_paths

def calculate_periodic_returns(data, portfolio_name="main"):
    PORTFOLIO_CONFIG = get_all_position_configs(portfolio_name)
    print("--- 6. Calculating Periodic Returns (YTD, 1Y, 3Y, 5Y) ---")
    periods = {
        '1Y': 252,
        '3Y': 252 * 3,
        '5Y': 252 * 5
    }
    
    # YTD calculation: from Jan 1st of current year
    _, ytd_start = get_period_params(portfolio_name)
    
    results = {}
    
    for ticker in data.columns:
        series = data[ticker].dropna()
        if series.empty: continue
        
        # Normalize index to remove timezone
        if hasattr(series.index, 'tz') and series.index.tz is not None:
            series.index = series.index.tz_localize(None)
        
        current_price = series.iloc[-1]
        ticker_res = {}
        
        # Calculate YTD return
        # Logic: Use the price at the close of the PREVIOUS year (last price before ytd_start)
        # Find index of first date >= ytd_start
        try:
             # searchsorted finds the first index >= value
            idx_start = series.index.searchsorted(pd.Timestamp(ytd_start))
            if idx_start > 0:
                # Include the previous observation (Year-end Close) as the starting price
                ytd_start_price = series.iloc[idx_start - 1]
                ticker_res['YTD'] = (current_price - ytd_start_price) / ytd_start_price
            elif idx_start == 0:
                 # No data before Jan 1 (e.g. IPO), use first available
                ytd_start_price = series.iloc[0]
                ticker_res['YTD'] = (current_price - ytd_start_price) / ytd_start_price
            else:
                 # Should not happen unless series is empty
                 ticker_res['YTD'] = np.nan
        except:
             ticker_res['YTD'] = np.nan
        
        # Calculate standard periods
        for p_name, days in periods.items():
            if len(series) > days:
                past_price = series.iloc[-(days+1)]
                ret = (current_price - past_price) / past_price
                ticker_res[p_name] = ret
            else:
                ticker_res[p_name] = np.nan 
                
        results[ticker] = ticker_res
        
    return pd.DataFrame(results).T

# ==========================================
# 4. VISUALIZATION
# ==========================================
# ==========================================
# 4. VISUALIZATION & REPORTING
# ==========================================
def generate_report(metrics, data, portfolio_name="main"):
    PORTFOLIO_CONFIG = get_effective_portfolio_config(portfolio_name)
    if metrics is None: return

    print("\n" + "="*50)
    print(f"      HEDGE FUND RISK REPORT ({datetime.now().strftime('%Y-%m-%d')})      ")
    print("="*50)
    
    # --- 0. PERIODIC RETURNS (Print First) ---
    periodic_rets = calculate_periodic_returns(data, portfolio_name=portfolio_name)
    
    print(f"\n[INDIVIDUAL TICKER PERFORMANCE]")
    print(f"  {'TICKER':<10} | {'1 YEAR':<10} | {'3 YEARS':<10} | {'5 YEARS':<10}")
    print("-" * 55)
    
    # Sort by 1Y return for display
    sorted_periodic = periodic_rets.sort_values('1Y', ascending=False)
    
    for ticker, row in sorted_periodic.iterrows():
        r1y = f"{row['1Y']:.1%}" if not np.isnan(row['1Y']) else "N/A"
        r3y = f"{row['3Y']:.1%}" if not np.isnan(row['3Y']) else "N/A"
        r5y = f"{row['5Y']:.1%}" if not np.isnan(row['5Y']) else "N/A"
        
        print(f"  {ticker:<10} | {r1y:<10} | {r3y:<10} | {r5y:<10}")
    
    # --- SUMMARY STATS ---
    print(f"\n[PORTFOLIO VITALS]")
    print(f"  Beta:             {metrics['Beta']:.2f}")
    print(f"  Sharpe Ratio:     {metrics['Sharpe']:.2f}")
    print(f"  Sortino Ratio:    {metrics['Sortino']:.2f}")
    print(f"  Ann. Volatility:  {metrics['Annual_Vol']:.1%}")
    print(f"  Max Drawdown:     {metrics['Max_Drawdown']:.1%}")
    
    print(f"\n[TAIL RISK]")
    print(f"  VaR (95% Daily):  {metrics['VaR_95']:.2%}  (Loss exceeded 5% of days)")
    print(f"  CVaR (95% Daily): {metrics['CVaR_95']:.2%}  (Arg loss on bad days)")
    print(f"  *On $100k, Exp. Shortfall is ~${abs(metrics['CVaR_95']*100000):.0f} per day in crisis.*")

    # --- STRESS TEST ---
    stress_results = stress_test_portfolio(metrics)
    print(f"\n[STRESS TESTS (Linear Beta Approximation)]")
    for scenario, result in stress_results.items():
        print(f"  {scenario:<25} -> PnL Impact: {result:+.2%}")

    # --- RISK ATTRIBUTION ---
    print(f"\n[RISK ATTRIBUTION (Top Drivers of Volatility)]")
    sorted_risk = sorted(metrics['Risk_Attribution'].items(), key=lambda x: x[1]['Pct_Risk'], reverse=True)
    
    print(f"  {'TICKER':<10} | {'WEIGHT':<8} | {'% TOTAL RISK':<12} | {'COMMENT'}")
    print("-" * 60)
    
    for ticker, stats in sorted_risk[:8]: # Top 8
        pct_risk = stats['Pct_Risk']
        weight = stats['Weight']
        comment = "High Risk Efficiency" if abs(pct_risk) < abs(weight) else "Volatile!"
        print(f"  {ticker:<10} | {weight:<8.1%} | {pct_risk:<12.1%} | {comment}")

    # --- PLOTS ---
    # 1. Dashboard Plot
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle('Institutional Risk Dashboard', fontsize=16)
    
    # A. Current Correlations
    valid_tickers = [t for t in PORTFOLIO_CONFIG.keys() if t in data.columns]
    corr_matrix = metrics['Correlation_Matrix'].loc[valid_tickers, valid_tickers]
    sns.heatmap(corr_matrix, ax=axes[0,0], cmap='RdBu', center=0, annot=False, cbar=True)
    axes[0,0].set_title('Correlation Heatmap')
    
    # B. Cumulative Returns (Alpha Check)
    cum_returns = (1 + metrics['Returns_Stream']).cumprod()
    cum_bench = (1 + metrics['Benchmark_Stream']).cumprod()
    
    final_port_ret = cum_returns.iloc[-1] - 1
    final_bench_ret = cum_bench.iloc[-1] - 1
    alpha = final_port_ret - final_bench_ret
    
    axes[0,1].plot(cum_returns, color='green', linewidth=2, label=f'Portfolio ({final_port_ret:+.1%})')
    axes[0,1].plot(cum_bench, color='gray', linestyle='--', alpha=0.7, label=f'Market ({final_bench_ret:+.1%})')
    
    axes[0,1].set_title(f'Alpha Check (Excess Ret: {alpha:+.1%})')
    axes[0,1].legend()
    axes[0,1].grid(True, alpha=0.3)
    
    # C. Drawdowns
    drawdown = metrics['Drawdown_Stream']
    axes[1,0].fill_between(drawdown.index, drawdown, 0, color='red', alpha=0.3)
    axes[1,0].plot(drawdown, color='red', lw=1)
    axes[1,0].set_title('Underwater Plot (Drawdowns)')
    axes[1,0].grid(True, alpha=0.3)
    
    # D. Risk Contribution Bar Chart
    tickers = [x[0] for x in sorted_risk]
    vals = [x[1]['Pct_Risk'] for x in sorted_risk]
    colors = ['red' if v > 0 else 'green' for v in vals] # Short positions adding risk are usually hedging (negative risk contrib), if positive they add risk
    
    axes[1,1].bar(tickers[:10], vals[:10], color='purple')
    axes[1,1].set_title('Top Risk Contributors (%)')
    axes[1,1].tick_params(axis='x', rotation=45)
    
    # 2. Future Scenarios Plot (New Figure)
    fig2, axes2 = plt.subplots(1, 2, figsize=(15, 6))
    fig2.suptitle('Future Scenarios: "What happens next?"', fontsize=16)
    
    # E. Monte Carlo Cone
    mc_paths = run_monte_carlo(metrics)
    if mc_paths is not None:
        days = mc_paths.shape[1] - 1
        x_axis = range(days + 1)
        
        # Percentiles
        p5 = np.percentile(mc_paths, 5, axis=0)
        p50 = np.percentile(mc_paths, 50, axis=0)
        p95 = np.percentile(mc_paths, 95, axis=0)
        p1 = np.percentile(mc_paths, 1, axis=0) # Worst case
        
        axes2[0].plot(x_axis, p50, color='blue', lw=2, label='Median Path')
        axes2[0].fill_between(x_axis, p5, p95, color='blue', alpha=0.2, label='90% Confidence Cone')
        axes2[0].plot(x_axis, p1, color='red', linestyle='--', lw=1, label='Worst Case (1%)')
        
        axes2[0].set_title(f'Monte Carlo: Next {days} Days (1000 Sims)')
        axes2[0].set_ylabel('Portfolio Value (Start=1.0)')
        axes2[0].set_xlabel('Trading Days Ahead')
        axes2[0].legend()
        axes2[0].grid(True, alpha=0.3)
        
    # F. Stress Test Bar Chart
    scenarios = list(stress_results.keys())
    impacts = list(stress_results.values())
    colors_stress = ['red' if x < 0 else 'green' for x in impacts]
    
    axes2[1].barh(scenarios, impacts, color=colors_stress)
    axes2[1].set_title('Stress Test PnL Impact')
    axes2[1].set_xlabel('Estimated Return')
    axes2[1].grid(True, alpha=0.3)
    # Add value labels
    for i, v in enumerate(impacts):
        axes2[1].text(v if v > 0 else 0, i, f' {v:+.1%}', va='center')

    plt.tight_layout()
    plt.show()


    # 3. Leverage & Ticker Performance (New Figure)
    periodic_rets = calculate_periodic_returns(data)
    
    fig3, axes3 = plt.subplots(1, 2, figsize=(16, 8))
    fig3.suptitle('Leverage Impact & Asset Performance', fontsize=16)
    
    # G. Gross vs Net Equity Curve
    gross_curve = (1 + metrics['Returns_Stream']).cumprod()
    net_curve = (1 + metrics['Net_Stream']).cumprod()
    
    axes3[0].plot(gross_curve, color='green', linestyle='--', label='Gross Return (Pre-Fee)')
    axes3[0].plot(net_curve, color='darkgreen', linewidth=2, label='Net Return (Post-Fee)')
    
    lev_stats = metrics['Leverage_Stats']
    cost_text = (f"Leverage Profile:\n"
                 f"Long: {lev_stats['Long_Exp']:.0%}\n"
                 f"Short: {lev_stats['Short_Exp']:.0%}\n\n"
                 f"Est Annual Drag: -{lev_stats['Daily_Drag']*360:.1%}")
    
    axes3[0].text(0.05, 0.95, cost_text, transform=axes3[0].transAxes, 
                  verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    axes3[0].set_title('Cost of Leverage: Gross vs Net')
    axes3[0].legend()
    axes3[0].grid(True, alpha=0.3)
    
    # H. Ticker Performance Heatmap
    # Prepare data for heatmap
    sorted_periodic = periodic_rets.sort_values('1Y', ascending=False)
    # Convert to numeric, handle NaNs
    heatmap_data = sorted_periodic.astype(float)
    
    # Annotations: Format as percentage string or "" if NaN
    annot_data = heatmap_data.applymap(lambda x: f"{x:.1%}" if not np.isnan(x) else "")
    
    sns.heatmap(heatmap_data, annot=annot_data, fmt="", cmap="RdYlGn", center=0, ax=axes3[1], cbar_kws={'label': 'Total Return'})
    axes3[1].set_title('Asset Performance Heatmap')
    
    plt.tight_layout()
    plt.show()

def audit_data_quality(df):
    print("\n" + "="*50)
    print("      DATA QUALITY AUDIT      ")
    print("="*50)
    
    expected_tickers = list(PORTFOLIO_CONFIG.keys())
    if BENCHMARK not in expected_tickers:
        expected_tickers.append(BENCHMARK)
        
    print(f"{'TICKER':<10} | {'START DATE':<12} | {'END DATE':<12} | {'ROWS':<5} | {'LAST PRICE ($)':<15} | {'STATUS'}")
    print("-" * 85)
    
    problem_tickers = []
    
    for ticker in expected_tickers:
        status = "OK"
        if ticker not in df.columns:
            print(f"{ticker:<10} | {'MISSING':<12} | {'MISSING':<12} | {'0':<5} | {'N/A':<15} | [CRITICAL FAILURE]")
            problem_tickers.append(ticker)
            continue
            
        valid_data = df[ticker].dropna()
        if valid_data.empty:
            print(f"{ticker:<10} | {'EMPTY':<12} | {'EMPTY':<12} | {'0':<5} | {'N/A':<15} | [NO DATA]")
            problem_tickers.append(ticker)
            continue
            
        start_date = valid_data.index[0].strftime('%Y-%m-%d')
        end_date = valid_data.index[-1].strftime('%Y-%m-%d')
        row_count = len(valid_data)
        last_price = valid_data.iloc[-1]
        
        if row_count < 200:
            status = "[WARNING: THIN DATA]"
        
        print(f"{ticker:<10} | {start_date:<12} | {end_date:<12} | {row_count:<5} | {last_price:<15.2f} | {status}")

    print("-" * 85)
    if problem_tickers:
        print(f"\n[!] CAUTION: The following tickers have issues and will distort your risk model: {problem_tickers}")
    else:
        print("\n[OK] All tickers have sufficient data coverage.")

if __name__ == "__main__":
    raw_prices, fx_rates = fetch_data()
    usd_prices = normalize_to_base_currency(raw_prices, fx_rates)
    audit_data_quality(usd_prices)
    metrics = calculate_risk_metrics(usd_prices)
    generate_report(metrics, usd_prices)
