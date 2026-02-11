import { useState, useEffect, useCallback, useRef } from "react";

// API and WebSocket configuration
const API_BASE = '';  // Same origin
const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

// ══════════════════════════════════════════════════════════════
//  HYDRA COMMAND CENTER — Event Intelligence & Alert Dashboard
// ══════════════════════════════════════════════════════════════

// ── DATA: Event Database (loaded from API) ──
const EVENTS_DB = [];  // Loaded from API

// ── Utility Functions ──
const getDTE = (dateStr) => {
  const now = new Date();
  const event = new Date(dateStr);
  const diff = event - now;
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
  if (diff < 0) return { days: 0, hours: 0, label: "LIVE NOW", isPast: true, totalHours: 0 };
  if (days === 0) return { days: 0, hours, label: `${hours}h`, isPast: false, totalHours: hours };
  return { days, hours, label: `${days}d ${hours}h`, isPast: false, totalHours: days * 24 + hours };
};

const priorityConfig = {
  CRITICAL: { color: "#ff2e4c", bg: "rgba(255,46,76,0.08)", border: "rgba(255,46,76,0.3)", glow: "0 0 20px rgba(255,46,76,0.15)" },
  HIGH: { color: "#ff9f1c", bg: "rgba(255,159,28,0.06)", border: "rgba(255,159,28,0.25)", glow: "0 0 15px rgba(255,159,28,0.1)" },
  MEDIUM: { color: "#4ecdc4", bg: "rgba(78,205,196,0.05)", border: "rgba(78,205,196,0.2)", glow: "none" },
  LOW: { color: "#7b8794", bg: "rgba(123,135,148,0.04)", border: "rgba(123,135,148,0.15)", glow: "none" }
};

const categoryIcons = {
  macro: "◆", political: "★", tech: "⬡", crypto: "◈", structural: "◇",
  ai_disruption: "⬡", metals: "◈", equities: "◆", volatility: "◇"
};

// ── Components ──

const PulsingDot = ({ color }) => (
  <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: color, marginRight: 8, animation: "pulse 2s ease-in-out infinite", boxShadow: `0 0 8px ${color}` }} />
);

