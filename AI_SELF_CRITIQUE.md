# AI Self-Critique Report

Generated: 2026-04-06
Training days analyzed: 16
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
- 'catalyst' rationale is working: +0.5% avg, 62% hit rate
- Conviction sizing is working: Tier 1 +0.2% > Tier 3 -0.8%

## Systematic Biases / Errors ⚠️
- 'high_sharpe' rationale is weak: -0.2% avg, 39% hit rate
- 'non_us_differentiator' rationale is weak: -0.5% avg, 19% hit rate
- Alpha hit rate is low: 50%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 66 | -0.04% | 45% |
| high_sharpe | 59 | -0.16% | 39% |
| breakout | 10 | +0.05% | 50% |
| consensus | 52 | -0.03% | 44% |
| catalyst | 8 | +0.53% | 62% |
| diversifier | 4 | -0.40% | 50% |
| non_us_differentiator | 26 | -0.49% | 19% |
| overbought | 35 | -0.24% | 43% |
| at_52w_high | 49 | +0.22% | 49% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 33 | +0.15% |
| Tier 2 (medium conviction) | 12-18% | 38 | -0.08% |
| Tier 3 (low conviction) | 5-10% | 10 | -0.84% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 4
- Recurring losers tracked: 3

## Action Items for the AI
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 19% over 26 observations (threshold: 30%).
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
