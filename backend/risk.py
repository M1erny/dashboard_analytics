import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta


# ==========================================
# 1. CONFIGURATION: Define Your Portfolio
# ==========================================
PORTFOLIO_CONFIG = {
    # --- LONG POSITIONS (150% Target) ---
    'AFRM':      {'weight': 0.20, 'type': 'Long', 'currency': 'USD'},
    'INPST.AS':  {'weight': 0.15, 'type': 'Long', 'currency': 'EUR'},
    'HARVIA.HE': {'weight': 0.15, 'type': 'Long', 'currency': 'EUR'},
    'BFT.WA':    {'weight': 0.15, 'type': 'Long', 'currency': 'PLN'},
    'NBIS':      {'weight': 0.05, 'type': 'Long', 'currency': 'USD'},
    'CDR.WA':    {'weight': 0.10, 'type': 'Long', 'currency': 'PLN'},
    '3659.T':    {'weight': 0.05, 'type': 'Long', 'currency': 'JPY'},
    'XTB.WA':    {'weight': 0.10, 'type': 'Long', 'currency': 'PLN'},
    'BRK-B':     {'weight': 0.10, 'type': 'Long', 'currency': 'USD'},
    'EQT':       {'weight': 0.10, 'type': 'Long', 'currency': 'USD'},
    'META':      {'weight': 0.10, 'type': 'Long', 'currency': 'USD'},
    'PSKY':      {'weight': 0.05, 'type': 'Long', 'currency': 'USD'}, # Updated Ticker
    'SWM.WA':    {'weight': 0.05, 'type': 'Long', 'currency': 'PLN'},
    'RBLX':      {'weight': 0.05, 'type': 'Long', 'currency': 'USD'},
    'SNAP':      {'weight': 0.05, 'type': 'Long', 'currency': 'USD'},
    'MU':        {'weight': 0.02, 'type': 'Long', 'currency': 'USD'},
    '000660.KS': {'weight': 0.02, 'type': 'Long', 'currency': 'KRW'},

    # --- SHORT POSITIONS (70% Target) ---
    'MSFT':      {'weight': 0.20, 'type': 'Short', 'currency': 'USD'},
    '7974.T':    {'weight': 0.10, 'type': 'Short', 'currency': 'JPY'},
    'JMT.LS':    {'weight': 0.075, 'type': 'Short', 'currency': 'EUR'},
    'CARL-B.CO': {'weight': 0.075, 'type': 'Short', 'currency': 'DKK'},
    'F':         {'weight': 0.075, 'type': 'Short', 'currency': 'USD'},
    'ABI.BR':    {'weight': 0.075, 'type': 'Short', 'currency': 'EUR'},
    'BDX.WA':    {'weight': 0.05, 'type': 'Short', 'currency': 'PLN'},
    'STLA':      {'weight': 0.05, 'type': 'Short', 'currency': 'USD'},
}

BENCHMARK = 'SPY'
BENCHMARK_WIG = 'WIG20.WA'  # Polish WIG20 Index
BENCHMARK = 'SPY'
BENCHMARK_WIG = 'WIG20.WA'  # Polish WIG20 Index
BENCHMARK_MSCI = 'URTH'     # iShares MSCI World ETF
WATCHLIST_FX = ['USDPLN=X', 'EURPLN=X', 'EURUSD=X', 'DKKEUR=X', 'JPYUSD=X'] # Pairs to track
BASE_CURRENCY = 'USD'
LOOKBACK_YEARS = 6

# Cost of Carry Assumptions
MARGIN_RATE = 0.055 # 5.5% on borrowed cash
BORROW_FEE = 0.01   # 1.0% hard-to-borrow fee estimate





