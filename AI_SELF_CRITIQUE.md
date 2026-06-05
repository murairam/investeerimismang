# AI Self-Critique Report

Generated: 2026-06-05
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
- 'breakout' rationale is working: +1.3% avg, 56% hit rate
- 'at_52w_high' rationale is working: +1.1% avg, 57% hit rate
- Conviction sizing is working: Tier 1 +1.1% > Tier 3 +0.1%

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.6% avg, 47% hit rate
- 'non_us_differentiator' rationale is weak: -0.3% avg, 31% hit rate
- Alpha hit rate is low: 55%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 280 | +0.97% | 54% |
| high_sharpe | 193 | +0.71% | 50% |
| breakout | 108 | +1.35% | 56% |
| consensus | 208 | +0.85% | 52% |
| catalyst | 41 | +0.79% | 51% |
| diversifier | 19 | -0.58% | 47% |
| non_us_differentiator | 42 | -0.25% | 31% |
| overbought | 183 | +0.87% | 54% |
| at_52w_high | 216 | +1.11% | 57% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 123 | +1.05% |
| Tier 2 (medium conviction) | 12-18% | 133 | +1.06% |
| Tier 3 (low conviction) | 5-10% | 33 | +0.09% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 4

## Action Items for the AI
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
