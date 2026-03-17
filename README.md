# AlphaShark

An autonomous quantitative trading agent for the **Äripäev/SEB Investment Game** (Estonia). Runs daily via GitHub Actions, fetches live market data, uses a 3-model AI ensemble (GPT-4o + Gemini 2.5 Flash + GPT-4o-mini) to build a momentum portfolio, validates it against game rules, and posts the result to Discord.

**Game period: 6 April – 19 June 2026**

---

## Key Features

- **3-Model AI Ensemble**: GPT-4o (Strategist) + Gemini 2.5 Flash (Challenger) + GPT-4o-mini (Risk Manager) analyse markets in parallel
- **Rich Signal Table**: 15 signals per stock including MACD, ATR, sector tag, volume confirmation, and more
- **Composite Regime Score**: 0–100 score combining 4 independent macro signals instead of a binary BULL/BEAR label
- **Automated Learning Loop**: AI reads its own prior critique every morning and adapts
- **News Headlines**: Top candidate stocks' recent headlines injected into agent prompts daily
- **Earnings Calendar**: Flags stocks reporting within 7 days as binary risk warnings
- **Paper Trading**: Virtual €10k account tracks pre-game performance; resets to real €10k on April 6

**Quick commands:**
```bash
python main.py                   # Run full pipeline
python scripts/status.py         # View project dashboard (costs, learning, next steps)
python scripts/verify.py         # Confirm portfolio sync (LIVE mode)
python scripts/pregame_review.py # View learning summary (PREGAME mode)
```

---

## Daily workflow

```
09:32 CEST (Paris) / 10:32 EEST (Tallinn) — GitHub Actions fires at 06:30 UTC:
  python main.py
      ↓ fetches market data + signals
      ↓ runs 3 AI agents in parallel
      ↓ posts Discord embed with proposed portfolio
      ↓ updates paper account and learning files

You check Discord and manually update your game portfolio before:
  09:00 CEST (Paris) = 10:00 EEST (Tallinn) ← submission cutoff

Then confirm the system's record matches yours:
  python scripts/verify.py
```

### Pre-game training mode (until 6 April)

The bot runs daily in **PREGAME** mode — all decisions are recorded but don't count toward the real game:

- Writes to `PREGAME_LOG.md` (separate from the real game log)
- Tracks virtual P&L against the paper account
- Generates `PREGAME_LEARNING.md` (win/loss stats, best tickers, action plan)
- Generates `AI_SELF_CRITIQUE.md` (AI critiques its own reasoning quality)
- Both learning files are injected into the next morning's agent prompts so the AI adapts

### Automatic mode switch on 6 April

- **PREGAME (before 2026-04-06):** training mode, writes to `PREGAME_LOG.md`
- **LIVE (on/after 2026-04-06):** real game mode, writes to `DAILY_LOG.md`, paper account resets to €10,000, strategy files are SHA256-locked to prevent accidental drift

---

## How it works

```
Market data (yfinance, free)
    ↓
15 signals per stock + macro context
    ↓
GPT-4o (Strategist) ──────────────────┐  run in parallel
Gemini 2.5 Flash (Challenger) ────────┤  (Gemini falls back to gpt-4o-mini if unavailable)
                                       ↓
GPT-4o-mini (Risk Manager) — synthesises both proposals, weights consensus picks higher
    ↓
PortfolioValidator — enforces game constraints, cash floor (min 75% invested)
    ↓
portfolio_history.json — saved for next day's context and P&L calculation
    ↓
Discord webhook — daily embed posted
    ↓
PREGAME_LOG.md / DAILY_LOG.md — human-readable entry appended
```

### The learning loop

```
Run → measure P&L → update PREGAME_LEARNING.md → AI self-critique → AI_SELF_CRITIQUE.md
  ↑                                                                          ↓
  └────────────────── both files injected into next morning's prompts ───────┘
```

---

## Signals computed per stock

| Signal | What it means |
|--------|---------------|
| `momentum` | 20-day price return — primary momentum signal |
| `sharpe_20d` | momentum / annualised vol — primary ranking signal |
| `mom_5d` | 5-day return (short-term acceleration) |
| `mom_60d` | 60-day return (longer trend confirmation) |
| `rsi_14` | 14-day RSI — stocks above 75 filtered out (overbought) |
| `vs_index` | stock return minus S&P 500 return — pure alpha signal |
| `pct_from_52w_high` | proximity to 52-week high — breakout signal |
| `beta` | sensitivity to S&P 500 moves |
| `vol_ratio` | today's volume / 20d avg volume — high-volume confirmation (>1.5 = strong) |
| `macd_hist` | MACD histogram normalised by price — trend acceleration signal |
| `atr_pct` | 14-day ATR as % of price — daily expected move, used for position sizing |
| `sector` | abbreviated sector tag (Tech, Health, Fin, Energy, Ind, Mat, Tel, Util, Cons) |

---

## Macro context injected into every agent prompt

| Signal | Source | What it tells the AI |
|--------|--------|----------------------|
| SPX vs 200d SMA | yfinance | Broad market trend |
| VIX level | yfinance `^VIX` | Current fear level |
| VIX term structure | yfinance `^VIX3M / ^VIX` | >1 = calm, <0.9 = fear spike |
| Market breadth | computed from universe | % of stocks above 50d SMA |
| Credit spread change | yfinance `HYG / LQD` 20d | Risk-on/off signal ahead of VIX |
| **Composite regime score** | all 4 signals above | **0–100: 0–30 defensive, 31–49 cautious, 50–69 neutral, 70+ bullish** |
| Earnings warnings | yfinance calendar | Flags stocks reporting within 7 days |
| News headlines | yfinance news | Recent headlines for top 20 candidates |
| Learning context | PREGAME_LEARNING.md | What worked / didn't in prior runs |
| AI self-critique | AI_SELF_CRITIQUE.md | Detected biases and reasoning flaws |

