# AI Self-Critique Report

Generated: 2026-03-30
Training days analyzed: 10
Days until live mode: 7

## Meta-Learning Question
**Is the AI's reasoning accurate, or just lucky/unlucky?**

This report evaluates whether the AI's stated rationales and conviction levels correlate with outcomes.

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Minimum rationale observations for bias claims: 5
- Latest day status: experimental / unverified

## What's Working ✅
- 'breakout' rationale is working: +0.4% avg, 60% hit rate
- 'consensus' rationale is working: +0.7% avg, 58% hit rate
- 'overbought' rationale is working: +0.8% avg, 63% hit rate
- 'at_52w_high' rationale is working: +1.3% avg, 64% hit rate
- Conviction sizing is working: Tier 1 +0.3% > Tier 3 -0.4%
- Strategy is producing alpha 80% of days.

## Systematic Biases / Errors ⚠️
- 'non_us_differentiator' rationale is weak: -1.7% avg, 14% hit rate

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 33 | +0.48% | 55% |
| high_sharpe | 32 | +0.50% | 53% |
| breakout | 5 | +0.40% | 60% |
| consensus | 26 | +0.71% | 58% |
| catalyst | 4 | +1.42% | 75% |
| diversifier | 2 | +0.63% | 100% |
| non_us_differentiator | 7 | -1.66% | 14% |
| overbought | 19 | +0.79% | 63% |
| at_52w_high | 25 | +1.29% | 64% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 17 | +0.34% |
| Tier 2 (medium conviction) | 12-18% | 25 | +0.37% |
| Tier 3 (low conviction) | 5-10% | 6 | -0.42% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 3
- Recurring losers tracked: 0

## Action Items for the AI
- No strong structured bias detected yet. Keep monitoring before changing strategy.
