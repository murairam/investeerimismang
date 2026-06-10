# AI Self-Critique Report

Generated: 2026-06-10
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
- 'at_52w_high' rationale is working: +1.0% avg, 56% hit rate
- Conviction sizing is working: Tier 1 +0.9% > Tier 3 -0.2%

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.6% avg, 47% hit rate
- 'non_us_differentiator' rationale is weak: +0.0% avg, 36% hit rate
- Alpha hit rate is low: 53%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 287 | +0.83% | 53% |
| high_sharpe | 184 | +0.79% | 51% |
| breakout | 109 | +1.24% | 54% |
| consensus | 209 | +0.68% | 51% |
| catalyst | 43 | +0.63% | 49% |
| diversifier | 19 | -0.58% | 47% |
| non_us_differentiator | 36 | +0.03% | 36% |
| overbought | 185 | +0.67% | 53% |
| at_52w_high | 220 | +0.95% | 56% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 126 | +0.95% |
| Tier 2 (medium conviction) | 12-18% | 133 | +0.96% |
| Tier 3 (low conviction) | 5-10% | 33 | -0.19% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 4

## Action Items for the AI
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
