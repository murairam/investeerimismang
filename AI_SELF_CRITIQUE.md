# AI Self-Critique Report

Generated: 2026-06-19
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
- 'at_52w_high' rationale is working: +0.9% avg, 57% hit rate
- Conviction sizing is working: Tier 1 +1.0% > Tier 3 -0.1%

## Systematic Biases / Errors ⚠️
- 'non_us_differentiator' rationale is weak: +0.0% avg, 34% hit rate
- Alpha hit rate is low: 48%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 295 | +0.90% | 54% |
| high_sharpe | 161 | +0.76% | 49% |
| breakout | 119 | +1.34% | 56% |
| consensus | 207 | +0.82% | 52% |
| catalyst | 41 | +0.55% | 46% |
| diversifier | 21 | -0.00% | 52% |
| non_us_differentiator | 35 | +0.03% | 34% |
| overbought | 177 | +0.73% | 53% |
| at_52w_high | 222 | +0.94% | 57% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 128 | +0.96% |
| Tier 2 (medium conviction) | 12-18% | 137 | +1.06% |
| Tier 3 (low conviction) | 5-10% | 30 | -0.12% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 5

## Action Items for the AI
- BAN VWS.CO: hit rate 20% over 10 observations — do not propose.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
