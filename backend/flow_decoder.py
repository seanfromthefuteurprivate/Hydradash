"""
HYDRA Institutional Flow Decoder v1.0

Uses Claude 3.5 Haiku via Bedrock to classify options flow.
Runs every 2 minutes during market hours.

Classifies:
- Net premium direction (calls vs puts)
- Sweep activity (urgency signal)
- Institutional bias (AGGRESSIVE/MODERATE/NEUTRAL)
- Flow confidence

Cost: ~$30/year with prompt caching
"""

import os
import json
import logging
import sqlite3
from datetime import datetime, timezone, time
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict
from pathlib import Path

log = logging.getLogger("HYDRA.FLOWDECODER")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from bedrock_client import get_bedrock_client, BedrockResponse

# Data directory
DATA_DIR = Path(__file__).parent.parent / "data"
FLOW_DB = DATA_DIR / "flow_history.db"

# Flow thresholds
MIN_PREMIUM_SWEEP = 50000      # $50K minimum for sweep consideration
MIN_CONTRACTS_BLOCK = 100      # 100+ contracts = institutional
SWEEP_CONDITIONS = [12, 37]    # Trade condition codes for sweeps


@dataclass
class FlowSnapshot:
    """Complete flow intelligence at a point in time."""
    timestamp: str
    ticker: str
    net_premium_calls: float
    net_premium_puts: float
    premium_ratio: float
    sweep_count_calls: int
    sweep_count_puts: int
    largest_trade: dict
    institutional_bias: str  # AGGRESSIVELY_BULLISH, MODERATELY_BULLISH, NEUTRAL, etc.
    confidence: float
    total_trades_analyzed: int
    haiku_analysis: str
    latency_ms: float

    def to_dict(self) -> dict:
        return asdict(self)


class FlowDecoder:
    """
    Decodes institutional options flow using Claude Haiku.

    Flow data comes from Polygon options trades.
    Classification is done by Haiku for context-aware analysis.
    """

    def __init__(self, polygon_api_key: str = None):
        self.polygon_key = polygon_api_key or os.environ.get("POLYGON_API_KEY", "")
        self.bedrock = get_bedrock_client()
        self.last_snapshot: Optional[FlowSnapshot] = None
        self.last_update: Optional[datetime] = None
        self._init_db()

        # System prompt for Haiku (cached for efficiency)
        self.system_prompt = """You are an institutional options flow analyst. Your job is to classify market sentiment based on options trading data.

Rules:
- Sweeps indicate URGENCY - someone needs to fill immediately
- Call premium > Put premium by 2x+ = AGGRESSIVELY_BULLISH
- Put premium > Call premium by 2x+ = AGGRESSIVELY_BEARISH
- 1.5x-2x difference = MODERATELY bullish/bearish
- Within 1.5x = NEUTRAL
- Large single trades ($1M+) are significant
- Consider the CONTEXT - high VIX environment changes interpretation

Always respond with valid JSON only, no explanations."""

    def _init_db(self):
        """Initialize SQLite database for flow history."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(FLOW_DB))
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS flow_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    net_premium_calls REAL,
                    net_premium_puts REAL,
                    institutional_bias TEXT,
                    confidence REAL,
                    haiku_analysis TEXT
                )
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Flow database init error: {e}")

    def _save_to_history(self, snapshot: FlowSnapshot):
        """Save snapshot to database."""
        try:
            conn = sqlite3.connect(str(FLOW_DB))
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO flow_history
                (timestamp, ticker, net_premium_calls, net_premium_puts, institutional_bias, confidence, haiku_analysis)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.timestamp,
                snapshot.ticker,
                snapshot.net_premium_calls,
                snapshot.net_premium_puts,
                snapshot.institutional_bias,
                snapshot.confidence,
                snapshot.haiku_analysis
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Flow history save error: {e}")

    def _fetch_options_trades(self, ticker: str = "SPY", limit: int = 500) -> List[dict]:
        """Fetch recent options trades from Polygon."""
        if not HAS_REQUESTS or not self.polygon_key:
            return []

        try:
            # Polygon options trades endpoint
            url = f"https://api.polygon.io/v3/trades/O:{ticker}"

            # Get recent 0DTE options trades
            today = datetime.now().strftime("%Y-%m-%d")

            params = {
                "apiKey": self.polygon_key,
                "limit": limit,
                "order": "desc",
                "sort": "timestamp"
            }

            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("results", [])
            else:
                log.warning(f"Options trades fetch failed: {resp.status_code}")
                return []

        except Exception as e:
            log.error(f"Options trades fetch error: {e}")
            return []

    def _aggregate_flow(self, trades: List[dict]) -> dict:
        """Aggregate flow data from trades."""
        call_premium = 0
        put_premium = 0
        call_sweeps = 0
        put_sweeps = 0
        largest_trade = None
        largest_premium = 0

        for trade in trades:
            # Parse option symbol to determine call/put
            # Format: O:SPY230825C00450000
            ticker = trade.get("ticker", "")
            if len(ticker) < 15:
                continue

            is_call = "C" in ticker[10:12]
            is_put = "P" in ticker[10:12]

            price = trade.get("price", 0)
            size = trade.get("size", 0)
            conditions = trade.get("conditions", [])

            premium = price * size * 100  # Premium in dollars

            if premium < MIN_PREMIUM_SWEEP:
                continue

            # Check if sweep
            is_sweep = any(c in SWEEP_CONDITIONS for c in conditions)

            if is_call:
                call_premium += premium
                if is_sweep:
                    call_sweeps += 1
            elif is_put:
                put_premium += premium
                if is_sweep:
                    put_sweeps += 1

            # Track largest trade
            if premium > largest_premium:
                largest_premium = premium
                largest_trade = {
                    "type": "CALL_SWEEP" if is_call and is_sweep else "CALL" if is_call else "PUT_SWEEP" if is_sweep else "PUT",
                    "premium": premium,
                    "ticker": ticker,
                    "size": size,
                    "price": price
                }

        return {
            "call_premium": call_premium,
            "put_premium": put_premium,
            "call_sweeps": call_sweeps,
            "put_sweeps": put_sweeps,
            "largest_trade": largest_trade or {},
            "total_trades": len(trades)
        }

    def _classify_with_haiku(self, flow_data: dict, ticker: str) -> dict:
        """Use Claude Haiku to classify the flow."""
        if not self.bedrock.is_available:
            # Fallback to rule-based classification
            return self._rule_based_classification(flow_data)

        prompt = f"""Analyze this options flow for {ticker}:

