evaluated.
every commit message:
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AlphaShark** is an autonomous quantitative trading agent for the **Äripäev/SEB Investment Game** (Estonia). It runs daily via GitHub Actions, fetches live market data across the full game-sized universe, uses a multi-agent AI ensemble to build a momentum portfolio, validates it against game rules, and posts the recommendation to Discord.

**Game period:** 6 April – 19 June 2026
**6 markets:** US S&P 500, OMX Helsinki/Stockholm/Copenhagen, OBX Norway, Baltic Main List (~630 selectable tickers after game-availability filtering)

## Running Locally

```bash
cp .env.example .env       # fill in API keys
pip install -r requirements.txt
python main.py             # run full pipeline
python scripts/status.py   # view project dashboard
python scripts/verify.py   # confirm portfolio (LIVE mode after submission)
python scripts/pregame_review.py  # refresh pre-game learning summary
```

Required env vars: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DISCORD_WEBHOOK_URL`.
Optional: `OPENROUTER_API_KEY` (secondary-agent routing), `DISCORD_USER_ID`.

Gemini fallback chain: OpenRouter `meta-llama/llama-4-maverick:free` first, then OpenAI `gpt-5.4-nano` as final fallback.

No formal test suite — validate changes with `python main.py` and `python scripts/status.py`.

## Architecture

```
yfinance primary market data + EODHD fallback for edge-case Nordic/Baltic symbols
    ↓
data/fetcher.py — 15 signals per stock + macro context (regime score 0-100, VIX, breadth)
    ↓ (parallel)
agents/strategist.py (GPT-5.4)          ─┐ Proposal A: momentum strategist
agents/challenger.py (Gemini 2.5 Flash)  ─┤ Proposal B: catalyst hunter
agents/full_analyst.py (DeepSeek V3.2 via OpenRouter, fallback GPT-5.4-nano) ─┘ Proposal C: full analyst (all signals)
    ↓
agents/devil.py (Qwen3-235B-A22B via OpenRouter, fallback GPT-5.4-nano) — stress-tests top picks → bear cases
    ↓
agents/risk_manager.py (GPT-5.4) — synthesises all 3 proposals + bear cases → PortfolioProposal
    ↓
portfolio/validator.py — enforces game constraints, normalises weights
    ↓
data/paper_account.py — virtual P&L rebalancing (PREGAME) / portfolio_history.json
    ↓
Structured learning loop: portfolio_history.json → learning_state.json → derived markdown reports
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
| `data/learning_state.py` | Structured learning rules, Devil accuracy tracking, rationale tag analysis |

## Competition Optimization Features (Added March 2026)

### BULL Regime Concentration
- **Target:** 5 positions at ~20% each — only add a 6th if genuinely high-conviction
- **Config:** `POSITION_TARGETS_BY_REGIME["BULL"]["max_stocks"] = 6` (was 8)
- **Enforced in:** All agent system prompts + Risk Manager synthesis rules

### Competition Context in Agent Prompts
- **All 4 agents** now open with: "{n_participants} participants, only #1 wins — INTELLIGENT AGGRESSION required" (count loaded dynamically from DB via `load_last_known_participant_count()` and injected into `snapshot["n_participants"]` by the orchestrator)
- **Risk Manager** additionally: "15% drawdown acceptable for 40% upside potential — price for competition, not wealth management"

### Sector Rotation Indicator
- **Computed:** In `data/fetcher.py::get_market_snapshot()` from all valid records before top-N filtering
- **Fields:** `avg_mom_20d`, `avg_mom_5d`, `avg_rsi`, `breadth` (% stocks with positive 5d return), `count`
- **Injected:** `snapshot["sector_momentum"]` — all 4 agents render a formatted rotation table in user messages
- **Why:** Rotation is THE alpha source in 75-day competitions — staying in exhausted sectors = 10–15% underperformance

### Pre-Earnings Opportunity Signal
- **New function:** `data/earnings_fetcher.py::format_earnings_opportunity()` — tags stocks with earnings in 2–6 days AND strong momentum (mom_5d ≥ 4% OR mom_20d ≥ 10%) AND RSI 50–75 as `PRE_EARNINGS_SETUP`
- **Sizing limits (Risk Manager rule 13):** max 20% per pre-earnings position, max 40% total, ≤2 names same week; hard cap 10% only for earnings within 1 day
- **Low-conviction earners** still get `EARNINGS RISK` warning via updated `format_earnings_warning(candidates=...)`

### Competition-Optimized Candidate Ranking
- **Config:** `COMPETITION_SORT_WEIGHTS` — Z-score weighted regime-specific ranking
  - BULL: `mom_20d 35% + mom_5d 25% + sharpe_20d 20% + beta 20%`
  - NEUTRAL: `sharpe_20d 40% + vs_index 30% + mom_20d 20% + beta 10%`
  - BEAR: `sharpe_20d 50% + vs_index 30% + inv_beta 20%`
- **Function:** `data/fetcher.py::_compute_competition_scores()` — Z-normalizes features, stores `competition_score` in each record
- **Sort key changed:** candidates now sorted by `competition_score` (was `selection_score + sharpe_20d`)
- **BEAR note:** `inv_beta = 1 - beta` is computed BEFORE Z-scoring

