# Copilot Instructions for AlphaShark

## Project Overview

**AlphaShark** is an autonomous quantitative trading agent for the **Äripäev/SEB Investment Game** (Estonia). It runs daily via GitHub Actions, fetches live market data, uses a 4-model AI ensemble (GPT-5.4 Strategist + Gemini 2.5 Flash Challenger + GPT-5.4-nano Devil + GPT-5.4 Risk Manager) to build a momentum portfolio, validates it against game rules, and posts the daily recommendation to Discord.

**Game period:** 6 April – 19 June 2026  
**Daily execution:** GitHub Actions fires at 06:30 UTC on weekdays (Mon–Fri)

---

## Technology Stack

- **Language:** Python 3.12
- **AI models:** OpenAI GPT-5.4 (Strategist, Risk Manager) + Gemini 2.5 Flash (Challenger, with Groq Llama 3.3 70B fallback) + OpenRouter Qwen3-32B (Devil, Full Analyst)
- **Market data:** `yfinance` (free, no API key required)
- **Libraries:** `pandas`, `numpy`, `openai`, `google-genai`, `anthropic`, `requests`, `python-dotenv`, `pytrends`
- **Automation:** GitHub Actions (`.github/workflows/`)
- **Notifications:** Discord webhooks

---

## Architecture

```
Market data (yfinance)
    ↓
data/fetcher.py — 15 signals per stock + macro context (regime score, VIX, breadth)
    ↓
GPT-5.4 Strategist ──────────────────────────────────────────┐  (run in parallel)
Gemini 2.5 Flash Challenger ─────────────────────────────────┤
GPT-5.4-nano FullAnalyst ────────────────────────────────────┘
                                                              ↓
              [Cross-agent debate — lightweight second pass per agent]
                                                              ↓
GPT-5.4-nano Devil — bear-case stress test for top picks
                                                              ↓
GPT-5.4 Risk Manager — synthesises all proposals + debate summary + bear cases
    ↓
portfolio/validator.py — enforces game constraints, cash floor (min 75% invested)
    ↓
portfolio_history.json — saved for next day's context and P&L calculation
    ↓
output/dispatcher.py — Discord webhook, daily embed posted
    ↓
PREGAME_LOG.md / DAILY_LOG.md — human-readable entry appended
```

### Key directories and files

| Path | Purpose |
|------|---------|
| `main.py` | Entry point |
| `orchestrator.py` | Full pipeline wiring |
| `config.py` | Universe, signal params, game constraints, sector map |
| `agents/base_agent.py` | Abstract base class all LLM agents must implement |
| `agents/openai_strategist.py` | GPT-5.4 momentum-driven portfolio selection |
| `agents/gemini_challenger.py` | Gemini 2.5 Flash catalyst-hunter second opinion |
| `agents/openai_challenger.py` | GPT-5.4-nano full analyst third proposal (all signals) |
| `agents/openai_devil.py` | GPT-5.4-nano bear-case stress tester |
| `agents/openai_risk_manager.py` | GPT-5.4 that synthesises all proposals + debate + bear cases |
| `data/fetcher.py` | Market data + 15 signal computations + macro context |
| `data/earnings_fetcher.py` | Upcoming earnings calendar (7-day risk warnings) |
| `data/news_fetcher.py` | Recent headlines for top candidates |
| `data/learning_context.py` | Reads `PREGAME_LEARNING.md` + `AI_SELF_CRITIQUE.md` for prompt injection |
| `data/meta_learning.py` | AI self-critique: reasoning quality analysis |
| `data/mode_guard.py` | PREGAME/LIVE switch + live parameter freeze |
| `portfolio/models.py` | `Position` and `PortfolioProposal` dataclasses |
| `portfolio/validator.py` | Constraint validation + normalisation |
| `output/dispatcher.py` | Discord webhook formatter + sender |
| `scripts/status.py` | Project dashboard (costs, learning, next steps) |
| `scripts/verify.py` | Interactive CLI to confirm/correct daily portfolio |

---

## Game Constraints (enforced in `portfolio/validator.py`)

| Rule | Value |
|------|-------|
| Min stocks | 5 |
| Max stocks | 20 |
| Min position weight | 5% |
| Max position weight | 25% |
| Max total weight | 100% |
| Min total weight | 75% (max 25% cash) |

These values live in `config.GAME_CONSTRAINTS` and must not be changed without updating the validator.

---

## Running the Project Locally

```bash
cp .env.example .env       # fill in API keys
pip install -r requirements.txt
python main.py             # run full pipeline
python scripts/status.py   # view dashboard
python scripts/verify.py   # confirm portfolio (LIVE mode)
```

### Required environment variables (see `.env.example`)

