# Pre-Game Learning Report

Generated: 2026-04-22
Target go-live date: 2026-04-06
Days remaining: 0

## Scoreboard
- Training days with measurable alpha: 28
- Win days (alpha > 0): 14
- Loss days (alpha < 0): 14
- Average daily alpha: -0.19%
- Paper account equity: €10,883.71 (from €10,000.00, return +8.84%)
- Max drawdown (paper): 2.44%
- Average turnover: 3.72%

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Latest day is still experimental / unverified.

## Best and worst day
- Best alpha day: 2026-04-21 (+3.17%)
- Worst alpha day: 2026-04-07 (-3.42%)

## Structured learning state
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Confidence notes: 5

## Ticker lessons
| Ticker | Bucket | Obs | Avg 1d return | Hit rate |
|---|---|---:|---:|---:|
| ON | winner | 8 | +2.61% | 100% |
| INTC | winner | 8 | +1.54% | 100% |
| XOM | winner | 8 | +1.50% | 75% |
| STX | winner | 22 | +1.32% | 73% |
| AMD | winner | 10 | +1.20% | 80% |
| EQNR.OL | loser | 10 | -1.56% | 20% |
| DOW | loser | 8 | -0.71% | 50% |
| VWS.CO | loser | 12 | -0.20% | 33% |

## Action plan until April 6
- RATIONALE CAP: cap any position whose primary thesis is 'non_us_differentiator' at 15% — hit rate 27% over 37 observations (threshold: 30%).
- Avoid overusing catalyst rationales until their hit rate recovers above 40%.

## Daily routine
- Run: `python main.py`
- Refresh report: `python scripts/pregame_review.py`
- Review `learning_state.json` when new hard rules appear.
