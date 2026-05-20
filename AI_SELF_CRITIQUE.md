# AI Self-Critique Report

Generated: 2026-05-20
Training days analyzed: 49
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
- Conviction sizing is working: Tier 1 +0.6% > Tier 3 +0.1%

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.5% avg, 44% hit rate
- 'non_us_differentiator' rationale is weak: -0.2% avg, 30% hit rate
- Alpha hit rate is low: 53%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 229 | +0.66% | 53% |
| high_sharpe | 193 | +0.71% | 50% |
| breakout | 82 | +0.94% | 54% |
| consensus | 169 | +0.61% | 51% |
| catalyst | 36 | +0.80% | 47% |
| diversifier | 16 | -0.50% | 44% |
| non_us_differentiator | 40 | -0.21% | 30% |
| overbought | 154 | +0.79% | 54% |
| at_52w_high | 180 | +0.87% | 57% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 100 | +0.57% |
| Tier 2 (medium conviction) | 12-18% | 114 | +0.79% |
| Tier 3 (low conviction) | 5-10% | 30 | +0.05% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 5

## Action Items for the AI
- BAN EQNR.OL: hit rate 20% over 10 observations — do not propose.
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
