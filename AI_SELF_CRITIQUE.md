# AI Self-Critique Report

Generated: 2026-05-06
Training days analyzed: 39
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
- 'breakout' rationale is working: +1.4% avg, 58% hit rate
- 'overbought' rationale is working: +1.2% avg, 57% hit rate
- 'at_52w_high' rationale is working: +1.2% avg, 60% hit rate

## Systematic Biases / Errors ⚠️
- 'diversifier' rationale is weak: -0.4% avg, 42% hit rate
- 'non_us_differentiator' rationale is weak: -0.2% avg, 28% hit rate
- Alpha hit rate is low: 59%.

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|
| momentum | 180 | +0.87% | 54% |
| high_sharpe | 158 | +0.96% | 53% |
| breakout | 52 | +1.43% | 58% |
| consensus | 128 | +0.78% | 52% |
| catalyst | 31 | +0.99% | 48% |
| diversifier | 12 | -0.38% | 42% |
| non_us_differentiator | 39 | -0.22% | 28% |
| overbought | 111 | +1.18% | 57% |
| at_52w_high | 139 | +1.22% | 60% |

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 79 | +0.61% |
| Tier 2 (medium conviction) | 12-18% | 93 | +1.04% |
| Tier 3 (low conviction) | 5-10% | 23 | +0.38% |

## Structured Learning State
- Active hard rules: 0
- Changed hard rules since yesterday: 0
- Validated winners tracked: 5
- Recurring losers tracked: 4

## Action Items for the AI
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.
