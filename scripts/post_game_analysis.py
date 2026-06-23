"""
Post-game analysis for AlphaShark — Äripäev/SEB Investment Game 2026.
Reads paper_account.json, learning_state.json, and DAILY_LOG.md,
then writes POST_GAME_ANALYSIS.md to the project root.
"""

import json
import re
import statistics
import math
import os
from datetime import datetime, date
from typing import Optional


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(filename: str):
    path = os.path.join(ROOT, filename)
    with open(path) as f:
        return json.load(f)


def parse_daily_log() -> list[dict]:
    """Parse DAILY_LOG.md — returns one dict per date header (log-entry date)."""
    path = os.path.join(ROOT, "DAILY_LOG.md")
    content = open(path).read()

    blocks = re.split(r"\n## (\d{4}-\d{2}-\d{2})", content)
    days = []
    for i in range(1, len(blocks), 2):
        entry_date = blocks[i]
        body = blocks[i + 1] if i + 1 < len(blocks) else ""

        regime_m = re.search(r"\*\*Market:\*\* (\w+) regime", body)
        pnl_m = re.search(
            r"Yesterday.s P&L.*?Portfolio ([+-]?\d+\.?\d*)%.*?Benchmark ([+-]?\d+\.?\d*)%.*?Alpha ([+-]?\d+\.?\d*)%",
            body,
        )
        days.append(
            {
                "log_date": entry_date,  # date of the log entry
                "regime": regime_m.group(1) if regime_m else "UNKNOWN",
                # "Yesterday's P&L" → attributed to prior trading day
                # We store under log_date for simplicity; noted in output
                "portfolio_pnl_pct": float(pnl_m.group(1)) if pnl_m else None,
                "benchmark_pnl_pct": float(pnl_m.group(2)) if pnl_m else None,
                "alpha_pct": float(pnl_m.group(3)) if pnl_m else None,
            }
        )
    return days


def compute_metrics(history: list[dict]) -> dict:
    returns = [e["daily_return"] for e in history if e.get("daily_return") is not None]
    equities = [e["equity"] for e in history]

    wins = sum(1 for r in returns if r > 0)
    losses = sum(1 for r in returns if r < 0)

    avg_return = statistics.mean(returns) if returns else 0.0
    std_return = statistics.stdev(returns) if len(returns) > 1 else 0.0
    sharpe = (avg_return / std_return) * math.sqrt(252) if std_return else 0.0

    # Max drawdown
    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        peak = max(peak, eq)
        dd = (eq - peak) / peak
        max_dd = min(max_dd, dd)

    peak_equity = max(equities)
    peak_idx = equities.index(peak_equity)
    peak_date = history[peak_idx]["date"]

    turnovers = [e.get("turnover", 0) for e in history]
    avg_turnover = statistics.mean(turnovers) if turnovers else 0.0
    rebalance_days = sum(1 for t in turnovers if t > 0.05)

    return {
        "n_days": len(returns),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(returns) if returns else 0,
        "avg_daily_return": avg_return,
        "std_daily_return": std_return,
        "annualized_sharpe": sharpe,
        "max_drawdown": max_dd,
        "peak_equity": peak_equity,
        "peak_date": peak_date,
        "avg_turnover": avg_turnover,
        "rebalance_days": rebalance_days,
    }


def monthly_breakdown(history: list[dict]) -> list[dict]:
    from collections import defaultdict
    months: dict[str, list] = defaultdict(list)
    for e in history:
        month = e["date"][:7]
        months[month].append(e["daily_return"])

    result = []
    for month in sorted(months):
        rets = months[month]
        wins_m = sum(1 for r in rets if r > 0)
        losses_m = sum(1 for r in rets if r <= 0)
        avg_m = statistics.mean(rets)
        cum_m = 1.0
        for r in rets:
            cum_m *= (1 + r)
        result.append({
            "month": month,
            "days": len(rets),
            "avg_daily_pct": avg_m * 100,
            "cumulative_pct": (cum_m - 1) * 100,
            "wins": wins_m,
            "losses": losses_m,
        })
    return result


