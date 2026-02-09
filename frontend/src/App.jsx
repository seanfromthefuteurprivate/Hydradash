import { useState, useEffect, useCallback, useRef } from "react";

// ══════════════════════════════════════════════════════════════
//  HYDRA COMMAND CENTER — Event Intelligence & Alert Dashboard
// ══════════════════════════════════════════════════════════════

// ── DATA: Event Database with full intelligence ──
const EVENTS_DB = [
  {
    id: "nfp-jan-2026",
    title: "January NFP Release (Delayed)",
    category: "macro",
    subcategory: "labor",
    date: "2026-02-11T13:30:00Z",
    priority: "CRITICAL",
    impact: 0.95,
    description: "Bureau of Labor Statistics releases delayed January jobs report. Market has been starved for this data since government shutdown pushed it from Feb 6. Information vacuum has amplified volatility all week.",
    consensus: "~70K jobs added, unemployment 4.3%",
    previousValue: "+50K (December)",
    whyItMatters: "This is the single most important data point in weeks. The labor market is cracking — JOLTS showed openings at lowest since 2020, ADP showed only 22K private jobs. If NFP confirms weakness, it validates the 'AI kills jobs' narrative and could trigger another leg down. If it beats, massive relief rally.",
    outcomes: [
      {
        scenario: "STRONG (>120K)",
        probability: 0.15,
        marketImpact: "SPY +1.5-2.5%, TLT -1.5%, Gold -2%, BTC +3-5%",
        trades: ["Buy SPY 0DTE calls at 8:25 AM", "Short TLT", "Buy TQQQ for momentum"],
        opportunities: ["Relief rally = sell premium on VIX", "Software stocks bounce = buy CRM/SHOP calls", "Risk-on = buy crypto dip"]
      },
      {
        scenario: "IN-LINE (50-90K)",
        probability: 0.45,
        marketImpact: "SPY ±0.5%, TLT +0.5%, muted reaction",
        trades: ["Sell iron condors on SPX (range-bound)", "Fade any initial spike"],
        opportunities: ["Volatility crush = sell UVXY calls", "Market stabilizes = sector rotation plays resume"]
      },
      {
        scenario: "WEAK (<50K)",
        probability: 0.30,
        marketImpact: "SPY -2-3%, TLT +2%, Gold +2%, BTC -5-8%",
        trades: ["Buy SPY 0DTE puts at 8:25 AM", "Buy TLT calls aggressively", "Buy GLD calls"],
        opportunities: ["Rate cut odds spike = mortgage/housing stocks (XHB)", "Labor weakness = automation/AI stocks benefit (PLTR, NVDA)", "Gold reclaims $5,000+"]
      },
      {
        scenario: "DISASTER (<0, negative)",
        probability: 0.10,
        marketImpact: "SPY -3-5%, TLT +3-4%, Gold +3-5%, VIX >30",
        trades: ["Buy deep OTM SPY puts (10x potential)", "Max long TLT", "Buy VIX calls"],
        opportunities: ["Emergency Fed cut speculation = buy rate-sensitive assets", "Full recession pricing = short cyclicals, long defensives", "Consulting demand spikes as companies restructure"]
      }
    ],
    assetsAffected: ["SPY", "QQQ", "TLT", "GLD", "SLV", "BTC", "XLF", "IWM", "UVXY"],
    signalSources: ["BLS.gov", "ADP (leading indicator)", "Challenger layoffs", "JOLTS"],
    telegramAlertConfig: {
      preTrigger: "4hr before release",
      liveTrigger: "On release at 8:30 AM ET",
      postTrigger: "15min after for direction confirmation"
    }
  },
  {
    id: "cpi-jan-2026",
    title: "January CPI Report",
    category: "macro",
    subcategory: "inflation",
    date: "2026-02-13T13:30:00Z",
    priority: "CRITICAL",
    impact: 0.90,
    description: "Consumer Price Index for January. Pushed from Feb 12 due to shutdown. Core CPI MoM is what matters — not headline. Hot inflation + weak jobs = stagflation nightmare. Cool inflation = Fed can cut.",
    consensus: "Core CPI MoM +0.25%, YoY 3.1%",
    previousValue: "Core MoM +0.23%, YoY 3.2%",
    whyItMatters: "Coming 2 days after NFP, this creates a back-to-back data gauntlet. If NFP is weak on Tuesday and CPI is hot on Thursday, the market faces the worst possible combo: stagflation. If both are benign, massive rally as uncertainty clears.",
    outcomes: [
      {
        scenario: "HOT (Core MoM >0.35%)",
        probability: 0.20,
        marketImpact: "SPY -1.5-2.5%, TLT -1.5%, Gold initially -1% then +2%",
        trades: ["Buy SPY puts", "Sell TLT", "Buy TIPS (TIP ETF)", "Buy GLD after initial dip"],
        opportunities: ["Inflation hedge demand surges", "TIPS outperform nominal bonds", "Energy stocks benefit (XLE)", "Pricing power stocks win (luxury, toll roads)"]
      },
      {
        scenario: "IN-LINE (Core MoM 0.2-0.3%)",
        probability: 0.50,
        marketImpact: "SPY ±0.5%, muted",
        trades: ["Sell strangles", "Fade initial move"],
        opportunities: ["Uncertainty resolved = vol crush", "Back to stock-picking environment"]
      },
      {
        scenario: "COOL (Core MoM <0.2%)",
        probability: 0.30,
        marketImpact: "SPY +1-2%, TLT +1.5%, Gold +1%",
        trades: ["Buy SPY calls", "Buy TLT calls", "Long IWM (small caps love rate cuts)"],
        opportunities: ["Fed cut March odds spike", "Growth stocks rip (QQQ outperforms)", "Homebuilders rally (XHB)", "Mortgage refinancing wave = fintech opportunity"]
      }
    ],
    assetsAffected: ["SPY", "TLT", "GLD", "SLV", "TIP", "XLE", "XHB", "IWM"],
    signalSources: ["BLS.gov", "Cleveland Fed Nowcast", "ISM Prices Paid (leading)"],
    telegramAlertConfig: {
      preTrigger: "4hr before",
      liveTrigger: "On release",
      postTrigger: "15min after"
    }
  },
  {
    id: "chinese-new-year-2026",
    title: "Chinese New Year — Metals Liquidity Drought",
    category: "structural",
    subcategory: "liquidity",
    date: "2026-02-16T00:00:00Z",
    priority: "HIGH",
    impact: 0.75,
    description: "Shanghai exchanges closed Feb 16-23. Chinese speculative capital (which drove gold to $5,600 and silver to $121) goes dormant. Thin markets = extreme, unpredictable price moves in precious metals.",
    consensus: "Reduced volume, wider spreads, flash moves likely",
    previousValue: "Last year: gold moved 8% during CNY week",
    whyItMatters: "Chinese speculators have been the marginal buyer/seller of gold and silver for months. Their absence creates a vacuum. Any news catalyst during this week will produce outsized moves because there's no liquidity to absorb it.",
    outcomes: [
      {
        scenario: "LOW VOL (Nothing happens)",
        probability: 0.30,
        marketImpact: "Gold/Silver drift sideways, slight recovery",
        trades: ["Sell premium on GLD/SLV — collect theta in low-vol environment"],
        opportunities: ["Physical gold buying opportunity while paper markets are quiet"]
      },
      {
        scenario: "FLASH CRASH (Surprise catalyst)",
        probability: 0.35,
        marketImpact: "Silver -10-20% intraday, Gold -5-10%",
        trades: ["Pre-position with SLV straddles expiring Feb 21", "Buy dip if silver touches $70 support again"],
        opportunities: ["Physical premium spikes = industrial buyers step in", "Mining stocks (GDX) don't fall as much = pairs trade", "Solar panel manufacturers lock in silver supply contracts"]
      },
      {
        scenario: "FLASH RALLY (Short squeeze)",
        probability: 0.35,
        marketImpact: "Silver +10-15% on short covering, Gold +5-8%",
        trades: ["Pre-position with SLV call spreads", "Buy GDX calls for leverage"],
        opportunities: ["Silver jewelry/industrial demand at discounted prices", "Streaming companies (WPM, FNV) benefit from higher metal prices"]
      }
    ],
    assetsAffected: ["GLD", "SLV", "GDX", "SIL", "WPM", "GOLD", "NEM"],
    signalSources: ["SGE premium/discount", "SHFE trading volume", "CME margin notices"],
    telegramAlertConfig: {
      preTrigger: "48hr before CNY start",
      liveTrigger: "Daily during CNY week",
      postTrigger: "On CNY end for resumption trade"
    }
  },
  {
    id: "warsh-confirmation",
    title: "Kevin Warsh Fed Chair Confirmation Watch",
    category: "political",
    subcategory: "fed",
    date: "2026-03-01T00:00:00Z",
    priority: "HIGH",
    impact: 0.85,
    description: "Senate Banking Committee confirmation hearings for Trump's Fed Chair nominee Kevin Warsh. His nomination crashed gold 21% and silver 41%. Any dovish comments = metals rally. Hawkish = dollar strength continues.",
    consensus: "Expected confirmation, but hearings could be contentious",
    previousValue: "Nomination alone caused $3.4T gold market cap loss",
    whyItMatters: "Warsh is perceived as hawkish. If he signals continuity with Powell's approach, markets calm. If he signals aggressive tightening or dollar-strengthening policy, metals and crypto face another leg down. If he's surprisingly dovish, everything reverses.",
    outcomes: [
      {
        scenario: "HAWKISH TESTIMONY",
        probability: 0.35,
        marketImpact: "Gold -3-5%, DXY +1%, TLT -1%, BTC -5%",
        trades: ["Buy UUP (dollar bull ETF)", "Short GLD", "Short BTC"],
        opportunities: ["Strong dollar benefits importers", "USD-denominated debt becomes cheaper for US companies", "Travel abroad becomes cheaper (tourism services)"]
      },
      {
        scenario: "NEUTRAL/BALANCED",
        probability: 0.40,
        marketImpact: "Muted reaction, slight relief rally in metals",
        trades: ["Buy gold dip into $4,800 support", "Sell vol"],
        opportunities: ["Uncertainty reduction benefits all risk assets"]
      },
      {
        scenario: "SURPRISINGLY DOVISH",
        probability: 0.25,
        marketImpact: "Gold +5-8%, Silver +10%, BTC +8%, TLT +2%",
        trades: ["Aggressive long gold/silver", "Buy BTC", "Buy TLT calls"],
        opportunities: ["Rate cut acceleration = real estate, construction, lending boom", "Gold supply companies benefit massively", "EM currencies rally = EM ETF opportunity"]
      }
    ],
    assetsAffected: ["GLD", "SLV", "TLT", "UUP", "BTC", "EEM", "XHB"],
    signalSources: ["Senate Banking Committee schedule", "Prediction markets (Polymarket)", "Fed Funds futures"],
    telegramAlertConfig: {
      preTrigger: "24hr before hearings",
      liveTrigger: "Real-time during testimony",
      postTrigger: "Market close summary"
    }
  },
  {
    id: "openai-frontier-launch",
    title: "OpenAI Frontier Platform Rollout",
    category: "tech",
    subcategory: "ai_disruption",
    date: "2026-02-10T00:00:00Z",
    priority: "HIGH",
    impact: 0.70,
    description: "OpenAI launched 'Frontier' — a semantic operating system that sits ABOVE existing apps, treating Salesforce, Adobe, etc. as data silos. Combined with Anthropic's Cowork plugins, this is a double-barrel attack on enterprise SaaS.",
    consensus: "Further pressure on software stocks expected",
    previousValue: "Anthropic plugins alone wiped $285B from SaaS",
    whyItMatters: "Two of the three largest AI labs are now DIRECTLY competing with enterprise software. This isn't speculation anymore — it's product. The question shifts from 'will AI disrupt SaaS?' to 'how fast?'",
    outcomes: [
      {
        scenario: "FRONTIER GAINS TRACTION",
        probability: 0.40,
        marketImpact: "IGV -3-5%, CRM -5%, Salesforce ecosystem stocks down",
        trades: ["Short IGV or buy puts", "Short CRM specifically", "Long NVDA (compute demand)"],
        opportunities: ["AI integration consulting demand explodes", "Custom AI agent development becomes a new industry", "Data migration services needed as companies switch platforms", "Cybersecurity for AI agents = new market (CRWD, PANW benefit)"]
      },
      {
        scenario: "MARKET FATIGUED, NO REACTION",
        probability: 0.35,
        marketImpact: "SaaS stocks stabilize, relief bounce possible",
        trades: ["Buy oversold SaaS names (SHOP, ADBE)", "Sell UVXY calls"],
        opportunities: ["Enterprise software at discount valuations = M&A targets", "Buy infrastructure (AWS, Azure) as AI increases compute spend"]
      },
      {
        scenario: "BACKLASH / SECURITY CONCERNS",
        probability: 0.25,
        marketImpact: "SaaS relief rally +3-5%, AI stocks down",
        trades: ["Buy CRM, WDAY on security narrative", "Short speculative AI names"],
        opportunities: ["Enterprise security consulting boom", "Data governance and compliance services", "Traditional software gains 'trust premium'"]
      }
    ],
    assetsAffected: ["IGV", "CRM", "ADBE", "WDAY", "SHOP", "NVDA", "MSFT", "CRWD"],
    signalSources: ["OpenAI blog", "GitHub releases", "HackerNews/ProductHunt", "Enterprise CIO surveys"],
    telegramAlertConfig: {
      preTrigger: "On any new OpenAI/Anthropic release",
      liveTrigger: "Market reaction monitoring",
      postTrigger: "End of day summary"
    }
  },
  {
    id: "btc-60k-support-test",
    title: "Bitcoin $60K Support Retest",
    category: "crypto",
    subcategory: "technical",
    date: "2026-02-09T00:00:00Z",
    priority: "MEDIUM",
    impact: 0.65,
    description: "BTC bounced from $60K to $71K but analysts warn the $58-60K zone (200-day MA and realized price) remains a magnet. If macro data is weak on Feb 11, BTC likely retests. This level = massive long liquidation cluster.",
    consensus: "$58-60K is do-or-die support. Break below = $40-50K risk.",
    previousValue: "Bounced from $60,062 to $71,458 in 24hrs on Feb 5-6",
    whyItMatters: "BTC is down 45% from its $126K October high. It's erased all Trump-election gains. ETFs are now net sellers. If $60K breaks, the next support is $50K and the 'digital gold' narrative is dead for this cycle.",
    outcomes: [
      {
        scenario: "HOLDS $60K, RECOVERS TO $80K+",
        probability: 0.30,
        marketImpact: "BTC +15-20%, ETH +20-25%, mining stocks +20%",
        trades: ["Buy BTC/USD at $62-65K with stop at $58K", "Buy MARA, CLSK calls", "Buy ETH/USD"],
        opportunities: ["Crypto custody services demand increases", "Stablecoin yield farming returns normalize", "DeFi TVL recovery"]
      },
      {
        scenario: "RANGES $60-75K FOR WEEKS",
        probability: 0.35,
        marketImpact: "Crypto vol compression, altcoins bleed",
        trades: ["Sell BTC strangles on Deribit", "Harvest funding rate (negative = paid to be long)"],
        opportunities: ["Build positions in quality altcoins at depressed prices", "Crypto infrastructure (exchanges, wallets) remains essential regardless of price"]
      },
      {
        scenario: "BREAKS $60K, CASCADES TO $45-50K",
        probability: 0.35,
        marketImpact: "BTC -25-30%, entire crypto market -30-50%, COIN -20%",
        trades: ["Short BTC/USD if $58K breaks", "Buy BITO puts", "Short COIN"],
        opportunities: ["Accumulate BTC at cycle lows for long-term", "Mining company acquisitions at pennies on the dollar", "Blockchain infrastructure development continues regardless", "Counter-narrative: institutional adoption still growing"]
      }
    ],
    assetsAffected: ["BTC/USD", "ETH/USD", "COIN", "MARA", "CLSK", "BITO", "MSTR"],
    signalSources: ["CoinGlass liquidation map", "Binance funding rates", "BTC ETF flow (Farside)", "CryptoQuant on-chain"],
    telegramAlertConfig: {
      preTrigger: "When BTC within 3% of $60K",
      liveTrigger: "On break below $60K",
      postTrigger: "Hourly updates during cascade"
    }
  },
  {
    id: "token-unlocks-week",
    title: "16 Altcoin Token Unlocks This Week",
    category: "crypto",
    subcategory: "supply",
    date: "2026-02-10T00:00:00Z",
    priority: "MEDIUM",
    impact: 0.55,
    description: "Massive token unlock events across 16 altcoins next week. When tokens unlock, supply floods the market. In this already-weak crypto environment, unlocks could accelerate selling pressure on specific tokens.",
    consensus: "Expect 5-15% additional downside pressure on affected tokens",
    previousValue: "Previous large unlock weeks saw 8-12% average decline in affected tokens",
    whyItMatters: "Token unlocks are one of the few PREDICTABLE events in crypto. The selling pressure is mechanical — team members, early investors, and VCs who've been locked up want to de-risk at any price. This is the crypto equivalent of insider selling after lockup expiry.",
    outcomes: [
      {
        scenario: "UNLOCKS CAUSE CASCADING SELL",
        probability: 0.50,
        marketImpact: "Affected altcoins -10-20%, BTC dragged -2-3%",
        trades: ["Short affected tokens pre-unlock", "Buy puts on crypto-adjacent stocks (COIN)"],
        opportunities: ["Accumulate quality altcoins at distressed prices post-unlock", "Provide liquidity (market making) during high-vol unlock periods"]
      },
      {
        scenario: "PRICED IN, MINIMAL IMPACT",
        probability: 0.50,
        marketImpact: "Affected tokens -2-5%, quickly absorbed",
        trades: ["Buy the dip on quality names that oversold in anticipation"],
        opportunities: ["Unlock absorption = demand signal for strong projects"]
      }
    ],
    assetsAffected: ["Various altcoins", "COIN", "BTC/USD", "ETH/USD"],
    signalSources: ["TokenUnlocks.app", "CoinGecko unlock calendar", "On-chain vesting contracts"],
    telegramAlertConfig: {
      preTrigger: "24hr before each unlock",
      liveTrigger: "On unlock",
      postTrigger: "Price impact summary"
    }
  },
  {
    id: "silver-industrial-demand",
    title: "Silver Industrial Demand vs Paper Crash Divergence",
    category: "structural",
    subcategory: "supply_demand",
    date: "2026-02-15T00:00:00Z",
    priority: "MEDIUM",
    impact: 0.70,
    description: "Silver's paper market crashed 41% but physical demand for AI/solar/EV applications is structurally growing. The divergence between paper price and physical demand creates an opportunity. Watch physical premiums — when they spike, the bottom is in.",
    consensus: "Silver in structural deficit due to AI compute and solar demand",
    previousValue: "Silver hit $121 before crashing to $71. Now ~$83.",
    whyItMatters: "Every AI data center needs silver for thermal management and connectors. Every solar panel needs silver. Global silver mine supply is DECLINING while demand from green energy + AI is INCREASING. The paper market crash is a gift for physical buyers.",
    outcomes: [
      {
        scenario: "PHYSICAL PREMIUM SPIKES (Shortage signals)",
        probability: 0.40,
        marketImpact: "SLV recovers to $95-100, mining stocks +15-25%",
        trades: ["Buy SLV call spreads 30-60 days", "Buy First Majestic (AG), Pan American Silver (PAAS)"],
        opportunities: ["Silver recycling businesses boom", "Solar panel manufacturers lock in forward contracts", "Silver streaming deals become extremely lucrative", "MINE supply: invest in silver exploration/development companies"]
      },
      {
        scenario: "PAPER AND PHYSICAL BOTH WEAK",
        probability: 0.30,
        marketImpact: "SLV grinds to $70-75, miners suffer",
        trades: ["Stay patient, wait for physical premium signal"],
        opportunities: ["Acquire distressed mining assets", "Silver at production cost = limited further downside"]
      },
      {
        scenario: "PAPER RECOVERS, CATCHES UP TO PHYSICAL",
        probability: 0.30,
        marketImpact: "SLV rallies 20-30% over 2-4 weeks",
        trades: ["Buy SLV aggressively", "Buy GDX/SIL for leverage"],
        opportunities: ["JP Morgan targets silver recovery in H2 2026", "Industrial users re-stock at lower prices"]
      }
    ],
    assetsAffected: ["SLV", "AG", "PAAS", "WPM", "GDX", "SIL", "TAN"],
    signalSources: ["SGE silver premium", "COMEX inventory data", "Silver Institute reports", "Solar installation data"],
    telegramAlertConfig: {
      preTrigger: "On physical premium threshold breach",
      liveTrigger: "Weekly supply report",
      postTrigger: "Monthly demand update"
    }
  }
];

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
  macro: "◆", political: "★", tech: "⬡", crypto: "◈", structural: "◇"
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
  const pc = priorityConfig[event.priority];
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
          <span style={{ fontSize: 18, opacity: 0.6 }}>{categoryIcons[event.category]}</span>
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
            {event.description.substring(0, isExpanded ? 9999 : 160)}{!isExpanded && event.description.length > 160 ? "..." : ""}
          </p>

          {/* Asset Tags */}
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
        </div>

        {/* Expand Arrow */}
        <div style={{ color: "#6b7280", fontSize: 18, transform: isExpanded ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.3s", flexShrink: 0, marginTop: 2 }}>▾</div>
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div style={{ padding: "0 20px 20px 82px", animation: "fadeIn 0.3s ease" }}>
          {/* Key Stats */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
            <div style={{ background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: "10px 14px" }}>
              <div style={{ fontSize: 10, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Consensus</div>
              <div style={{ fontSize: 12, color: "#c4b5a0", fontFamily: "'JetBrains Mono', monospace" }}>{event.consensus}</div>
            </div>
            <div style={{ background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: "10px 14px" }}>
              <div style={{ fontSize: 10, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Previous</div>
              <div style={{ fontSize: 12, color: "#c4b5a0", fontFamily: "'JetBrains Mono', monospace" }}>{event.previousValue}</div>
            </div>
          </div>

          {/* Why It Matters */}
          <div style={{ background: "rgba(255,159,28,0.04)", border: "1px solid rgba(255,159,28,0.12)", borderRadius: 8, padding: "12px 16px", marginBottom: 16 }}>
            <div style={{ fontSize: 10, color: "#ff9f1c", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700, marginBottom: 6 }}>Why This Matters</div>
            <p style={{ margin: 0, fontSize: 12, color: "#c4b5a0", lineHeight: 1.6, fontFamily: "'IBM Plex Sans', sans-serif" }}>{event.whyItMatters}</p>
          </div>

          {/* Outcomes */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: "#8a8578", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700, marginBottom: 10 }}>Scenario Analysis & Opportunities</div>
            {event.outcomes.map((outcome, idx) => (
              <OutcomeCard key={idx} outcome={outcome} idx={idx} />
            ))}
          </div>

          {/* Telegram Alert Config */}
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

          {/* Signal Sources */}
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
        </div>
      )}
    </div>
  );
};

// ── Main Dashboard ──
export default function HydraCommandCenter() {
  const [expandedId, setExpandedId] = useState(null);
  const [filter, setFilter] = useState("all");
  const [sortBy, setSortBy] = useState("dte");
  const [telegramStatus, setTelegramStatus] = useState("disconnected");
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(t);
  }, []);

  const events = EVENTS_DB
    .filter(e => filter === "all" || e.category === filter || e.priority === filter)
    .sort((a, b) => {
      if (sortBy === "dte") return new Date(a.date) - new Date(b.date);
      if (sortBy === "priority") {
        const order = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
        return order[a.priority] - order[b.priority];
      }
      if (sortBy === "impact") return b.impact - a.impact;
      return 0;
    });

  const critCount = EVENTS_DB.filter(e => e.priority === "CRITICAL").length;
  const urgentCount = EVENTS_DB.filter(e => getDTE(e.date).totalHours < 72 && !getDTE(e.date).isPast).length;
  const liveCount = EVENTS_DB.filter(e => getDTE(e.date).isPast).length;

  return (
    <div style={{
      minHeight: "100vh", background: "#0c0b0a",
      fontFamily: "'IBM Plex Sans', 'Outfit', sans-serif", color: "#e8e6e3",
      position: "relative", overflow: "hidden"
    }}>
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
              { label: "TOTAL", value: EVENTS_DB.length, color: "#7b8794" }
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
              background: telegramStatus === "connected" ? "rgba(78,205,196,0.06)" : "rgba(255,46,76,0.06)",
              border: `1px solid ${telegramStatus === "connected" ? "rgba(78,205,196,0.2)" : "rgba(255,46,76,0.2)"}`,
              padding: "6px 14px", borderRadius: 8, cursor: "pointer"
            }} onClick={() => setTelegramStatus(s => s === "connected" ? "disconnected" : "connected")}>
              <span style={{ fontSize: 13 }}>✈</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: telegramStatus === "connected" ? "#4ecdc4" : "#ff2e4c", letterSpacing: "0.06em" }}>
                TG: {telegramStatus.toUpperCase()}
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
              { key: "tech", label: "AI/TECH" },
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
