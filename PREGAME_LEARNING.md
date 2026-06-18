# Pre-Game Learning Report

Generated: 2026-06-18
Target go-live date: 2026-04-06
Days remaining: 0

## Scoreboard
- Training days with measurable alpha: 58
- Win days (alpha > 0): 28
- Loss days (alpha < 0): 30
- Average daily alpha: +0.12%
- Paper account equity: €14,443.70 (from €10,000.00, return +44.44%)
- Max drawdown (paper): 11.46%
- Average turnover: 4.18%

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Latest day is still experimental / unverified.

## Best and worst day
- Best alpha day: 2026-05-29 (+11.42%)
- Worst alpha day: 2026-06-05 (-4.57%)

## Structured learning state
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Confidence notes: 5

## Ticker lessons
| Ticker | Bucket | Obs | Avg 1d return | Hit rate |
|---|---|---:|---:|---:|
| DELL | winner | 14 | +4.96% | 57% |
| CSCO | winner | 10 | +2.69% | 60% |
| MPWR | winner | 8 | +2.65% | 100% |
| NOKIA.HE | winner | 8 | +2.64% | 75% |
| AMD | winner | 22 | +2.58% | 73% |
| GEV | loser | 8 | -1.21% | 25% |
| FSLR | loser | 12 | -0.83% | 50% |
| DOW | loser | 8 | -0.71% | 50% |
| KLAC | loser | 8 | -0.44% | 50% |
| VWS.CO | loser | 10 | -0.25% | 20% |

## Action plan until April 6
- BAN VWS.CO: hit rate 20% over 10 observations — do not propose.
- Avoid overusing non_us_differentiator rationales until their hit rate recovers above 40%.

## Daily routine
- Run: `python main.py`
- Refresh report: `python scripts/pregame_review.py`
- Review `learning_state.json` when new hard rules appear.
