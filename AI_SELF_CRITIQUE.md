# AI Self-Critique Report

Generated: 2026-03-31
Training days analyzed: 11
Days until live mode: 6

## Meta-Learning Question
**Is the AI's reasoning accurate, or just lucky/unlucky?**

This report evaluates whether the AI's stated rationales and conviction levels correlate with outcomes.

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Minimum rationale observations for bias claims: 5
- Latest day status: verified

## What's Working ✅
- 'consensus' rationale is working: +0.4% avg, 56% hit rate
- 'catalyst' rationale is working: +1.3% avg, 80% hit rate
- 'at_52w_high' rationale is working: +0.8% avg, 61% hit rate
- Conviction sizing is working: Tier 1 +0.5% > Tier 3 -0.9%
- Strategy is producing alpha 73% of days.

## Systematic Biases / Errors ⚠️
- 'breakout' rationale is weak: -0.5% avg, 50% hit rate
- 'non_us_differentiator' rationale is weak: -0.8% avg, 40% hit rate

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 39 | +0.24% | 54% |
| high_sharpe | 36 | +0.15% | 50% |
| breakout | 6 | -0.51% | 50% |
| consensus | 32 | +0.36% | 56% |
| catalyst | 5 | +1.34% | 80% |
| diversifier | 2 | +0.63% | 100% |
| non_us_differentiator | 10 | -0.76% | 40% |
| overbought | 24 | +0.22% | 58% |
| at_52w_high | 31 | +0.82% | 61% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 19 | +0.51% |
| Tier 2 (medium conviction) | 12-18% | 28 | +0.09% |
| Tier 3 (low conviction) | 5-10% | 7 | -0.93% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 3
- Recurring losers tracked: 1

## Action Items for the AI
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
