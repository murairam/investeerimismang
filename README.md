# AlphaShark

An autonomous quantitative trading agent for the **Äripäev/SEB Investment Game** (Estonia). It runs daily via GitHub Actions, fetches live market data, scores the full trading universe, runs an all-OpenAI multi-agent pipeline, validates the final portfolio against game rules, and posts the result to Discord.

**Game period: 6 April – 19 June 2026**

---

## Key Features

- **All-OpenAI decision stack**: GPT-5.4 Strategist + GPT-5.4 Challenger run in parallel, GPT-5.4-nano Devil's Advocate pressure-tests the picks, and GPT-5.4 Risk Manager synthesizes the final portfolio
- **Full-universe candidate set**: agents see the current filtered universe instead of a tiny shortlist capped per market
- **Rich signal snapshot**: momentum, Sharpe, RSI, beta, volume confirmation, MACD, ATR, dividend yield, regime data, and catalyst overlays
- **Parallel enrichment layer**: news, earnings, insider buying, and Google Trends are fetched concurrently and injected into prompts
- **Structured learning loop**: `portfolio_history.json` stores the canonical daily record, `learning_state.json` drives prompt injection, and `PREGAME_LEARNING.md` / `AI_SELF_CRITIQUE.md` are derived human summaries
- **Verification and audit trail**: whole-percent portfolio rounding, manual verification tooling, and devil's-advocate impact logging
- **Historical shadow trader**: strict no-lookahead backtest script for open-to-open portfolio simulation over prior periods

**Quick commands:**
```bash
python main.py                   # Run full pipeline
python scripts/status.py         # View project dashboard (costs, learning, next steps)
python scripts/verify.py         # Confirm portfolio sync (LIVE mode)
python scripts/pregame_review.py # View learning summary (PREGAME mode)
python scripts/historical_shadow_trader.py --start 2024-04-01 --end 2024-06-21
```

---

## Daily workflow

```
08:00 CEST (Paris) / 09:00 EEST (Tallinn) during the game period — GitHub Actions fires at 06:00 UTC:
  python main.py
      ↓ fetches market data + signals
      ↓ enriches with news, earnings, insider, and trends context
      ↓ runs strategist + challenger in parallel
      ↓ runs devil's advocate against the top combined picks
      ↓ synthesises, validates, and rounds the final portfolio
      ↓ posts Discord embed with proposed portfolio
      ↓ updates paper account and learning files

You check Discord and manually update your game portfolio before:
  09:00 CEST / 10:00 EEST during summer time
  08:00 CET / 09:00 EET before the DST switch
  practical rule: submit before the game's 10:00 local cutoff

Then confirm the system's record matches yours:
  python scripts/verify.py

`verify.py` is the truth-after-submission step: it confirms or corrects the day's canonical record and marks it as verified.
```

### Pre-game training mode (until 6 April)

The bot runs daily in **PREGAME** mode — all decisions are recorded but don't count toward the real game:

- Writes to `PREGAME_LOG.md` (separate from the real game log)
- Tracks virtual P&L against the paper account
- Generates `learning_state.json` (machine-usable rules, winners/losers, decision-quality metrics)
- Generates `PREGAME_LEARNING.md` and `AI_SELF_CRITIQUE.md` as human-readable summaries of that structured state
- Prompt injection prefers `learning_state.json`; markdown reports are derived outputs and fallbacks

### Automatic mode switch on 6 April

- **PREGAME (before 2026-04-06):** training mode, writes to `PREGAME_LOG.md`
- **LIVE (on/after 2026-04-06):** real game mode, writes to `DAILY_LOG.md`, paper account resets to €10,000, strategy files are SHA256-locked to prevent accidental drift

---

## How it works

```
Market data (yfinance, free)
    ↓
signal computation + catalyst overlays
    ↓
news + earnings + insider buys + Google Trends
    ↓
GPT-5.4 Strategist ───────────────────┐  run in parallel
GPT-5.4 Challenger ───────────────────┤
                                       ↓
GPT-5.4-nano Devil's Advocate — generates bear cases for top combined picks
                                       ↓
GPT-5.4 Risk Manager — synthesises consensus picks, unique picks, and bear cases
    ↓
PortfolioValidator — validates, normalises if needed, and rounds to whole %
    ↓
portfolio_history.json — canonical daily proposal/verification state plus structured history and outcomes
    ↓
Discord webhook — daily embed posted
    ↓
PREGAME_LOG.md / DAILY_LOG.md — human-readable entry appended
```

### The learning loop

```
Run → update structured daily history → generate learning_state.json
  ↓                                             ↓
derived markdown reports                  prompt-ready learning context
```

