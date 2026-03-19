import risk
import pandas as pd
import numpy as np

raw, fx, vol = risk.fetch_data()
usd = risk.normalize_to_base_currency(raw, fx)
pret = risk.calculate_periodic_returns(usd)

config_tickers = list(risk.PORTFOLIO_CONFIG.keys())
missing = [t for t in config_tickers if t not in pret.index]

print("\n--- MISSING TICKERS ---")
print(missing)

for t in missing:
    print(f"\nAnalyzing {t}:")
    if t not in raw.columns:
        print("  Not in raw columns!")
        continue
    r_series = raw[t].dropna()
    print(f"  Raw data: {len(r_series)} rows. \n  Last price: {r_series.iloc[-1] if not r_series.empty else 'EMPTY'}")
    
    if t not in usd.columns:
        print("  Not in usd columns!")
        continue
    u_series = usd[t].dropna()
    print(f"  USD data: {len(u_series)} rows." )
    
    currency = risk.PORTFOLIO_CONFIG[t]['currency']
    fx_ticker = f"{currency}USD=X" if currency != "USD" else "USD"
    if currency != "USD":
        if fx_ticker in fx.columns:
           fx_ser = fx[fx_ticker].dropna()
           print(f"  FX {fx_ticker} data: {len(fx_ser)} rows.")
        else:
           print(f"  FX {fx_ticker} missing from fx.columns!")
