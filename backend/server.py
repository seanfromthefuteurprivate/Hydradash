"""
HYDRA API Server — FastAPI backend that:
1. Runs the signal detection engine on a background loop
2. Exposes REST API for the dashboard
3. Runs the trading engine (paper mode)
4. Manages Telegram bridge
"""

import os
import json
from pathlib import Path

from dotenv import load_dotenv
# Data directory path
DATA_DIR = Path(__file__).parent.parent / "data"
# Load .env from project root (parent of backend/) when running locally
_load_env = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_load_env)
import asyncio
import threading
import time
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from hydra_signal_detection import SignalOrchestrator, export_dashboard_data, DATA_SOURCE_REGISTRY
from hydra_telegram import TelegramBridge, SignalParser, EventScheduler
from hydra_engine import HydraOrchestrator
from blowup_detector import get_blowup_detector, BlowupResult
from event_surprise import get_event_calendar, get_surprise_detector
from weight_calibrator import get_weight_calibrator, TradeResult

# Predator Intelligence Stack (Layers 8-11)
from predator_intelligence import get_predator_intelligence_engine
from gex_engine import get_gex_engine
from flow_decoder import get_flow_decoder
from dark_pool_mapper import get_dark_pool_mapper
from sequence_matcher import get_sequence_matcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("HYDRA.API")

# ── Global State ──
signal_orch = SignalOrchestrator()
telegram = TelegramBridge(
    bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
)
trading_engine = None  # Initialized if Alpaca keys present
ws_clients: list[WebSocket] = []

# Blowup detection engine
blowup_detector = get_blowup_detector()
event_calendar = get_event_calendar()
weight_calibrator = get_weight_calibrator()

# Predator Intelligence Engine (GEX, Flow, Dark Pool, Sequence)
predator_engine = get_predator_intelligence_engine()


async def broadcast_to_clients(data: str):
    """Safely broadcast to all WebSocket clients from async context."""
    disconnected = []
    for ws in ws_clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        ws_clients.remove(ws)


# ── Background Workers ──
def signal_scan_loop(loop: asyncio.AbstractEventLoop):
    """Continuously scan all data sources."""
    while True:
        try:
            new_signals = signal_orch.scan_all()
            if new_signals:
                log.info(f"Signal scan: {len(new_signals)} new signals")
                # Push to websocket clients via the main event loop
                data = json.dumps({
                    "type": "signals_update",
                    "signals": [s.to_dict() for s in new_signals],
                    "summary": signal_orch.get_summary()
                }, default=str)
                asyncio.run_coroutine_threadsafe(broadcast_to_clients(data), loop)
        except Exception as e:
            log.error(f"Signal scan error: {e}")
        time.sleep(60)  # Scan every 60 seconds


def trading_loop():
    """Run the HYDRA trading engine."""
    global trading_engine
    api_key = os.environ.get("ALPACA_API_KEY", "")
    api_secret = os.environ.get("ALPACA_SECRET_KEY", "")

    if not api_key or not api_secret:
        log.info("No Alpaca keys — trading engine disabled. Set ALPACA_API_KEY and ALPACA_SECRET_KEY.")
        return

    trading_engine = HydraOrchestrator()
    log.info("Trading engine started (paper mode)")

    while True:
        try:
            trading_engine.run_cycle()
        except Exception as e:
            log.error(f"Trading cycle error: {e}")
        time.sleep(60)


def telegram_poll_loop():
    """Poll Telegram for incoming signals."""
    if not telegram.connected:
        return
    parser = SignalParser()
    while True:
        try:
            signals = telegram.poll_messages()
            for sig in signals:
                log.info(f"Telegram signal: {sig.signal_type} {sig.asset or 'N/A'}")
        except Exception as e:
            log.error(f"Telegram poll error: {e}")
        time.sleep(10)


def blowup_detection_loop(loop: asyncio.AbstractEventLoop):
    """Run the blowup probability engine every 60 seconds."""
    while True:
        try:
            result = blowup_detector.calculate()
            log.info(f"Blowup score: {result.blowup_probability} | Direction: {result.direction} | Rec: {result.recommendation}")

            # Broadcast to WebSocket clients
            data = json.dumps({
                "type": "blowup_update",
                "blowup": result.to_dict()
            }, default=str)
            asyncio.run_coroutine_threadsafe(broadcast_to_clients(data), loop)

            # Alert on high blowup scores
            if result.blowup_probability >= 70 and telegram.connected:
                try:
                    telegram.send_message(
                        f"🚨 BLOWUP ALERT: {result.blowup_probability}%\n"
                        f"Direction: {result.direction}\n"
                        f"Regime: {result.regime}\n"
                        f"Recommendation: {result.recommendation}\n"
                        f"Triggers: {', '.join(result.triggers[:3])}"
                    )
                except Exception:
                    pass

        except Exception as e:
            log.error(f"Blowup detection error: {e}")
        time.sleep(60)  # Run every 60 seconds


