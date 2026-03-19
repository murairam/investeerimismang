# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AlphaShark** is an autonomous quantitative trading agent for the **Äripäev/SEB Investment Game** (Estonia). It runs daily via GitHub Actions (Mon–Fri 06:30 UTC), fetches live market data, uses a 3-model AI ensemble to build a momentum portfolio, validates it against game rules, and posts the recommendation to Discord.

**Game period:** 6 April – 19 June 2026
**6 markets:** US S&P 500, OMX Helsinki/Stockholm/Copenhagen, OBX Norway, Baltic Main List (~111 tickers total)

## Running Locally

```bash
cp .env.example .env       # fill in API keys
pip install -r requirements.txt
python main.py             # run full pipeline
python scripts/status.py   # view project dashboard
python scripts/verify.py   # confirm portfolio (LIVE mode after submission)
python scripts/pregame_review.py  # refresh pre-game learning summary
```

Required env vars: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DISCORD_WEBHOOK_URL`, optionally `DISCORD_USER_ID`.

No formal test suite — validate changes with `python main.py` and `python scripts/status.py`.

## Architecture

```
yfinance market data
    ↓
data/fetcher.py — 15 signals per stock + macro context (regime score 0-100, VIX, breadth)
    ↓ (parallel)
agents/openai_strategist.py (GPT-4o)      ─┐
agents/gemini_challenger.py (Gemini 2.5)  ─┤→ agents/openai_risk_manager.py (GPT-4o-mini)
                                            │   synthesises both proposals → PortfolioProposal
    ↓
portfolio/validator.py — enforces game constraints, normalises weights
    ↓
data/paper_account.py — virtual P&L rebalancing (PREGAME) / portfolio_history.json
    ↓
Learning loop: PREGAME_LEARNING.md + AI_SELF_CRITIQUE.md → injected into next morning's prompts
    ↓
