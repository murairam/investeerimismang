# AI Self-Critique Report

Generated: 2026-05-07
Training days analyzed: 40
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
- 'momentum' rationale is working: +0.9% avg, 56% hit rate
- 'breakout' rationale is working: +1.5% avg, 59% hit rate
- 'overbought' rationale is working: +1.2% avg, 59% hit rate
- 'at_52w_high' rationale is working: +1.3% avg, 62% hit rate
- Strategy is producing alpha 60% of days.

## Systematic Biases / Errors ⚠️
- 'non_us_differentiator' rationale is weak: -0.2% avg, 28% hit rate

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 185 | +0.93% | 56% |
| high_sharpe | 163 | +1.02% | 55% |
| breakout | 54 | +1.51% | 59% |
| consensus | 132 | +0.84% | 54% |
| catalyst | 32 | +1.08% | 50% |
| diversifier | 13 | -0.24% | 46% |
| non_us_differentiator | 39 | -0.22% | 28% |
| overbought | 116 | +1.25% | 59% |
| at_52w_high | 144 | +1.28% | 62% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 81 | +0.67% |
| Tier 2 (medium conviction) | 12-18% | 96 | +1.10% |
| Tier 3 (low conviction) | 5-10% | 23 | +0.38% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 4

## Action Items for the AI
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
