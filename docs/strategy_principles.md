# AlphaShark — Permanent Strategy Principles

**Last updated:** 2026-04-27
**Status:** Active (overrides any conservative defaults in auto-generated files)

This file is NOT auto-generated. It survives daily pipeline runs and is injected into every
agent's learning context via `data/learning_context.py`.

---

## Strategic Mandate — Aggressive Hedge Fund

We are NOT a conservative wealth-preservation fund. We are an aggressive, high-beta,
catalyst-driven hedge fund competing in a short-term 10-week game. The objective is to **WIN**,
not to preserve capital.

- **Prioritize:** high-beta breakouts, sector momentum leaders, pre-earnings catalysts
- **Concentrate:** 5–8 positions maximum. Diversification is for managing money, not winning competitions.
- **Current regime (April 2026):** BULL tape but with widespread deceleration. SPX +5% above 50d SMA.
  Tech/semis had a big 20d run (+16%) but are now overbought and decelerating — rotation risk HIGH.
  Energy in correction (Brent $90, -19% 20d) — no energy thesis. Follow the momentum signals, not a thesis.
  Validated winners from live game: XOM, STX, APA. Recurring losers to avoid: AMD, EQNR.OL, DOW, VWS.CO.
- **Avoid:** low-beta telecom, Nordic banks as filler, shipping with SELL consensus (Mærsk), energy names in downtrend

---

## The Conservative Mistake — Do Not Repeat

**Mistake made:** The system was tuned for conservative wealth preservation — rigid beta targets
in NEUTRAL regimes, strict sector caps, RSI overbought filters, and wide diversification (8-10 positions).
This guarantees underperformance in a short-term competition. With 844 participants, a median
portfolio finishes 422nd. Conservative = losing by design.

**Fix in effect:** Prioritize high-beta momentum, extreme concentration (5-8 names), and sector
rotation leaders. The alpha source changes with regime — energy worked in pregame, but follow
live signal data, not a cached thesis. Never fill remaining weight with boring Nordic banks or telecom.

**Rule:** If any position has beta < 0.5 AND is not a deliberate hedge, replace it with a
higher-momentum candidate.

---

## Risk Management Guardrails (March 2026)

### Overbought Position Sizing
- **Rule:** RSI > 79 + within 2% of 52-week high → max 15% position weight
- **Exception:** volume_ratio > 1.8 allows full 25% (genuine breakout volume overrides overbought signal)
- **Rationale:** Breakout moves often exhaust at peaks; strong volume confirmation trumps RSI
- **Implementation:** `agents/risk_manager.py` rules 18 & 19

### Sector Concentration Policy
- **Updated 2026-04-27:** Caps tightened after a mono-sector (84% semiconductors) book dropped 300 ranks on a single sector down-day. Root causes: SECTOR_MAP was missing 20 tickers (mis-tagged as "US"), old 70% cap was too permissive for a 5-6 stock book, and exhaustion trigger had a vol < 1.2 gate that blocked detection of high-volume crowded sectors.
- **Unconditional ceiling:** 55% max in any single sector (was 70%).
- **Rotation-risk MEDIUM cap:** 45% (was 55%).
- **Rotation-risk HIGH cap:** 35% (was 40%).
- **MANDATORY: at least 2 different sectors** in every portfolio — code-enforced, never waivable.
- **Exhaustion trigger fix:** `vol_ratio < 1.2` gate removed from `exhaustion_high`. High-volume sector rallies (everyone piling into the same sector) are the most dangerous crowding scenario, not the safest.
- **SECTOR_MAP fix:** 20 tickers added (ON, MCHP, MPWR, LRCX, TER, ANET, COHR, SMCI, WDC, STX, GLW, DELL, GEV, WAB, STLD, HOOD, CVNA, FOXA, SBAC, SDRL.OL). Previously tagged "US" fallback, making sector enforcement blind to true concentration.
- **Implementation:** `agents/risk_manager.py::_enforce_sector_rotation_cap()` + orchestrator step 5c + `config.SECTOR_CAP_UNCONDITIONAL`.

