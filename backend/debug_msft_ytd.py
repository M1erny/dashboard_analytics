import yfinance as yf
import pandas as pd
from datetime import datetime

def debug_ytd():
    ticker = "MSFT"
    print(f"--- Debugging YTD for {ticker} ---")
    
    # Fetch data surrounding the year transition
    # Look back enough to cover Dec 2025
    start_date = "2025-12-01" 
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    print(f"Fetching data from {start_date} to {end_date}...")
    df = yf.download(ticker, start=start_date, auto_adjust=True)
    
    if isinstance(df.columns, pd.MultiIndex):
        try:
            close = df['Close'][ticker]
        except:
            close = df.xs('Close', axis=1, level=0, drop_level=True)
    else:
        close = df['Close']
        
    print("\nRecent Data Head:")
    print(close.head())
    print("\nRecent Data Tail:")
    print(close.tail())
    
    # Locate Dec 31, 2025 (or last trading day of 2025)
    # Since we are in 2026, previous year is 2025.
    curr_year = datetime.now().year
    prev_year = curr_year - 1
    
    start_of_year_ts = pd.Timestamp(f"{curr_year}-01-01")
    
    # Logic from risk.py
    idx_start = close.index.searchsorted(start_of_year_ts)
    
    val_start = None
    date_start = None
    
    if idx_start > 0:
        # risk.py logic: takes index-1
        val_start = close.iloc[idx_start - 1]
        date_start = close.index[idx_start - 1]
        print(f"\n[RISK.PY LOGIC]")
        print(f"Located Start Index: {idx_start} ({close.index[idx_start]})")
        print(f"Taking Index-1: {date_start}")
        print(f"Base Price (Prev Year Close): {val_start:.4f}")
    else:
        print("\n[RISK.PY LOGIC] Start index is 0! (Data starts too late?)")
        
    # ... existing logic ...
    
    val_current = close.iloc[-1]
    date_current = close.index[-1]
    print(f"Current Price ({date_current}): {val_current:.4f}")
    
    # CHECK LIVE PRICE via Ticker.history
    print("\n[LIVE CHECK]")
    live_hist = yf.Ticker(ticker).history(period="1d")
    if not live_hist.empty:
        live_price = live_hist['Close'].iloc[-1]
        live_date = live_hist.index[-1]
        print(f"Live Price ({live_date}): {live_price:.4f}")
        
        ytd_live = (live_price - val_start) / val_start
        print(f"Calculated YTD (LIVE): {ytd_live:.4%}")
    else:
        print("Could not fetch live data via history().")

    if val_start:
        ytd_perf = (val_current - val_start) / val_start
        print(f"Calculated YTD (Download): {ytd_perf:.4%}")
        # ... logic continues
        
        # Check Short Logic
        short_ytd = -1 * ytd_perf
        print(f"Short YTD (Simple Inverted): {short_ytd:.4%}")
        
        # Value-based Short logic (Contribution)
        # Entry=Start, Current=End. 
        # P&L = Entry - Current
        # Return = (Entry - Current) / Entry = 1 - (Current/Entry)
        short_return_contribution = (val_start - val_current) / val_start
        print(f"Short YTD (Contribution Logic): {short_return_contribution:.4%}")

if __name__ == "__main__":
    debug_ytd()
