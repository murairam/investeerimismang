# AI Self-Critique Report

Generated: 2026-04-27
Training days analyzed: 32
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
- 'momentum' rationale is working: +0.8% avg, 55% hit rate
- 'breakout' rationale is working: +2.0% avg, 60% hit rate
- 'overbought' rationale is working: +1.3% avg, 59% hit rate
- 'at_52w_high' rationale is working: +1.2% avg, 62% hit rate
- Conviction sizing is working: Tier 1 +0.8% > Tier 3 -0.6%

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.4% avg, 40% hit rate
- 'non_us_differentiator' rationale is weak: -0.3% avg, 27% hit rate
- Alpha hit rate is low: 56%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 139 | +0.84% | 55% |
| high_sharpe | 118 | +0.98% | 54% |
| breakout | 30 | +1.98% | 60% |
| consensus | 103 | +0.75% | 53% |
| catalyst | 22 | +0.73% | 45% |
| diversifier | 5 | -0.42% | 40% |
| non_us_differentiator | 37 | -0.31% | 27% |
| overbought | 75 | +1.30% | 59% |
| at_52w_high | 107 | +1.24% | 62% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 65 | +0.79% |
| Tier 2 (medium conviction) | 12-18% | 76 | +0.92% |
| Tier 3 (low conviction) | 5-10% | 13 | -0.61% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 3

## Action Items for the AI
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 27% over 37 observations (threshold: 30%).
