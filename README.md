# AlphaShark

An autonomous quantitative trading agent for the **Äripäev/SEB Investment Game** (Estonia). Runs daily via GitHub Actions, fetches live market data, uses a 3-model AI ensemble (GPT-4o + Gemini + GPT-4o-mini) to build a momentum portfolio, validates it against game rules, and posts the result to Discord.

**Game end date: 19 June 2026**

---

## Key Features

- 🤖 **3-Model AI Ensemble**: GPT-4o + Gemini + GPT-4o-mini analyze markets in parallel
- 📊 **Automated Learning**: Tracks win/loss patterns, best tickers, optimal position sizing
- 🧠 **AI Self-Critique**: Evaluates quality of its own reasoning (not just which stocks won)
- 💰 **Cost Tracking**: Monitors OpenAI API spending per run
- ⏰ **Automated Verification Reminders**: Pings you if portfolio sync is missing (LIVE mode)
- 📝 **Paper Trading**: Virtual €10k account for pregame training

**Quick commands:**
```bash
python main.py           # Run full pipeline
python status.py         # View project dashboard (costs, learning, next steps)
python verify.py         # Confirm portfolio sync (LIVE mode)
python pregame_review.py # View learning summary (PREGAME mode)
```

---

## Daily workflow

```
Morning (automated, before 10:00 EET):
  python main.py          ← GitHub Actions runs this
      ↓ posts to Discord with proposed portfolio changes
            ↓ rebalances paper account (virtual €10,000) and tracks learning P&L

You manually update your game portfolio on the website.

Then confirm the system's record matches yours:
  python verify.py        ← run after updating the game
```

### Pre-game training mode (starting now)

Before the game starts (6 April), run `python main.py` daily and use the built-in paper account:

- Starts at **€10,000 virtual capital** on first run
- Rebalances automatically to the latest validated agent portfolio
- Persists holdings/equity in `paper_account.json`
- Appends paper-account performance to `DAILY_LOG.md`
- Includes paper-account equity/performance in Discord output
- Auto-generates `PREGAME_LEARNING.md` with win/loss analysis and action items until 6 April

Run this anytime to refresh and inspect the learning summary:

```bash
python pregame_review.py
```

This gives you a live rehearsal loop: observe suggestions, measure virtual outcomes, and tune the code before real capital/game decisions.

### Automatic mode switch on 6 April

The system now enforces two modes by date:

- **PREGAME (before 2026-04-06):** training/experimentation mode
- **LIVE (on/after 2026-04-06):** strict parameter freeze mode

In LIVE mode, protected strategy files are fingerprint-locked in `live_mode_lock.json`.
If those files change after lock creation, the run fails fast so accidental strategy drift is prevented.

On the first LIVE run, a one-time handoff file is generated automatically:

- `LIVE_HANDOFF_2026-04-06.md`

---

## How it works

```
Market data (yfinance)
    ↓
Rich signal table (momentum, Sharpe, RSI, regime…)
    ↓
GPT-4o (OpenAIStrategist) ──┐  independent proposals
Gemini 2.0 Flash             ├─ (challenger falls back to gpt-4o-mini if quota exceeded)
(GeminiChallenger)          ─┘
    ↓
GPT-4o-mini (OpenAIRiskManager) — meta-analyst, synthesises both proposals
    ↓
PortfolioValidator — enforces game constraints
    ↓
portfolio_history.json — saved for next day's context
    ↓
Discord webhook — daily embed posted
    ↓
DAILY_LOG.md — human-readable daily log appended
```

---

## Signals computed per stock

| Signal | What it means |
|--------|--------------|
| `momentum` | 20-day price return |
| `sharpe_20d` | momentum / annualised vol — the primary ranking signal |
| `mom_5d` | 5-day return (short-term acceleration) |
| `mom_60d` | 60-day return (longer trend confirmation) |
| `rsi_14` | 14-day RSI — stocks above 75 are filtered out (overbought) |
| `vs_index` | stock return minus S&P 500 return — pure alpha |
| `pct_from_52w_high` | proximity to 52-week high — breakout signal |
| `beta` | sensitivity to S&P 500 moves |
| `vol_20d` | annualised 20-day volatility |

**Market regime** (BULL / BEAR / NEUTRAL) is determined by SPX vs its 200-day SMA and injected into each model's system prompt to adjust aggression level.

---

## Game constraints

