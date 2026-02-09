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


# ── Background Workers ──
def signal_scan_loop():
    """Continuously scan all data sources."""
    while True:
        try:
            new_signals = signal_orch.scan_all()
            if new_signals:
                log.info(f"Signal scan: {len(new_signals)} new signals")
                # Push to websocket clients
                data = json.dumps({
                    "type": "signals_update",
                    "signals": [s.to_dict() for s in new_signals],
                    "summary": signal_orch.get_summary()
                }, default=str)
                for ws in ws_clients[:]:
                    try:
                        asyncio.run(ws.send_text(data))
                    except Exception:
                        ws_clients.remove(ws)
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


# ── App Lifecycle ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background threads
    threads = [
        threading.Thread(target=signal_scan_loop, daemon=True, name="signal-scanner"),
        threading.Thread(target=trading_loop, daemon=True, name="trading-engine"),
        threading.Thread(target=telegram_poll_loop, daemon=True, name="telegram-poller"),
    ]
    for t in threads:
        t.start()
        log.info(f"Started: {t.name}")

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
