# AI Self-Critique Report

Generated: 2026-06-15
Training days analyzed: 58
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
- 'at_52w_high' rationale is working: +0.9% avg, 57% hit rate
- Conviction sizing is working: Tier 1 +0.9% > Tier 3 -0.1%

## Systematic Biases / Errors ⚠️
- 'non_us_differentiator' rationale is weak: +0.0% avg, 36% hit rate
- Alpha hit rate is low: 52%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 286 | +0.87% | 55% |
| high_sharpe | 172 | +0.73% | 51% |
| breakout | 111 | +1.31% | 55% |
| consensus | 208 | +0.67% | 52% |
| catalyst | 42 | +0.62% | 50% |
| diversifier | 21 | -0.19% | 52% |
| non_us_differentiator | 36 | +0.03% | 36% |
| overbought | 184 | +0.67% | 53% |
| at_52w_high | 217 | +0.94% | 57% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 125 | +0.91% |
| Tier 2 (medium conviction) | 12-18% | 135 | +1.04% |
| Tier 3 (low conviction) | 5-10% | 31 | -0.06% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 4

## Action Items for the AI
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