```
OPENAI_API_KEY=...          # GPT-5.4 Strategist + Risk Manager
GEMINI_API_KEY=...          # Gemini 2.5 Flash Challenger
GROQ_API_KEY=...            # Groq Llama 3.3 70B — Gemini fallback (free tier, optional)
OPENROUTER_API_KEY=...      # Qwen3-32B for Devil + Full Analyst (optional, falls back to GPT-5.4-nano)
EODHD_API_KEY=...           # Nordic/Baltic ticker fallback
DISCORD_WEBHOOK_URL=...     # Discord channel webhook
DISCORD_USER_ID=...         # Optional: enables @mentions in LIVE mode
```

---

## Coding Conventions

- **Style:** Standard Python 3.12 conventions; use type hints throughout (all public functions and methods must have type annotations).
- **Docstrings:** Module-level and class-level docstrings use triple double-quotes. Function docstrings describe args and return values.
- **Logging:** Use Python's built-in `logging` module (not `print`) for runtime messages. Log levels: `DEBUG` for verbose diagnostics, `INFO` for normal pipeline progress, `WARNING` for degraded-but-recoverable states, `ERROR` for failures.
- **Configuration:** All tunable parameters (signal windows, thresholds, universe lists) live in `config.py`. Do not hard-code magic numbers inside agent or data code.
- **Dataclasses:** Domain models (`Position`, `PortfolioProposal`, `MarketSnapshot`) use Python `dataclasses`. Keep them pure data containers — no business logic.
- **Agent interface:** Every LLM agent must extend `agents/base_agent.py::BaseAgent` and implement `propose(snapshot, prior_proposal)`.
- **Error handling:** Network and API calls must handle timeouts and retries gracefully; never crash the pipeline on a single data-fetch failure.
- **No tests directory:** There is no formal test framework. Validate changes manually with `python main.py` and `python scripts/status.py`.
- **Secrets:** Never commit real credentials. All API keys must be loaded from environment variables via `python-dotenv`.

---

## Operational Modes

The system has two modes controlled by `data/mode_guard.py`:

- **PREGAME (before 2026-04-06):** Training mode. Writes to `PREGAME_LOG.md`, tracks virtual P&L against `paper_account.json`.
- **LIVE (on/after 2026-04-06):** Real game mode. Writes to `DAILY_LOG.md`. Strategy parameters are SHA256-locked via `live_mode_lock.json` to prevent accidental drift.

**Do not modify `live_mode_lock.json` manually in LIVE mode** — this will break the integrity check.

---

## The Learning Loop

```
Run → measure P&L → update PREGAME_LEARNING.md → AI self-critique → AI_SELF_CRITIQUE.md
  ↑                                                                          ↓
  └────────────────── both files injected into next morning's prompts ───────┘
```

`PREGAME_LEARNING.md` and `AI_SELF_CRITIQUE.md` are auto-generated. Do not edit them manually — they will be overwritten on the next run.

---

## Auto-generated Files (do not edit manually)

- `portfolio_history.json` — last accepted portfolio
- `paper_account.json` — virtual paper account ledger
- `cost_log.json` — API cost tracking
- `verification_tracker.json` — portfolio sync tracking
- `live_mode_lock.json` — strategy file fingerprints for LIVE mode
- `PREGAME_LOG.md` — pre-game training log
- `PREGAME_LEARNING.md` — performance learning report
- `AI_SELF_CRITIQUE.md` — AI reasoning quality analysis

---

## GitHub Actions Workflows

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `alphashark.yml` | Mon–Fri 06:30 UTC | Run full pipeline, commit portfolio + learning files back to repo |
| `verification_reminder.yml` | Mon–Fri 07:00 UTC | Send Discord reminder if portfolio hasn't been verified (LIVE mode only) |

Required GitHub repository secrets: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DISCORD_WEBHOOK_URL`. Optional: `DISCORD_USER_ID`.

---

## Common Tasks

**Add a new stock to the universe:**  
Edit `config.UNIVERSE` (add the yfinance ticker to the appropriate market list) and add a sector tag to `config.SECTOR_MAP`.

**Add a new signal:**  
Compute it in `data/fetcher.py` and add it to the `MarketSnapshot` dataclass. Update agent prompt templates to reference it.

**Add a new AI agent:**  
Create a class that extends `BaseAgent` in the `agents/` directory, implement `propose()`, and wire it into `orchestrator.py`.

**Change game constraints:**  
Update `config.GAME_CONSTRAINTS` — `portfolio/validator.py` reads from there.

**Adjust the stock universe or candidate count:**  
Edit `config.TOP_N_CANDIDATES`, `config.SP500_MARKET_CAP`, and `config.OTHER_MARKET_CAP`.