---

## Current portfolio construction strategy

- **High-conviction concentration**: the system aims to stay concentrated, usually around 5-8 names depending on regime, risk-manager synthesis, and validator normalization
- **Unequal sizing by conviction**: the prompts explicitly push top-heavy sizing instead of equal weight, typically with a 25/25/25/20/5 shape in stronger regimes
- **Consensus first, catalysts second**: the Risk Manager prefers names selected by both Strategist and Challenger, then fills remaining slots with the best unique catalyst picks
- **Devil's-advocate check**: top combined picks are pressure-tested before final sizing so obvious dead-money or asymmetric-risk names can be cut or downweighted
  - **Devil accuracy feedback loop**: when Devil's accuracy at flagging true underperformers exceeds 60%, the Risk Manager applies a 10% hard cap on HIGH-flagged positions (tracked in `learning_state.json`)
- **Overbought weight cap**: positions with RSI > 82 AND within 2% of 52w high are capped at 15% unless volume_ratio > 1.8 (exception for strong volume breakouts)
- **No sector cap**: sector concentration is intentionally allowed if one theme has the strongest momentum
- **Cross-market awareness**: the agents are steered away from cloning a pure US mega-cap portfolio and are encouraged to use Nordic/Baltic names when signal quality justifies it
- **High RSI is not an auto-reject**: strong RSI plus volume confirmation is treated as a breakout clue, not a blanket overbought filter (but see overbought weight cap rule above)

---

## Signals computed per candidate

| Signal | What it means |
|--------|---------------|
| `momentum` | 20-day price return — primary momentum signal |
| `sharpe_20d` | momentum / annualised vol — primary ranking signal |
| `mom_5d` | 5-day return (short-term acceleration) |
| `mom_60d` | 60-day return (longer trend confirmation) |
| `rsi_14` | 14-day RSI — used as a breakout / exhaustion context signal, not a hard exclusion filter |
| `vs_index` | stock return minus S&P 500 return — pure alpha signal |
| `pct_from_52w_high` | proximity to 52-week high — breakout signal |
| `beta` | sensitivity to S&P 500 moves |
| `vol_ratio` | today's volume / 20d avg volume — high-volume confirmation (>1.5 = strong) |
| `macd_hist` | MACD histogram normalised by price — trend acceleration signal |
| `atr_pct` | 14-day ATR as % of price — daily expected move, used for position sizing |
| `dividend_yield` | trailing 12-month dividend yield — relevant because the game auto-reinvests dividends |
| `sector` | abbreviated sector tag (Tech, Health, Fin, Energy, Ind, Mat, Tel, Util, Cons) |

---

## Extra context injected into prompts

| Signal | Source | What it tells the AI |
|--------|--------|----------------------|
| SPX vs 200d SMA | yfinance | Broad market trend |
| VIX level | yfinance `^VIX` | Current fear level |
| VIX term structure | yfinance `^VIX3M / ^VIX` | >1 = calm, <0.9 = fear spike |
| Market breadth | computed from universe | % of stocks above 50d SMA |
| Credit spread change | yfinance `HYG / LQD` 20d | Risk-on/off signal ahead of VIX |
| **Composite regime score** | all 4 signals above | **0–100: 0–30 defensive, 31–49 cautious, 50–69 neutral, 70+ bullish** |
| Earnings warnings | yfinance calendar | Flags stocks reporting within 7 days |
| News headlines | yfinance news | Recent headlines for top candidate stocks |
| Insider buying | SEC EDGAR Form 4 | Recent open-market insider purchases over $50k for US tickers |
| Search interest | Google Trends via `pytrends` | Flags crowded retail trades vs under-the-radar names |
| Short interest | yfinance | Challenger-only catalyst signal for squeeze setups |
| Premarket gap | yfinance intraday/daily data | Challenger-only catalyst confirmation |
| IV proxy | yfinance options / info | Challenger-only event-volatility signal |
| Learning state | learning_state.json | Structured rules, winners/losers, decision-quality metrics |
| Learning report | PREGAME_LEARNING.md | Human-readable training summary |
| AI self-critique | AI_SELF_CRITIQUE.md | Human-readable reasoning audit |

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

Stocks across 6 markets: **US S&P 500**, **OMX Helsinki Large Cap** (Finland), **OMX Stockholm 30** (Sweden), **OBX** (Norway), **OMX Copenhagen 25** (Denmark), **Baltic Main List** (Tallinn, Riga, Vilnius), minus any tickers explicitly excluded because they are not selectable in the game UI.