### Beta — Informational Only in BEAR
- **Rule:** In BULL/NEUTRAL, beta target is 1.6–2.0 (BULL) or 0.95–1.30 (NEUTRAL) as a soft guide.
- **BEAR:** Beta is logged for information only. No position caps, no forced beta reduction. The goal is to find stocks going UP, not stocks that fall less.
- **Override in NEUTRAL:** If rotation risk is active (HIGH/MEDIUM), beta target is a soft diagnostic. Do not add high-beta filler to hit a number.
- **Implementation:** `agents/risk_manager.py::_enforce_beta()` (BEAR enforcement removed 2026-03-24)

### Low-Volume Concentration Guard
- **Rule:** Positions with `vol_ratio < 0.80` are capped at **18%** (even outside BEAR).
- **Portfolio check:** weighted-average `vol_ratio` warning fires below **0.85**.
- **Rationale:** Prevent portfolios dominated by unconfirmed breakouts.
- **Implementation:** `agents/risk_manager.py::_enforce_selection_quality()` + config thresholds

### Devil's Advocate Accuracy Tracking
- **Mechanism:** Devil tracks HIGH-flagged picks and compares their 1d returns vs all other picks
- **Data:** Stored in `learning_state.json['devil_accuracy']` (requires ≥5 HIGH-flag observations)
- **High accuracy (>60%):** Risk Manager applies 10% hard cap on HIGH-flagged positions
- **Low accuracy (≤60%):** Risk Manager uses own judgment; Devil is advisory only
- **Repeat offender pre-injection:** Tickers flagged HIGH in ≥2 of the last 5 days get a ≤12% sizing warning to all agents regardless of overall accuracy threshold
- **Implementation:** `data/learning_state.py::_devil_accuracy()` + prompt injection in context builder

### Learning Rule Promotion Ladder
- **Rule:** weak rationale tags with 5–7 observations are treated as **early warnings**, not mandatory bans.
- **Mandatory bias avoidance** now requires **8+ observations**.
- **Rationale:** avoid overfitting hard rules from thin samples.
- **Implementation:** `data/learning_state.py` thresholds and context rendering

### Cross-Agent Debate
- **Mechanism:** After initial proposals, each agent (Strategist, GeminiChallenger, FullAnalyst) runs a lightweight second-pass LLM call surfacing agreements and disagreements with peer proposals
- **Data:** Debate summary compiled by orchestrator and injected into Risk Manager's synthesis context
- **Implementation:** `agents/base_agent.py::cross_check()` + orchestrator step 3d (3 workers, 45s timeout, non-fatal)

### Dynamic Signal Importance
- **Mechanism:** `compute_signal_importance()` in `learning_state.py` tracks directional accuracy of each signal vs next-day returns across all position observations
- **Data:** Stored in `learning_state.json['signal_importance']`; top signals highlighted in learning context shown to all agents
- **Implementation:** `data/learning_state.py::compute_signal_importance()`

### Confidence Calibration Tracking
- **Mechanism:** Compares 1d returns on high-confidence (≥75%) vs low-confidence days
- **Action:** Flags overconfidence pattern when high-confidence days underperform expectations
- **Data:** Stored in `learning_state.json`; calibration warning injected into learning context
- **Implementation:** `data/learning_state.py::compute_confidence_calibration()`

### Strategy Decay Monitoring
- **Mechanism:** Compares recent 5-day alpha vs prior 10-day alpha
- **Threshold:** `decay_detected=True` when gap exceeds 0.2% per day
- **Action:** Risk Manager renders a STRATEGY DECAY ALERT section when decay is active
- **Implementation:** `data/meta_learning.py::detect_strategy_decay()` + orchestrator step 1b

