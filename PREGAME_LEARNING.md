# Pre-Game Learning Report

Generated: 2026-04-14
Target go-live date: 2026-04-06
Days remaining: 0

## Scoreboard
- Training days with measurable alpha: 22
- Win days (alpha > 0): 9
- Loss days (alpha < 0): 13
- Average daily alpha: -0.39%
- Paper account equity: €10,423.00 (from €10,000.00, return +4.23%)
- Max drawdown (paper): 0.00%
- Average turnover: 0.00%

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Latest day is verified against the actual game portfolio.

## Best and worst day
- Best alpha day: 2026-03-23 (+1.42%)
- Worst alpha day: 2026-04-07 (-3.42%)

## Structured learning state
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Confidence notes: 5

## Ticker lessons
| Ticker | Bucket | Obs | Avg 1d return | Hit rate |
|---|---|---:|---:|---:|
| XOM | winner | 8 | +1.50% | 75% |
| STX | winner | 16 | +1.03% | 75% |
| APA | winner | 14 | +1.03% | 71% |
| EQNR.OL | loser | 10 | -1.56% | 20% |
| DOW | loser | 8 | -0.71% | 50% |
| VWS.CO | loser | 12 | -0.20% | 33% |

## Action plan until April 6
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 27% over 37 observations (threshold: 30%).

## Daily routine
- Run: `python main.py`
- Refresh report: `python scripts/pregame_review.py`
- Review `learning_state.json` when new hard rules appear.
