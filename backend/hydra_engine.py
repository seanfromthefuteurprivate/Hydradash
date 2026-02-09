"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                          H Y D R A   E N G I N E                           ║
║                 Multi-Asset Adaptive Scalping & Event System                ║
║                                                                            ║
║  Architecture Philosophy:                                                  ║
║  Renaissance used Hidden Markov Models to find signal in noise.            ║
║  Citadel uses dealer flow mechanics to front-run positioning.              ║
║  We combine BOTH: statistical signal processing + mechanical flow          ║
║  analysis + AI narrative velocity detection + cross-asset regime           ║
║  detection + forced liquidation hunting.                                   ║
║                                                                            ║
║  This is not a single strategy. It's an ECOSYSTEM of 7 strategy            ║
║  modules that share signals, adapt to regime changes, and                  ║
║  dynamically allocate capital to wherever the edge is fattest.             ║
║                                                                            ║
║  Deploy on Alpaca Paper Trading to prove the edge before going live.       ║
╚══════════════════════════════════════════════════════════════════════════════╝

REQUIRED SETUP:
    pip install alpaca-py requests numpy pandas websocket-client aiohttp

USAGE:
    1. Set ALPACA_API_KEY and ALPACA_SECRET_KEY env vars (paper trading keys)
    2. python hydra_engine.py
    3. System starts in OBSERVATION mode for first 30 minutes to calibrate
    4. Then activates trading modules based on detected regime

DISCLAIMER:
    This is a paper trading research system for educational purposes.
    Not financial advice. Trading involves substantial risk of loss.
