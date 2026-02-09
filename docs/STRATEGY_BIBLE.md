# HYDRA ENGINE — Strategy Bible & Deployment Guide

## What This Is

HYDRA is a multi-asset, multi-strategy, regime-adaptive trading engine designed to operate across equities, options (via ETF proxies), crypto, and precious metals simultaneously. It connects to Alpaca's paper trading API to prove itself before risking real capital.

This is not a "trading bot." It's an **ecosystem** of 5 strategy modules that share intelligence, adapt to market regimes in real-time, and dynamically allocate capital to wherever the mathematical edge is fattest at any given moment.

---

## The Philosophy: Why This Is Different

### What Renaissance Technologies Actually Did

Renaissance's Medallion Fund returned 63.3% annually for 30 years. They were right only 50.75% of the time. Their edge was NOT prediction accuracy. It was:

1. **Signal processing from noise** — treating price data like encrypted radio signals (Jim Simons came from NSA code-breaking)
2. **Massive diversification across thousands of small bets** — no single trade mattered
3. **Execution cost minimization** — being particularly effective at minimizing transaction costs despite enormous volume
4. **Leverage on high-confidence, low-correlation signals** — 12.5x leverage, sometimes 20x, but on positions with negative market beta

### What Citadel/Optiver/Susquehanna Do

These firms don't predict direction. They predict **flow**. They know:
- Where market makers are hedging (dealer gamma exposure)
- Where forced selling will occur (margin calls, index rebalances)
- Where liquidity is thin (and will be exploited)

### What HYDRA Combines

HYDRA takes BOTH approaches:

**From Renaissance:** Statistical signal processing. Every data source becomes a Signal object scored -1 to +1, weighted by historical reliability, time-decayed, and combined using confidence-weighted averaging. We don't predict — we detect regime shifts and apply the right strategy.

**From Citadel:** Mechanical flow analysis. We track CME margin changes, crypto funding rates, liquidation heatmaps, ETF flows, and dealer gamma positioning. These aren't predictions — they're known forced flows that will occur.

**Beyond both:** AI narrative velocity detection and cross-asset signal graphs. The SaaSpocalypse taught us that narrative speed matters as much as fundamentals. We track how fast a story spreads and whether it's converging with macro weakness.

---

## Architecture: How the System Thinks

```
                    ┌─────────────────────┐
                    │   REGIME DETECTOR    │
                    │  (Hidden Markov-like │
                    │   state classifier)  │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  SIGNAL AGGREGATOR   │
                    │  (Confidence-weighted│
                    │   signal combiner)   │
                    └─────────┬───────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
    ┌─────▼─────┐     ┌──────▼──────┐    ┌──────▼──────┐
    │ STRATEGY  │     │  STRATEGY   │    │  STRATEGY   │
    │ MODULE 1  │     │  MODULE 2   │    │  MODULE N   │
    │ (Crypto)  │     │  (Events)   │    │  (Metals)   │
    └─────┬─────┘     └──────┬──────┘    └──────┬──────┘
          │                  │                   │
          └──────────────────┼───────────────────┘
                             │
                    ┌────────▼────────┐
                    │  RISK MANAGER   │
                    │ (Half-Kelly +   │
                    │  Vol Scaling +  │
                    │  Kill Switch)   │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │    EXECUTOR     │
                    │  (Alpaca API)   │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ POSITION MGR    │
                    │ (Stops/Targets/ │
                    │  Trailing)      │
                    └─────────────────┘
```

### The Loop (runs every 60 seconds)

1. **OBSERVE** — Fetch prices for all 19 watched assets from Alpaca
2. **DETECT REGIME** — Is the market trending, mean-reverting, crashing, or recovering?
3. **GENERATE SIGNALS** — Each strategy fetches its external data and produces Signal objects
4. **PROPOSE TRADES** — Active strategies (those compatible with current regime) propose trades
5. **RANK** — Proposals ranked by expected value = confidence × reward:risk × strategy_weight
6. **FILTER** — Risk manager approves sizing, checks limits, enforces kill switch
7. **EXECUTE** — Top proposals sent to Alpaca paper trading
8. **MANAGE** — Open positions monitored for stop/target/trailing stop
9. **ADAPT** — Strategy weights updated based on recent win rates