## Risk Control Features (Added March 2026, updated April 2026)

### Sector Concentration Cap (Updated 2026-04-29)
- **Unconditional ceiling:** 55% in any single sector (lowered from 70% — the old 70% cap was too high for a 5-6 stock book; a 6-stock mono-sector portfolio reached 84% and dropped 300 ranks in one sector down-day)
- **Rotation-risk MEDIUM:** 45% (was 55%); **HIGH:** 35% (was 40%)
- **MANDATORY minimum:** at least 2 sectors in every portfolio — **code-enforced in `portfolio/validator.py::validate()` AND by `_enforce_sector_rotation_cap()` after step 5c** (previously prompt-only; added to validator 2026-04-29)
- **SECTOR_MAP fix:** 20 SP500/OBX tickers added that were previously mis-tagged as "US" fallback (ON, MCHP, MPWR, LRCX, TER, ANET, COHR, SMCI, WDC, STX, GLW, DELL, GEV, WAB, STLD, HOOD, CVNA, FOXA, SBAC, SDRL.OL) — the missing tags made sector enforcement blind to true Tech concentration
- **Exhaustion trigger fix:** `vol_ratio < 1.2` gate removed from `detect_rotation_risk()` `exhaustion_high` branch — high-volume sector rallies are crowding events, not exceptions
- **Learning-state cap threshold:** `_RATIONALE_CAP_HIT_RATE_THRESHOLD` lowered from 0.30 → 0.25 so that mediocre diversification rationales (e.g. `non_us_differentiator` at 27%) no longer trigger a hard position cap that compounds the mono-sector bias

### Overbought Weight Cap
- **When triggered:** RSI > 85 AND position within 2% of 52-week high (raised from 79 — in competition momentum markets RSI 79-84 = leader, not topper)
- **Action:** Cap position weight at 15% — **code-enforced in `_enforce_selection_quality()` (Pass A)**
- **Exception:** If volume_ratio > 1.8 (strong breakout volume), full 25% is allowed
- **Rationale:** Prevents max-sizing exhausted patterns while allowing momentum leaders at RSI 79-84

### Devil's Accuracy Feedback Loop (Updated 2026-04-29)
- **What it measures:** Devil's advocate flagged picks as HIGH-risk — tracked against 1-day returns
- **Where stored:** `learning_state.json['devil_accuracy']`
- **Activation criterion:** ≥15 HIGH-flag observations in the rolling 30-day window (raised from 5/8 — at n=5 the 95% CI spans ±35%, making the cap statistically indefensible)
- **Win definition:** Loss > 0.5% (–0.005) — plain negative returns include intraday mean-reversion noise; only real losses count as devil wins
- **If accuracy > 65%:** HIGH-flagged picks are hard-capped at 10% — **code-enforced in `_enforce_selection_quality()` (Pass B)** (threshold raised from 60%)
- **Rolling window:** 30-day lookback — stale pregame errors no longer permanently cap live picks
- **If accuracy ≤ 60%:** Risk Manager uses own judgment (Devil is noisy, lighter weight)
- **How to inspect:** Run `python scripts/status.py` — shows Devil accuracy, active rules, and weight caps

### BEAR Regime Beta Cap
- **When triggered:** BEAR regime AND portfolio beta exceeds adjusted target (≤0.90 scaled for non-US exposure)
- **Action:** All individual position weights capped at 15%; freed weight left as cash (NOT re-normalized — renormalizing would immediately undo the cap; orchestrator step-5e floors at 75% if needed)
- **Where enforced:** `_enforce_beta()` in `agents/risk_manager.py` (fixed 2026-04-29: removed internal renormalization that was undoing the cap)
- **Rationale:** Prevents high-beta concentration in bear markets where downside risk is asymmetric

### Analyst Consensus + Price Target
- **Fields:** `analyst_rating` (1=Strong Buy → 5=Strong Sell), `analyst_upside` ((target−price)/price)
- **Source:** `yfinance Ticker.info` — `recommendationMean`, `targetMeanPrice`
- **Coverage:** Good for US S&P 500; `analyst_upside` is NaN for non-US tickers (currency mismatch guard); rating returned for Nordic large-caps where available
- **Visible in:** FullAnalyst signal table (`AnaRtg` / `AnaUp%` columns); Risk Manager synthesis note
- **Interpretation:** High momentum + positive upside = conviction; high momentum + negative upside = stretched/crowded

### Commodity Price Context
- **Fetched:** `BZ=F` (Brent crude), `CL=F` (WTI), `NG=F` (Henry Hub nat gas) via `DataFetcher.fetch_commodity_context()`
- **Injected:** `snapshot["commodity_context"]` added in `orchestrator.py` step 1a; rendered in Strategist, FullAnalyst, and Risk Manager user messages
- **Signals:** last price, 20d return, 5d return (Brent only) for all three commodities
- **Purpose:** Energy stock thesis validation — agents see live commodity momentum before sizing energy positions