Call Premium: ${flow_data['call_premium']:,.0f}
Put Premium: ${flow_data['put_premium']:,.0f}
Call Sweeps: {flow_data['call_sweeps']}
Put Sweeps: {flow_data['put_sweeps']}
Largest Trade: {json.dumps(flow_data['largest_trade'])}
Total Trades: {flow_data['total_trades']}

Respond with JSON:
{{
  "institutional_bias": "AGGRESSIVELY_BULLISH" | "MODERATELY_BULLISH" | "NEUTRAL" | "MODERATELY_BEARISH" | "AGGRESSIVELY_BEARISH",
  "confidence": 0-100,
  "reasoning": "one sentence explanation"
}}"""

        response = self.bedrock.invoke_claude_haiku(
            prompt=prompt,
            system=self.system_prompt,
            max_tokens=200,
            temperature=0.0
        )

        if response.success:
            try:
                # Parse JSON response
                result = json.loads(response.content)
                result["latency_ms"] = response.latency_ms
                result["haiku_raw"] = response.content
                return result
            except json.JSONDecodeError:
                log.warning(f"Failed to parse Haiku response: {response.content}")
                return self._rule_based_classification(flow_data)
        else:
            log.warning(f"Haiku classification failed: {response.error}")
            return self._rule_based_classification(flow_data)

    def _rule_based_classification(self, flow_data: dict) -> dict:
        """Fallback rule-based classification when Haiku unavailable."""
        call_premium = flow_data["call_premium"]
        put_premium = flow_data["put_premium"]

        if call_premium == 0 and put_premium == 0:
            return {
                "institutional_bias": "NEUTRAL",
                "confidence": 50,
                "reasoning": "No significant flow",
                "latency_ms": 0,
                "haiku_raw": "fallback"
            }

        total = call_premium + put_premium
        ratio = call_premium / put_premium if put_premium > 0 else 10

        if ratio > 2.5:
            bias = "AGGRESSIVELY_BULLISH"
            confidence = min(95, 70 + (ratio - 2) * 10)
        elif ratio > 1.5:
            bias = "MODERATELY_BULLISH"
            confidence = 70
        elif ratio < 0.4:
            bias = "AGGRESSIVELY_BEARISH"
            confidence = min(95, 70 + (1/ratio - 2) * 10)
        elif ratio < 0.67:
            bias = "MODERATELY_BEARISH"
            confidence = 70
        else:
            bias = "NEUTRAL"
            confidence = 60

        return {
            "institutional_bias": bias,
            "confidence": confidence,
            "reasoning": f"Call/Put ratio: {ratio:.2f}",
            "latency_ms": 0,
            "haiku_raw": "rule-based"
        }

    def calculate(self, ticker: str = "SPY") -> FlowSnapshot:
        """
        Calculate flow classification.
        This is the main method called every 2 minutes.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Fetch options trades
        trades = self._fetch_options_trades(ticker)

        # Aggregate flow data
        flow_data = self._aggregate_flow(trades)

        # Classify with Haiku
        classification = self._classify_with_haiku(flow_data, ticker)

        # Calculate premium ratio
        call_premium = flow_data["call_premium"]
        put_premium = flow_data["put_premium"]
        premium_ratio = call_premium / put_premium if put_premium > 0 else 10.0

        snapshot = FlowSnapshot(
            timestamp=timestamp,
            ticker=ticker,
            net_premium_calls=round(call_premium, 0),
            net_premium_puts=round(put_premium, 0),
            premium_ratio=round(premium_ratio, 2),
            sweep_count_calls=flow_data["call_sweeps"],
            sweep_count_puts=flow_data["put_sweeps"],
            largest_trade=flow_data["largest_trade"],
            institutional_bias=classification["institutional_bias"],
            confidence=classification["confidence"],
            total_trades_analyzed=flow_data["total_trades"],
            haiku_analysis=classification.get("reasoning", ""),
            latency_ms=classification.get("latency_ms", 0)
        )

        # Log summary
        log.info(
            f"Flow: {ticker} | "
            f"Calls: ${call_premium/1e6:.2f}M | "
            f"Puts: ${put_premium/1e6:.2f}M | "
            f"Bias: {classification['institutional_bias']} ({classification['confidence']}%)"
        )

        # Save to history
        self._save_to_history(snapshot)
        self.last_snapshot = snapshot
        self.last_update = datetime.now(timezone.utc)

        return snapshot

    def get_last_snapshot(self) -> Optional[FlowSnapshot]:
        """Get the most recent flow snapshot."""
        return self.last_snapshot

    def get_conviction_modifier(self, trade_direction: str) -> dict:
        """
        Get conviction modifier based on flow bias.

        Args:
            trade_direction: "BULLISH" or "BEARISH"

        Returns:
            dict with modifier and reasoning
        """
        if not self.last_snapshot:
            return {"modifier": 0, "reasons": ["No flow data"]}

        flow = self.last_snapshot
        modifier = 0
        reasons = []

        # Check alignment with trade direction
        if trade_direction == "BULLISH":
            if flow.institutional_bias in ("AGGRESSIVELY_BULLISH", "MODERATELY_BULLISH"):
                modifier += 10 if "AGGRESSIVELY" in flow.institutional_bias else 5
                reasons.append(f"Flow aligns: {flow.institutional_bias}")
            elif flow.institutional_bias in ("AGGRESSIVELY_BEARISH", "MODERATELY_BEARISH"):
                modifier -= 10 if "AGGRESSIVELY" in flow.institutional_bias else 5
                reasons.append(f"Flow conflicts: {flow.institutional_bias}")

        elif trade_direction == "BEARISH":
            if flow.institutional_bias in ("AGGRESSIVELY_BEARISH", "MODERATELY_BEARISH"):
                modifier += 10 if "AGGRESSIVELY" in flow.institutional_bias else 5
                reasons.append(f"Flow aligns: {flow.institutional_bias}")
            elif flow.institutional_bias in ("AGGRESSIVELY_BULLISH", "MODERATELY_BULLISH"):
                modifier -= 10 if "AGGRESSIVELY" in flow.institutional_bias else 5
                reasons.append(f"Flow conflicts: {flow.institutional_bias}")

        # Sweep activity bonus
        if trade_direction == "BULLISH" and flow.sweep_count_calls > flow.sweep_count_puts * 2:
            modifier += 5
            reasons.append(f"Call sweeps dominant ({flow.sweep_count_calls} vs {flow.sweep_count_puts})")
        elif trade_direction == "BEARISH" and flow.sweep_count_puts > flow.sweep_count_calls * 2:
            modifier += 5
            reasons.append(f"Put sweeps dominant ({flow.sweep_count_puts} vs {flow.sweep_count_calls})")

        return {
            "modifier": modifier,
            "reasons": reasons,
            "institutional_bias": flow.institutional_bias,
            "confidence": flow.confidence
        }


# Singleton instance
_flow_decoder: Optional[FlowDecoder] = None


def get_flow_decoder() -> FlowDecoder:
    """Get or create the singleton flow decoder instance."""
    global _flow_decoder
    if _flow_decoder is None:
        _flow_decoder = FlowDecoder()
    return _flow_decoder


# CLI for testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    decoder = get_flow_decoder()
    snapshot = decoder.calculate("SPY")

    print("\n" + "=" * 60)
    print("FLOW DECODER - TEST RUN")
    print("=" * 60)
    print(f"Call Premium: ${snapshot.net_premium_calls:,.0f}")
    print(f"Put Premium: ${snapshot.net_premium_puts:,.0f}")
    print(f"Premium Ratio: {snapshot.premium_ratio}")
    print(f"Call Sweeps: {snapshot.sweep_count_calls}")
    print(f"Put Sweeps: {snapshot.sweep_count_puts}")
    print(f"Institutional Bias: {snapshot.institutional_bias}")
    print(f"Confidence: {snapshot.confidence}%")
    print(f"Haiku Analysis: {snapshot.haiku_analysis}")
    print(f"Latency: {snapshot.latency_ms}ms")
    print(f"Largest Trade: {json.dumps(snapshot.largest_trade, indent=2)}")
