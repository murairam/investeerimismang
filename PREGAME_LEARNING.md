# Pre-Game Learning Report

Generated: 2026-03-24
Target go-live date: 2026-04-06
Days remaining: 13

## Scoreboard
- Training days with measurable alpha: 5
- Win days (alpha > 0): 3
- Loss days (alpha < 0): 2
- Average daily alpha: +0.31%
- Paper account equity: €10,202.00 (from €10,000.00, return +2.02%)
- Max drawdown (paper): 1.39%
- Average turnover: 33.33%

## Confidence note
- Evidence status: actionable
- Minimum daily observations for strong conclusions: 5
- Latest day is still experimental / unverified.

## Best and worst day
- Best alpha day: 2026-03-23 (+1.44%)
- Worst alpha day: 2026-03-22 (-0.89%)

## Structured learning state
- Active hard rules: 1
- Changed hard rules since yesterday: 0
- Confidence notes: 3

## Ticker lessons
| Ticker | Bucket | Obs | Avg 1d return | Hit rate |
|---|---|---:|---:|---:|
| APA | winner | 10 | +2.37% | 80% |
| AKRBP.OL | loser | 6 | -4.14% | 0% |
| EQNR.OL | loser | 6 | -0.93% | 0% |
| NESTE.HE | loser | 6 | -0.74% | 0% |

## Action plan until April 6
- Cap all positions at 15% until Tier 1 returns exceed Tier 3 returns over recent history.
- Avoid overusing momentum rationales until their hit rate recovers above 40%.
- Avoid overusing high_sharpe rationales until their hit rate recovers above 40%.

## Daily routine
- Run: `python main.py`
- Refresh report: `python scripts/pregame_review.py`
- Review `learning_state.json` when new hard rules appear.
