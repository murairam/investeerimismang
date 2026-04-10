# AI Self-Critique Report

Generated: 2026-04-10
Training days analyzed: 20
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
- Conviction sizing is working: Tier 1 -0.1% > Tier 3 -0.7%

## Systematic Biases / Errors ⚠️
- 'high_sharpe' rationale is weak: -0.2% avg, 39% hit rate
- 'non_us_differentiator' rationale is weak: -0.5% avg, 25% hit rate
- Alpha hit rate is low: 40%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 87 | +0.02% | 44% |
| high_sharpe | 72 | -0.22% | 39% |
| breakout | 12 | +0.05% | 50% |
| consensus | 72 | -0.02% | 43% |
| catalyst | 13 | +0.47% | 46% |
| diversifier | 4 | -0.40% | 50% |
| non_us_differentiator | 36 | -0.52% | 25% |
| overbought | 40 | -0.04% | 48% |
| at_52w_high | 61 | +0.11% | 48% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 44 | -0.06% |
| Tier 2 (medium conviction) | 12-18% | 47 | +0.18% |
| Tier 3 (low conviction) | 5-10% | 11 | -0.70% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 3
- Recurring losers tracked: 3

## Action Items for the AI
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 25% over 36 observations (threshold: 30%).
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
