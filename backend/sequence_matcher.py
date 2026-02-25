"""
HYDRA Temporal Sequence Matcher v1.0

Hybrid approach for finding similar historical trading sequences:
1. Vector DB (Titan Embeddings) for fast candidate retrieval
2. Nova Pro for analysis of top candidates

This is 100x cheaper than putting all history in Nova Pro's context.

Cost: ~$31/month (embeddings + selective Nova Pro calls)
"""

import os
import json
import logging
import sqlite3
import math
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from pathlib import Path

log = logging.getLogger("HYDRA.SEQUENCE")

from bedrock_client import get_bedrock_client, BedrockResponse

# Data directory
DATA_DIR = Path(__file__).parent.parent / "data"
SEQUENCE_DB = DATA_DIR / "sequence_vectors.db"

# Embedding dimension (Titan V2 supports 256, 512, 1024)
EMBEDDING_DIM = 512

# Number of historical days to maintain
HISTORY_DAYS = 60

# Number of similar sequences to retrieve before Nova analysis
TOP_K_CANDIDATES = 5


@dataclass
class DailyFingerprint:
    """A day's market conditions encoded as a fingerprint."""
    date: str
    gex_regime: str
    flow_bias: str
    vix_level: float
    spy_change_pct: float
    spy_range_pct: float
    blowup_score: int
    dark_pool_bias: str
    outcome_next_day: Optional[float]  # SPY change next day
    embedding: Optional[List[float]] = None

    def to_text(self) -> str:
        """Convert fingerprint to text for embedding."""
        return (
            f"Market conditions on {self.date}: "
            f"GEX regime {self.gex_regime}, "
            f"institutional flow {self.flow_bias}, "
            f"VIX at {self.vix_level:.1f}, "
            f"SPY moved {self.spy_change_pct:+.2f}% with {self.spy_range_pct:.2f}% range, "
            f"blowup score {self.blowup_score}, "
            f"dark pool bias {self.dark_pool_bias}"
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop('embedding', None)  # Don't include embedding in dict
        return d


@dataclass
class SequenceMatch:
    """A matched historical sequence."""
    date: str
    similarity: float
    conditions: dict
    outcome: float
    reasoning: Optional[str] = None


@dataclass
class SequenceAnalysis:
    """Complete sequence matching analysis."""
    timestamp: str
    current_conditions: dict
    similar_sequences: List[dict]
    predicted_direction: str  # BULLISH, BEARISH, NEUTRAL
    historical_win_rate: float
    average_outcome: float
    nova_analysis: str
    confidence: float
    latency_ms: float

    def to_dict(self) -> dict:
        return asdict(self)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


class SequenceMatcher:
    """
    Matches current conditions to historical sequences.

    Uses:
    - Titan Embeddings V2 for vector similarity search
    - Nova Pro for final analysis of top candidates
    """

    def __init__(self):
        self.bedrock = get_bedrock_client()
        self._init_db()

        # Cache for embeddings to reduce API calls
        self.embedding_cache: Dict[str, List[float]] = {}

        # Nova system prompt
        self.nova_system = """You are a quantitative trading analyst. Analyze historical market patterns to predict likely outcomes.

Given current market conditions and similar historical sequences, determine:
1. Most likely direction (BULLISH/BEARISH/NEUTRAL)
2. Expected magnitude of move
3. Confidence level based on pattern consistency

Be concise and data-driven. Focus on pattern recurrence and outcome distribution."""

    def _init_db(self):
        """Initialize SQLite database for sequence vectors."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(SEQUENCE_DB))
            cursor = conn.cursor()

            # Store daily fingerprints
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_fingerprints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE NOT NULL,
                    gex_regime TEXT,
                    flow_bias TEXT,
                    vix_level REAL,
                    spy_change_pct REAL,
                    spy_range_pct REAL,
                    blowup_score INTEGER,
                    dark_pool_bias TEXT,
                    outcome_next_day REAL,
                    embedding BLOB
                )
            """)

            # Index for date lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_fingerprints_date
                ON daily_fingerprints(date)
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Sequence database init error: {e}")

    def _store_fingerprint(self, fingerprint: DailyFingerprint):
        """Store a daily fingerprint in the database."""
        try:
            conn = sqlite3.connect(str(SEQUENCE_DB))
            cursor = conn.cursor()

            embedding_blob = json.dumps(fingerprint.embedding) if fingerprint.embedding else None

            cursor.execute("""
                INSERT OR REPLACE INTO daily_fingerprints
                (date, gex_regime, flow_bias, vix_level, spy_change_pct, spy_range_pct,
                 blowup_score, dark_pool_bias, outcome_next_day, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fingerprint.date,
                fingerprint.gex_regime,
                fingerprint.flow_bias,
                fingerprint.vix_level,
                fingerprint.spy_change_pct,
                fingerprint.spy_range_pct,
                fingerprint.blowup_score,
                fingerprint.dark_pool_bias,
                fingerprint.outcome_next_day,
                embedding_blob
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Store fingerprint error: {e}")

    def _load_fingerprints(self, days: int = HISTORY_DAYS) -> List[DailyFingerprint]:
        """Load recent fingerprints from database."""
        try:
            conn = sqlite3.connect(str(SEQUENCE_DB))
            cursor = conn.cursor()

            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            cursor.execute("""
                SELECT date, gex_regime, flow_bias, vix_level, spy_change_pct, spy_range_pct,
                       blowup_score, dark_pool_bias, outcome_next_day, embedding
                FROM daily_fingerprints
                WHERE date >= ?
                ORDER BY date DESC
            """, (cutoff,))

            fingerprints = []
            for row in cursor.fetchall():
                embedding = json.loads(row[9]) if row[9] else None
                fingerprints.append(DailyFingerprint(
                    date=row[0],
                    gex_regime=row[1],
                    flow_bias=row[2],
                    vix_level=row[3],
                    spy_change_pct=row[4],
                    spy_range_pct=row[5],
                    blowup_score=row[6],
                    dark_pool_bias=row[7],
                    outcome_next_day=row[8],
                    embedding=embedding
                ))

            conn.close()
            return fingerprints

        except Exception as e:
            log.error(f"Load fingerprints error: {e}")
            return []

    def record_daily_conditions(
        self,
        date: str,
        gex_regime: str,
        flow_bias: str,
        vix_level: float,
        spy_change_pct: float,
        spy_range_pct: float,
        blowup_score: int,
        dark_pool_bias: str,
        outcome_next_day: float = None
    ):
        """
        Record a day's conditions for future matching.
        Call this at end of each trading day.
        """
        fingerprint = DailyFingerprint(
            date=date,
            gex_regime=gex_regime,
            flow_bias=flow_bias,
            vix_level=vix_level,
            spy_change_pct=spy_change_pct,
            spy_range_pct=spy_range_pct,
            blowup_score=blowup_score,
            dark_pool_bias=dark_pool_bias,
            outcome_next_day=outcome_next_day
        )

        # Generate embedding
        if self.bedrock.is_available:
            text = fingerprint.to_text()
            embedding = self.bedrock.get_embedding(text)
            fingerprint.embedding = embedding

        # Store in database
        self._store_fingerprint(fingerprint)

        log.info(f"Recorded daily fingerprint for {date}")

    def update_outcome(self, date: str, outcome: float):
        """Update the next-day outcome for a fingerprint."""
        try:
            conn = sqlite3.connect(str(SEQUENCE_DB))
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE daily_fingerprints
                SET outcome_next_day = ?
                WHERE date = ?
            """, (outcome, date))

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Update outcome error: {e}")

    def find_similar_sequences(
        self,
        current_conditions: dict,
        top_k: int = TOP_K_CANDIDATES
    ) -> List[SequenceMatch]:
        """
        Find similar historical sequences using vector similarity.

        Args:
            current_conditions: dict with gex_regime, flow_bias, vix_level, etc.
            top_k: Number of similar sequences to return

        Returns:
            List of SequenceMatch objects
        """
        # Build current fingerprint
        current = DailyFingerprint(
            date=datetime.now().strftime("%Y-%m-%d"),
            gex_regime=current_conditions.get("gex_regime", "UNKNOWN"),
            flow_bias=current_conditions.get("flow_bias", "NEUTRAL"),
            vix_level=current_conditions.get("vix_level", 20.0),
            spy_change_pct=current_conditions.get("spy_change_pct", 0.0),
            spy_range_pct=current_conditions.get("spy_range_pct", 0.0),
            blowup_score=current_conditions.get("blowup_score", 0),
            dark_pool_bias=current_conditions.get("dark_pool_bias", "NEUTRAL"),
            outcome_next_day=None
        )

        # Get embedding for current conditions
        current_embedding = None
        if self.bedrock.is_available:
            text = current.to_text()
            current_embedding = self.bedrock.get_embedding(text)

        # Load historical fingerprints
        historical = self._load_fingerprints()

        if not historical:
            return []

        # Calculate similarities
        matches = []
        for fp in historical:
            if fp.embedding and current_embedding:
                similarity = cosine_similarity(current_embedding, fp.embedding)
            else:
                # Fallback: rule-based similarity
                similarity = self._rule_based_similarity(current, fp)

            if fp.outcome_next_day is not None:  # Only include if we know the outcome
                matches.append(SequenceMatch(
                    date=fp.date,
                    similarity=round(similarity, 4),
                    conditions=fp.to_dict(),
                    outcome=fp.outcome_next_day
                ))

        # Sort by similarity and return top K
        matches.sort(key=lambda x: x.similarity, reverse=True)
        return matches[:top_k]

    def _rule_based_similarity(self, a: DailyFingerprint, b: DailyFingerprint) -> float:
        """Calculate similarity using rules when embeddings unavailable."""
        score = 0.0
        max_score = 7.0

        # GEX regime match
        if a.gex_regime == b.gex_regime:
            score += 1.5

        # Flow bias match
        if a.flow_bias == b.flow_bias:
            score += 1.5
        elif "BULLISH" in a.flow_bias and "BULLISH" in b.flow_bias:
            score += 0.75
        elif "BEARISH" in a.flow_bias and "BEARISH" in b.flow_bias:
            score += 0.75

        # VIX level proximity
        vix_diff = abs(a.vix_level - b.vix_level)
        if vix_diff < 2:
            score += 1.0
        elif vix_diff < 5:
            score += 0.5

        # SPY change direction match
        if (a.spy_change_pct > 0 and b.spy_change_pct > 0) or \
           (a.spy_change_pct < 0 and b.spy_change_pct < 0):
            score += 1.0

        # SPY range proximity
        range_diff = abs(a.spy_range_pct - b.spy_range_pct)
        if range_diff < 0.5:
            score += 0.5

        # Blowup score proximity
        blowup_diff = abs(a.blowup_score - b.blowup_score)
        if blowup_diff < 10:
            score += 1.0
        elif blowup_diff < 20:
            score += 0.5

        # Dark pool bias match
        if a.dark_pool_bias == b.dark_pool_bias:
            score += 0.5

        return score / max_score

    def analyze_with_nova(
        self,
        current_conditions: dict,
        similar_sequences: List[SequenceMatch]
    ) -> SequenceAnalysis:
        """
        Use Nova Pro to analyze similar sequences and predict outcome.
        Only called when a trade is being considered.
        """
        import time
        start_time = time.time()

        timestamp = datetime.now(timezone.utc).isoformat()

        if not similar_sequences:
            return SequenceAnalysis(
                timestamp=timestamp,
                current_conditions=current_conditions,
                similar_sequences=[],
                predicted_direction="NEUTRAL",
                historical_win_rate=0.5,
                average_outcome=0.0,
                nova_analysis="No similar sequences found",
                confidence=0.0,
                latency_ms=0
            )

        # Calculate basic stats
        outcomes = [s.outcome for s in similar_sequences if s.outcome is not None]
        if outcomes:
            avg_outcome = sum(outcomes) / len(outcomes)
            bullish_count = sum(1 for o in outcomes if o > 0.1)
            bearish_count = sum(1 for o in outcomes if o < -0.1)
            win_rate = bullish_count / len(outcomes) if outcomes else 0.5
        else:
            avg_outcome = 0.0
            win_rate = 0.5

        # Build prompt for Nova Pro
        sequence_text = "\n".join([
            f"- {s.date}: Similarity {s.similarity:.2f}, "
            f"Conditions: {json.dumps(s.conditions)}, "
            f"Next day outcome: {s.outcome:+.2f}%"
            for s in similar_sequences
        ])

        prompt = f"""Current market conditions:
{json.dumps(current_conditions, indent=2)}

Most similar historical sequences:
{sequence_text}

Based on these {len(similar_sequences)} similar historical patterns:
1. What is the most likely direction for the next trading session?
2. What is your confidence level (0-100)?
3. What is the key pattern driving this prediction?

Respond with JSON:
{{
  "predicted_direction": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": 0-100,
  "expected_magnitude": "percentage range like 0.5-1.0%",
  "key_pattern": "one sentence description"
}}"""

        # Invoke Nova Pro
        if self.bedrock.is_available:
            response = self.bedrock.invoke_nova_pro(
                prompt=prompt,
                system=self.nova_system,
                max_tokens=300,
                temperature=0.0
            )

            if response.success:
                try:
                    nova_result = json.loads(response.content)
                    predicted_direction = nova_result.get("predicted_direction", "NEUTRAL")
                    confidence = nova_result.get("confidence", 50)
                    nova_analysis = nova_result.get("key_pattern", "")
                except json.JSONDecodeError:
                    # Use fallback
                    predicted_direction = "BULLISH" if avg_outcome > 0.1 else "BEARISH" if avg_outcome < -0.1 else "NEUTRAL"
                    confidence = 50 + int(abs(avg_outcome) * 10)
                    nova_analysis = response.content
            else:
                predicted_direction = "BULLISH" if avg_outcome > 0.1 else "BEARISH" if avg_outcome < -0.1 else "NEUTRAL"
                confidence = 50 + int(abs(avg_outcome) * 10)
                nova_analysis = f"Nova unavailable: {response.error}"
        else:
            # Fallback without Nova
            predicted_direction = "BULLISH" if avg_outcome > 0.1 else "BEARISH" if avg_outcome < -0.1 else "NEUTRAL"
            confidence = 50 + int(abs(avg_outcome) * 10)
            nova_analysis = f"Pattern match based on {len(similar_sequences)} similar days, avg outcome {avg_outcome:+.2f}%"

        latency_ms = (time.time() - start_time) * 1000

        analysis = SequenceAnalysis(
            timestamp=timestamp,
            current_conditions=current_conditions,
            similar_sequences=[asdict(s) for s in similar_sequences],
            predicted_direction=predicted_direction,
            historical_win_rate=round(win_rate, 2),
            average_outcome=round(avg_outcome, 2),
            nova_analysis=nova_analysis,
            confidence=confidence,
            latency_ms=round(latency_ms, 1)
        )

        log.info(
            f"Sequence: {len(similar_sequences)} matches | "
            f"Direction: {predicted_direction} ({confidence}%) | "
            f"Avg outcome: {avg_outcome:+.2f}%"
        )

        return analysis

    def get_conviction_modifier(self, trade_direction: str, current_conditions: dict) -> dict:
        """
        Get conviction modifier based on sequence matching.

        Args:
            trade_direction: "BULLISH" or "BEARISH"
            current_conditions: Current market conditions dict

        Returns:
            dict with modifier and reasoning
        """
        # Find similar sequences
        similar = self.find_similar_sequences(current_conditions)

        if not similar:
            return {"modifier": 0, "reasons": ["No historical pattern match"]}

        # Calculate outcomes
        outcomes = [s.outcome for s in similar]
        avg_outcome = sum(outcomes) / len(outcomes) if outcomes else 0

        modifier = 0
        reasons = []

        # Check if history supports the trade direction
        if trade_direction == "BULLISH":
            bullish_outcomes = [o for o in outcomes if o > 0]
            win_rate = len(bullish_outcomes) / len(outcomes) if outcomes else 0.5

            if win_rate >= 0.7:
                modifier += 15
                reasons.append(f"Historical win rate: {win_rate:.0%} bullish")
            elif win_rate >= 0.6:
                modifier += 8
                reasons.append(f"Historical win rate: {win_rate:.0%} bullish")
            elif win_rate < 0.4:
                modifier -= 10
                reasons.append(f"Historical win rate: {win_rate:.0%} bullish (bearish history)")

        elif trade_direction == "BEARISH":
            bearish_outcomes = [o for o in outcomes if o < 0]
            win_rate = len(bearish_outcomes) / len(outcomes) if outcomes else 0.5

            if win_rate >= 0.7:
                modifier += 15
                reasons.append(f"Historical win rate: {win_rate:.0%} bearish")
            elif win_rate >= 0.6:
                modifier += 8
                reasons.append(f"Historical win rate: {win_rate:.0%} bearish")
            elif win_rate < 0.4:
                modifier -= 10
                reasons.append(f"Historical win rate: {win_rate:.0%} bearish (bullish history)")

        return {
            "modifier": modifier,
            "reasons": reasons,
            "similar_sequences": len(similar),
            "avg_outcome": round(avg_outcome, 2)
        }


