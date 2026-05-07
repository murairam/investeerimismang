# Pre-Game Learning Report

Generated: 2026-05-07
Target go-live date: 2026-04-06
Days remaining: 0

## Scoreboard
- Training days with measurable alpha: 40
- Win days (alpha > 0): 23
- Loss days (alpha < 0): 17
- Average daily alpha: +0.09%
- Paper account equity: €13,461.00 (from €10,000.00, return +34.61%)
- Max drawdown (paper): 3.81%
- Average turnover: 1.60%

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Latest day is verified against the actual game portfolio.

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
| INTC | winner | 24 | +3.60% | 67% |
| AMD | winner | 20 | +3.14% | 80% |
| MPWR | winner | 8 | +2.65% | 100% |
| NOKIA.HE | winner | 8 | +2.64% | 75% |
| ON | winner | 22 | +2.44% | 82% |
| EQNR.OL | loser | 10 | -1.56% | 20% |
| GEV | loser | 8 | -1.21% | 25% |
| DOW | loser | 8 | -0.71% | 50% |
| VWS.CO | loser | 12 | -0.20% | 33% |
| MU | loser | 8 | -0.01% | 25% |

## Action plan until April 6
- BAN EQNR.OL: hit rate 20% over 10 observations — do not propose.
- Avoid overusing diversifier rationales until their hit rate recovers above 40%.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.

## Daily routine
- Run: `python main.py`
- Refresh report: `python scripts/pregame_review.py`
- Review `learning_state.json` when new hard rules appear.
