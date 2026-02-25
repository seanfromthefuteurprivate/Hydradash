"""
╔══════════════════════════════════════════════════════════════════════════════╗
║               HYDRA EVENT SURPRISE DETECTOR v1.0                            ║
║         Real-time detection of economic data surprises                       ║
║                                                                              ║
║  When a scheduled economic event happens (CPI, NFP, FOMC):                  ║
║  1. Scrape actual number from FRED/news within 60s of release               ║
║  2. Compare to consensus                                                    ║
║  3. Calculate surprise magnitude and market impact                          ║
║  4. Send direction signal to blowup engine                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any
from pathlib import Path

log = logging.getLogger("HYDRA.EVENTS")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

DATA_DIR = Path(__file__).parent.parent / "data"
EVENTS_DB = DATA_DIR / "event_surprises.db"


# ═══════════════════════════════════════════════════════════════
#  EVENT DEFINITIONS
# ═══════════════════════════════════════════════════════════════

@dataclass
class EconomicEvent:
    """Definition of a scheduled economic event."""
    name: str
    date: str                    # ISO date
    time: str                    # HH:MM UTC
    fred_series: Optional[str]   # FRED series ID for actual data
    consensus: Optional[float]   # Market consensus estimate
    previous: Optional[float]    # Previous period value
    unit: str                    # %, K, M, etc.
    importance: str              # HIGH, MEDIUM, LOW
    category: str                # inflation, labor, growth, rates
    assets_affected: List[str]


@dataclass
class EventSurprise:
    """Result of surprise detection after data release."""
    event_name: str
    timestamp: str
    actual: float
    consensus: float
    previous: float
    surprise_pct: float         # (actual - consensus) / consensus
    surprise_std: float         # Standard deviations from consensus
    direction: str              # BETTER_THAN_EXPECTED, WORSE_THAN_EXPECTED, IN_LINE
    magnitude: str              # MASSIVE, LARGE, MODERATE, SMALL
    market_impact: str          # Description of expected impact
    trade_signals: List[str]    # Suggested trades
    confidence: float           # Data quality confidence

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
#  EVENT CALENDAR
# ═══════════════════════════════════════════════════════════════

class EventCalendar:
    """
    Manages the economic event calendar with consensus estimates.
    Updated regularly with upcoming events.
    """

    # Static event definitions - in production, scrape from Bloomberg/Investing.com
    EVENTS = [
        EconomicEvent(
            name="Nonfarm Payrolls",
            date="2026-03-07",
            time="13:30",
            fred_series="PAYEMS",
            consensus=150,      # Expected change in thousands
            previous=143,
            unit="K",
            importance="HIGH",
            category="labor",
            assets_affected=["SPY", "TLT", "GLD", "DXY", "EUR/USD"]
        ),
        EconomicEvent(
            name="CPI YoY",
            date="2026-03-12",
            time="13:30",
            fred_series="CPIAUCSL",
            consensus=2.9,
            previous=2.9,
            unit="%",
            importance="HIGH",
            category="inflation",
            assets_affected=["SPY", "TLT", "GLD", "TIP"]
        ),
        EconomicEvent(
            name="Core CPI MoM",
            date="2026-03-12",
            time="13:30",
            fred_series="CPILFESL",
            consensus=0.3,
            previous=0.4,
            unit="%",
            importance="HIGH",
            category="inflation",
            assets_affected=["SPY", "TLT", "GLD", "TIP"]
        ),
        EconomicEvent(
            name="Initial Jobless Claims",
            date="2026-02-27",
            time="13:30",
            fred_series="ICSA",
            consensus=215,
            previous=219,
            unit="K",
            importance="MEDIUM",
            category="labor",
            assets_affected=["SPY", "TLT"]
        ),
        EconomicEvent(
            name="GDP QoQ",
            date="2026-02-27",
            time="13:30",
            fred_series="A191RL1Q225SBEA",
            consensus=2.3,
            previous=2.3,
            unit="%",
            importance="HIGH",
            category="growth",
            assets_affected=["SPY", "IWM", "TLT"]
        ),
        EconomicEvent(
            name="PCE Price Index YoY",
            date="2026-02-28",
            time="13:30",
            fred_series="PCEPI",
            consensus=2.6,
            previous=2.6,
            unit="%",
            importance="HIGH",
            category="inflation",
            assets_affected=["SPY", "TLT", "GLD"]
        ),
        EconomicEvent(
            name="ISM Manufacturing PMI",
            date="2026-03-03",
            time="15:00",
            fred_series="NAPM",
            consensus=49.5,
            previous=49.2,
            unit="",
            importance="MEDIUM",
            category="manufacturing",
            assets_affected=["SPY", "XLI", "CAT"]
        ),
        EconomicEvent(
            name="FOMC Rate Decision",
            date="2026-03-19",
            time="19:00",
            fred_series="DFF",
            consensus=4.50,
            previous=4.50,
            unit="%",
            importance="HIGH",
            category="rates",
            assets_affected=["SPY", "TLT", "GLD", "QQQ", "IWM", "XLF"]
        ),
    ]

    def __init__(self):
        self._init_db()

    def _init_db(self):
        """Initialize SQLite for event tracking."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(EVENTS_DB))
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS event_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_name TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    actual REAL,
                    consensus REAL,
                    previous REAL,
                    surprise_pct REAL,
                    direction TEXT,
                    spy_move_15min REAL,
                    spy_move_30min REAL,
                    tlt_move_15min REAL,
                    timestamp TEXT NOT NULL
                )
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Event DB init error: {e}")

    def get_upcoming_events(self, hours: int = 24) -> List[EconomicEvent]:
        """Get events happening within the next N hours."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours)

        upcoming = []
        for event in self.EVENTS:
            try:
                event_dt = datetime.strptime(
                    f"{event.date} {event.time}",
                    "%Y-%m-%d %H:%M"
                ).replace(tzinfo=timezone.utc)

                if now <= event_dt <= cutoff:
                    upcoming.append(event)
            except ValueError:
                continue

        return sorted(upcoming, key=lambda e: f"{e.date} {e.time}")

    def get_events_for_api(self, hours: int = 72) -> List[dict]:
        """Get events formatted for API response."""
        events = self.get_upcoming_events(hours)
        now = datetime.now(timezone.utc)

        result = []
        for event in events:
            try:
                event_dt = datetime.strptime(
                    f"{event.date} {event.time}",
                    "%Y-%m-%d %H:%M"
                ).replace(tzinfo=timezone.utc)

                time_until = (event_dt - now).total_seconds()
                minutes_until = int(time_until / 60)
                hours_until = time_until / 3600

                result.append({
                    "name": event.name,
                    "datetime": event_dt.isoformat(),
                    "minutes_until": minutes_until,
                    "hours_until": round(hours_until, 1),
                    "consensus": event.consensus,
                    "previous": event.previous,
                    "unit": event.unit,
                    "importance": event.importance,
                    "category": event.category,
                    "assets_affected": event.assets_affected,
                    "impact_description": self._get_impact_description(event)
                })
            except ValueError:
                continue

        return result

    def _get_impact_description(self, event: EconomicEvent) -> str:
        """Generate impact description for an event."""
        if event.category == "labor":
            return "Strong data = hawkish Fed = risk off. Weak data = dovish Fed = risk on initially, then recession fears."
        elif event.category == "inflation":
            return "Hot inflation = hawkish Fed = bonds down, stocks volatile. Cool inflation = rally in risk assets."
        elif event.category == "growth":
            return "Strong GDP = risk on. Weak GDP = recession fears but also rate cut hopes."
        elif event.category == "rates":
            return "Hawkish surprise = risk off. Dovish surprise = massive rally."
        elif event.category == "manufacturing":
            return "Above 50 = expansion, bullish for industrials. Below 50 = contraction, defensive positioning."
        return "Market moving event."


# ═══════════════════════════════════════════════════════════════
#  SURPRISE DETECTOR
# ═══════════════════════════════════════════════════════════════

class SurpriseDetector:
    """
    Detects surprises when economic data is released.
    Compares actual to consensus and calculates market impact.
    """

    # Historical standard deviations for surprise calculation
    HISTORICAL_STDEV = {
        "Nonfarm Payrolls": 40,      # NFP typically surprises by +/- 40K
        "CPI YoY": 0.1,               # CPI by +/- 0.1%
        "Core CPI MoM": 0.1,
        "Initial Jobless Claims": 15,
        "GDP QoQ": 0.3,
        "PCE Price Index YoY": 0.1,
        "ISM Manufacturing PMI": 1.5,
        "FOMC Rate Decision": 0.25,   # Quarter point moves
    }

    def __init__(self):
        self.calendar = EventCalendar()
        self.fred_api_key = os.environ.get("FRED_API_KEY", "")

    def check_for_release(self, event: EconomicEvent) -> Optional[EventSurprise]:
        """
        Check if data has been released for an event.
        Called shortly after scheduled release time.
        """
        if not event.fred_series or not self.fred_api_key:
            return None

        try:
            actual = self._fetch_fred_data(event.fred_series)
            if actual is None:
                return None

            consensus = event.consensus or 0
            previous = event.previous or 0

            # Calculate surprise
            if consensus != 0:
                surprise_pct = (actual - consensus) / abs(consensus)
            else:
                surprise_pct = 0

            # Calculate standard deviation surprise
            stdev = self.HISTORICAL_STDEV.get(event.name, 1.0)
            surprise_std = (actual - consensus) / stdev if stdev > 0 else 0

            # Determine direction
            direction = self._classify_direction(event, actual, consensus)

            # Determine magnitude
            magnitude = self._classify_magnitude(abs(surprise_std))

            # Generate market impact
            market_impact = self._generate_impact(event, direction, magnitude)

            # Generate trade signals
            trade_signals = self._generate_trades(event, direction, magnitude)

            return EventSurprise(
                event_name=event.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
                actual=actual,
                consensus=consensus,
                previous=previous,
                surprise_pct=round(surprise_pct, 4),
                surprise_std=round(surprise_std, 2),
                direction=direction,
                magnitude=magnitude,
                market_impact=market_impact,
                trade_signals=trade_signals,
                confidence=0.9 if self.fred_api_key else 0.5
            )

        except Exception as e:
            log.error(f"Surprise detection error for {event.name}: {e}")
            return None

    def _fetch_fred_data(self, series_id: str) -> Optional[float]:
        """Fetch latest data from FRED API."""
        if not HAS_REQUESTS or not self.fred_api_key:
            return None

        try:
            url = "https://api.stlouisfed.org/fred/series/observations"
            resp = requests.get(url, params={
                "series_id": series_id,
                "api_key": self.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1
            }, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                obs = data.get("observations", [])
                if obs and obs[0].get("value") != ".":
                    return float(obs[0]["value"])
        except Exception as e:
            log.debug(f"FRED fetch error: {e}")

        return None

    def _classify_direction(self, event: EconomicEvent, actual: float, consensus: float) -> str:
        """Classify if data is better or worse than expected."""
        diff = actual - consensus

        # For some indicators, higher is worse (inflation, jobless claims)
        higher_is_worse = event.category in ["inflation"] or "Claims" in event.name

        if abs(diff) < 0.01 * abs(consensus):  # Within 1%
            return "IN_LINE"
        elif higher_is_worse:
            return "WORSE_THAN_EXPECTED" if diff > 0 else "BETTER_THAN_EXPECTED"
        else:
            return "BETTER_THAN_EXPECTED" if diff > 0 else "WORSE_THAN_EXPECTED"

    def _classify_magnitude(self, surprise_std: float) -> str:
        """Classify surprise magnitude by standard deviations."""
        abs_std = abs(surprise_std)
        if abs_std >= 3:
            return "MASSIVE"
        elif abs_std >= 2:
            return "LARGE"
        elif abs_std >= 1:
            return "MODERATE"
        else:
            return "SMALL"

    def _generate_impact(self, event: EconomicEvent, direction: str, magnitude: str) -> str:
        """Generate market impact description."""
        if magnitude == "SMALL" or direction == "IN_LINE":
            return f"{event.name} came in line with expectations. Minimal market impact expected."

        impacts = {
            ("labor", "BETTER_THAN_EXPECTED"): "Strong labor data is hawkish for Fed. Expect rates higher for longer, pressure on growth stocks.",
            ("labor", "WORSE_THAN_EXPECTED"): "Weak labor data raises recession fears but also rate cut hopes. Watch for risk-off then risk-on pattern.",
            ("inflation", "BETTER_THAN_EXPECTED"): "Cooler inflation = dovish Fed. Risk assets rally, bonds bid.",
            ("inflation", "WORSE_THAN_EXPECTED"): "Hot inflation = hawkish Fed. Bonds sell off, stocks volatile, dollar strengthens.",
            ("growth", "BETTER_THAN_EXPECTED"): "Strong growth = risk on. Cyclicals outperform.",
            ("growth", "WORSE_THAN_EXPECTED"): "Weak growth = recession fears. Defensive positioning.",
            ("rates", "BETTER_THAN_EXPECTED"): "Dovish Fed = massive risk rally.",
            ("rates", "WORSE_THAN_EXPECTED"): "Hawkish Fed = risk off, yields spike.",
        }

        key = (event.category, direction)
        base_impact = impacts.get(key, f"{event.name} surprise detected.")

        if magnitude == "MASSIVE":
            return f"MASSIVE SURPRISE: {base_impact} Expect 1-2% moves in affected assets."
        elif magnitude == "LARGE":
            return f"LARGE SURPRISE: {base_impact} Expect 0.5-1% moves."
        else:
            return f"MODERATE SURPRISE: {base_impact}"

    def _generate_trades(self, event: EconomicEvent, direction: str, magnitude: str) -> List[str]:
        """Generate trade signals based on surprise."""
        trades = []

        if magnitude == "SMALL" or direction == "IN_LINE":
            trades.append("Data in line - fade any overreaction")
            return trades

        if event.category == "labor":
            if direction == "WORSE_THAN_EXPECTED":
                trades.extend([
                    "BUY TLT calls - rate cut expectations rise",
                    "SELL IWM - small caps most exposed to labor weakness",
                    "BUY GLD calls - safe haven + lower rates"
                ])
            else:
                trades.extend([
                    "SELL TLT - rates higher for longer",
                    "BUY XLF calls - banks benefit from higher rates"
                ])

        elif event.category == "inflation":
            if direction == "BETTER_THAN_EXPECTED":
                trades.extend([
                    "BUY QQQ calls - growth benefits from lower rates",
                    "BUY TLT calls - bonds rally on dovish Fed",
                    "BUY GLD - real rates decline"
                ])
            else:
                trades.extend([
                    "BUY TLT puts - yields spike on hot inflation",
                    "BUY DXY - dollar strengthens",
                    "SELL XLY - consumer discretionary hit"
                ])

        elif event.category == "rates":
            if direction == "BETTER_THAN_EXPECTED":  # Dovish
                trades.extend([
                    "BUY SPY calls - risk on",
                    "BUY QQQ calls - growth rallies",
                    "BUY IWM calls - small caps rip"
                ])
            else:  # Hawkish
                trades.extend([
                    "BUY SPY puts - risk off",
                    "BUY TLT puts - yields spike",
                    "SELL growth stocks"
                ])

        if magnitude == "MASSIVE":
            trades.insert(0, "PRIORITY: Trade the first 15-minute candle direction")

        return trades

    def save_result(self, surprise: EventSurprise, spy_move_15: float = None, spy_move_30: float = None):
        """Save surprise result to database for future calibration."""
        try:
            conn = sqlite3.connect(str(EVENTS_DB))
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO event_results
                (event_name, event_date, actual, consensus, previous, surprise_pct, direction, spy_move_15min, spy_move_30min, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                surprise.event_name,
                datetime.now().strftime("%Y-%m-%d"),
                surprise.actual,
                surprise.consensus,
                surprise.previous,
                surprise.surprise_pct,
                surprise.direction,
                spy_move_15,
                spy_move_30,
                surprise.timestamp
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Event result save error: {e}")


# ═══════════════════════════════════════════════════════════════
#  SINGLETON INSTANCES
# ═══════════════════════════════════════════════════════════════

_calendar_instance: Optional[EventCalendar] = None
_detector_instance: Optional[SurpriseDetector] = None

def get_event_calendar() -> EventCalendar:
    """Get or create singleton EventCalendar."""
    global _calendar_instance
    if _calendar_instance is None:
        _calendar_instance = EventCalendar()
    return _calendar_instance

def get_surprise_detector() -> SurpriseDetector:
    """Get or create singleton SurpriseDetector."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = SurpriseDetector()
    return _detector_instance


# ═══════════════════════════════════════════════════════════════
#  CLI FOR TESTING
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    calendar = get_event_calendar()
    print("\nUpcoming Events (next 72 hours):")
    print("=" * 60)

    events = calendar.get_events_for_api(hours=72)
    for event in events:
        print(f"\n{event['name']}")
        print(f"  Time: {event['datetime']}")
        print(f"  In: {event['hours_until']} hours")
        print(f"  Consensus: {event['consensus']} {event['unit']}")
        print(f"  Previous: {event['previous']} {event['unit']}")
        print(f"  Assets: {', '.join(event['assets_affected'])}")
