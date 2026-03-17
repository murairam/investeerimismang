# AI Self-Critique Report

Generated: 2026-03-17
Training days analyzed: 1
Days until live mode: 20

## Meta-Learning Question
**Is the AI's reasoning accurate, or just lucky/unlucky?**

This report evaluates whether the AI's stated rationales (e.g., 'strong momentum', 'breakout') actually correlate with strong performance. If not, the AI needs to adjust its analysis framework.

## What's Working ✅
- ✅ Strategy is producing alpha 100% of days (target: >60%)

## Systematic Biases / Errors ⚠️
- ⚠️ Conviction sizing is INVERTED: Tier 1 (20-25%) averaged -0.6%, but Tier 3 (5-10%) averaged +3.7%. Lower conviction beats higher!

## Rationale Performance Breakdown
| Rationale Type | Observations | Avg Return | Hit Rate |
|---|---:|---:|---:|

## Conviction Sizing Accuracy
| Tier | Weight Range | Observations | Avg Return |
|---|---|---:|---:|
| Tier 1 (high conviction) | 20-25% | 1 | -0.55% |
| Tier 2 (medium conviction) | 12-18% | 1 | +2.78% |
| Tier 3 (low conviction) | 5-10% | 1 | +3.66% |

## Action Items for the AI
- Re-calibrate conviction: If low-conviction picks are winning, increase their weights. If high-conviction picks are losing, reduce tier 1 sizing or improve stock selection.

## How This Improves the AI
This report is automatically fed into the AI's system prompt on each run, so it learns to:
- Trust signals that have proven accurate (e.g., 'high Sharpe' if it's working)
- De-emphasize signals that haven't worked (e.g., 'recovery' if it keeps losing)
- Adjust conviction sizing based on actual tier performance
- Recognize when it's overconfident or underconfident