output/dispatcher.py — Discord webhook embed
```

All pipeline wiring is in `orchestrator.py`. Entry point is `main.py`.

## Key Files

| Path | Purpose |
|------|---------|
| `config.py` | Universe, game constraints, signal params, sector map — all tunable values live here |
| `agents/base_agent.py` | Abstract base; all agents implement `propose(snapshot, prior_proposal)` |
| `data/fetcher.py` | 15 per-stock signals (momentum, Sharpe, RSI, beta, MACD, ATR, vol_ratio, etc.) + macro |
| `data/mode_guard.py` | PREGAME/LIVE switch; LIVE locks strategy params via SHA256 in `live_mode_lock.json` |
| `portfolio/models.py` | `Position`, `PortfolioProposal`, `MarketSnapshot` dataclasses |
| `portfolio/validator.py` | Constraint validation + weight normalisation |

## Game Constraints — Hard Rules (from docs/rules.txt)

These are competition rules that NO code may violate. Enforced by `portfolio/validator.py`.

| Rule | Value |
|------|-------|
| Stocks | 5–20 |
| Position weight | 5–25% (inclusive) |
| Max cash | 25% (must invest ≥75%) |
| Sector concentration | No cap — 100% in one sector is legal |
| Markets | US S&P 500, Baltic, OMX Helsinki, OMX Stockholm, OBX Norway, OMX Copenhagen |
| Execution | Baltic/Nordic orders at 10:00 EET open; US at 16:30 EET open |
| Fees | Zero transaction fees |
| Game period | 6 April – 19 June 2026 (75 trading days) |

Never write portfolio logic that violates these rules. The validator in `portfolio/validator.py`
enforces them — always run validation before committing a portfolio proposal.

## Strategic Mandate — Aggressive Hedge Fund (Updated 2026-03-19)

We are no longer a conservative fund. We are an aggressive, high-beta, catalyst-driven hedge fund
competing in a short-term 10-week game. The objective is to **WIN**, not to preserve capital.

- Prioritize: high-beta breakouts, sector momentum leaders, pre-earnings catalysts
- Concentrate: 5–8 positions maximum. Diversification is for managing money, not winning competitions.
- Current regime (as of March 2026): Energy rotation year. Brent ~$103, energy +25% YTD.
  Tech in correction. Favour XOM, CVX, EQNR.OL, KONG.OL, LLY, DSV.CO.
- Avoid: low-beta telecom, Nordic banks as filler, shipping with SELL consensus (Mærsk)
- Tech stack: yfinance for data, vectorized pandas for math (no TA-Lib or bloated libraries),
  Python 3.10+ type hints throughout, `logging` (not `print`) for all output.

## Memory Loop — Mandatory Reading

Before writing any new trading logic or modifying agent prompts, you MUST:
1. Read `AI_SELF_CRITIQUE.md` — start your first response with a 1-sentence summary of the
   last recorded mistake so we do not repeat it.
2. Read `PREGAME_LEARNING.md` — check the action plan section for active constraints.
3. Read `docs/strategy_principles.md` — the persistent strategic pivot document that survives
   daily auto-generation of `AI_SELF_CRITIQUE.md`.

## Agent Testing Protocol

After modifying any portfolio logic, validator, or agent prompt:
1. Run `python scripts/verify.py --show` to display current portfolio without prompts.
2. Run `python main.py` to execute the full pipeline end-to-end.
3. Check logs for: turnover %, position count, sector weights, held-over %.
4. Confirm no validation errors in the output.
5. Run `python scripts/status.py` to confirm learning report is updated.

Note: `verify.py` in interactive mode requires manual input — use `--show` flag for autonomous checks.

## Game Constraints (`config.GAME_CONSTRAINTS`, enforced by validator)

| Rule | Value |
|------|-------|
| Stocks | 5–20 |
| Position weight | 5–25% |
| Min total invested | 75% (max 25% cash) |
| Sector concentration | No cap |
| Regime-based target count | BULL 5-7, NEUTRAL 6-8, BEAR 8-12 |

## Operational Modes

- **PREGAME (before 2026-04-06):** Writes to `PREGAME_LOG.md`, tracks virtual €10k in `paper_account.json`, generates learning files.
- **LIVE (on/after 2026-04-06):** Writes to `DAILY_LOG.md`. `live_mode_lock.json` SHA256-locks strategy files — do not edit it manually.

## Coding Conventions

- All public functions/methods must have type hints.
- Use `logging` (not `print`) — DEBUG/INFO/WARNING/ERROR levels.
- All tunable params in `config.py` — no magic numbers in agent or data code.
- Domain models are pure `dataclasses` (no business logic inside them).
- Network/API calls must handle timeouts and retries; never crash the pipeline on a single failure.

## Auto-generated Files (do not edit manually)

These are overwritten on each run: `portfolio_history.json`, `paper_account.json`, `cost_log.json`, `verification_tracker.json`, `live_mode_lock.json`, `PREGAME_LOG.md`, `PREGAME_LEARNING.md`, `AI_SELF_CRITIQUE.md`.

## Common Tasks

**Add a stock:** Edit `config.UNIVERSE` (yfinance ticker) and `config.SECTOR_MAP` (sector tag).

**Add a signal:** Compute in `data/fetcher.py`, add to `MarketSnapshot`, update agent prompt templates.

**Add an agent:** Extend `BaseAgent`, implement `propose()`, wire into `orchestrator.py`.

**Change constraints:** Edit `config.GAME_CONSTRAINTS` — validator reads from there automatically.

## GitHub Actions

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `alphashark.yml` | Mon–Fri 06:30 UTC | Full pipeline, auto-commits portfolio + learning files |
| `verification_reminder.yml` | Mon–Fri 07:00 UTC | Discord reminder if portfolio not verified (LIVE only) |
| `evening_review.yml` | Post-market | Optional evening review |

GitHub secrets required: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DISCORD_WEBHOOK_URL`, optionally `DISCORD_USER_ID`.
