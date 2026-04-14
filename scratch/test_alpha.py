import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import json
import os

# Mock the environment or load actual data if possible
# Since I can't easily mock the whole DB, I'll just check the logic with some dummy data 
# or try to run a subset of risk.py functions if I can import them.

# Let's try to import the actual functions and test them
import sys
sys.path.append('backend')
import risk

def test_szymon_metrics():
    print("Testing Szymon Metrics Calculation...")
    # Load config
    with open('backend/portfolios/szymon.json', 'r') as f:
        config = json.load(f)
    
    tickers = list(config.keys())
    tickers.append('SPY') # Benchmark
    
    # Fetch data for Q2 2026
    start_date = "2026-03-25" # Buffer before April 1st
    end_date = "2026-04-14"
    
    print(f"Fetching data from {start_date} to {end_date} for {tickers}")
    data = yf.download(tickers, start=start_date, end=end_date)['Close']
    
    if data.empty:
        print("Data fetch failed. Maybe dates are in the future relative to the system clock?")
        print(f"Current System Time: {datetime.now()}")
        return

    # Filter to April 1st onwards
    april_data = data[data.index >= "2026-04-01"]
    print(f"Days of data in April: {len(april_data)}")
    
    # Run the calc
    # Note: calculate_risk_metrics takes (price_df, volume_df, fx_df, ..., portfolio_name)
    metrics = risk.calculate_risk_metrics(data, portfolio_name="szymon")
    
    if metrics:
        print("\n--- RESULTS ---")
        print(f"Period Label: {metrics.get('Period_Label')}")
        print(f"YTD (Q2) Return: {metrics.get('YTD_Return'):.4%}")
        print(f"Benchmark (SPY) YTD: {metrics.get('Benchmark_YTD'):.4%}")
        print(f"YTD Alpha (Raw): {metrics.get('YTD_Alpha_Raw'):.4%}")
        print(f"YTD Alpha (Ann): {metrics.get('YTD_Alpha'):.4%}")
        print(f"YTD Beta: {metrics.get('YTD_Beta'):.4f}")
        print(f"Expected Return (Ann): {metrics.get('YTD_Return') - metrics.get('YTD_Alpha'):.4%}") # Reverse engineer
        
        # Check components
        # ytd_expected_return = rf_rate_long + ytd_beta * (bench_ytd_ann_ret - rf_rate_long)
        # ytd_alpha = ytd_ann_ret - ytd_expected_return
    else:
        print("Metrics calc returned None")

if __name__ == "__main__":
    test_szymon_metrics()
