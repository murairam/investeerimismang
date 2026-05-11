# AI Self-Critique Report

Generated: 2026-05-11
Training days analyzed: 42
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
- 'breakout' rationale is working: +1.3% avg, 57% hit rate
- 'overbought' rationale is working: +1.0% avg, 55% hit rate
- 'at_52w_high' rationale is working: +1.1% avg, 59% hit rate
- Conviction sizing is working: Tier 1 +0.6% > Tier 3 +0.1%

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.5% avg, 47% hit rate
- 'non_us_differentiator' rationale is weak: -0.2% avg, 28% hit rate
- Alpha hit rate is low: 57%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 193 | +0.74% | 53% |
| high_sharpe | 168 | +0.80% | 51% |
| breakout | 61 | +1.25% | 57% |
| consensus | 136 | +0.68% | 51% |
| catalyst | 34 | +0.88% | 50% |
| diversifier | 15 | -0.53% | 47% |
| non_us_differentiator | 39 | -0.22% | 28% |
| overbought | 123 | +0.97% | 55% |
| at_52w_high | 151 | +1.05% | 59% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 87 | +0.62% |
| Tier 2 (medium conviction) | 12-18% | 96 | +0.87% |
| Tier 3 (low conviction) | 5-10% | 25 | +0.11% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 5

## Action Items for the AI
- BAN EQNR.OL: hit rate 20% over 10 observations — do not propose.
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
