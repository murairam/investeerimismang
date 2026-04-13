# AI Self-Critique Report

Generated: 2026-04-13
Training days analyzed: 21
Days until live mode: 0

## Meta-Learning Question
**Is the AI's reasoning accurate, or just lucky/unlucky?**

This report evaluates whether the AI's stated rationales and conviction levels correlate with outcomes.

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Minimum rationale observations for bias claims: 5
- Latest day status: experimental / unverified

## What's Working ✅
- Conviction sizing is working: Tier 1 -0.1% > Tier 3 -0.7%

## Systematic Biases / Errors ⚠️
- 'high_sharpe' rationale is weak: -0.2% avg, 39% hit rate
- 'diversifier' rationale is weak: -0.6% avg, 40% hit rate
- 'non_us_differentiator' rationale is weak: -0.5% avg, 24% hit rate
- Alpha hit rate is low: 38%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 92 | -0.01% | 43% |
| high_sharpe | 77 | -0.25% | 39% |
| breakout | 15 | -0.26% | 40% |
| consensus | 75 | -0.04% | 43% |
| catalyst | 15 | +0.13% | 40% |
| diversifier | 5 | -0.60% | 40% |
| non_us_differentiator | 37 | -0.51% | 24% |
| overbought | 42 | -0.14% | 45% |
| at_52w_high | 66 | +0.06% | 47% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 46 | -0.12% |
| Tier 2 (medium conviction) | 12-18% | 50 | +0.17% |
| Tier 3 (low conviction) | 5-10% | 11 | -0.70% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 3
- Recurring losers tracked: 3

## Action Items for the AI
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 24% over 37 observations (threshold: 30%).
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
