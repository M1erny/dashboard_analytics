import yfinance as yf
import pandas as pd
from datetime import datetime

# Mimic risk.py logic
current_year = datetime.now().year
ytd_calc_start = f"{current_year}-01-01"
print(f"Current Year: {current_year}")
print(f"YTD Start: {ytd_calc_start}")

try:
    print("Fetching USDPLN=X...")
    usdpln = yf.Ticker("USDPLN=X")
    start_date = pd.Timestamp(ytd_calc_start) - pd.Timedelta(days=10)
    print(f"Fetch Start Date: {start_date}")
    
    pln_hist = usdpln.history(start=start_date)
    
    if hasattr(pln_hist.index, 'tz'):
        pln_hist.index = pln_hist.index.tz_localize(None)
    
    print("\n--- History Data ---")
    print(pln_hist)
    
    if pln_hist.empty:
        print("ERROR: pln_hist IS EMPTY")
    else:
        print(f"Rows: {len(pln_hist)}")
        print(f"First Date: {pln_hist.index[0]}")
        print(f"Last Date: {pln_hist.index[-1]}")
        
        # Test logic
        # target_start_date would come from price_df logic, let's assume Dec 31, 2025
        target_dates = [
            pd.Timestamp(f"{current_year-1}-12-31"),
            pd.Timestamp(f"{current_year}-01-01"),
            pd.Timestamp(f"{current_year}-01-02")
        ]
        
        for t_date in target_dates:
            print(f"\nTesting lookup for: {t_date}")
            idx_loc = pln_hist.index.searchsorted(t_date)
            print(f"Searchsorted idx: {idx_loc}")
            
            if idx_loc < len(pln_hist) and pln_hist.index[idx_loc] == t_date:
                val = pln_hist['Close'].iloc[idx_loc]
                print(f"Found Match: {val}")
            elif idx_loc > 0:
                val = pln_hist['Close'].iloc[idx_loc-1]
                print(f"Fallback to previous: {val} (Date: {pln_hist.index[idx_loc-1]})")
            else:
                val = pln_hist['Close'].iloc[0]
                print(f"Fallback to first: {val}")

except Exception as e:
    print(f"EXCEPTION: {e}")
