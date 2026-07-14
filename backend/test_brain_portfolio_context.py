"""Focused checks for the live portfolio context supplied to Investment Brain."""

import asyncio
import time
from datetime import datetime, timedelta

import server


original_get_config = server.risk.get_effective_portfolio_config
original_get_metrics = server.get_metrics
server.risk.get_effective_portfolio_config = lambda _portfolio: {
    "LONG": {
        "weight": 0.60,
        "type": "Long",
        "sector": "Technology",
        "country": "USA",
        "currency": "USD",
    },
    "SHORT": {
        "weight": 0.40,
        "type": "Short",
        "sector": "Consumer",
        "country": "USA",
        "currency": "USD",
    },
}

try:
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    metrics = {
        "leverage": {"Long_Exp": 0.60, "Short_Exp": 0.40, "Gross_Exp": 1.0, "Net_Exp": 0.20},
        "vitals": {
            "ytdReturn": 0.12,
            "ytdReturnGross": 0.135,
            "benchmarkYtd": 0.08,
            "ytdAlpha": 0.04,
            "ytdBeta": 0.75,
            "ytdVol": 0.18,
            "ytdMaxDrawdown": -0.07,
            "ytdFinancingCost": 0.015,
        },
        "periodicReturns": [
            {
                "ticker": "LONG",
                "currentWeight": 0.65,
                "r1m": 0.05,
                "r3m": 0.20,
                "r6m": 0.30,
                "r12mEx1m": 0.25,
                "ytd": 0.18,
                "priceVs50d": 0.08,
                "priceVs200d": 0.12,
                "drawdown52w": -0.03,
                "ytdContribution": 0.10,
            },
            {
                "ticker": "SHORT",
                "currentWeight": 0.35,
                "r1m": 0.03,
                "r3m": 0.10,
                "r6m": -0.05,
                "r12mEx1m": 0.07,
                "ytd": 0.11,
                "priceVs50d": 0.02,
                "priceVs200d": -0.04,
                "drawdown52w": -0.09,
                "ytdContribution": -0.04,
            },
        ],
        "momentum": {
            "all_rs": [
                {"ticker": "LONG", "rs": 0.04, "bmk": "SPY"},
                {"ticker": "SHORT", "rs": -0.02, "bmk": "SPY"},
            ],
            "corr_surges": [],
            "methodology": {"source": "Yahoo Finance adjusted close via yfinance"},
        },
        "ytdHistory": [{"date": today, "portfolio": 112000, "benchmark": 108000}],
    }

    context = server._build_brain_portfolio_context(
        metrics,
        portfolio="main",
        cache_timestamp=time.time() - 2,
    )
    positions = {item["ticker"]: item for item in context["positions"]}

    assert context["positionCount"] == 2
    assert context["dataAsOf"] == today
    assert context["marketDataAgeDays"] == 0
    assert context["fresh"] is True
    assert abs(context["exposure"]["target"]["net"] - 0.20) < 1e-12
    assert abs(context["exposure"]["currentDrifted"]["net"] - 0.30) < 1e-12
    assert positions["LONG"]["targetWeight"] == 0.60
    assert positions["LONG"]["currentWeight"] == 0.65
    assert positions["SHORT"]["returns"]["3m"] == 0.10
    assert positions["SHORT"]["positionMomentum"]["3m"] == -0.10
    assert positions["SHORT"]["signedCurrentWeight"] == -0.35
    assert context["momentum"]["leaders3mPositionAdjusted"][0]["ticker"] == "LONG"
    assert context["momentum"]["laggards3mPositionAdjusted"][0]["ticker"] == "SHORT"
    assert context["performanceRankings"]["realizedYtdContributionLeaders"][0]["ticker"] == "LONG"
    assert context["performanceRankings"]["realizedYtdContributionLaggards"][0]["ticker"] == "SHORT"

    prompt_context = server._format_brain_portfolio_context(context)
    assert "Current drifted exposure" in prompt_context
    assert "underlying returns are security returns" in prompt_context
    assert "NAV/equity" in prompt_context
    assert "Pre-ranked 3m position-adjusted leaders" in prompt_context
    assert "Ranking guardrail" in prompt_context
    assert "MANDATORY RANKING FACTS" in prompt_context
    assert "realized YTD contribution leader=LONG Long +10.0%" in prompt_context
    assert "SHORT Short | target +40.0% | current +35.0%" in prompt_context
    assert "SHORT INTERPRETATION: underlying 3m +10.0% becomes BOOK EFFECT 3m -10.0%" in prompt_context
    assert "must never be called a book leader" in prompt_context

    assert server._brain_market_data_intent("Analyze the moat in my Drive research")["requested"] is False
    live_intent = server._brain_market_data_intent("Which holding has weak momentum and adverse volume?")
    assert live_intent["requested"] is True
    assert "price_momentum_or_volume" in live_intent["reasons"]
    disabled_intent = server._brain_market_data_intent("Discuss momentum from my documents only")
    assert disabled_intent["requested"] is False
    assert disabled_intent["explicitlyDisabled"] is True

    outline = server._build_brain_portfolio_outline("main")
    assert outline["marketDataAvailable"] is False
    assert outline["exposure"]["currentDrifted"] is None
    assert "market data was not requested" in server._format_brain_portfolio_context(outline)

    weak_short = {
        "side": "Short",
        "positionMomentum": {"1m": -0.08, "3m": -0.20, "6m": -0.25, "12mEx1m": -0.15},
        "relativeStrength1m": 0.08,
        "momentumAcceleration1m": 0.10,
        "priceVs50d": 0.12,
        "priceVs200d": 0.18,
        "volume": {
            "adverseVolumeRatio20d": 1.30,
            "positionVolumePressure20d": -0.25,
            "volume5dVs20d": 1.20,
            "volume20dVs63d": 1.15,
            "latestCompletedVolumeZScore": 1.5,
            "observations": 100,
        },
    }
    weak_short_diagnostic = server._position_technical_diagnostic(weak_short)
    assert weak_short_diagnostic["screeningStatus"] == "high_conviction_technical_review"
    assert weak_short_diagnostic["technicalAction"] == "review_reduce_or_cover"
    assert weak_short_diagnostic["volumeConfirmsWeakness"] is True

    yesterday = datetime.now() - timedelta(days=1)
    tomorrow = datetime.now() + timedelta(days=1)
    assert server._market_session_is_complete(yesterday, "USA") is True
    assert server._market_session_is_complete(tomorrow, "USA") is False

    async def fake_get_metrics(force=False, costTier="retail", portfolio="main"):
        return metrics

    server.get_metrics = fake_get_metrics
    server._cache["main_retail"] = {"data": metrics, "timestamp": time.time()}
    loaded_context = asyncio.run(server._load_brain_portfolio_context("main"))
    assert loaded_context["positionCount"] == 2
    assert loaded_context["fresh"] is True

    stale = server._build_brain_portfolio_context(
        metrics,
        portfolio="main",
        cache_timestamp=time.time() - server.CACHE_TTL - 30,
    )
    assert stale["fresh"] is False

    missing_market_data = server._build_brain_portfolio_context({}, portfolio="main")
    assert missing_market_data["positionCount"] == 2
    assert missing_market_data["positions"][0]["currentWeight"] in {0.60, 0.40}
    assert missing_market_data["fresh"] is False
finally:
    server.risk.get_effective_portfolio_config = original_get_config
    server.get_metrics = original_get_metrics

print("Brain portfolio context checks passed.")
