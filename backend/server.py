import sys
import os

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import pandas as pd
import numpy as np
import time
import yfinance as yf
from datetime import datetime
from typing import Any

# Import risk.py (Now local)
try:
    import risk
except ImportError as e:
    print(f"Error importing risk.py: {e}")
    risk = None

try:
    from brain_store import BrainStore
    from brain_ingestion import chunk_text, normalize_text, stable_hash
except ImportError as e:
    print(f"Error importing Investment Brain modules: {e}")
    BrainStore = None

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
_data_cache = {}  # Shared raw market data cache keyed by portfolio
brain_store = BrainStore() if BrainStore else None


class BrainMemoryRequest(BaseModel):
    type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=240)
    body: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    source: str = "manual"
    confidence: float | None = Field(default=None, ge=0, le=1)


class BrainSourceRequest(BaseModel):
    kind: str = "note"
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1)
    author: str | None = None
    sourceDate: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class BrainChunkRequest(BaseModel):
    ordinal: int = 0
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1)
    summary: str | None = None
    tokenCount: int = 0
    pageStart: int | None = None
    pageEnd: int | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    contentHash: str | None = None
    embeddingModel: str | None = None
    embedding: list[float] | None = None


class BrainTextIngestRequest(BaseModel):
    kind: str = "document"
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1)
    author: str | None = None
    sourceDate: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunkWords: int = Field(default=900, ge=150, le=2500)
    overlapWords: int = Field(default=120, ge=0, le=800)


def _brain_or_503():
    if not brain_store:
        raise HTTPException(status_code=503, detail="Investment Brain store is not available")
    return brain_store

def _get_cached_market_data(force: bool = False, portfolio_name: str = "main"):
    """Fetch and cache raw market data for a portfolio."""
    global _data_cache
    now = time.time()
    
    if portfolio_name not in _data_cache:
        _data_cache[portfolio_name] = {"data": None, "timestamp": 0}
        
    cache_entry = _data_cache[portfolio_name]
    
    if not force and cache_entry["data"] and (now - cache_entry["timestamp"]) < CACHE_TTL:
        print(f"Using cached market data for {portfolio_name} (age: {int(now - cache_entry['timestamp'])}s)")
        return cache_entry["data"]
    
    print(f"Fetching fresh market data for {portfolio_name}...")
    raw_prices, fx_rates, volume_data = risk.fetch_data(portfolio_name)
    usd_prices = risk.normalize_to_base_currency(raw_prices, fx_rates, portfolio_name)
    cache_entry["data"] = (usd_prices, fx_rates, volume_data, raw_prices)
    cache_entry["timestamp"] = now
    return cache_entry["data"]

CACHE_TTL = 300  # seconds

@app.get("/api/status")
async def get_status():
    if risk:
        return {"state": "ready", "message": "Ready"}
    else:
        return {"state": "error", "message": "Risk module failed to load"}


# ==========================================
# Investment Brain API (SQLite + unified FTS)
# ==========================================

@app.get("/api/brain/status")
async def get_brain_status():
    store = _brain_or_503()
    return {
        "state": "ready",
        "database": str(store.db_path),
        "search": "sqlite_fts5",
        "vectorSearch": "not_configured",
        "embeddingProvider": "not_configured",
        "capabilities": [
            "manual_memories",
            "source_storage",
            "text_ingestion",
            "chunk_indexing",
            "keyword_search",
            "embedding_ready_schema",
        ],
        "counts": store.counts(),
    }


