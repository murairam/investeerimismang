# AI Self-Critique Report

Generated: 2026-04-01
Training days analyzed: 12
Days until live mode: 5

## Meta-Learning Question
**Is the AI's reasoning accurate, or just lucky/unlucky?**

This report evaluates whether the AI's stated rationales and conviction levels correlate with outcomes.

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Minimum rationale observations for bias claims: 5
- Latest day status: experimental / unverified

## What's Working ✅
- 'catalyst' rationale is working: +0.4% avg, 67% hit rate
- Conviction sizing is working: Tier 1 -0.0% > Tier 3 -1.1%
- Strategy is producing alpha 67% of days.

## Systematic Biases / Errors ⚠️
- 'momentum' rationale is weak: -0.3% avg, 47% hit rate
- 'high_sharpe' rationale is weak: -0.4% avg, 43% hit rate
- 'breakout' rationale is weak: -0.7% avg, 43% hit rate
- 'consensus' rationale is weak: -0.3% avg, 47% hit rate
- 'non_us_differentiator' rationale is weak: -1.3% avg, 31% hit rate
- 'overbought' rationale is weak: -0.3% avg, 50% hit rate

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 45 | -0.33% | 47% |
| high_sharpe | 42 | -0.44% | 43% |
| breakout | 7 | -0.71% | 43% |
| consensus | 38 | -0.32% | 47% |
| catalyst | 6 | +0.42% | 67% |
| diversifier | 3 | -0.23% | 67% |
| non_us_differentiator | 13 | -1.31% | 31% |
| overbought | 28 | -0.30% | 50% |
| at_52w_high | 36 | +0.10% | 53% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 21 | -0.03% |
| Tier 2 (medium conviction) | 12-18% | 31 | -0.30% |
| Tier 3 (low conviction) | 5-10% | 8 | -1.06% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 3
- Recurring losers tracked: 1

## Action Items for the AI
- Avoid overusing momentum rationales until their hit rate recovers above 40%.
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
- Avoid overusing consensus rationales until their hit rate recovers above 40%.
