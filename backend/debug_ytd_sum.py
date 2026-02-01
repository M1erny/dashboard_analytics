import sys
import os
import pandas as pd
import numpy as np

RISK_DIR = r"c:\Users\Tomek\.antigravity\alpha"
sys.path.append(RISK_DIR)

try:
    import risk
except ImportError as e:
    print(f"Error importing risk.py: {e}")
    sys.exit(1)

def debug_ytd_sum():
    # Force pandas to display more
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    
    out = []
    out.append("Fetching data...")
    stock_raw, fx_rates = risk.fetch_data()
    usd_prices = risk.normalize_to_base_currency(stock_raw, fx_rates)
    
    out.append("Calculating metrics...")
    metrics = risk.calculate_risk_metrics(usd_prices)
    
    ytd_return = metrics['YTD_Return']
    longs_contrib = metrics['YTD_Longs_Contrib']
    shorts_contrib = metrics['YTD_Shorts_Contrib']
    sum_contrib = longs_contrib + shorts_contrib
    
    out.append(f"\n--- YTD Summary ---")
    out.append(f"Portfolio YTD Return: {ytd_return:.6f} ({ytd_return:.4%})")
    out.append(f"Sum of Contribs (Risk.py): {sum_contrib:.6f} ({sum_contrib:.4%})")
    out.append(f"  Longs: {longs_contrib:.6f}")
    out.append(f"  Shorts: {shorts_contrib:.6f}")
    out.append(f"Difference: {ytd_return - sum_contrib:.6e}")
    
    
    out.append(f"\n--- Periodic Returns Check (Server Logic) ---")
    periodic_rets = risk.calculate_periodic_returns(usd_prices)
    
    manual_sum = 0
    out.append(f"{'Ticker':<10} | {'Weight':<8} | {'Dir':<6} | {'YTD':<10} | {'Contrib':<10}")
    
    for ticker, info in risk.PORTFOLIO_CONFIG.items():
        if ticker in periodic_rets.index:
            weight = info['weight']
            direction = 1 if info['type'] == 'Long' else -1
            
            ytd_val = periodic_rets.loc[ticker, 'YTD']
            
            if pd.isna(ytd_val):
                ytd_val = 0
                
            contrib = weight * direction * ytd_val
            manual_sum += contrib
            
            out.append(f"{ticker:<10} | {weight:<8} | {direction:<6} | {ytd_val:<10.4%} | {contrib:<10.4%}")
        else:
            out.append(f"{ticker:<10} | NOT FOUND IN PERIODIC RETS")
            
    out.append(f"\nManual Sum of Ticker Contributions: {manual_sum:.6f} ({manual_sum:.4%})")
    out.append(f"Difference vs Portfolio YTD: {ytd_return - manual_sum:.6e}")
    
    # Write to a clean text file
    with open("ytd_analysis.txt", "w") as f:
        f.write("\n".join(out))

if __name__ == "__main__":
    debug_ytd_sum()
