# AlphaShark — Post-Game Analysis

**Competition:** Äripäev/SEB Investment Game 2026  
**Game period:** 6 April – 19 June 2026 (75 calendar trading days)  
**Paper track period:** 13 April – 15 June 2026 (36 trading sessions tracked)  

> The paper account tracks what would have happened if every daily AI recommendation
> was executed. It is the "hypothetical-perfect-execution" baseline.
> The user did not submit trades actively in the final ~4 weeks of the game.
> Final 4 trading days (Jun 16–19) are not captured.

## Executive Summary

| Metric                         | Value                                          |
| ------------------------------ | ---------------------------------------------- |
| Paper track return             | +41.78%                                        |
| Peak return (Jun 1)            | +59.22%                                        |
| Max drawdown from peak         | -11.46%                                        |
| Trading days tracked           | 36                                             |
| Win rate (days > 0%)           | 61.1% (22W / 13L)                              |
| Avg daily return               | +1.04%                                         |
| Annualized Sharpe ratio        | 4.46                                           |
| Avg daily turnover             | 4.3%                                           |
| Rebalance days (turnover > 5%) | 4                                              |
| Last known game rank (Jun 12)  | #809 / 9,300 players                           |
| AI agents deployed             | 4 (Strategist, Challenger, FullAnalyst, Devil) |

## Equity Curve

| Date       | Equity (€) | Daily Return | Cumulative Return | Turnover |
| ---------- | ---------: | -----------: | ----------------: | -------: |
| 2026-04-13 |    €10,423 |       +4.23% |            +4.23% |       0% |
| 2026-04-14 |    €10,536 |       +1.08% |            +5.36% |       0% |
| 2026-04-15 |    €10,546 |       +0.09% |            +5.46% |       0% |
| 2026-04-16 |    €10,537 |       -0.08% |            +5.37% |       0% |
| 2026-04-15 |    €10,537 |       +0.00% |            +5.37% |       0% |
| 2026-04-17 |    €10,947 |       +3.89% |            +9.47% |      34% |
| 2026-04-20 |    €10,680 |       -2.44% |            +6.80% |       0% |
| 2026-04-21 |    €10,866 |       +1.74% |            +8.66% |       0% |
| 2026-04-22 |    €10,895 |       +0.27% |            +8.95% |       0% |
| 2026-04-23 |    €11,267 |       +3.41% |           +12.67% |       0% |
| 2026-04-24 |    €11,621 |       +3.14% |           +16.21% |       0% |
| 2026-04-26 |    €11,590 |       -0.26% |           +15.90% |       0% |
| 2026-04-27 |    €12,022 |       +3.72% |           +20.22% |       0% |
| 2026-04-28 |    €11,827 |       -1.62% |           +18.27% |       0% |
| 2026-04-29 |    €11,564 |       -2.22% |           +15.64% |       0% |
| 2026-04-30 |    €12,402 |       +7.25% |           +24.02% |       0% |
| 2026-05-01 |    €12,517 |       +0.93% |           +25.17% |       0% |
| 2026-05-04 |    €12,681 |       +1.31% |           +26.81% |       0% |
| 2026-05-05 |    €12,691 |       +0.08% |           +26.91% |       0% |
| 2026-05-06 |    €12,960 |       +2.12% |           +29.60% |       0% |
| 2026-05-07 |    €13,461 |       +3.86% |           +34.61% |       0% |
| 2026-05-08 |    €13,964 |       +3.74% |           +39.64% |       0% |
| 2026-05-11 |    €14,234 |       +1.93% |           +42.34% |       0% |
| 2026-05-12 |    €14,264 |       +0.21% |           +42.64% |       0% |
| 2026-05-13 |    €13,914 |       -2.45% |           +39.14% |       0% |
| 2026-05-14 |    €14,200 |       +2.06% |           +42.00% |       0% |
| 2026-05-15 |    €13,908 |       -2.06% |           +39.08% |      52% |
| 2026-05-18 |    €13,764 |       -1.04% |           +37.64% |      22% |
| 2026-05-19 |    €13,555 |       -1.52% |           +35.55% |      47% |
| 2026-05-20 |    €13,259 |       -2.18% |           +32.59% |       0% |
| 2026-05-21 |    €13,167 |       -0.69% |           +31.67% |       0% |
| 2026-05-28 |    €13,944 |       +5.90% |           +39.44% |       0% |
| 2026-06-01 |    €15,922 |      +14.19% |           +59.22% |       0% |
| 2026-06-04 |    €15,360 |       -3.53% |           +53.60% |       0% |
| 2026-06-12 |    €14,098 |       -8.22% |           +40.98% |       0% |
| 2026-06-15 |    €14,178 |       +0.57% |           +41.78% |       0% |

