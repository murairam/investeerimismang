# AI Self-Critique Report

Generated: 2026-05-19
Training days analyzed: 48
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
- 'at_52w_high' rationale is working: +0.9% avg, 57% hit rate

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.5% avg, 44% hit rate
- 'non_us_differentiator' rationale is weak: -0.2% avg, 30% hit rate
- Alpha hit rate is low: 52%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 224 | +0.68% | 53% |
| high_sharpe | 193 | +0.71% | 50% |
| breakout | 80 | +0.99% | 54% |
| consensus | 164 | +0.64% | 51% |
| catalyst | 36 | +0.80% | 47% |
| diversifier | 16 | -0.50% | 44% |
| non_us_differentiator | 40 | -0.21% | 30% |
| overbought | 149 | +0.82% | 54% |
| at_52w_high | 175 | +0.90% | 57% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 97 | +0.58% |
| Tier 2 (medium conviction) | 12-18% | 114 | +0.79% |
| Tier 3 (low conviction) | 5-10% | 28 | +0.14% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 5

## Action Items for the AI
- BAN EQNR.OL: hit rate 20% over 10 observations — do not propose.
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
