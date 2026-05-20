# Pre-Game Learning Report

Generated: 2026-05-20
Target go-live date: 2026-04-06
Days remaining: 0

## Scoreboard
- Training days with measurable alpha: 49
- Win days (alpha > 0): 26
- Loss days (alpha < 0): 23
- Average daily alpha: -0.00%
- Paper account equity: €13,385.53 (from €10,000.00, return +33.86%)
- Max drawdown (paper): 6.16%
- Average turnover: 6.70%

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Latest day is still experimental / unverified.

## Best and worst day
- Best alpha day: 2026-04-29 (+4.02%)
- Worst alpha day: 2026-04-07 (-3.42%)

## Structured learning state
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Confidence notes: 5

## Ticker lessons
| Ticker | Bucket | Obs | Avg 1d return | Hit rate |
|---|---|---:|---:|---:|
| CSCO | winner | 8 | +3.63% | 75% |
| INTC | winner | 30 | +2.69% | 60% |
| MPWR | winner | 8 | +2.65% | 100% |
| NOKIA.HE | winner | 8 | +2.64% | 75% |
| AMD | winner | 22 | +2.58% | 73% |
| EQNR.OL | loser | 10 | -1.56% | 20% |
| GEV | loser | 8 | -1.21% | 25% |
| DOW | loser | 8 | -0.71% | 50% |
| MU | loser | 20 | -0.38% | 30% |
| VWS.CO | loser | 12 | -0.20% | 33% |

## Action plan until April 6
- BAN EQNR.OL: hit rate 20% over 10 observations — do not propose.
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.

## Daily routine
- Run: `python main.py`
- Refresh report: `python scripts/pregame_review.py`
- Review `learning_state.json` when new hard rules appear.
