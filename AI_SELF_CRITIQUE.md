# AI Self-Critique Report

Generated: 2026-06-17
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
- 'breakout' rationale is working: +1.2% avg, 55% hit rate
- 'at_52w_high' rationale is working: +0.9% avg, 57% hit rate
- Conviction sizing is working: Tier 1 +0.9% > Tier 3 -0.1%

## Systematic Biases / Errors ⚠️
- 'non_us_differentiator' rationale is weak: +0.0% avg, 36% hit rate
- Alpha hit rate is low: 48%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 297 | +0.78% | 54% |
| high_sharpe | 172 | +0.73% | 51% |
| breakout | 114 | +1.21% | 55% |
| consensus | 210 | +0.66% | 52% |
| catalyst | 43 | +0.60% | 49% |
| diversifier | 21 | -0.19% | 52% |
| non_us_differentiator | 36 | +0.03% | 36% |
| overbought | 184 | +0.67% | 53% |
| at_52w_high | 224 | +0.87% | 57% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 126 | +0.86% |
| Tier 2 (medium conviction) | 12-18% | 140 | +0.89% |
| Tier 3 (low conviction) | 5-10% | 31 | -0.06% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 5

## Action Items for the AI
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
