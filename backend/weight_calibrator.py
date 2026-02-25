"""
╔══════════════════════════════════════════════════════════════════════════════╗
║               HYDRA WEIGHT CALIBRATOR v1.0                                  ║
║         Auto-calibrate blowup detector weights based on trade results       ║
║                                                                              ║
║  POST /api/trade-result receives trade feedback from WSB Snake              ║
║  Daily at 4:30 PM ET: recalibrate weights based on what's actually working ║
║                                                                              ║
║  Tracks:                                                                     ║
║  - Precision: When score > 60, did SPY actually move > 0.8%?               ║
║  - Recall: When SPY moved > 0.8%, was score > 60?                          ║
║  - Per-trigger accuracy: Which triggers actually predict blowups?          ║
║  - Directional accuracy: When HYDRA says BEARISH, are puts winners?        ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from pathlib import Path
from collections import defaultdict

log = logging.getLogger("HYDRA.CALIBRATOR")

DATA_DIR = Path(__file__).parent.parent / "data"
FEEDBACK_DB = DATA_DIR / "trade_feedback.db"
WEIGHTS_FILE = DATA_DIR / "blowup_weights.json"

# Minimum trades before calibration kicks in
MIN_TRADES_FOR_CALIBRATION = 20

# Default weights (from blowup_detector.py)
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


# ═══════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class TradeResult:
    """Trade result received from WSB Snake."""
    trade_id: str
    ticker: str
    direction: str                  # CALL, PUT
    mode: str                       # BLOWUP, SIGNAL, etc.
    entry_time: str
    exit_time: str
    pnl_percent: float
    conviction: int                 # 0-100
    blowup_score_at_entry: int
    blowup_direction_at_entry: str  # BULLISH, BEARISH, NEUTRAL
    triggers_at_entry: List[str]
    regime_at_entry: str

    @classmethod
    def from_dict(cls, data: dict) -> 'TradeResult':
        return cls(
            trade_id=data.get("trade_id", ""),
            ticker=data.get("ticker", ""),
            direction=data.get("direction", ""),
            mode=data.get("mode", ""),
            entry_time=data.get("entry_time", ""),
            exit_time=data.get("exit_time", ""),
            pnl_percent=data.get("pnl_percent", 0.0),
            conviction=data.get("conviction", 0),
            blowup_score_at_entry=data.get("blowup_score_at_entry", 0),
            blowup_direction_at_entry=data.get("blowup_direction_at_entry", "NEUTRAL"),
            triggers_at_entry=data.get("triggers_at_entry", []),
            regime_at_entry=data.get("regime_at_entry", "UNKNOWN")
        )


@dataclass
class CalibrationResult:
    """Result of weight calibration run."""
    timestamp: str
    total_trades: int
    blowup_trades: int
    win_rate: float
    avg_pnl: float
    old_weights: Dict[str, float]
    new_weights: Dict[str, float]
    trigger_performance: Dict[str, Dict[str, float]]
    direction_accuracy: float
    precision: float           # Score > 60 and SPY moved > 0.8%
    recall: float              # SPY moved > 0.8% and score was > 60
    notes: List[str]


# ═══════════════════════════════════════════════════════════════
#  WEIGHT CALIBRATOR
# ═══════════════════════════════════════════════════════════════

class WeightCalibrator:
    """
    Calibrates blowup detector weights based on actual trade performance.
    Runs daily at 4:30 PM ET to update weights.
    """

    def __init__(self):
        self._init_db()
        self.current_weights = self._load_weights()

    def _init_db(self):
        """Initialize SQLite database for trade feedback."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(FEEDBACK_DB))
            cursor = conn.cursor()

            # Trade feedback table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT UNIQUE,
                    ticker TEXT,
                    direction TEXT,
                    mode TEXT,
                    entry_time TEXT,
                    exit_time TEXT,
                    pnl_percent REAL,
                    conviction INTEGER,
                    blowup_score INTEGER,
                    blowup_direction TEXT,
                    triggers TEXT,
                    regime TEXT,
                    created_at TEXT
                )
            """)

            # Daily calibration log
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS calibration_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE,
                    total_trades INTEGER,
                    blowup_trades INTEGER,
                    win_rate REAL,
                    avg_pnl REAL,
                    precision REAL,
                    recall REAL,
                    direction_accuracy REAL,
                    old_weights TEXT,
                    new_weights TEXT,
                    notes TEXT
                )
            """)

            # Blowup accuracy tracking (for precision/recall)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blowup_accuracy (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    blowup_score INTEGER,
                    spy_move_30min REAL,
                    direction_predicted TEXT,
                    direction_actual TEXT,
                    triggers TEXT
                )
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Calibrator DB init error: {e}")

    def _load_weights(self) -> Dict[str, float]:
        """Load current weights from file."""
        try:
            if WEIGHTS_FILE.exists():
                with open(WEIGHTS_FILE) as f:
                    return json.load(f)
        except Exception as e:
            log.warning(f"Could not load weights: {e}")
        return DEFAULT_WEIGHTS.copy()

    def _save_weights(self, weights: Dict[str, float]):
        """Save weights to file."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(WEIGHTS_FILE, 'w') as f:
                json.dump(weights, f, indent=2)
            self.current_weights = weights
            log.info(f"Weights saved: {weights}")
        except Exception as e:
            log.error(f"Could not save weights: {e}")

    def record_trade(self, trade: TradeResult) -> bool:
        """Record a trade result from WSB Snake."""
        try:
            conn = sqlite3.connect(str(FEEDBACK_DB))
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO trade_feedback
                (trade_id, ticker, direction, mode, entry_time, exit_time,
                 pnl_percent, conviction, blowup_score, blowup_direction,
                 triggers, regime, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.trade_id,
                trade.ticker,
                trade.direction,
                trade.mode,
                trade.entry_time,
                trade.exit_time,
                trade.pnl_percent,
                trade.conviction,
                trade.blowup_score_at_entry,
                trade.blowup_direction_at_entry,
                json.dumps(trade.triggers_at_entry),
                trade.regime_at_entry,
                datetime.now(timezone.utc).isoformat()
            ))

            conn.commit()
            conn.close()

            log.info(f"Recorded trade: {trade.trade_id} PnL: {trade.pnl_percent:+.1f}%")
            return True

        except Exception as e:
            log.error(f"Trade record error: {e}")
            return False

    def record_blowup_accuracy(self, score: int, spy_move: float,
                               direction_predicted: str, direction_actual: str,
                               triggers: List[str]):
        """Record a blowup prediction vs actual move for precision/recall tracking."""
        try:
            conn = sqlite3.connect(str(FEEDBACK_DB))
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO blowup_accuracy
                (timestamp, blowup_score, spy_move_30min, direction_predicted,
                 direction_actual, triggers)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                score,
                spy_move,
                direction_predicted,
                direction_actual,
                json.dumps(triggers)
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Accuracy record error: {e}")

    def get_trade_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get trade statistics for the last N days."""
        try:
            conn = sqlite3.connect(str(FEEDBACK_DB))
            cursor = conn.cursor()

            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            cursor.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN pnl_percent > 0 THEN 1 ELSE 0 END),
                       AVG(pnl_percent),
                       COUNT(CASE WHEN mode = 'BLOWUP' THEN 1 END)
                FROM trade_feedback
                WHERE created_at > ?
            """, (cutoff,))

            row = cursor.fetchone()
            conn.close()

            if row:
                total = row[0] or 0
                wins = row[1] or 0
                avg_pnl = row[2] or 0
                blowup_trades = row[3] or 0

                return {
                    "total_trades": total,
                    "wins": wins,
                    "win_rate": wins / total if total > 0 else 0,
                    "avg_pnl": avg_pnl,
                    "blowup_trades": blowup_trades
                }

        except Exception as e:
            log.error(f"Stats error: {e}")

        return {"total_trades": 0, "wins": 0, "win_rate": 0, "avg_pnl": 0, "blowup_trades": 0}

    def calibrate(self) -> Optional[CalibrationResult]:
        """
        Run daily calibration to update weights.
        Called at 4:30 PM ET each trading day.
        """
        try:
            conn = sqlite3.connect(str(FEEDBACK_DB))
            cursor = conn.cursor()

            # Get all blowup trades
            cursor.execute("""
                SELECT * FROM trade_feedback
                WHERE mode = 'BLOWUP'
            """)

            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

            trades = [dict(zip(columns, row)) for row in rows]

            # Check minimum trades requirement
            if len(trades) < MIN_TRADES_FOR_CALIBRATION:
                log.info(f"Calibration skipped: only {len(trades)} trades (min: {MIN_TRADES_FOR_CALIBRATION})")
                conn.close()
                return None

            # Calculate trigger performance
            trigger_stats = defaultdict(lambda: {"wins": 0, "total": 0, "total_pnl": 0})

            for trade in trades:
                triggers = json.loads(trade.get("triggers", "[]"))
                is_win = trade["pnl_percent"] > 0
                pnl = trade["pnl_percent"]

                for trigger in triggers:
                    # Extract trigger name (format: "name:value")
                    trigger_name = trigger.split(":")[0] if ":" in trigger else trigger
                    trigger_stats[trigger_name]["total"] += 1
                    trigger_stats[trigger_name]["total_pnl"] += pnl
                    if is_win:
                        trigger_stats[trigger_name]["wins"] += 1

            # Calculate precision and recall for each trigger
            trigger_performance = {}
            for trigger, stats in trigger_stats.items():
                if stats["total"] > 0:
                    precision = stats["wins"] / stats["total"]
                    recall = stats["wins"] / max(1, sum(1 for t in trades if t["pnl_percent"] > 0))
                    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
                    avg_pnl = stats["total_pnl"] / stats["total"]

                    trigger_performance[trigger] = {
                        "precision": round(precision, 3),
                        "recall": round(recall, 3),
                        "f1_score": round(f1, 3),
                        "avg_pnl": round(avg_pnl, 2),
                        "total_trades": stats["total"]
                    }

            # Calculate new weights based on F1 scores
            old_weights = self.current_weights.copy()
            new_weights = old_weights.copy()

            if trigger_performance:
                # Normalize F1 scores to sum to 1.0
                total_f1 = sum(tp["f1_score"] for tp in trigger_performance.values())

                if total_f1 > 0:
                    for trigger, perf in trigger_performance.items():
                        if trigger in new_weights:
                            # New weight = normalized F1 score
                            new_weights[trigger] = round(perf["f1_score"] / total_f1, 3)

                    # Ensure weights sum to 1.0
                    weight_sum = sum(new_weights.values())
                    if weight_sum > 0:
                        new_weights = {k: round(v / weight_sum, 3) for k, v in new_weights.items()}

            # Calculate direction accuracy
            direction_correct = 0
            direction_total = 0
            for trade in trades:
                if trade["blowup_direction"] in ["BULLISH", "BEARISH"]:
                    direction_total += 1
                    # Check if direction matched trade outcome
                    if (trade["blowup_direction"] == "BULLISH" and trade["direction"] == "CALL" and trade["pnl_percent"] > 0) or \
                       (trade["blowup_direction"] == "BEARISH" and trade["direction"] == "PUT" and trade["pnl_percent"] > 0):
                        direction_correct += 1

            direction_accuracy = direction_correct / direction_total if direction_total > 0 else 0

            # Calculate overall precision/recall
            cursor.execute("""
                SELECT blowup_score, spy_move_30min
                FROM blowup_accuracy
                WHERE spy_move_30min IS NOT NULL
            """)

            accuracy_rows = cursor.fetchall()
            conn.close()

            high_score_correct = 0
            high_score_total = 0
            big_move_detected = 0
            big_move_total = 0

            for row in accuracy_rows:
                score, move = row
                if score and move:
                    # Precision: score > 60 and move > 0.8%
                    if score > 60:
                        high_score_total += 1
                        if abs(move) > 0.8:
                            high_score_correct += 1

                    # Recall: move > 0.8% and score > 60
                    if abs(move) > 0.8:
                        big_move_total += 1
                        if score > 60:
                            big_move_detected += 1

            precision = high_score_correct / high_score_total if high_score_total > 0 else 0
            recall = big_move_detected / big_move_total if big_move_total > 0 else 0

            # Generate notes
            notes = []
            for trigger, perf in trigger_performance.items():
                if perf["f1_score"] > 0.5:
                    notes.append(f"{trigger}: strong predictor (F1={perf['f1_score']:.2f})")
                elif perf["f1_score"] < 0.2:
                    notes.append(f"{trigger}: weak predictor (F1={perf['f1_score']:.2f})")

            if direction_accuracy < 0.55:
                notes.append("WARNING: Direction accuracy below 55% - demoting direction confidence")

            # Calculate overall stats
            total_trades = len(trades)
            wins = sum(1 for t in trades if t["pnl_percent"] > 0)
            win_rate = wins / total_trades if total_trades > 0 else 0
            avg_pnl = sum(t["pnl_percent"] for t in trades) / total_trades if total_trades > 0 else 0

            # Create result
            result = CalibrationResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                total_trades=total_trades,
                blowup_trades=total_trades,
                win_rate=round(win_rate, 3),
                avg_pnl=round(avg_pnl, 2),
                old_weights=old_weights,
                new_weights=new_weights,
                trigger_performance=trigger_performance,
                direction_accuracy=round(direction_accuracy, 3),
                precision=round(precision, 3),
                recall=round(recall, 3),
                notes=notes
            )

            # Save new weights if significantly different
            weight_changes = sum(abs(new_weights.get(k, 0) - old_weights.get(k, 0)) for k in old_weights)
            if weight_changes > 0.1:  # >10% total change
                self._save_weights(new_weights)
                self._log_calibration(result)
                log.info(f"CALIBRATION: Weights updated. Changes: {weight_changes:.2f}")

                # Log individual changes
                for k in old_weights:
                    old_v = old_weights.get(k, 0)
                    new_v = new_weights.get(k, 0)
                    if abs(new_v - old_v) > 0.01:
                        log.info(f"  {k}: {old_v:.2f} → {new_v:.2f}")
            else:
                log.info("CALIBRATION: Weights unchanged (delta < 10%)")

            return result

        except Exception as e:
            log.error(f"Calibration error: {e}")
            return None

    def _log_calibration(self, result: CalibrationResult):
        """Log calibration to database."""
        try:
            conn = sqlite3.connect(str(FEEDBACK_DB))
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO calibration_log
                (date, total_trades, blowup_trades, win_rate, avg_pnl,
                 precision, recall, direction_accuracy, old_weights, new_weights, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().strftime("%Y-%m-%d"),
                result.total_trades,
                result.blowup_trades,
                result.win_rate,
                result.avg_pnl,
                result.precision,
                result.recall,
                result.direction_accuracy,
                json.dumps(result.old_weights),
                json.dumps(result.new_weights),
                json.dumps(result.notes)
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Calibration log error: {e}")

    def get_calibration_history(self, days: int = 30) -> List[Dict]:
        """Get calibration history for the last N days."""
        try:
            conn = sqlite3.connect(str(FEEDBACK_DB))
            cursor = conn.cursor()

            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            cursor.execute("""
                SELECT * FROM calibration_log
                WHERE date > ?
                ORDER BY date DESC
            """, (cutoff,))

            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            conn.close()

            return [dict(zip(columns, row)) for row in rows]

        except Exception as e:
            log.error(f"Calibration history error: {e}")
            return []


# ═══════════════════════════════════════════════════════════════
#  SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════

_calibrator_instance: Optional[WeightCalibrator] = None

def get_weight_calibrator() -> WeightCalibrator:
    """Get or create singleton WeightCalibrator."""
    global _calibrator_instance
    if _calibrator_instance is None:
        _calibrator_instance = WeightCalibrator()
    return _calibrator_instance


# ═══════════════════════════════════════════════════════════════
#  CLI FOR TESTING
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    calibrator = get_weight_calibrator()

    print("\nCurrent Weights:")
    print("=" * 40)
    for k, v in calibrator.current_weights.items():
        print(f"  {k}: {v:.3f}")

    print("\nTrade Stats (30 days):")
    print("=" * 40)
    stats = calibrator.get_trade_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # Test recording a trade
    test_trade = TradeResult(
        trade_id="test_001",
        ticker="SPY",
        direction="PUT",
        mode="BLOWUP",
        entry_time="2026-02-25T14:00:00Z",
        exit_time="2026-02-25T14:15:00Z",
        pnl_percent=23.5,
        conviction=75,
        blowup_score_at_entry=68,
        blowup_direction_at_entry="BEARISH",
        triggers_at_entry=["vix_inversion:0.45", "flow_imbalance:0.55"],
        regime_at_entry="RISK_OFF"
    )

    print(f"\nRecording test trade...")
    calibrator.record_trade(test_trade)
    print("Done!")