### Portfolio Continuity Context (State + History)
- **Mechanism:** Orchestrator builds a shared `portfolio_state_context` from verified/current holdings + yesterday's realized portfolio vs benchmark performance + last 5 days of performance history
- **Action:** Injected into all agent prompts (Strategist, Gemini Challenger, Full Analyst, Risk Manager) so turnover and resizing are explicitly grounded in prior state
- **Intent:** Avoid stateless day-to-day churn; force explicit keep/cut/resize reasoning linked to actual portfolio history

### Discord Change Explanations
- **Mechanism:** Discord `Changes from Yesterday` now includes a short reason per ADD/REMOVE/RESIZE line
- **Source:** Uses position rationale + live signal context (momentum, relative strength, volume confirmation, overbought flags)
- **Intent:** Make execution instructions actionable (what changed and why), not just a diff list

---

| Rule | Value |
|------|-------|
| Stocks | 5–20 |
| Position weight | 5–25% (inclusive) |
| Max cash | 25% (must invest ≥75%) |
| Sector concentration | **No cap** — 100% in one sector is legal |
| Markets | US S&P 500, Baltic, OMX Helsinki, OMX Stockholm, OBX Norway, OMX Copenhagen |

### Sector concentration — no limits
The game has **zero sector caps**. If a single sector (Energy, Tech, AI, Healthcare) is showing
extreme momentum, you are fully authorized to concentrate 100% of the portfolio into that sector.

Examples of fully legal portfolios:
- 4 Energy stocks at 25% each (XOM + CVX + EQNR + AKRBP = 100%) ✅
- 4 Tech stocks at 25% each ✅
- Any combination as long as each position is 5–25% and total ≤ 100%

**Previous mistake to avoid:** The system previously enforced a fictitious 35% sector cap that
does not exist in the game rules. This was hallucinated by the AI and actively harmed performance
by preventing energy concentration during the 2026 Energy rotation year.

---

## Conviction Sizing Rules

| Signal | Weight |
|--------|--------|
| Consensus (both models agree) + strong signals | 20–25% |
| Single model, strong signals | 12–18% |
| Smaller position / lower conviction | 5–10% |

### Earnings — Opportunity, Not Risk
Pre-earnings momentum is an OPPORTUNITY. Binary gaps can deliver 10–20% in a single session — exactly the kind of right-tail outcome that wins competitions. Size pre-earnings plays by conviction, not by fear.
Rule 13 sizing limits apply (reinstated): max 20% per pre-earnings position, max 40% total, ≤2 names same week. Hard cap 10% for earnings within 1 day.

Never equal-weight. If everything gets the same weight, you are not thinking.

---

## Current Regime Guidance (April 2026 — live game)

This section is updated manually when the regime materially shifts. Always defer to live signal data over anything written here.

- **Regime:** BULL. SPX +5% above 50d SMA. VIX ~19. Breadth 65%.
- **Tech/semis:** Had a huge 20d run (+16%) — now decelerating and showing HIGH rotation risk (RSI overbought, vol fading). Still the strongest sector but sizing risk is elevated. The pipeline will apply rotation caps if concentration is too high.
- **Energy in correction:** Brent $90 (-19% in 20 days). No energy thesis. Avoid XOM, CVX, EQNR as primary positions unless signals specifically support them.
- **Validated live winners (from game data):** XOM (+1.5%/day, 75% hit rate), STX (+1.2%/day, 73% hit rate), APA (+1.0%/day, 71% hit rate).
- **Recurring live losers — avoid or hard-cap:** AMD (7% max cap, -0.24%/day avg), EQNR.OL (7% max cap, -1.56%/day avg), DOW (7% max cap), VWS.CO (-0.20%/day).
- **Devil accuracy note:** The Devil's HIGH-risk flags have been net BULLISH signals in this game (+0.63%/day on flagged picks vs -0.31% on non-flagged). Do not over-weight Devil warnings.
- **Signal ranking:** vol_ratio is the most reliable directional signal (56% accuracy). mom_5d and vs_index follow at 50%.
- **Avoid:** MAERSK-B.CO (SELL consensus), telecom (TEL.OL, TELIA.ST, ELISA.HE), low-beta fillers.

