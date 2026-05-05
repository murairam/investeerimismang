# AI Self-Critique Report

Generated: 2026-05-05
Training days analyzed: 38
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
- 'breakout' rationale is working: +1.5% avg, 57% hit rate
- 'overbought' rationale is working: +1.1% avg, 56% hit rate
- 'at_52w_high' rationale is working: +1.1% avg, 59% hit rate
- Conviction sizing is working: Tier 1 +0.6% > Tier 3 -0.0%

## Systematic Biases / Errors ⚠️
- 'non_us_differentiator' rationale is weak: -0.2% avg, 28% hit rate
- Alpha hit rate is low: 58%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 174 | +0.79% | 53% |
| high_sharpe | 152 | +0.86% | 52% |
| breakout | 51 | +1.46% | 57% |
| consensus | 123 | +0.66% | 51% |
| catalyst | 31 | +0.99% | 48% |
| diversifier | 11 | -0.28% | 45% |
| non_us_differentiator | 39 | -0.22% | 28% |
| overbought | 106 | +1.14% | 56% |
| at_52w_high | 134 | +1.11% | 59% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 77 | +0.63% |
| Tier 2 (medium conviction) | 12-18% | 91 | +0.94% |
| Tier 3 (low conviction) | 5-10% | 21 | -0.01% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 4

## Action Items for the AI
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