const OutcomeCard = ({ outcome, idx }) => {
  const probWidth = `${outcome.probability * 100}%`;
  const probColor = outcome.probability > 0.4 ? "#4ecdc4" : outcome.probability > 0.25 ? "#ff9f1c" : "#7b8794";
  return (
    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, padding: "14px 16px", marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, fontWeight: 700, color: "#e8e6e3", letterSpacing: "0.02em" }}>{outcome.scenario}</span>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: probColor, fontWeight: 600 }}>{(outcome.probability * 100).toFixed(0)}%</span>
      </div>
      <div style={{ height: 3, background: "rgba(255,255,255,0.05)", borderRadius: 2, marginBottom: 10, overflow: "hidden" }}>
        <div style={{ height: "100%", width: probWidth, background: `linear-gradient(90deg, ${probColor}, ${probColor}88)`, borderRadius: 2, transition: "width 0.8s ease" }} />
      </div>
      <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 8, fontFamily: "'JetBrains Mono', monospace" }}>
        IMPACT: <span style={{ color: "#c4b5a0" }}>{outcome.marketImpact}</span>
      </div>
      <div style={{ marginBottom: 6 }}>
        <div style={{ fontSize: 10, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4, fontWeight: 600 }}>Trades</div>
        {outcome.trades.map((t, i) => (
          <div key={i} style={{ fontSize: 11, color: "#d4d0c8", padding: "3px 0", display: "flex", alignItems: "flex-start", gap: 6 }}>
            <span style={{ color: "#4ecdc4", flexShrink: 0, fontSize: 8, marginTop: 3 }}>▸</span>
            <span>{t}</span>
          </div>
        ))}
      </div>
      <div>
        <div style={{ fontSize: 10, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4, fontWeight: 600 }}>Opportunities Beyond Trading</div>
        {outcome.opportunities.map((o, i) => (
          <div key={i} style={{ fontSize: 11, color: "#a89f91", padding: "3px 0", display: "flex", alignItems: "flex-start", gap: 6 }}>
            <span style={{ color: "#ff9f1c", flexShrink: 0, fontSize: 8, marginTop: 3 }}>◆</span>
            <span>{o}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

const EventCard = ({ event, isExpanded, onToggle }) => {
  const dte = getDTE(event.date);
  const pc = priorityConfig[event.priority] || priorityConfig.MEDIUM;
  const isUrgent = dte.totalHours < 48 && !dte.isPast;
  const isLive = dte.isPast;

  return (
    <div
      onClick={onToggle}
      style={{
        background: isLive ? "rgba(255,46,76,0.04)" : pc.bg,
        border: `1px solid ${isLive ? "rgba(255,46,76,0.4)" : pc.border}`,
        borderRadius: 12,
        padding: 0,
        marginBottom: 12,
        cursor: "pointer",
        transition: "all 0.3s ease",
        boxShadow: isUrgent ? pc.glow : "none",
        overflow: "hidden",
        animation: isLive ? "livePulse 3s ease-in-out infinite" : "none"
      }}
    >
      {/* Header */}
      <div style={{ padding: "16px 20px", display: "flex", alignItems: "flex-start", gap: 14 }}>
        {/* Priority + Category */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, flexShrink: 0, minWidth: 48 }}>
          <div style={{
            fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fontWeight: 800,
            color: pc.color, letterSpacing: "0.05em",
            padding: "3px 8px", borderRadius: 4,
            background: `${pc.color}15`, border: `1px solid ${pc.color}30`
          }}>
            {event.priority}
          </div>
          <span style={{ fontSize: 18, opacity: 0.6 }}>{categoryIcons[event.category] || "◇"}</span>
        </div>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 6 }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#e8e6e3", lineHeight: 1.3, fontFamily: "'Outfit', sans-serif" }}>
              {isLive && <PulsingDot color="#ff2e4c" />}
              {event.title}
            </h3>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: isUrgent ? 14 : 12,
              fontWeight: isUrgent ? 800 : 600,
              color: isLive ? "#ff2e4c" : isUrgent ? pc.color : "#9ca3af",
              whiteSpace: "nowrap",
              padding: "2px 10px",
              borderRadius: 6,
              background: isLive ? "rgba(255,46,76,0.12)" : isUrgent ? `${pc.color}10` : "transparent"
            }}>
              {isLive ? "● LIVE" : `DTE ${dte.label}`}
            </div>
          </div>

          <p style={{ margin: 0, fontSize: 12, color: "#8a8578", lineHeight: 1.5, fontFamily: "'IBM Plex Sans', sans-serif" }}>
            {event.description ? (event.description.substring(0, isExpanded ? 9999 : 160) + (!isExpanded && event.description.length > 160 ? "..." : "")) : "No description available"}
          </p>

          {/* Asset Tags */}
          {event.assetsAffected && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 10 }}>
              {event.assetsAffected.slice(0, isExpanded ? 999 : 6).map(a => (
                <span key={a} style={{
                  fontFamily: "'JetBrains Mono', monospace", fontSize: 10,
                  color: "#b0a899", background: "rgba(255,255,255,0.04)",
                  padding: "2px 7px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.06)"
                }}>{a}</span>
              ))}
              {!isExpanded && event.assetsAffected.length > 6 && (
                <span style={{ fontSize: 10, color: "#6b7280" }}>+{event.assetsAffected.length - 6}</span>
              )}
            </div>
          )}
        </div>

        {/* Expand Arrow */}
        <div style={{ color: "#6b7280", fontSize: 18, transform: isExpanded ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.3s", flexShrink: 0, marginTop: 2 }}>▾</div>
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div style={{ padding: "0 20px 20px 82px", animation: "fadeIn 0.3s ease" }}>
          {/* Key Stats */}
          {(event.consensus || event.previousValue) && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
              {event.consensus && (
                <div style={{ background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: "10px 14px" }}>
                  <div style={{ fontSize: 10, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Consensus</div>
                  <div style={{ fontSize: 12, color: "#c4b5a0", fontFamily: "'JetBrains Mono', monospace" }}>{event.consensus}</div>
                </div>
              )}
              {event.previousValue && (
                <div style={{ background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: "10px 14px" }}>
                  <div style={{ fontSize: 10, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Previous</div>
                  <div style={{ fontSize: 12, color: "#c4b5a0", fontFamily: "'JetBrains Mono', monospace" }}>{event.previousValue}</div>
                </div>
              )}
            </div>
          )}

          {/* Why It Matters */}
          {event.whyItMatters && (
            <div style={{ background: "rgba(255,159,28,0.04)", border: "1px solid rgba(255,159,28,0.12)", borderRadius: 8, padding: "12px 16px", marginBottom: 16 }}>
              <div style={{ fontSize: 10, color: "#ff9f1c", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700, marginBottom: 6 }}>Why This Matters</div>
              <p style={{ margin: 0, fontSize: 12, color: "#c4b5a0", lineHeight: 1.6, fontFamily: "'IBM Plex Sans', sans-serif" }}>{event.whyItMatters}</p>
            </div>
          )}

          {/* Outcomes */}
          {event.outcomes && event.outcomes.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 11, color: "#8a8578", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700, marginBottom: 10 }}>Scenario Analysis & Opportunities</div>
              {event.outcomes.map((outcome, idx) => (
                <OutcomeCard key={idx} outcome={outcome} idx={idx} />
              ))}
            </div>
          )}

          {/* Telegram Alert Config */}
          {event.telegramAlertConfig && (
            <div style={{ background: "rgba(78,205,196,0.04)", border: "1px solid rgba(78,205,196,0.12)", borderRadius: 8, padding: "12px 16px", marginBottom: 12 }}>
              <div style={{ fontSize: 10, color: "#4ecdc4", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 14 }}>✈</span> Telegram Alert Schedule
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                {Object.entries(event.telegramAlertConfig).map(([key, val]) => (
                  <div key={key} style={{ fontSize: 11, color: "#9ca3af" }}>
                    <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: "#4ecdc4", textTransform: "uppercase", marginBottom: 3 }}>
                      {key.replace("Trigger", "")}
                    </div>
                    {val}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Signal Sources */}
          {event.signalSources && event.signalSources.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              <span style={{ fontSize: 10, color: "#6b7280", marginRight: 4 }}>SOURCES:</span>
              {event.signalSources.map(s => (
                <span key={s} style={{
                  fontFamily: "'JetBrains Mono', monospace", fontSize: 9,
                  color: "#7b8794", background: "rgba(255,255,255,0.03)",
                  padding: "2px 6px", borderRadius: 3
                }}>{s}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ── Main Dashboard ──
export default function HydraCommandCenter() {
  // Data state
  const [signals, setSignals] = useState([]);
  const [summary, setSummary] = useState({ critical: 0, high: 0, medium: 0, low: 0, total_active: 0 });

  // UI state
  const [expandedId, setExpandedId] = useState(null);
  const [filter, setFilter] = useState("all");
  const [sortBy, setSortBy] = useState("dte");
  const [now, setNow] = useState(new Date());

  // Connection state
  const [connectionStatus, setConnectionStatus] = useState("connecting");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  // Refs
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);

  // Fetch dashboard data from API
  const fetchDashboardData = useCallback(async () => {
    try {
      const res = await fetch('/api/dashboard');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSignals(data.signals || []);
      setSummary(data.summary || {});
      setIsLoading(false);
      setError(null);
    } catch (err) {
      setError(err.message);
      setIsLoading(false);
    }
  }, []);

  // WebSocket connection with auto-reconnect
  const connectWebSocket = useCallback(() => {
    if (wsRef.current) wsRef.current.close();

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnectionStatus("connected");
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "init" || msg.type === "signals_update") {
          setSignals(msg.signals || []);
          setSummary(msg.summary || {});
          setIsLoading(false);
        }
      } catch (err) {
        console.error("WebSocket message parse error:", err);
      }
    };

    ws.onclose = () => {
      setConnectionStatus("disconnected");
      reconnectTimeoutRef.current = setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => setConnectionStatus("error");
  }, []);

  // Initialize data fetching and WebSocket connection
  useEffect(() => {
    fetchDashboardData();
    connectWebSocket();
    const clockInterval = setInterval(() => setNow(new Date()), 30000);

    return () => {
      clearInterval(clockInterval);
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, [fetchDashboardData, connectWebSocket]);

  // Use signals from API/WebSocket, fallback to static EVENTS_DB if empty
  const displayEvents = signals.length > 0 ? signals : EVENTS_DB;

  const events = displayEvents
    .filter(e => filter === "all" || e.category === filter || e.priority === filter)
    .sort((a, b) => {
      if (sortBy === "dte") return new Date(a.date) - new Date(b.date);
      if (sortBy === "priority") {
        const order = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
        return (order[a.priority] || 3) - (order[b.priority] || 3);
      }
      if (sortBy === "impact") return (b.impact || 0) - (a.impact || 0);
      return 0;
    });

  // Use summary from API/WebSocket for counts
  const critCount = summary.critical || displayEvents.filter(e => e.priority === "CRITICAL").length;
  const urgentCount = summary.high || displayEvents.filter(e => getDTE(e.date).totalHours < 72 && !getDTE(e.date).isPast).length;
  const liveCount = displayEvents.filter(e => getDTE(e.date).isPast).length;
  const totalCount = summary.total_active || displayEvents.length;

  return (
    <div style={{
      minHeight: "100vh", background: "#0c0b0a",
      fontFamily: "'IBM Plex Sans', 'Outfit', sans-serif", color: "#e8e6e3",
      position: "relative", overflow: "hidden"
    }}>
      {/* Loading overlay */}
      {isLoading && (
        <div style={{position:"fixed",inset:0,background:"rgba(12,11,10,0.95)",display:"flex",alignItems:"center",justifyContent:"center",zIndex:1000}}>
          <div style={{fontFamily:"'JetBrains Mono',monospace",fontSize:14,color:"#4ecdc4"}}>
            HYDRA INITIALIZING...
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && !isLoading && (
        <div style={{position:"fixed",top:0,left:0,right:0,background:"rgba(255,46,76,0.9)",padding:"10px 20px",zIndex:999,fontFamily:"'JetBrains Mono',monospace",fontSize:12,color:"#fff",textAlign:"center"}}>
          CONNECTION ERROR: {error} — Attempting reconnect...
        </div>
      )}

      {/* Texture overlay */}
      <div style={{
        position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0,
        background: "radial-gradient(ellipse at 20% 20%, rgba(255,159,28,0.015) 0%, transparent 50%), radial-gradient(ellipse at 80% 80%, rgba(78,205,196,0.01) 0%, transparent 50%)"
      }} />

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes livePulse { 0%, 100% { box-shadow: 0 0 0 rgba(255,46,76,0); } 50% { box-shadow: 0 0 20px rgba(255,46,76,0.08); } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes scanline { 0% { transform: translateY(-100%); } 100% { transform: translateY(100vh); } }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: rgba(255,255,255,0.02); }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 3px; }
      `}</style>

      <div style={{ position: "relative", zIndex: 1, maxWidth: 900, margin: "0 auto", padding: "24px 16px" }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#4ecdc4", letterSpacing: "0.2em", fontWeight: 600 }}>HYDRA</div>
                <div style={{ width: 1, height: 14, background: "rgba(255,255,255,0.1)" }} />
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#6b7280", letterSpacing: "0.1em" }}>COMMAND CENTER</div>
              </div>
              <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, color: "#e8e6e3", fontFamily: "'Outfit', sans-serif", letterSpacing: "-0.02em" }}>
                Event Intelligence
              </h1>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "#6b7280", fontFamily: "'IBM Plex Sans', sans-serif" }}>
                Priority-ranked macro, crypto, metals & disruption events with opportunity mapping
              </p>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#8a8578" }}>
                {now.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}
              </div>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 18, color: "#c4b5a0", fontWeight: 600 }}>
                {now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true })}
              </div>
            </div>
          </div>

          {/* Status Bar */}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
            {[
              { label: "CRITICAL", value: critCount, color: "#ff2e4c" },
              { label: "WITHIN 72H", value: urgentCount, color: "#ff9f1c" },
              { label: "LIVE", value: liveCount, color: liveCount > 0 ? "#ff2e4c" : "#4ecdc4" },
              { label: "TOTAL", value: totalCount, color: "#7b8794" }
            ].map(s => (
              <div key={s.label} style={{
                display: "flex", alignItems: "center", gap: 8,
                background: `${s.color}08`, border: `1px solid ${s.color}20`,
                padding: "6px 14px", borderRadius: 8
              }}>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 16, fontWeight: 800, color: s.color }}>{s.value}</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: "#6b7280", letterSpacing: "0.08em" }}>{s.label}</span>
              </div>
            ))}
            <div style={{
              marginLeft: "auto", display: "flex", alignItems: "center", gap: 6,
              background: connectionStatus === "connected" ? "rgba(78,205,196,0.06)" : "rgba(255,46,76,0.06)",
              border: `1px solid ${connectionStatus === "connected" ? "rgba(78,205,196,0.2)" : "rgba(255,46,76,0.2)"}`,
              padding: "6px 14px", borderRadius: 8
            }}>
              <span style={{ fontSize: 13 }}>◉</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: connectionStatus === "connected" ? "#4ecdc4" : "#ff2e4c", letterSpacing: "0.06em" }}>
                WS: {connectionStatus.toUpperCase()}
              </span>
            </div>
          </div>

          {/* Filters */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {[
              { key: "all", label: "ALL" },
              { key: "CRITICAL", label: "CRITICAL" },
              { key: "macro", label: "MACRO" },
              { key: "crypto", label: "CRYPTO" },
              { key: "ai_disruption", label: "AI/TECH" },
              { key: "structural", label: "STRUCTURAL" },
              { key: "political", label: "POLITICAL" }
            ].map(f => (
              <button key={f.key} onClick={() => setFilter(f.key)} style={{
                fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fontWeight: 600,
                letterSpacing: "0.06em", padding: "5px 12px", borderRadius: 6,
                border: `1px solid ${filter === f.key ? "#4ecdc4" : "rgba(255,255,255,0.08)"}`,
                background: filter === f.key ? "rgba(78,205,196,0.08)" : "transparent",
                color: filter === f.key ? "#4ecdc4" : "#7b8794",
                cursor: "pointer", transition: "all 0.2s"
              }}>{f.label}</button>
            ))}
            <div style={{ marginLeft: "auto", display: "flex", gap: 4, alignItems: "center" }}>
              <span style={{ fontSize: 10, color: "#6b7280", fontFamily: "'JetBrains Mono', monospace" }}>SORT:</span>
              {[
                { key: "dte", label: "DTE" },
                { key: "priority", label: "PRIORITY" },
                { key: "impact", label: "IMPACT" }
              ].map(s => (
                <button key={s.key} onClick={() => setSortBy(s.key)} style={{
                  fontFamily: "'JetBrains Mono', monospace", fontSize: 9,
                  padding: "3px 8px", borderRadius: 4,
                  border: `1px solid ${sortBy === s.key ? "#ff9f1c40" : "rgba(255,255,255,0.06)"}`,
                  background: sortBy === s.key ? "rgba(255,159,28,0.06)" : "transparent",
                  color: sortBy === s.key ? "#ff9f1c" : "#6b7280",
                  cursor: "pointer"
                }}>{s.label}</button>
              ))}
            </div>
          </div>
        </div>

        {/* Events List */}
        <div>
          {events.length === 0 && !isLoading && (
            <div style={{ textAlign: "center", padding: "60px 20px", color: "#6b7280", fontFamily: "'JetBrains Mono', monospace", fontSize: 13 }}>
              {error ? "Unable to load signals. Retrying..." : "No signals available. Waiting for data..."}
            </div>
          )}
          {events.map(event => (
            <EventCard
              key={event.id}
              event={event}
              isExpanded={expandedId === event.id}
              onToggle={() => setExpandedId(expandedId === event.id ? null : event.id)}
            />
          ))}
        </div>

        {/* Telegram Integration Logic Panel */}
        <div style={{
          marginTop: 24, background: "rgba(78,205,196,0.03)",
          border: "1px solid rgba(78,205,196,0.1)", borderRadius: 12, padding: 20
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <span style={{ fontSize: 16 }}>✈</span>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "#4ecdc4", fontFamily: "'Outfit', sans-serif" }}>
              Telegram Signal Integration
            </h3>
          </div>
          <div style={{ fontSize: 12, color: "#8a8578", lineHeight: 1.7, fontFamily: "'IBM Plex Sans', sans-serif", marginBottom: 14 }}>
            Connect your Telegram signal channel to feed alerts into HYDRA. The system will parse incoming messages, classify them by event type, and auto-generate trade proposals through the engine.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div style={{ background: "rgba(0,0,0,0.2)", borderRadius: 8, padding: 12 }}>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#4ecdc4", marginBottom: 8, letterSpacing: "0.08em" }}>INBOUND (Telegram → HYDRA)</div>
              <div style={{ fontSize: 11, color: "#9ca3af", lineHeight: 1.6 }}>
                Signal messages parsed via Bot API<br/>
                NLP classification: macro / crypto / metals / tech<br/>
                Priority scoring based on keyword extraction<br/>
                Auto-attach to matching event in calendar<br/>
                Generate TradeProposal if confidence &gt; 0.6
              </div>
            </div>
            <div style={{ background: "rgba(0,0,0,0.2)", borderRadius: 8, padding: 12 }}>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#ff9f1c", marginBottom: 8, letterSpacing: "0.08em" }}>OUTBOUND (HYDRA → Telegram)</div>
              <div style={{ fontSize: 11, color: "#9ca3af", lineHeight: 1.6 }}>
                Pre-event alerts at configured intervals<br/>
                Live event data push on release<br/>
                Post-event direction confirmation + trade signal<br/>
                Daily portfolio summary at market close<br/>
                Kill switch notification if daily loss limit hit
              </div>
            </div>
          </div>
          <div style={{ background: "rgba(0,0,0,0.3)", borderRadius: 8, padding: 14, fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#6b7280", lineHeight: 1.8, overflowX: "auto" }}>
            <span style={{ color: "#4ecdc4" }}>// Configuration required in hydra_engine.py:</span><br/>
            <span style={{ color: "#ff9f1c" }}>TELEGRAM_BOT_TOKEN</span> = <span style={{ color: "#c4b5a0" }}>"your_bot_token"</span><br/>
            <span style={{ color: "#ff9f1c" }}>TELEGRAM_CHAT_ID</span> = <span style={{ color: "#c4b5a0" }}>"your_chat_id"</span><br/>
            <span style={{ color: "#ff9f1c" }}>SIGNAL_CHANNEL_ID</span> = <span style={{ color: "#c4b5a0" }}>"@your_signal_channel"</span><br/>
            <br/>
            <span style={{ color: "#4ecdc4" }}>// Inbound signal parsing pattern:</span><br/>
            <span style={{ color: "#9ca3af" }}>{"{"} direction: BUY|SELL, asset: "BTC", entry: 70000,</span><br/>
            <span style={{ color: "#9ca3af" }}>{"  "}stop: 67000, target: 78000, confidence: 0.7 {"}"}</span>
          </div>
        </div>

        {/* Footer */}
        <div style={{ marginTop: 24, padding: "16px 0", borderTop: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: "#4a4a4a", letterSpacing: "0.05em" }}>
            HYDRA ENGINE v1.0 — Event Intelligence Module — Paper Trading Only
          </div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: "#4a4a4a" }}>
            Not financial advice. Trading involves substantial risk.
          </div>
        </div>
      </div>
    </div>
  );
}