---

## The 5 Strategy Modules

### Strategy 1: Crypto Liquidation Cascade Hunter
- **Edge:** Forced liquidation mechanics are predictable
- **Data:** Binance funding rates (free API), open interest
- **Logic:** When funding >0.05%, market is overleveraged long → position for downside cascade. When OI drops >5% in 1hr, cascade is in progress → ride the momentum.
- **Assets:** BTC/USD, ETH/USD via Alpaca crypto
- **Regimes:** HIGH_VOL, CRASH, TRENDING
- **Capital:** $200-2,000 per trade

### Strategy 2: Macro Event Scalper
- **Edge:** NFP/CPI/FOMC create predictable volatility spikes
- **Data:** Economic calendar, BLS releases
- **Logic:** Pre-event (1-4 hrs before): prepare for volatility expansion. Post-event (first 15 min candle): trade directionally with the move.
- **Assets:** SPY, TLT, GLD, SLV
- **Regimes:** ALL (events override regime)
- **Critical dates:** Feb 11 (delayed NFP), Feb 13 (CPI)

### Strategy 3: Precious Metals Flow & Margin Trader
- **Edge:** CME margin hikes force liquidation cascades 24-48hr later
- **Data:** CME advisory notices, Shanghai gold premium, gold/silver ratio
- **Logic:** When CME raises margins → buy puts/short. When physical premium recovers → flip long. Gold/silver ratio mean-reversion when z-score exceeds ±1.5σ.
- **Assets:** GLD, SLV, GDX
- **Regimes:** HIGH_VOL, CRASH, RECOVERY, MEAN_REVERTING

### Strategy 4: AI/SaaS Disruption Shock Trader
- **Edge:** AI product launches create predictable panic → overreaction → reversion
- **Data:** GitHub API (Anthropic/OpenAI repos), IGV ETF, analyst notes
- **Logic:** Day 1-2: Short structurally impaired names (LZ). Day 3-10: Buy quality dips (CRM, SHOP, ADBE). The DeepSeek playbook.
- **Assets:** IGV, CRM, SHOP, ADBE, MSFT, WDAY, LZ
- **Regimes:** TRENDING_DOWN, HIGH_VOL, RECOVERY

### Strategy 5: Cross-Asset Regime Signal Graph
- **Edge:** Assets signal each other 6-24 hours in advance
- **Data:** All asset prices, credit spreads (HYG), VIX structure
- **Logic:** Generates signals that amplify/dampen other strategies. Also trades TLT directly when risk-off regime detected.
- **Assets:** SPY, TLT, GLD, BTC/USD, HYG
- **Regimes:** ALL

---

## Risk Management: The Actual Edge

### Position Sizing: Modified Half-Kelly

The Kelly Criterion tells you the optimal bet size: `f* = (bp - q) / b`

We use HALF-Kelly because:
- Full Kelly maximizes long-run growth but has enormous drawdowns
- Half-Kelly gives 75% of the growth rate with 50% of the drawdown
- In practice, our edge estimates are noisy, so half-Kelly is more robust

### Volatility Scaling

Higher volatility = smaller positions. This is counterintuitive but essential:
- In a crash (VIX 30+), each point of movement is worth more in absolute terms
- So you need FEWER shares to achieve the same dollar risk
- The system scales position sizes inversely to realized volatility

### Hard Limits (Cannot Be Overridden)

| Limit | Value | Why |
|-------|-------|-----|
| Max per position | 3% of capital | No single trade can hurt you badly |
| Max daily loss | 5% of capital | Automatic kill switch |
| Max total exposure | 25% of capital | 75% always in cash |
| Max per asset | 5% of capital | Diversification enforced |
| Max consecutive losses | 3 | Forces 4-hour cooldown |
| Max trades per day | 30 | Prevents overtrading |

