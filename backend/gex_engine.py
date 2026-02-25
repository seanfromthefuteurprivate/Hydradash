"""
HYDRA GEX (Gamma Exposure) Engine v1.0

Computes real-time dealer gamma exposure from SPY options chain.
This is the single most important variable for 0DTE options trading.

GEX tells you how dealers MUST hedge:
- Positive GEX: Dealers buy dips, sell rips (mean-reverting, low vol)
- Negative GEX: Dealers sell into selling, buy into buying (trending, high vol)

Outputs:
- Total GEX in dollars
- GEX regime (POSITIVE/NEGATIVE)
- Gamma flip point (price where dealer behavior inverts)
- Charm flow (delta decay per hour - critical for 0DTE)
- Vanna exposure (IV sensitivity)
- Key support/resistance levels from high-GEX strikes
"""

import os
import math
import logging
import sqlite3
from datetime import datetime, timezone, time, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from pathlib import Path
from enum import Enum

log = logging.getLogger("HYDRA.GEX")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Data directory
DATA_DIR = Path(__file__).parent.parent / "data"
GEX_DB = DATA_DIR / "gex_history.db"


class GEXRegime(Enum):
    POSITIVE = "POSITIVE"      # Mean-reverting, dealers suppress moves
    NEGATIVE = "NEGATIVE"      # Trending, dealers amplify moves
    NEUTRAL = "NEUTRAL"        # Near flip point, regime uncertain
    UNKNOWN = "UNKNOWN"


class RefreshInterval(Enum):
    REALTIME = 30      # 30 seconds - final hour
    FAST = 60          # 1 minute - open, power hour
    NORMAL = 300       # 5 minutes - mid-day
    SLOW = 900         # 15 minutes - pre-market


# GEX thresholds for SPY (in dollars)
GEX_THRESHOLDS = {
    "extreme_positive": 1_000_000_000,    # $1B - strong pin
    "high_positive": 500_000_000,          # $500M - mean reversion likely
    "neutral_low": -200_000_000,           # Neutral band
    "neutral_high": 200_000_000,
    "negative": -200_000_000,              # Trending possible
    "extreme_negative": -500_000_000,      # High volatility regime
}


@dataclass
class GEXSnapshot:
    """Complete GEX state at a point in time."""
    timestamp: str
    spot_price: float
    total_gex: float
    call_gex: float
    put_gex: float
    flip_point: Optional[float]
    flip_distance_pct: float
    regime: str
    charm_flow_per_hour: float
    vanna_exposure: float
    key_support: List[float]
    key_resistance: List[float]
    magnets: List[float]
    refresh_interval_seconds: int
    options_count: int

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_gex_per_strike(
    gamma: float,
    open_interest: int,
    spot_price: float,
    is_call: bool
) -> float:
    """
    Calculate Gamma Exposure for a single strike.

    Formula: GEX = Gamma × OI × 100 × Spot² × Direction
    Direction: +1 for calls, -1 for puts (dealer positioning convention)

    Returns: GEX in dollars (delta-dollars that must be hedged per $1 move)
    """
    if gamma <= 0 or open_interest <= 0 or spot_price <= 0:
        return 0.0

    contract_multiplier = 100  # SPY options = 100 shares per contract
    direction = 1 if is_call else -1

    gex = gamma * open_interest * contract_multiplier * (spot_price ** 2) * direction

    return gex


def calculate_charm(
    gamma: float,
    iv: float,
    spot: float,
    strike: float,
    time_to_expiry_years: float
) -> float:
    """
    Calculate charm (delta decay rate) for an option.
    Charm = dDelta/dTime

    For 0DTE options, charm is extreme near ATM strikes.
    """
    if time_to_expiry_years <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return 0.0

    try:
        tau = time_to_expiry_years
        sigma = iv

        d1 = (math.log(spot / strike) + (0.05 + sigma**2 / 2) * tau) / (sigma * math.sqrt(tau))

        # Simplified charm formula
        charm = -gamma * (0.05 - d1 * sigma / (2 * tau))

        return charm
    except (ValueError, ZeroDivisionError):
        return 0.0


