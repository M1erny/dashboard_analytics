import risk 
import pandas as pd
import numpy as np

print("--- Testing YTD Drawdown Logic ---")
try:
    # 1. Fetch & Normalize
    print("Fetching data...")
    prices, fx, volume = risk.fetch_data()
    usd_prices = risk.normalize_to_base_currency(prices, fx)
    
    # 2. Calculate
    print("Calculating Metrics...")
    metrics = risk.calculate_risk_metrics(usd_prices, volume)
    
    if metrics:
        print("\n--- YTD Results ---")
        print(f"YTD Return: {metrics.get('YTD_Return'):.2%}")
        print(f"YTD Max Drawdown (Portfolio): {metrics.get('YTD_Max_Drawdown'):.2%}")
        print(f"YTD Max Drawdown (Benchmark): {metrics.get('Benchmark_YTD_Max_Drawdown'):.2%}")
        
        ytd_mdd = metrics.get('YTD_Max_Drawdown')
        if ytd_mdd is not None and ytd_mdd <= 0:
             print("Status: SUCCESS (Values reasonable)")
        else:
             print(f"Status: WARNING (Positive or None MDD? {ytd_mdd})")
    else:
        print("Status: FAILURE (Metrics None)")

except Exception as e:
    print(f"EXCEPTION: {e}")
    import traceback
    traceback.print_exc()
