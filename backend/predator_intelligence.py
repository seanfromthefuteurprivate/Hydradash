"""
HYDRA Predator Intelligence Aggregator v1.0

Central aggregator for all predator intelligence layers:
- Layer 8: GEX Engine (dealer gamma exposure)
- Layer 9: Flow Decoder (institutional options flow)
- Layer 10: Dark Pool Mapper (block trade levels)
- Layer 11: Sequence Matcher (temporal pattern matching)

Plus existing:
- Blowup Detector (probability of violent move)
- Event Calendar (economic events)

Provides a unified API for WSB Snake to consume.
"""

import logging
import asyncio
from datetime import datetime, timezone, time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
import threading

log = logging.getLogger("HYDRA.PREDATOR")

# Import all intelligence modules
from gex_engine import get_gex_engine, GEXSnapshot
from flow_decoder import get_flow_decoder, FlowSnapshot
from dark_pool_mapper import get_dark_pool_mapper, DarkPoolSnapshot
from sequence_matcher import get_sequence_matcher, SequenceAnalysis
from blowup_detector import get_blowup_detector, BlowupResult


@dataclass
class PredatorIntelligence:
    """Complete predator intelligence package."""
    timestamp: str

    # Blowup (existing)
    blowup_probability: int
    blowup_direction: str
    blowup_regime: str
    blowup_recommendation: str
    blowup_triggers: list

    # GEX (Layer 8)
    gex_regime: str
    gex_total: float
    gex_flip_point: Optional[float]
    gex_flip_distance_pct: float
    gex_charm_per_hour: float
    gex_key_support: list
    gex_key_resistance: list

    # Flow (Layer 9)
    flow_institutional_bias: str
    flow_confidence: int
    flow_premium_calls: float
    flow_premium_puts: float
    flow_sweep_direction: str

    # Dark Pool (Layer 10)
    dp_nearest_support: Optional[float]
    dp_nearest_resistance: Optional[float]
    dp_support_strength: str
    dp_resistance_strength: str
    dp_buy_volume: int
    dp_sell_volume: int

    # Sequence Match (Layer 11)
    sequence_similar_count: int
    sequence_predicted_direction: str
    sequence_historical_win_rate: float
    sequence_avg_outcome: float

    # Meta
    components_healthy: int
    components_total: int

    def to_dict(self) -> dict:
        return asdict(self)


