# AI Self-Critique Report

Generated: 2026-03-29
Training days analyzed: 9
Days until live mode: 8

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
- Conviction sizing is working: Tier 1 +0.3% > Tier 3 -0.4%
- Strategy is producing alpha 78% of days.

## Systematic Biases / Errors ⚠️
- 'non_us_differentiator' rationale is weak: -1.7% avg, 14% hit rate

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 27 | +0.22% | 44% |
| high_sharpe | 26 | +0.23% | 42% |
| breakout | 5 | +0.40% | 60% |
| consensus | 21 | +0.52% | 48% |
| catalyst | 2 | +1.30% | 50% |
| diversifier | 2 | +0.63% | 100% |
| non_us_differentiator | 7 | -1.66% | 14% |
| overbought | 15 | +0.57% | 53% |
| at_52w_high | 19 | +1.17% | 53% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 16 | +0.34% |
| Tier 2 (medium conviction) | 12-18% | 20 | -0.02% |
| Tier 3 (low conviction) | 5-10% | 6 | -0.42% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 2
- Recurring losers tracked: 0

## Action Items for the AI
- No strong structured bias detected yet. Keep monitoring before changing strategy.
