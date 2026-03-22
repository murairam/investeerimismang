# AI Self-Critique Report

Generated: 2026-03-22
Training days analyzed: 6
Days until live mode: 15

## Meta-Learning Question
**Is the AI's reasoning accurate, or just lucky/unlucky?**

This report evaluates whether the AI's stated rationales and conviction levels correlate with outcomes.

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Minimum rationale observations for bias claims: 5
- Latest day status: experimental / unverified

## What's Working ✅
- Strategy is producing alpha 67% of days.

## Systematic Biases / Errors ⚠️
- 'momentum' rationale is weak: -0.8% avg, 22% hit rate
- 'high_sharpe' rationale is weak: -0.8% avg, 22% hit rate
- 'consensus' rationale is weak: -0.8% avg, 25% hit rate
- 'non_us_differentiator' rationale is weak: -1.9% avg, 0% hit rate
- 'overbought' rationale is weak: +0.4% avg, 33% hit rate
- 'at_52w_high' rationale is weak: +0.2% avg, 29% hit rate

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 9 | -0.78% | 22% |
| high_sharpe | 9 | -0.78% | 22% |
| breakout | 2 | +0.92% | 50% |
| consensus | 8 | -0.79% | 25% |
| non_us_differentiator | 6 | -1.94% | 0% |
| overbought | 6 | +0.36% | 33% |
| at_52w_high | 7 | +0.18% | 29% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 6 | -1.36% |
| Tier 2 (medium conviction) | 12-18% | 7 | -0.32% |
| Tier 3 (low conviction) | 5-10% | 2 | -1.72% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 1
- Recurring losers tracked: 3

## Action Items for the AI
- Avoid overusing momentum rationales until their hit rate recovers above 40%.
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
- Avoid overusing consensus rationales until their hit rate recovers above 40%.
