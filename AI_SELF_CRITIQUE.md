# AI Self-Critique Report

Generated: 2026-05-29
Training days analyzed: 54
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
- 'breakout' rationale is working: +1.0% avg, 57% hit rate
- 'at_52w_high' rationale is working: +0.9% avg, 58% hit rate

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.4% avg, 47% hit rate
- 'non_us_differentiator' rationale is weak: -0.3% avg, 31% hit rate
- Alpha hit rate is low: 52%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 255 | +0.74% | 55% |
| high_sharpe | 193 | +0.71% | 50% |
| breakout | 95 | +0.99% | 57% |
| consensus | 189 | +0.63% | 52% |
| catalyst | 39 | +0.84% | 51% |
| diversifier | 17 | -0.45% | 47% |
| non_us_differentiator | 42 | -0.25% | 31% |
| overbought | 167 | +0.81% | 54% |
| at_52w_high | 196 | +0.89% | 58% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 114 | +0.61% |
| Tier 2 (medium conviction) | 12-18% | 123 | +0.88% |
| Tier 3 (low conviction) | 5-10% | 33 | +0.19% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 5

## Action Items for the AI
- BAN EQNR.OL: hit rate 20% over 10 observations — do not propose.
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