def calculate_vanna(
    vega: float,
    spot: float,
    strike: float,
    iv: float,
    time_to_expiry_years: float
) -> float:
    """
    Calculate vanna (delta sensitivity to IV changes).
    Vanna = dDelta/dIV

    When IV changes, delta changes, forcing dealers to re-hedge.
    """
    if time_to_expiry_years <= 0 or iv <= 0 or spot <= 0 or vega == 0:
        return 0.0

    try:
        tau = time_to_expiry_years
        sigma = iv

        d1 = (math.log(spot / strike) + (0.05 + sigma**2 / 2) * tau) / (sigma * math.sqrt(tau))

        vanna = vega * d1 / (spot * sigma * math.sqrt(tau))

        return vanna
    except (ValueError, ZeroDivisionError):
        return 0.0


def find_gamma_flip_point(gex_by_strike: Dict[float, float], spot_price: float) -> Optional[float]:
    """
    Find the price level where cumulative GEX flips from positive to negative.
    Uses linear interpolation between strikes where sign changes.
    """
    if not gex_by_strike:
        return None

    strikes = sorted(gex_by_strike.keys())

    # Calculate cumulative GEX from lowest strike upward
    cumulative_gex = {}
    running_total = 0

    for strike in strikes:
        running_total += gex_by_strike[strike]
        cumulative_gex[strike] = running_total

    # Find where sign flips
    flip_points = []

    for i in range(len(strikes) - 1):
        s1, s2 = strikes[i], strikes[i + 1]
        g1, g2 = cumulative_gex[s1], cumulative_gex[s2]

        # Check for sign change
        if g1 * g2 < 0:
            # Linear interpolation
            flip = s1 + (s2 - s1) * abs(g1) / (abs(g1) + abs(g2))
            flip_points.append(flip)

    # Return flip point closest to current spot
    if flip_points:
        return min(flip_points, key=lambda x: abs(x - spot_price))

    return None


def identify_key_levels(
    gex_by_strike: Dict[float, float],
    spot_price: float,
    top_n: int = 5
) -> Dict[str, List[float]]:
    """
    Identify key GEX levels that act as support/resistance.
    High positive GEX = price magnet (dealers defend)
    High negative GEX = volatility trigger
    """
    if not gex_by_strike:
        return {"support": [], "resistance": [], "magnets": []}

    # Sort by absolute GEX magnitude
    sorted_strikes = sorted(gex_by_strike.items(), key=lambda x: abs(x[1]), reverse=True)

    support = []
    resistance = []
    magnets = []

    for strike, gex in sorted_strikes[:top_n * 2]:
        if gex > 0:  # Positive GEX = magnet
            magnets.append(strike)
            if strike < spot_price:
                support.append(strike)
            else:
                resistance.append(strike)

    return {
        "support": sorted(support, reverse=True)[:top_n],
        "resistance": sorted(resistance)[:top_n],
        "magnets": sorted(magnets, key=lambda x: abs(x - spot_price))[:top_n]
    }


def get_refresh_interval(
    current_time: datetime,
    total_gex: float,
    flip_point_distance: float
) -> RefreshInterval:
    """
    Determine optimal refresh interval based on market conditions.
    """
    t = current_time.time()

    # Time-based baseline
    if t < time(9, 30):
        baseline = RefreshInterval.SLOW
    elif t < time(10, 0):
        baseline = RefreshInterval.FAST
    elif t < time(14, 0):
        baseline = RefreshInterval.NORMAL
    elif t < time(15, 0):
        baseline = RefreshInterval.FAST
    else:
        baseline = RefreshInterval.REALTIME

    # Near flip point = increase frequency
    if flip_point_distance < 0.005:  # Within 0.5%
        return RefreshInterval.REALTIME

    # Extreme negative GEX = increase frequency
    if total_gex < GEX_THRESHOLDS["extreme_negative"]:
        return RefreshInterval(min(baseline.value, RefreshInterval.FAST.value))

    return baseline


