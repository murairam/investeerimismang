# AlphaShark

An autonomous quantitative trading agent for the **Äripäev/SEB Investment Game** (Estonia). Runs daily via GitHub Actions, fetches live market data, uses GPT-4o to build a momentum portfolio, validates it against game rules, and posts the result to Discord.

**Game end date: 19 June 2026**

---

## Daily workflow

```
Morning (automated, before 10:00 EET):
  python main.py          ← GitHub Actions runs this
      ↓ posts to Discord with proposed portfolio changes

You manually update your game portfolio on the website.

Then confirm the system's record matches yours:
  python verify.py        ← run after updating the game
```

---

## How it works

```
Market data (yfinance)
    ↓
Rich signal table (momentum, Sharpe, RSI, regime…)
    ↓
GPT-4o (OpenAIStrategist) — portfolio selection & sizing
    ↓
GPT-4o-mini (OpenAIRiskManager) — risk review pass
    ↓
PortfolioValidator — enforces game constraints
    ↓
portfolio_history.json — saved for next day's context
    ↓
Discord webhook — daily embed posted
    ↓
DIARY.md — human-readable daily log appended
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

**Market regime** (BULL / BEAR / NEUTRAL) is determined by SPX vs its 200-day SMA and injected into Claude's system prompt to adjust aggression level.

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

Top 30 candidates by Sharpe ratio are passed to Claude, with:
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

### Required environment variables

```
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
DISCORD_WEBHOOK_URL=...
```

---

## Project structure

```
├── main.py                    # entry point
├── orchestrator.py            # pipeline wiring
├── config.py                  # universe, signal params, game constraints
├── data/
│   ├── fetcher.py             # market data + signal computation
│   └── portfolio_store.py     # load/save portfolio_history.json
├── agents/
│   ├── anthropic_strategist.py  # Claude — portfolio generation
│   └── openai_risk_manager.py   # OpenAI — risk review (Phase 2)
├── portfolio/
│   ├── models.py              # Position, PortfolioProposal dataclasses
│   └── validator.py           # constraint validation + normalisation
├── output/
│   └── dispatcher.py          # Discord webhook
├── portfolio_history.json     # last accepted portfolio (auto-generated)
└── DAILY_LOG.md               # daily decision log (auto-generated)
```

---

## Daily diary

After each run, `DAILY_LOG.md` is automatically updated with a human-readable entry: what was held, what changed, why, and the market regime at the time. See [DAILY_LOG.md](DAILY_LOG.md) for the full history.
