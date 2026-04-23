# AI Self-Critique Report

Generated: 2026-04-23
Training days analyzed: 29
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
- 'breakout' rationale is working: +0.7% avg, 59% hit rate
- 'overbought' rationale is working: +0.8% avg, 59% hit rate
- 'at_52w_high' rationale is working: +0.8% avg, 61% hit rate
- Conviction sizing is working: Tier 1 +0.5% > Tier 3 -0.7%

## Systematic Biases / Errors ⚠️
- 'catalyst' rationale is weak: -0.5% avg, 40% hit rate
- 'diversifier' rationale is weak: -0.4% avg, 40% hit rate
- 'non_us_differentiator' rationale is weak: -0.3% avg, 27% hit rate
- Alpha hit rate is low: 52%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 124 | +0.45% | 54% |
| high_sharpe | 103 | +0.53% | 52% |
| breakout | 22 | +0.66% | 59% |
| consensus | 95 | +0.43% | 53% |
| catalyst | 20 | -0.47% | 40% |
| diversifier | 5 | -0.42% | 40% |
| non_us_differentiator | 37 | -0.31% | 27% |
| overbought | 63 | +0.75% | 59% |
| at_52w_high | 92 | +0.78% | 61% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 57 | +0.45% |
| Tier 2 (medium conviction) | 12-18% | 70 | +0.50% |
| Tier 3 (low conviction) | 5-10% | 12 | -0.69% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 3

## Action Items for the AI
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 27% over 37 observations (threshold: 30%).
- Avoid overusing catalyst rationales until their hit rate recovers above 40%.