---

## May 2026 Recalibration (2026-05-07)

After 17 trading days live (€10k → €13.46k paper, +34.6%), rank trajectory in the live game went **393 → 406 → 355 → 556 → 551** out of ~8900 portfolios. Two consecutive +2-3% days lost ~200 ranks. Diagnosis: field's right tail outpacing us; need higher right-tail variance and lower turnover, not incremental alpha.

### Rationale evidence (n=139 position observations)

| Tag | Obs | Hit | Avg 1d |
|---|---|---|---|
| at_52w_high | 92 | 62% | +0.81% |
| overbought (RSI>80) | 63 | 60% | +0.80% |
| breakout | 22 | 59% | +0.62% |
| **catalyst (earnings)** | 20 | 40% | **−0.47%** |
| **diversifier** | 5 | 40% | **−0.42%** |
| **non_us_differentiator** | 37 | 27% | **−0.31%** |

### Rules added or changed

- **Rationale blacklist** propagated to all four agent system prompts: do not propose positions whose primary thesis is `non_us_differentiator`, `diversifier`, or earnings-only `catalyst`.
- **Rationale whitelist:** `at_52w_high + overbought + vol_ratio≥1.5 + mom_5d≥10%` is treated as leadership confirmation (max conviction allowed), not exhaustion.
- **Sector cap relaxed back to 70%** (was 55%). The 55% cap was forcing diversifier picks into the book to satisfy multi-sector minimum, dragging returns. With 5-stock concentrated books, mono-sector >55% is normal when one sector leads.
- **Pre-earnings caps tightened:** per name 20% → 12%, total 40% → 30%.
- **Overbought volume exception lowered** (1.8 → 1.5): leaders with vol_ratio 1.5–1.8 were getting capped despite RSI>85 + mom_5d>10% setup that empirically wins 62% of the time.
- **Turnover baseline raised:** min_hold_weight 0.50 → 0.65, replacement_sharpe_delta 0.20 → 0.40. Rationale: 14-day live data showed panic exits of winners (sold INTC then re-bought next day; sold QCOM the day after +14.8%). Whipsaw was costing alpha.
- **Devil's Advocate inversion:** with 80 obs and accuracy 24% (HIGH-flagged averaged +1.06%/day), Devil bear cases are prefixed `[CONTRARIAN-INVERTED]` and a `DEVIL CONTRARIAN MODE ACTIVE` block is injected into the Risk Manager system prompt instructing it not to downweight HIGH-flagged tickers.
- **Hard ban for tickers with hit_rate ≤25% and ≥10 obs:** `weight_caps` entry `max_weight=0.0`. Initial casualty: EQNR.OL (20% over 10 obs).

### New rank-aware feedback loop

- `competition_standings` table feeds `load_rank_delta_history(days)`.
- New `learning_state.rank_performance` block: 5-day rank delta, normalized delta (rank/total), best/worst alpha-day rank delta, alpha→rank Pearson correlation.
- Risk Manager system prompt now receives a dynamic `RANK CONTEXT` block listing the last five sessions; instruction: "If rank slipping despite positive alpha — field running hotter, INCREASE concentration / beta / right-tail breakouts."
- New `learning_state.missed_winners` block (will populate from 2026-05-08 onward): compares 1d return of held positions to top-3 unheld `candidate_alternatives`.

### Candidate alternatives logging

`orchestrator.py` now captures the top-30 candidates by `competition_score` (was top-5) including `proposed_by` (which agents proposed the ticker) and `in_final` flags. Persisted inside `decision_metrics` JSONB on `daily_runs`. Enables future post-mortem: which high-ranked names did the system pass over, and at what cost?
