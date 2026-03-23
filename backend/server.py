import sys
import os

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import numpy as np
import time
from datetime import datetime

# Import risk.py (Now local)
try:
    import risk
except ImportError as e:
    print(f"Error importing risk.py: {e}")
    risk = None

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Response cache (mapped by costTier, 5 minute TTL)
_cache = {}
CACHE_TTL = 300  # seconds

@app.get("/api/status")
async def get_status():
    if risk:
        return {"state": "ready", "message": "Ready"}
    else:
        return {"state": "error", "message": "Risk module failed to load"}

@app.get("/api/metrics")
async def get_metrics(force: bool = False, costTier: str = 'retail'):
    global _cache
    
    if not risk:
        return {"error": "risk.py not found or failed to import"}
        
    if costTier not in _cache:
        _cache[costTier] = {"data": None, "timestamp": 0}
        
    tier_cache = _cache[costTier]
    
    # Return cached response if fresh (unless force=True)
    if not force and tier_cache["data"] and (time.time() - tier_cache["timestamp"]) < CACHE_TTL:
        print(f"Returning cached response for {costTier} (age: {int(time.time() - tier_cache['timestamp'])}s)")
        return tier_cache["data"]

    try:
        print(f"Fetching fresh data for tier: {costTier}...")
        
        # Determine rates based on costTier
        if costTier == 'institutional':
            margin_rate = 0.055
            borrow_fee = 0.010
        elif costTier == 'none':
            margin_rate = 0.0
            borrow_fee = 0.0
        else: # retail
            margin_rate = 0.120
            borrow_fee = 0.025
            
        # 1. Fetch and Calculate Base Metrics
        raw_prices, fx_rates, volume_data = risk.fetch_data()
        usd_prices = risk.normalize_to_base_currency(raw_prices, fx_rates)
        metrics = risk.calculate_risk_metrics(
            usd_prices, 
            volume_data, 
            fx_rates,
            margin_rate=margin_rate,
            borrow_fee=borrow_fee
        )
        
        if metrics is None:
             print("Error: Metrics calculation returned None (insufficient data).")
             # Return a valid structure with nulls/zeros to allow frontend to render empty state
             # rather than crashing with 500
             return {
                "error": "Insufficient data to calculate metrics. (Likely Yahoo Finance rate limit or connection issue).",
                "vitals": { k: 0 for k in ["beta", "annualReturn", "annualVol", "sharpe", "sortino", "maxDrawdown", "cvar95", "rolling1mVol"] }, # Partial fallback
                "riskAttribution": [],
                "stressTests": [],
                "periodicReturns": [],
                "history": [],
                "leverage": {}
             }

        # 2. Run Advanced Models
        stress_results = risk.stress_test_portfolio(metrics)
            
        periodic_rets = risk.calculate_periodic_returns(usd_prices)

        # 3. Format Response
        import math
        def to_float(val):
            if val is None: return None
            try:
                f = float(val)
                # Return None for NaN/Inf to avoid JSON serialization errors
                if math.isnan(f) or math.isinf(f):
                    return None
                return f
            except:
                return None

        # 3. Format Response
        response = {
            "vitals": {
                "beta": to_float(metrics['Beta']),
                "annualReturn": to_float(metrics['Annual_Return']),
                "annualVol": to_float(metrics['Annual_Vol']),
                "sharpe": to_float(metrics['Sharpe']),
                "sortino": to_float(metrics['Sortino']),
                "maxDrawdown": to_float(metrics['Max_Drawdown']),
                "rolling1mVol": to_float(metrics.get('Rolling_1M_Vol')),
                "rolling1mVolBenchmark": to_float(metrics.get('Benchmark_Rolling_1M_Vol')),
                "cvar95": to_float(metrics['CVaR_95']),
                "jensensAlpha": to_float(metrics.get('Jensens_Alpha')),
                "periodInfo": metrics.get('Period_Info'),
                
                # New YTD Fields
                "ytdReturn": to_float(metrics.get('YTD_Return')),
                "ytdAlpha": to_float(metrics.get('YTD_Alpha')),
                "ytdAlphaRaw": to_float(metrics.get('YTD_Alpha_Raw')),
                "benchmarkYtd": to_float(metrics.get('Benchmark_YTD')),
                "ytdBeta": to_float(metrics.get('YTD_Beta')),
                "ytdMaxDrawdown": to_float(metrics.get('YTD_Max_Drawdown')),
                "benchmarkYtdMaxDrawdown": to_float(metrics.get('Benchmark_YTD_Max_Drawdown')),
                "ytdReturnGross": to_float(metrics.get('YTD_Return_Gross')),
                "ytdFinancingCost": to_float(metrics.get('YTD_Financing_Cost')),
                "annualFinancingCost": to_float(metrics.get('Annual_Financing_Cost')),
                
                # Standardized Sharpe Metrics
                "ytdSharpe": to_float(metrics.get('YTD_Sharpe')),           # Previously riskEfficiencyVol
                "benchmarkYtdSharpe": to_float(metrics.get('Benchmark_YTD_Sharpe')), 
                "benchmarkHistSharpe": to_float(metrics.get('Benchmark_Hist_Sharpe')), # For Hist Avg comparison
                "ytdReturnPln": to_float(metrics.get('YTD_Return_PLN')),
                "wigYtd": to_float(metrics.get('WIG_YTD')),
                "msciYtd": to_float(metrics.get('MSCI_YTD')),
                "ytdLongsContrib": to_float(metrics.get('YTD_Longs_Contrib')),
                "ytdShortsContrib": to_float(metrics.get('YTD_Shorts_Contrib')),
                "fxWatchlist": metrics.get('Fx_Watchlist', {}),
                "currencyExposure": {}, # Will be populated below
            },
            "leverage": metrics['Leverage_Stats'],
            "talebMetrics": metrics.get('Taleb_Metrics'),
            "riskAttribution": [],
            "stressTests": [],
            "periodicReturns": [],
            "history": []
        }

        # Format Risk Attribution
        for ticker, stats in metrics['Risk_Attribution'].items():
            response["riskAttribution"].append({
                "ticker": ticker,
                "weight": stats['Weight'],
                "pctRisk": stats['Pct_Risk'],
                "mctr": stats['MCTR']
            })
        response["riskAttribution"].sort(key=lambda x: x["pctRisk"], reverse=True)

        # Format Stress Tests
        for scenario, impact in stress_results.items():
            response["stressTests"].append({
                "scenario": scenario,
                "impact": impact
            })
        
        # Format Volume Weighted Correlation Matrix
        vw_corr = metrics.get('Volume_Weighted_Correlation')
        vw_corr_data = { "tickers": [], "matrix": [] }
        if vw_corr is not None and not vw_corr.empty:
            try:
                vw_corr_data["tickers"] = vw_corr.columns.tolist()
                # Handle NaN/Inf in matrix: replace with None
                mat = vw_corr.values
                # We need to iterate or use a masked replacement because simple tolist() keeps NaNs which are invalid JSON
                clean_mat = []
                for row in mat:
                    clean_row = [to_float(x) for x in row]
                    clean_mat.append(clean_row)
                vw_corr_data["matrix"] = clean_mat
            except Exception as e:
                print(f"Error formatting correlation matrix: {e}")
                
        response["volumeWeightedCorrelation"] = vw_corr_data

        # Get portfolio config for weights and direction (Used for Currency & Periodic Returns)
        portfolio_config = getattr(risk, 'PORTFOLIO_CONFIG', {})

        # Calculate Currency Exposure using portfolio_config
        # Share of Gross Exposure
        curr_exposure = {}
        total_gross = 0
        if portfolio_config:
            for ticker, info in portfolio_config.items():
                curr = info.get('currency', 'USD')
                weight = info.get('weight', 0)
                curr_exposure[curr] = curr_exposure.get(curr, 0) + weight
                total_gross += weight
        
        # Normalize to percentages of entire portfolio gross exposure
        if total_gross > 0:
            for curr in curr_exposure:
                curr_exposure[curr] = curr_exposure[curr] / total_gross
        
        response["vitals"]["currencyExposure"] = curr_exposure

        # Calculate Country Allocation for World Map
        country_allocation = {}
        if portfolio_config:
            for ticker, info in portfolio_config.items():
                country = info.get('country', 'USA')  # Default to USA if not specified
                weight = info.get('weight', 0)
                pos_type = info.get('type', 'Long')
                direction = 1 if pos_type == 'Long' else -1
                
                # Get YTD Return for contribution
                ytd_ret = 0
                if ticker in periodic_rets.index:
                    val = periodic_rets.loc[ticker, 'YTD']
                    if not pd.isna(val):
                        ytd_ret = val

                contribution = weight * ytd_ret * direction

                if country not in country_allocation:
                    country_allocation[country] = {'long': 0, 'short': 0, 'contribution': 0, 'tickers': []}
                
                if pos_type == 'Long':
                    country_allocation[country]['long'] += weight
                else:
                    country_allocation[country]['short'] += weight
                
                country_allocation[country]['contribution'] += contribution
                
                country_allocation[country]['tickers'].append({
                    'ticker': ticker,
                    'weight': weight,
                    'type': pos_type,
                    'contribution': contribution
                })
        
        response["countryAllocation"] = country_allocation

        # Format Periodic Returns
        # Periodic returns is a DataFrame: index=ticker, columns=['YTD', '1Y', '3Y', '5Y']
        # We need to add 1M returns and YTD contribution
        portfolio_ytd = to_float(metrics.get('YTD_Return')) or 0.0
        
        for ticker, row in periodic_rets.iterrows():
            # Get portfolio info for this ticker
            ticker_config = portfolio_config.get(ticker, {})
            weight = ticker_config.get('weight', 0) if ticker_config else 0
            direction = ticker_config.get('type', None)  # 'Long' or 'Short'
            
            # Calculate YTD contribution: weight * ytd_return * direction
            ytd_ret = row['YTD'] if 'YTD' in row and not pd.isna(row['YTD']) else 0
            dir_multiplier = 1 if direction == 'Long' else (-1 if direction == 'Short' else 0)
            ytd_contribution = weight * ytd_ret * dir_multiplier if weight and ytd_ret else None
            
            # Calculate current drifted weight
            # W_current = W_initial * (1 + R_ytd_asset) / (1 + R_ytd_portfolio)
            current_weight = float(weight * (1 + ytd_ret) / (1 + portfolio_ytd)) if weight else None
            
            # Calculate Returns and Contributions
            r1d = None
            r1m = None
            r7d = None
            last_price = None
            volatility = None
            currency = ticker_config.get('currency', 'USD') if ticker_config else 'USD'
            sector = ticker_config.get('sector', 'Unknown') if ticker_config else 'Unknown'
            
            # Get last price from raw_prices (original currency)
            if ticker in raw_prices.columns:
                raw_series = raw_prices[ticker].dropna()
                if len(raw_series) > 0:
                    last_price = float(raw_series.iloc[-1])
            
            # Volume indicator: 7d avg vs YTD avg
            vol_7d_avg = None
            vol_ytd_avg = None
            volume_indicator = None  # ratio: >1 means higher recent volume
            if volume_data is not None and ticker in volume_data.columns:
                vol_series = volume_data[ticker].dropna()
                if len(vol_series) > 7:
                    vol_7d_avg = float(vol_series.iloc[-7:].mean())
                    # YTD volume average
                    ytd_start = pd.Timestamp(datetime.now().year, 1, 1)
                    ytd_vol = vol_series[vol_series.index >= ytd_start]
                    if len(ytd_vol) > 0:
                        vol_ytd_avg = float(ytd_vol.mean())
                        if vol_ytd_avg > 0:
                            volume_indicator = vol_7d_avg / vol_ytd_avg

            if ticker in usd_prices.columns:
                series = usd_prices[ticker].dropna()
                
                # 1D return
                if len(series) > 1:
                    current = series.iloc[-1]
                    past_1d = series.iloc[-2]
                    r1d = (current - past_1d) / past_1d if past_1d != 0 else None

                # 7D return
                if len(series) > 5:  # ~1 week of trading days
                    current = series.iloc[-1]
                    past_7d = series.iloc[-6]
                    r7d = (current - past_7d) / past_7d if past_7d != 0 else None
                
                # 1M return
                if len(series) > 21:  # ~1 month of trading days
                    current = series.iloc[-1]
                    past = series.iloc[-22]
                    r1m = (current - past) / past if past != 0 else None
                
                # Annualized volatility (std dev of daily returns * sqrt(252))
                if len(series) > 20:
                    daily_returns = series.pct_change().dropna()
                    if len(daily_returns) > 0:
                        volatility = float(daily_returns.std() * np.sqrt(252))
            
            r1d_contribution = weight * r1d * dir_multiplier if weight and r1d is not None else None
            r7d_contribution = weight * r7d * dir_multiplier if weight and r7d is not None else None

            item = {
                "ticker": ticker,
                "sector": sector,
                "ytd": row['YTD'] if 'YTD' in row and not pd.isna(row['YTD']) else None,
                "r1d": to_float(r1d),
                "r7d": to_float(r7d),
                "r1m": to_float(r1m),
                "r1y": row['1Y'] if not pd.isna(row['1Y']) else None,
                "ytdContribution": to_float(ytd_contribution),
                "r1dContribution": to_float(r1d_contribution),
                "r7dContribution": to_float(r7d_contribution),
                "weight": to_float(weight) if weight else None,
                "currentWeight": to_float(current_weight),
                "direction": direction,
                "lastPrice": last_price,
                "currency": currency,
                "volatility": volatility,
                "volumeIndicator": to_float(volume_indicator),
            }
            response["periodicReturns"].append(item)
            
        # Format History (Cumulative 1000 base)
        portfolio_cum = (1 + metrics['Returns_Stream']).cumprod() * 1000
        benchmark_cum = (1 + metrics['Benchmark_Stream']).cumprod() * 1000
        drawdown_stream = metrics['Drawdown_Stream']
        
        # Align indexes
        common_idx = portfolio_cum.index
        
        # We'll limit history to optimize payload if needed, but for now send full
        for date in common_idx:
            date_str = date.strftime('%Y-%m-%d')
            response["history"].append({
                "date": date_str,
                "portfolio": to_float(portfolio_cum.loc[date]),
                "benchmark": to_float(benchmark_cum.loc[date]),
                "drawdown": to_float(drawdown_stream.loc[date])
            })

        # Format YTD History (Base 100k)
        response["ytdHistory"] = []
        if metrics.get('YTD_Stream') is not None:
            ytd_port = metrics['YTD_Stream']
            # Reconstruct YTD Benchmark Value Series (Start=1.0)
            ytd_bench_ret = metrics.get('YTD_Benchmark_Stream')
            
            if ytd_port is not None and not ytd_port.empty:
                 # Benchmark might be returns series, need convert to price index starting 1.0
                if ytd_bench_ret is not None and not ytd_bench_ret.empty:
                    ytd_bench_idx = (1 + ytd_bench_ret).cumprod()
                    # Align start to 1.0 (it starts at 1+r, so we need to prepend 1.0 or just rebase)
                    # Easier: ytd_bench_idx / ytd_bench_idx.iloc[0] * (1 + first_ret)? 
                    # Actually standard way: Price_t = Price_{t-1} * (1+r_t). Start at 100k.
                    # ytd_bench_ret is daily returns.
                    ytd_bench_vals = (1 + ytd_bench_ret).cumprod()
                    # Prepend starting value 1.0 if possible, or just normalize
                    # Simplest: assume first return is from Day 1. Day 0 is 100k.
                    # We will just plot the available series scaled to 100k.
                    pass
                
                # Align dates
                for date in ytd_port.index:
                    date_str = date.strftime('%Y-%m-%d')
                    
                    port_val = ytd_port.loc[date] * 100000
                    
                    bench_val = None
                    if ytd_bench_ret is not None and date in ytd_bench_ret.index:
                         # This is approximate as we need full series for accurate index
                         # Let's do it properly outside loop
                         pass
                    
                    response["ytdHistory"].append({
                        "date": date_str,
                        "portfolio": to_float(port_val),
                        "benchmark": None # calculated below
                    })

                # Proper Benchmark Index Calculation
                if ytd_bench_ret is not None and not ytd_bench_ret.empty:
                    # Align to portfolio dates
                    aligned_bench = ytd_bench_ret.reindex(ytd_port.index).fillna(0)
                    bench_curve = (1 + aligned_bench).cumprod() * 100000
                    
                    for i, item in enumerate(response["ytdHistory"]):
                        date = item["date"]
                        # Map back
                        if i < len(bench_curve):
                             item["benchmark"] = to_float(bench_curve.iloc[i])

        # Sanitize stress tests
        for st in response["stressTests"]:
            st["impact"] = to_float(st["impact"])
        
        # Sanitize risk attribution
        for ra in response["riskAttribution"]:
            ra["weight"] = to_float(ra["weight"])
            ra["pctRisk"] = to_float(ra["pctRisk"])
            ra["mctr"] = to_float(ra["mctr"])

        # Store in cache
        tier_cache["data"] = response
        tier_cache["timestamp"] = time.time()
        print(f"Response cached at {tier_cache['timestamp']}")

        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

