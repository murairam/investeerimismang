# Copilot Instructions for AlphaShark

## Project Overview

**AlphaShark** is an autonomous quantitative trading agent for the **Äripäev/SEB Investment Game** (Estonia). It runs daily via GitHub Actions, fetches live market data, uses a multi-model AI ensemble (GPT-5.4 Strategist + Gemini 2.5 Flash Challenger + DeepSeek V3.2 Full Analyst + Qwen3-235B Devil + GPT-5.4 Risk Manager) to build a momentum portfolio, validates it against game rules, and posts the daily recommendation to Discord.

**Game period:** 6 April – 19 June 2026  
**Daily execution:** GitHub Actions fires at 06:00 UTC on weekdays (Mon–Fri)

---

## Technology Stack

- **Language:** Python 3.12
- **AI models:** OpenAI GPT-5.4 (Strategist, Risk Manager) + Gemini 2.5 Flash (Challenger, with OpenRouter Llama 4 Maverick fallback then OpenAI GPT-5.4-nano) + OpenRouter DeepSeek V3.2 (Full Analyst) + OpenRouter Qwen3-235B-A22B (Devil)
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
DeepSeek V3.2 FullAnalyst ────────────────────────────────────┘
                                                              ↓
              [Cross-agent debate — lightweight second pass per agent]
                                                              ↓
Qwen3-235B-A22B Devil — bear-case stress test for top picks
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
| `agents/strategist.py` | GPT-5.4 momentum-driven portfolio selection |
| `agents/challenger.py` | Gemini 2.5 Flash catalyst-hunter second opinion |
| `agents/full_analyst.py` | DeepSeek V3.2 full analyst third proposal (OpenRouter; fallback GPT-5.4-nano) |
| `agents/devil.py` | Qwen3-235B bear-case stress tester (OpenRouter; fallback GPT-5.4-nano) |
| `agents/risk_manager.py` | GPT-5.4 that synthesises all proposals + debate + bear cases |
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
OPENROUTER_API_KEY=...      # DeepSeek V3.2 (Full Analyst), Qwen3-235B (Devil), and Llama 4 Maverick (Gemini fallback)
GROQ_API_KEY=...            # Optional legacy key (current fallback chain no longer depends on Groq)
EODHD_API_KEY=...           # Nordic/Baltic ticker fallback
DISCORD_WEBHOOK_URL=...     # Discord channel webhook
DISCORD_USER_ID=...         # Optional: enables @mentions in LIVE mode
```

---

```

