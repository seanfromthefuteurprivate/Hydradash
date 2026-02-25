"""
╔══════════════════════════════════════════════════════════════════════════════╗
║               HYDRA BLOWUP PROBABILITY ENGINE v1.0                          ║
║         "What is the probability of a violent market move in 30 min?"       ║
║                                                                              ║
║  This is the crown jewel. It synthesizes ALL data sources into one score:   ║
║  BLOWUP_PROBABILITY (0-100). Calculated every 60 seconds.                   ║
║                                                                              ║
║  Inputs:                                                                     ║
║  1. VIX term structure inversion                                            ║
║  2. Options flow imbalance                                                  ║
║  3. Crypto cascade detection                                                ║
║  4. Premarket gap analysis                                                  ║
║  5. Event proximity (FOMC/CPI/NFP)                                          ║
║  6. Cross-asset divergence                                                  ║
║  7. Volume surge detection                                                  ║
║  8. Market breadth collapse                                                 ║
║                                                                              ║
║  Output: JSON with probability, direction, regime, recommendation           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import json
import time
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any
from enum import Enum
from pathlib import Path
from collections import deque

log = logging.getLogger("HYDRA.BLOWUP")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════

class BlowupRegime(Enum):
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


class Direction(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Recommendation(Enum):
    NO_TRADE = "NO_TRADE"
    SCALP_ONLY = "SCALP_ONLY"
    STRADDLE = "STRADDLE"
    DIRECTIONAL_PUT = "DIRECTIONAL_PUT"
    DIRECTIONAL_CALL = "DIRECTIONAL_CALL"


# Default weights - calibrated via weight_calibrator.py
DEFAULT_WEIGHTS = {
    "vix_inversion": 0.20,
    "flow_imbalance": 0.20,
    "crypto_cascade": 0.10,
    "premarket_gap": 0.10,
    "event_proximity": 0.15,
    "cross_asset": 0.10,
    "volume_surge": 0.10,
    "breadth": 0.05
}

# Thresholds for recommendations
THRESHOLDS = {
    "calm": 30,          # 0-30: SCALP_ONLY
    "elevated": 50,      # 30-50: SCALP_ONLY (tighten stops)
    "high": 70,          # 50-70: STRADDLE
    "extreme": 100       # 70-100: DIRECTIONAL
}

# Path to store weights and history
DATA_DIR = Path(__file__).parent.parent / "data"
WEIGHTS_FILE = DATA_DIR / "blowup_weights.json"
HISTORY_DB = DATA_DIR / "blowup_history.db"


# ═══════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class ComponentScore:
    """Individual component contribution to blowup score."""
    name: str
    raw_value: float      # 0.0 to 1.0 normalized
    weight: float         # From weights config
    weighted_value: float # raw * weight
    source: str           # Data source used
    healthy: bool         # Was data fetch successful?
    details: dict = field(default_factory=dict)


@dataclass
class BlowupResult:
    """Complete blowup analysis result."""
    blowup_probability: int           # 0-100
    direction: str                    # BULLISH/BEARISH/NEUTRAL
    regime: str                       # RISK_ON/RISK_OFF/TRANSITION
    confidence: float                 # 0.0-1.0 based on data quality
    triggers: List[str]               # Active triggers
    recommendation: str               # NO_TRADE/SCALP_ONLY/STRADDLE/DIRECTIONAL_*
    events_next_30min: List[dict]     # Upcoming events
    timestamp: str                    # ISO timestamp
    components: List[dict]            # Detailed component breakdown

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ═══════════════════════════════════════════════════════════════
#  COMPONENT FETCHERS
#  Each returns a normalized 0-1 score with fallback to 0 on error
# ═══════════════════════════════════════════════════════════════

# Global response cache to reduce API calls (rate limit: 5/min on free tier)
_response_cache: Dict[str, tuple] = {}  # {url: (timestamp, data)}
CACHE_TTL = 60  # Cache responses for 60 seconds


def _get_cached(url: str, params: dict = None, headers: dict = None, timeout: int = 10) -> Optional[dict]:
    """HTTP GET with caching to reduce API calls and avoid rate limits."""
    if not HAS_REQUESTS:
        return None

    # Build cache key from URL and params
    cache_key = url + (json.dumps(params, sort_keys=True) if params else "")
    now = time.time()

    # Check cache
    if cache_key in _response_cache:
        cached_time, cached_data = _response_cache[cache_key]
        if now - cached_time < CACHE_TTL:
            return cached_data

    # Make request
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            _response_cache[cache_key] = (now, data)
            return data
        elif resp.status_code == 429:
            log.warning(f"Rate limited: {url}")
            # Return cached data if available, even if stale
            if cache_key in _response_cache:
                return _response_cache[cache_key][1]
        else:
            log.debug(f"HTTP {resp.status_code}: {url}")
        return None
    except Exception as e:
        log.debug(f"Request error: {e}")
        # Return cached data if available
        if cache_key in _response_cache:
            return _response_cache[cache_key][1]
        return None


class ComponentFetcher:
    """Base class for component data fetching with timeout and fallback."""

    TIMEOUT = 10  # seconds

    def __init__(self):
        self.last_value = 0.0
        self.last_fetch = None
        self.error_count = 0

    def _get(self, url: str, params: dict = None, headers: dict = None) -> Optional[dict]:
        """HTTP GET with caching and graceful fallback."""
        data = _get_cached(url, params, headers, self.TIMEOUT)
        if data:
            self.error_count = 0
        else:
            self.error_count += 1
        return data

    def _get_text(self, url: str) -> Optional[str]:
        """HTTP GET text with timeout."""
        if not HAS_REQUESTS:
            return None
        try:
            resp = requests.get(url, timeout=self.TIMEOUT, headers={
                "User-Agent": "Mozilla/5.0 (HYDRA Blowup Engine)"
            })
            return resp.text if resp.status_code == 200 else None
        except Exception:
            return None

    @property
    def is_healthy(self) -> bool:
        return self.error_count < 3


class VIXTermStructure(ComponentFetcher):
    """
    VIX Volatility Indicator.
    Uses VIX level and daily change as volatility signal.
    High VIX (>25) = elevated fear, increasing VIX = worsening sentiment.
    """

    def fetch(self) -> ComponentScore:
        score = 0.0
        details = {}
        source = "polygon_prev"
        healthy = True

        api_key = os.environ.get("POLYGON_API_KEY", "")
        if api_key:
            try:
                # Get VIX data
                vix_data = self._get(
                    "https://api.polygon.io/v2/aggs/ticker/I:VIX/prev",
                    params={"apiKey": api_key}
                )

                if vix_data and vix_data.get("results"):
                    result = vix_data["results"][0]
                    vix_open = result.get("o", 20)
                    vix_close = result.get("c", 20)
                    vix_high = result.get("h", 20)

                    # Calculate daily change
                    vix_change = ((vix_close - vix_open) / vix_open) if vix_open > 0 else 0

                    details = {
                        "vix_close": round(vix_close, 2),
                        "vix_open": round(vix_open, 2),
                        "vix_high": round(vix_high, 2),
                        "vix_change_pct": round(vix_change * 100, 2)
                    }

                    # Score based on VIX level and change
                    # High VIX = elevated volatility/fear
                    if vix_close > 35:
                        score = 1.0  # Extreme fear
                    elif vix_close > 30:
                        score = 0.8
                    elif vix_close > 25:
                        score = 0.5
                    elif vix_close > 22:
                        score = 0.3
                    elif vix_close > 20:
                        score = 0.15

                    # Boost score if VIX is rising
                    if vix_change > 0.10:  # >10% increase
                        score = min(1.0, score + 0.3)
                    elif vix_change > 0.05:  # >5% increase
                        score = min(1.0, score + 0.15)

                    details["score_reason"] = f"VIX {vix_close:.1f}, change {vix_change*100:+.1f}%"
                else:
                    healthy = False
                    details["error"] = "No VIX data"

            except Exception as e:
                log.debug(f"VIX error: {e}")
                healthy = False
                details["error"] = str(e)
        else:
            healthy = False
            source = "no_api_key"

        self.last_value = score
        self.last_fetch = datetime.now(timezone.utc)

        return ComponentScore(
            name="vix_inversion",
            raw_value=score,
            weight=DEFAULT_WEIGHTS["vix_inversion"],
            weighted_value=score * DEFAULT_WEIGHTS["vix_inversion"],
            source=source,
            healthy=healthy,
            details=details
        )


class OptionsFlowImbalance(ComponentFetcher):
    """
    Options Flow Imbalance Detection.
    Uses VIX level + SPY volume as proxy for options flow sentiment.
    High VIX + high volume = bearish flow pressure.
    """

    def fetch(self) -> ComponentScore:
        score = 0.0
        details = {}
        source = "polygon_prev"
        healthy = True
        direction_hint = "neutral"

        api_key = os.environ.get("POLYGON_API_KEY", "")
        if api_key:
            try:
                # Get SPY previous day volume
                spy_data = self._get(
                    "https://api.polygon.io/v2/aggs/ticker/SPY/prev",
                    params={"apiKey": api_key}
                )

                volume = 0
                if spy_data and spy_data.get("results"):
                    volume = spy_data["results"][0].get("v", 0)

                avg_volume = 80_000_000  # Typical SPY daily volume
                vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0

                # Get VIX from prev endpoint
                vix_data = self._get(
                    "https://api.polygon.io/v2/aggs/ticker/I:VIX/prev",
                    params={"apiKey": api_key}
                )

                vix = 20
                if vix_data and vix_data.get("results"):
                    vix = vix_data["results"][0].get("c", 20)

                details = {
                    "spy_volume": volume,
                    "vol_ratio": round(vol_ratio, 2),
                    "vix": round(vix, 2)
                }

                # Score: high VIX + high volume = potential blowup
                if vix > 25 and vol_ratio > 1.5:
                    score = min(1.0, (vix - 20) / 20 * vol_ratio / 2)
                    direction_hint = "bearish"
                elif vix > 30:
                    score = min(1.0, (vix - 20) / 25)
                    direction_hint = "bearish"
                elif vix > 22:
                    score = min(0.4, (vix - 18) / 20)
                    direction_hint = "bearish"
                elif vix < 15 and vol_ratio > 2:
                    score = min(0.6, vol_ratio / 4)
                    direction_hint = "bullish"

                details["direction_hint"] = direction_hint
                healthy = spy_data is not None or vix_data is not None

            except Exception as e:
                log.debug(f"Options flow error: {e}")
                healthy = False
                details["error"] = str(e)
        else:
            healthy = False
            source = "no_api_key"

        self.last_value = score
        return ComponentScore(
            name="flow_imbalance",
            raw_value=score,
            weight=DEFAULT_WEIGHTS["flow_imbalance"],
            weighted_value=score * DEFAULT_WEIGHTS["flow_imbalance"],
            source=source,
            healthy=healthy,
            details=details
        )


class CryptoCascade(ComponentFetcher):
    """
    Crypto Cascade Detection.
    Monitors BTC funding rates and OI changes for liquidation cascade signals.
    Uses CoinGlass or Deribit data.
    """

    def __init__(self):
        super().__init__()
        self.oi_history = deque(maxlen=20)

    def fetch(self) -> ComponentScore:
        score = 0.0
        details = {}
        source = "deribit"
        healthy = True

        try:
            # Try Deribit (no auth required for public data)
            deribit_data = self._get(
                "https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
                params={"currency": "BTC", "kind": "future"}
            )

            if deribit_data and deribit_data.get("result"):
                # Calculate aggregate OI and funding sentiment
                total_oi = 0
                btc_price = 0

                for item in deribit_data["result"]:
                    if item.get("instrument_name") == "BTC-PERPETUAL":
                        total_oi = item.get("open_interest", 0)
                        btc_price = item.get("mark_price", 0)
                        funding = item.get("funding_8h", 0)

                        details = {
                            "btc_price": btc_price,
                            "perpetual_oi": total_oi,
                            "funding_8h": funding
                        }

                        # Check for extreme funding (liquidation signal)
                        if abs(funding) > 0.0005:  # >0.05% per 8hr
                            score += min(0.5, abs(funding) / 0.001)

                        break

                # Track OI changes
                if total_oi > 0:
                    self.oi_history.append((time.time(), total_oi))

                    if len(self.oi_history) >= 2:
                        prev_ts, prev_oi = self.oi_history[-2]
                        oi_change_pct = (total_oi - prev_oi) / prev_oi if prev_oi > 0 else 0
                        details["oi_change_pct"] = oi_change_pct

                        # Rapid OI drop = cascade in progress
                        if oi_change_pct < -0.03:
                            score += min(0.5, abs(oi_change_pct) * 10)
                        # Rapid OI increase = leverage building
                        elif oi_change_pct > 0.05:
                            score += min(0.3, oi_change_pct * 5)
            else:
                healthy = False
                source = "deribit_failed"

        except Exception as e:
            log.debug(f"Crypto cascade error: {e}")
            healthy = False

        score = min(1.0, score)
        self.last_value = score

        return ComponentScore(
            name="crypto_cascade",
            raw_value=score,
            weight=DEFAULT_WEIGHTS["crypto_cascade"],
            weighted_value=score * DEFAULT_WEIGHTS["crypto_cascade"],
            source=source,
            healthy=healthy,
            details=details
        )


class PremarketGap(ComponentFetcher):
    """
    Gap/Move Analysis.
    Uses previous day's open-to-close move as volatility indicator.
    Large daily ranges signal potential for continued moves.
    """

    def fetch(self) -> ComponentScore:
        score = 0.0
        details = {}
        source = "polygon_prev"
        healthy = True

        api_key = os.environ.get("POLYGON_API_KEY", "")
        if api_key:
            try:
                # Get SPY previous day data
                data = self._get(
                    "https://api.polygon.io/v2/aggs/ticker/SPY/prev",
                    params={"apiKey": api_key}
                )

                if data and data.get("results"):
                    result = data["results"][0]
                    open_price = result.get("o", 0)
                    high_price = result.get("h", 0)
                    low_price = result.get("l", 0)
                    close_price = result.get("c", 0)

                    if open_price > 0 and close_price > 0:
                        # Calculate daily move and range
                        daily_move = (close_price - open_price) / open_price
                        daily_range = (high_price - low_price) / close_price

                        details = {
                            "prev_open": round(open_price, 2),
                            "prev_high": round(high_price, 2),
                            "prev_low": round(low_price, 2),
                            "prev_close": round(close_price, 2),
                            "daily_move_pct": round(daily_move * 100, 2),
                            "daily_range_pct": round(daily_range * 100, 2)
                        }

                        # Score based on daily range (volatility indicator)
                        range_pct = abs(daily_range)
                        if range_pct > 0.025:  # >2.5% range
                            score = 1.0
                        elif range_pct > 0.018:  # >1.8% range
                            score = 0.7
                        elif range_pct > 0.012:  # >1.2% range
                            score = 0.4
                        elif range_pct > 0.008:  # >0.8% range
                            score = 0.2

                        details["move_direction"] = "up" if daily_move > 0 else "down"
                        details["score_reason"] = f"{range_pct*100:.2f}% daily range"
                else:
                    healthy = False
                    details["error"] = "No prev data"

            except Exception as e:
                log.debug(f"Premarket gap error: {e}")
                healthy = False
                details["error"] = str(e)
        else:
            healthy = False
            source = "no_api_key"

        self.last_value = score

        return ComponentScore(
            name="premarket_gap",
            raw_value=score,
            weight=DEFAULT_WEIGHTS["premarket_gap"],
            weighted_value=score * DEFAULT_WEIGHTS["premarket_gap"],
            source=source,
            healthy=healthy,
            details=details
        )


class EventProximity(ComponentFetcher):
    """
    Event Proximity Detection.
    FOMC/CPI/NFP within 30 min = +20, within 2hr = +10.
    """

    # Key market-moving events (updated regularly)
    EVENTS = [
        {"name": "NFP", "dates": ["2026-02-07", "2026-03-07", "2026-04-04"]},
        {"name": "CPI", "dates": ["2026-02-13", "2026-03-12", "2026-04-10"]},
        {"name": "FOMC", "dates": ["2026-03-19", "2026-05-07", "2026-06-18"]},
        {"name": "GDP", "dates": ["2026-02-27", "2026-03-27"]},
        {"name": "PCE", "dates": ["2026-02-28", "2026-03-28"]},
    ]

    # Events typically release at 8:30 AM ET (13:30 UTC) or 2:00 PM ET (19:00 UTC for FOMC)
    EVENT_TIMES = {
        "NFP": "13:30",
        "CPI": "13:30",
        "GDP": "13:30",
        "PCE": "13:30",
        "FOMC": "19:00",
    }

    def fetch(self) -> ComponentScore:
        score = 0.0
        details = {}
        source = "calendar"
        healthy = True
        events_soon = []

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        for event in self.EVENTS:
            event_name = event["name"]
            event_time_str = self.EVENT_TIMES.get(event_name, "13:30")

            for date_str in event["dates"]:
                try:
                    event_datetime = datetime.strptime(
                        f"{date_str} {event_time_str}",
                        "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=timezone.utc)

                    time_diff = (event_datetime - now).total_seconds()
                    minutes_until = time_diff / 60

                    if -30 <= minutes_until <= 30:  # Within 30 min
                        score = max(score, 1.0)  # Full score
                        events_soon.append({
                            "name": event_name,
                            "minutes_until": int(minutes_until),
                            "datetime": event_datetime.isoformat()
                        })
                    elif 30 < minutes_until <= 120:  # Within 2hr
                        score = max(score, 0.5)
                        events_soon.append({
                            "name": event_name,
                            "minutes_until": int(minutes_until),
                            "datetime": event_datetime.isoformat()
                        })
                    elif 120 < minutes_until <= 1440:  # Within 24hr
                        score = max(score, 0.2)
                        events_soon.append({
                            "name": event_name,
                            "minutes_until": int(minutes_until),
                            "datetime": event_datetime.isoformat()
                        })

                except ValueError:
                    continue

        details = {"events_soon": events_soon}
        self.last_value = score

        return ComponentScore(
            name="event_proximity",
            raw_value=score,
            weight=DEFAULT_WEIGHTS["event_proximity"],
            weighted_value=score * DEFAULT_WEIGHTS["event_proximity"],
            source=source,
            healthy=healthy,
            details=details
        )


class CrossAssetDivergence(ComponentFetcher):
    """
    Cross-Asset Divergence Detection.
    If SPY, TLT, GLD, VIX all moving same direction = regime shift signal.
    Uses previous day's moves to identify correlated price action.
    """

    def fetch(self) -> ComponentScore:
        score = 0.0
        details = {}
        source = "polygon_prev"
        healthy = True

        api_key = os.environ.get("POLYGON_API_KEY", "")
        if api_key:
            try:
                tickers = ["SPY", "TLT", "GLD"]
                changes = {}

                for ticker in tickers:
                    data = self._get(
                        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev",
                        params={"apiKey": api_key}
                    )

                    if data and data.get("results"):
                        result = data["results"][0]
                        open_price = result.get("o", 0)
                        close_price = result.get("c", 0)
                        if open_price > 0:
                            change_pct = (close_price - open_price) / open_price
                            changes[ticker] = change_pct

                # Get VIX direction
                vix_data = self._get(
                    "https://api.polygon.io/v2/aggs/ticker/I:VIX/prev",
                    params={"apiKey": api_key}
                )

                if vix_data and vix_data.get("results"):
                    result = vix_data["results"][0]
                    vix_open = result.get("o", 20)
                    vix_close = result.get("c", 20)
                    if vix_open > 0:
                        changes["VIX"] = (vix_close - vix_open) / vix_open

                details = {"changes": {k: round(v * 100, 2) for k, v in changes.items()}}

                if len(changes) >= 3:
                    # Check for correlated moves (threshold: 0.1% = 0.001)
                    directions = [1 if v > 0.001 else (-1 if v < -0.001 else 0) for v in changes.values()]

                    # Count how many are moving together
                    positive = sum(1 for d in directions if d > 0)
                    negative = sum(1 for d in directions if d < 0)

                    # If 3+ assets moving same direction strongly
                    max_aligned = max(positive, negative)
                    if max_aligned >= 3:
                        # Calculate magnitude of moves
                        avg_magnitude = sum(abs(v) for v in changes.values()) / len(changes)
                        score = min(1.0, (max_aligned / 4) * (avg_magnitude / 0.01))
                        details["alignment"] = "risk_off" if negative > positive else "risk_on"

                    details["up_count"] = positive
                    details["down_count"] = negative
                    healthy = True
                else:
                    healthy = len(changes) > 0
                    details["error"] = f"Only {len(changes)} assets reporting"

            except Exception as e:
                log.debug(f"Cross-asset error: {e}")
                healthy = False
                details["error"] = str(e)
        else:
            healthy = False
            source = "no_api_key"

        self.last_value = score

        return ComponentScore(
            name="cross_asset",
            raw_value=score,
            weight=DEFAULT_WEIGHTS["cross_asset"],
            weighted_value=score * DEFAULT_WEIGHTS["cross_asset"],
            source=source,
            healthy=healthy,
            details=details
        )


class VolumeSurge(ComponentFetcher):
    """
    Volume Surge Detection.
    Uses previous day's volume vs 20-day average as volatility indicator.
    High previous-day volume often precedes continued volatility.
    """

    def fetch(self) -> ComponentScore:
        score = 0.0
        details = {}
        source = "polygon_prev"
        healthy = True

        api_key = os.environ.get("POLYGON_API_KEY", "")
        if api_key:
            try:
                # Use prev endpoint (free tier compatible)
                data = self._get(
                    "https://api.polygon.io/v2/aggs/ticker/SPY/prev",
                    params={"apiKey": api_key}
                )

                if data and data.get("results"):
                    result = data["results"][0]
                    volume = result.get("v", 0)
                    avg_volume = 80_000_000  # Approximate 20-day average for SPY

                    vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0

                    # Also check the price range as volatility indicator
                    high = result.get("h", 0)
                    low = result.get("l", 0)
                    close = result.get("c", 0)
                    range_pct = ((high - low) / close * 100) if close > 0 else 0

                    details = {
                        "prev_volume": volume,
                        "avg_volume": avg_volume,
                        "vol_ratio": round(vol_ratio, 2),
                        "prev_range_pct": round(range_pct, 2),
                        "prev_high": high,
                        "prev_low": low,
                        "prev_close": close
                    }

                    # Score based on volume + range (both indicate volatility)
                    if vol_ratio > 3.0 or range_pct > 2.5:
                        score = 1.0
                    elif vol_ratio > 2.0 or range_pct > 2.0:
                        score = 0.6
                    elif vol_ratio > 1.5 or range_pct > 1.5:
                        score = 0.3
                    elif vol_ratio > 1.2 or range_pct > 1.0:
                        score = 0.15
                else:
                    healthy = False
                    details["error"] = "No prev data"

            except Exception as e:
                log.debug(f"Volume surge error: {e}")
                healthy = False
                details["error"] = str(e)
        else:
            healthy = False
            source = "no_api_key"

        self.last_value = score

        return ComponentScore(
            name="volume_surge",
            raw_value=score,
            weight=DEFAULT_WEIGHTS["volume_surge"],
            weighted_value=score * DEFAULT_WEIGHTS["volume_surge"],
            source=source,
            healthy=healthy,
            details=details
        )


class BreadthCollapse(ComponentFetcher):
    """
    Market Breadth Collapse Detection.
    Uses previous day's sector ETF moves as breadth indicator.
    If most sectors moved same direction strongly = breadth collapse signal.
    """

    # Top 5 sector ETFs by AUM (reduced from 10 to stay within API rate limits)
    SECTOR_ETFS = ["XLK", "XLF", "XLV", "XLY", "XLE"]

    def fetch(self) -> ComponentScore:
        score = 0.0
        details = {}
        source = "polygon_prev"
        healthy = True

        api_key = os.environ.get("POLYGON_API_KEY", "")
        if api_key:
            try:
                # Get previous day data for sector ETFs
                up_count = 0
                down_count = 0
                changes = {}

                for etf in self.SECTOR_ETFS:
                    data = self._get(
                        f"https://api.polygon.io/v2/aggs/ticker/{etf}/prev",
                        params={"apiKey": api_key}
                    )

                    if data and data.get("results"):
                        result = data["results"][0]
                        open_price = result.get("o", 0)
                        close_price = result.get("c", 0)

                        if open_price > 0:
                            change_pct = ((close_price - open_price) / open_price) * 100
                            changes[etf] = change_pct

                            if change_pct > 0.1:  # >0.1% up
                                up_count += 1
                            elif change_pct < -0.1:  # >0.1% down
                                down_count += 1

                total = up_count + down_count
                if total >= 3:  # Need at least 3 sectors showing significant moves
                    max_side = max(up_count, down_count)
                    breadth_ratio = max_side / len(self.SECTOR_ETFS)

                    details = {
                        "up_count": up_count,
                        "down_count": down_count,
                        "total_reporting": len(changes),
                        "breadth_ratio": round(breadth_ratio, 2),
                        "sector_changes": {k: round(v, 2) for k, v in changes.items()}
                    }

                    # Score if one side dominates (>70% same direction)
                    if breadth_ratio > 0.70:
                        score = min(1.0, (breadth_ratio - 0.70) / 0.20)
                        details["collapse_direction"] = "down" if down_count > up_count else "up"
                    elif breadth_ratio > 0.60:
                        score = 0.3
                        details["collapse_direction"] = "down" if down_count > up_count else "up"

                    healthy = True
                else:
                    healthy = len(changes) > 0  # At least some data came through
                    details["error"] = f"Only {total} sectors showing significant moves"
                    details["sector_changes"] = {k: round(v, 2) for k, v in changes.items()}

            except Exception as e:
                log.debug(f"Breadth collapse error: {e}")
                healthy = False
                details["error"] = str(e)
        else:
            healthy = False
            source = "no_api_key"

        self.last_value = score

        return ComponentScore(
            name="breadth",
            raw_value=score,
            weight=DEFAULT_WEIGHTS["breadth"],
            weighted_value=score * DEFAULT_WEIGHTS["breadth"],
            source=source,
            healthy=healthy,
            details=details
        )


# ═══════════════════════════════════════════════════════════════
#  BLOWUP PROBABILITY ENGINE
# ═══════════════════════════════════════════════════════════════

class BlowupDetector:
    """
    Main blowup probability engine.
    Synthesizes all components into a single score every 60 seconds.
    """

    def __init__(self):
        # Initialize component fetchers
        self.components = {
            "vix_inversion": VIXTermStructure(),
            "flow_imbalance": OptionsFlowImbalance(),
            "crypto_cascade": CryptoCascade(),
            "premarket_gap": PremarketGap(),
            "event_proximity": EventProximity(),
            "cross_asset": CrossAssetDivergence(),
            "volume_surge": VolumeSurge(),
            "breadth": BreadthCollapse(),
        }

        # Load weights from file or use defaults
        self.weights = self._load_weights()

        # History tracking
        self.score_history = deque(maxlen=100)  # Last 100 scores
        self.last_result: Optional[BlowupResult] = None

        # Initialize SQLite for history
        self._init_db()

    def _load_weights(self) -> dict:
        """Load weights from file or return defaults."""
        try:
            if WEIGHTS_FILE.exists():
                with open(WEIGHTS_FILE) as f:
                    loaded = json.load(f)
                    # Merge with defaults in case new components added
                    weights = DEFAULT_WEIGHTS.copy()
                    weights.update(loaded)
                    return weights
        except Exception as e:
            log.warning(f"Could not load weights file: {e}")
        return DEFAULT_WEIGHTS.copy()

    def save_weights(self, weights: dict):
        """Save weights to file."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(WEIGHTS_FILE, 'w') as f:
                json.dump(weights, f, indent=2)
            self.weights = weights
            log.info(f"Weights saved: {weights}")
        except Exception as e:
            log.error(f"Could not save weights: {e}")

    def reload_weights(self):
        """Hot reload weights from file."""
        self.weights = self._load_weights()
        log.info(f"Weights reloaded: {self.weights}")

    def _init_db(self):
        """Initialize SQLite database for history tracking."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(HISTORY_DB))
            cursor = conn.cursor()

            # Blowup score history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blowup_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    blowup_score INTEGER,
                    direction TEXT,
                    regime TEXT,
                    confidence REAL,
                    triggers TEXT,
                    recommendation TEXT,
                    components TEXT,
                    spy_price REAL,
                    spy_30min_move REAL
                )
            """)

            # Signal accuracy tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signal_accuracy (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    max_spy_range REAL,
                    blowup_score_at_max INTEGER,
                    direction_correct INTEGER,
                    triggers_active TEXT,
                    precision REAL,
                    recall REAL
                )
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Database init error: {e}")

    def _save_to_history(self, result: BlowupResult, spy_price: float = None):
        """Save result to database."""
        try:
            conn = sqlite3.connect(str(HISTORY_DB))
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO blowup_history
                (timestamp, blowup_score, direction, regime, confidence, triggers, recommendation, components, spy_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.timestamp,
                result.blowup_probability,
                result.direction,
                result.regime,
                result.confidence,
                json.dumps(result.triggers),
                result.recommendation,
                json.dumps(result.components),
                spy_price
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"History save error: {e}")

    def calculate(self) -> BlowupResult:
        """
        Calculate the blowup probability score.
        This is the main method called every 60 seconds.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        component_scores: List[ComponentScore] = []
        triggers: List[str] = []

        # Fetch all component scores
        for name, fetcher in self.components.items():
            try:
                score = fetcher.fetch()
                # Update weight from current config
                score.weight = self.weights.get(name, DEFAULT_WEIGHTS.get(name, 0.1))
                score.weighted_value = score.raw_value * score.weight
                component_scores.append(score)

                # Track triggers (components contributing significantly)
                if score.raw_value > 0.3:
                    triggers.append(f"{name}:{score.raw_value:.2f}")

            except Exception as e:
                log.error(f"Component {name} error: {e}")
                component_scores.append(ComponentScore(
                    name=name,
                    raw_value=0.0,
                    weight=self.weights.get(name, 0.1),
                    weighted_value=0.0,
                    source="error",
                    healthy=False,
                    details={"error": str(e)}
                ))

        # Calculate total blowup score
        total_weighted = sum(cs.weighted_value for cs in component_scores)
        blowup_probability = int(min(100, total_weighted * 100))

        # Calculate confidence based on data health
        healthy_count = sum(1 for cs in component_scores if cs.healthy)
        confidence = healthy_count / len(component_scores)

        # Determine direction
        direction = self._determine_direction(component_scores)

        # Determine regime
        regime = self._determine_regime(component_scores, direction)

        # Determine recommendation
        recommendation = self._determine_recommendation(blowup_probability, direction, confidence)

        # Get upcoming events
        events_next_30min = self._get_events_next_30min(component_scores)

        # Build result
        result = BlowupResult(
            blowup_probability=blowup_probability,
            direction=direction.value,
            regime=regime.value,
            confidence=round(confidence, 2),
            triggers=triggers,
            recommendation=recommendation.value,
            events_next_30min=events_next_30min,
            timestamp=timestamp,
            components=[asdict(cs) for cs in component_scores]
        )

        # Log the calculation
        component_breakdown = " + ".join([
            f"{cs.name}({cs.raw_value:.2f}*{cs.weight:.2f})"
            for cs in component_scores if cs.raw_value > 0
        ])
        log.info(f"BLOWUP: {blowup_probability} = {component_breakdown}")

        # Save to history
        self.score_history.append(result)
        self._save_to_history(result)
        self.last_result = result

        return result

    def _determine_direction(self, components: List[ComponentScore]) -> Direction:
        """Determine market direction from component signals."""
        bullish_signals = 0
        bearish_signals = 0

        for cs in components:
            details = cs.details

            # VIX inversion is bearish
            if cs.name == "vix_inversion" and cs.raw_value > 0.3:
                bearish_signals += 1

            # Flow imbalance direction
            if cs.name == "flow_imbalance":
                hint = details.get("direction_hint", "neutral")
                if hint == "bearish":
                    bearish_signals += 1
                elif hint == "bullish":
                    bullish_signals += 1

            # Cross-asset alignment
            if cs.name == "cross_asset":
                alignment = details.get("alignment", "")
                if alignment == "risk_off":
                    bearish_signals += 1
                elif alignment == "risk_on":
                    bullish_signals += 1

            # Breadth collapse direction
            if cs.name == "breadth":
                collapse_dir = details.get("collapse_direction", "")
                if collapse_dir == "down":
                    bearish_signals += 1
                elif collapse_dir == "up":
                    bullish_signals += 1

        if bearish_signals >= 3:
            return Direction.BEARISH
        elif bullish_signals >= 3:
            return Direction.BULLISH
        else:
            return Direction.NEUTRAL

    def _determine_regime(self, components: List[ComponentScore], direction: Direction) -> BlowupRegime:
        """Determine market regime from signals."""
        # Get VIX level if available
        flow_component = next((c for c in components if c.name == "flow_imbalance"), None)
        vix = flow_component.details.get("vix", 20) if flow_component else 20

        # Get cross-asset alignment
        cross_component = next((c for c in components if c.name == "cross_asset"), None)
        alignment = cross_component.details.get("alignment", "") if cross_component else ""

        if vix > 25 or direction == Direction.BEARISH:
            return BlowupRegime.RISK_OFF
        elif vix < 18 and direction == Direction.BULLISH:
            return BlowupRegime.RISK_ON
        elif alignment:
            return BlowupRegime.TRANSITION
        else:
            return BlowupRegime.UNKNOWN

    def _determine_recommendation(self, score: int, direction: Direction, confidence: float) -> Recommendation:
        """Determine trading recommendation based on score and direction."""
        if confidence < 0.5:
            return Recommendation.NO_TRADE

        if score < THRESHOLDS["calm"]:  # 0-30
            return Recommendation.SCALP_ONLY
        elif score < THRESHOLDS["elevated"]:  # 30-50
            return Recommendation.SCALP_ONLY
        elif score < THRESHOLDS["high"]:  # 50-70
            return Recommendation.STRADDLE
        else:  # 70-100
            if direction == Direction.BEARISH:
                return Recommendation.DIRECTIONAL_PUT
            elif direction == Direction.BULLISH:
                return Recommendation.DIRECTIONAL_CALL
            else:
                return Recommendation.STRADDLE

    def _get_events_next_30min(self, components: List[ComponentScore]) -> List[dict]:
        """Extract upcoming events from event proximity component."""
        event_component = next((c for c in components if c.name == "event_proximity"), None)
        if event_component:
            events = event_component.details.get("events_soon", [])
            return [e for e in events if -30 <= e.get("minutes_until", 999) <= 30]
        return []

    def get_recent_scores(self, count: int = 10) -> List[dict]:
        """Get recent blowup scores for trend display."""
        recent = list(self.score_history)[-count:]
        return [
            {
                "timestamp": r.timestamp,
                "score": r.blowup_probability,
                "direction": r.direction
            }
            for r in recent
        ]

    def get_last_result(self) -> Optional[BlowupResult]:
        """Get the most recent calculation result."""
        return self.last_result


# ═══════════════════════════════════════════════════════════════
#  SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════

_detector_instance: Optional[BlowupDetector] = None

def get_blowup_detector() -> BlowupDetector:
    """Get or create the singleton BlowupDetector instance."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = BlowupDetector()
    return _detector_instance


# ═══════════════════════════════════════════════════════════════
#  CLI FOR TESTING
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    detector = get_blowup_detector()
    result = detector.calculate()

    print("\n" + "=" * 60)
    print("BLOWUP PROBABILITY ENGINE - TEST RUN")
    print("=" * 60)
    print(result.to_json())
