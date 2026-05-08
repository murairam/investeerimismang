# AI Self-Critique Report

Generated: 2026-05-08
Training days analyzed: 41
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
- 'breakout' rationale is working: +1.1% avg, 55% hit rate
- 'at_52w_high' rationale is working: +1.0% avg, 58% hit rate

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.6% avg, 43% hit rate
- 'non_us_differentiator' rationale is weak: -0.2% avg, 28% hit rate
- Alpha hit rate is low: 56%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 190 | +0.68% | 53% |
| high_sharpe | 166 | +0.73% | 51% |
| breakout | 58 | +1.07% | 55% |
| consensus | 134 | +0.60% | 51% |
| catalyst | 33 | +0.88% | 48% |
| diversifier | 14 | -0.63% | 43% |
| non_us_differentiator | 39 | -0.22% | 28% |
| overbought | 120 | +0.88% | 54% |
| at_52w_high | 148 | +0.98% | 58% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 84 | +0.47% |
| Tier 2 (medium conviction) | 12-18% | 96 | +0.87% |
| Tier 3 (low conviction) | 5-10% | 25 | +0.11% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 5

## Action Items for the AI
- BAN EQNR.OL: hit rate 20% over 10 observations — do not propose.
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
