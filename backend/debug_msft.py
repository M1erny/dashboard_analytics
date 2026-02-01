import sys
import os
import pandas as pd
from datetime import datetime

# Add the directory containing risk.py to path
RISK_DIR = r"c:\Users\Tomek\.antigravity\alpha"
sys.path.append(RISK_DIR)

try:
    import risk
except ImportError as e:
    print(f"Error importing risk.py: {e}")
    sys.exit(1)

def verify_fix():
    output_lines = []
    output_lines.append("Fetching data...")
    stock_raw, fx_rates = risk.fetch_data()
    usd_prices = risk.normalize_to_base_currency(stock_raw, fx_rates)
    
    output_lines.append("\n--- Running risk.calculate_risk_metrics ---")
    metrics = risk.calculate_risk_metrics(usd_prices)
    
    if metrics:
        output_lines.append(f"Portfolio YTD Return: {metrics.get('YTD_Return'):.4%}")
        output_lines.append(f"Benchmark YTD: {metrics.get('Benchmark_YTD'):.4%}")
    else:
        output_lines.append("Metrics calculation failed.")

    output_lines.append("\n--- Running risk.calculate_periodic_returns ---")
    periodic = risk.calculate_periodic_returns(usd_prices)
    
    if 'MSFT' in periodic.index:
        msft_ytd = periodic.loc['MSFT', 'YTD']
        output_lines.append(f"MSFT YTD Return: {msft_ytd:.4%}")
    else:
        output_lines.append("MSFT not found in periodic returns.")
        
    # Check what the expected value calculation gives now
    # Previous Year Close for MSFT (approx Dec 31 2025)
    # We saw in previous debug: Dec 31 Close = 483.62
    # Current (Jan 29) = 433.5
    # Expected: (433.5 - 483.62) / 483.62 = -10.36%
    
    with open("verification_results.txt", "w") as f:
        f.write("\n".join(output_lines))

if __name__ == "__main__":
    verify_fix()
