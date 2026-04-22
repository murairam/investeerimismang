# AI Self-Critique Report

Generated: 2026-04-22
Training days analyzed: 28
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
- 'breakout' rationale is working: +0.5% avg, 60% hit rate
- 'overbought' rationale is working: +0.6% avg, 59% hit rate
- 'at_52w_high' rationale is working: +0.7% avg, 61% hit rate
- Conviction sizing is working: Tier 1 +0.4% > Tier 3 -0.7%

## Systematic Biases / Errors ⚠️
- 'catalyst' rationale is weak: -0.5% avg, 40% hit rate
- 'diversifier' rationale is weak: -0.4% avg, 40% hit rate
- 'non_us_differentiator' rationale is weak: -0.3% avg, 27% hit rate
- Alpha hit rate is low: 50%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 119 | +0.36% | 54% |
| high_sharpe | 98 | +0.41% | 52% |
| breakout | 20 | +0.51% | 60% |
| consensus | 93 | +0.32% | 52% |
| catalyst | 20 | -0.47% | 40% |
| diversifier | 5 | -0.42% | 40% |
| non_us_differentiator | 37 | -0.31% | 27% |
| overbought | 58 | +0.59% | 59% |
| at_52w_high | 87 | +0.67% | 61% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 56 | +0.44% |
| Tier 2 (medium conviction) | 12-18% | 67 | +0.33% |
| Tier 3 (low conviction) | 5-10% | 11 | -0.70% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 3

## Action Items for the AI
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 27% over 37 observations (threshold: 30%).
- Avoid overusing catalyst rationales until their hit rate recovers above 40%.