Candidate selection currently works like this:
- Start from the current game-sized universe, roughly 630 selectable names
- Use Yahoo as the primary price source, with EODHD fallback for a small provider-override set of Nordic/Baltic edge cases
- Maintain a symbol master / alias layer so game tickers, Yahoo symbols, and fallback-provider symbols can differ safely
- Rank candidates with the composite `selection_score` plus catalyst overlays and regime context
- Top `TOP_N_CANDIDATES` are passed downstream after filtering and scoring

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
   - `DISCORD_WEBHOOK_URL` (required)
   - `DISCORD_USER_ID` (optional — enables @mentions in LIVE mode)
4. The main workflow fires at **06:00 UTC** on weekdays:
   - During the game's summer-time window: **08:00 CEST** (Paris) / **09:00 EEST** (Tallinn)
   - This is designed to leave roughly one hour before the 10:00 local submission cutoff
5. After each run, portfolio and learning files are committed back to the repo automatically
6. **In LIVE mode**: a second workflow fires at 07:00 UTC (09:00 CEST / 10:00 EEST) and sends a Discord reminder if `verify.py` hasn't been run

### Required environment variables

```
OPENAI_API_KEY=...         # all decision agents use OpenAI
DISCORD_WEBHOOK_URL=...    # Discord channel webhook for daily posts
DISCORD_USER_ID=...        # optional: Discord user ID for @mentions in LIVE mode
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
│   ├── evening_review.py        # end-of-day Discord performance review
│   ├── historical_shadow_trader.py # no-lookahead historical simulator / backtest
│   └── verification_reminder.py # GitHub Actions job for LIVE mode sync reminders
├── docs/
│   └── rules.txt                # official game rules reference
├── data/
│   ├── fetcher.py               # market data, regime data, catalyst signals, candidate ranking
│   ├── earnings_fetcher.py      # upcoming earnings calendar (7-day risk warnings)
│   ├── news_fetcher.py          # recent headlines for top candidates (yfinance)
│   ├── insider_fetcher.py       # SEC EDGAR insider-buying enrichment for US stocks
│   ├── trends_fetcher.py        # Google Trends crowding / under-the-radar signal
│   ├── portfolio_store.py       # canonical daily portfolio state + structured history
│   ├── paper_account.py         # virtual account state + daily rebalancing
│   ├── learning_report.py       # pre-game win/loss analyser + markdown report
│   ├── learning_state.py        # structured learning rules + prompt-ready state
│   ├── learning_context.py      # prompt context builder (structured state first, markdown fallback second)
│   ├── meta_learning.py         # AI self-critique: reasoning quality analysis
│   ├── symbol_master.py         # symbol mapping metadata across game/Yahoo/fallback providers
│   ├── yahoo_symbols.py         # aliasing, quarantine, and EODHD-assisted lookup budget handling
│   ├── cost_tracker.py          # OpenAI API spending tracker
│   ├── verification_tracker.py  # tracks when portfolio was last verified
│   ├── mode_guard.py            # pregame/live switch + live parameter freeze
│   └── diary.py                 # appends entries to PREGAME_LOG.md or DAILY_LOG.md
├── agents/
│   ├── base_agent.py            # abstract base class
│   ├── openai_strategist.py     # GPT-5.4 — momentum-driven portfolio selection
│   ├── openai_challenger.py     # GPT-5.4 — catalyst-hunter second opinion
│   ├── openai_devil.py          # GPT-5.4-nano — bear-case stress test for top picks
│   └── openai_risk_manager.py   # GPT-5.4 — synthesises both proposals into final portfolio
├── portfolio/
│   ├── models.py                # Position, PortfolioProposal dataclasses
│   └── validator.py             # constraint validation + normalisation
├── output/
│   └── dispatcher.py            # Discord webhook formatter + sender
├── portfolio_history.json       # canonical daily record + structured decision history (auto-generated)
├── paper_account.json           # virtual paper account ledger (auto-generated)
├── cost_log.json                # API cost tracking (auto-generated)
├── verification_tracker.json    # portfolio sync tracking (auto-generated)
├── learning_state.json          # structured machine-usable learning state (auto-generated)
├── DAILY_LOG.md                 # canonical live-game log — one entry per date
├── PREGAME_LOG.md               # canonical pregame log — one entry per date
├── PREGAME_RUNS.md              # optional debug log of every pregame rerun
├── PREGAME_LEARNING.md          # latest structured training summary (auto-generated)
├── AI_SELF_CRITIQUE.md          # latest structured reasoning audit (auto-generated)
├── LIVE_HANDOFF_2026-04-06.md   # one-time pregame-to-live transition summary
└── live_mode_lock.json          # strategy file fingerprints for LIVE mode (auto-generated)
```
