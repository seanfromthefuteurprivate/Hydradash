"""
╔══════════════════════════════════════════════════════════════════════╗
║          HYDRA — Telegram Signal Integration Module                 ║
║                                                                      ║
║  This module sits on top of the HYDRA engine and provides:           ║
║  1. INBOUND: Parse Telegram signals → HYDRA Signal objects           ║
║  2. OUTBOUND: Push alerts, trade confirmations, portfolio updates    ║
║  3. EVENT CALENDAR: Automated pre/live/post event notifications      ║
║  4. SIGNAL CLASSIFICATION: NLP-lite parsing of free-text signals     ║
║                                                                      ║
║  Requires: pip install python-telegram-bot aiohttp                   ║
║  Set env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID                 ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import json
import time
import logging
import threading
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Optional
from collections import deque

log = logging.getLogger("HYDRA.TELEGRAM")

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SIGNAL_CHANNEL_ID = os.environ.get("SIGNAL_CHANNEL_ID", "")


# ═════════════════════════════════════════════════════════════
#  SECTION 1: SIGNAL PARSER
#  ─────────────────────────────────────────────────────────
#  Parses incoming Telegram messages from signal channels
#  into structured data the HYDRA engine can consume.
#
#  Handles multiple signal formats:
#  - Structured JSON signals
#  - Free-text signals ("BUY BTC at 70000, SL 67000, TP 78000")
#  - Alert-style ("⚠️ NFP releasing in 1 hour")
#  - News-style ("Breaking: Fed cuts rates 50bps")
# ═════════════════════════════════════════════════════════════

@dataclass
class ParsedSignal:
    """A signal parsed from a Telegram message."""
    source: str               # Channel/user that sent it
    raw_text: str             # Original message
    parsed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Extracted fields
    signal_type: str = "unknown"   # "trade", "alert", "news", "data_release"
    direction: Optional[str] = None  # "BUY", "SELL", None
    asset: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 0.5

    # Classification
    category: str = "unknown"      # "macro", "crypto", "metals", "tech", "geopolitical"
    priority: str = "MEDIUM"       # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    urgency: str = "normal"        # "immediate", "normal", "patient"

    # Matched event
    matched_event_id: Optional[str] = None
    sentiment: float = 0.0        # -1 (bearish) to +1 (bullish)

    # Metadata
    metadata: dict = field(default_factory=dict)


class SignalParser:
    """
    Parses raw Telegram messages into structured signals.

    Uses pattern matching and keyword extraction - not a full NLP model,
    but effective for the structured signal formats commonly used
    in trading Telegram channels.
    """

    # Asset aliases and mappings
    ASSET_MAP = {
        # Crypto
        "btc": "BTC/USD", "bitcoin": "BTC/USD",
        "eth": "ETH/USD", "ethereum": "ETH/USD",
        "sol": "SOL/USD", "solana": "SOL/USD",
        "xrp": "XRP/USD",
        # Equities
        "spy": "SPY", "spx": "SPX", "es": "SPX",
        "qqq": "QQQ", "nq": "QQQ",
        "aapl": "AAPL", "msft": "MSFT", "nvda": "NVDA",
        "crm": "CRM", "shop": "SHOP", "adbe": "ADBE",
        # Metals
        "gold": "GLD", "xauusd": "GLD", "xau": "GLD", "gld": "GLD",
        "silver": "SLV", "xagusd": "SLV", "xag": "SLV", "slv": "SLV",
        # Bonds
        "tlt": "TLT", "bonds": "TLT", "treasuries": "TLT",
        # Volatility
        "vix": "UVXY", "uvxy": "UVXY",
    }

    # Direction keywords
    BUY_KEYWORDS = {"buy", "long", "call", "bullish", "bid", "accumulate", "dip buy", "btd", "🟢", "🚀", "📈"}
    SELL_KEYWORDS = {"sell", "short", "put", "bearish", "ask", "dump", "fade", "🔴", "📉"}

    # Priority keywords
    CRITICAL_KEYWORDS = {"urgent", "critical", "breaking", "flash", "emergency", "crash", "limit down", "circuit breaker", "⚠️", "🚨", "‼️"}
    HIGH_KEYWORDS = {"important", "watch", "alert", "warning", "significant", "major"}

    # Category keywords
    MACRO_KEYWORDS = {"nfp", "cpi", "fomc", "fed", "jobs", "employment", "inflation", "gdp", "pce", "jolts", "ism", "retail sales", "treasury", "yield", "rate cut", "rate hike"}
    CRYPTO_KEYWORDS = {"bitcoin", "btc", "ethereum", "eth", "crypto", "defi", "nft", "altcoin", "liquidation", "funding rate", "halving", "whale"}
    METALS_KEYWORDS = {"gold", "silver", "platinum", "palladium", "xau", "xag", "precious metals", "bullion", "mining", "comex", "lbma"}
    TECH_KEYWORDS = {"ai", "artificial intelligence", "openai", "anthropic", "claude", "gpt", "saas", "software", "tech", "startup", "ipo"}
    GEO_KEYWORDS = {"war", "sanctions", "tariff", "election", "geopolitical", "iran", "china", "russia", "trump", "nato"}

    # Event matching patterns
    EVENT_PATTERNS = {
        "nfp": r"(?:nfp|non.?farm|payroll|jobs?\s*report|employment\s*situation)",
        "cpi": r"(?:cpi|consumer\s*price|inflation\s*report|inflation\s*data)",
        "fomc": r"(?:fomc|federal\s*reserve|fed\s*meeting|rate\s*decision|powell)",
        "jolts": r"(?:jolts|job\s*openings)",
    }

    def parse(self, message_text: str, source: str = "unknown") -> ParsedSignal:
        """
        Parse a raw Telegram message into a structured signal.
        """
        signal = ParsedSignal(source=source, raw_text=message_text)
        text = message_text.lower().strip()

        # ── Try structured JSON first ──
        json_signal = self._try_parse_json(message_text)
        if json_signal:
            return json_signal

        # ── Extract direction ──
        signal.direction = self._extract_direction(text)

        # ── Extract asset ──
        signal.asset = self._extract_asset(text)

        # ── Extract prices ──
        prices = self._extract_prices(text)
        if prices.get("entry"):
            signal.entry_price = prices["entry"]
        if prices.get("stop"):
            signal.stop_loss = prices["stop"]
        if prices.get("target"):
            signal.take_profit = prices["target"]

        # ── Classify category ──
        signal.category = self._classify_category(text)

        # ── Determine priority ──
        signal.priority = self._classify_priority(text)

        # ── Calculate sentiment ──
        signal.sentiment = self._calc_sentiment(text)

        # ── Determine signal type ──
        if signal.direction and signal.asset:
            signal.signal_type = "trade"
            signal.confidence = 0.7 if signal.stop_loss else 0.5
        elif any(re.search(p, text) for p in self.EVENT_PATTERNS.values()):
            signal.signal_type = "data_release"
            signal.confidence = 0.8
        elif any(k in text for k in self.CRITICAL_KEYWORDS | self.HIGH_KEYWORDS):
            signal.signal_type = "alert"
            signal.confidence = 0.6
        else:
            signal.signal_type = "news"
            signal.confidence = 0.4

        # ── Match to known events ──
        signal.matched_event_id = self._match_event(text)

        # ── Urgency ──
        if signal.priority == "CRITICAL" or any(k in text for k in ["now", "immediately", "urgent"]):
            signal.urgency = "immediate"
        elif signal.priority == "HIGH":
            signal.urgency = "normal"
        else:
            signal.urgency = "patient"

        return signal

    def _try_parse_json(self, text: str) -> Optional[ParsedSignal]:
        """Try to parse as structured JSON signal."""
        try:
            # Find JSON-like content in the message
            match = re.search(r'\{[^}]+\}', text)
            if match:
                data = json.loads(match.group())
                signal = ParsedSignal(source="json", raw_text=text)
                signal.signal_type = "trade"
                signal.direction = data.get("direction", "").upper()
                signal.asset = self.ASSET_MAP.get(
                    data.get("asset", "").lower(),
                    data.get("asset")
                )
                signal.entry_price = float(data["entry"]) if "entry" in data else None
                signal.stop_loss = float(data["stop"]) if "stop" in data else None
                signal.take_profit = float(data["target"]) if "target" in data else None
                signal.confidence = float(data.get("confidence", 0.7))
                return signal
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
        return None

    def _extract_direction(self, text: str) -> Optional[str]:
        """
        Extract buy/sell direction from text.
        Uses FIRST directional keyword found (position matters).
        If both BUY and SELL keywords exist, the one appearing first wins.
        """
        words = text.split()

        # Find first occurrence index of each direction
        buy_idx = float("inf")
        sell_idx = float("inf")

        for i, w in enumerate(words):
            if w in self.BUY_KEYWORDS and i < buy_idx:
                buy_idx = i
            if w in self.SELL_KEYWORDS and i < sell_idx:
                sell_idx = i

        # Check emoji-based signals (these are usually at the start)
        if "🟢" in text or "🚀" in text or "📈" in text:
            buy_idx = min(buy_idx, text.index("🟢") if "🟢" in text else buy_idx)
        if "🔴" in text or "📉" in text:
            sell_idx = min(sell_idx, text.index("🔴") if "🔴" in text else sell_idx)

        if buy_idx == float("inf") and sell_idx == float("inf"):
            return None
        return "BUY" if buy_idx < sell_idx else "SELL"

    def _extract_asset(self, text: str) -> Optional[str]:
        """Extract the traded asset from text."""
        # Check explicit ticker mentions (e.g., $BTC, $SPY)
        ticker_match = re.findall(r'\$([A-Z]{1,5})', text.upper())
        if ticker_match:
            ticker = ticker_match[0].lower()
            return self.ASSET_MAP.get(ticker, ticker_match[0])

        # Check against asset map
        for alias, asset in self.ASSET_MAP.items():
            if alias in text.split() or alias in text:
                return asset

        return None

    def _extract_prices(self, text: str) -> dict:
        """Extract entry, stop loss, and take profit prices."""
        prices = {}

        # Entry patterns
        for pattern in [
            r'(?:entry|enter|@|at)\s*[\$:]?\s*([\d,]+\.?\d*)',
            r'(?:buy|sell|long|short)\s+(?:at\s+)?[\$]?([\d,]+\.?\d*)',
        ]:
            match = re.search(pattern, text)
            if match:
                prices["entry"] = float(match.group(1).replace(",", ""))
                break

        # Stop loss patterns
        for pattern in [
            r'(?:sl|stop\s*loss|stop)\s*[\$:=]?\s*([\d,]+\.?\d*)',
            r'(?:risk|invalidation)\s*[\$:=]?\s*([\d,]+\.?\d*)',
        ]:
            match = re.search(pattern, text)
            if match:
                prices["stop"] = float(match.group(1).replace(",", ""))
                break

        # Take profit patterns
        for pattern in [
            r'(?:tp|take\s*profit|target|tgt)\s*[\$:=]?\s*([\d,]+\.?\d*)',
            r'(?:goal|exit)\s*[\$:=]?\s*([\d,]+\.?\d*)',
        ]:
            match = re.search(pattern, text)
            if match:
                prices["target"] = float(match.group(1).replace(",", ""))
                break

        return prices

    def _classify_category(self, text: str) -> str:
        """Classify the signal category."""
        scores = {
            "macro": sum(1 for k in self.MACRO_KEYWORDS if k in text),
            "crypto": sum(1 for k in self.CRYPTO_KEYWORDS if k in text),
            "metals": sum(1 for k in self.METALS_KEYWORDS if k in text),
            "tech": sum(1 for k in self.TECH_KEYWORDS if k in text),
            "geopolitical": sum(1 for k in self.GEO_KEYWORDS if k in text),
        }
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "unknown"

    def _classify_priority(self, text: str) -> str:
        """Classify signal priority."""
        if any(k in text for k in self.CRITICAL_KEYWORDS):
            return "CRITICAL"
        if any(k in text for k in self.HIGH_KEYWORDS):
            return "HIGH"
        return "MEDIUM"

    def _calc_sentiment(self, text: str) -> float:
        """Simple sentiment scoring -1 to +1."""
        bull_score = sum(1 for k in self.BUY_KEYWORDS if k in text)
        bear_score = sum(1 for k in self.SELL_KEYWORDS if k in text)
        total = bull_score + bear_score
        if total == 0:
            return 0.0
        return (bull_score - bear_score) / total

    def _match_event(self, text: str) -> Optional[str]:
        """Match signal to a known event in the calendar."""
        for event_id, pattern in self.EVENT_PATTERNS.items():
            if re.search(pattern, text):
                return event_id
        return None


# ═════════════════════════════════════════════════════════════
#  SECTION 2: TELEGRAM BOT — Sends & Receives
# ═════════════════════════════════════════════════════════════

class TelegramBridge:
    """
    Bidirectional bridge between Telegram and HYDRA.

    INBOUND: Listens for signals from configured channels
    OUTBOUND: Pushes alerts, trade confirmations, portfolio updates
    """

    def __init__(self, bot_token: str, chat_id: str, signal_channel: str = ""):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.signal_channel = signal_channel
        self.parser = SignalParser()
        self.message_queue = deque(maxlen=500)
        self.last_update_id = 0
        self.connected = False

        if bot_token and chat_id:
            self.connected = True
            log.info(f"Telegram bridge initialized. Chat: {chat_id}")
        else:
            log.warning("Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

    # ── OUTBOUND: Send messages to Telegram ──

    def _send_message(self, text: str, parse_mode: str = "HTML"):
        """Send a message to the configured chat."""
        if not self.connected:
            log.info(f"[TG DRY RUN] {text[:100]}...")
            return

        try:
            import requests
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                log.error(f"Telegram send failed: {resp.text}")
        except Exception as e:
            log.error(f"Telegram send error: {e}")

    def send_event_alert(self, event: dict, phase: str = "pre"):
        """Send an event alert to Telegram."""
        emoji_map = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "📊", "LOW": "ℹ️"}
        emoji = emoji_map.get(event.get("priority", "MEDIUM"), "📊")

        if phase == "pre":
            msg = (
                f"{emoji} <b>EVENT ALERT — PRE-POSITIONING</b>\n\n"
                f"<b>{event['title']}</b>\n"
                f"📅 {event.get('date', 'TBD')}\n"
                f"🎯 Priority: {event.get('priority', 'N/A')}\n"
                f"📈 Impact: {event.get('impact', 0) * 100:.0f}/100\n\n"
                f"<i>{event.get('description', '')[:300]}</i>\n\n"
                f"Consensus: {event.get('consensus', 'N/A')}\n"
                f"Previous: {event.get('previousValue', 'N/A')}\n\n"
                f"Assets: {', '.join(event.get('assetsAffected', []))}"
            )
        elif phase == "live":
            msg = (
                f"🔴 <b>LIVE — {event['title']}</b>\n\n"
                f"Data released. Monitoring market reaction.\n"
                f"Direction confirmation in 15 minutes."
            )
        elif phase == "post":
            msg = (
                f"✅ <b>POST-EVENT — {event['title']}</b>\n\n"
                f"Event processed. Check dashboard for updated scenarios."
            )
        else:
            msg = f"{emoji} {event.get('title', 'Unknown event')}"

        self._send_message(msg)

    def send_trade_alert(self, proposal: dict):
        """Send a trade execution alert."""
        side_emoji = "🟢" if proposal.get("side") == "buy" else "🔴"
        msg = (
            f"{side_emoji} <b>TRADE EXECUTED</b>\n\n"
            f"Strategy: {proposal.get('strategy_name', 'N/A')}\n"
            f"Asset: <b>{proposal.get('asset', 'N/A')}</b>\n"
            f"Side: {proposal.get('side', 'N/A').upper()}\n"
            f"Entry: ${proposal.get('entry_price', 0):,.2f}\n"
            f"Stop: ${proposal.get('stop_price', 0):,.2f}\n"
            f"Target: ${proposal.get('target_price', 0):,.2f}\n"
            f"Confidence: {proposal.get('confidence', 0):.0%}\n\n"
            f"<i>{proposal.get('rationale', '')}</i>"
        )
        self._send_message(msg)

    def send_trade_result(self, asset: str, pnl: float, result: str):
        """Send a trade closure alert."""
        emoji = "★" if pnl > 0 else "✗"
        color = "profit" if pnl > 0 else "loss"
        msg = (
            f"{emoji} <b>TRADE CLOSED — {result.upper()}</b>\n\n"
            f"Asset: <b>{asset}</b>\n"
            f"PnL: <b>${pnl:+,.2f}</b> ({color})"
        )
        self._send_message(msg)

    def send_daily_summary(self, stats: dict):
        """Send end-of-day portfolio summary."""
        msg = (
            f"📋 <b>DAILY SUMMARY</b>\n"
            f"{'═' * 30}\n\n"
            f"Capital: ${stats.get('capital', 0):,.2f}\n"
            f"Daily PnL: ${stats.get('daily_pnl', 0):+,.2f}\n"
            f"Trades: {stats.get('trades', 0)} "
            f"(W:{stats.get('wins', 0)} L:{stats.get('losses', 0)})\n"
            f"Win Rate: {stats.get('win_rate', 0):.1%}\n"
            f"Drawdown: {stats.get('drawdown', 0):.1%}\n\n"
            f"Active Regime: {stats.get('regime', 'N/A')}\n"
            f"Active Strategies: {stats.get('active_strategies', 'N/A')}\n\n"
            f"Open Positions: {stats.get('open_positions', 0)}"
        )
        self._send_message(msg)

    def send_kill_switch_alert(self, reason: str):
        """Send emergency kill switch notification."""
        msg = (
            f"🚨🚨🚨 <b>KILL SWITCH ACTIVATED</b> 🚨🚨🚨\n\n"
            f"Reason: {reason}\n\n"
            f"All trading halted. Manual review required.\n"
            f"Open positions maintained with existing stops."
        )
        self._send_message(msg)

    # ── INBOUND: Receive and parse signals ──

    def poll_messages(self) -> list[ParsedSignal]:
        """
        Poll for new messages from Telegram.
        Returns list of parsed signals.
        """
        if not self.connected:
            return []

        signals = []
        try:
            import requests
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            params = {"offset": self.last_update_id + 1, "timeout": 5}
            resp = requests.get(url, params=params, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                for update in data.get("result", []):
                    self.last_update_id = update["update_id"]
                    msg = update.get("message", {}) or update.get("channel_post", {})
                    text = msg.get("text", "")
                    source = msg.get("chat", {}).get("title", "unknown")

                    if text:
                        parsed = self.parser.parse(text, source=source)
                        signals.append(parsed)
                        self.message_queue.append(parsed)

                        log.info(
                            f"TG Signal: [{parsed.signal_type}] "
                            f"{parsed.direction or 'N/A'} {parsed.asset or 'N/A'} "
                            f"| Cat={parsed.category} Pri={parsed.priority} "
                            f"Conf={parsed.confidence:.2f}"
                        )

        except Exception as e:
            log.error(f"Telegram poll error: {e}")

        return signals


# ═════════════════════════════════════════════════════════════
#  SECTION 3: EVENT SCHEDULER
#  ─────────────────────────────────────────────────────────
#  Automatically sends alerts at configured intervals
#  before, during, and after events.
# ═════════════════════════════════════════════════════════════

class EventScheduler:
    """
    Monitors the event calendar and triggers Telegram alerts
    at the appropriate times (pre, live, post).
    """

    def __init__(self, telegram_bridge: TelegramBridge):
        self.telegram = telegram_bridge
        self.sent_alerts = set()  # Track which alerts have been sent

    def check_and_alert(self, events: list[dict]):
        """Check all events and send appropriate alerts."""
        now = datetime.now(timezone.utc)

        for event in events:
            event_time = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
            time_until = (event_time - now).total_seconds()
            event_id = event["id"]

            config = event.get("telegramAlertConfig", {})

            # PRE-EVENT ALERT (4 hours before by default)
            pre_key = f"{event_id}_pre"
            pre_hours = self._parse_trigger_hours(config.get("preTrigger", "4hr before"))
            if 0 < time_until < pre_hours * 3600 and pre_key not in self.sent_alerts:
                self.telegram.send_event_alert(event, phase="pre")
                self.sent_alerts.add(pre_key)
                log.info(f"Pre-event alert sent: {event['title']}")

            # LIVE ALERT (within 5 minutes of event)
            live_key = f"{event_id}_live"
            if -300 < time_until < 300 and live_key not in self.sent_alerts:
                self.telegram.send_event_alert(event, phase="live")
                self.sent_alerts.add(live_key)
                log.info(f"Live event alert sent: {event['title']}")

            # POST-EVENT ALERT (15 minutes after)
            post_key = f"{event_id}_post"
            if -1800 < time_until < -900 and post_key not in self.sent_alerts:
                self.telegram.send_event_alert(event, phase="post")
                self.sent_alerts.add(post_key)
                log.info(f"Post-event alert sent: {event['title']}")

    def _parse_trigger_hours(self, trigger_str: str) -> float:
        """Parse trigger string like '4hr before' into hours."""
        match = re.search(r'(\d+)\s*hr', trigger_str)
        if match:
            return float(match.group(1))
        match = re.search(r'(\d+)\s*min', trigger_str)
        if match:
            return float(match.group(1)) / 60
        return 4.0  # Default 4 hours


# ═════════════════════════════════════════════════════════════
#  SECTION 4: SIGNAL-TO-HYDRA CONVERTER
#  ─────────────────────────────────────────────────────────
#  Converts ParsedSignal objects from Telegram into
#  HYDRA Signal objects that the engine can process.
# ═════════════════════════════════════════════════════════════

class SignalConverter:
    """
    Converts Telegram ParsedSignals into HYDRA engine Signal objects.
    This is the bridge between the Telegram world and the trading world.
    """

    # Map Telegram categories to HYDRA signal sources
    SOURCE_MAP = {
        "macro": "labor_data",
        "crypto": "funding_rate",
        "metals": "physical_premium",
        "tech": "narrative_velocity",
        "geopolitical": "narrative_velocity",
    }

    def convert(self, parsed: ParsedSignal) -> Optional[dict]:
        """
        Convert a ParsedSignal to a dict compatible with HYDRA's
        SignalAggregator.add_signal() method.

        Returns None if the signal doesn't meet minimum quality thresholds.
        """
        # Quality gate: must have minimum confidence
        if parsed.confidence < 0.4:
            return None

        # Quality gate: trade signals must have direction and asset
        if parsed.signal_type == "trade" and (not parsed.direction or not parsed.asset):
            return None

        # Map direction to numeric
        if parsed.direction == "BUY":
            direction = 1.0
        elif parsed.direction == "SELL":
            direction = -1.0
        else:
            direction = parsed.sentiment  # Use sentiment as direction proxy

        # Map to HYDRA signal source
        source = self.SOURCE_MAP.get(parsed.category, "narrative_velocity")

        # Determine target assets
        target_assets = [parsed.asset] if parsed.asset else []

        # Build TTL based on urgency
        ttl_map = {"immediate": 30, "normal": 120, "patient": 480}
        ttl = ttl_map.get(parsed.urgency, 120)

        return {
            "name": f"TG: {parsed.signal_type} ({parsed.source})",
            "source": source,
            "direction": direction,
            "strength": parsed.confidence,
            "asset_class": self._map_asset_class(parsed.category),
            "target_assets": target_assets,
            "ttl_minutes": ttl,
            "metadata": {
                "telegram_source": parsed.source,
                "raw_text": parsed.raw_text[:200],
                "signal_type": parsed.signal_type,
                "entry": parsed.entry_price,
                "stop": parsed.stop_loss,
                "target": parsed.take_profit,
                "matched_event": parsed.matched_event_id,
            }
        }

    def _map_asset_class(self, category: str) -> str:
        mapping = {
            "macro": "equity",
            "crypto": "crypto",
            "metals": "metals",
            "tech": "equity",
            "geopolitical": "equity",
        }
        return mapping.get(category, "equity")


# ═════════════════════════════════════════════════════════════
#  SECTION 5: INTEGRATED USAGE EXAMPLE
# ═════════════════════════════════════════════════════════════

def demo():
    """Demonstrate the full Telegram integration pipeline."""

    parser = SignalParser()
    converter = SignalConverter()

    # Test signals that would come from Telegram channels
    test_messages = [
        # Structured JSON signal
        '{"direction": "BUY", "asset": "BTC", "entry": 70000, "stop": 67000, "target": 78000, "confidence": 0.75}',

        # Free-text trade signal
        "🟢 BUY $SPY at 580, SL 570, TP 600. NFP expected weak, positioning for relief rally.",

        # Alert-style
        "⚠️ BREAKING: January NFP releasing in 1 hour. JOLTS was terrible. Expect high volatility.",

        # News-style
        "Anthropic just released new Claude plugins for healthcare vertical. Watch VEEV, TDOC.",

        # Crypto signal
        "🔴 SHORT BTC @ 71000. Funding rate at 0.08% — extreme long crowding. Liquidation cluster at 68K. SL 73000 TP 65000.",

        # Metals signal
        "Gold physical premium in Shanghai just flipped positive. CME margins unchanged. Buy GLD dip.",

        # Ambiguous signal
        "Markets look uncertain ahead of Fed testimony next week. Stay cautious.",
    ]

    print("=" * 70)
    print("  HYDRA — Telegram Signal Parser Demo")
    print("=" * 70)

    for i, msg in enumerate(test_messages):
        print(f"\n{'─' * 60}")
        print(f"  Message {i+1}: {msg[:80]}...")
        print(f"{'─' * 60}")

        parsed = parser.parse(msg, source="demo_channel")
        hydra_signal = converter.convert(parsed)

        print(f"  Type:       {parsed.signal_type}")
        print(f"  Direction:  {parsed.direction or 'N/A'}")
        print(f"  Asset:      {parsed.asset or 'N/A'}")
        print(f"  Entry:      ${parsed.entry_price:,.2f}" if parsed.entry_price else "  Entry:      N/A")
        print(f"  Stop:       ${parsed.stop_loss:,.2f}" if parsed.stop_loss else "  Stop:       N/A")
        print(f"  Target:     ${parsed.take_profit:,.2f}" if parsed.take_profit else "  Target:     N/A")
        print(f"  Category:   {parsed.category}")
        print(f"  Priority:   {parsed.priority}")
        print(f"  Confidence: {parsed.confidence:.2f}")
        print(f"  Sentiment:  {parsed.sentiment:+.2f}")
        print(f"  Event Match:{parsed.matched_event_id or 'None'}")
        print(f"  → HYDRA:    {'ACCEPTED' if hydra_signal else 'REJECTED (below threshold)'}")
        if hydra_signal:
            print(f"    Source:    {hydra_signal['source']}")
            print(f"    Direction: {hydra_signal['direction']:+.2f}")
            print(f"    TTL:       {hydra_signal['ttl_minutes']}min")


if __name__ == "__main__":
    demo()
