"""Verify Jensen's Alpha YTD calculation with actual portfolio data."""
import sys, os
sys.stdout.reconfigure(line_buffering=True)

import numpy as np
import pandas as pd
from datetime import datetime

import risk

print("Fetching data...")
raw_prices, fx_rates, volume_data = risk.fetch_data()
usd_prices = risk.normalize_to_base_currency(raw_prices, fx_rates)

# --- Reproduce YTD calculations (same logic as risk.py) ---
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

# YTD Return
ytd_return = portfolio_val_series.iloc[-1] - 1
benchmark_ytd = (1 + ytd_benchmark).prod() - 1

# Derive daily returns
ytd_portfolio_daily_ret = portfolio_val_series.pct_change().dropna()
ytd_benchmark_aligned = ytd_benchmark.reindex(ytd_portfolio_daily_ret.index).dropna()
ytd_portfolio_daily_ret = ytd_portfolio_daily_ret.loc[ytd_benchmark_aligned.index]

N = len(ytd_benchmark_aligned)
ANNUAL_FACTOR = 252

# Beta
cov_val = np.cov(ytd_portfolio_daily_ret, ytd_benchmark_aligned)[0][1]
var_sample = np.var(ytd_benchmark_aligned, ddof=1)
ytd_beta = cov_val / var_sample

# Risk-free rate
import yfinance as yf
tnx = yf.Ticker("^TNX")
tnx_hist = tnx.history(period="5d")
rf_rate = tnx_hist['Close'].iloc[-1] / 100.0 if not tnx_hist.empty else 0.04

# YTD RF scaled
ytd_trading_days = len(ytd_portfolio_daily_ret)
ytd_rf_rate = rf_rate * (ytd_trading_days / ANNUAL_FACTOR)

# Annualized metrics
ytd_ann_ret = np.mean(ytd_portfolio_daily_ret) * ANNUAL_FACTOR
bench_ytd_ann_ret = np.mean(ytd_benchmark) * ANNUAL_FACTOR

# === RAW YTD ALPHA (what the UI shows as "Raw YTD") ===
# α = Rp - [Rf + β × (Rm - Rf)]
ytd_alpha_raw = ytd_return - (ytd_rf_rate + ytd_beta * (benchmark_ytd - ytd_rf_rate))

# === ANNUALIZED YTD ALPHA ===
ytd_expected_return = rf_rate + ytd_beta * (bench_ytd_ann_ret - rf_rate)
ytd_alpha_annualized = ytd_ann_ret - ytd_expected_return

# Write results
with open("alpha_results.txt", "w") as f:
    f.write("JENSEN'S ALPHA VERIFICATION\n")
    f.write("===========================\n\n")
    f.write("--- INPUT VALUES ---\n")
    f.write(f"  Portfolio YTD Return (Rp):   {ytd_return:+.4%}\n")
    f.write(f"  Benchmark YTD Return (Rm):   {benchmark_ytd:+.4%}\n")
    f.write(f"  YTD Beta:                    {ytd_beta:.4f}\n")
    f.write(f"  Annual Risk-Free Rate:       {rf_rate:.4%}\n")
    f.write(f"  YTD Risk-Free (scaled):      {ytd_rf_rate:.4%}\n")
    f.write(f"  Trading Days YTD:            {ytd_trading_days}\n")
    f.write(f"\n")
    f.write("--- RAW YTD ALPHA (displayed as 'Raw YTD') ---\n")
    f.write(f"  Formula: alpha = Rp - [Rf_ytd + beta * (Rm - Rf_ytd)]\n")
    f.write(f"  Step 1: Expected = Rf_ytd + beta * (Rm - Rf_ytd)\n")
    f.write(f"         = {ytd_rf_rate:.4%} + {ytd_beta:.4f} * ({benchmark_ytd:.4%} - {ytd_rf_rate:.4%})\n")
    expected_raw = ytd_rf_rate + ytd_beta * (benchmark_ytd - ytd_rf_rate)
    f.write(f"         = {ytd_rf_rate:.4%} + {ytd_beta:.4f} * {benchmark_ytd - ytd_rf_rate:.4%}\n")
    f.write(f"         = {expected_raw:.4%}\n")
    f.write(f"  Step 2: alpha = Rp - Expected\n")
    f.write(f"         = {ytd_return:.4%} - ({expected_raw:.4%})\n")
    f.write(f"         = {ytd_alpha_raw:.4%}\n")
    f.write(f"\n")
    f.write("--- ANNUALIZED ALPHA ---\n")
    f.write(f"  Annualized Portfolio Ret:    {ytd_ann_ret:+.4%}\n")
    f.write(f"  Annualized Benchmark Ret:    {bench_ytd_ann_ret:+.4%}\n")
    f.write(f"  Expected = Rf + beta * (Rm_ann - Rf)\n")
    f.write(f"           = {rf_rate:.4%} + {ytd_beta:.4f} * ({bench_ytd_ann_ret:.4%} - {rf_rate:.4%})\n")
    f.write(f"           = {ytd_expected_return:.4%}\n")
    f.write(f"  Alpha_ann = {ytd_ann_ret:.4%} - ({ytd_expected_return:.4%}) = {ytd_alpha_annualized:.4%}\n")
    f.write(f"\n")
    f.write("--- INTUITION CHECK ---\n")
    f.write(f"  Simple excess = Rp - Rm = {ytd_return:.4%} - ({benchmark_ytd:.4%}) = {ytd_return - benchmark_ytd:.4%}\n")
    f.write(f"  But Jensen's alpha is HIGHER because beta > 1:\n")
    f.write(f"    With beta={ytd_beta:.2f}, portfolio was EXPECTED to lose\n")
    f.write(f"    MORE than the market ({expected_raw:.4%} vs {benchmark_ytd:.4%}).\n")
    f.write(f"    Instead it GAINED {ytd_return:.4%}.\n")
    f.write(f"    The outperformance vs expectation = {ytd_alpha_raw:.4%}\n")

print("Results written to alpha_results.txt")
