# AlphaShark — Architectural & Strategy Roadmap

**Document Purpose:** A specific, actionable roadmap for evolving AlphaShark into an elite, competition-winning AI trading system while strictly adhering to a ~$130 API budget. It outlines what to build, and crucially, what "institutional quant traps" to avoid.

---

## 1. ❌ The "Do Not Build" List (Avoiding Quant Traps)
*Standard institutional quant advice focuses on wealth preservation. AlphaShark is built for a winner-takes-all 10-week sprint. We intentionally reject the following:*

- **NO Conservative Kelly Sizing / Max Drawdown Budgets:** Minimising drawdowns mathematically minimises upside variance. We want right-tail volatility. 
- **NO Market-Neutral Orthogonalization:** Stripping out sector beta to find "pure" idiosyncratic alpha is for hedge funds hedging market risk. In a long-only game during an energy/tech rotation, sector beta is our biggest edge.
- **NO Probabilistic Forecasts from LLMs:** Do not ask the LLM to output "expected return distributions" or confidence intervals. LLMs hallucinate math. Keep their job strictly to synthesising narrative and qualitative conviction.
- **NO Over-engineered Agentic Frameworks (LangGraph/AutoGen):** Introducing asynchronous, cyclic agent loops breaks the clean, linear DAG currently running flawlessly on stateless GitHub Actions. Keep it simple and linear.
- **NO Options Flow / Gamma Exposure (GEX):** While highly predictive, options data APIs (Polygon, Databento) are far too expensive and noisy for the $130 budget. Rely on free proxies (volume ratios, realised IV).

---

## 2. ⚡ In-Flight Efficiency: Token & Context Compression (Active)
*Goal: Squeeze maximum intelligence out of the $130 API budget (~$2.60/day).*

- **CSV/PSV over Padded Text/JSON [IMPLEMENTED]:** 
  - LLMs process Comma-Separated Values (CSV) or Pipe-Separated Values (PSV) natively.
  - Converting padded tables (`AAPL      10.5%`) to CSV (`AAPL,10.5%`) reduces prompt token counts by ~40-50%, allowing us to pass more candidates to the models for the same cost.
- **Strict Model Routing (Grunts vs. Brain):** 
  - *Data cleanup, rule checks, and debate:* Offload entirely to zero/low-cost models (Llama-3-70b, Gemini 2.5 Flash).
  - *Final Synthesis (Risk Manager):* Reserve premium credits (GPT-4o, GPT-5.x) strictly for the final decision layer.
- **Z-Score Normalisation:**
  - LLMs fail at absolute numerical reasoning but excel at cross-sectional percentiles. Always feed the LLM Z-scores (e.g., `+2.1 stdev`) rather than raw indicator values (e.g., `MACD 0.45`).

---

## 3. 🧠 Alpha Strategy: Structural Adjustments
*Goal: Move beyond basic retail technicals into structural market anomalies.*

### A. Post-Earnings Announcement Drift (PEAD)
- **Current State:** Flags *pre-earnings* risk/opportunity.
- **New Feature:** Track *post-earnings* reactions. When a stock beats earnings and gaps up >5% on 3x normal volume, it statistically drifts in that direction for 2–6 weeks due to institutional accumulation. 
- **Action:** Add a PEAD signal scanner to `earnings_fetcher.py` to specifically hunt yesterday's massive earnings winners.

### B. Mathematical Position Sizing (Aggressive Kelly)
- **Current State:** The Risk Manager LLM guesses raw percentage weights (e.g., "I like it, 20%").
- **New Feature:** Strip the LLM of its percentage-sizing power. Ask the LLM only for a "Conviction Score (1-10)".
- **The Math:** Implement the Kelly Criterion in `portfolio/validator.py`: `Kelly % = W - [(1 - W) / R]` (W = Historical Win Rate of that agent/tag, R = Average Win/Loss Ratio). 
- **Execution:** Use **Full Kelly** (capped at the 25% game limit) to maximise right-tail compound growth.

---

## 4. 🏗️ At-Rest Persistence: Serverless Database Migration
*Goal: Fix the structural bottleneck of committing JSON files to GitHub every day.*

- **The Problem:** Saving state via `portfolio_history.json` and `learning_state.json` via GitHub Actions `git commit` risks merge conflicts, silent race condition failures, and repository bloat. It also makes querying historical data highly inefficient.
- **The Solution:** Migrate to a free Serverless PostgreSQL database (e.g., Neon.tech, Supabase).
- **Implementation Steps:**
  1. Spin up a free Neon.tech Postgres instance.
  2. Store `DATABASE_URL` in GitHub Secrets.
  3. Replace `data/portfolio_store.py` with SQL inserts.
- **Proposed Schema:**
  - `daily_snapshots`: Stores regime, VIX, breadth.
  - `agent_proposals`: Stores individual agent picks, conviction scores, and rationale.
  - `portfolio_positions`: Stores the final chosen portfolio and its 1-day forward realized return.
- **Impact on Learning Loop:** `learning_state.py` can be entirely rewritten as clean SQL queries (e.g., `SELECT AVG(return_1d) FROM portfolio_positions WHERE rationale_tag = 'breakout'`) rather than looping through heavy JSON objects in Python memory.

---

## 5. Execution Roadmap & Priority List

**Phase 1: Immediate Token Savings (Done/In Progress)**
- [x] Convert agent `_build_message` formatting to CSV/PSV to radically drop token burn.

**Phase 2: Mathematical Sizing & Edge (Next Steps)**
- [ ] Update `portfolio/validator.py` to calculate Aggressive Kelly weights based on historical win-rates per signal/agent.
- [ ] Update `OpenAIRiskManager` prompt to output Conviction Scores (1-10) instead of `%` weights.
- [ ] Implement PEAD (Post-Earnings Announcement Drift) signal logic in data fetchers.

**Phase 3: Database & Production Hardening**
- [ ] Create Neon/Supabase DB.
- [ ] Migrate `portfolio_history.json` writes to SQL `INSERT` statements.
- [ ] Refactor `learning_state.py` to derive insights via SQL queries directly from the database.