def get_time_to_expiry_years() -> float:
    """Calculate time to expiry for 0DTE options (until 4:00 PM ET)."""
    now = datetime.now()
    market_close = datetime.combine(now.date(), time(16, 0))

    # If after market close, return small positive number
    if now >= market_close:
        return 1e-6

    time_remaining = (market_close - now).total_seconds()
    return max(time_remaining / (365.25 * 24 * 3600), 1e-6)


class GEXEngine:
    """
    Real-time GEX computation engine for HYDRA.

    Fetches SPY options chain from Polygon and computes:
    - Total dealer gamma exposure
    - Gamma flip point
    - Charm flow (delta decay)
    - Vanna exposure (IV sensitivity)
    - Key support/resistance levels
    """

    def __init__(self, polygon_api_key: str = None):
        self.api_key = polygon_api_key or os.environ.get("POLYGON_API_KEY", "")
        self.last_snapshot: Optional[GEXSnapshot] = None
        self.last_update: Optional[datetime] = None
        self.refresh_interval = RefreshInterval.NORMAL
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for GEX history."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(GEX_DB))
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gex_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    spot_price REAL,
                    total_gex REAL,
                    call_gex REAL,
                    put_gex REAL,
                    flip_point REAL,
                    regime TEXT,
                    charm_flow REAL,
                    vanna_exposure REAL
                )
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"GEX database init error: {e}")

    def _save_to_history(self, snapshot: GEXSnapshot):
        """Save snapshot to database."""
        try:
            conn = sqlite3.connect(str(GEX_DB))
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO gex_history
                (timestamp, spot_price, total_gex, call_gex, put_gex, flip_point, regime, charm_flow, vanna_exposure)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.timestamp,
                snapshot.spot_price,
                snapshot.total_gex,
                snapshot.call_gex,
                snapshot.put_gex,
                snapshot.flip_point,
                snapshot.regime,
                snapshot.charm_flow_per_hour,
                snapshot.vanna_exposure
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"GEX history save error: {e}")

    def _fetch_options_chain(self) -> List[dict]:
        """Fetch SPY options chain from Polygon."""
        if not HAS_REQUESTS or not self.api_key:
            log.warning("No requests library or API key for options chain")
            return []

        try:
            # Get 0DTE options
            today = datetime.now().strftime("%Y-%m-%d")

            url = "https://api.polygon.io/v3/snapshot/options/SPY"
            params = {
                "apiKey": self.api_key,
                "expiration_date": today,  # 0DTE only
                "limit": 250
            }

            all_results = []

            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                all_results.extend(data.get("results", []))

                # Handle pagination
                next_url = data.get("next_url")
                while next_url:
                    resp = requests.get(f"{next_url}&apiKey={self.api_key}", timeout=15)
                    if resp.status_code == 200:
                        data = resp.json()
                        all_results.extend(data.get("results", []))
                        next_url = data.get("next_url")
                    else:
                        break
            else:
                log.warning(f"Options chain fetch failed: {resp.status_code}")

            return all_results

        except Exception as e:
            log.error(f"Options chain fetch error: {e}")
            return []

    def _parse_option(self, raw: dict) -> dict:
        """Parse Polygon option snapshot into usable format."""
        details = raw.get("details", {})
        greeks = raw.get("greeks", {})
        underlying = raw.get("underlying_asset", {})

        return {
            "strike": details.get("strike_price", 0),
            "contract_type": details.get("contract_type", ""),
            "expiration": details.get("expiration_date", ""),
            "open_interest": raw.get("open_interest", 0),
            "gamma": greeks.get("gamma", 0),
            "delta": greeks.get("delta", 0),
            "theta": greeks.get("theta", 0),
            "vega": greeks.get("vega", 0),
            "iv": raw.get("implied_volatility", 0.3),
            "underlying_price": underlying.get("price", 0),
        }

    def calculate(self) -> GEXSnapshot:
        """
        Calculate complete GEX snapshot.
        This is the main method called by the background loop.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Fetch and parse options chain
        raw_options = self._fetch_options_chain()

        if not raw_options:
            # Return empty snapshot if no data
            log.warning("No options data available for GEX calculation")
            return GEXSnapshot(
                timestamp=timestamp,
                spot_price=0,
                total_gex=0,
                call_gex=0,
                put_gex=0,
                flip_point=None,
                flip_distance_pct=1.0,
                regime=GEXRegime.UNKNOWN.value,
                charm_flow_per_hour=0,
                vanna_exposure=0,
                key_support=[],
                key_resistance=[],
                magnets=[],
                refresh_interval_seconds=300,
                options_count=0
            )

        options = [self._parse_option(o) for o in raw_options]
        spot_price = options[0]["underlying_price"] if options else 0

        if spot_price <= 0:
            # Try to get spot from first valid option
            for opt in options:
                if opt["underlying_price"] > 0:
                    spot_price = opt["underlying_price"]
                    break

        # Calculate GEX for each strike
        total_gex = 0
        call_gex = 0
        put_gex = 0
        gex_by_strike: Dict[float, float] = {}

        total_charm = 0
        total_vanna = 0

        tau = get_time_to_expiry_years()

        for opt in options:
            if opt["strike"] <= 0 or opt["open_interest"] <= 0:
                continue

            is_call = opt["contract_type"] == "call"

            # Calculate GEX
            strike_gex = calculate_gex_per_strike(
                gamma=opt["gamma"],
                open_interest=opt["open_interest"],
                spot_price=spot_price,
                is_call=is_call
            )

            total_gex += strike_gex
            if is_call:
                call_gex += strike_gex
            else:
                put_gex += strike_gex

            # Aggregate by strike
            strike = opt["strike"]
            gex_by_strike[strike] = gex_by_strike.get(strike, 0) + strike_gex

            # Calculate charm
            charm = calculate_charm(
                gamma=opt["gamma"],
                iv=opt["iv"],
                spot=spot_price,
                strike=strike,
                time_to_expiry_years=tau
            )
            direction = 1 if is_call else -1
            total_charm += charm * opt["open_interest"] * 100 * direction

            # Calculate vanna
            vanna = calculate_vanna(
                vega=opt["vega"],
                spot=spot_price,
                strike=strike,
                iv=opt["iv"],
                time_to_expiry_years=tau
            )
            total_vanna += vanna * opt["open_interest"] * 100 * direction

        # Find gamma flip point
        flip_point = find_gamma_flip_point(gex_by_strike, spot_price)
        flip_distance_pct = abs(flip_point - spot_price) / spot_price if flip_point and spot_price > 0 else 1.0

        # Determine regime
        if total_gex > GEX_THRESHOLDS["high_positive"]:
            regime = GEXRegime.POSITIVE
        elif total_gex < GEX_THRESHOLDS["negative"]:
            regime = GEXRegime.NEGATIVE
        elif flip_distance_pct < 0.01:
            regime = GEXRegime.NEUTRAL
        elif total_gex > 0:
            regime = GEXRegime.POSITIVE
        else:
            regime = GEXRegime.NEGATIVE

        # Calculate charm flow per hour
        hours_remaining = tau * 365.25 * 24
        charm_per_hour = total_charm / hours_remaining if hours_remaining > 0 else 0

        # Identify key levels
        levels = identify_key_levels(gex_by_strike, spot_price)

        # Determine refresh interval
        self.refresh_interval = get_refresh_interval(
            datetime.now(),
            total_gex,
            flip_distance_pct
        )

        snapshot = GEXSnapshot(
            timestamp=timestamp,
            spot_price=round(spot_price, 2),
            total_gex=round(total_gex, 0),
            call_gex=round(call_gex, 0),
            put_gex=round(put_gex, 0),
            flip_point=round(flip_point, 2) if flip_point else None,
            flip_distance_pct=round(flip_distance_pct, 4),
            regime=regime.value,
            charm_flow_per_hour=round(charm_per_hour, 0),
            vanna_exposure=round(total_vanna, 0),
            key_support=levels["support"],
            key_resistance=levels["resistance"],
            magnets=levels["magnets"],
            refresh_interval_seconds=self.refresh_interval.value,
            options_count=len(options)
        )

        # Log summary
        log.info(
            f"GEX: {total_gex/1e9:.2f}B | Regime: {regime.value} | "
            f"Flip: {flip_point:.2f} ({flip_distance_pct*100:.1f}% away) | "
            f"Options: {len(options)}"
        )

        # Save to history
        self._save_to_history(snapshot)
        self.last_snapshot = snapshot
        self.last_update = datetime.now(timezone.utc)

        return snapshot

    def get_last_snapshot(self) -> Optional[GEXSnapshot]:
        """Get the most recent GEX snapshot."""
        return self.last_snapshot

    def should_refresh(self) -> bool:
        """Check if GEX should be recalculated."""
        if self.last_update is None:
            return True

        elapsed = (datetime.now(timezone.utc) - self.last_update).total_seconds()
        return elapsed >= self.refresh_interval.value

    def get_conviction_modifier(self, trade_direction: str) -> dict:
        """
        Get conviction modifier based on GEX regime.

        Args:
            trade_direction: "BULLISH" or "BEARISH"

        Returns:
            dict with modifier and reasoning
        """
        if not self.last_snapshot:
            return {"modifier": 0, "reason": "No GEX data"}

        gex = self.last_snapshot
        modifier = 0
        reasons = []

        # Regime alignment
        if gex.regime == "NEGATIVE":
            # Negative GEX = trending market, directional plays work
            modifier += 10
            reasons.append("Negative GEX favors directional trades")
        elif gex.regime == "POSITIVE" and abs(gex.total_gex) > GEX_THRESHOLDS["high_positive"]:
            # Strong positive GEX = mean reversion, directional plays struggle
            modifier -= 15
            reasons.append("High positive GEX suppresses directional moves")

        # Near flip point = explosive move possible
        if gex.flip_distance_pct < 0.005:
            modifier += 5
            reasons.append("Near gamma flip - explosive move possible")

        # Charm acceleration in final hour
        now = datetime.now().time()
        if now >= time(15, 0) and abs(gex.charm_flow_per_hour) > 5_000_000:
            modifier += 5
            reasons.append("High charm flow - accelerated moves into close")

        return {
            "modifier": modifier,
            "reasons": reasons,
            "regime": gex.regime,
            "flip_distance_pct": gex.flip_distance_pct
        }


# Singleton instance
_gex_engine: Optional[GEXEngine] = None


def get_gex_engine() -> GEXEngine:
    """Get or create the singleton GEX engine instance."""
    global _gex_engine
    if _gex_engine is None:
        _gex_engine = GEXEngine()
    return _gex_engine


# CLI for testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    engine = get_gex_engine()
    snapshot = engine.calculate()

    print("\n" + "=" * 60)
    print("GEX ENGINE - TEST RUN")
    print("=" * 60)
    print(f"Spot Price: ${snapshot.spot_price}")
    print(f"Total GEX: ${snapshot.total_gex/1e9:.3f}B")
    print(f"Call GEX: ${snapshot.call_gex/1e9:.3f}B")
    print(f"Put GEX: ${snapshot.put_gex/1e9:.3f}B")
    print(f"Regime: {snapshot.regime}")
    print(f"Flip Point: ${snapshot.flip_point} ({snapshot.flip_distance_pct*100:.2f}% away)")
    print(f"Charm Flow/Hour: ${snapshot.charm_flow_per_hour:,.0f}")
    print(f"Key Support: {snapshot.key_support}")
    print(f"Key Resistance: {snapshot.key_resistance}")
    print(f"Options Analyzed: {snapshot.options_count}")
