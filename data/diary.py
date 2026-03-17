"""
Diary writer — appends a human-readable daily entry to DIARY.md after each run.
"""
import logging
import math
import os
from datetime import datetime
from typing import Optional

from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal

logger = logging.getLogger(__name__)

_PREGAME_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "PREGAME_LOG.md")
_LIVE_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "DAILY_LOG.md")


def append_entry(
    final: PortfolioProposal,
    snapshot: MarketSnapshot,
    prior: Optional[PortfolioProposal] = None,
    performance: Optional[dict] = None,
    paper_metrics: Optional[dict] = None,
    mode: str = "PREGAME",
) -> None:
    """Append today's portfolio entry to the appropriate log file.

    PREGAME runs write to PREGAME_LOG.md (training record).
    LIVE runs write to DAILY_LOG.md (the real competition log, starts clean on April 6).
    """
    if mode == "LIVE":
        path = os.path.abspath(_LIVE_LOG_PATH)
        title = "AlphaShark — Daily Portfolio Log"
        subtitle = "Each entry is written automatically after the daily run."
    else:
        path = os.path.abspath(_PREGAME_LOG_PATH)
        title = "AlphaShark — Pre-Game Training Log"
        subtitle = "Training runs before the game starts (April 6). Values reset to €10,000 on game day."

    entry = _build_entry(final, snapshot, prior, performance, paper_metrics)

    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(f"# {title}\n\n{subtitle}\n\n---\n\n")

    with open(path, "a") as f:
        f.write(entry)

    logger.info("Diary entry appended to %s", path)


def _build_entry(
    final: PortfolioProposal,
    snapshot: MarketSnapshot,
    prior: Optional[PortfolioProposal] = None,
    performance: Optional[dict] = None,
    paper_metrics: Optional[dict] = None,
) -> str:
    date = snapshot["as_of_date"]
    run_time_str = datetime.now().strftime("%H:%M:%S")
    regime = snapshot.get("regime", "N/A")
    spx_vs = snapshot.get("spx_vs_200d", 0.0)
    vix = snapshot.get("vix_level", float("nan"))
    bench = snapshot["benchmark_return"]
    total_weight = sum(p.weight for p in final.positions)

    vix_str = "N/A" if math.isnan(vix) else f"{vix:.1f}"

    lines = [
        f"## {date} {run_time_str}",
        "",
        f"**Market:** {regime} regime · SPX vs 200d SMA: {spx_vs:+.1%} · "
        f"VIX: {vix_str} · "
        f"S&P 500 20d: {bench:+.1%}",
        "",
    ]

    # P&L section — only when yesterday's performance data is available
    if performance is not None:
        p_ret = performance.get("portfolio_return_1d", float("nan"))
        b_ret = performance.get("benchmark_return_1d", float("nan"))
        a_ret = performance.get("alpha_1d", float("nan"))
        pos_rets = performance.get("position_returns", {})

        p_str = f"{p_ret:+.1%}" if not math.isnan(p_ret) else "N/A"
        b_str = f"{b_ret:+.1%}" if not math.isnan(b_ret) else "N/A"
        a_str = f"{a_ret:+.1%}" if not math.isnan(a_ret) else "N/A"

        pnl_line = f"**Yesterday's P&L:** Portfolio {p_str} · Benchmark {b_str} · Alpha {a_str}"

        winner_parts = []
        loser_parts = []
        if pos_rets:
            winners_sorted = sorted([(t, r) for t, r in pos_rets.items() if r > 0], key=lambda x: -x[1])
            losers_sorted = sorted([(t, r) for t, r in pos_rets.items() if r < 0], key=lambda x: x[1])
            winner_parts = [f"{t} {r:+.1%}" for t, r in winners_sorted[:3]]
            loser_parts = [f"{t} {r:+.1%}" for t, r in losers_sorted[:3]]

        movers_parts = []
        if winner_parts:
            movers_parts.append("Winners: " + ", ".join(winner_parts))
        if loser_parts:
            movers_parts.append("Losers: " + ", ".join(loser_parts))
        movers_line = " | ".join(movers_parts) if movers_parts else ""

        lines.append(pnl_line)
        if movers_line:
            lines.append(movers_line)
        lines.append("")

    if paper_metrics is not None:
        equity = paper_metrics.get("equity", float("nan"))
        cash = paper_metrics.get("cash", float("nan"))
        daily_ret = paper_metrics.get("daily_return", float("nan"))
        since_start = paper_metrics.get("return_since_start", float("nan"))
        turnover = paper_metrics.get("turnover", float("nan"))
        init_cap = paper_metrics.get("initial_capital", float("nan"))

        eq_str = f"€{equity:,.2f}" if not math.isnan(equity) else "N/A"
        cash_str = f"€{cash:,.2f}" if not math.isnan(cash) else "N/A"
        d_str = f"{daily_ret:+.2%}" if not math.isnan(daily_ret) else "N/A"
        s_str = f"{since_start:+.2%}" if not math.isnan(since_start) else "N/A"
        t_str = f"{turnover:.1%}" if not math.isnan(turnover) else "N/A"
        init_str = f"€{init_cap:,.0f}" if not math.isnan(init_cap) else "N/A"

        lines.append(
            f"**Paper account:** Equity {eq_str} (start {init_str}) · "
            f"Today {d_str} · Since start {s_str} · Turnover {t_str} · Cash {cash_str}"
        )
        lines.append("")

    lines += [
        f"**Confidence:** {final.confidence:.0%} · "
        f"**Positions:** {len(final.positions)} · "
        f"**Total weight:** {total_weight:.1%}",
        "",
        f"**Thesis:** {final.reasoning}",
        "",
    ]

    # Portfolio table
    lines.append("| # | Ticker | Weight | Rationale |")
    lines.append("|---|--------|--------|-----------|")
    for i, pos in enumerate(final.positions, 1):
        lines.append(f"| {i} | **{pos.ticker}** | {pos.weight:.1%} | {pos.rationale} |")
    lines.append("")

    # Changes vs yesterday
    if prior and prior.positions:
        prior_map = {p.ticker: p.weight for p in prior.positions}
        final_map = {p.ticker: p.weight for p in final.positions}

        added = [t for t in final_map if t not in prior_map]
        removed = [t for t in prior_map if t not in final_map]
        resized = [
            t for t in final_map
            if t in prior_map and abs(final_map[t] - prior_map[t]) >= 0.02
        ]

        if added or removed or resized:
            lines.append("**Changes from yesterday:**")
            for t in added:
                lines.append(f"- ➕ Added **{t}** at {final_map[t]:.1%}")
            for t in removed:
                lines.append(f"- ➖ Removed **{t}** (was {prior_map[t]:.1%})")
            for t in resized:
                diff = final_map[t] - prior_map[t]
                arrow = "▲" if diff > 0 else "▼"
                lines.append(f"- {arrow} **{t}**: {prior_map[t]:.1%} → {final_map[t]:.1%} ({diff:+.1%})")
        else:
            lines.append("**Changes from yesterday:** No significant changes — held positions.")
    else:
        lines.append("**Changes from yesterday:** First run (no prior portfolio).")

    lines += ["", "---", ""]
    return "\n".join(lines)
