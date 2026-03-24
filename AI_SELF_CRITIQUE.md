# AI Self-Critique Report

Generated: 2026-03-24
Training days analyzed: 5
Days until live mode: 13

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
- 'momentum' rationale is weak: -0.2% avg, 38% hit rate
- 'high_sharpe' rationale is weak: -0.2% avg, 38% hit rate
- 'consensus' rationale is weak: +0.2% avg, 38% hit rate
- 'non_us_differentiator' rationale is weak: -1.9% avg, 0% hit rate
- INVERTED CONVICTION: Tier 1 averaged -1.2% vs Tier 3 -0.8%. Cap large weights.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 16 | -0.17% | 38% |
| high_sharpe | 16 | -0.17% | 38% |
| breakout | 3 | -0.79% | 33% |
| consensus | 13 | +0.19% | 38% |
| catalyst | 1 | -5.60% | 0% |
| diversifier | 1 | +1.25% | 100% |
| non_us_differentiator | 6 | -1.94% | 0% |
| overbought | 8 | +0.94% | 50% |
| at_52w_high | 12 | +1.29% | 50% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 8 | -1.18% |
| Tier 2 (medium conviction) | 12-18% | 13 | +0.31% |
| Tier 3 (low conviction) | 5-10% | 5 | -0.84% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 1
- Recurring losers tracked: 3

## Action Items for the AI
- Cap all positions at 15% until Tier 1 returns exceed Tier 3 returns over recent history.
- Avoid overusing momentum rationales until their hit rate recovers above 40%.
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
- Avoid overusing consensus rationales until their hit rate recovers above 40%.
