# AI Self-Critique Report

Generated: 2026-06-01
Training days analyzed: 55
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
- 'breakout' rationale is working: +1.4% avg, 58% hit rate
- 'at_52w_high' rationale is working: +1.1% avg, 58% hit rate
- Conviction sizing is working: Tier 1 +0.9% > Tier 3 +0.2%

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.4% avg, 50% hit rate
- 'non_us_differentiator' rationale is weak: -0.3% avg, 31% hit rate
- Alpha hit rate is low: 53%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 260 | +0.91% | 55% |
| high_sharpe | 193 | +0.71% | 50% |
| breakout | 98 | +1.35% | 58% |
| consensus | 192 | +0.79% | 53% |
| catalyst | 39 | +0.84% | 51% |
| diversifier | 18 | -0.36% | 50% |
| non_us_differentiator | 42 | -0.25% | 31% |
| overbought | 168 | +0.81% | 55% |
| at_52w_high | 199 | +1.07% | 58% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 116 | +0.89% |
| Tier 2 (medium conviction) | 12-18% | 126 | +0.99% |
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