# ── App Lifecycle ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Get the running event loop to pass to background threads
    loop = asyncio.get_running_loop()

    # Start background threads
    threads = [
        threading.Thread(target=signal_scan_loop, args=(loop,), daemon=True, name="signal-scanner"),
        threading.Thread(target=trading_loop, daemon=True, name="trading-engine"),
        threading.Thread(target=telegram_poll_loop, daemon=True, name="telegram-poller"),
        threading.Thread(target=blowup_detection_loop, args=(loop,), daemon=True, name="blowup-detector"),
    ]
    for t in threads:
        t.start()
        log.info(f"Started: {t.name}")

    # Start Predator Intelligence background loops (GEX, Flow, Dark Pool)
    predator_engine.start_background_loops(loop)
    log.info("Started: predator-intelligence-stack")

    yield

    log.info("Shutting down HYDRA API")


# ── FastAPI App ──
app = FastAPI(
    title="HYDRA Command Center API",
    version="2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── API Routes ──

@app.get("/api/health")
def health():
    return {
        "status": "online",
        "engine": "HYDRA v2.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signals_active": len(signal_orch.all_signals),
        "trading_engine": "active" if trading_engine else "disabled",
        "telegram": "connected" if telegram.connected else "disconnected",
    }


@app.get("/api/signals")
def get_signals(category: str = None, priority: str = None):
    """Get all active signals, optionally filtered."""
    return {
        "signals": signal_orch.get_active_signals(category=category, min_priority=priority),
        "summary": signal_orch.get_summary(),
    }


@app.get("/api/signals/summary")
def get_summary():
    return signal_orch.get_summary()


@app.get("/api/dashboard")
def get_dashboard_data():
    """Full dashboard export — signals + sources + stats."""
    return export_dashboard_data(signal_orch)


@app.get("/api/sources")
def get_data_sources():
    """List all 37 data sources with status."""
    return {
        "sources": DATA_SOURCE_REGISTRY,
        "total": len(DATA_SOURCE_REGISTRY),
        "implemented": sum(1 for d in DATA_SOURCE_REGISTRY if d["status"] == "IMPLEMENTED"),
        "planned": sum(1 for d in DATA_SOURCE_REGISTRY if d["status"] == "PLANNED"),
    }


@app.get("/api/trading/status")
def get_trading_status():
    if not trading_engine:
        return {"status": "disabled", "reason": "No Alpaca API keys configured"}
    rm = trading_engine.risk_mgr
    return {
        "status": "active",
        "capital": rm.capital,
        "daily_pnl": rm.daily_pnl,
        "trades_today": rm.daily_trade_count,
        "consecutive_losses": rm.consecutive_losses,
        "peak_capital": rm.peak_capital,
        "drawdown_pct": (rm.peak_capital - rm.capital) / rm.peak_capital * 100,
    }


@app.get("/api/trading/log")
def get_trade_log():
    if not trading_engine:
        return {"trades": []}
    return {"trades": trading_engine.risk_mgr.trade_log[-50:]}


@app.post("/api/scan")
def trigger_scan():
    """Manually trigger a full signal scan."""
    new = signal_orch.scan_all()
    return {"new_signals": len(new), "total_active": len(signal_orch.all_signals)}


# ═══════════════════════════════════════════════════════════════
#  PREDICTIVE INTELLIGENCE ENGINE ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.get("/api/blowup")
def get_blowup():
    """
    Get current blowup probability score.
    This is the core predictive intelligence output.
    """
    result = blowup_detector.get_last_result()
    if result:
        return result.to_dict()

    # If no result yet, calculate one
    result = blowup_detector.calculate()
    return result.to_dict()


@app.get("/api/blowup/history")
def get_blowup_history(count: int = 10):
    """Get recent blowup scores for trend display."""
    return {
        "scores": blowup_detector.get_recent_scores(count),
        "count": count
    }


@app.get("/api/events")
def get_events(hours: int = 72):
    """
    Get upcoming economic events with time-to-event and expected impact.
    """
    return {
        "events": event_calendar.get_events_for_api(hours),
        "count": len(event_calendar.get_events_for_api(hours))
    }


@app.get("/api/intelligence")
def get_intelligence():
    """
    MASTER ENDPOINT: Returns ALL intelligence data in one call.
    This is the single source of truth that WSB Snake polls every 60 seconds.
    Must be fast (<200ms) and never crash (returns safe defaults if data source down).
    """
    try:
        # Get blowup result (cached from last calculation)
        blowup_result = blowup_detector.get_last_result()
        if not blowup_result:
            blowup_result = blowup_detector.calculate()

        # Get upcoming events
        events = event_calendar.get_events_for_api(hours=24)
        events_next_30min = [e for e in events if -30 <= e.get("minutes_until", 999) <= 30]

        # Get recent blowup scores for trend
        recent_scores = blowup_detector.get_recent_scores(10)

        # Get signal summary
        signal_summary = signal_orch.get_summary()

        # Get trading status
        trading_status = None
        if trading_engine:
            rm = trading_engine.risk_mgr
            trading_status = {
                "status": "active",
                "capital": rm.capital,
                "daily_pnl": rm.daily_pnl,
                "trades_today": rm.daily_trade_count
            }

        return {
            # Core blowup intelligence
            "blowup_probability": blowup_result.blowup_probability,
            "direction": blowup_result.direction,
            "regime": blowup_result.regime,
            "confidence": blowup_result.confidence,
            "triggers": blowup_result.triggers,
            "recommendation": blowup_result.recommendation,

            # Events
            "events_next_30min": events_next_30min,
            "upcoming_events": events[:5],

            # Trends
            "recent_scores": recent_scores,

            # Signal summary
            "signals_active": signal_summary.get("total_active", 0),
            "signals_critical": signal_summary.get("critical", 0),

            # Trading status
            "trading": trading_status,

            # System status
            "timestamp": blowup_result.timestamp,
            "engine": "HYDRA v2.0 - Predictive Intelligence",
            "components_healthy": sum(1 for c in blowup_result.components if c.get("healthy", False)),
            "components_total": len(blowup_result.components)
        }

    except Exception as e:
        log.error(f"Intelligence endpoint error: {e}")
        # Return safe defaults - never crash
        return {
            "blowup_probability": 0,
            "direction": "NEUTRAL",
            "regime": "UNKNOWN",
            "confidence": 0.0,
            "triggers": [],
            "recommendation": "NO_TRADE",
            "events_next_30min": [],
            "upcoming_events": [],
            "recent_scores": [],
            "signals_active": 0,
            "signals_critical": 0,
            "trading": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "engine": "HYDRA v2.0 - ERROR STATE",
            "error": str(e)
        }


@app.post("/api/trade-result")
def record_trade_result(data: dict):
    """
    Receive trade result from WSB Snake for weight calibration.

    Expected payload:
    {
        "trade_id": "...",
        "ticker": "SPY",
        "direction": "CALL",
        "mode": "BLOWUP",
        "entry_time": "2026-02-25T15:03:00",
        "exit_time": "2026-02-25T15:18:00",
        "pnl_percent": 47.3,
        "conviction": 78,
        "blowup_score_at_entry": 72,
        "blowup_direction_at_entry": "BULLISH",
        "triggers_at_entry": ["vix_inverted", "volume_surge"],
        "regime_at_entry": "RISK_ON"
    }
    """
    try:
        trade = TradeResult.from_dict(data)
        success = weight_calibrator.record_trade(trade)

        return {
            "status": "ok" if success else "error",
            "trade_id": trade.trade_id,
            "recorded": success
        }

    except Exception as e:
        log.error(f"Trade result error: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/api/calibration/stats")
def get_calibration_stats(days: int = 30):
    """Get trade statistics for calibration."""
    return weight_calibrator.get_trade_stats(days)


@app.get("/api/calibration/weights")
def get_current_weights():
    """Get current blowup detector weights."""
    return {
        "weights": weight_calibrator.current_weights,
        "source": "calibrated" if (DATA_DIR / "blowup_weights.json").exists() else "default"
    }


@app.post("/api/calibration/run")
def run_calibration():
    """Manually trigger weight calibration (normally runs daily at 4:30 PM ET)."""
    result = weight_calibrator.calibrate()
    if result:
        # Hot reload weights in blowup detector
        blowup_detector.reload_weights()
        return {
            "status": "ok",
            "calibration": {
                "total_trades": result.total_trades,
                "win_rate": result.win_rate,
                "precision": result.precision,
                "recall": result.recall,
                "new_weights": result.new_weights,
                "notes": result.notes
            }
        }
    return {
        "status": "skipped",
        "reason": "Not enough trades for calibration"
    }


# ═══════════════════════════════════════════════════════════════
#  PREDATOR INTELLIGENCE ENDPOINTS (Layers 8-11)
# ═══════════════════════════════════════════════════════════════

@app.get("/api/predator")
def get_predator_intelligence():
    """
    MASTER PREDATOR ENDPOINT: Full intelligence package from all layers.

    Returns GEX, Flow, Dark Pool, and Sequence data in one call.
    This is what WSB Snake polls for trade decisions.
    """
    try:
        intel = predator_engine.get_intelligence()
        return intel.to_dict()
    except Exception as e:
        log.error(f"Predator intelligence error: {e}")
        return {
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@app.get("/api/gex")
def get_gex():
    """
    Layer 8: GEX (Gamma Exposure) regime and key levels.

    Returns dealer gamma positioning, flip point, charm flow.
    """
    try:
        gex_engine = predator_engine.gex_engine
        snapshot = gex_engine.get_last_snapshot()

        if not snapshot:
            # Calculate fresh if no cached data
            snapshot = gex_engine.calculate()

        return snapshot.to_dict()
    except Exception as e:
        log.error(f"GEX endpoint error: {e}")
        return {
            "error": str(e),
            "regime": "UNKNOWN",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@app.get("/api/flow")
def get_flow():
    """
    Layer 9: Institutional Flow classification.

    Returns call/put premium, sweep activity, institutional bias.
    Uses Claude Haiku for context-aware classification.
    """
    try:
        flow_decoder = predator_engine.flow_decoder
        snapshot = flow_decoder.get_last_snapshot()

        if not snapshot:
            snapshot = flow_decoder.calculate("SPY")

        return snapshot.to_dict()
    except Exception as e:
        log.error(f"Flow endpoint error: {e}")
        return {
            "error": str(e),
            "institutional_bias": "UNKNOWN",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@app.get("/api/darkpool")
def get_dark_pool():
    """
    Layer 10: Dark Pool support/resistance levels.

    Returns institutional block trade levels and volume.
    """
    try:
        dp_mapper = predator_engine.dp_mapper
        snapshot = dp_mapper.get_last_snapshot()

        if not snapshot:
            snapshot = dp_mapper.calculate("SPY")

        return snapshot.to_dict()
    except Exception as e:
        log.error(f"Dark pool endpoint error: {e}")
        return {
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@app.post("/api/sequence/analyze")
def analyze_sequence(data: dict):
    """
    Layer 11: Temporal sequence analysis (on-demand).

    Finds similar historical market conditions and predicts outcome.
    Uses Nova Pro for pattern analysis (expensive - only call when needed).

    Expected payload:
    {
        "trade_direction": "BULLISH" | "BEARISH"
    }
    """
    try:
        trade_direction = data.get("trade_direction", "BULLISH")
        analysis = predator_engine.run_sequence_analysis(trade_direction)
        return analysis.to_dict()
    except Exception as e:
        log.error(f"Sequence analysis error: {e}")
        return {
            "error": str(e),
            "predicted_direction": "NEUTRAL",
            "confidence": 0,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@app.post("/api/conviction")
def get_conviction_modifiers(data: dict):
    """
    Get conviction modifiers from all predator layers for a proposed trade.

    WSB Snake calls this before entering a position to get a total
    conviction boost/penalty from all intelligence layers.

    Expected payload:
    {
        "trade_direction": "BULLISH" | "BEARISH",
        "entry_price": 548.00,
        "stop_price": 546.50,
        "target_price": 551.00
    }
    """
    try:
        trade_direction = data.get("trade_direction", "BULLISH")
        entry_price = data.get("entry_price", 0)
        stop_price = data.get("stop_price", 0)
        target_price = data.get("target_price", 0)

        modifiers = predator_engine.get_trade_conviction_modifiers(
            trade_direction=trade_direction,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price
        )

        return modifiers
    except Exception as e:
        log.error(f"Conviction modifiers error: {e}")
        return {
            "error": str(e),
            "total_modifier": 0,
            "modifiers": {},
            "reasons": []
        }


# ── WebSocket for real-time updates ──

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    log.info(f"WebSocket client connected ({len(ws_clients)} total)")
    try:
        # Send initial state
        await websocket.send_json({
            "type": "init",
            "signals": signal_orch.get_active_signals(),
            "summary": signal_orch.get_summary(),
        })
        # Keep alive
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_clients.remove(websocket)
        log.info(f"WebSocket client disconnected ({len(ws_clients)} remaining)")


# ── Serve frontend (if built) ──
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(FRONTEND_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        file_path = os.path.join(FRONTEND_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