# Singleton instance
_sequence_matcher: Optional[SequenceMatcher] = None


def get_sequence_matcher() -> SequenceMatcher:
    """Get or create the singleton sequence matcher instance."""
    global _sequence_matcher
    if _sequence_matcher is None:
        _sequence_matcher = SequenceMatcher()
    return _sequence_matcher


# CLI for testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    matcher = get_sequence_matcher()

    # Record some test data
    print("\nRecording test fingerprints...")
    test_days = [
        ("2026-02-20", "NEGATIVE", "AGGRESSIVELY_BULLISH", 19.5, 1.2, 1.5, 35, "BUY", 0.8),
        ("2026-02-21", "POSITIVE", "NEUTRAL", 18.0, 0.3, 0.8, 15, "NEUTRAL", -0.2),
        ("2026-02-24", "NEGATIVE", "MODERATELY_BEARISH", 22.0, -0.5, 1.2, 45, "SELL", 0.5),
    ]

    for date, gex, flow, vix, change, range_, blowup, dp, outcome in test_days:
        matcher.record_daily_conditions(
            date=date,
            gex_regime=gex,
            flow_bias=flow,
            vix_level=vix,
            spy_change_pct=change,
            spy_range_pct=range_,
            blowup_score=blowup,
            dark_pool_bias=dp,
            outcome_next_day=outcome
        )

    # Test matching
    print("\nFinding similar sequences...")
    current = {
        "gex_regime": "NEGATIVE",
        "flow_bias": "AGGRESSIVELY_BULLISH",
        "vix_level": 20.0,
        "spy_change_pct": 0.5,
        "spy_range_pct": 1.0,
        "blowup_score": 30,
        "dark_pool_bias": "BUY"
    }

    similar = matcher.find_similar_sequences(current)

    print(f"\nFound {len(similar)} similar sequences:")
    for s in similar:
        print(f"  {s.date}: Similarity {s.similarity:.2f}, Outcome: {s.outcome:+.2f}%")

    # Test full analysis
    print("\nRunning Nova Pro analysis...")
    analysis = matcher.analyze_with_nova(current, similar)

    print("\n" + "=" * 60)
    print("SEQUENCE MATCHER - TEST RESULTS")
    print("=" * 60)
    print(f"Predicted Direction: {analysis.predicted_direction}")
    print(f"Confidence: {analysis.confidence}%")
    print(f"Historical Win Rate: {analysis.historical_win_rate:.0%}")
    print(f"Average Outcome: {analysis.average_outcome:+.2f}%")
    print(f"Nova Analysis: {analysis.nova_analysis}")
    print(f"Latency: {analysis.latency_ms}ms")
