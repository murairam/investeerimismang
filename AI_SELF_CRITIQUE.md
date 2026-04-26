# AI Self-Critique Report

Generated: 2026-04-24
Training days analyzed: 30
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
- 'momentum' rationale is working: +0.5% avg, 55% hit rate
- 'breakout' rationale is working: +1.0% avg, 60% hit rate
- 'overbought' rationale is working: +0.8% avg, 60% hit rate
- 'at_52w_high' rationale is working: +0.9% avg, 62% hit rate
- Conviction sizing is working: Tier 1 +0.5% > Tier 3 -0.7%

## Systematic Biases / Errors ⚠️
- 'catalyst' rationale is weak: -0.3% avg, 43% hit rate
- 'diversifier' rationale is weak: -0.4% avg, 40% hit rate
- 'non_us_differentiator' rationale is weak: -0.3% avg, 27% hit rate
- Alpha hit rate is low: 53%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 129 | +0.54% | 55% |
| high_sharpe | 108 | +0.63% | 54% |
| breakout | 25 | +1.04% | 60% |
| consensus | 95 | +0.43% | 53% |
| catalyst | 21 | -0.35% | 43% |
| diversifier | 5 | -0.42% | 40% |
| non_us_differentiator | 37 | -0.31% | 27% |
| overbought | 67 | +0.76% | 60% |
| at_52w_high | 97 | +0.88% | 62% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 60 | +0.46% |
| Tier 2 (medium conviction) | 12-18% | 72 | +0.65% |
| Tier 3 (low conviction) | 5-10% | 12 | -0.69% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 3

## Action Items for the AI
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 27% over 37 observations (threshold: 30%).
- Avoid overusing catalyst rationales until their hit rate recovers above 40%.