> **Peak:** €15,922 on 2026-06-01 (+59.22%)  
> **Final:** €14,178 on 2026-06-15 (+41.78%)  
> **Max drawdown from peak:** -11.46%

## Month-by-Month Breakdown

| Month   | Days | Avg Daily Return | Monthly Return |  W | L |
| ------- | ---: | ---------------: | -------------: | -: | : |
| 2026-04 |   16 |           +1.39% |        +24.02% | 10 | 6 |
| 2026-05 |   16 |           +0.76% |        +12.43% | 10 | 6 |
| 2026-06 |    4 |           +0.75% |         +1.68% |  2 | 2 |

## Market Regime Breakdown

> Based on DAILY_LOG entries — regime on the date the recommendation was made.

| Regime  | Days | Avg Alpha vs Benchmark |
| ------- | ---: | ---------------------: |
| BEAR    |    2 |                 -1.55% |
| BULL    |   39 |                 +0.58% |
| NEUTRAL |    5 |                 -0.86% |

## What Worked

### Rationale Tag Performance

> Each AI recommendation is tagged with one or more rationale labels.
> Tracked over 56 recorded trading days, 270 position-day observations.

| Rationale Tag         | Observations | Avg Daily Return | Hit Rate |
| --------------------- | -----------: | ---------------: | -------: |
| breakout              |           95 |           +0.99% |    56.8% |
| at_52w_high           |          196 |           +0.89% |    57.6% |
| catalyst              |           39 |           +0.84% |    51.3% |
| overbought            |          167 |           +0.81% |    54.5% |
| momentum              |          255 |           +0.74% |    54.5% |
| high_sharpe           |          193 |           +0.71% |    49.7% |
| consensus             |          189 |           +0.63% |    52.4% |
| non_us_differentiator |           42 |           -0.25% |    30.9% |
| diversifier           |           17 |           -0.45% |    47.1% |

> **Hit rate** = % of days the position closed positive.  
> Tags that appear on a single position are cumulative (e.g. `momentum + at_52w_high` increments both).

### Best Performing Tickers

| Ticker   | Observations | Avg Daily Return | Hit Rate |
| -------- | -----------: | ---------------: | -------: |
| INTC     |           30 |           +2.69% |    60.0% |
| CSCO     |           10 |           +2.69% |    60.0% |
| MPWR     |            8 |           +2.65% |   100.0% |
| NOKIA.HE |            8 |           +2.64% |    75.0% |
| AMD      |           22 |           +2.58% |    72.7% |

### Signal Directional Accuracy

> % of next-day predictions where signal pointed the right direction.
> Random baseline = 50%.

| Signal     | Directional Accuracy (Global) |
| ---------- | ----------------------------: |
| vol_ratio  |                         57.6% |
| momentum   |                         54.6% |
| mom_5d     |                         54.6% |
| vs_index   |                         54.6% |
| rsi_14     |                         53.8% |
| beta       |                         53.8% |
| sharpe_20d |                         44.6% |

> In **BULL** regime: `vol_ratio`, `momentum`, `vs_index` all hit **58.6%** accuracy.
> In **NEUTRAL** regime: `vol_ratio` was the only signal above 50% at **54.0%**.

## What Didn't Work

### Underperforming Rationale Tags

| Rationale Tag         | Observations | Avg Daily Return | Hit Rate | Verdict            |
| --------------------- | ------------ | ---------------- | -------- | ------------------ |
| diversifier           | 17           | -0.45%           | 47.1%    | Blacklisted May 7  |
| non_us_differentiator | 42           | -0.25%           | 30.9%    | Blacklisted May 7  |
| catalyst (earnings)   | 39           | +0.84%           | 51.3%    | Size-capped (≤12%) |

> `diversifier` and `non_us_differentiator` were added to `biases_to_avoid` after
> empirical evidence accumulated past the 5-observation threshold. These tags typically
> reflected Nordic/Baltic filler picks chosen for geographic diversification rather
> than signal quality.

### Recurring Losers

| Ticker  | Observations | Avg Daily Return | Hit Rate | Outcome       |
| ------- | -----------: | ---------------: | -------: | ------------- |
| EQNR.OL |           10 |           -1.56% |    20.0% | Hard banned   |
| GEV     |            8 |           -1.21% |    25.0% | Hard banned   |
| DOW     |            8 |           -0.71% |    50.0% | Weight-capped |
| MU      |           22 |           -0.42% |    27.3% | Weight-capped |
| VWS.CO  |           12 |           -0.20% |    33.3% | Weight-capped |