### Signal Rationale Tagging
- **Where tracked:** `data/learning_state.py::derive_rationale_tags()` and `learning_state.json`
- **Tags include:** `overbought`, `at_52w_high`, `strong_volume`, `consensus`, etc.
- **Purpose:** Structured audit trail explaining why each position was sized as it was
- **Used in:** AI self-critique report generation + Devil accuracy analysis

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
    Tech in correction. Favour XOM, CVX, EQNR.OL, KOG.OL, LLY, DSV.CO.
- Avoid: low-beta telecom, Nordic banks as filler, shipping with SELL consensus (Mærsk)
- Tech stack: yfinance for data, vectorized pandas for math (no TA-Lib or bloated libraries),
    Python 3.12+ type hints throughout, `logging` (not `print`) for all output.

## Memory Loop — Mandatory Reading

Before writing any new trading logic or modifying agent prompts, you MUST:
1. Read `learning_state.json` or `data/learning_state.py` outputs first — this is the machine source of truth.
2. Read `AI_SELF_CRITIQUE.md` only as a human-readable audit (optional for prompt logic).
3. Read `PREGAME_LEARNING.md` only as a human-readable training summary (optional for prompt logic).
4. Read `docs/strategy_principles.md` — the persistent strategic pivot document that survives
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
| Regime-based target count | concentrated book, typically 5-8 names depending on current risk-manager policy |

## Operational Modes

- **PREGAME (before 2026-04-06):** Updates one canonical `PREGAME_LOG.md` entry per date, appends full reruns to `PREGAME_RUNS.md`, tracks virtual €10k in `paper_account.json`, and generates structured learning files.
- **LIVE (on/after 2026-04-06):** Writes to `DAILY_LOG.md`. `live_mode_lock.json` SHA256-locks strategy files. **Do not edit it manually** — the `update_live_lock.yml` workflow regenerates it automatically on every merge to `main` that touches a protected file.

## Coding Conventions

- All public functions/methods must have type hints.
- Use `logging` (not `print`) — DEBUG/INFO/WARNING/ERROR levels.
- All tunable params in `config.py` — no magic numbers in agent or data code.
- Domain models are pure `dataclasses` (no business logic inside them).
- Network/API calls must handle timeouts and retries; never crash the pipeline on a single failure.

## Auto-generated Files (do not edit manually)

These are updated automatically by the pipeline: `portfolio_history.json`, `paper_account.json`, `cost_log.json`, `verification_tracker.json`, `live_mode_lock.json`, `PREGAME_LOG.md`, `PREGAME_RUNS.md`, `PREGAME_LEARNING.md`, `AI_SELF_CRITIQUE.md`, `learning_state.json`, `evening_observations.json`.

## Common Tasks

**Add / remove a game ticker:** Update the universe loader / game-availability layer, not a small hardcoded shortlist.

**Add a signal:** Compute in `data/fetcher.py`, add to `MarketSnapshot`, update agent prompt templates.

**Add an agent:** Extend `BaseAgent`, implement `propose()`, wire into `orchestrator.py`.

**Change constraints:** Edit `config.GAME_CONSTRAINTS` — validator reads from there automatically.

## Pre-Push Documentation Checklist

Before committing code changes, update the following documentation files if they are affected:

1. **Modified agent prompts or decision logic?** → Update `docs/strategy_principles.md` with any new strategic rules or regime guidance
2. **Added/changed signal or feature?** → Update `README.md` signals table or architecture diagram
3. **Added/changed risk controls or constraints?** → Update this CLAUDE.md "Risk Control Features" section
4. **Changed game universe, ticker selection, or symbol mapping?** → Update `README.md` Universe section
5. **Changed config parameters?** → Document the change in CLAUDE.md or CLAUDE.md code comments
6. **Fixing a JSON serialization issue?** → Document the fix approach (e.g., NaN → null conversion in `_sanitize()`)

Auto-generated files (`PREGAME_LOG.md`, `PREGAME_RUNS.md`, `PREGAME_LEARNING.md`, `AI_SELF_CRITIQUE.md`, `portfolio_history.json`, `learning_state.json`) do NOT need manual updates.

7. **Modified a protected strategy file** (`config.py`, `docs/rules.txt`, any file in `agents/`)? → **Do NOT update `live_mode_lock.json` manually.** The `update_live_lock.yml` workflow regenerates it automatically as soon as your PR is merged to `main`. Including a manually-updated lock in your PR is fine too, but the workflow will overwrite it correctly anyway.

## GitHub Actions

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `alphashark.yml` | Mon–Fri 04:00 UTC | Full pipeline, auto-commits portfolio + learning files |
| `verification_reminder.yml` | Mon–Fri 07:00 UTC | Discord reminder if portfolio not verified (LIVE only) |
| `evening_review.yml` | Post-market | Optional evening review |
| `update_live_lock.yml` | On push to `main` (protected files only) | Regenerates `live_mode_lock.json` fingerprints so the daily run never hits a freeze violation |

GitHub secrets required: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DISCORD_WEBHOOK_URL`.
Optional: `OPENROUTER_API_KEY`, `DISCORD_USER_ID`.