# ==========================================
# 2. DATA ENGINE: Fetch & Normalize
# ==========================================
def fetch_data():
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
    
    print(f"Fetching stock data for {len(tickers)} tickers from {start_date}...")
    stock_raw = yf.download(tickers, start=start_date, auto_adjust=True)
    print(f"Stock Raw Shape: {stock_raw.shape}")
    if stock_raw.empty:
         print("WARNING: Stock Raw is EMPTY!")
    
    # Handle Data Structure (MultiIndex vs Single)
    if isinstance(stock_raw.columns, pd.MultiIndex):
        try:
            stock_data = stock_raw['Close']
            volume_data = stock_raw['Volume']
        except KeyError:
             stock_data = stock_raw.xs('Close', axis=1, level=0, drop_level=True)
             volume_data = stock_raw.xs('Volume', axis=1, level=0, drop_level=True)
    elif 'Close' in stock_raw.columns:
         stock_data = stock_raw['Close']
         volume_data = stock_raw['Volume']
    else:
        stock_data = stock_raw
        # Use dummy volume if missing (should not happen with standard downloads)
        volume_data = pd.DataFrame(1, index=stock_raw.index, columns=stock_raw.columns)
        
    print(f"Fetching FX rates for: {fx_pairs}...")
    fx_raw = yf.download(fx_pairs, start=start_date, auto_adjust=True)
    
    if isinstance(fx_raw.columns, pd.MultiIndex):
        try:
            fx_data = fx_raw['Close']
        except KeyError:
             fx_data = fx_raw.xs('Close', axis=1, level=0, drop_level=True)
    elif 'Close' in fx_raw.columns:
         fx_data = fx_raw['Close']
    else:
        fx_data = fx_raw

    return stock_data, fx_data, volume_data

def normalize_to_base_currency(stock_df, fx_df):
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
# ==========================================
# 3. RISK CALCULATOR (ADVANCED)
# ==========================================
def calculate_risk_metrics(price_df, volume_df=None, fx_df=None):
    print("--- 3. Calculating Advanced Risk Metrics ---")
    
    if price_df.empty or len(price_df) < 2:
        print("Error: Insufficient price data.")
        return None
        
    # Use dropna(how='all') to only drop rows where ALL values are NaN
    # This prevents dropping rows where just some tickers are missing
    returns_df = price_df.pct_change().dropna(how='all')
    
    # ... (skipping unchanged parts) ...

    # --- 5. YTD METRICS ---
    # ... (skipping calculation setup) ...

    # [Locate where we insert the FX Logic]
    # It was around line 493 where the error happened.
    pass

    # ... (Wait, I need to replace the whole function start or find the specific block)
    # Let's replace the signature first.

