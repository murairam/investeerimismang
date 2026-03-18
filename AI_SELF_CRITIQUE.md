# AI Self-Critique Report

Generated: 2026-03-18
Training days analyzed: 2
Days until live mode: 19

## Meta-Learning Question
**Is the AI's reasoning accurate, or just lucky/unlucky?**

This report evaluates whether the AI's stated rationales (e.g., 'strong momentum', 'breakout') actually correlate with strong performance. If not, the AI needs to adjust its analysis framework.

## What's Working ✅
- ✅ Strategy is producing alpha 100% of days (target: >60%)

## Systematic Biases / Errors ⚠️
- None detected yet

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 2 (medium conviction) | 12-18% | 4 | -0.67% |
| Tier 3 (low conviction) | 5-10% | 4 | +1.07% |

## Action Items for the AI
- Continue current strategy. Performance signals are healthy.

## How This Improves the AI
This report is automatically fed into the AI's system prompt on each run, so it learns to:
- Trust signals that have proven accurate (e.g., 'high Sharpe' if it's working)
- De-emphasize signals that haven't worked (e.g., 'recovery' if it keeps losing)
- Adjust conviction sizing based on actual tier performance
- Recognize when it's overconfident or underconfident
