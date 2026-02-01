import risk 
import pandas as pd
import numpy as np

print("--- Testing Volume Logic ---")
try:
    # 1. Fetch
    print("Fetching data...")
    prices, fx, volume = risk.fetch_data()
    print(f"Prices Shape: {prices.shape}")
    print(f"Volume Shape: {volume.shape}")
    
    # 2. Normalize
    print("Normalizing...")
    usd_prices = risk.normalize_to_base_currency(prices, fx)
    
    # 3. Calculate w/ Volume
    print("Calculating Metrics...")
    metrics = risk.calculate_risk_metrics(usd_prices, volume)
    
    if metrics:
        vw_corr = metrics.get('Volume_Weighted_Correlation')
        if vw_corr is not None and not vw_corr.empty:
            print("\n--- Volume Weighted Correlation (Snippet) ---")
            print(vw_corr.iloc[:3, :3]) # Show top 3x3
            print(f"\nShape: {vw_corr.shape}")
            print("Status: SUCCESS")
        else:
             print("Status: FAILURE (Matrix missing or empty)")
    else:
        print("Status: FAILURE (Metrics None)")

except Exception as e:
    print(f"EXCEPTION: {e}")
    import traceback
    traceback.print_exc()
