"""Compare YTD 2026 beta: old formula (population var) vs fixed formula (sample var)."""
import sys, os
sys.stdout.reconfigure(line_buffering=True)
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

import numpy as np
import pandas as pd
from datetime import datetime

import risk

print("Fetching data...")
raw_prices, fx_rates, volume_data = risk.fetch_data()
usd_prices = risk.normalize_to_base_currency(raw_prices, fx_rates)

# --- Reproduce YTD portfolio value series (same logic as risk.py) ---
price_df = usd_prices.copy()
if hasattr(price_df.index, 'tz') and price_df.index.tz is not None:
    price_df.index = price_df.index.tz_localize(None)

returns_df = price_df.pct_change().dropna(how='all')
benchmark_ret = returns_df[risk.BENCHMARK]
if hasattr(benchmark_ret.index, 'tz') and benchmark_ret.index.tz is not None:
    benchmark_ret.index = benchmark_ret.index.tz_localize(None)

current_year = datetime.now().year
ytd_calc_start = f"{current_year}-01-01"
ytd_benchmark = benchmark_ret[benchmark_ret.index >= ytd_calc_start]

price_df_filled = price_df.ffill()
start_idx_loc = price_df.index.searchsorted(pd.Timestamp(ytd_calc_start))
ytd_prices = price_df_filled.iloc[start_idx_loc-1:] if start_idx_loc > 0 else price_df_filled

ytd_prices_filled = ytd_prices.ffill()
ytd_rel_prices = ytd_prices_filled / ytd_prices_filled.iloc[0]

active_tickers = [t for t in risk.PORTFOLIO_CONFIG.keys() if t in returns_df.columns]

portfolio_val_series = pd.Series(0.0, index=ytd_rel_prices.index)
for ticker in active_tickers:
    info = risk.PORTFOLIO_CONFIG[ticker]
    weight = info['weight']
    direction = 1 if info['type'] == 'Long' else -1
    if ticker in ytd_rel_prices.columns:
        asset_cum_ret = ytd_rel_prices[ticker] - 1
        position_contrib = weight * direction * asset_cum_ret
        portfolio_val_series += position_contrib.fillna(0)

portfolio_val_series += 1.0

# Derive daily returns
ytd_portfolio_daily_ret = portfolio_val_series.pct_change().dropna()
ytd_benchmark_aligned = ytd_benchmark.reindex(ytd_portfolio_daily_ret.index).dropna()
ytd_portfolio_daily_ret = ytd_portfolio_daily_ret.loc[ytd_benchmark_aligned.index]

N = len(ytd_benchmark_aligned)

# --- Calculate both betas ---
cov_val = np.cov(ytd_portfolio_daily_ret, ytd_benchmark_aligned)[0][1]
var_population = np.var(ytd_benchmark_aligned)          # ddof=0 (OLD)
var_sample = np.var(ytd_benchmark_aligned, ddof=1)      # ddof=1 (FIXED)

beta_old = cov_val / var_population
beta_fixed = cov_val / var_sample

# OLS ground truth
beta_ols = np.polyfit(ytd_benchmark_aligned, ytd_portfolio_daily_ret, 1)[0]

# Write results to file
with open("beta_results.txt", "w") as f:
    f.write(f"YTD 2026 BETA COMPARISON\n")
    f.write(f"========================\n")
    f.write(f"Trading days (N):          {N}\n")
    f.write(f"Inflation factor N/(N-1):  {N/(N-1):.4f}  ({(N/(N-1)-1)*100:.2f}%)\n")
    f.write(f"\n")
    f.write(f"Old beta (np.var pop):      {beta_old:.4f}\n")
    f.write(f"Fixed beta (np.var ddof=1): {beta_fixed:.4f}\n")
    f.write(f"OLS beta (ground truth):    {beta_ols:.4f}\n")
    f.write(f"\n")
    f.write(f"Difference (old - fixed):   {beta_old - beta_fixed:+.4f}\n")
    f.write(f"Matches OLS? Fixed: {np.isclose(beta_fixed, beta_ols, atol=1e-10)}  Old: {np.isclose(beta_old, beta_ols, atol=1e-10)}\n")

print("Results written to beta_results.txt")