# Actually, let's fix the block I messed up first.

    print("--- 3. Calculating Advanced Risk Metrics ---")
    
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
    
    # --- 0.5. DYNAMIC RISK FREE RATE (^TNX) ---
    try:
        tnx = yf.Ticker("^TNX")
        tnx_hist = tnx.history(period="5d")
        if not tnx_hist.empty:
            # TNX is yield (e.g., 4.25), convert to decimal (0.0425)
            latest_yield = tnx_hist['Close'].iloc[-1]
            rf_rate = latest_yield / 100.0
            print(f"DEBUG: Using Dynamic Risk-Free Rate (^TNX): {rf_rate:.4%}")
        else:
            rf_rate = 0.04
            print("Warning: ^TNX data unavailable. Defaulting Rf to 4%.")
    except Exception as e:
        print(f"Error fetching ^TNX: {e}. Defaulting Rf to 4%.")
        rf_rate = 0.04
    
    # --- 1. PREPARE PORTFOLIO RETURNS ---
    # Construct a weighted portfolio return series
    portfolio_daily_ret = pd.Series(0.0, index=returns_df.index)
    
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
            portfolio_daily_ret += returns_df[ticker].fillna(0.0) * weight * direction
            active_tickers.append(ticker)

    # --- 1.5 LEVERAGE COST (DRAG) ---
    # Daily Cost = (Net Debit * Margin / 360) + (Gross Short * Borrow / 360)
    # Net Debit = Max(0, Long Exposure - 1.0) -> Assuming 1.0 is our Equity
    
    net_debit = max(0, total_long_weight - 1.0)
    daily_margin_cost = (net_debit * MARGIN_RATE) / 360
    daily_borrow_cost = (total_short_weight * BORROW_FEE) / 360
    total_daily_drag = daily_margin_cost + daily_borrow_cost
    
    # Net Returns (After Cost)
    portfolio_net_ret = portfolio_daily_ret - total_daily_drag

    # --- 2. CORE METRICS ---
    # Annualize factor
    ANNUAL_FACTOR = 252
    
    # Beta
    # Beta (Robust Calculation)
    valid_mask = ~(np.isnan(portfolio_daily_ret) | np.isnan(benchmark_ret))
    clean_port = portfolio_daily_ret[valid_mask]
    clean_bench = benchmark_ret[valid_mask]
    
    if len(clean_bench) > 1:
        covariance = np.cov(clean_port, clean_bench)[0][1]
        market_variance = np.var(clean_bench)
        portfolio_beta = covariance / market_variance if market_variance > 0 else 0
    else:
        portfolio_beta = 0
    
    # Volatility (Annualized)
    daily_vol = np.std(portfolio_daily_ret)
    annual_vol = daily_vol * np.sqrt(ANNUAL_FACTOR)
    
    # Returns (Annualized)
    avg_daily_ret = np.mean(portfolio_daily_ret)
    annual_ret = avg_daily_ret * ANNUAL_FACTOR
    
    # Sharpe Ratio (Dynamic Rf)
    sharpe_ratio = (annual_ret - rf_rate) / annual_vol if annual_vol > 0 else 0
    
    # Sortino Ratio (Downside Risk only)
    downside_returns = portfolio_daily_ret[portfolio_daily_ret < 0]
    downside_std = np.std(downside_returns) * np.sqrt(ANNUAL_FACTOR)
    sortino_ratio = (annual_ret - rf_rate) / downside_std if downside_std > 0 else 0
    
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
    cum_ret = (1 + portfolio_daily_ret).cumprod()
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
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

            total_risk_sum += mctr
            
    # --- 4.4 Rolling Volatility ---
    # Rolling 1-Month Volatility (Annualized)
    rolling_vol_series = portfolio_daily_ret.rolling(window=21).std()
    rolling_1m_vol = rolling_vol_series.iloc[-1] * np.sqrt(ANNUAL_FACTOR) if not rolling_vol_series.empty else 0
    
    bench_rolling_vol_series = benchmark_ret.rolling(window=21).std()
    bench_rolling_1m_vol = bench_rolling_vol_series.iloc[-1] * np.sqrt(ANNUAL_FACTOR) if not bench_rolling_vol_series.empty else 0

    # --- 4.5 CAPM Metrics (Jensen's Alpha) ---
    # Alpha = Rp - (Rf + Beta * (Rm - Rf))
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
    current_year = datetime.now().year
    ytd_calc_start = f"{current_year}-01-01"
    
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
        
        # Calculate Value Series
        portfolio_val_series = pd.Series(0.0, index=ytd_rel_prices.index)
        
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
                
                # Final Contribution (for summary)
                final_contrib = position_contrib.iloc[-1]
                if not pd.isna(final_contrib):
                    if direction == 1:
                        ytd_longs_contrib += final_contrib
                    else:
                        ytd_shorts_contrib += final_contrib

        # Add initial base (1.0)
        portfolio_val_series += 1.0
        
        # YTD Return (B&H)
        ytd_return = portfolio_val_series.iloc[-1] - 1
        benchmark_ytd = (1 + ytd_benchmark).prod() - 1

        # Derive Daily Returns for Vol/Beta/Sharpe consistency
        ytd_portfolio_daily_ret = portfolio_val_series.pct_change().dropna()
        
        # Align benchmark
        ytd_benchmark_aligned = ytd_benchmark.reindex(ytd_portfolio_daily_ret.index).dropna()
        ytd_portfolio_daily_ret = ytd_portfolio_daily_ret.loc[ytd_benchmark_aligned.index]

        # YTD Beta
        if not ytd_benchmark_aligned.empty and np.var(ytd_benchmark_aligned) > 0:
            ytd_beta = np.cov(ytd_portfolio_daily_ret, ytd_benchmark_aligned)[0][1] / np.var(ytd_benchmark_aligned)
        else:
            ytd_beta = 0
            
        # Risk Efficiency -> YTD Sharpe
        ytd_vol = np.std(ytd_portfolio_daily_ret) * np.sqrt(ANNUAL_FACTOR)
        ytd_ann_ret = np.mean(ytd_portfolio_daily_ret) * ANNUAL_FACTOR
        ytd_sharpe = (ytd_ann_ret - rf_rate) / ytd_vol if ytd_vol > 0 else 0
        
        # Benchmark YTD Sharpe
        bench_ytd_vol = np.std(ytd_benchmark) * np.sqrt(ANNUAL_FACTOR)
        bench_ytd_ann_ret = np.mean(ytd_benchmark) * ANNUAL_FACTOR
        bench_ytd_sharpe = (bench_ytd_ann_ret - rf_rate) / bench_ytd_vol if bench_ytd_vol > 0 else 0
        
        # YTD Jensen's Alpha
        ytd_expected_return = rf_rate + ytd_beta * (bench_ytd_ann_ret - rf_rate)
        ytd_alpha = ytd_ann_ret - ytd_expected_return

        # Benchmark Historical Sharpe
        bench_ann_vol = np.std(benchmark_ret) * np.sqrt(ANNUAL_FACTOR)
        bench_hist_sharpe = (annual_bench_ret - rf_rate) / bench_ann_vol if bench_ann_vol > 0 else 0
        
        # YTD Max Drawdown (Portfolio)
        ytd_cum_max = portfolio_val_series.cummax()
        ytd_drawdown = (portfolio_val_series - ytd_cum_max) / ytd_cum_max
        ytd_max_drawdown = ytd_drawdown.min()

        # YTD Max Drawdown (Benchmark)
        # Note: ytd_benchmark is typically daily returns, construct value index first
        # We did this earlier for alignment? No, ytd_benchmark is the slice of returns.
        if not ytd_benchmark.empty:
            ytd_bench_idx = (1 + ytd_benchmark).cumprod()
            ytd_bench_cum_max = ytd_bench_idx.cummax()
            ytd_bench_drawdown = (ytd_bench_idx - ytd_bench_cum_max) / ytd_bench_cum_max
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
        try:
            usdpln = yf.Ticker("USDPLN=X")
            # Fetch explicitly covering end of last year
            pln_hist = usdpln.history(start=(pd.Timestamp(ytd_calc_start) - pd.Timedelta(days=10)))
            
            if not pln_hist.empty:
                # Normalize timezone to match price_df
                if hasattr(pln_hist.index, 'tz'):
                    pln_hist.index = pln_hist.index.tz_localize(None)

                # Find the closest available price to YTD start (Dec 31 if possible, else Jan 1/2)
                # We want the last price BEFORE or ON ytd_calc_start (actually before Jan 1 usually means Dec 31)
                # But since we use simple pct_change for FX, let's just grab the price at the START of our ytd_prices period.
                
                target_start_date = ytd_prices.index[0] # Should be Dec 31 or Jan 2
                
                # Find available index closest to target_start_date
                # Using searchsorted / get_indexer methodology or just loop
                
                # Simplest: reindex
                idx_loc = pln_hist.index.searchsorted(target_start_date)
                # If exact match or close
                if idx_loc < len(pln_hist) and pln_hist.index[idx_loc] == target_start_date:
                    pln_start_val = pln_hist['Close'].iloc[idx_loc]
                elif idx_loc > 0:
                     # If target date (e.g. Dec 31) exists, it should be matched. 
                     # If not (maybe FX trades on Jan 1?), take closest previous.
                     pln_start_val = pln_hist['Close'].iloc[idx_loc-1]
                else:
                    pln_start_val = pln_hist['Close'].iloc[0]
                
                pln_end_val = pln_hist['Close'].iloc[-1]
                
                fx_ytd_change = (pln_end_val - pln_start_val) / pln_start_val
                ytd_return_pln = (1 + ytd_return) * (1 + fx_ytd_change) - 1
                
            else:
                ytd_return_pln = ytd_return
                
        except Exception as e:
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
            
        # Longs/Shorts Contribution 
        # Needs to align with the new base logic? 
        # Since we use ytd_rel_prices logic above for total portfolio, this loop for granular contribution
        # should ideally match.
        # Note: Above we calculate "ytd_longs_contrib" and "ytd_shorts_contrib" in the main loop.
        # The loop below was recalculating it differently. Let's just use the ones from the main loop!
        # But wait, the main loop calculates portfolio *weighted* contribution.
        # The variables `ytd_longs_contrib` were already accumulated there.
        # So we can remove the redundant loop below or update it?
        # The redundant loop calculates it slightly differently using product of returns.
        # Let's stick effectively to the main loop's result as it matches the "YTD Return" number exactly by definition.
        
        # DO NOTHING here, we already calculated ytd_longs_contrib in the loop above.
        
    else:
        ytd_return = 0.0
        benchmark_ytd = 0.0
        ytd_beta = 0.0
        ytd_sharpe = 0.0
        bench_ytd_sharpe = 0.0
        bench_hist_sharpe = 0.0
        ytd_return_pln = 0.0
        wig_ytd = 0.0
        msci_ytd = 0.0
        ytd_longs_contrib = 0.0
        ytd_shorts_contrib = 0.0
        ytd_max_drawdown = 0.0
        ytd_bench_max_drawdown = 0.0

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
            curr_year_start = pd.Timestamp(f"{datetime.now().year}-01-01")
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

    return {
        'Beta': portfolio_beta,
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
        'Benchmark_YTD': benchmark_ytd,
        'YTD_Beta': ytd_beta,
        'YTD_Sharpe': ytd_sharpe,
        'Benchmark_YTD_Sharpe': bench_ytd_sharpe,
        'Benchmark_Hist_Sharpe': bench_hist_sharpe,
        'YTD_Return_PLN': ytd_return_pln,
        'WIG_YTD': wig_ytd,
        'MSCI_YTD': msci_ytd,
        'YTD_Longs_Contrib': ytd_longs_contrib,
        'YTD_Shorts_Contrib': ytd_shorts_contrib,
        'YTD_Alpha': ytd_alpha,
        'YTD_Max_Drawdown': ytd_max_drawdown,
        'Benchmark_YTD_Max_Drawdown': ytd_bench_max_drawdown,
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
        'YTD_Benchmark_Stream': ytd_benchmark if 'ytd_benchmark' in locals() else None
    }

