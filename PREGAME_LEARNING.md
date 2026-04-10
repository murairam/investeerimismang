# Pre-Game Learning Report

Generated: 2026-04-10
Target go-live date: 2026-04-06
Days remaining: 0

## Scoreboard
- Training days with measurable alpha: 20
- Win days (alpha > 0): 8
- Loss days (alpha < 0): 12
- Average daily alpha: -0.44%
- Paper account equity: €10,000.00 (from €10,000.00, return +0.00%)
- Max drawdown (paper): 0.00%
- Average turnover: 0.00%

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Latest day is still experimental / unverified.

## Best and worst day
- Best alpha day: 2026-03-23 (+1.42%)
- Worst alpha day: 2026-04-07 (-3.42%)

## Structured learning state
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Confidence notes: 4

## Ticker lessons
| Ticker | Bucket | Obs | Avg 1d return | Hit rate |
|---|---|---:|---:|---:|
| XOM | winner | 8 | +1.50% | 75% |
| STX | winner | 12 | +1.17% | 67% |
| APA | winner | 14 | +1.03% | 71% |
| EQNR.OL | loser | 10 | -1.56% | 20% |
| DOW | loser | 8 | -0.71% | 50% |
| VWS.CO | loser | 12 | -0.20% | 33% |

## Action plan until April 6
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 25% over 36 observations (threshold: 30%).
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.

## Daily routine
- Run: `python main.py`
- Refresh report: `python scripts/pregame_review.py`
- Review `learning_state.json` when new hard rules appear.
