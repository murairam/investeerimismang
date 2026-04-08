# AI Self-Critique Report

Generated: 2026-04-08
Training days analyzed: 18
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
- 'catalyst' rationale is working: +0.4% avg, 60% hit rate
- Conviction sizing is working: Tier 1 +0.0% > Tier 3 -0.7%

## Systematic Biases / Errors ⚠️
- 'momentum' rationale is weak: -0.1% avg, 39% hit rate
- 'high_sharpe' rationale is weak: -0.2% avg, 37% hit rate
- 'consensus' rationale is weak: -0.1% avg, 37% hit rate
- 'non_us_differentiator' rationale is weak: -0.5% avg, 22% hit rate
- Alpha hit rate is low: 44%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 77 | -0.13% | 39% |
| high_sharpe | 67 | -0.19% | 37% |
| breakout | 11 | +0.01% | 45% |
| consensus | 62 | -0.15% | 37% |
| catalyst | 10 | +0.39% | 60% |
| diversifier | 4 | -0.40% | 50% |
| non_us_differentiator | 32 | -0.49% | 22% |
| overbought | 38 | -0.24% | 45% |
| at_52w_high | 54 | +0.14% | 46% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 38 | +0.02% |
| Tier 2 (medium conviction) | 12-18% | 43 | -0.16% |
| Tier 3 (low conviction) | 5-10% | 11 | -0.70% |

## Structured Learning State
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Validated winners tracked: 2
- Recurring losers tracked: 3

## Action Items for the AI
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 22% over 32 observations (threshold: 30%).
- Avoid overusing momentum rationales until their hit rate recovers above 40%.
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
- Avoid overusing consensus rationales until their hit rate recovers above 40%.