def stress_test_portfolio(metrics):
    print("--- 4. Running Stress Tests ---")
    if metrics is None: return {}
    
    beta = metrics['Beta']
    
    # Simple Beta-based Stress Testing
    scenarios = {
        'Market Crash (-10%)': -0.10,
        'Market Correction (-5%)': -0.05,
        'Market Rally (+5%)': 0.05,
        'Market Surge (+10%)': 0.10
    }
    
    results = {}
    for name, mkt_move in scenarios.items():
        # Estimated Portfolio Move = Beta * Market Move
        # (This is a linear approximation, assuming correlations hold 1.0)
        est_move = beta * mkt_move
        results[name] = est_move
        
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

def calculate_periodic_returns(data):
    print("--- 6. Calculating Periodic Returns (YTD, 1Y, 3Y, 5Y) ---")
    periods = {
        '1Y': 252,
        '3Y': 252 * 3,
        '5Y': 252 * 5
    }
    
    # YTD calculation: from Jan 1st of current year
    current_year = datetime.now().year
    ytd_start = f"{current_year}-01-01"
    
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
def generate_report(metrics, data):
    if metrics is None: return

    print("\n" + "="*50)
    print(f"      HEDGE FUND RISK REPORT ({datetime.now().strftime('%Y-%m-%d')})      ")
    print("="*50)
    
    # --- 0. PERIODIC RETURNS (Print First) ---
    periodic_rets = calculate_periodic_returns(data)
    
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