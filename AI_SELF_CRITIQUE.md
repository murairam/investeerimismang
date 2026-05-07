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
- Latest day status: verified

## What's Working ✅
- 'breakout' rationale is working: +1.2% avg, 56% hit rate
- 'at_52w_high' rationale is working: +1.0% avg, 58% hit rate

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.8% avg, 38% hit rate
- 'non_us_differentiator' rationale is weak: -0.2% avg, 28% hit rate
- Alpha hit rate is low: 57%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 185 | +0.73% | 53% |
| high_sharpe | 163 | +0.79% | 52% |
| breakout | 54 | +1.22% | 56% |
| consensus | 132 | +0.62% | 51% |
| catalyst | 32 | +0.87% | 47% |
| diversifier | 13 | -0.75% | 38% |
| non_us_differentiator | 39 | -0.22% | 28% |
| overbought | 116 | +0.94% | 54% |
| at_52w_high | 144 | +1.03% | 58% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 81 | +0.50% |
| Tier 2 (medium conviction) | 12-18% | 96 | +0.87% |
| Tier 3 (low conviction) | 5-10% | 23 | +0.38% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 5

## Action Items for the AI
- BAN EQNR.OL: hit rate 20% over 10 observations — do not propose.
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