@app.get("/api/brain/memories")
async def list_brain_memories(
    q: str | None = None,
    memory_type: str | None = Query(default=None, alias="type"),
    limit: int = 100,
):
    store = _brain_or_503()
    try:
        return {"memories": store.list_memories(query=q, memory_type=memory_type, limit=limit)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/brain/memories")
async def add_brain_memory(memory: BrainMemoryRequest):
    store = _brain_or_503()
    try:
        saved = store.add_memory(
            memory_type=memory.type,
            title=memory.title,
            body=memory.body,
            tags=memory.tags,
            source=memory.source,
            confidence=memory.confidence,
        )
        return {"memory": saved}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/brain/memories/{memory_id}")
async def delete_brain_memory(memory_id: int):
    store = _brain_or_503()
    deleted = store.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted", "id": memory_id}


@app.post("/api/brain/sources")
async def add_brain_source(source: BrainSourceRequest):
    store = _brain_or_503()
    try:
        saved = store.add_source(
            kind=source.kind,
            title=source.title,
            body=source.body,
            author=source.author,
            source_date=source.sourceDate,
            tags=source.tags,
            metadata=source.metadata,
        )
        return {"source": saved}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/brain/sources")
async def list_brain_sources(
    q: str | None = None,
    kind: str | None = None,
    limit: int = 100,
):
    store = _brain_or_503()
    return {"sources": store.list_sources(query=q, kind=kind, limit=limit)}


@app.delete("/api/brain/sources/{source_id}")
async def delete_brain_source(source_id: int):
    store = _brain_or_503()
    deleted = store.delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"status": "deleted", "id": source_id, "counts": store.counts()}