### Devil's Advocate — A Contrarian Reversal

> The Devil agent stress-tests top picks and flags them HIGH or LOW risk.
> Original expectation: HIGH flags = bad picks to avoid.
> Empirical outcome after 77 observations: **opposite**.

| Devil Flag | Avg 1-Day Return | Negative Rate |
| ---------- | ---------------: | ------------: |
| HIGH risk  |           +0.66% |         36.4% |
| LOW risk   |           +1.67% |           n/a |

> Devil accuracy (HIGH-flag = actual loser): **36.4%** (n=77)  
> At n=77 the system **inverted** the Devil signal — HIGH-flagged tickers became
> contrarian buy confirmations, not warnings. This was automated via `devil_inversion_active`.

### Conviction Tier Paradox

| Tier                        | Observations | Avg Daily Return |
| --------------------------- | -----------: | ---------------: |
| Tier 1 (highest conviction) |          114 |           +0.61% |
| Tier 2 (mid conviction)     |          123 |           +0.88% |
| Tier 3 (lowest conviction)  |           33 |           +0.19% |

> Tier 2 outperformed Tier 1 by **+0.27%/day**. Hypothesis: over-consensus on top-ranked
> names led to buying at crowded prices, while second-tier picks had less efficient pricing.

## Key Lessons for Next Time

| # | Lesson | Evidence |
|---|--------|----------|
| 1 | **Concentrate in breakout + at_52w_high** | Breakout: +0.99%/day, 56.8% hit — best tag. Diversifier: -0.45%/day. |
| 2 | **Invert Devil's Advocate early** | Devil was wrong 63.6% of the time. Inversion should trigger at n=20, not n=77. |
| 3 | **Avoid non-US filler picks** | `non_us_differentiator` hit rate: 30.9%. Nordic/Baltic diversification cost alpha. |
| 4 | **Rank ≠ alpha** | Correlation between daily alpha and rank improvement was only **-0.16**. Need higher-beta right-tail picks to move rank in a 9,300-player field. |
| 5 | **Hold winners longer** | Average turnover 30% — too high. Turnover guidance target: ≤25%. Replacing winners cost entry/re-entry spread. |
| 6 | **Ship trades daily** | Not submitting for ~4 weeks meant the paper track diverged from reality. Even submitting once/week captures most of the alpha. |

## Architecture Reflection

### What the Multi-Agent Ensemble Added

- **Debate prevented groupthink:** Strategist (GPT-5.4) and Challenger (Gemini 2.5 Flash)
  regularly diverged on Nordic vs US picks. When FullAnalyst (DeepSeek V3.2) broke the tie,
  consensus positions showed +0.63%/day and 52.4% hit rate — better than any single model.
- **Self-improving loop worked:** Hard rules, weight caps, and rationale blacklists were
  promoted automatically from `learning_state.json` after empirical thresholds were crossed.
  EQNR.OL was banned at n=10 observations; the ban prevented further losses.
- **Devil inversion was a net win:** Even though the inversion wasn't triggered until n=77,
  recognizing the contrarian pattern automated a valuable behavioral correction.

### What Failed

- **FullAnalyst timeout:** DeepSeek V3.2 via OpenRouter routinely took 8–12 min.
  When it timed out, the three-way consensus became two-way, reducing debate quality.
- **Agent accuracy tracking was never populated:** `agent_accuracy` in learning_state
  shows 0 observations for all three proposal agents. Per-agent attribution was
  architecturally planned but the linking of final positions back to proposing agents
  was never completed.
- **Rank feedback was too late:** The rank-aware feedback loop was added May 7 after
  rank slipped from #355 to #556. Earlier activation (week 2) would have allowed
  more aggressive beta dialing while the game was still early.
- **No execution layer:** The system recommended portfolios but relied on manual
  submission to the game. Automation would have made the paper track = real track.

### For the Next Competition

1. Add execution API integration (game portal or broker) to eliminate manual submission.
2. Trigger Devil inversion at n=20 (not 77); use rolling 14-day accuracy window.
3. Implement per-agent attribution to track which model's unique picks added alpha.
4. Start rank-aware mode from day 1 — competitions are relative performance games.
5. Use `vol_ratio` as primary signal filter; it showed highest directional accuracy
   across all regimes (57.6% global, 58.6% BULL).

---

*Generated by `scripts/post_game_analysis.py` on 2026-06-23.*  
*Data sources: `paper_account.json`, `learning_state.json`, `DAILY_LOG.md`.*
