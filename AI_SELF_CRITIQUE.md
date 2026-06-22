# AI Self-Critique Report

Generated: 2026-06-22
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
- 'momentum' rationale is working: +0.9% avg, 55% hit rate
- 'breakout' rationale is working: +1.3% avg, 59% hit rate
- 'at_52w_high' rationale is working: +1.0% avg, 58% hit rate
- Conviction sizing is working: Tier 1 +0.9% > Tier 3 +0.0%

## Systematic Biases / Errors ⚠️
- 'non_us_differentiator' rationale is weak: -0.1% avg, 28% hit rate
- Alpha hit rate is low: 48%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 295 | +0.92% | 55% |
| high_sharpe | 157 | +0.84% | 50% |
| breakout | 124 | +1.33% | 59% |
| consensus | 203 | +0.87% | 53% |
| catalyst | 41 | +0.53% | 46% |
| diversifier | 21 | -0.00% | 52% |
| non_us_differentiator | 32 | -0.09% | 28% |
| overbought | 173 | +0.80% | 53% |
| at_52w_high | 222 | +0.97% | 58% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 127 | +0.94% |
| Tier 2 (medium conviction) | 12-18% | 138 | +1.10% |
| Tier 3 (low conviction) | 5-10% | 30 | +0.01% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 4

## Action Items for the AI
- BAN VWS.CO: hit rate 20% over 10 observations — do not propose.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
