# AI Self-Critique Report

Generated: 2026-04-07
Training days analyzed: 17
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
- 'catalyst' rationale is working: +0.4% avg, 56% hit rate
- Conviction sizing is working: Tier 1 +0.1% > Tier 3 -0.7%

## Systematic Biases / Errors ⚠️
- 'high_sharpe' rationale is weak: -0.2% avg, 38% hit rate
- 'consensus' rationale is weak: -0.1% avg, 40% hit rate
- 'non_us_differentiator' rationale is weak: -0.4% avg, 21% hit rate
- Alpha hit rate is low: 47%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 72 | -0.06% | 40% |
| high_sharpe | 64 | -0.16% | 38% |
| breakout | 11 | +0.01% | 45% |
| consensus | 58 | -0.06% | 40% |
| catalyst | 9 | +0.43% | 56% |
| diversifier | 4 | -0.40% | 50% |
| non_us_differentiator | 29 | -0.44% | 21% |
| overbought | 36 | -0.21% | 44% |
| at_52w_high | 51 | +0.20% | 47% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 35 | +0.11% |
| Tier 2 (medium conviction) | 12-18% | 41 | -0.10% |
| Tier 3 (low conviction) | 5-10% | 11 | -0.70% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 2
- Recurring losers tracked: 3

## Action Items for the AI
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 21% over 29 observations (threshold: 30%).
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
- Avoid overusing consensus rationales until their hit rate recovers above 40%.
