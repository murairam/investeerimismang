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

## Game Constraints (`config.GAME_CONSTRAINTS`, enforced by validator)

| Rule | Value |
|------|-------|
| Stocks | 5–20 |
| Position weight | 5–25% |
| Min total invested | 75% (max 25% cash) |
| Max sector concentration | 35% |
| Regime-based target count | BULL 6-8, NEUTRAL 8-10, BEAR 10-14 |

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
