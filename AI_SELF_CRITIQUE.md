# AI Self-Critique Report

Generated: 2026-05-15
Training days analyzed: 46
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
- 'at_52w_high' rationale is working: +0.9% avg, 56% hit rate
- Conviction sizing is working: Tier 1 +0.5% > Tier 3 +0.0%

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.5% avg, 44% hit rate
- 'non_us_differentiator' rationale is weak: -0.2% avg, 28% hit rate
- Alpha hit rate is low: 54%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 214 | +0.71% | 51% |
| high_sharpe | 188 | +0.75% | 49% |
| breakout | 74 | +1.03% | 51% |
| consensus | 156 | +0.70% | 50% |
| catalyst | 36 | +0.80% | 47% |
| diversifier | 16 | -0.50% | 44% |
| non_us_differentiator | 39 | -0.22% | 28% |
| overbought | 142 | +0.78% | 51% |
| at_52w_high | 167 | +0.90% | 56% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 93 | +0.54% |
| Tier 2 (medium conviction) | 12-18% | 110 | +0.88% |
| Tier 3 (low conviction) | 5-10% | 26 | +0.00% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 5

## Action Items for the AI
- BAN EQNR.OL: hit rate 20% over 10 observations — do not propose.
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
