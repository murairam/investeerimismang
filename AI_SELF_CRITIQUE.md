# AI Self-Critique Report

Generated: 2026-04-20
Training days analyzed: 26
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
- 'breakout' rationale is working: +0.5% avg, 56% hit rate
- 'at_52w_high' rationale is working: +0.5% avg, 58% hit rate
- Conviction sizing is working: Tier 1 +0.1% > Tier 3 -0.7%

## Systematic Biases / Errors ⚠️
- 'catalyst' rationale is weak: -0.5% avg, 37% hit rate
- 'diversifier' rationale is weak: -0.4% avg, 40% hit rate
- 'non_us_differentiator' rationale is weak: -0.3% avg, 27% hit rate
- Alpha hit rate is low: 46%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 109 | +0.17% | 50% |
| high_sharpe | 89 | +0.18% | 48% |
| breakout | 18 | +0.54% | 56% |
| consensus | 84 | +0.14% | 48% |
| catalyst | 19 | -0.51% | 37% |
| diversifier | 5 | -0.42% | 40% |
| non_us_differentiator | 37 | -0.31% | 27% |
| overbought | 50 | +0.22% | 54% |
| at_52w_high | 79 | +0.52% | 58% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 49 | +0.07% |
| Tier 2 (medium conviction) | 12-18% | 64 | +0.30% |
| Tier 3 (low conviction) | 5-10% | 11 | -0.70% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 3
- Recurring losers tracked: 3

## Action Items for the AI
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 27% over 37 observations (threshold: 30%).
- Avoid overusing catalyst rationales until their hit rate recovers above 40%.
