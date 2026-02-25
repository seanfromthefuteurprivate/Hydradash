import { useState, useEffect, useCallback, useRef } from "react";

// API and WebSocket configuration
const API_BASE = '';  // Same origin
const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

// ══════════════════════════════════════════════════════════════
//  HYDRA COMMAND CENTER — Predictive Intelligence Dashboard
// ══════════════════════════════════════════════════════════════

// ── Utility Functions ──
const getDTE = (dateStr) => {
  const now = new Date();
  const event = new Date(dateStr);
  const diff = event - now;
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
  const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
  if (diff < 0) return { days: 0, hours: 0, minutes: 0, label: "LIVE NOW", isPast: true, totalMinutes: 0 };
  if (days === 0 && hours === 0) return { days: 0, hours: 0, minutes, label: `${minutes}m`, isPast: false, totalMinutes: minutes };
  if (days === 0) return { days: 0, hours, minutes, label: `${hours}h ${minutes}m`, isPast: false, totalMinutes: hours * 60 + minutes };
  return { days, hours, minutes, label: `${days}d ${hours}h`, isPast: false, totalMinutes: days * 24 * 60 + hours * 60 + minutes };
};

const priorityConfig = {
  CRITICAL: { color: "#ff2e4c", bg: "rgba(255,46,76,0.08)", border: "rgba(255,46,76,0.3)", glow: "0 0 20px rgba(255,46,76,0.15)" },
  HIGH: { color: "#ff9f1c", bg: "rgba(255,159,28,0.06)", border: "rgba(255,159,28,0.25)", glow: "0 0 15px rgba(255,159,28,0.1)" },
  MEDIUM: { color: "#4ecdc4", bg: "rgba(78,205,196,0.05)", border: "rgba(78,205,196,0.2)", glow: "none" },
  LOW: { color: "#7b8794", bg: "rgba(123,135,148,0.04)", border: "rgba(123,135,148,0.15)", glow: "none" }
};

// Blowup score color gradient
const getBlowupColor = (score) => {
  if (score >= 70) return "#ff2e4c";      // Red - EXTREME
  if (score >= 50) return "#ff9f1c";      // Orange - HIGH
  if (score >= 30) return "#ffd93d";      // Yellow - ELEVATED
  return "#4ecdc4";                        // Green - CALM
};

const getDirectionColor = (direction) => {
  if (direction === "BEARISH") return "#ff2e4c";
  if (direction === "BULLISH") return "#4ecdc4";
  return "#7b8794";
};

// ── Components ──

const PulsingDot = ({ color }) => (
  <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: color, marginRight: 8, animation: "pulse 2s ease-in-out infinite", boxShadow: `0 0 8px ${color}` }} />
);

