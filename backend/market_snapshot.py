"""The saved market-data snapshot: one encoding, shared by the server and the job.

The dashboard's market data comes from Yahoo through yfinance. Yahoo throttles
shared hosting IPs, and a free-tier process restarts with an empty memory, so
the frames a successful fetch produced are also written to the brain store
as one compressed setting per portfolio. Two writers exist: the server, after a
fetch of its own, and the scheduled refresh job in GitHub Actions, which fetches
from a runner instead of the web host so the host barely has to call Yahoo at
all. Both must produce the same bytes, hence this module.
"""

import base64
import gzip
import json
from datetime import datetime

import pandas as pd

SETTING_PREFIX = "market.snapshot.v1."
MAX_BYTES = 6 * 1024 * 1024
FRAME_KEYS = ("usd_prices", "fx_rates", "volume_data", "raw_prices")


def setting_key(portfolio_name: str) -> str:
    return SETTING_PREFIX + str(portfolio_name or "main").strip()


def iso_from_epoch(epoch: float | None) -> str | None:
    if not epoch:
        return None
    return datetime.utcfromtimestamp(float(epoch)).isoformat() + "Z"


def epoch_from_iso(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def market_as_of(usd_prices) -> str | None:
    try:
        if usd_prices is None or usd_prices.empty:
            return None
        return pd.Timestamp(usd_prices.index[-1]).strftime("%Y-%m-%d")
    except Exception:
        return None


def frame_to_payload(frame):
    if frame is None:
        return None
    # 10 decimals: a JPY/USD rate is ~0.0065 and must survive the round trip.
    return json.loads(frame.to_json(orient="split", date_format="iso", double_precision=10))


def frame_from_payload(payload):
    if not payload:
        return None
    frame = pd.DataFrame(
        payload.get("data") or [],
        index=payload.get("index") or [],
        columns=payload.get("columns") or [],
    )
    if len(frame.index):
        frame.index = pd.to_datetime(frame.index)
        if getattr(frame.index, "tz", None) is not None:
            frame.index = frame.index.tz_localize(None)
    return frame


def encode(data, as_of: str | None, fetched_at: float) -> str:
    usd_prices, fx_rates, volume_data, raw_prices = data
    payload = {
        "version": 1,
        "asOf": as_of,
        "fetchedAt": iso_from_epoch(fetched_at),
        "frames": {
            "usd_prices": frame_to_payload(usd_prices),
            "fx_rates": frame_to_payload(fx_rates),
            "volume_data": frame_to_payload(volume_data),
            "raw_prices": frame_to_payload(raw_prices),
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, compresslevel=6)).decode("ascii")


def decode(text: str):
    """Return (frames, asOf, fetchedAt). Raises on anything that is not a snapshot."""
    payload = json.loads(gzip.decompress(base64.b64decode(text)).decode("utf-8"))
    frames = payload.get("frames") or {}
    data = tuple(frame_from_payload(frames.get(key)) for key in FRAME_KEYS)
    if data[0] is None or data[0].empty:
        raise ValueError("snapshot holds no prices")
    return data, payload.get("asOf"), payload.get("fetchedAt")
