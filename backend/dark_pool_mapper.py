"""
HYDRA Dark Pool Level Mapper v1.0

Tracks institutional block trades to identify support/resistance levels.
Dark pool trades are identified by exchange=4 + trf_id field in Polygon data.

Outputs:
- Institutional support levels (large buy blocks)
- Institutional resistance levels (large sell blocks)
- VWAP clustering as fallback for institutional positioning
"""

import os
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict
from pathlib import Path
from collections import defaultdict

log = logging.getLogger("HYDRA.DARKPOOL")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Data directory
DATA_DIR = Path(__file__).parent.parent / "data"
DP_DB = DATA_DIR / "dark_pool_levels.db"

# Minimum block size to consider "institutional"
MIN_BLOCK_SIZE = 10000  # 10K shares
MIN_NOTIONAL = 500000   # $500K minimum notional value

# Price clustering granularity
PRICE_CLUSTER_SIZE = 0.50  # Round to nearest $0.50


@dataclass
class DarkPoolLevel:
    """A price level with significant institutional activity."""
    price: float
    volume: int
    notional: float
    trade_count: int
    side: str  # "BUY" or "SELL" or "UNKNOWN"
    strength: str  # "LOW", "MEDIUM", "HIGH", "VERY_HIGH"
    last_seen: str


@dataclass
class DarkPoolSnapshot:
    """Complete dark pool intelligence at a point in time."""
    timestamp: str
    ticker: str
    spot_price: float
    levels: List[dict]
    nearest_support: Optional[float]
    nearest_resistance: Optional[float]
    support_strength: str
    resistance_strength: str
    total_dark_volume: int
    total_dark_notional: float
    buy_volume: int
    sell_volume: int

    def to_dict(self) -> dict:
        return asdict(self)


def cluster_price(price: float) -> float:
    """Round price to cluster granularity."""
    return round(price / PRICE_CLUSTER_SIZE) * PRICE_CLUSTER_SIZE


def determine_side(price: float, bid: float, ask: float) -> str:
    """
    Determine trade side based on price relative to NBBO.
    - Price at/near ask = BUY (buyer initiated)
    - Price at/near bid = SELL (seller initiated)
    """
    if bid <= 0 or ask <= 0:
        return "UNKNOWN"

    mid = (bid + ask) / 2
    spread = ask - bid

    if spread <= 0:
        return "UNKNOWN"

    # If price is closer to ask, it's a buy
    if price >= mid + spread * 0.25:
        return "BUY"
    elif price <= mid - spread * 0.25:
        return "SELL"
    else:
        return "UNKNOWN"


def determine_strength(notional: float, trade_count: int) -> str:
    """Determine level strength based on notional value and trade count."""
    if notional >= 10_000_000 or trade_count >= 20:
        return "VERY_HIGH"
    elif notional >= 5_000_000 or trade_count >= 10:
        return "HIGH"
    elif notional >= 2_000_000 or trade_count >= 5:
        return "MEDIUM"
    else:
        return "LOW"