@app.post("/api/brain/ingest/text")
async def ingest_brain_text(payload: BrainTextIngestRequest):
    store = _brain_or_503()
    body = normalize_text(payload.body)
    if not body:
        raise HTTPException(status_code=400, detail="body is required")

    metadata = {
        **payload.metadata,
        "sourceHash": stable_hash(payload.title, body),
        "ingestion": {
            "mode": "text",
            "chunkWords": payload.chunkWords,
            "overlapWords": payload.overlapWords,
            "embeddingProvider": "not_configured",
        },
    }

    try:
        source = store.add_source(
            kind=payload.kind,
            title=payload.title,
            body=body,
            author=payload.author,
            source_date=payload.sourceDate,
            tags=payload.tags,
            metadata=metadata,
        )
        chunks = chunk_text(
            body,
            source_title=payload.title,
            tags=payload.tags,
            chunk_words=payload.chunkWords,
            overlap_words=payload.overlapWords,
        )
        saved_chunks = store.add_chunks(source["id"], chunks)
        return {
            "source": source,
            "chunks": saved_chunks,
            "counts": store.counts(),
            "message": "Text stored, chunked, and indexed. Embeddings can be attached later.",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/brain/sources/{source_id}/chunks")
async def add_brain_chunks(source_id: int, chunks: list[BrainChunkRequest]):
    store = _brain_or_503()
    prepared = []
    for chunk in chunks:
        data = chunk.dict()
        body = normalize_text(data["body"])
        data["body"] = body
        data["contentHash"] = data["contentHash"] or stable_hash(str(source_id), str(data["ordinal"]), body)
        prepared.append(data)

    try:
        saved = store.add_chunks(source_id, prepared)
        return {"chunks": saved, "counts": store.counts()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/brain/chunks")
async def list_brain_chunks(
    source_id: int | None = None,
    q: str | None = None,
    limit: int = 100,
):
    store = _brain_or_503()
    return {"chunks": store.list_chunks(source_id=source_id, query=q, limit=limit)}


@app.get("/api/brain/sources/{source_id}/chunks")
async def list_brain_source_chunks(source_id: int, limit: int = 100):
    store = _brain_or_503()
    return {"chunks": store.list_chunks(source_id=source_id, limit=limit)}


@app.get("/api/brain/search")
async def search_brain(q: str, limit: int = 50, entity_type: str | None = None):
    store = _brain_or_503()
    return {
        "query": q,
        "results": store.search(query=q, limit=limit, entity_type=entity_type),
        "counts": store.counts(),
    }

@app.get("/api/metrics")
async def get_metrics(force: bool = False, costTier: str = 'retail', portfolio: str = 'main'):
    global _cache
    
    if not risk:
        return {"error": "risk.py not found or failed to import"}
        
    cache_key = f"{portfolio}_{costTier}"
    if cache_key not in _cache:
        _cache[cache_key] = {"data": None, "timestamp": 0}
        
    tier_cache = _cache[cache_key]
    
    # Return cached response if fresh (unless force=True)
    if force:
        # Invalidate all tier caches
        for k in _cache:
            _cache[k] = {"data": None, "timestamp": 0}
    elif tier_cache["data"] and (time.time() - tier_cache["timestamp"]) < CACHE_TTL:
        print(f"Returning cached response for {cache_key} (age: {int(time.time() - tier_cache['timestamp'])}s)")
        return tier_cache["data"]

    try:
        print(f"Calculating metrics for tier: {costTier}...")
        
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
            
        # 1. Fetch market data (shared cache — same data for all tiers)
        usd_prices, fx_rates, volume_data, raw_prices = _get_cached_market_data(force, portfolio_name=portfolio)
        
        # 2. Calculate risk metrics with tier-specific rates
        metrics = risk.calculate_risk_metrics(
            usd_prices, 
            volume_data, 
            fx_rates,
            margin_rate=margin_rate,
            borrow_fee=borrow_fee,
            portfolio_name=portfolio
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
            
        periodic_rets = risk.calculate_periodic_returns(usd_prices, portfolio_name=portfolio)

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
                "longOnlyBeta": to_float(metrics.get('YTD_Long_Only_Beta')),
                "shortOnlyBeta": to_float(metrics.get('YTD_Short_Only_Beta')),
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
                "ytdCorrelation": to_float(metrics.get('YTD_Correlation')),
                "ytdMaxDrawdown": to_float(metrics.get('YTD_Max_Drawdown')),
                "benchmarkYtdMaxDrawdown": to_float(metrics.get('Benchmark_YTD_Max_Drawdown')),
                "ytdReturnGross": to_float(metrics.get('YTD_Return_Gross')),
                "ytdFinancingCost": to_float(metrics.get('YTD_Financing_Cost')),
                "annualFinancingCost": to_float(metrics.get('Annual_Financing_Cost')),
                
                # Standardized Sharpe Metrics
                "ytdSharpe": to_float(metrics.get('YTD_Sharpe')),           # Previously riskEfficiencyVol
                "benchmarkYtdSharpe": to_float(metrics.get('Benchmark_YTD_Sharpe')), 
                "benchmarkHistSharpe": to_float(metrics.get('Benchmark_Hist_Sharpe')), # For Hist Avg comparison
                "ytdVol": to_float(metrics.get('YTD_Vol')),
                "benchmarkYtdVol": to_float(metrics.get('Benchmark_YTD_Vol')),
                "ytdReturnPln": to_float(metrics.get('YTD_Return_PLN')),
                "wigYtd": to_float(metrics.get('WIG_YTD')),
                "msciYtd": to_float(metrics.get('MSCI_YTD')),
                "ytdLongsContrib": to_float(metrics.get('YTD_Longs_Contrib')),
                "ytdShortsContrib": to_float(metrics.get('YTD_Shorts_Contrib')),
                "fxWatchlist": metrics.get('Fx_Watchlist', {}),
                "currencyExposure": {}, # Will be populated below
                "periodLabel": metrics.get('Period_Label')
            },
            "leverage": metrics['Leverage_Stats'],
            "talebMetrics": metrics.get('Taleb_Metrics'),
            "riskAttribution": [],
            "stressTests": [],
            "periodicReturns": [],
            "history": []
        }

        # Format Convexity Metrics
        convexity = metrics.get('Convexity_Metrics')
        if convexity:
            response["convexity"] = {
                "upsideCapture": to_float(convexity.get('Upside_Capture')),
                "downsideCapture": to_float(convexity.get('Downside_Capture')),
                "captureSpread": to_float(convexity.get('Capture_Spread')),
                "quadraticCoeffs": [to_float(c) for c in convexity.get('Quadratic_Coeffs', [0,0,0])],
                "linearCoeffs": [to_float(c) for c in convexity.get('Linear_Coeffs', [0,0])],
                "rSquared": to_float(convexity.get('R_Squared')),
                "isConvex": bool(convexity.get('Is_Convex', False)),
                "scatterData": convexity.get('Scatter_Data', []),
            }
        else:
            response["convexity"] = None
            
        # Format Momentum Metrics
        momentum = metrics.get('Momentum_Metrics')
        if momentum:
            response["momentum"] = {
                "top_rs": momentum.get('top_rs', []),
                "bot_rs": momentum.get('bot_rs', []),
                "corr_surges": momentum.get('corr_surges', [])
            }
        else:
            response["momentum"] = None

        # Format Risk Attribution
        for ticker, stats in metrics['Risk_Attribution'].items():
            response["riskAttribution"].append({
                "ticker": ticker,
                "weight": stats['Weight'],
                "pctRisk": stats['Pct_Risk'],
                "mctr": stats['MCTR']
            })
        response["riskAttribution"].sort(key=lambda x: x["pctRisk"], reverse=True)

        # Format Stress Tests (non-linear)
        for scenario, result in stress_results.items():
            if isinstance(result, dict):
                response["stressTests"].append({
                    "scenario": scenario,
                    "impact": to_float(result.get('alpha_neutral', result.get('nonlinear', 0))),
                    "linearImpact": to_float(result.get('linear', 0)),
                    "fittedImpact": to_float(result.get('fitted_with_alpha', result.get('nonlinear', 0))),
                    "shapeEffect": to_float(result.get('shape_effect', 0)),
                    "alphaEffect": to_float(result.get('alpha_effect', 0)),
                    "modelCurve": to_float(result.get('model_curve', 0)),
                    "modelSlope": to_float(result.get('model_slope', 0)),
                    "modelIntercept": to_float(result.get('model_intercept', 0)),
                    "marketMove": to_float(result.get('market_move', 0)),
                    "stressDays": result.get('stress_days'),
                    "dailyMarketMove": to_float(result.get('daily_market_move')),
                })
            else:
                # Fallback for old format
                response["stressTests"].append({
                    "scenario": scenario,
                    "impact": to_float(result),
                    "linearImpact": to_float(result),
                    "marketMove": None,
                })
        # Current exposure book is separate from historical snapshots used for YTD contribution.
        portfolio_config = risk.get_effective_portfolio_config(portfolio)
        all_position_config = risk.get_all_position_configs(portfolio)
        target_config = risk.load_portfolio_config(portfolio)
        ytd_position_contributions = metrics.get('YTD_Position_Contributions', {}) or {}
        ytd_current_weights = metrics.get('YTD_Current_Weights', {}) or {}
        rebalance_events = metrics.get('Rebalance_Events', []) or []
        response["rebalance"] = {
            "mode": metrics.get('Rebalance_Mode', 'static'),
            "events": rebalance_events,
            "eventCount": len(rebalance_events),
        }

        # Calculate Currency Exposure using portfolio_config.
        # Net exposure is the signed currency risk as a share of equity;
        # gross exposure is the absolute book size in that currency.
        curr_exposure_net = {}
        curr_exposure_gross = {}
        total_gross = 0
        if portfolio_config:
            for ticker, info in portfolio_config.items():
                curr = info.get('currency', 'USD')
                weight = info.get('weight', 0)
                direction = 1 if info.get('type', 'Long') == 'Long' else -1
                curr_exposure_net[curr] = curr_exposure_net.get(curr, 0) + weight * direction
                curr_exposure_gross[curr] = curr_exposure_gross.get(curr, 0) + weight
                total_gross += weight
        
        curr_exposure_gross_share = {}
        if total_gross > 0:
            curr_exposure_gross_share = {
                curr: gross / total_gross
                for curr, gross in curr_exposure_gross.items()
            }
        
        response["vitals"]["currencyExposure"] = curr_exposure_net
        response["vitals"]["currencyExposureNet"] = curr_exposure_net
        response["vitals"]["currencyExposureGross"] = curr_exposure_gross
        response["vitals"]["currencyExposureGrossShare"] = curr_exposure_gross_share

        # Calculate Country Allocation for World Map
        country_allocation = {}
        if all_position_config:
            for ticker, info in all_position_config.items():
                country = info.get('country', 'USA')  # Default to USA if not specified
                current_info = portfolio_config.get(ticker)
                weight = current_info.get('weight', 0) if current_info else 0
                pos_type = info.get('type', 'Long')
                direction = 1 if pos_type == 'Long' else -1
                
                if ticker in ytd_position_contributions:
                    contribution = ytd_position_contributions.get(ticker) or 0
                else:
                    # Get YTD Return for active-book contribution fallback
                    ytd_ret = 0
                    if ticker in periodic_rets.index:
                        val = periodic_rets.loc[ticker, 'YTD']
                        if not pd.isna(val):
                            ytd_ret = val
                    contribution = weight * ytd_ret * direction

                if country not in country_allocation:
                    country_allocation[country] = {'long': 0, 'short': 0, 'contribution': 0, 'tickers': []}
                
                if current_info:
                    if pos_type == 'Long':
                        country_allocation[country]['long'] += weight
                    else:
                        country_allocation[country]['short'] += weight
                
                country_allocation[country]['contribution'] += contribution
                
                country_allocation[country]['tickers'].append({
                    'ticker': ticker,
                    'weight': weight,
                    'type': pos_type,
                    'contribution': contribution,
                    'status': "Active" if current_info else ("Planned" if ticker in target_config else "Exited")
                })
        
        response["countryAllocation"] = country_allocation

        # Format Periodic Returns
        # Periodic returns is a DataFrame: index=ticker, columns=['YTD', '1Y', '3Y', '5Y']
        # We need to add 1M returns and YTD contribution
        portfolio_ytd = to_float(metrics.get('YTD_Return')) or 0.0
        
        display_tickers = list(all_position_config.keys())
        for ticker in ytd_position_contributions.keys():
            if ticker not in all_position_config:
                display_tickers.append(ticker)

        for ticker in display_tickers:
            ticker_config = all_position_config.get(ticker, {})
            current_config = portfolio_config.get(ticker)
            is_planned = current_config is None and ticker in target_config
            weight = current_config.get('weight', 0) if current_config else 0
            direction = ticker_config.get('type', None)  # 'Long' or 'Short'
            is_active = current_config is not None
            status = "Active" if is_active else ("Planned" if is_planned else "Exited")
            
            # Check if this ticker is in periodic_rets
            has_rets = (periodic_rets is not None) and (ticker in periodic_rets.index)
            row = periodic_rets.loc[ticker] if has_rets else None
            
            # Calculate YTD contribution: weight * ytd_return * direction
            ytd_ret = row['YTD'] if (row is not None and 'YTD' in row and not pd.isna(row['YTD'])) else None
            dir_multiplier = 1 if direction == 'Long' else (-1 if direction == 'Short' else 0)
            if ticker in ytd_position_contributions:
                ytd_contribution = ytd_position_contributions.get(ticker)
            else:
                ytd_contribution = weight * ytd_ret * dir_multiplier if weight and ytd_ret is not None else None
            
            # Calculate current drifted weight
            if ticker in ytd_current_weights:
                current_weight = ytd_current_weights.get(ticker)
            elif is_active and weight and ytd_ret is not None:
                current_weight = float(weight * (1 + ytd_ret) / (1 + portfolio_ytd))
            elif not is_active:
                current_weight = 0.0
            else:
                current_weight = None
            
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

            if usd_prices is not None and ticker in usd_prices.columns:
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
            
            # Daily/Weekly contribution uses CURRENT (drifted) weight, not initial.
            r1d_contribution = current_weight * r1d * dir_multiplier if is_active and current_weight and r1d is not None else None
            r7d_contribution = current_weight * r7d * dir_multiplier if is_active and current_weight and r7d is not None else None

            item = {
                "ticker": ticker,
                "sector": sector,
                "ytd": ytd_ret,
                "r1d": to_float(r1d),
                "r7d": to_float(r7d),
                "r1m": to_float(r1m),
                "r1y": row['1Y'] if (row is not None and '1Y' in row and not pd.isna(row['1Y'])) else None,
                "ytdContribution": to_float(ytd_contribution),
                "r1dContribution": to_float(r1d_contribution),
                "r7dContribution": to_float(r7d_contribution),
                "weight": to_float(weight) if weight else None,
                "currentWeight": to_float(current_weight) if current_weight is not None else to_float(weight),
                "direction": direction,
                "status": status,
                "lastPrice": last_price,
                "entryPrice": ticker_config.get('entry_price', None) if ticker_config else None,
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
                    ytd_bench_vals = (1 + ytd_bench_ret).cumprod()

                ytd_beta_hist = metrics.get('YTD_Beta_History')
                
                # Align dates
                for date in ytd_port.index:
                    date_str = date.strftime('%Y-%m-%d')
                    port_val = ytd_port.loc[date] * 100000
                    
                    beta_val = None
                    if ytd_beta_hist is not None and date in ytd_beta_hist.index:
                        beta_val = ytd_beta_hist.loc[date]
                    
                    response["ytdHistory"].append({
                        "date": date_str,
                        "portfolio": to_float(port_val),
                        "benchmark": None, # calculated below
                        "beta": to_float(beta_val)
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
            for key in (
                "impact",
                "linearImpact",
                "fittedImpact",
                "shapeEffect",
                "alphaEffect",
                "modelCurve",
                "modelSlope",
                "modelIntercept",
                "marketMove",
                "dailyMarketMove",
            ):
                if key in st:
                    st[key] = to_float(st[key])
        
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
async def get_portfolio(portfolio: str = 'main'):
    """Return the full portfolio composition from config."""
    if not risk:
        return {"error": "Risk module not loaded"}

    portfolio_config = risk.get_effective_portfolio_config(portfolio)
    benchmark = getattr(risk, 'BENCHMARK', 'SPY')

    positions = []
    long_exposure = 0.0
    short_exposure = 0.0

    for ticker, info in portfolio_config.items():
        position = {
            "ticker": ticker,
            "weight": info.get('weight', 0),
            "type": info.get('type', 'Long'),
            "currency": info.get('currency', 'USD'),
            "country": info.get('country', 'USA'),
            "sector": info.get('sector', 'Unknown'),
        }
        if 'entry_price' in info:
            position['entry_price'] = info['entry_price']
            
        positions.append(position)
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
async def get_portfolio_allocation(portfolio: str = 'main'):
    """Return portfolio allocation breakdowns by sector, country, currency, and direction."""
    if not risk:
        return {"error": "Risk module not loaded"}

    portfolio_config = risk.get_effective_portfolio_config(portfolio)

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

# ==========================================
# Stock Autocomplete API
# ==========================================

@app.get("/api/lookup/suggest")
async def suggest_tickers(query: str):
    """
    Returns autocomplete suggestions using Yahoo Finance's search endpoint.
    """
    import httpx
    if not query or len(query.strip()) < 1:
        return []
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {
            "q": query,
            "quotesCount": 7,
            "newsCount": 0,
            "listsCount": 0,
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            data = resp.json()
        quotes = data.get("quotes", [])
        return [
            {
                "symbol":   q.get("symbol", ""),
                "name":     q.get("longname") or q.get("shortname", ""),
                "exchange": q.get("exchange", ""),
                "type":     q.get("quoteType", ""),
            }
            for q in quotes
            if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF")
        ]
    except Exception as e:
        return []


# ==========================================
# Stock Lookup API
# ==========================================

@app.get("/api/lookup")
async def lookup_stock(query: str):
    """
    Fetch price returns and valuation metrics for any ticker via yfinance.
    Returns: 1D, 7D, 1M, YTD, 1Y returns + TTM P/E + (FCF-SBC)/EV yield.
    """
    import math

    def safe_float(val):
        try:
            f = float(val)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except:
            return None

    try:
        ticker_str = query.strip().upper()
        t = yf.Ticker(ticker_str)

        # --- Fetch price history for returns ---
        hist = t.history(period="2y", auto_adjust=True)
        if hist.empty or len(hist) < 2:
            return {"error": f"No price data found for '{query}'. Please check the ticker symbol."}

        close = hist["Close"].dropna()
        now = close.index[-1]
        current_price = float(close.iloc[-1])

        def period_return(days=None, ytd=False):
            if ytd:
                year_start = pd.Timestamp(f"{now.year}-01-01", tz=close.index.tz)
                sub = close[close.index >= year_start]
                if len(sub) < 1:
                    return None
                # Find prev year close
                prev = close[close.index < year_start]
                base = float(prev.iloc[-1]) if not prev.empty else float(sub.iloc[0])
                return (float(sub.iloc[-1]) - base) / base if base != 0 else None
            else:
                # Find approx trading days back
                if len(close) <= days:
                    return None
                base = float(close.iloc[-days - 1])
                return (current_price - base) / base if base != 0 else None

        r1d  = period_return(days=1)
        r7d  = period_return(days=5)    # ~1 trading week
        r1m  = period_return(days=21)   # ~1 trading month
        r1y  = period_return(days=252)
        r_ytd = period_return(ytd=True)

        # --- Fetch info dict for valuation ---
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass

        name     = info.get("longName") or info.get("shortName") or ticker_str
        currency = info.get("currency", "USD")

        # TTM P/E
        pe = safe_float(info.get("trailingPE"))

        # (FCF - SBC) / EV
        fcf = safe_float(info.get("freeCashflow"))
        ev  = safe_float(info.get("enterpriseValue"))

        # Try to get SBC from cashflow statement
        sbc = None
        sbc_estimated = False
        try:
            cf = t.cashflow  # columns = years, index = line items
            if cf is not None and not cf.empty:
                # yfinance labels vary — try a few
                for label in ["Stock Based Compensation", "StockBasedCompensation", "Share Based Compensation Expense"]:
                    if label in cf.index:
                        sbc_val = safe_float(cf.loc[label].iloc[0])  # most recent year
                        if sbc_val is not None:
                            sbc = abs(sbc_val)  # cashflow statements show SBC as positive outflow
                            break
        except Exception:
            pass

        if sbc is None:
            sbc = 0.0
            sbc_estimated = True

        # Compute (FCF - SBC) / EV yield
        fcf_sbc_yield = None
        if fcf is not None and ev is not None and ev != 0:
            fcf_sbc_yield = (fcf - sbc) / ev  # expressed as decimal, rendered as % on frontend

        return {
            "ticker":        ticker_str,
            "name":          name,
            "currency":      currency,
            "currentPrice":  current_price,
            "r1d":           safe_float(r1d),
            "r7d":           safe_float(r7d),
            "r1m":           safe_float(r1m),
            "rYtd":          safe_float(r_ytd),
            "r1y":           safe_float(r1y),
            "pe":            pe,
            "fcfSbcYield":   safe_float(fcf_sbc_yield),
            "sbc_estimated": sbc_estimated,
            "error":         None,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


# ==========================================
# Business Quality API  — "Munger Lens"
# ==========================================

_quality_cache: dict = {}
QUALITY_TTL = 3600  # 1 hour – fundamental data doesn't change daily

@app.get("/api/quality")
async def get_quality(portfolio: str = 'main'):
    """
    Return Munger-style business quality metrics for every holding.
    Metrics: ROIC proxy (ROE as fallback), gross margin, debt/equity,
             FCF yield (FCF/EV), owner earnings yield ((FCF-SBC)/EV),
    All sourced from yfinance .info – cached 1 hour.
    """
    import math

    now = time.time()
    if portfolio in _quality_cache:
        entry = _quality_cache[portfolio]
        if (now - entry["ts"]) < QUALITY_TTL:
            print(f"[quality] Returning cached data for {portfolio}")
            return entry["data"]

    if not risk:
        return {"error": "Risk module not loaded"}

    portfolio_config = risk.get_effective_portfolio_config(portfolio)

    def sf(val):
        """Safe float – returns None for NaN/Inf/missing."""
        try:
            f = float(val)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except:
            return None

    results = []

    for ticker, cfg in portfolio_config.items():
        print(f"[quality] Fetching {ticker}…")
        try:
            t = yf.Ticker(ticker)
            info = {}
            try:
                info = t.info or {}
            except Exception:
                pass

            # ── Core quality metrics ──────────────────────────────
            roe          = sf(info.get("returnOnEquity"))      # proxy for ROIC when no debt breakdown
            roic_approx  = sf(info.get("returnOnAssets"))      # more conservative ROIC proxy
            gross_margin = sf(info.get("grossMargins"))
            op_margin    = sf(info.get("operatingMargins"))
            net_margin   = sf(info.get("profitMargins"))
            debt_equity  = sf(info.get("debtToEquity"))        # as ratio (e.g. 0.5 = 50%)
            rev_growth   = sf(info.get("revenueGrowth"))       # trailing 12m vs prior year
            current_ratio= sf(info.get("currentRatio"))
            peg          = sf(info.get("pegRatio"))
            pe           = sf(info.get("trailingPE"))
            pb           = sf(info.get("priceToBook"))

            # ── Owner Earnings (FCF − SBC) / EV ──────────────────
            fcf          = sf(info.get("freeCashflow"))
            ev           = sf(info.get("enterpriseValue"))

            sbc = None
            try:
                cf = t.cashflow
                if cf is not None and not cf.empty:
                    for label in ["Stock Based Compensation", "StockBasedCompensation",
                                  "Share Based Compensation Expense"]:
                        if label in cf.index:
                            v = sf(cf.loc[label].iloc[0])
                            if v is not None:
                                sbc = abs(v)
                                break
            except Exception:
                pass

            fcf_ev_yield = (fcf / ev) if (fcf is not None and ev and ev != 0) else None
            owner_earnings = (fcf - (sbc or 0)) if fcf is not None else None
            oe_yield = (owner_earnings / ev) if (owner_earnings is not None and ev and ev != 0) else None

            # ── Munger quality score (0-100) ──────────────────────
            # Each criterion contributes points; no single factor dominates.
            score = 0
            flags = []

            if gross_margin is not None:
                if gross_margin >= 0.50:  score += 25; flags.append("✓ Pricing power")
                elif gross_margin >= 0.30: score += 12
                else: flags.append("✗ Thin margins")

            if roic_approx is not None:
                if roic_approx >= 0.15:   score += 25; flags.append("✓ High ROIC")
                elif roic_approx >= 0.08:  score += 12
                else: flags.append("✗ Low ROIC")

            if oe_yield is not None:
                if oe_yield >= 0.05:   score += 20; flags.append("✓ Cheap on OE")
                elif oe_yield >= 0.02: score += 10
                elif oe_yield < 0:     flags.append("✗ Negative OE yield")

            if debt_equity is not None:
                # yfinance returns D/E as percent (e.g. 45.2 means 45.2%)
                de_ratio = debt_equity / 100 if debt_equity > 5 else debt_equity
                if de_ratio <= 0.30:   score += 15; flags.append("✓ Fortress balance sheet")
                elif de_ratio <= 0.80: score += 7
                else: flags.append("✗ High leverage")

            if rev_growth is not None:
                if rev_growth >= 0.10:  score += 15; flags.append("✓ Revenue growth")
                elif rev_growth >= 0.0:  score += 7
                else: flags.append("✗ Revenue shrinking")

            score = min(score, 100)

            # ── Inversion: biggest risk to the thesis ─────────────
            inversion_risks = []
            if gross_margin is not None and gross_margin < 0.20:
                inversion_risks.append("Commodity-like pricing — margin compression risk")
            if debt_equity is not None:
                de_ratio = debt_equity / 100 if debt_equity > 5 else debt_equity
                if de_ratio > 1.0:
                    inversion_risks.append("High debt — rising rates could stress coverage")
            if pe is not None and pe > 40:
                inversion_risks.append("Rich valuation — growth disappointment = large de-rating")
            if rev_growth is not None and rev_growth < 0:
                inversion_risks.append("Declining revenue — business in structural decline?")
            if oe_yield is not None and oe_yield < 0:
                inversion_risks.append("Burning cash after SBC — not self-financing")
            if not inversion_risks:
                inversion_risks.append("No obvious red flags in available data")

            results.append({
                "ticker":        ticker,
                "direction":     cfg.get("type", "Long"),
                "weight":        cfg.get("weight", 0),
                "sector":        cfg.get("sector", "Unknown"),
                "country":       cfg.get("country", "USA"),
                "name":          info.get("longName") or info.get("shortName") or ticker,
                # Quality metrics
                "grossMargin":   sf(gross_margin),
                "roic":          sf(roic_approx),   # ROA as ROIC proxy
                "roe":           sf(roe),
                "debtEquity":    sf(debt_equity),
                "revenueGrowth": sf(rev_growth),
                "currentRatio":  sf(current_ratio),
                "opMargin":      sf(op_margin),
                "netMargin":     sf(net_margin),
                "pe":            sf(pe),
                "pb":            sf(pb),
                "peg":           sf(peg),
                "fcfEvYield":    sf(fcf_ev_yield),
                "ownerEarningsYield": sf(oe_yield),
                "sbcEstimated":  sbc is None,
                # Munger lens
                "qualityScore":  score,
                "qualityFlags":  flags,
                "inversionRisks": inversion_risks,
            })

        except Exception as e:
            print(f"[quality] Error fetching {ticker}: {e}")
            results.append({
                "ticker": ticker,
                "direction": cfg.get("type", "Long"),
                "weight": cfg.get("weight", 0),
                "sector": cfg.get("sector", "Unknown"),
                "error": str(e),
                "qualityScore": None,
                "qualityFlags": [],
                "inversionRisks": ["Data unavailable"],
            })

    payload = {"portfolio": portfolio, "positions": results}
    _quality_cache[portfolio] = {"data": payload, "ts": now}
    return payload


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