### Why 75% Cash?

This seems conservative. It's actually the edge. When a crash happens (like this week), you have MASSIVE buying power when everyone else is forced-selling. The system is designed to be most aggressive during peak panic — not during calm markets.

---

## Deployment Guide

### Prerequisites

```bash
pip install alpaca-py requests numpy pandas
```

### Step 1: Get Alpaca Paper Trading Keys

1. Sign up at https://alpaca.markets (free)
2. Go to Paper Trading dashboard
3. Generate API key and secret
4. You get $100,000 in paper money

### Step 2: Set Environment Variables

```bash
export ALPACA_API_KEY="your_paper_key"
export ALPACA_SECRET_KEY="your_paper_secret"
```

### Step 3: Run

```bash
python hydra_engine.py
```

The system starts in **OBSERVATION mode** for the first 20 cycles (~20 minutes) while it builds enough price history to detect the regime. Then it activates trading.

### Step 4: Monitor

Watch the logs. You'll see:
- Regime detection updates every 10 cycles
- Signal generation as external data arrives
- Trade proposals ranked and executed
- Position management (stops, targets, trailing)
- Kill switch activation if daily loss exceeds 5%

### Step 5: Review

After each session, a JSON trade log is saved. Review:
- Win rate per strategy
- Average R:R realized
- Drawdown curve
- Which regimes generated the most profit

---

## What Makes This Cutting-Edge

### vs. Traditional Algo Trading (Moving Average Crossovers, etc.)
Those systems use price data alone. HYDRA uses 12+ data sources including liquidation maps, funding rates, margin changes, physical commodity premiums, and narrative velocity.

### vs. ML-Only Systems (LSTM, Transformer price prediction)
ML models overfit to historical patterns that don't repeat. HYDRA uses ML-inspired signal weighting but relies on MECHANICAL edges (forced liquidations, margin cascades) that are structural, not statistical.

### vs. Single-Asset Bots
HYDRA trades across 5 asset classes simultaneously, using each as both a trade and a signal for other trades. The cross-asset intelligence layer is what Renaissance built — we've made it accessible.

### vs. HFT Systems
We're not competing on speed. Our edge is on INFORMATION SYNTHESIS — combining signals from sources that HFT firms don't use (narrative velocity, CME margin advisories, Shanghai physical premiums) with mechanical flow analysis.

---

## The Evolution Path

### Phase 1 (Current): Paper Trading Proof
Run HYDRA on Alpaca paper for 30+ days. Target: Sharpe ratio > 1.5.

### Phase 2: Add Options Execution
Alpaca now supports Level 3 options. Add actual 0DTE SPX options trading, iron condors, straddles. This multiplies the edge because options provide asymmetric payoffs.

### Phase 3: Add More Data Feeds
- CoinGlass API for full liquidation heatmaps
- SpotGamma for GEX levels
- Unusual Whales for dark pool flow
- FRED API for automated macro calendar
- GitHub webhooks for real-time AI lab release detection

### Phase 4: Reinforcement Learning Meta-Optimizer
Train an RL agent to optimize strategy weights, position sizes, and regime classification thresholds based on realized trading performance. The system that learns which strategies work in which environments — and adapts.

### Phase 5: Multi-Agent Architecture
Deploy multiple HYDRA instances with different risk profiles:
- Conservative (1% max position, 3% daily loss limit)
- Moderate (3% max position, 5% daily loss limit)
- Aggressive (5% max position, 8% daily loss limit)

Compare performance across risk profiles. The system discovers its own optimal aggression level.

---

## Disclaimer

This is a paper trading research system for educational and analytical purposes. It is not financial advice. Trading involves substantial risk of loss. Past performance, including backtested or paper trading results, does not guarantee future returns. Always do your own research and never risk more than you can afford to lose.