# ==========================================
# Portfolio Details API (lightweight, no market data fetch)
# ==========================================

@app.get("/api/portfolio")
async def get_portfolio():
    """Return the full portfolio composition from PORTFOLIO_CONFIG."""
    if not risk:
        return {"error": "Risk module not loaded"}

    portfolio_config = getattr(risk, 'PORTFOLIO_CONFIG', {})
    benchmark = getattr(risk, 'BENCHMARK', 'SPY')

    positions = []
    long_exposure = 0.0
    short_exposure = 0.0

    for ticker, info in portfolio_config.items():
        positions.append({
            "ticker": ticker,
            "weight": info.get('weight', 0),
            "type": info.get('type', 'Long'),
            "currency": info.get('currency', 'USD'),
            "country": info.get('country', 'USA'),
            "sector": info.get('sector', 'Unknown'),
        })
        if info.get('type') == 'Long':
            long_exposure += info.get('weight', 0)
        else:
            short_exposure += info.get('weight', 0)

    return {
        "positions": positions,
        "leverage": {
            "longExposure": round(long_exposure, 4),
            "shortExposure": round(short_exposure, 4),
            "grossExposure": round(long_exposure + short_exposure, 4),
            "netExposure": round(long_exposure - short_exposure, 4),
        },
        "benchmark": benchmark,
        "positionCount": len(positions),
    }


