# Pre-Game Learning Report

Generated: 2026-03-23
Target go-live date: 2026-04-06
Days remaining: 14

## Scoreboard
- Training days with measurable alpha: 7
- Win days (alpha > 0): 4
- Loss days (alpha < 0): 3
- Average daily alpha: -0.01%
- Paper account equity: €10,059.00 (from €10,000.00, return +0.59%)
- Max drawdown (paper): 1.39%
- Average turnover: 36.36%

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Latest day is still experimental / unverified.

## Best and worst day
- Best alpha day: 2026-03-21 (+0.74%)
- Worst alpha day: 2026-03-19 (-0.89%)

## Structured learning state
- Active hard rules: 3
- Changed hard rules since yesterday: 0
- Confidence notes: 2

## Ticker lessons
| Ticker | Bucket | Obs | Avg 1d return | Hit rate |
|---|---|---:|---:|---:|
| APA | winner | 8 | +1.94% | 75% |
| XOM | winner | 5 | +0.78% | 100% |
| AKRBP.OL | loser | 6 | -4.14% | 0% |
| EQNR.OL | loser | 6 | -0.93% | 0% |
| NESTE.HE | loser | 6 | -0.74% | 0% |

## Action plan until April 6
- RATIONALE CAP: cap any position whose primary thesis is 'momentum' at 15% — hit rate 22% over 9 observations (threshold: 30%).
- RATIONALE CAP: cap any position whose primary thesis is 'high_sharpe' at 15% — hit rate 22% over 9 observations (threshold: 30%).

## Daily routine
- Run: `python main.py`
- Refresh report: `python scripts/pregame_review.py`
- Review `learning_state.json` when new hard rules appear.
