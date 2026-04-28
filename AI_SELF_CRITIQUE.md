# AI Self-Critique Report

Generated: 2026-04-28
Training days analyzed: 33
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
- 'breakout' rationale is working: +1.6% avg, 56% hit rate
- 'overbought' rationale is working: +1.1% avg, 56% hit rate
- 'at_52w_high' rationale is working: +1.1% avg, 59% hit rate
- Conviction sizing is working: Tier 1 +0.7% > Tier 3 -0.6%

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.7% avg, 33% hit rate
- 'non_us_differentiator' rationale is weak: -0.3% avg, 27% hit rate
- Alpha hit rate is low: 55%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 145 | +0.75% | 54% |
| high_sharpe | 124 | +0.86% | 52% |
| breakout | 34 | +1.58% | 56% |
| consensus | 108 | +0.65% | 52% |
| catalyst | 25 | +0.66% | 44% |
| diversifier | 6 | -0.75% | 33% |
| non_us_differentiator | 37 | -0.31% | 27% |
| overbought | 80 | +1.12% | 56% |
| at_52w_high | 113 | +1.10% | 59% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 68 | +0.71% |
| Tier 2 (medium conviction) | 12-18% | 78 | +0.83% |
| Tier 3 (low conviction) | 5-10% | 14 | -0.59% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 3

## Action Items for the AI
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