@app.get("/api/portfolio/allocation")
async def get_portfolio_allocation():
    """Return portfolio allocation breakdowns by sector, country, currency, and direction."""
    if not risk:
        return {"error": "Risk module not loaded"}

    portfolio_config = getattr(risk, 'PORTFOLIO_CONFIG', {})

    by_sector = {}
    by_country = {}
    by_currency = {}
    by_direction = {"Long": 0.0, "Short": 0.0}

    for ticker, info in portfolio_config.items():
        weight = info.get('weight', 0)
        sector = info.get('sector', 'Unknown')
        country = info.get('country', 'USA')
        currency = info.get('currency', 'USD')
        direction = info.get('type', 'Long')

        by_sector[sector] = round(by_sector.get(sector, 0) + weight, 4)
        by_country[country] = round(by_country.get(country, 0) + weight, 4)
        by_currency[currency] = round(by_currency.get(currency, 0) + weight, 4)
        by_direction[direction] = round(by_direction.get(direction, 0) + weight, 4)

    return {
        "bySector": dict(sorted(by_sector.items(), key=lambda x: x[1], reverse=True)),
        "byCountry": dict(sorted(by_country.items(), key=lambda x: x[1], reverse=True)),
        "byCurrency": dict(sorted(by_currency.items(), key=lambda x: x[1], reverse=True)),
        "byDirection": by_direction,
    }