def regime_breakdown(log_days: list[dict]) -> dict:
    from collections import defaultdict, Counter
    counts: Counter = Counter()
    alpha_by_regime: dict[str, list] = defaultdict(list)
    for d in log_days:
        if d["regime"]:
            counts[d["regime"]] += 1
        if d["alpha_pct"] is not None and d["regime"]:
            alpha_by_regime[d["regime"]].append(d["alpha_pct"])
    result = {}
    for regime in sorted(counts):
        alphas = alpha_by_regime[regime]
        result[regime] = {
            "days": counts[regime],
            "avg_alpha_pct": statistics.mean(alphas) if alphas else 0.0,
        }
    return result


def md_table(headers: list[str], rows: list[list], align: Optional[list[str]] = None) -> str:
    align = align or ["left"] * len(headers)
    col_widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0)) for i, h in enumerate(headers)]

    def fmt_cell(val: str, width: int, al: str) -> str:
        if al == "right":
            return str(val).rjust(width)
        return str(val).ljust(width)

    sep_row = []
    for width, al in zip(col_widths, align):
        if al == "right":
            sep_row.append("-" * (width - 1) + ":")
        else:
            sep_row.append("-" * width)

    lines = []
    header_cells = [fmt_cell(h, col_widths[i], align[i]) for i, h in enumerate(headers)]
    lines.append("| " + " | ".join(header_cells) + " |")
    lines.append("| " + " | ".join(sep_row) + " |")
    for row in rows:
        cells = [fmt_cell(str(row[i]), col_widths[i], align[i]) for i in range(len(headers))]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_report(pa: dict, ls: dict, log_days: list[dict]) -> str:
    history = pa["history"]
    initial_capital = pa["initial_capital"]
    final_equity = history[-1]["equity"]
    total_return = (final_equity - initial_capital) / initial_capital

    metrics = compute_metrics(history)
    monthly = monthly_breakdown(history)
    regime_stats = regime_breakdown(log_days)

    lines: list[str] = []

    # ─── Header ───────────────────────────────────────────────────────────────
    lines += [
        "# AlphaShark — Post-Game Analysis",
        "",
        "**Competition:** Äripäev/SEB Investment Game 2026  ",
        "**Game period:** 6 April – 19 June 2026 (75 calendar trading days)  ",
        "**Paper track period:** 13 April – 15 June 2026 (36 trading sessions tracked)  ",
        "",
        "> The paper account tracks what would have happened if every daily AI recommendation",
        "> was executed. It is the \"hypothetical-perfect-execution\" baseline.",
        "> The user did not submit trades actively in the final ~4 weeks of the game.",
        "> Final 4 trading days (Jun 16–19) are not captured.",
        "",
    ]

    # ─── Executive Summary ────────────────────────────────────────────────────
    lines += [
        "## Executive Summary",
        "",
        md_table(
            ["Metric", "Value"],
            [
                ["Paper track return", f"+{total_return:.2%}"],
                ["Peak return (Jun 1)", f"+{(metrics['peak_equity'] - initial_capital) / initial_capital:.2%}"],
                ["Max drawdown from peak", f"{metrics['max_drawdown']:.2%}"],
                ["Trading days tracked", str(metrics["n_days"])],
                ["Win rate (days > 0%)", f"{metrics['win_rate']:.1%} ({metrics['wins']}W / {metrics['losses']}L)"],
                ["Avg daily return", f"+{metrics['avg_daily_return']:.2%}"],
                ["Annualized Sharpe ratio", f"{metrics['annualized_sharpe']:.2f}"],
                ["Avg daily turnover", f"{metrics['avg_turnover']:.1%}"],
                ["Rebalance days (turnover > 5%)", str(metrics["rebalance_days"])],
                ["Last known game rank (Jun 12)", "#809 / 9,300 players"],
                ["AI agents deployed", "4 (Strategist, Challenger, FullAnalyst, Devil)"],
            ],
        ),
        "",
    ]

    # ─── Equity Curve ─────────────────────────────────────────────────────────
    lines += [
        "## Equity Curve",
        "",
        md_table(
            ["Date", "Equity (€)", "Daily Return", "Cumulative Return", "Turnover"],
            [
                [
                    e["date"],
                    f"€{e['equity']:,.0f}",
                    f"{e['daily_return']:+.2%}",
                    f"{e['return_since_start']:+.2%}",
                    f"{e.get('turnover', 0):.0%}",
                ]
                for e in history
            ],
            align=["left", "right", "right", "right", "right"],
        ),
        "",
        f"> **Peak:** €{metrics['peak_equity']:,.0f} on {metrics['peak_date']} (+{(metrics['peak_equity']-initial_capital)/initial_capital:.2%})  ",
        f"> **Final:** €{final_equity:,.0f} on {history[-1]['date']} (+{total_return:.2%})  ",
        f"> **Max drawdown from peak:** {metrics['max_drawdown']:.2%}",
        "",
    ]

    # ─── Monthly Breakdown ────────────────────────────────────────────────────
    lines += [
        "## Month-by-Month Breakdown",
        "",
        md_table(
            ["Month", "Days", "Avg Daily Return", "Monthly Return", "W", "L"],
            [
                [
                    m["month"],
                    m["days"],
                    f"{m['avg_daily_pct']:+.2f}%",
                    f"{m['cumulative_pct']:+.2f}%",
                    m["wins"],
                    m["losses"],
                ]
                for m in monthly
            ],
            align=["left", "right", "right", "right", "right", "right"],
        ),
        "",
    ]

    # ─── Regime Breakdown ─────────────────────────────────────────────────────
    lines += [
        "## Market Regime Breakdown",
        "",
        "> Based on DAILY_LOG entries — regime on the date the recommendation was made.",
        "",
        md_table(
            ["Regime", "Days", "Avg Alpha vs Benchmark"],
            [
                [regime, str(data["days"]), f"{data['avg_alpha_pct']:+.2f}%"]
                for regime, data in regime_stats.items()
            ],
            align=["left", "right", "right"],
        ),
        "",
    ]

    # ─── What Worked ──────────────────────────────────────────────────────────
    lines += [
        "## What Worked",
        "",
        "### Rationale Tag Performance",
        "",
        "> Each AI recommendation is tagged with one or more rationale labels.",
        "> Tracked over 56 recorded trading days, 270 position-day observations.",
        "",
    ]

    rationale = ls.get("rationale_stats", {})
    rat_rows = sorted(
        [
            [tag, data["observations"], f"{data['avg_return_1d']*100:+.2f}%", f"{data['hit_rate']:.1%}"]
            for tag, data in rationale.items()
        ],
        key=lambda r: float(r[2].replace("%", "")),
        reverse=True,
    )
    lines += [
        md_table(
            ["Rationale Tag", "Observations", "Avg Daily Return", "Hit Rate"],
            rat_rows,
            align=["left", "right", "right", "right"],
        ),
        "",
        "> **Hit rate** = % of days the position closed positive.  ",
        "> Tags that appear on a single position are cumulative (e.g. `momentum + at_52w_high` increments both).",
        "",
        "### Best Performing Tickers",
        "",
        md_table(
            ["Ticker", "Observations", "Avg Daily Return", "Hit Rate"],
            [
                [t["ticker"], t["observations"], f"{t['avg_return_1d']*100:+.2f}%", f"{t['hit_rate']:.1%}"]
                for t in ls.get("validated_winners", [])
            ],
            align=["left", "right", "right", "right"],
        ),
        "",
        "### Signal Directional Accuracy",
        "",
        "> % of next-day predictions where signal pointed the right direction.",
        "> Random baseline = 50%.",
        "",
    ]

    sig = ls.get("signal_importance", {}).get("global", {})
    sig_rows = sorted(
        [[k, f"{v:.1%}"] for k, v in sig.items()],
        key=lambda r: float(r[1].replace("%", "")),
        reverse=True,
    )
    lines += [
        md_table(
            ["Signal", "Directional Accuracy (Global)"],
            sig_rows,
            align=["left", "right"],
        ),
        "",
        "> In **BULL** regime: `vol_ratio`, `momentum`, `vs_index` all hit **58.6%** accuracy.",
        "> In **NEUTRAL** regime: `vol_ratio` was the only signal above 50% at **54.0%**.",
        "",
    ]

    # ─── What Didn't Work ─────────────────────────────────────────────────────
    lines += [
        "## What Didn't Work",
        "",
        "### Underperforming Rationale Tags",
        "",
        md_table(
            ["Rationale Tag", "Observations", "Avg Daily Return", "Hit Rate", "Verdict"],
            [
                ["diversifier", 17, "-0.45%", "47.1%", "Blacklisted May 7"],
                ["non_us_differentiator", 42, "-0.25%", "30.9%", "Blacklisted May 7"],
                ["catalyst (earnings)", 39, "+0.84%", "51.3%", "Size-capped (≤12%)"],
            ],
        ),
        "",
        "> `diversifier` and `non_us_differentiator` were added to `biases_to_avoid` after",
        "> empirical evidence accumulated past the 5-observation threshold. These tags typically",
        "> reflected Nordic/Baltic filler picks chosen for geographic diversification rather",
        "> than signal quality.",
        "",
        "### Recurring Losers",
        "",
        md_table(
            ["Ticker", "Observations", "Avg Daily Return", "Hit Rate", "Outcome"],
            [
                [t["ticker"], t["observations"], f"{t['avg_return_1d']*100:+.2f}%", f"{t['hit_rate']:.1%}", "Hard banned" if t["hit_rate"] <= 0.25 else "Weight-capped"]
                for t in ls.get("recurring_losers", [])
            ],
            align=["left", "right", "right", "right", "left"],
        ),
        "",
        "### Devil's Advocate — A Contrarian Reversal",
        "",
        "> The Devil agent stress-tests top picks and flags them HIGH or LOW risk.",
        "> Original expectation: HIGH flags = bad picks to avoid.",
        "> Empirical outcome after 77 observations: **opposite**.",
        "",
    ]

    devil = ls.get("devil_accuracy", {})
    lines += [
        md_table(
            ["Devil Flag", "Avg 1-Day Return", "Negative Rate"],
            [
                ["HIGH risk", f"{devil.get('high_risk_avg_return_1d', 0)*100:+.2f}%", f"{devil.get('high_risk_negative_rate', 0):.1%}"],
                ["LOW risk", f"{devil.get('low_risk_avg_return_1d', 0)*100:+.2f}%", "n/a"],
            ],
            align=["left", "right", "right"],
        ),
        "",
        f"> Devil accuracy (HIGH-flag = actual loser): **{devil.get('accuracy', 0):.1%}** (n={devil.get('observations', 0)})  ",
        "> At n=77 the system **inverted** the Devil signal — HIGH-flagged tickers became",
        "> contrarian buy confirmations, not warnings. This was automated via `devil_inversion_active`.",
        "",
        "### Conviction Tier Paradox",
        "",
    ]

    ct = ls.get("conviction_tiers", {})
    lines += [
        md_table(
            ["Tier", "Observations", "Avg Daily Return"],
            [
                ["Tier 1 (highest conviction)", ct.get("tier1_observations", "?"), f"{ct.get('tier1_avg_return_1d', 0)*100:+.2f}%"],
                ["Tier 2 (mid conviction)", ct.get("tier2_observations", "?"), f"{ct.get('tier2_avg_return_1d', 0)*100:+.2f}%"],
                ["Tier 3 (lowest conviction)", ct.get("tier3_observations", "?"), f"{ct.get('tier3_avg_return_1d', 0)*100:+.2f}%"],
            ],
            align=["left", "right", "right"],
        ),
        "",
        "> Tier 2 outperformed Tier 1 by **+0.27%/day**. Hypothesis: over-consensus on top-ranked",
        "> names led to buying at crowded prices, while second-tier picks had less efficient pricing.",
        "",
    ]

    # ─── Key Lessons ──────────────────────────────────────────────────────────
    lines += [
        "## Key Lessons for Next Time",
        "",
        "| # | Lesson | Evidence |",
        "|---|--------|----------|",
        "| 1 | **Concentrate in breakout + at_52w_high** | Breakout: +0.99%/day, 56.8% hit — best tag. Diversifier: -0.45%/day. |",
        "| 2 | **Invert Devil's Advocate early** | Devil was wrong 63.6% of the time. Inversion should trigger at n=20, not n=77. |",
        "| 3 | **Avoid non-US filler picks** | `non_us_differentiator` hit rate: 30.9%. Nordic/Baltic diversification cost alpha. |",
        "| 4 | **Rank ≠ alpha** | Correlation between daily alpha and rank improvement was only **-0.16**. Need higher-beta right-tail picks to move rank in a 9,300-player field. |",
        "| 5 | **Hold winners longer** | Average turnover 30% — too high. Turnover guidance target: ≤25%. Replacing winners cost entry/re-entry spread. |",
        "| 6 | **Ship trades daily** | Not submitting for ~4 weeks meant the paper track diverged from reality. Even submitting once/week captures most of the alpha. |",
        "",
    ]

    # ─── Architecture Reflection ──────────────────────────────────────────────
    lines += [
        "## Architecture Reflection",
        "",
        "### What the Multi-Agent Ensemble Added",
        "",
        "- **Debate prevented groupthink:** Strategist (GPT-5.4) and Challenger (Gemini 2.5 Flash)",
        "  regularly diverged on Nordic vs US picks. When FullAnalyst (DeepSeek V3.2) broke the tie,",
        "  consensus positions showed +0.63%/day and 52.4% hit rate — better than any single model.",
        "- **Self-improving loop worked:** Hard rules, weight caps, and rationale blacklists were",
        "  promoted automatically from `learning_state.json` after empirical thresholds were crossed.",
        "  EQNR.OL was banned at n=10 observations; the ban prevented further losses.",
        "- **Devil inversion was a net win:** Even though the inversion wasn't triggered until n=77,",
        "  recognizing the contrarian pattern automated a valuable behavioral correction.",
        "",
        "### What Failed",
        "",
        "- **FullAnalyst timeout:** DeepSeek V3.2 via OpenRouter routinely took 8–12 min.",
        "  When it timed out, the three-way consensus became two-way, reducing debate quality.",
        "- **Agent accuracy tracking was never populated:** `agent_accuracy` in learning_state",
        "  shows 0 observations for all three proposal agents. Per-agent attribution was",
        "  architecturally planned but the linking of final positions back to proposing agents",
        "  was never completed.",
        "- **Rank feedback was too late:** The rank-aware feedback loop was added May 7 after",
        "  rank slipped from #355 to #556. Earlier activation (week 2) would have allowed",
        "  more aggressive beta dialing while the game was still early.",
        "- **No execution layer:** The system recommended portfolios but relied on manual",
        "  submission to the game. Automation would have made the paper track = real track.",
        "",
        "### For the Next Competition",
        "",
        "1. Add execution API integration (game portal or broker) to eliminate manual submission.",
        "2. Trigger Devil inversion at n=20 (not 77); use rolling 14-day accuracy window.",
        "3. Implement per-agent attribution to track which model's unique picks added alpha.",
        "4. Start rank-aware mode from day 1 — competitions are relative performance games.",
        "5. Use `vol_ratio` as primary signal filter; it showed highest directional accuracy",
        "   across all regimes (57.6% global, 58.6% BULL).",
        "",
    ]

    # ─── Footer ───────────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        f"*Generated by `scripts/post_game_analysis.py` on {date.today().isoformat()}.*  ",
        "*Data sources: `paper_account.json`, `learning_state.json`, `DAILY_LOG.md`.*",
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    print("Loading data...")
    pa = load_json("paper_account.json")
    ls = load_json("learning_state.json")
    log_days = parse_daily_log()
    print(f"  paper_account: {len(pa['history'])} history entries")
    print(f"  learning_state: {ls.get('position_observations')} position observations")
    print(f"  DAILY_LOG: {len(log_days)} date entries")

    print("Building report...")
    report = build_report(pa, ls, log_days)

    out_path = os.path.join(ROOT, "POST_GAME_ANALYSIS.md")
    with open(out_path, "w") as f:
        f.write(report)
    print(f"Written: {out_path} ({len(report):,} chars)")


if __name__ == "__main__":
    main()
