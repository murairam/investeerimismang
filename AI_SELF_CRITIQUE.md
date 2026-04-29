# AI Self-Critique Report

Generated: 2026-04-29
Training days analyzed: 34
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
- 'at_52w_high' rationale is working: +1.0% avg, 57% hit rate
- Conviction sizing is working: Tier 1 +0.6% > Tier 3 -0.8%

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -1.0% avg, 29% hit rate
- 'non_us_differentiator' rationale is weak: -0.3% avg, 27% hit rate
- Alpha hit rate is low: 53%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 151 | +0.61% | 52% |
| high_sharpe | 130 | +0.69% | 50% |
| breakout | 36 | +1.33% | 53% |
| consensus | 112 | +0.53% | 50% |
| catalyst | 25 | +0.66% | 44% |
| diversifier | 7 | -1.02% | 29% |
| non_us_differentiator | 37 | -0.31% | 27% |
| overbought | 85 | +0.89% | 53% |
| at_52w_high | 117 | +0.96% | 57% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 70 | +0.61% |
| Tier 2 (medium conviction) | 12-18% | 80 | +0.73% |
| Tier 3 (low conviction) | 5-10% | 16 | -0.83% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 3

## Action Items for the AI
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
