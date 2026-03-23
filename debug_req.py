import sys
sys.stdout.reconfigure(line_buffering=True)
import requests
import json
try:
    res = requests.get('http://localhost:8000/api/metrics?force=true')
    d = res.json().get('periodicReturns', [])
    for x in d[:5]:
        print(f"ticker: {x['ticker']}, weight: {x['weight']}, r7d: {x['r7d']}, r7dC: {x['r7dContribution']}, r1d: {x['r1d']}, r1dC: {x['r1dContribution']}")
except Exception as e:
    print("Error:", e)