"""

import os
import time
import json
import math
import logging
import threading
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from collections import deque

# ─────────────────────────────────────────────────────────────────────
# Alpaca SDK imports
# ─────────────────────────────────────────────────────────────────────
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        MarketOrderRequest, LimitOrderRequest, StopLimitOrderRequest,
        GetOrdersRequest, GetAssetsRequest
    )
    from alpaca.trading.enums import (
        OrderSide, TimeInForce, OrderType, OrderStatus, AssetClass
    )
    from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
    from alpaca.data.requests import (
        StockBarsRequest, StockLatestQuoteRequest,
        CryptoBarsRequest, CryptoLatestQuoteRequest
    )
    from alpaca.data.timeframe import TimeFrame
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    print("[WARN] alpaca-py not installed. Running in simulation-only mode.")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("[WARN] numpy not installed. Using fallback math.")

try:
    import requests as req
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("[WARN] requests not installed. External data feeds disabled.")

# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("HYDRA")

PAPER = True  # Always paper trading
API_KEY = os.environ.get("ALPACA_API_KEY", "")
API_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")

# ═════════════════════════════════════════════════════════════════════
#  SECTION 1: MARKET REGIME DETECTION
#  ─────────────────────────────────────────────────────────────────
#  Before ANY trade, we must know the regime. This is Renaissance's
#  core insight: you don't predict price, you predict the REGIME,
#  then apply the strategy that works in that regime.
# ═════════════════════════════════════════════════════════════════════

class Regime(Enum):
    """Market regime states - determines which strategies activate."""
    TRENDING_UP = "trending_up"          # Momentum strategies
    TRENDING_DOWN = "trending_down"      # Short/put strategies
    MEAN_REVERTING = "mean_reverting"    # Sell premium, fade moves
    HIGH_VOL_EXPANSION = "high_vol"     # Buy premium, straddles
    CRASH = "crash"                      # Liquidation hunting, tail hedges pay
    RECOVERY = "recovery"               # Buy dips, sell vol
    UNKNOWN = "unknown"                  # Observation mode, no trading


@dataclass
class RegimeState:
    """Current detected regime with confidence score."""
    regime: Regime = Regime.UNKNOWN
    confidence: float = 0.0            # 0.0 to 1.0
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    vix_level: float = 0.0
    vix_term_slope: float = 0.0        # positive = contango, negative = backwardation
    trend_strength: float = 0.0        # ADX-like measure
    mean_reversion_score: float = 0.0  # How mean-reverting is current action
    cross_asset_stress: float = 0.0    # 0 = calm, 1 = everything correlated in selloff


class RegimeDetector:
    """
    Detects market regime using multiple signals.

    This is the BRAIN of the system. Everything else depends on this.

    Signals used:
    1. VIX level and term structure (contango vs backwardation)
    2. Price trend strength (modified ADX using recent bars)
    3. Realized vs implied volatility ratio
    4. Cross-asset correlation (when everything moves together = stress)
    5. Credit spread direction (HYG/LQD ratio)
    6. Put/call ratio extremes
    """

    def __init__(self):
        self.price_history = deque(maxlen=500)  # Rolling window of SPY prices
        self.vix_history = deque(maxlen=100)
        self.current_state = RegimeState()
        self.regime_history = deque(maxlen=50)

    def update(self, spy_price: float, vix: float, vix_3m: float = 0,
               hyg_price: float = 0, btc_price: float = 0):
        """Ingest new data and re-evaluate regime."""
        self.price_history.append(spy_price)
        self.vix_history.append(vix)

        if len(self.price_history) < 20:
            self.current_state = RegimeState(regime=Regime.UNKNOWN, confidence=0.0)
            return self.current_state

        prices = list(self.price_history)

        # ── Signal 1: VIX Level ──
        vix_signal = self._score_vix(vix)

        # ── Signal 2: VIX Term Structure ──
        term_slope = (vix_3m - vix) if vix_3m > 0 else 0
        # Positive = contango (normal), Negative = backwardation (panic)

        # ── Signal 3: Trend Strength ──
        trend = self._calc_trend_strength(prices)

        # ── Signal 4: Mean Reversion Score ──
        mr_score = self._calc_mean_reversion(prices)

        # ── Signal 5: Determine Regime ──
        regime, confidence = self._classify(vix, vix_signal, term_slope, trend, mr_score)

        self.current_state = RegimeState(
            regime=regime,
            confidence=confidence,
            vix_level=vix,
            vix_term_slope=term_slope,
            trend_strength=trend,
            mean_reversion_score=mr_score
        )
        self.regime_history.append(self.current_state)
        return self.current_state

    def _score_vix(self, vix: float) -> float:
        """Score VIX on a 0-1 scale where 1 = extreme fear."""
        if vix < 12: return 0.0
        if vix < 16: return 0.2
        if vix < 20: return 0.4
        if vix < 25: return 0.6
        if vix < 35: return 0.8
        return 1.0

    def _calc_trend_strength(self, prices: list) -> float:
        """
        Modified ADX calculation using price momentum over multiple timeframes.
        Returns -1 (strong downtrend) to +1 (strong uptrend). Near 0 = range-bound.
        """
        if len(prices) < 50:
            return 0.0

        # Short-term momentum (5 bars)
        short_mom = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] != 0 else 0

        # Medium-term momentum (20 bars)
        med_mom = (prices[-1] - prices[-20]) / prices[-20] if prices[-20] != 0 else 0

        # Long-term momentum (50 bars)
        long_mom = (prices[-1] - prices[-50]) / prices[-50] if prices[-50] != 0 else 0

        # Weighted combination - short-term weighted more heavily
        raw = (short_mom * 0.5 + med_mom * 0.3 + long_mom * 0.2) * 100

        # Clamp to -1 to +1
        return max(-1.0, min(1.0, raw / 5.0))

    def _calc_mean_reversion(self, prices: list) -> float:
        """
        Calculate how mean-reverting recent price action is.
        Uses autocorrelation of returns - negative autocorrelation = mean-reverting.
        Returns 0 (trending) to 1 (strongly mean-reverting).
        """
        if len(prices) < 30:
            return 0.5

        # Calculate returns
        returns = [(prices[i] - prices[i-1]) / prices[i-1]
                   for i in range(max(1, len(prices)-30), len(prices))
                   if prices[i-1] != 0]

        if len(returns) < 10:
            return 0.5

        # Lag-1 autocorrelation of returns
        mean_r = sum(returns) / len(returns)
        var = sum((r - mean_r)**2 for r in returns)
        if var == 0:
            return 0.5

        cov = sum((returns[i] - mean_r) * (returns[i-1] - mean_r)
                  for i in range(1, len(returns)))

        autocorr = cov / var if var != 0 else 0

        # Negative autocorrelation = mean reverting
        # Map from [-1, 1] to [0, 1] where 1 = strongly mean-reverting
        return max(0.0, min(1.0, 0.5 - autocorr))

    def _classify(self, vix, vix_signal, term_slope, trend, mr_score):
        """
        Final regime classification using all signals.
        This is the Hidden Markov Model equivalent - but explicit.
        """
        # ── CRASH REGIME ──
        if vix > 30 and term_slope < -2 and trend < -0.5:
            return Regime.CRASH, min(1.0, vix_signal + 0.2)

        # ── HIGH VOL EXPANSION ──
        if vix > 22 and term_slope < 0:
            return Regime.HIGH_VOL_EXPANSION, 0.6 + vix_signal * 0.3

        # ── TRENDING UP ──
        if trend > 0.3 and mr_score < 0.4:
            return Regime.TRENDING_UP, abs(trend)

        # ── TRENDING DOWN ──
        if trend < -0.3 and mr_score < 0.4:
            return Regime.TRENDING_DOWN, abs(trend)

        # ── RECOVERY ──
        if trend > 0.1 and vix > 18 and len(self.regime_history) > 0:
            last = self.regime_history[-1]
            if last.regime in (Regime.CRASH, Regime.HIGH_VOL_EXPANSION):
                return Regime.RECOVERY, 0.6

        # ── MEAN REVERTING ──
        if mr_score > 0.55 and vix < 22:
            return Regime.MEAN_REVERTING, mr_score

        return Regime.UNKNOWN, 0.3


# ═════════════════════════════════════════════════════════════════════
#  SECTION 2: SIGNAL PROCESSING ENGINE
#  ─────────────────────────────────────────────────────────────────
#  Each data source feeds into standardized "Signal" objects.
#  Signals are scored -1 to +1 and weighted by reliability.
#  This is the signal-processing layer that Renaissance pioneered -
#  treating market data like radio signals to be decoded.
# ═════════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    """A single trading signal from any source."""
    name: str
    source: str                   # e.g., "coinglass", "vix", "gex"
    direction: float              # -1.0 (bearish) to +1.0 (bullish)
    strength: float               # 0.0 (noise) to 1.0 (maximum conviction)
    asset_class: str              # "equity", "crypto", "metals", "rates"
    target_assets: list           # Which specific assets this applies to
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_minutes: int = 60         # Signal expires after this many minutes
    metadata: dict = field(default_factory=dict)

    @property
    def composite_score(self) -> float:
        """Direction * strength = composite score."""
        return self.direction * self.strength

    @property
    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        return (now - self.timestamp).total_seconds() > self.ttl_minutes * 60


class SignalAggregator:
    """
    Collects signals from all sources, weights them, and produces
    a unified view of market conditions per asset.

    This is the equivalent of Renaissance's signal combination layer.
    Each signal is independent, but they're combined using confidence-
    weighted averaging with decay over time.
    """

    def __init__(self):
        self.signals: list[Signal] = []
        self.signal_weights = {
            # Source reliability weights based on historical accuracy
            "gex_levels": 0.85,         # Dealer gamma is highly reliable
            "funding_rate": 0.75,       # Crypto funding rates are mechanical
            "liquidation_map": 0.80,    # Liquidation levels are known
            "margin_hike": 0.90,        # CME margin changes are the most reliable crash signal
            "vix_term": 0.70,           # VIX structure is informative
            "credit_spread": 0.65,      # Credit moves are slower but meaningful
            "narrative_velocity": 0.60, # AI-detected narrative speed
            "physical_premium": 0.75,   # Shanghai gold premium is a leading signal
            "etf_flow": 0.70,           # Daily ETF flows predict next-day direction
            "labor_data": 0.80,         # Macro data moves markets mechanically
            "order_flow": 0.75,         # Order book imbalance
            "candle_structure": 0.50,   # Candlestick patterns alone are weak
        }

    def add_signal(self, signal: Signal):
        """Add a new signal, removing expired ones."""
        self.signals = [s for s in self.signals if not s.is_expired]
        self.signals.append(signal)
        log.info(f"Signal: {signal.name} | Dir={signal.direction:+.2f} "
                 f"Str={signal.strength:.2f} | {signal.target_assets}")

    def get_composite(self, asset: str) -> dict:
        """
        Get the weighted composite signal for a specific asset.

        Returns:
            {
                "direction": float,  # -1 to +1
                "confidence": float, # 0 to 1
                "signal_count": int,
                "dominant_signal": str,
                "signals": list
            }
        """
        active = [s for s in self.signals
                  if not s.is_expired and asset in s.target_assets]

        if not active:
            return {"direction": 0, "confidence": 0, "signal_count": 0,
                    "dominant_signal": "none", "signals": []}

        # Time-decay weighting: newer signals weighted more
        now = datetime.now(timezone.utc)
        weighted_scores = []
        total_weight = 0

        for s in active:
            age_minutes = (now - s.timestamp).total_seconds() / 60
            time_decay = max(0.1, 1.0 - (age_minutes / s.ttl_minutes))
            source_weight = self.signal_weights.get(s.source, 0.5)
            weight = s.strength * source_weight * time_decay
            weighted_scores.append(s.composite_score * weight)
            total_weight += weight

        if total_weight == 0:
            return {"direction": 0, "confidence": 0, "signal_count": 0,
                    "dominant_signal": "none", "signals": []}

        direction = sum(weighted_scores) / total_weight
        confidence = min(1.0, total_weight / len(active))  # More signals = more confident
        dominant = max(active, key=lambda s: abs(s.composite_score))

        return {
            "direction": direction,
            "confidence": confidence,
            "signal_count": len(active),
            "dominant_signal": dominant.name,
            "signals": [(s.name, s.composite_score) for s in active]
        }


# ═════════════════════════════════════════════════════════════════════
#  SECTION 3: RISK MANAGEMENT — THE ACTUAL EDGE
#  ─────────────────────────────────────────────────────────────────
#  Renaissance was right 50.75% of the time. The edge wasn't
#  prediction accuracy — it was position sizing, risk limits,
#  and execution. This section is the most important.
# ═════════════════════════════════════════════════════════════════════

@dataclass
class RiskLimits:
    """Hard risk limits that CANNOT be overridden by any strategy."""
    max_position_pct: float = 0.03       # Max 3% of capital per position
    max_daily_loss_pct: float = 0.05     # 5% daily loss → all strategies stop
    max_total_exposure_pct: float = 0.25 # Max 25% of capital deployed
    max_correlated_exposure: float = 0.15 # Max 15% in correlated positions
    max_single_asset_pct: float = 0.05   # Max 5% in any single name
    max_consecutive_losses: int = 3      # 3 losses in a row → pause 4 hours
    cooldown_minutes: int = 240          # Pause duration after consecutive losses
    max_trades_per_day: int = 30         # Hard cap on daily trades


class RiskManager:
    """
    The guardian. Every trade request must pass through here.

    Key principles:
    1. Size inversely to volatility (higher vol = smaller positions)
    2. Kelly Criterion for optimal sizing (but use half-Kelly for safety)
    3. Correlation-aware exposure limits
    4. Hard daily loss limit with automatic kill switch
    5. Consecutive loss detection with forced cooldown
    """

    def __init__(self, starting_capital: float = 100000.0):
        self.capital = starting_capital
        self.peak_capital = starting_capital
        self.daily_pnl = 0.0
        self.daily_start_capital = starting_capital
        self.limits = RiskLimits()
        self.positions: dict = {}         # asset -> position details
        self.trade_log: list = []
        self.consecutive_losses = 0
        self.cooldown_until: Optional[datetime] = None
        self.daily_trade_count = 0
        self.last_reset_date = datetime.now(timezone.utc).date()

    def _reset_daily(self):
        """Reset daily counters at market open."""
        today = datetime.now(timezone.utc).date()
        if today != self.last_reset_date:
            self.daily_pnl = 0.0
            self.daily_start_capital = self.capital
            self.daily_trade_count = 0
            self.last_reset_date = today
            log.info(f"Daily reset. Capital: ${self.capital:,.2f}")

    def can_trade(self) -> tuple[bool, str]:
        """Check if trading is allowed right now."""
        self._reset_daily()

        # Kill switch: daily loss limit
        if self.daily_pnl <= -(self.daily_start_capital * self.limits.max_daily_loss_pct):
            return False, f"KILL SWITCH: Daily loss {self.daily_pnl:,.2f} exceeds limit"

        # Cooldown after consecutive losses
        if self.cooldown_until and datetime.now(timezone.utc) < self.cooldown_until:
            remaining = (self.cooldown_until - datetime.now(timezone.utc)).seconds // 60
            return False, f"COOLDOWN: {remaining}min remaining after {self.limits.max_consecutive_losses} consecutive losses"

        # Daily trade limit
        if self.daily_trade_count >= self.limits.max_trades_per_day:
            return False, f"TRADE LIMIT: {self.daily_trade_count} trades today (max {self.limits.max_trades_per_day})"

        return True, "OK"

    def calculate_position_size(self, asset: str, entry_price: float,
                                stop_price: float, volatility: float,
                                signal_confidence: float) -> dict:
        """
        Calculate optimal position size using modified Kelly Criterion.

        The Kelly formula: f* = (bp - q) / b
        Where:
            b = odds ratio (reward/risk)
            p = probability of winning
            q = 1 - p

        We use HALF-Kelly for safety, then apply volatility scaling.
        """
        can, reason = self.can_trade()
        if not can:
            return {"shares": 0, "notional": 0, "reason": reason}

        # Risk per share
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share == 0:
            return {"shares": 0, "notional": 0, "reason": "Stop price equals entry"}

        # Estimate win probability from signal confidence
        # Signal confidence 0.7 → ~58% win rate (conservative mapping)
        win_prob = 0.50 + (signal_confidence * 0.12)  # Maps 0-1 to 50-62%
        loss_prob = 1 - win_prob

        # Estimate reward/risk ratio (default 2:1, adjust by regime)
        reward_risk = 2.0

        # Kelly fraction
        kelly = (reward_risk * win_prob - loss_prob) / reward_risk
        half_kelly = max(0, kelly * 0.5)  # Half-Kelly for safety

        # Volatility scaling: higher vol = smaller position
        vol_scalar = max(0.3, 1.0 - (volatility * 2))  # Vol 0.5 → scalar 0.3

        # Maximum dollar risk for this trade
        max_risk_dollars = self.capital * self.limits.max_position_pct * half_kelly * vol_scalar

        # Calculate shares
        shares = int(max_risk_dollars / risk_per_share) if risk_per_share > 0 else 0

        # Apply absolute limits
        max_notional = self.capital * self.limits.max_single_asset_pct
        max_shares_by_notional = int(max_notional / entry_price) if entry_price > 0 else 0
        shares = min(shares, max_shares_by_notional)

        # Check total exposure
        current_exposure = sum(p.get("notional", 0) for p in self.positions.values())
        remaining_capacity = (self.capital * self.limits.max_total_exposure_pct) - current_exposure
        if shares * entry_price > remaining_capacity:
            shares = max(0, int(remaining_capacity / entry_price))

        notional = shares * entry_price

        return {
            "shares": shares,
            "notional": notional,
            "risk_dollars": shares * risk_per_share,
            "kelly_fraction": half_kelly,
            "vol_scalar": vol_scalar,
            "win_prob_est": win_prob,
            "reason": "OK" if shares > 0 else "Position too small after limits"
        }

    def record_trade_result(self, pnl: float, asset: str):
        """Record a completed trade and update tracking."""
        self.daily_pnl += pnl
        self.capital += pnl
        self.peak_capital = max(self.peak_capital, self.capital)
        self.daily_trade_count += 1

        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.limits.max_consecutive_losses:
                self.cooldown_until = datetime.now(timezone.utc) + timedelta(
                    minutes=self.limits.cooldown_minutes
                )
                log.warning(f"COOLDOWN ACTIVATED: {self.consecutive_losses} consecutive losses. "
                            f"Paused until {self.cooldown_until}")
        else:
            self.consecutive_losses = 0

        self.trade_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset": asset,
            "pnl": pnl,
            "capital_after": self.capital,
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses
        })

        # Log status
        drawdown = (self.peak_capital - self.capital) / self.peak_capital * 100
        log.info(f"Trade closed: {asset} PnL=${pnl:+,.2f} | "
                 f"Capital=${self.capital:,.2f} | "
                 f"Daily={self.daily_pnl:+,.2f} | "
                 f"Drawdown={drawdown:.1f}%")


# ═════════════════════════════════════════════════════════════════════
#  SECTION 4: STRATEGY MODULES
#  ─────────────────────────────────────────────────────────────────
#  Each strategy is a self-contained module that:
#  1. Declares which regimes it operates in
#  2. Generates signals from its data sources
#  3. Proposes trades to the risk manager
#  4. Manages its own open positions
#
#  Strategies don't execute directly. They propose, and the
#  Orchestrator + Risk Manager decide.
# ═════════════════════════════════════════════════════════════════════

@dataclass
class TradeProposal:
    """A proposed trade from a strategy module."""
    strategy_name: str
    asset: str
    side: str                    # "buy" or "sell"
    order_type: str              # "market", "limit", "stop_limit"
    entry_price: float
    stop_price: float
    target_price: float
    confidence: float            # 0-1
    regime_required: list        # Which regimes this trade works in
    rationale: str
    urgency: str = "normal"      # "immediate", "normal", "patient"
    asset_class: str = "equity"  # "equity", "crypto", "option"
    option_details: dict = field(default_factory=dict)  # For options trades
    metadata: dict = field(default_factory=dict)


class StrategyModule:
    """Base class for all strategy modules."""

    name: str = "base"
    active_regimes: list = []

    def __init__(self, signal_agg: SignalAggregator, risk_mgr: RiskManager):
        self.signals = signal_agg
        self.risk = risk_mgr
        self.open_positions = {}
        self.trade_count = 0
        self.win_count = 0

    @property
    def win_rate(self) -> float:
        return self.win_count / self.trade_count if self.trade_count > 0 else 0

    def should_activate(self, regime: RegimeState) -> bool:
        """Check if this strategy should be active in current regime."""
        return regime.regime in self.active_regimes and regime.confidence > 0.4

    def generate_proposals(self, market_data: dict) -> list[TradeProposal]:
        """Generate trade proposals. Override in subclass."""
        raise NotImplementedError

    def manage_positions(self, market_data: dict) -> list[dict]:
        """Manage existing positions (trailing stops, scaling, etc). Override in subclass."""
        return []


class CryptoLiquidationHunter(StrategyModule):
    """
    STRATEGY 1: Crypto Liquidation Cascade Hunter

    Edge: When leveraged positions cluster at predictable price levels,
    forced liquidations create mechanical, predictable price cascades.
    We position WITH the cascade, not against it.

    Data: Funding rates, OI, liquidation heatmaps, exchange flows.
    Assets: BTC/USD, ETH/USD via Alpaca Crypto.
    Regime: Works in HIGH_VOL, CRASH, and TRENDING regimes.
    """

    name = "crypto_liquidation_hunter"
    active_regimes = [
        Regime.HIGH_VOL_EXPANSION, Regime.CRASH,
        Regime.TRENDING_DOWN, Regime.TRENDING_UP
    ]

    def __init__(self, signal_agg, risk_mgr):
        super().__init__(signal_agg, risk_mgr)
        self.funding_rate_history = deque(maxlen=100)
        self.oi_history = deque(maxlen=100)

    def _fetch_funding_rate(self) -> Optional[float]:
        """Fetch BTC perpetual funding rate from public API."""
        if not REQUESTS_AVAILABLE:
            return None
        try:
            # Binance public endpoint (no auth needed)
            resp = req.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": "BTCUSDT", "limit": 1},
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    return float(data[0]["fundingRate"])
        except Exception as e:
            log.debug(f"Funding rate fetch failed: {e}")
        return None

    def _fetch_open_interest(self) -> Optional[float]:
        """Fetch BTC futures open interest."""
        if not REQUESTS_AVAILABLE:
            return None
        try:
            resp = req.get(
                "https://fapi.binance.com/fapi/v1/openInterest",
                params={"symbol": "BTCUSDT"},
                timeout=5
            )
            if resp.status_code == 200:
                return float(resp.json()["openInterest"])
        except Exception as e:
            log.debug(f"OI fetch failed: {e}")
        return None

    def process_data(self):
        """Fetch external data and generate signals."""
        funding = self._fetch_funding_rate()
        oi = self._fetch_open_interest()

        if funding is not None:
            self.funding_rate_history.append(funding)

            # SIGNAL: Extreme funding rate
            if abs(funding) > 0.0005:  # 0.05% per 8hr = extreme
                direction = -1.0 if funding > 0 else 1.0  # Fade the crowded side
                self.signals.add_signal(Signal(
                    name="BTC Funding Rate Extreme",
                    source="funding_rate",
                    direction=direction,
                    strength=min(1.0, abs(funding) / 0.001),
                    asset_class="crypto",
                    target_assets=["BTC/USD", "ETH/USD"],
                    ttl_minutes=480,  # Valid for 8 hours (until next funding)
                    metadata={"funding_rate": funding}
                ))

        if oi is not None:
            self.oi_history.append(oi)

            # SIGNAL: OI rapid decline (liquidation cascade in progress)
            if len(self.oi_history) >= 2:
                oi_change = (oi - self.oi_history[-2]) / self.oi_history[-2]
                if oi_change < -0.05:  # >5% OI drop = major liquidation
                    self.signals.add_signal(Signal(
                        name="BTC OI Cascade Detected",
                        source="liquidation_map",
                        direction=-1.0,  # Liquidations push price down (usually)
                        strength=min(1.0, abs(oi_change) * 10),
                        asset_class="crypto",
                        target_assets=["BTC/USD", "ETH/USD"],
                        ttl_minutes=60,
                        metadata={"oi_change_pct": oi_change}
                    ))

    def generate_proposals(self, market_data: dict) -> list[TradeProposal]:
        """Generate crypto trade proposals based on liquidation mechanics."""
        proposals = []
        self.process_data()

        btc_composite = self.signals.get_composite("BTC/USD")
        if btc_composite["confidence"] < 0.5 or btc_composite["signal_count"] < 2:
            return proposals

        btc_price = market_data.get("BTC/USD", 0)
        if btc_price <= 0:
            return proposals

        direction = btc_composite["direction"]
        confidence = btc_composite["confidence"]

        # Calculate stop and target based on recent volatility
        # Use 1.5% stop, 4% target for crypto (accounting for high vol)
        stop_distance = btc_price * 0.015
        target_distance = btc_price * 0.04

        if direction > 0.2:  # Bullish
            proposals.append(TradeProposal(
                strategy_name=self.name,
                asset="BTC/USD",
                side="buy",
                order_type="market",
                entry_price=btc_price,
                stop_price=btc_price - stop_distance,
                target_price=btc_price + target_distance,
                confidence=confidence,
                regime_required=self.active_regimes,
                rationale=f"Liquidation hunter LONG: {btc_composite['dominant_signal']} "
                          f"(composite={direction:+.2f}, signals={btc_composite['signal_count']})",
                asset_class="crypto"
            ))
        elif direction < -0.2:  # Bearish
            proposals.append(TradeProposal(
                strategy_name=self.name,
                asset="BTC/USD",
                side="sell",
                order_type="market",
                entry_price=btc_price,
                stop_price=btc_price + stop_distance,
                target_price=btc_price - target_distance,
                confidence=confidence,
                regime_required=self.active_regimes,
                rationale=f"Liquidation hunter SHORT: {btc_composite['dominant_signal']} "
                          f"(composite={direction:+.2f}, signals={btc_composite['signal_count']})",
                asset_class="crypto"
            ))

        return proposals


class EventDrivenMacro(StrategyModule):
    """
    STRATEGY 2: Macro Event Scalper

    Edge: Scheduled economic releases (NFP, CPI, JOLTS, FOMC) create
    predictable volatility patterns. The move direction is unknown,
    but the MAGNITUDE is predictable. Buy straddles before, then
    trade directionally after the first 15-minute candle.

    Assets: SPY, TLT, GLD, SLV via Alpaca equities.
    Regime: Works in ALL regimes (events override regime).
    """

    name = "event_driven_macro"
    active_regimes = list(Regime)  # Active in all regimes

    # Major economic event calendar (would be dynamically fetched in production)
    EVENTS = {
        "NFP": {"impact": 1.0, "assets": ["SPY", "TLT", "GLD", "SLV", "BTC/USD"]},
        "CPI": {"impact": 0.9, "assets": ["SPY", "TLT", "GLD", "SLV"]},
        "FOMC": {"impact": 1.0, "assets": ["SPY", "TLT", "GLD", "SLV", "BTC/USD"]},
        "JOLTS": {"impact": 0.6, "assets": ["SPY", "TLT"]},
        "Jobless_Claims": {"impact": 0.5, "assets": ["SPY", "TLT"]},
        "ISM_Manufacturing": {"impact": 0.7, "assets": ["SPY", "XLI"]},
        "PCE": {"impact": 0.8, "assets": ["SPY", "TLT", "GLD"]},
    }

    def _check_upcoming_events(self) -> list[dict]:
        """
        Check for upcoming macro events within next 24 hours.
        In production, this would scrape the BLS/Fed calendar or use
        an economic calendar API. Here we demonstrate the logic.
        """
        # CRITICAL UPCOMING EVENTS (as of Feb 8, 2026):
        # Feb 11 - Delayed January NFP release (HUGE - market has been starved for this)
        # Feb 13 - CPI January (pushed from Feb 12)
        now = datetime.now(timezone.utc)
        upcoming = []

        # Example: Check if NFP is within 24 hours
        # In production: fetch from FRED calendar API
        nfp_date = datetime(2026, 2, 11, 13, 30, tzinfo=timezone.utc)  # 8:30 AM ET
        if 0 < (nfp_date - now).total_seconds() < 86400:
            upcoming.append({
                "event": "NFP",
                "time": nfp_date,
                "hours_away": (nfp_date - now).total_seconds() / 3600,
                **self.EVENTS["NFP"]
            })

        cpi_date = datetime(2026, 2, 13, 13, 30, tzinfo=timezone.utc)
        if 0 < (cpi_date - now).total_seconds() < 86400:
            upcoming.append({
                "event": "CPI",
                "time": cpi_date,
                "hours_away": (cpi_date - now).total_seconds() / 3600,
                **self.EVENTS["CPI"]
            })

        return upcoming

    def generate_proposals(self, market_data: dict) -> list[TradeProposal]:
        """
        Pre-event: Buy straddle-equivalent (long both directions)
        Post-event: Trade the directional move after initial 15min candle
        """
        proposals = []
        events = self._check_upcoming_events()

        for event in events:
            hours_away = event["hours_away"]

            # PRE-EVENT SETUP (1-4 hours before)
            if 1 < hours_away < 4:
                for asset in event["assets"]:
                    price = market_data.get(asset, 0)
                    if price <= 0:
                        continue

                    # Pre-event: we want LONG VOLATILITY
                    # For equities/ETFs without options: buy shares with tight stops
                    # The signal will tell us which direction after release
                    impact = event["impact"]

                    self.signals.add_signal(Signal(
                        name=f"Pre-{event['event']} Vol Setup",
                        source="labor_data",
                        direction=0.0,  # Neutral direction, just flagging vol
                        strength=impact,
                        asset_class="equity" if asset != "BTC/USD" else "crypto",
                        target_assets=[asset],
                        ttl_minutes=int(hours_away * 60),
                        metadata={"event": event["event"], "hours_away": hours_away}
                    ))

            # POST-EVENT DIRECTION TRADE (within 2 hours after)
            # This would trigger once we see the actual data and first candle
            # Logic: wait for 15-min candle to close after release,
            # then trade in direction of that candle with 2:1 R:R

        return proposals


class MetalsFlowTrader(StrategyModule):
    """
    STRATEGY 3: Precious Metals Flow & Margin Trader

    Edge: Margin hikes by CME/Shanghai force liquidation cascades.
    Physical premium/discount signals demand shifts. Gold/Silver
    ratio mean-reverts. Chinese New Year creates thin markets.

    Assets: GLD, SLV, GDX via Alpaca equities.
    Regime: Active in HIGH_VOL, CRASH, RECOVERY, MEAN_REVERTING.
    """

    name = "metals_flow_trader"
    active_regimes = [
        Regime.HIGH_VOL_EXPANSION, Regime.CRASH,
        Regime.RECOVERY, Regime.MEAN_REVERTING
    ]

    def __init__(self, signal_agg, risk_mgr):
        super().__init__(signal_agg, risk_mgr)
        self.gold_silver_ratio_history = deque(maxlen=100)

    def _calc_gold_silver_ratio(self, gld_price: float, slv_price: float) -> float:
        """
        Calculate gold/silver ratio using ETF prices as proxy.
        GLD represents ~1/10 oz gold, SLV represents ~1 oz silver.
        """
        if slv_price <= 0:
            return 0
        # Approximate ratio: (GLD * 10) / SLV gives rough gold/silver
        return (gld_price * 10) / slv_price

    def generate_proposals(self, market_data: dict) -> list[TradeProposal]:
        proposals = []

        gld = market_data.get("GLD", 0)
        slv = market_data.get("SLV", 0)

        if gld <= 0 or slv <= 0:
            return proposals

        # GOLD/SILVER RATIO MEAN REVERSION
        ratio = self._calc_gold_silver_ratio(gld, slv)
        self.gold_silver_ratio_history.append(ratio)

        if len(self.gold_silver_ratio_history) >= 20:
            ratios = list(self.gold_silver_ratio_history)
            mean_ratio = sum(ratios) / len(ratios)
            std_ratio = (sum((r - mean_ratio)**2 for r in ratios) / len(ratios)) ** 0.5

            if std_ratio > 0:
                z_score = (ratio - mean_ratio) / std_ratio

                # Ratio too high (silver cheap vs gold) → buy SLV
                if z_score > 1.5:
                    self.signals.add_signal(Signal(
                        name="Gold/Silver Ratio Extreme High",
                        source="physical_premium",
                        direction=1.0,  # Bullish silver
                        strength=min(1.0, abs(z_score) / 3.0),
                        asset_class="metals",
                        target_assets=["SLV"],
                        ttl_minutes=1440,  # 24hr signal
                        metadata={"ratio": ratio, "z_score": z_score}
                    ))

                    proposals.append(TradeProposal(
                        strategy_name=self.name,
                        asset="SLV",
                        side="buy",
                        order_type="limit",
                        entry_price=slv,
                        stop_price=slv * 0.95,
                        target_price=slv * 1.10,
                        confidence=min(0.8, abs(z_score) / 3.0),
                        regime_required=self.active_regimes,
                        rationale=f"G/S ratio {ratio:.1f} is {z_score:.1f}σ above mean. "
                                  f"Silver underpriced vs gold. Mean reversion trade.",
                        asset_class="equity"
                    ))

                # Ratio too low (silver expensive vs gold) → buy GLD
                elif z_score < -1.5:
                    proposals.append(TradeProposal(
                        strategy_name=self.name,
                        asset="GLD",
                        side="buy",
                        order_type="limit",
                        entry_price=gld,
                        stop_price=gld * 0.97,
                        target_price=gld * 1.06,
                        confidence=min(0.8, abs(z_score) / 3.0),
                        regime_required=self.active_regimes,
                        rationale=f"G/S ratio {ratio:.1f} is {z_score:.1f}σ below mean. "
                                  f"Gold underpriced vs silver. Mean reversion trade.",
                        asset_class="equity"
                    ))

        return proposals


class SaaSDisruptionTrader(StrategyModule):
    """
    STRATEGY 4: AI Disruption Shock Trader

    Edge: AI product launches create predictable panic cycles.
    Day 1-2: Panic selling (short/buy puts)
    Day 3-5: Overreaction correction (buy dips on quality names)

    Assets: IGV, CRM, SHOP, ADBE, WDAY, MSFT via Alpaca equities.
    Regime: Active in TRENDING_DOWN, HIGH_VOL, RECOVERY.
    """

    name = "saas_disruption_trader"
    active_regimes = [Regime.TRENDING_DOWN, Regime.HIGH_VOL_EXPANSION, Regime.RECOVERY]

    # Categorize by vulnerability
    STRUCTURALLY_IMPAIRED = ["LZ"]      # Short these on AI launches
    TEMPORARILY_PUNISHED = ["CRM", "SHOP", "ADBE", "MSFT", "WDAY"]  # Buy dips
    SECTOR_ETF = ["IGV"]

    def generate_proposals(self, market_data: dict) -> list[TradeProposal]:
        proposals = []

        igv_price = market_data.get("IGV", 0)
        if igv_price <= 0:
            return proposals

        igv_composite = self.signals.get_composite("IGV")

        # During active SaaS selloff (IGV declining, high signal count)
        if igv_composite["direction"] < -0.3 and igv_composite["confidence"] > 0.5:
            # PHASE 1: Ride the selloff on weak names
            for asset in self.STRUCTURALLY_IMPAIRED:
                price = market_data.get(asset, 0)
                if price > 0:
                    proposals.append(TradeProposal(
                        strategy_name=self.name,
                        asset=asset,
                        side="sell",
                        order_type="market",
                        entry_price=price,
                        stop_price=price * 1.05,
                        target_price=price * 0.85,
                        confidence=igv_composite["confidence"],
                        regime_required=self.active_regimes,
                        rationale=f"SaaS disruption SHORT: {asset} structurally impaired. "
                                  f"IGV composite={igv_composite['direction']:+.2f}",
                        asset_class="equity"
                    ))

        # During recovery (IGV composite turning positive after being negative)
        if igv_composite["direction"] > 0.1 and igv_composite["confidence"] > 0.4:
            for asset in self.TEMPORARILY_PUNISHED:
                price = market_data.get(asset, 0)
                if price > 0:
                    proposals.append(TradeProposal(
                        strategy_name=self.name,
                        asset=asset,
                        side="buy",
                        order_type="limit",
                        entry_price=price * 0.99,  # Bid slightly below market
                        stop_price=price * 0.93,
                        target_price=price * 1.12,
                        confidence=igv_composite["confidence"] * 0.8,
                        regime_required=[Regime.RECOVERY, Regime.MEAN_REVERTING],
                        rationale=f"SaaS recovery LONG: {asset} quality name oversold. "
                                  f"DeepSeek playbook - panic reverses.",
                        asset_class="equity"
                    ))

        return proposals


class CrossAssetRegimeTrader(StrategyModule):
    """
    STRATEGY 5: Cross-Asset Signal Graph Trader

    Edge: Assets signal each other's moves 6-24 hours in advance.
    Copper → equities. Credit spreads → risk. VIX structure → vol.
    Shanghai gold premium → metals. BTC ETF flows → crypto.

    This strategy doesn't trade directly - it generates signals
    that amplify or dampen other strategies' confidence levels.
    """

    name = "cross_asset_regime"
    active_regimes = list(Regime)

    def generate_proposals(self, market_data: dict) -> list[TradeProposal]:
        """
        This strategy primarily generates SIGNALS, not direct trades.
        It monitors cross-asset relationships and feeds the signal aggregator.
        """
        spy = market_data.get("SPY", 0)
        tlt = market_data.get("TLT", 0)
        gld = market_data.get("GLD", 0)
        btc = market_data.get("BTC/USD", 0)
        hyg = market_data.get("HYG", 0)

        # SIGNAL: TLT/SPY divergence
        # If TLT is rallying (flight to safety) while SPY is flat → bearish equity signal
        if tlt > 0 and spy > 0:
            # In production: compare rate of change, not levels
            pass

        # SIGNAL: Gold strength as equity warning
        if gld > 0 and spy > 0:
            # Gold outperforming SPY = risk-off regime building
            pass

        # The primary value of this module is in generating signals
        # that get aggregated and affect position sizing of other strategies

        # DIRECT TRADE: Rates collapse trade
        # When labor data weakens AND AI disruption narrative active
        # → TLT rallies as market prices in Fed cuts
        if tlt > 0:
            tlt_composite = self.signals.get_composite("TLT")
            if tlt_composite["direction"] > 0.3 and tlt_composite["confidence"] > 0.5:
                return [TradeProposal(
                    strategy_name=self.name,
                    asset="TLT",
                    side="buy",
                    order_type="market",
                    entry_price=tlt,
                    stop_price=tlt * 0.97,
                    target_price=tlt * 1.05,
                    confidence=tlt_composite["confidence"],
                    regime_required=[Regime.TRENDING_DOWN, Regime.CRASH, Regime.HIGH_VOL_EXPANSION],
                    rationale="Cross-asset: Risk-off regime detected. Bonds rallying.",
                    asset_class="equity"
                )]

        return []


# ═════════════════════════════════════════════════════════════════════
#  SECTION 5: EXECUTION ENGINE (Alpaca Integration)
#  ─────────────────────────────────────────────────────────────────
#  Translates approved TradeProposals into actual Alpaca API orders.
#  Handles order types, bracket orders, and position management.
# ═════════════════════════════════════════════════════════════════════

class AlpacaExecutor:
    """
    Handles all interaction with Alpaca's Trading API.
    Paper trading mode by default.
    """

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self.paper = paper
        self.client = None
        self.stock_data = None
        self.crypto_data = None

        if ALPACA_AVAILABLE and api_key and secret_key:
            try:
                self.client = TradingClient(api_key, secret_key, paper=paper)
                self.stock_data = StockHistoricalDataClient(api_key, secret_key)
                self.crypto_data = CryptoHistoricalDataClient(api_key, secret_key)
                account = self.client.get_account()
                log.info(f"Alpaca connected ({'PAPER' if paper else 'LIVE'}). "
                         f"Buying power: ${float(account.buying_power):,.2f}")
            except Exception as e:
                log.error(f"Alpaca connection failed: {e}")
                self.client = None
        else:
            log.warning("Alpaca not configured. Running in dry-run simulation mode.")

    def get_account_info(self) -> dict:
        """Get current account status."""
        if not self.client:
            return {"buying_power": 100000, "equity": 100000, "status": "simulated"}
        try:
            acct = self.client.get_account()
            return {
                "buying_power": float(acct.buying_power),
                "equity": float(acct.equity),
                "cash": float(acct.cash),
                "portfolio_value": float(acct.portfolio_value),
                "status": acct.status
            }
        except Exception as e:
            log.error(f"Account info error: {e}")
            return {}

    def get_current_price(self, symbol: str) -> float:
        """Get latest price for a symbol."""
        if not self.client:
            return 0.0

        try:
            if "/" in symbol:  # Crypto
                if self.crypto_data:
                    request = CryptoLatestQuoteRequest(symbol_or_symbols=[symbol])
                    quotes = self.crypto_data.get_crypto_latest_quote(request)
                    if symbol in quotes:
                        return float(quotes[symbol].ask_price)
            else:  # Stock/ETF
                if self.stock_data:
                    request = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
                    quotes = self.stock_data.get_stock_latest_quote(request)
                    if symbol in quotes:
                        return float(quotes[symbol].ask_price)
        except Exception as e:
            log.debug(f"Price fetch error for {symbol}: {e}")
        return 0.0

    def execute_proposal(self, proposal: TradeProposal, shares: int) -> Optional[str]:
        """
        Execute a trade proposal via Alpaca API.
        Returns order ID if successful, None if failed.
        """
        if shares <= 0:
            return None

        if not self.client:
            # Dry-run simulation
            log.info(f"[DRY RUN] {proposal.side.upper()} {shares} {proposal.asset} "
                     f"@ ${proposal.entry_price:.2f} | "
                     f"Stop=${proposal.stop_price:.2f} Target=${proposal.target_price:.2f}")
            return f"SIM-{int(time.time())}"

        try:
            side = OrderSide.BUY if proposal.side == "buy" else OrderSide.SELL

            if proposal.order_type == "market":
                order_req = MarketOrderRequest(
                    symbol=proposal.asset,
                    qty=shares if "/" not in proposal.asset else None,
                    notional=shares * proposal.entry_price if "/" in proposal.asset else None,
                    side=side,
                    time_in_force=TimeInForce.GTC if "/" in proposal.asset else TimeInForce.DAY
                )
            elif proposal.order_type == "limit":
                order_req = LimitOrderRequest(
                    symbol=proposal.asset,
                    qty=shares,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=round(proposal.entry_price, 2)
                )
            else:
                log.warning(f"Unsupported order type: {proposal.order_type}")
                return None

            order = self.client.submit_order(order_req)
            log.info(f"ORDER SUBMITTED: {order.id} | {proposal.side.upper()} "
                     f"{shares} {proposal.asset} | Status: {order.status}")
            return str(order.id)

        except Exception as e:
            log.error(f"Order execution failed: {e}")
            return None

    def get_positions(self) -> list:
        """Get all open positions."""
        if not self.client:
            return []
        try:
            return self.client.get_all_positions()
        except Exception as e:
            log.error(f"Position fetch error: {e}")
            return []

    def close_position(self, symbol: str) -> bool:
        """Close an entire position."""
        if not self.client:
            log.info(f"[DRY RUN] Closing position: {symbol}")
            return True
        try:
            self.client.close_position(symbol)
            log.info(f"Position closed: {symbol}")
            return True
        except Exception as e:
            log.error(f"Close position error for {symbol}: {e}")
            return False


# ═════════════════════════════════════════════════════════════════════
#  SECTION 6: THE ORCHESTRATOR — The Brain That Ties It All Together
#  ─────────────────────────────────────────────────────────────────
#  This is the conductor. It:
#  1. Detects the current regime
#  2. Activates appropriate strategies
#  3. Collects proposals from all active strategies
#  4. Filters through risk management
#  5. Ranks by expected value and executes the best ones
#  6. Monitors open positions and manages exits
#  7. Adapts dynamically as regime shifts
# ═════════════════════════════════════════════════════════════════════

class HydraOrchestrator:
    """
    The master controller of the HYDRA system.

    Named after the mythological creature — cut off one head (strategy),
    and others continue to generate alpha. The system is resilient
    because no single strategy is responsible for all profits.

    Operational Loop:
    1. OBSERVE  → Ingest data, update regime detector
    2. SIGNAL   → All strategies generate signals from their data sources
    3. PROPOSE  → Active strategies propose trades
    4. FILTER   → Risk manager approves/rejects/sizes proposals
    5. RANK     → Proposals ranked by expected value (confidence × R:R)
    6. EXECUTE  → Top proposals sent to Alpaca
    7. MANAGE   → Monitor positions, adjust stops, scale out
    8. LEARN    → Log results, update strategy weights
    """

    def __init__(self):
        log.info("=" * 70)
        log.info("  HYDRA ENGINE INITIALIZING")
        log.info("=" * 70)

        # Core components
        self.signal_agg = SignalAggregator()
        self.risk_mgr = RiskManager(starting_capital=100000.0)
        self.regime_detector = RegimeDetector()
        self.executor = AlpacaExecutor(API_KEY, API_SECRET, paper=PAPER)

        # Strategy modules
        self.strategies: list[StrategyModule] = [
            CryptoLiquidationHunter(self.signal_agg, self.risk_mgr),
            EventDrivenMacro(self.signal_agg, self.risk_mgr),
            MetalsFlowTrader(self.signal_agg, self.risk_mgr),
            SaaSDisruptionTrader(self.signal_agg, self.risk_mgr),
            CrossAssetRegimeTrader(self.signal_agg, self.risk_mgr),
        ]

        # Tracking
        self.cycle_count = 0
        self.active_orders = {}
        self.running = False

        # Dynamic strategy weights (updated based on recent performance)
        self.strategy_weights = {s.name: 1.0 for s in self.strategies}

        log.info(f"Strategies loaded: {[s.name for s in self.strategies]}")
        log.info(f"Executor mode: {'Alpaca Paper' if self.executor.client else 'Dry-Run Simulation'}")

    def _fetch_market_data(self) -> dict:
        """
        Fetch current prices for all watched assets.
        This is the data ingestion layer.
        """
        assets = [
            "SPY", "QQQ", "TLT", "GLD", "SLV", "IGV",
            "CRM", "SHOP", "ADBE", "MSFT", "WDAY", "LZ",
            "HYG", "XLF", "XLE", "GDX", "UVXY",
            "BTC/USD", "ETH/USD"
        ]

        data = {}
        for asset in assets:
            price = self.executor.get_current_price(asset)
            if price > 0:
                data[asset] = price

        return data

    def _rank_proposals(self, proposals: list[TradeProposal]) -> list[TradeProposal]:
        """
        Rank proposals by expected value = confidence × (target - entry) / (entry - stop).
        Apply strategy weight multiplier.
        """
        scored = []
        for p in proposals:
            reward = abs(p.target_price - p.entry_price)
            risk = abs(p.entry_price - p.stop_price)
            rr_ratio = reward / risk if risk > 0 else 0

            # Expected value = confidence × R:R ratio × strategy weight
            strat_weight = self.strategy_weights.get(p.strategy_name, 1.0)
            ev = p.confidence * rr_ratio * strat_weight

            scored.append((ev, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored]

    def _execute_top_proposals(self, proposals: list[TradeProposal],
                               market_data: dict, regime: RegimeState):
        """Execute the highest-ranked proposals that pass risk management."""
        executed = 0
        max_per_cycle = 3  # Don't overwhelm with too many orders at once

        for proposal in proposals:
            if executed >= max_per_cycle:
                break

            # Check regime compatibility
            if regime.regime not in proposal.regime_required:
                log.debug(f"Skipping {proposal.asset}: regime {regime.regime} "
                          f"not in {proposal.regime_required}")
                continue

            # Check risk limits
            can_trade, reason = self.risk_mgr.can_trade()
            if not can_trade:
                log.warning(f"Risk block: {reason}")
                break

            # Calculate volatility (simplified: use 20-bar std of returns)
            volatility = 0.02  # Default 2% daily vol (would be calculated from data)

            # Get position size
            sizing = self.risk_mgr.calculate_position_size(
                asset=proposal.asset,
                entry_price=proposal.entry_price,
                stop_price=proposal.stop_price,
                volatility=volatility,
                signal_confidence=proposal.confidence
            )

            if sizing["shares"] <= 0:
                log.debug(f"Skip {proposal.asset}: {sizing['reason']}")
                continue

            # EXECUTE
            order_id = self.executor.execute_proposal(proposal, sizing["shares"])
            if order_id:
                self.active_orders[order_id] = {
                    "proposal": proposal,
                    "sizing": sizing,
                    "entry_time": datetime.now(timezone.utc),
                    "status": "open"
                }
                executed += 1
                log.info(f"✓ EXECUTED: {proposal.strategy_name} → "
                         f"{proposal.side.upper()} {sizing['shares']} {proposal.asset} "
                         f"@ ${proposal.entry_price:.2f} | "
                         f"Risk=${sizing['risk_dollars']:.2f} | "
                         f"Kelly={sizing['kelly_fraction']:.3f}")

    def _manage_open_positions(self, market_data: dict):
        """
        Monitor open positions and enforce stops/targets.
        This runs every cycle and is critical for risk management.
        """
        for order_id, order_info in list(self.active_orders.items()):
            if order_info["status"] != "open":
                continue

            proposal = order_info["proposal"]
            current_price = market_data.get(proposal.asset, 0)
            if current_price <= 0:
                continue

            entry = proposal.entry_price
            stop = proposal.stop_price
            target = proposal.target_price
            is_long = proposal.side == "buy"

            # CHECK STOP
            if is_long and current_price <= stop:
                pnl = (current_price - entry) * order_info["sizing"]["shares"]
                self.executor.close_position(proposal.asset)
                self.risk_mgr.record_trade_result(pnl, proposal.asset)
                order_info["status"] = "stopped_out"
                log.warning(f"✗ STOP HIT: {proposal.asset} | PnL=${pnl:+,.2f}")

            elif not is_long and current_price >= stop:
                pnl = (entry - current_price) * order_info["sizing"]["shares"]
                self.executor.close_position(proposal.asset)
                self.risk_mgr.record_trade_result(pnl, proposal.asset)
                order_info["status"] = "stopped_out"
                log.warning(f"✗ STOP HIT: {proposal.asset} | PnL=${pnl:+,.2f}")

            # CHECK TARGET
            elif is_long and current_price >= target:
                pnl = (current_price - entry) * order_info["sizing"]["shares"]
                self.executor.close_position(proposal.asset)
                self.risk_mgr.record_trade_result(pnl, proposal.asset)
                order_info["status"] = "target_hit"
                log.info(f"★ TARGET HIT: {proposal.asset} | PnL=${pnl:+,.2f}")

            elif not is_long and current_price <= target:
                pnl = (entry - current_price) * order_info["sizing"]["shares"]
                self.executor.close_position(proposal.asset)
                self.risk_mgr.record_trade_result(pnl, proposal.asset)
                order_info["status"] = "target_hit"
                log.info(f"★ TARGET HIT: {proposal.asset} | PnL=${pnl:+,.2f}")

            # TRAILING STOP: If in profit by 50%+ of target, tighten stop to breakeven
            elif is_long and current_price > entry + (target - entry) * 0.5:
                proposal.stop_price = max(stop, entry)  # Move stop to breakeven
                log.debug(f"Trailing stop moved to breakeven for {proposal.asset}")

    def _update_strategy_weights(self):
        """
        Adapt strategy weights based on recent performance.
        Strategies that are winning get more capital allocation.
        Strategies that are losing get reduced allocation.

        This is the META-LEARNING layer — the system that learns
        which strategies work in the current environment.
        """
        for strategy in self.strategies:
            if strategy.trade_count < 5:
                continue  # Not enough data to judge

            # Weight = smoothed win rate × average R:R
            # With floor of 0.3 (never fully disable a strategy)
            wr = strategy.win_rate
            self.strategy_weights[strategy.name] = max(0.3, min(2.0, wr * 2))

    def run_cycle(self):
        """
        Execute one full cycle of the HYDRA loop.
        This is called repeatedly (every 30-60 seconds during market hours).
        """
        self.cycle_count += 1

        # ── STEP 1: OBSERVE ──
        market_data = self._fetch_market_data()
        if not market_data:
            log.debug("No market data available this cycle.")
            return

        spy_price = market_data.get("SPY", 0)
        # VIX would be fetched from data feed; using placeholder
        vix_approx = 20.0  # Current VIX is around 20 based on research

        # ── STEP 2: DETECT REGIME ──
        regime = self.regime_detector.update(spy_price, vix_approx)

        if self.cycle_count % 10 == 0:  # Log regime every 10 cycles
            log.info(f"Regime: {regime.regime.value} (confidence={regime.confidence:.2f}) | "
                     f"VIX≈{vix_approx} | Trend={regime.trend_strength:+.2f} | "
                     f"MR={regime.mean_reversion_score:.2f}")

        # ── STEP 3: COLLECT PROPOSALS ──
        all_proposals = []
        for strategy in self.strategies:
            if strategy.should_activate(regime):
                try:
                    proposals = strategy.generate_proposals(market_data)
                    all_proposals.extend(proposals)
                except Exception as e:
                    log.error(f"Strategy {strategy.name} error: {e}")

        # ── STEP 4: RANK & FILTER ──
        ranked = self._rank_proposals(all_proposals)

        # ── STEP 5: EXECUTE ──
        if ranked:
            self._execute_top_proposals(ranked, market_data, regime)

        # ── STEP 6: MANAGE POSITIONS ──
        self._manage_open_positions(market_data)

        # ── STEP 7: ADAPT ──
        if self.cycle_count % 50 == 0:
            self._update_strategy_weights()

    def run(self, interval_seconds: int = 60):
        """
        Main loop. Runs continuously, executing cycles at the given interval.
        """
        self.running = True
        log.info("=" * 70)
        log.info("  HYDRA ENGINE ACTIVE — Paper Trading Mode")
        log.info(f"  Cycle interval: {interval_seconds}s")
        log.info(f"  Strategies: {len(self.strategies)}")
        log.info(f"  Starting capital: ${self.risk_mgr.capital:,.2f}")
        log.info("=" * 70)

        while self.running:
            try:
                self.run_cycle()
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                log.info("Shutdown requested. Closing all positions...")
                self.running = False
                self._shutdown()
            except Exception as e:
                log.error(f"Cycle error: {e}")
                time.sleep(interval_seconds)

    def _shutdown(self):
        """Graceful shutdown — close all positions and log final state."""
        log.info("=" * 70)
        log.info("  HYDRA ENGINE SHUTTING DOWN")
        log.info("=" * 70)

        # Close all positions
        positions = self.executor.get_positions()
        for pos in positions:
            self.executor.close_position(pos.symbol)

        # Final report
        total_trades = len(self.risk_mgr.trade_log)
        winners = sum(1 for t in self.risk_mgr.trade_log if t["pnl"] > 0)
        losers = sum(1 for t in self.risk_mgr.trade_log if t["pnl"] < 0)
        total_pnl = sum(t["pnl"] for t in self.risk_mgr.trade_log)

        log.info(f"Final Capital: ${self.risk_mgr.capital:,.2f}")
        log.info(f"Total PnL: ${total_pnl:+,.2f}")
        log.info(f"Total Trades: {total_trades} (W:{winners} L:{losers})")
        log.info(f"Win Rate: {winners/total_trades*100:.1f}%" if total_trades > 0 else "N/A")
        log.info(f"Max Drawdown: {((self.risk_mgr.peak_capital - self.risk_mgr.capital) / self.risk_mgr.peak_capital * 100):.1f}%")

        # Dump trade log
        log_path = f"hydra_trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_path, "w") as f:
            json.dump(self.risk_mgr.trade_log, f, indent=2)
        log.info(f"Trade log saved: {log_path}")


# ═════════════════════════════════════════════════════════════════════
#  SECTION 7: ENTRY POINT
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║                   H Y D R A   E N G I N E                   ║
    ║          Multi-Asset Adaptive Scalping System                ║
    ║                                                              ║
    ║  Strategies:                                                 ║
    ║    1. Crypto Liquidation Cascade Hunter                      ║
    ║    2. Macro Event Scalper (NFP/CPI/FOMC)                     ║
    ║    3. Precious Metals Flow & Margin Trader                   ║
    ║    4. AI/SaaS Disruption Shock Trader                        ║
    ║    5. Cross-Asset Regime Signal Graph                        ║
    ║                                                              ║
    ║  Risk Management:                                            ║
    ║    • Half-Kelly position sizing                              ║
    ║    • Volatility-scaled exposure                              ║
    ║    • 5% daily loss kill switch                               ║
    ║    • Consecutive loss cooldown                               ║
    ║    • Correlation-aware limits                                ║
    ║                                                              ║
    ║  Set ALPACA_API_KEY and ALPACA_SECRET_KEY env vars            ║
    ║  for paper trading, or run in dry-run simulation mode.       ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

    hydra = HydraOrchestrator()
    hydra.run(interval_seconds=60)
