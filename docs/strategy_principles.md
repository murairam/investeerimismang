# AlphaShark — Permanent Strategy Principles

**Last updated:** 2026-03-20
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

**Mistake made:** The system was tuned for conservative wealth preservation — low beta targets
(0.95–1.15), strict sector caps, RSI overbought filters, and wide diversification (8-10 positions).
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
- **Rule:** RSI > 82 + within 2% of 52-week high → max 15% position weight
- **Exception:** volume_ratio > 1.8 allows full 25% (genuine breakout volume overrides overbought signal)
- **Rationale:** Breakout moves often exhaust at peaks; strong volume confirmation trumps RSI
- **Implementation:** `agents/openai_risk_manager.py` rules 18 & 19

### Devil's Advocate Accuracy Tracking
- **Mechanism:** Devil tracks HIGH-flagged picks and compares their 1d returns vs all other picks
- **Data:** Stored in `learning_state.json['devil_accuracy']` (requires ≥5 HIGH-flag observations)
- **High accuracy (>60%):** Risk Manager applies 10% hard cap on HIGH-flagged positions
- **Low accuracy (≤60%):** Risk Manager uses own judgment; Devil is advisory only
- **Implementation:** `data/learning_state.py::_devil_accuracy()` + prompt injection in context builder

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
| Diversifier / speculative | 5–10% |

Never equal-weight. If everything gets the same weight, you are not thinking.

---

## Current Regime Guidance (March–April 2026)

- **Energy rotation:** Brent ~$103, Iran conflict, OPEC+ discipline. XOM, CVX, EQNR, AKRBP up 25%+ YTD.
- **Tech correction:** AI/semiconductor names -15-20% from 2025 highs. Avoid pure-tech concentration.
- **Defense:** European rearmament driving KONG.OL (Kongsberg Gruppen) — strong OBX performer.
- **Healthcare catalyst:** LLY on GLP-1 drug pipeline momentum.
- **Nordic logistics:** DSV.CO recovering, differentiated from crowd.
- **Avoid:** MAERSK-B.CO (SELL consensus, structural overcapacity), telecom (TEL.OL, TELIA.ST, ELISA.HE).
