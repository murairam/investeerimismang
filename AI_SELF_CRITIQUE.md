# AI Self-Critique Report

Generated: 2026-04-02
Training days analyzed: 12
Days until live mode: 4

## Meta-Learning Question
**Is the AI's reasoning accurate, or just lucky/unlucky?**

This report evaluates whether the AI's stated rationales and conviction levels correlate with outcomes.

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Minimum rationale observations for bias claims: 5
- Latest day status: experimental / unverified

## What's Working ✅
- 'catalyst' rationale is working: +0.7% avg, 67% hit rate
- Conviction sizing is working: Tier 1 +0.0% > Tier 3 -1.1%
- Strategy is producing alpha 67% of days.

## Systematic Biases / Errors ⚠️
- 'high_sharpe' rationale is weak: -0.4% avg, 43% hit rate
- 'breakout' rationale is weak: -0.7% avg, 43% hit rate
- 'non_us_differentiator' rationale is weak: -1.3% avg, 31% hit rate

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 45 | -0.27% | 47% |
| high_sharpe | 42 | -0.39% | 43% |
| breakout | 7 | -0.71% | 43% |
| consensus | 38 | -0.26% | 47% |
| catalyst | 6 | +0.69% | 67% |
| diversifier | 3 | -0.23% | 67% |
| non_us_differentiator | 13 | -1.31% | 31% |
| overbought | 28 | -0.27% | 50% |
| at_52w_high | 36 | +0.16% | 53% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 21 | +0.01% |
| Tier 2 (medium conviction) | 12-18% | 31 | -0.24% |
| Tier 3 (low conviction) | 5-10% | 8 | -1.06% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 3
- Recurring losers tracked: 1

## Action Items for the AI
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
