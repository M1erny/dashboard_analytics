import sys
import pandas as pd
import numpy as np
from risk import fetch_data, normalize_to_base_currency, PORTFOLIO_CONFIG

print("Fetching data...")
prices, fx, vol = fetch_data()
norm = normalize_to_base_currency(prices, fx)

rets = norm.pct_change().dropna(how='all')
bench = rets['SPY']

port = pd.Series(0.0, index=rets.index)
for ticker, info in PORTFOLIO_CONFIG.items():
    if ticker in rets.columns:
        weight = info['weight']
        direction = 1 if info['type'] == 'Long' else -1
        port += rets[ticker].fillna(0.0) * weight * direction

valid_mask = ~(np.isnan(port) | np.isnan(bench))
b = bench[valid_mask]
p = port[valid_mask]

# Calculate Historical Beta exactly as the app does
cov = np.cov(p, b)[0][1]
var = np.var(b, ddof=1)
beta = cov / var

df = pd.DataFrame({'SPY': b, 'Port': p})
df['Linear_Expected'] = df['SPY'] * beta
df['Miss'] = df['Port'] - df['Linear_Expected']

print(f"\nHistorical Beta: {beta:.4f}")

print("\n--- TOP 3 WORST SPY DAYS (Crashes) ---")
worst = df.sort_values('SPY').head(3)
for d, row in worst.iterrows():
    date_str = pd.to_datetime(d).strftime('%Y-%m-%d')
    print(f"{date_str}: SPY={row['SPY']:.2%}, Port={row['Port']:.2%}")
    print(f"  -> Linear Expected: {row['Linear_Expected']:.2%} | Actual Miss: {row['Miss']:.2%}")

print("\n--- TOP 3 BEST SPY DAYS (Surges) ---")
best = df.sort_values('SPY', ascending=False).head(3)
for d, row in best.iterrows():
    date_str = pd.to_datetime(d).strftime('%Y-%m-%d')
    print(f"{date_str}: SPY={row['SPY']:.2%}, Port={row['Port']:.2%}")
    print(f"  -> Linear Expected: {row['Linear_Expected']:.2%} | Actual Miss: {row['Miss']:.2%}")

# Look for specific days where shorts rallied hard or AFRM crashed
print("\n--- TOP 3 DAYS WHERE PORTFOLIO MISSED THE MOST ON DOWNSIDE ---")
# Days where SPY was down deeply but Port was down EVEN WORSE than expected
crush = df[df['SPY'] < -0.02].sort_values('Miss').head(3)
for d, row in crush.iterrows():
    date_str = pd.to_datetime(d).strftime('%Y-%m-%d')
    print(f"{date_str}: SPY={row['SPY']:.2%}, Port={row['Port']:.2%}")
    print(f"  -> Expected: {row['Linear_Expected']:.2%} | Miss: {row['Miss']:.2%}")