---

## Game constraints

| Rule | Value |
|------|-------|
| Min stocks | 5 |
| Max stocks | 20 |
| Min position weight | 5% |
| Max position weight | 25% |
| Max total weight | 100% |
| Min total weight | 75% (max 25% cash — cash earns no return) |

---

## Universe

Stocks across 6 markets: **US S&P 500**, **OMX Helsinki** (Finland), **OMX Stockholm 30** (Sweden), **OBX** (Norway), **OMX Copenhagen 25** (Denmark), **Baltic Main List** (Tallinn, Riga, Vilnius).

Top 30 candidates by Sharpe ratio are passed to the models, with:
- Max 15 US candidates
- Max 5 candidates per other market
- Correlated pairs (>0.85 over 60d) deduplicated — keep higher Sharpe
- Overbought stocks (RSI > 75) filtered out

---

## Setup

```bash
cp .env.example .env   # fill in your API keys
pip install -r requirements.txt
python main.py
```

### GitHub Actions (automated daily runs)

1. Push the repo to GitHub
2. Go to **Settings → Secrets and variables → Actions**
3. Add these repository secrets:
   - `OPENAI_API_KEY` (required)
   - `GEMINI_API_KEY` (required — free tier, 1500 req/day)
   - `DISCORD_WEBHOOK_URL` (required)
   - `DISCORD_USER_ID` (optional — enables @mentions in LIVE mode)
4. The workflow fires at **06:30 UTC** on weekdays:
   - **08:32 CEST** (Paris) / **09:32 EEST** (Tallinn) — Discord notification arrives
   - **09:00 CEST** / **10:00 EEST** — game portal submission cutoff (~28 min window)
5. After each run, portfolio and learning files are committed back to the repo automatically
6. **In LIVE mode**: a second workflow fires at 07:00 UTC (09:00 CEST / 10:00 EEST) and sends a Discord reminder if `verify.py` hasn't been run

### Required environment variables

```
OPENAI_API_KEY=...         # GPT-4o strategist + GPT-4o-mini meta-analyst
GEMINI_API_KEY=...         # Gemini 2.5 Flash challenger (free tier)
DISCORD_WEBHOOK_URL=...    # Discord channel webhook for daily posts
DISCORD_USER_ID=...        # Optional: Discord user ID for @mentions in LIVE mode
```

---

## Project structure

```
├── main.py                      # entry point
├── orchestrator.py              # full pipeline wiring
├── config.py                    # universe, signal params, game constraints, sector map
├── scripts/
│   ├── status.py                # project dashboard (costs, learning, next steps)
│   ├── verify.py                # interactive CLI to confirm/correct daily portfolio
│   ├── pregame_review.py        # refresh/print pre-game learning summary
│   └── verification_reminder.py # GitHub Actions job for LIVE mode sync reminders
├── docs/
│   └── rules.txt                # official game rules reference
├── data/
│   ├── fetcher.py               # market data + 12 signal computations + macro context
│   ├── earnings_fetcher.py      # upcoming earnings calendar (7-day risk warnings)
│   ├── news_fetcher.py          # recent headlines for top candidates (yfinance)
│   ├── portfolio_store.py       # load/save portfolio_history.json
│   ├── paper_account.py         # virtual account state + daily rebalancing
│   ├── learning_report.py       # pre-game win/loss analyser + markdown report
│   ├── learning_context.py      # reads PREGAME_LEARNING.md + AI_SELF_CRITIQUE.md for prompt injection
│   ├── meta_learning.py         # AI self-critique: reasoning quality analysis
│   ├── cost_tracker.py          # OpenAI API spending tracker
│   ├── verification_tracker.py  # tracks when portfolio was last verified
│   ├── mode_guard.py            # pregame/live switch + live parameter freeze
│   └── diary.py                 # appends entries to PREGAME_LOG.md or DAILY_LOG.md
├── agents/
│   ├── base_agent.py            # abstract base class
│   ├── openai_strategist.py     # GPT-4o — momentum-driven portfolio selection
│   ├── gemini_challenger.py     # Gemini 2.5 Flash — contrarian second opinion
│   └── openai_risk_manager.py   # GPT-4o-mini — synthesises both proposals
├── portfolio/
│   ├── models.py                # Position, PortfolioProposal dataclasses
│   └── validator.py             # constraint validation + normalisation
├── output/
│   └── dispatcher.py            # Discord webhook formatter + sender
├── portfolio_history.json       # last accepted portfolio (auto-generated)
├── paper_account.json           # virtual paper account ledger (auto-generated)
├── cost_log.json                # API cost tracking (auto-generated)
├── verification_tracker.json    # portfolio sync tracking (auto-generated)
├── DAILY_LOG.md                 # real game log — entries from 6 April onwards
├── PREGAME_LOG.md               # training log — pre-game runs (auto-generated)
├── PREGAME_LEARNING.md          # performance learning report (auto-generated)
├── AI_SELF_CRITIQUE.md          # AI reasoning quality analysis (auto-generated)
└── live_mode_lock.json          # strategy file fingerprints for LIVE mode (auto-generated)
```