class PredatorIntelligenceEngine:
    """
    Orchestrates all predator intelligence layers.

    Runs background loops for each component and provides
    a unified API for fetching current intelligence.
    """

    def __init__(self):
        # Initialize all engines
        self.gex_engine = get_gex_engine()
        self.flow_decoder = get_flow_decoder()
        self.dp_mapper = get_dark_pool_mapper()
        self.sequence_matcher = get_sequence_matcher()
        self.blowup_detector = get_blowup_detector()

        # Latest snapshots
        self.last_intelligence: Optional[PredatorIntelligence] = None
        self.last_update: Optional[datetime] = None

        # Background loop control
        self._running = False
        self._threads: list = []

    def start_background_loops(self, event_loop: asyncio.AbstractEventLoop):
        """
        Start background monitoring loops for all layers.
        Called from server.py lifespan.
        """
        self._running = True

        # GEX loop - adaptive interval (30s to 15min)
        gex_thread = threading.Thread(
            target=self._gex_loop,
            args=(event_loop,),
            daemon=True,
            name="gex-engine"
        )
        gex_thread.start()
        self._threads.append(gex_thread)
        log.info("Started: gex-engine")

        # Flow decoder loop - every 2 minutes during market hours
        flow_thread = threading.Thread(
            target=self._flow_loop,
            daemon=True,
            name="flow-decoder"
        )
        flow_thread.start()
        self._threads.append(flow_thread)
        log.info("Started: flow-decoder")

        # Dark pool loop - every 5 minutes
        dp_thread = threading.Thread(
            target=self._dark_pool_loop,
            daemon=True,
            name="dark-pool-mapper"
        )
        dp_thread.start()
        self._threads.append(dp_thread)
        log.info("Started: dark-pool-mapper")

    def stop(self):
        """Stop all background loops."""
        self._running = False

    def _is_market_hours(self) -> bool:
        """Check if within market hours (9:30 AM - 4:00 PM ET)."""
        import pytz
        et = pytz.timezone('America/New_York')
        now_et = datetime.now(et)
        return time(9, 30) <= now_et.time() <= time(16, 0)

    def _gex_loop(self, event_loop: asyncio.AbstractEventLoop):
        """GEX calculation loop with adaptive interval."""
        import time as time_module

        while self._running:
            try:
                if self._is_market_hours():
                    snapshot = self.gex_engine.calculate()
                    interval = snapshot.refresh_interval_seconds
                else:
                    interval = 900  # 15 min outside market hours

                time_module.sleep(interval)

            except Exception as e:
                log.error(f"GEX loop error: {e}")
                time_module.sleep(60)

    def _flow_loop(self):
        """Flow decoder loop - every 2 minutes during market hours."""
        import time as time_module

        while self._running:
            try:
                if self._is_market_hours():
                    self.flow_decoder.calculate("SPY")
                    time_module.sleep(120)  # 2 minutes
                else:
                    time_module.sleep(300)  # 5 minutes outside market

            except Exception as e:
                log.error(f"Flow loop error: {e}")
                time_module.sleep(60)

    def _dark_pool_loop(self):
        """Dark pool mapper loop - every 5 minutes."""
        import time as time_module

        while self._running:
            try:
                if self._is_market_hours():
                    self.dp_mapper.calculate("SPY")
                    time_module.sleep(300)  # 5 minutes
                else:
                    time_module.sleep(900)  # 15 minutes outside market

            except Exception as e:
                log.error(f"Dark pool loop error: {e}")
                time_module.sleep(60)

    def get_intelligence(self) -> PredatorIntelligence:
        """
        Get current predator intelligence.
        Aggregates all layer outputs into a single package.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get blowup (always available)
        blowup = self.blowup_detector.get_last_result()
        if not blowup:
            blowup = self.blowup_detector.calculate()

        # Get GEX
        gex = self.gex_engine.get_last_snapshot()

        # Get Flow
        flow = self.flow_decoder.get_last_snapshot()

        # Get Dark Pool
        dp = self.dp_mapper.get_last_snapshot()

        # Count healthy components
        components_healthy = 1  # Blowup always works
        if gex and gex.options_count > 0:
            components_healthy += 1
        if flow and flow.total_trades_analyzed > 0:
            components_healthy += 1
        if dp and dp.total_dark_volume > 0:
            components_healthy += 1

        # Build sweep direction
        sweep_direction = "NEUTRAL"
        if flow:
            if flow.sweep_count_calls > flow.sweep_count_puts * 2:
                sweep_direction = "CALL_HEAVY"
            elif flow.sweep_count_puts > flow.sweep_count_calls * 2:
                sweep_direction = "PUT_HEAVY"

        intelligence = PredatorIntelligence(
            timestamp=timestamp,

            # Blowup
            blowup_probability=blowup.blowup_probability,
            blowup_direction=blowup.direction,
            blowup_regime=blowup.regime,
            blowup_recommendation=blowup.recommendation,
            blowup_triggers=blowup.triggers,

            # GEX
            gex_regime=gex.regime if gex else "UNKNOWN",
            gex_total=gex.total_gex if gex else 0,
            gex_flip_point=gex.flip_point if gex else None,
            gex_flip_distance_pct=gex.flip_distance_pct if gex else 1.0,
            gex_charm_per_hour=gex.charm_flow_per_hour if gex else 0,
            gex_key_support=gex.key_support if gex else [],
            gex_key_resistance=gex.key_resistance if gex else [],

            # Flow
            flow_institutional_bias=flow.institutional_bias if flow else "UNKNOWN",
            flow_confidence=flow.confidence if flow else 0,
            flow_premium_calls=flow.net_premium_calls if flow else 0,
            flow_premium_puts=flow.net_premium_puts if flow else 0,
            flow_sweep_direction=sweep_direction,

            # Dark Pool
            dp_nearest_support=dp.nearest_support if dp else None,
            dp_nearest_resistance=dp.nearest_resistance if dp else None,
            dp_support_strength=dp.support_strength if dp else "UNKNOWN",
            dp_resistance_strength=dp.resistance_strength if dp else "UNKNOWN",
            dp_buy_volume=dp.buy_volume if dp else 0,
            dp_sell_volume=dp.sell_volume if dp else 0,

            # Sequence (computed on demand, not in background)
            sequence_similar_count=0,
            sequence_predicted_direction="NEUTRAL",
            sequence_historical_win_rate=0.5,
            sequence_avg_outcome=0.0,

            # Meta
            components_healthy=components_healthy,
            components_total=4
        )

        self.last_intelligence = intelligence
        self.last_update = datetime.now(timezone.utc)

        return intelligence

    def get_trade_conviction_modifiers(
        self,
        trade_direction: str,
        entry_price: float,
        stop_price: float,
        target_price: float
    ) -> dict:
        """
        Get conviction modifiers from all layers for a proposed trade.

        Args:
            trade_direction: "BULLISH" or "BEARISH"
            entry_price: Proposed entry price
            stop_price: Proposed stop loss
            target_price: Proposed target

        Returns:
            dict with total modifier, breakdown by layer, and reasons
        """
        modifiers = {}
        total_modifier = 0
        all_reasons = []

        # GEX modifier
        gex_mod = self.gex_engine.get_conviction_modifier(trade_direction)
        modifiers["gex"] = gex_mod
        total_modifier += gex_mod["modifier"]
        all_reasons.extend(gex_mod.get("reasons", []))

        # Flow modifier
        flow_mod = self.flow_decoder.get_conviction_modifier(trade_direction)
        modifiers["flow"] = flow_mod
        total_modifier += flow_mod["modifier"]
        all_reasons.extend(flow_mod.get("reasons", []))

        # Dark pool modifier
        dp_mod = self.dp_mapper.get_conviction_modifier(entry_price, stop_price, target_price)
        modifiers["dark_pool"] = dp_mod
        total_modifier += dp_mod["modifier"]
        all_reasons.extend(dp_mod.get("reasons", []))

        # Sequence modifier (build current conditions)
        gex = self.gex_engine.get_last_snapshot()
        flow = self.flow_decoder.get_last_snapshot()
        blowup = self.blowup_detector.get_last_result()
        dp = self.dp_mapper.get_last_snapshot()

        current_conditions = {
            "gex_regime": gex.regime if gex else "UNKNOWN",
            "flow_bias": flow.institutional_bias if flow else "NEUTRAL",
            "vix_level": 20.0,  # TODO: get from blowup components
            "spy_change_pct": 0.0,
            "spy_range_pct": 0.0,
            "blowup_score": blowup.blowup_probability if blowup else 0,
            "dark_pool_bias": "BUY" if dp and dp.buy_volume > dp.sell_volume else "SELL" if dp else "NEUTRAL"
        }

        seq_mod = self.sequence_matcher.get_conviction_modifier(trade_direction, current_conditions)
        modifiers["sequence"] = seq_mod
        total_modifier += seq_mod["modifier"]
        all_reasons.extend(seq_mod.get("reasons", []))

        return {
            "total_modifier": total_modifier,
            "modifiers": modifiers,
            "reasons": all_reasons,
            "trade_direction": trade_direction
        }

    def run_sequence_analysis(self, trade_direction: str) -> SequenceAnalysis:
        """
        Run full sequence analysis with Nova Pro.
        Only call this when a trade is being considered (not in background).
        """
        gex = self.gex_engine.get_last_snapshot()
        flow = self.flow_decoder.get_last_snapshot()
        blowup = self.blowup_detector.get_last_result()
        dp = self.dp_mapper.get_last_snapshot()

        current_conditions = {
            "gex_regime": gex.regime if gex else "UNKNOWN",
            "flow_bias": flow.institutional_bias if flow else "NEUTRAL",
            "vix_level": 20.0,
            "spy_change_pct": 0.0,
            "spy_range_pct": 0.0,
            "blowup_score": blowup.blowup_probability if blowup else 0,
            "dark_pool_bias": "BUY" if dp and dp.buy_volume > dp.sell_volume else "SELL" if dp else "NEUTRAL"
        }

        similar = self.sequence_matcher.find_similar_sequences(current_conditions)
        analysis = self.sequence_matcher.analyze_with_nova(current_conditions, similar)

        return analysis


# Singleton instance
_predator_engine: Optional[PredatorIntelligenceEngine] = None


def get_predator_intelligence_engine() -> PredatorIntelligenceEngine:
    """Get or create the singleton predator intelligence engine."""
    global _predator_engine
    if _predator_engine is None:
        _predator_engine = PredatorIntelligenceEngine()
    return _predator_engine


# CLI for testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    engine = get_predator_intelligence_engine()

    print("\n" + "=" * 60)
    print("PREDATOR INTELLIGENCE ENGINE - TEST")
    print("=" * 60)

    # Get current intelligence
    intel = engine.get_intelligence()

    print(f"\nTimestamp: {intel.timestamp}")
    print(f"Components Healthy: {intel.components_healthy}/{intel.components_total}")

    print(f"\n--- BLOWUP ---")
    print(f"Probability: {intel.blowup_probability}%")
    print(f"Direction: {intel.blowup_direction}")
    print(f"Regime: {intel.blowup_regime}")
    print(f"Recommendation: {intel.blowup_recommendation}")

    print(f"\n--- GEX ---")
    print(f"Regime: {intel.gex_regime}")
    print(f"Total: ${intel.gex_total/1e9:.2f}B")
    print(f"Flip Point: ${intel.gex_flip_point} ({intel.gex_flip_distance_pct*100:.1f}% away)")
    print(f"Key Support: {intel.gex_key_support}")
    print(f"Key Resistance: {intel.gex_key_resistance}")

    print(f"\n--- FLOW ---")
    print(f"Institutional Bias: {intel.flow_institutional_bias}")
    print(f"Confidence: {intel.flow_confidence}%")
    print(f"Call Premium: ${intel.flow_premium_calls:,.0f}")
    print(f"Put Premium: ${intel.flow_premium_puts:,.0f}")
    print(f"Sweep Direction: {intel.flow_sweep_direction}")

    print(f"\n--- DARK POOL ---")
    print(f"Nearest Support: ${intel.dp_nearest_support} ({intel.dp_support_strength})")
    print(f"Nearest Resistance: ${intel.dp_nearest_resistance} ({intel.dp_resistance_strength})")
    print(f"Buy Volume: {intel.dp_buy_volume:,}")
    print(f"Sell Volume: {intel.dp_sell_volume:,}")

    # Test conviction modifiers
    print(f"\n--- CONVICTION MODIFIERS (BULLISH trade) ---")
    mods = engine.get_trade_conviction_modifiers(
        trade_direction="BULLISH",
        entry_price=548.00,
        stop_price=546.50,
        target_price=551.00
    )
    print(f"Total Modifier: {mods['total_modifier']:+d}")
    print(f"Reasons: {mods['reasons']}")