# ... existing imports ...
from pydantic import BaseModel
try:
    from portfolio_tracker import PortfolioTracker
except ImportError:
    PortfolioTracker = None

tracker = PortfolioTracker() if PortfolioTracker else None

# Pydantic Models
class PositionRequest(BaseModel):
    ticker: str
    shares: float
    price: float
    date: str
    currency: str = "USD"
    type: str = "Long"

@app.get("/api/tracker")
async def get_portfolio_tracker():
    if not tracker:
        return {"error": "Portfolio Tracker module not loaded"}
    try:
        # For now return raw DB data, heavy calc later
        return tracker.get_portfolio()
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/tracker/summary")
async def get_portfolio_summary():
    if not tracker:
        return {"error": "Portfolio Tracker module not loaded"}
    try:
        # This triggers live price fetch
        return tracker.get_summary()
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/tracker/position")
async def add_position(pos: PositionRequest):
    if not tracker:
        return {"error": "Portfolio Tracker module not loaded"}
    try:
        tracker.add_position(
            pos.ticker, 
            pos.shares, 
            pos.price, 
            pos.date, 
            pos.currency, 
            pos.type
        )
        return {"status": "success", "message": f"Added {pos.ticker}"}
    except Exception as e:
        return {"error": str(e)}

@app.delete("/api/tracker/position/{ticker}")
async def remove_position(ticker: str):
    if not tracker:
        return {"error": "Portfolio Tracker module not loaded"}
    try:
        tracker.remove_position(ticker)
        return {"status": "success", "message": f"Removed {ticker}"}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
