# AI Self-Critique Report

Generated: 2026-03-24
Training days analyzed: 8
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
- Not enough structured history yet to identify strong patterns.

## Systematic Biases / Errors ⚠️
- 'momentum' rationale is weak: +0.1% avg, 38% hit rate
- 'high_sharpe' rationale is weak: +0.1% avg, 38% hit rate
- 'non_us_differentiator' rationale is weak: -1.9% avg, 0% hit rate
- 'overbought' rationale is weak: +0.3% avg, 29% hit rate
- Alpha hit rate is low: 50%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 13 | +0.13% | 38% |
| high_sharpe | 13 | +0.13% | 38% |
| breakout | 2 | +0.92% | 50% |
| consensus | 12 | +0.20% | 42% |
| non_us_differentiator | 6 | -1.94% | 0% |
| overbought | 7 | +0.28% | 29% |
| at_52w_high | 11 | +0.90% | 45% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 8 | -1.18% |
| Tier 2 (medium conviction) | 12-18% | 12 | +0.33% |
| Tier 3 (low conviction) | 5-10% | 3 | +0.04% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 2
- Recurring losers tracked: 4

## Action Items for the AI
- Avoid overusing momentum rationales until their hit rate recovers above 40%.
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
