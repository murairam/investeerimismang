# AI Self-Critique Report

Generated: 2026-05-04
Training days analyzed: 37
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
- 'breakout' rationale is working: +1.4% avg, 55% hit rate
- 'overbought' rationale is working: +1.2% avg, 55% hit rate
- 'at_52w_high' rationale is working: +1.1% avg, 59% hit rate
- Conviction sizing is working: Tier 1 +0.6% > Tier 3 -0.1%

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.4% avg, 40% hit rate
- 'non_us_differentiator' rationale is weak: -0.2% avg, 28% hit rate
- Alpha hit rate is low: 57%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 168 | +0.80% | 53% |
| high_sharpe | 146 | +0.87% | 51% |
| breakout | 49 | +1.42% | 55% |
| consensus | 120 | +0.68% | 51% |
| catalyst | 29 | +0.88% | 45% |
| diversifier | 10 | -0.39% | 40% |
| non_us_differentiator | 39 | -0.22% | 28% |
| overbought | 100 | +1.17% | 55% |
| at_52w_high | 129 | +1.13% | 59% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 74 | +0.62% |
| Tier 2 (medium conviction) | 12-18% | 89 | +0.97% |
| Tier 3 (low conviction) | 5-10% | 20 | -0.10% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 4

## Action Items for the AI
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