class DarkPoolMapper:
    """
    Tracks dark pool prints and builds institutional support/resistance levels.
    """

    def __init__(self, polygon_api_key: str = None):
        self.api_key = polygon_api_key or os.environ.get("POLYGON_API_KEY", "")
        self.last_snapshot: Optional[DarkPoolSnapshot] = None
        self.last_update: Optional[datetime] = None
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for dark pool levels."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(DP_DB))
            cursor = conn.cursor()

            # Track individual dark pool prints
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dark_pool_prints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    price REAL,
                    size INTEGER,
                    notional REAL,
                    side TEXT,
                    exchange INTEGER,
                    trf_id INTEGER
                )
            """)

            # Track aggregated levels
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dark_pool_levels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    price_level REAL,
                    total_volume INTEGER,
                    total_notional REAL,
                    trade_count INTEGER,
                    buy_volume INTEGER,
                    sell_volume INTEGER,
                    strength TEXT,
                    UNIQUE(date, ticker, price_level)
                )
            """)

            # Index for efficient lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_dp_prints_ticker_time
                ON dark_pool_prints(ticker, timestamp)
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Dark pool database init error: {e}")

    def _fetch_trades(self, ticker: str = "SPY", limit: int = 1000) -> List[dict]:
        """
        Fetch recent trades from Polygon.
        Filter for dark pool trades (exchange=4 + trf_id present).
        """
        if not HAS_REQUESTS or not self.api_key:
            return []

        try:
            url = f"https://api.polygon.io/v3/trades/{ticker}"
            params = {
                "apiKey": self.api_key,
                "limit": limit,
                "order": "desc",
                "sort": "timestamp"
            }

            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("results", [])
            else:
                log.warning(f"Trades fetch failed: {resp.status_code}")
                return []

        except Exception as e:
            log.error(f"Trades fetch error: {e}")
            return []

    def _fetch_nbbo(self, ticker: str = "SPY") -> dict:
        """Fetch current NBBO for side determination."""
        if not HAS_REQUESTS or not self.api_key:
            return {"bid": 0, "ask": 0}

        try:
            url = f"https://api.polygon.io/v3/quotes/{ticker}"
            params = {
                "apiKey": self.api_key,
                "limit": 1,
                "order": "desc"
            }

            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    return {
                        "bid": results[0].get("bid_price", 0),
                        "ask": results[0].get("ask_price", 0)
                    }
            return {"bid": 0, "ask": 0}

        except Exception as e:
            log.error(f"NBBO fetch error: {e}")
            return {"bid": 0, "ask": 0}

    def _fetch_spot_price(self, ticker: str = "SPY") -> float:
        """Fetch current spot price."""
        if not HAS_REQUESTS or not self.api_key:
            return 0

        try:
            url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev"
            params = {"apiKey": self.api_key}

            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    return results[0].get("c", 0)
            return 0

        except Exception as e:
            log.error(f"Spot price fetch error: {e}")
            return 0

    def _is_dark_pool_trade(self, trade: dict) -> bool:
        """Check if trade is from dark pool (exchange 4 + trf_id)."""
        return trade.get("exchange") == 4 and "trf_id" in trade

    def _filter_block_trades(self, trades: List[dict], spot_price: float) -> List[dict]:
        """Filter for institutional block trades."""
        blocks = []

        for trade in trades:
            # Check if dark pool
            if not self._is_dark_pool_trade(trade):
                continue

            size = trade.get("size", 0)
            price = trade.get("price", 0)

            if size < MIN_BLOCK_SIZE:
                continue

            notional = size * price
            if notional < MIN_NOTIONAL:
                continue

            blocks.append({
                "price": price,
                "size": size,
                "notional": notional,
                "timestamp": trade.get("participant_timestamp", 0),
                "conditions": trade.get("conditions", []),
                "trf_id": trade.get("trf_id")
            })

        return blocks

    def calculate(self, ticker: str = "SPY") -> DarkPoolSnapshot:
        """
        Calculate dark pool levels from recent trades.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Fetch data
        trades = self._fetch_trades(ticker, limit=5000)
        nbbo = self._fetch_nbbo(ticker)
        spot_price = self._fetch_spot_price(ticker)

        if spot_price <= 0 and nbbo["bid"] > 0:
            spot_price = (nbbo["bid"] + nbbo["ask"]) / 2

        # Filter for dark pool block trades
        blocks = self._filter_block_trades(trades, spot_price)

        # Cluster by price level
        levels: Dict[float, dict] = defaultdict(lambda: {
            "volume": 0,
            "notional": 0,
            "trade_count": 0,
            "buy_volume": 0,
            "sell_volume": 0,
            "last_seen": ""
        })

        total_dark_volume = 0
        total_dark_notional = 0
        total_buy_volume = 0
        total_sell_volume = 0

        for block in blocks:
            price_level = cluster_price(block["price"])
            side = determine_side(block["price"], nbbo["bid"], nbbo["ask"])

            levels[price_level]["volume"] += block["size"]
            levels[price_level]["notional"] += block["notional"]
            levels[price_level]["trade_count"] += 1

            if side == "BUY":
                levels[price_level]["buy_volume"] += block["size"]
                total_buy_volume += block["size"]
            elif side == "SELL":
                levels[price_level]["sell_volume"] += block["size"]
                total_sell_volume += block["size"]

            total_dark_volume += block["size"]
            total_dark_notional += block["notional"]

            # Track last seen
            if block["timestamp"]:
                levels[price_level]["last_seen"] = str(block["timestamp"])

        # Build level objects
        level_objects = []
        for price, data in levels.items():
            # Determine side based on buy vs sell volume
            if data["buy_volume"] > data["sell_volume"] * 1.5:
                side = "BUY"
            elif data["sell_volume"] > data["buy_volume"] * 1.5:
                side = "SELL"
            else:
                side = "UNKNOWN"

            strength = determine_strength(data["notional"], data["trade_count"])

            level_objects.append(DarkPoolLevel(
                price=price,
                volume=data["volume"],
                notional=data["notional"],
                trade_count=data["trade_count"],
                side=side,
                strength=strength,
                last_seen=data["last_seen"]
            ))

        # Sort by notional value
        level_objects.sort(key=lambda x: x.notional, reverse=True)

        # Find nearest support and resistance
        support_levels = [l for l in level_objects if l.price < spot_price and l.side in ("BUY", "UNKNOWN")]
        resistance_levels = [l for l in level_objects if l.price > spot_price and l.side in ("SELL", "UNKNOWN")]

        # Sort support by proximity (highest first), resistance by proximity (lowest first)
        support_levels.sort(key=lambda x: x.price, reverse=True)
        resistance_levels.sort(key=lambda x: x.price)

        nearest_support = support_levels[0].price if support_levels else None
        nearest_resistance = resistance_levels[0].price if resistance_levels else None

        support_strength = support_levels[0].strength if support_levels else "UNKNOWN"
        resistance_strength = resistance_levels[0].strength if resistance_levels else "UNKNOWN"

        snapshot = DarkPoolSnapshot(
            timestamp=timestamp,
            ticker=ticker,
            spot_price=round(spot_price, 2),
            levels=[asdict(l) for l in level_objects[:20]],  # Top 20 levels
            nearest_support=nearest_support,
            nearest_resistance=nearest_resistance,
            support_strength=support_strength,
            resistance_strength=resistance_strength,
            total_dark_volume=total_dark_volume,
            total_dark_notional=round(total_dark_notional, 0),
            buy_volume=total_buy_volume,
            sell_volume=total_sell_volume
        )

        # Log summary
        log.info(
            f"DarkPool: {len(blocks)} blocks | "
            f"${total_dark_notional/1e6:.1f}M notional | "
            f"Support: ${nearest_support} ({support_strength}) | "
            f"Resistance: ${nearest_resistance} ({resistance_strength})"
        )

        self.last_snapshot = snapshot
        self.last_update = datetime.now(timezone.utc)

        return snapshot

    def get_last_snapshot(self) -> Optional[DarkPoolSnapshot]:
        """Get the most recent dark pool snapshot."""
        return self.last_snapshot

    def get_levels_near_price(self, price: float, range_pct: float = 0.02) -> List[dict]:
        """Get dark pool levels within range of a price."""
        if not self.last_snapshot:
            return []

        low = price * (1 - range_pct)
        high = price * (1 + range_pct)

        return [
            l for l in self.last_snapshot.levels
            if low <= l["price"] <= high
        ]

    def get_conviction_modifier(self, entry_price: float, stop_price: float, target_price: float) -> dict:
        """
        Get conviction modifier based on dark pool levels.

        Returns modifier and reasoning based on:
        - Dark pool support below entry
        - Dark pool resistance above entry
        """
        if not self.last_snapshot:
            return {"modifier": 0, "reasons": ["No dark pool data"]}

        modifier = 0
        reasons = []

        dp = self.last_snapshot

        # Check if there's support between stop and entry
        if dp.nearest_support and stop_price < dp.nearest_support < entry_price:
            if dp.support_strength in ("HIGH", "VERY_HIGH"):
                modifier += 10
                reasons.append(f"Strong DP support at ${dp.nearest_support} above stop")
            else:
                modifier += 5
                reasons.append(f"DP support at ${dp.nearest_support}")

        # Check if resistance is before target
        if dp.nearest_resistance and entry_price < dp.nearest_resistance < target_price:
            if dp.resistance_strength in ("HIGH", "VERY_HIGH"):
                modifier -= 10
                reasons.append(f"Strong DP resistance at ${dp.nearest_resistance} before target")
            else:
                modifier -= 5
                reasons.append(f"DP resistance at ${dp.nearest_resistance}")

        # Check overall flow direction
        if dp.buy_volume > dp.sell_volume * 2:
            modifier += 5
            reasons.append("Dark pool flow heavily buying")
        elif dp.sell_volume > dp.buy_volume * 2:
            modifier -= 5
            reasons.append("Dark pool flow heavily selling")

        return {
            "modifier": modifier,
            "reasons": reasons,
            "nearest_support": dp.nearest_support,
            "nearest_resistance": dp.nearest_resistance
        }


# Singleton instance
_dp_mapper: Optional[DarkPoolMapper] = None


def get_dark_pool_mapper() -> DarkPoolMapper:
    """Get or create the singleton dark pool mapper instance."""
    global _dp_mapper
    if _dp_mapper is None:
        _dp_mapper = DarkPoolMapper()
    return _dp_mapper


# CLI for testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    mapper = get_dark_pool_mapper()
    snapshot = mapper.calculate("SPY")

    print("\n" + "=" * 60)
    print("DARK POOL MAPPER - TEST RUN")
    print("=" * 60)
    print(f"Spot Price: ${snapshot.spot_price}")
    print(f"Total Dark Volume: {snapshot.total_dark_volume:,}")
    print(f"Total Dark Notional: ${snapshot.total_dark_notional:,.0f}")
    print(f"Buy Volume: {snapshot.buy_volume:,}")
    print(f"Sell Volume: {snapshot.sell_volume:,}")
    print(f"Nearest Support: ${snapshot.nearest_support} ({snapshot.support_strength})")
    print(f"Nearest Resistance: ${snapshot.nearest_resistance} ({snapshot.resistance_strength})")
    print(f"\nTop Levels:")
    for level in snapshot.levels[:5]:
        print(f"  ${level['price']}: {level['volume']:,} shares (${level['notional']:,.0f}) - {level['side']} - {level['strength']}")
