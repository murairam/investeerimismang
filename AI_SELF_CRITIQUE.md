# AI Self-Critique Report

Generated: 2026-04-09
Training days analyzed: 19
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
- 'catalyst' rationale is working: +0.9% avg, 60% hit rate
- Conviction sizing is working: Tier 1 -0.0% > Tier 3 -0.7%

## Systematic Biases / Errors ⚠️
- 'high_sharpe' rationale is weak: -0.2% avg, 39% hit rate
- 'non_us_differentiator' rationale is weak: -0.5% avg, 24% hit rate
- Alpha hit rate is low: 42%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 82 | +0.04% | 44% |
| high_sharpe | 70 | -0.21% | 39% |
| breakout | 11 | +0.01% | 45% |
| consensus | 67 | -0.00% | 43% |
| catalyst | 10 | +0.85% | 60% |
| diversifier | 4 | -0.40% | 50% |
| non_us_differentiator | 34 | -0.52% | 24% |
| overbought | 39 | -0.01% | 49% |
| at_52w_high | 57 | +0.14% | 47% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 41 | -0.03% |
| Tier 2 (medium conviction) | 12-18% | 45 | +0.19% |
| Tier 3 (low conviction) | 5-10% | 11 | -0.70% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 3
- Recurring losers tracked: 3

## Action Items for the AI
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 24% over 34 observations (threshold: 30%).
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
