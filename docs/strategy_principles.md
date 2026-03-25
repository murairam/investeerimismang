# AlphaShark — Permanent Strategy Principles

**Last updated:** 2026-03-24
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
- **Current regime (2026):** Energy rotation year. Brent ~$103, energy +25% YTD. Tech in correction.
  Favour XOM, CVX, EQNR.OL, KONG.OL, LLY, DSV.CO.
- **Avoid:** low-beta telecom, Nordic banks as filler, shipping with SELL consensus (Mærsk)

---

## The Conservative Mistake — Do Not Repeat

**Mistake made:** The system was tuned for conservative wealth preservation — rigid beta targets
in NEUTRAL regimes, strict sector caps, RSI overbought filters, and wide diversification (8-10 positions).
This guarantees underperformance in a short-term competition. With 844 participants, a median
portfolio finishes 422nd. Conservative = losing by design.

**Fix in effect:** Prioritize high-beta momentum, extreme concentration (5-8 names), and sector
rotation leaders. In the 2026 Energy rotation regime, that means XOM/EQNR at 20%+ each.
Never fill remaining weight with boring Nordic banks or telecom.

**Rule:** If any position has beta < 0.5 AND is not a deliberate hedge, replace it with a
higher-momentum candidate.

---

## Risk Management Guardrails (March 2026)

### Overbought Position Sizing
- **Rule:** RSI > 79 + within 2% of 52-week high → max 15% position weight
- **Exception:** volume_ratio > 1.8 allows full 25% (genuine breakout volume overrides overbought signal)
- **Rationale:** Breakout moves often exhaust at peaks; strong volume confirmation trumps RSI
- **Implementation:** `agents/openai_risk_manager.py` rules 18 & 19

### Sector Concentration Policy
- **Rule:** No sector caps are enforced in code. If alpha clusters in one sector, concentration is allowed up to game position limits.
- **Rationale:** The game has no sector concentration rule; artificial caps can dilute winning momentum clusters.
- **Implementation:** Sector concentration remains unconstrained in `agents/openai_risk_manager.py`.

### Beta — Informational Only in BEAR
- **Rule:** In BULL/NEUTRAL, beta target is 1.6–2.0 (BULL) or 0.95–1.30 (NEUTRAL) as a soft guide.
- **BEAR:** Beta is logged for information only. No position caps, no forced beta reduction. The goal is to find stocks going UP, not stocks that fall less.
- **Override in NEUTRAL:** If rotation risk is active (HIGH/MEDIUM), beta target is a soft diagnostic. Do not add high-beta filler to hit a number.
- **Implementation:** `agents/openai_risk_manager.py::_enforce_beta()` (BEAR enforcement removed 2026-03-24)

### Low-Volume Concentration Guard
- **Rule:** Positions with `vol_ratio < 0.80` are capped at **18%** (even outside BEAR).
- **Portfolio check:** weighted-average `vol_ratio` warning fires below **0.85**.
- **Rationale:** Prevent portfolios dominated by unconfirmed breakouts.
- **Implementation:** `agents/openai_risk_manager.py::_enforce_selection_quality()` + config thresholds

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
Pre-earnings momentum is an OPPORTUNITY. Binary gaps can deliver 10–20% in a single session — exactly the kind of right-tail outcome that wins competitions. Size pre-earnings plays by conviction (up to 25%), not by fear. Rule 13 earnings caps have been removed (2026-03-24).

Never equal-weight. If everything gets the same weight, you are not thinking.

---

## Current Regime Guidance (March–April 2026)

- **Energy rotation:** Brent ~$103, Iran conflict, OPEC+ discipline. XOM, CVX, EQNR, AKRBP up 25%+ YTD.
- **Tech correction:** AI/semiconductor names -15-20% from 2025 highs. Avoid pure-tech concentration.
- **Defense:** European rearmament driving KONG.OL (Kongsberg Gruppen) — strong OBX performer.
- **Healthcare catalyst:** LLY on GLP-1 drug pipeline momentum.
- **Nordic logistics:** DSV.CO recovering, differentiated from crowd.
- **Avoid:** MAERSK-B.CO (SELL consensus, structural overcapacity), telecom (TEL.OL, TELIA.ST, ELISA.HE).
