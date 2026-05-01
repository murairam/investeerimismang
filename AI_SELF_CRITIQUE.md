# AI Self-Critique Report

Generated: 2026-05-01
Training days analyzed: 36
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
- 'at_52w_high' rationale is working: +1.1% avg, 58% hit rate
- Conviction sizing is working: Tier 1 +0.6% > Tier 3 -0.8%

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.4% avg, 44% hit rate
- 'non_us_differentiator' rationale is weak: -0.2% avg, 29% hit rate
- Alpha hit rate is low: 56%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 162 | +0.74% | 52% |
| high_sharpe | 140 | +0.81% | 51% |
| breakout | 45 | +1.32% | 53% |
| consensus | 116 | +0.63% | 50% |
| catalyst | 28 | +0.96% | 46% |
| diversifier | 9 | -0.43% | 44% |
| non_us_differentiator | 38 | -0.23% | 29% |
| overbought | 94 | +1.10% | 54% |
| at_52w_high | 124 | +1.05% | 58% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 72 | +0.61% |
| Tier 2 (medium conviction) | 12-18% | 88 | +0.98% |
| Tier 3 (low conviction) | 5-10% | 17 | -0.82% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 4

## Action Items for the AI
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
