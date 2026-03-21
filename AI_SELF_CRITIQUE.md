# AI Self-Critique Report

Generated: 2026-03-21
Training days analyzed: 5
Days until live mode: 16

## Meta-Learning Question
**Is the AI's reasoning accurate, or just lucky/unlucky?**

This report evaluates whether the AI's stated rationales and conviction levels correlate with outcomes.

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Minimum rationale observations for bias claims: 5
- Latest day status: experimental / unverified

## What's Working ✅
- Strategy is producing alpha 60% of days.

## Systematic Biases / Errors ⚠️
- 'momentum' rationale is weak: -0.8% avg, 20% hit rate
- 'high_sharpe' rationale is weak: -0.8% avg, 20% hit rate

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 5 | -0.79% | 20% |
| high_sharpe | 5 | -0.79% | 20% |
| breakout | 1 | -0.93% | 0% |
| consensus | 4 | -0.81% | 25% |
| non_us_differentiator | 3 | -1.94% | 0% |
| overbought | 3 | +0.36% | 33% |
| at_52w_high | 4 | +0.04% | 25% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 4 | -1.70% |
| Tier 2 (medium conviction) | 12-18% | 5 | -0.11% |
| Tier 3 (low conviction) | 5-10% | 2 | -1.72% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 0
- Recurring losers tracked: 0

## Action Items for the AI
- Avoid overusing momentum rationales until their hit rate recovers above 40%.
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