| Rule | Value |
|------|-------|
| Min stocks | 5 |
| Max stocks | 20 |
| Min position weight | 5% |
| Max position weight | 25% |
| Max total weight | 100% |

---

## Universe

Stocks across 6 markets: **US S&P 500**, **OMX Helsinki** (Finland), **OMX Stockholm 30** (Sweden), **OBX** (Norway), **OMX Copenhagen 25** (Denmark), **Baltic Main List** (Tallinn, Riga, Vilnius).

Top 30 candidates by Sharpe ratio are passed to the models, with:
- Max 15 US candidates
- Max 5 candidates per other market
- Correlated pairs (>0.85 over 60d) deduplicated — keep higher Sharpe

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
   - `GEMINI_API_KEY` (required)
   - `DISCORD_WEBHOOK_URL` (required)
   - `DISCORD_USER_ID` (optional — enables @mentions in LIVE mode)
4. The workflow runs automatically at **09:30 EEST (06:30 UTC)** on weekdays, 90 min before the 10:00 EET submission cutoff
5. After each run, portfolio and learning files are committed back to the repo automatically
6. **In LIVE mode**: 30 minutes later (10:00 EEST), a second workflow checks if you've run `python verify.py`. If not, it sends a Discord reminder.

After the automated run posts to Discord, manually update your positions on the game website, then run `python verify.py` to confirm the baseline matches.

### Required environment variables

```
OPENAI_API_KEY=...         # GPT-4o strategist + GPT-4o-mini meta-analyst
GEMINI_API_KEY=...         # Gemini 2.0 Flash challenger (free tier, 1500 req/day)
DISCORD_WEBHOOK_URL=...    # Discord channel webhook for daily posts
DISCORD_USER_ID=...        # Optional: Discord user ID for @mentions in LIVE mode
```

To get your Discord user ID: Enable Developer Mode in Discord → Right-click your username → Copy User ID

---

## Project structure

```
├── main.py                      # entry point
├── status.py                    # project dashboard (costs, learning, next steps)
├── orchestrator.py              # pipeline wiring (all 3 agents)
├── config.py                    # universe, signal params, game constraints
├── verify.py                    # interactive CLI to confirm/correct daily portfolio
├── pregame_review.py            # refresh/print pre-game learning summary
├── verification_reminder.py     # GitHub Actions job for LIVE mode sync reminders
├── data/
│   ├── fetcher.py               # market data + signal computation
│   ├── portfolio_store.py       # load/save portfolio_history.json
│   ├── paper_account.py         # virtual account state + daily rebalancing
│   ├── learning_report.py       # pre-game win/loss analyzer + markdown report
│   ├── meta_learning.py         # AI self-critique: reasoning quality analysis
│   ├── cost_tracker.py          # OpenAI API spending tracker
│   ├── verification_tracker.py  # tracks when portfolio was last verified
│   ├── mode_guard.py            # pregame/live switch + live parameter freeze
│   └── diary.py                 # append entries to DAILY_LOG.md
├── agents/
│   ├── base_agent.py            # abstract base class
│   ├── openai_strategist.py     # GPT-4o — primary portfolio selection & sizing
│   ├── gemini_challenger.py     # Gemini 2.0 Flash — independent second opinion
│   └── openai_risk_manager.py   # GPT-4o-mini — meta-analyst, synthesises proposals
├── portfolio/
│   ├── models.py                # Position, PortfolioProposal dataclasses
│   └── validator.py             # constraint validation + normalisation
├── output/
│   └── dispatcher.py            # Discord webhook
├── portfolio_history.json       # last accepted portfolio (auto-generated)
├── paper_account.json           # virtual paper account ledger (auto-generated)
├── cost_log.json                # API cost tracking (auto-generated)
├── verification_tracker.json    # portfolio sync tracking (auto-generated)
├── DAILY_LOG.md                 # daily decision + paper P&L log (auto-generated)
├── PREGAME_LEARNING.md          # actionable pre-game learning report (auto-generated)
├── AI_SELF_CRITIQUE.md          # AI reasoning quality analysis (auto-generated)
├── live_mode_lock.json          # live-mode strategy lock fingerprints (auto-generated)
└── LIVE_HANDOFF_2026-04-06.md   # final pregame handoff when live mode starts
```

---

## Daily diary

After each run, `DAILY_LOG.md` is automatically updated with a human-readable entry: what was held, what changed, why, and the market regime at the time. See [DAILY_LOG.md](DAILY_LOG.md) for the full history.
