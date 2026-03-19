# Pre-Game Learning Report

Generated: 2026-03-19
Target go-live date: 2026-04-06
Days remaining: 18

## Scoreboard
- Training days with measurable alpha: 3
- Win days (alpha > 0): 3
- Loss days (alpha < 0): 0
- Average daily alpha: +0.25%
- Paper account equity: €9,876.00 (from €10,000.00, return -1.24%)
- Max drawdown (paper): 1.24%
- Average turnover: 100.00%

## Best and worst day
- Best alpha day: 2026-03-18 (+0.59%)
- Worst alpha day: 2026-03-19 (+0.01%)

## Ticker lessons
| Ticker | Obs | Avg 1d return | Hit rate |
|---|---:|---:|---:|
| MAERSK-B.CO | 3 | +2.09% | 67% |
| CVX | 2 | +0.96% | 100% |
| XOM | 2 | +0.83% | 100% |
| FORTUM.HE | 1 | +0.50% | 100% |
| CSCO | 1 | +0.47% | 100% |
| SALM.OL | 1 | -0.33% | 0% |
| DSV.CO | 1 | -0.34% | 0% |
| SAMPO.HE | 1 | -0.54% | 0% |
| DNB.OL | 1 | -0.88% | 0% |
| TELIA.ST | 1 | -0.95% | 0% |

## Action plan until April 6
- Turnover is 100% — target ≤35%. Keep at least 50% of weight in yesterday's holdings. Only replace a position if the new pick's Sharpe_20d is ≥20% higher.
- Core basket — keep these unless Sharpe_20d drops below 0.2: MAERSK-B.CO, CVX, XOM.
- Avoid or underweight these recurring underperformers (max 7% each if held at all): NEE, NOKIA.HE, NHY.OL.

## Daily routine
- Run: `python main.py`
- Refresh report: `python pregame_review.py`
- Record what changed in weights and why before the next run.