// ── BLOWUP PROBABILITY GAUGE ──
const BlowupGauge = ({ score, direction, regime, confidence, triggers, recommendation }) => {
  const color = getBlowupColor(score);
  const dirColor = getDirectionColor(direction);
  const circumference = 2 * Math.PI * 45;
  const strokeDashoffset = circumference - (score / 100) * circumference;

  return (
    <div style={{
      background: "rgba(0,0,0,0.3)",
      border: `2px solid ${color}40`,
      borderRadius: 16,
      padding: 24,
      marginBottom: 20,
      boxShadow: score >= 70 ? `0 0 30px ${color}30` : "none",
      animation: score >= 70 ? "criticalPulse 2s ease-in-out infinite" : "none"
    }}>
      <div style={{ display: "flex", gap: 24, alignItems: "center" }}>
        {/* Circular Gauge */}
        <div style={{ position: "relative", width: 120, height: 120 }}>
          <svg width="120" height="120" style={{ transform: "rotate(-90deg)" }}>
            {/* Background circle */}
            <circle
              cx="60" cy="60" r="45"
              fill="none"
              stroke="rgba(255,255,255,0.1)"
              strokeWidth="10"
            />
            {/* Progress circle */}
            <circle
              cx="60" cy="60" r="45"
              fill="none"
              stroke={color}
              strokeWidth="10"
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
              strokeLinecap="round"
              style={{ transition: "stroke-dashoffset 0.5s ease, stroke 0.5s ease" }}
            />
          </svg>
          <div style={{
            position: "absolute", inset: 0,
            display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center"
          }}>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 32, fontWeight: 800, color: color
            }}>{score}</div>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 9, color: "#6b7280", letterSpacing: "0.1em"
            }}>BLOWUP %</div>
          </div>
        </div>

        {/* Status Info */}
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", gap: 16, marginBottom: 12, flexWrap: "wrap" }}>
            {/* Direction */}
            <div style={{
              background: `${dirColor}15`,
              border: `1px solid ${dirColor}40`,
              borderRadius: 8, padding: "8px 16px"
            }}>
              <div style={{ fontSize: 9, color: "#6b7280", letterSpacing: "0.1em", marginBottom: 2 }}>DIRECTION</div>
              <div style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 14, fontWeight: 700, color: dirColor,
                display: "flex", alignItems: "center", gap: 6
              }}>
                {direction === "BULLISH" ? "▲" : direction === "BEARISH" ? "▼" : "◆"}
                {direction}
              </div>
            </div>

            {/* Regime */}
            <div style={{
              background: "rgba(255,255,255,0.03)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 8, padding: "8px 16px"
            }}>
              <div style={{ fontSize: 9, color: "#6b7280", letterSpacing: "0.1em", marginBottom: 2 }}>REGIME</div>
              <div style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 14, fontWeight: 600, color: "#c4b5a0"
              }}>{regime}</div>
            </div>

            {/* Confidence */}
            <div style={{
              background: "rgba(255,255,255,0.03)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 8, padding: "8px 16px"
            }}>
              <div style={{ fontSize: 9, color: "#6b7280", letterSpacing: "0.1em", marginBottom: 2 }}>CONFIDENCE</div>
              <div style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 14, fontWeight: 600, color: confidence > 0.7 ? "#4ecdc4" : "#ff9f1c"
              }}>{(confidence * 100).toFixed(0)}%</div>
            </div>
          </div>

          {/* Recommendation */}
          <div style={{
            background: score >= 70 ? `${color}15` : "rgba(78,205,196,0.08)",
            border: `1px solid ${score >= 70 ? color : "#4ecdc4"}40`,
            borderRadius: 8, padding: "10px 16px", marginBottom: 12
          }}>
            <div style={{ fontSize: 9, color: "#6b7280", letterSpacing: "0.1em", marginBottom: 4 }}>RECOMMENDATION</div>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 16, fontWeight: 700, color: score >= 70 ? color : "#4ecdc4"
            }}>{recommendation.replace(/_/g, " ")}</div>
          </div>

          {/* Active Triggers */}
          {triggers && triggers.length > 0 && (
            <div>
              <div style={{ fontSize: 9, color: "#6b7280", letterSpacing: "0.1em", marginBottom: 6 }}>ACTIVE TRIGGERS</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {triggers.slice(0, 5).map((t, i) => (
                  <span key={i} style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 10, color: "#ff9f1c",
                    background: "rgba(255,159,28,0.1)",
                    padding: "3px 8px", borderRadius: 4,
                    border: "1px solid rgba(255,159,28,0.3)"
                  }}>{t}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ── MINI SCORE CHART ──
const ScoreChart = ({ scores }) => {
  if (!scores || scores.length === 0) return null;

  const maxScore = Math.max(...scores.map(s => s.score), 100);
  const width = 200;
  const height = 40;

  return (
    <div style={{
      background: "rgba(0,0,0,0.2)",
      borderRadius: 8, padding: 12,
      marginBottom: 16
    }}>
      <div style={{ fontSize: 9, color: "#6b7280", letterSpacing: "0.1em", marginBottom: 8 }}>
        BLOWUP TREND (Last {scores.length})
      </div>
      <svg width={width} height={height}>
        {scores.map((s, i) => {
          const x = (i / (scores.length - 1 || 1)) * (width - 20) + 10;
          const y = height - (s.score / maxScore) * (height - 10) - 5;
          const color = getBlowupColor(s.score);

          return (
            <g key={i}>
              {i > 0 && (
                <line
                  x1={(((i - 1) / (scores.length - 1 || 1)) * (width - 20)) + 10}
                  y1={height - (scores[i - 1].score / maxScore) * (height - 10) - 5}
                  x2={x}
                  y2={y}
                  stroke={color}
                  strokeWidth="2"
                  strokeOpacity="0.5"
                />
              )}
              <circle cx={x} cy={y} r="3" fill={color} />
            </g>
          );
        })}
      </svg>
    </div>
  );
};

// ── EVENT COUNTDOWN ──
const EventCountdown = ({ events }) => {
  if (!events || events.length === 0) {
    return (
      <div style={{
        background: "rgba(0,0,0,0.2)",
        borderRadius: 8, padding: 16, marginBottom: 16,
        textAlign: "center", color: "#6b7280",
        fontFamily: "'JetBrains Mono', monospace", fontSize: 12
      }}>
        No events in next 24 hours
      </div>
    );
  }

  const nextEvent = events[0];
  const dte = getDTE(nextEvent.datetime);

  return (
    <div style={{
      background: dte.totalMinutes < 60 ? "rgba(255,46,76,0.1)" : "rgba(255,159,28,0.06)",
      border: `1px solid ${dte.totalMinutes < 60 ? "rgba(255,46,76,0.3)" : "rgba(255,159,28,0.2)"}`,
      borderRadius: 12, padding: 16, marginBottom: 16
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 9, color: "#6b7280", letterSpacing: "0.1em", marginBottom: 4 }}>NEXT EVENT</div>
          <div style={{
            fontFamily: "'Outfit', sans-serif",
            fontSize: 16, fontWeight: 700, color: "#e8e6e3", marginBottom: 4
          }}>{nextEvent.name}</div>
          <div style={{ fontSize: 11, color: "#8a8578" }}>
            {nextEvent.importance} | {nextEvent.category}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 24, fontWeight: 800,
            color: dte.totalMinutes < 60 ? "#ff2e4c" : "#ff9f1c"
          }}>
            {dte.label}
          </div>
          {dte.totalMinutes < 60 && (
            <div style={{
              fontSize: 10, color: "#ff2e4c",
              animation: "pulse 1s ease-in-out infinite"
            }}>IMMINENT</div>
          )}
        </div>
      </div>

      {nextEvent.consensus && (
        <div style={{
          display: "flex", gap: 16, marginTop: 12,
          background: "rgba(0,0,0,0.2)", borderRadius: 6, padding: 10
        }}>
          <div>
            <div style={{ fontSize: 9, color: "#6b7280" }}>CONSENSUS</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: "#c4b5a0" }}>
              {nextEvent.consensus}{nextEvent.unit}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 9, color: "#6b7280" }}>PREVIOUS</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: "#c4b5a0" }}>
              {nextEvent.previous}{nextEvent.unit}
            </div>
          </div>
        </div>
      )}

      {events.length > 1 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 9, color: "#6b7280", marginBottom: 6 }}>UPCOMING</div>
          {events.slice(1, 4).map((e, i) => (
            <div key={i} style={{
              display: "flex", justifyContent: "space-between",
              fontSize: 11, color: "#8a8578", padding: "4px 0",
              borderTop: "1px solid rgba(255,255,255,0.05)"
            }}>
              <span>{e.name}</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                {getDTE(e.datetime).label}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ── SIGNAL CARD ──
const SignalCard = ({ signal, isExpanded, onToggle }) => {
  const pc = priorityConfig[signal.priority] || priorityConfig.MEDIUM;

  return (
    <div
      onClick={onToggle}
      style={{
        background: pc.bg,
        border: `1px solid ${pc.border}`,
        borderRadius: 10, padding: 14, marginBottom: 10,
        cursor: "pointer", transition: "all 0.2s ease"
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{
              fontFamily: "'JetBrains Mono', monospace", fontSize: 9, fontWeight: 700,
              color: pc.color, padding: "2px 6px", borderRadius: 3,
              background: `${pc.color}15`
            }}>{signal.priority}</span>
            <span style={{ fontSize: 10, color: "#6b7280" }}>{signal.category}</span>
          </div>
          <div style={{
            fontSize: 14, fontWeight: 600, color: "#e8e6e3",
            fontFamily: "'Outfit', sans-serif", marginBottom: 4
          }}>{signal.name}</div>
          <div style={{
            fontSize: 11, color: "#8a8578", lineHeight: 1.5,
            maxHeight: isExpanded ? "none" : 40, overflow: "hidden"
          }}>{signal.description}</div>
        </div>
        <div style={{
          fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
          color: signal.direction > 0 ? "#4ecdc4" : signal.direction < 0 ? "#ff2e4c" : "#7b8794"
        }}>
          {signal.direction > 0 ? "▲ BULL" : signal.direction < 0 ? "▼ BEAR" : "— NEUTRAL"}
        </div>
      </div>

      {isExpanded && signal.affected_assets && (
        <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 4 }}>
          {signal.affected_assets.map((a, i) => (
            <span key={i} style={{
              fontFamily: "'JetBrains Mono', monospace", fontSize: 9,
              color: "#b0a899", background: "rgba(255,255,255,0.04)",
              padding: "2px 6px", borderRadius: 3
            }}>{a}</span>
          ))}
        </div>
      )}
    </div>
  );
};

// ── WSB SNAKE CONNECTION STATUS ──
const WSBSnakeStatus = ({ status }) => (
  <div style={{
    background: status === "connected" ? "rgba(78,205,196,0.08)" : "rgba(255,46,76,0.08)",
    border: `1px solid ${status === "connected" ? "rgba(78,205,196,0.3)" : "rgba(255,46,76,0.3)"}`,
    borderRadius: 8, padding: "8px 12px",
    display: "flex", alignItems: "center", gap: 8
  }}>
    <span style={{ fontSize: 12 }}>🐍</span>
    <span style={{
      fontFamily: "'JetBrains Mono', monospace", fontSize: 10,
      color: status === "connected" ? "#4ecdc4" : "#ff2e4c"
    }}>
      WSB SNAKE: {status.toUpperCase()}
    </span>
  </div>
);

// ── Main Dashboard ──
export default function HydraCommandCenter() {
  // Intelligence data
  const [intelligence, setIntelligence] = useState(null);
  const [signals, setSignals] = useState([]);
  const [recentScores, setRecentScores] = useState([]);

  // UI state
  const [expandedId, setExpandedId] = useState(null);
  const [filter, setFilter] = useState("all");
  const [now, setNow] = useState(new Date());

  // Connection state
  const [connectionStatus, setConnectionStatus] = useState("connecting");
  const [wsbSnakeStatus, setWsbSnakeStatus] = useState("disconnected");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  // Refs
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);

  // Fetch intelligence data
  const fetchIntelligence = useCallback(async () => {
    try {
      const res = await fetch('/api/intelligence');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setIntelligence(data);
      setIsLoading(false);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  // Fetch signals
  const fetchSignals = useCallback(async () => {
    try {
      const res = await fetch('/api/signals');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSignals(data.signals || []);
    } catch (err) {
      console.error("Signals fetch error:", err);
    }
  }, []);

  // Fetch blowup history
  const fetchBlowupHistory = useCallback(async () => {
    try {
      const res = await fetch('/api/blowup/history?count=10');
      if (!res.ok) return;
      const data = await res.json();
      setRecentScores(data.scores || []);
    } catch (err) {
      console.error("History fetch error:", err);
    }
  }, []);

  // WebSocket connection
  const connectWebSocket = useCallback(() => {
    if (wsRef.current) wsRef.current.close();

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => setConnectionStatus("connected");

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "blowup_update" && msg.blowup) {
          setIntelligence(prev => ({
            ...prev,
            blowup_probability: msg.blowup.blowup_probability,
            direction: msg.blowup.direction,
            regime: msg.blowup.regime,
            confidence: msg.blowup.confidence,
            triggers: msg.blowup.triggers,
            recommendation: msg.blowup.recommendation
          }));
        }
        if (msg.type === "signals_update" && msg.signals) {
          setSignals(msg.signals);
        }
      } catch (err) {
        console.error("WS parse error:", err);
      }
    };

    ws.onclose = () => {
      setConnectionStatus("disconnected");
      reconnectTimeoutRef.current = setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => setConnectionStatus("error");
  }, []);

  // Initialize
  useEffect(() => {
    fetchIntelligence();
    fetchSignals();
    fetchBlowupHistory();
    connectWebSocket();

    // Poll intelligence every 30 seconds
    const pollInterval = setInterval(() => {
      fetchIntelligence();
      fetchBlowupHistory();
    }, 30000);

    // Update clock every second
    const clockInterval = setInterval(() => setNow(new Date()), 1000);

    return () => {
      clearInterval(pollInterval);
      clearInterval(clockInterval);
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, [fetchIntelligence, fetchSignals, fetchBlowupHistory, connectWebSocket]);

  // Filter signals
  const filteredSignals = signals.filter(s =>
    filter === "all" || s.category === filter || s.priority === filter
  );

  return (
    <div style={{
      minHeight: "100vh", background: "#0c0b0a",
      fontFamily: "'IBM Plex Sans', 'Outfit', sans-serif", color: "#e8e6e3",
      position: "relative", overflow: "hidden"
    }}>
      {/* Loading overlay */}
      {isLoading && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(12,11,10,0.95)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 14, color: "#4ecdc4" }}>
            HYDRA INTELLIGENCE LOADING...
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && !isLoading && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, background: "rgba(255,46,76,0.9)", padding: "10px 20px", zIndex: 999, fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: "#fff", textAlign: "center" }}>
          CONNECTION ERROR: {error}
        </div>
      )}

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes criticalPulse { 0%, 100% { box-shadow: 0 0 20px rgba(255,46,76,0.2); } 50% { box-shadow: 0 0 40px rgba(255,46,76,0.4); } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: rgba(255,255,255,0.02); }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 3px; }
      `}</style>

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1000, margin: "0 auto", padding: "24px 16px" }}>
        {/* Header */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#4ecdc4", letterSpacing: "0.2em", fontWeight: 600 }}>HYDRA</div>
                <div style={{ width: 1, height: 14, background: "rgba(255,255,255,0.1)" }} />
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#6b7280", letterSpacing: "0.1em" }}>PREDICTIVE INTELLIGENCE</div>
              </div>
              <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, color: "#e8e6e3", fontFamily: "'Outfit', sans-serif", letterSpacing: "-0.02em" }}>
                Blowup Probability Engine
              </h1>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "#6b7280" }}>
                Real-time prediction of violent market moves
              </p>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#8a8578" }}>
                {now.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}
              </div>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 20, color: "#c4b5a0", fontWeight: 600 }}>
                {now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true })}
              </div>
            </div>
          </div>

          {/* Connection Status */}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 6,
              background: connectionStatus === "connected" ? "rgba(78,205,196,0.08)" : "rgba(255,46,76,0.08)",
              border: `1px solid ${connectionStatus === "connected" ? "rgba(78,205,196,0.3)" : "rgba(255,46,76,0.3)"}`,
              padding: "6px 12px", borderRadius: 6
            }}>
              <PulsingDot color={connectionStatus === "connected" ? "#4ecdc4" : "#ff2e4c"} />
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: connectionStatus === "connected" ? "#4ecdc4" : "#ff2e4c" }}>
                WS: {connectionStatus.toUpperCase()}
              </span>
            </div>
            <WSBSnakeStatus status={wsbSnakeStatus} />
          </div>
        </div>

        {/* BLOWUP GAUGE - The Crown Jewel */}
        {intelligence && (
          <BlowupGauge
            score={intelligence.blowup_probability || 0}
            direction={intelligence.direction || "NEUTRAL"}
            regime={intelligence.regime || "UNKNOWN"}
            confidence={intelligence.confidence || 0}
            triggers={intelligence.triggers || []}
            recommendation={intelligence.recommendation || "NO_TRADE"}
          />
        )}

        {/* Two Column Layout */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          {/* Left Column */}
          <div>
            {/* Score History Chart */}
            <ScoreChart scores={recentScores} />

            {/* Event Countdown */}
            {intelligence && (
              <EventCountdown events={intelligence.upcoming_events || []} />
            )}

            {/* Quick Stats */}
            {intelligence && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
                <div style={{
                  background: "rgba(0,0,0,0.2)", borderRadius: 8, padding: 12
                }}>
                  <div style={{ fontSize: 9, color: "#6b7280", letterSpacing: "0.08em" }}>SIGNALS ACTIVE</div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 24, fontWeight: 700, color: "#4ecdc4" }}>
                    {intelligence.signals_active || 0}
                  </div>
                </div>
                <div style={{
                  background: "rgba(0,0,0,0.2)", borderRadius: 8, padding: 12
                }}>
                  <div style={{ fontSize: 9, color: "#6b7280", letterSpacing: "0.08em" }}>CRITICAL</div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 24, fontWeight: 700, color: intelligence.signals_critical > 0 ? "#ff2e4c" : "#4ecdc4" }}>
                    {intelligence.signals_critical || 0}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Right Column - Active Signals */}
          <div>
            <div style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#c4b5a0" }}>ACTIVE SIGNALS</div>
                <div style={{ display: "flex", gap: 4 }}>
                  {["all", "CRITICAL", "HIGH"].map(f => (
                    <button key={f} onClick={() => setFilter(f)} style={{
                      fontFamily: "'JetBrains Mono', monospace", fontSize: 9,
                      padding: "4px 8px", borderRadius: 4,
                      border: `1px solid ${filter === f ? "#4ecdc4" : "rgba(255,255,255,0.1)"}`,
                      background: filter === f ? "rgba(78,205,196,0.1)" : "transparent",
                      color: filter === f ? "#4ecdc4" : "#6b7280",
                      cursor: "pointer"
                    }}>{f}</button>
                  ))}
                </div>
              </div>
            </div>

            <div style={{ maxHeight: 400, overflowY: "auto" }}>
              {filteredSignals.length === 0 ? (
                <div style={{ textAlign: "center", padding: 40, color: "#6b7280", fontSize: 12 }}>
                  No active signals
                </div>
              ) : (
                filteredSignals.slice(0, 10).map(signal => (
                  <SignalCard
                    key={signal.id}
                    signal={signal}
                    isExpanded={expandedId === signal.id}
                    onToggle={() => setExpandedId(expandedId === signal.id ? null : signal.id)}
                  />
                ))
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div style={{ marginTop: 24, padding: "16px 0", borderTop: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: "#4a4a4a", letterSpacing: "0.05em" }}>
            HYDRA ENGINE v2.0 — Predictive Intelligence Module — Paper Trading Only
          </div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: "#4a4a4a" }}>
            Components: {intelligence?.components_healthy || 0}/{intelligence?.components_total || 8} healthy
          </div>
        </div>
      </div>
    </div>
  );
}
