import time
import risk

print("--- Starting Benchmark ---")
start_time = time.time()

print("1. Fetching Data...")
t0 = time.time()
raw_prices, fx_rates, volume_data = risk.fetch_data()
t1 = time.time()
print(f"Fetch completed in {t1-t0:.2f} seconds")

print("2. Normalizing...")
usd_prices = risk.normalize_to_base_currency(raw_prices, fx_rates)
t2 = time.time()
print(f"Normalize completed in {t2-t1:.2f} seconds")

print("3. Calculating Metrics...")
metrics = risk.calculate_risk_metrics(usd_prices, volume_data, fx_rates)
t3 = time.time()
print(f"Calculation completed in {t3-t2:.2f} seconds")

total_time = t3 - start_time
print(f"--- Total Time: {total_time:.2f} seconds ---")
