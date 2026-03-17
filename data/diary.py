"""
Diary writer — appends a human-readable daily entry to DIARY.md after each run.
"""
import logging
import math
import os
from typing import Optional

from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal

logger = logging.getLogger(__name__)

_DIARY_PATH = os.path.join(os.path.dirname(__file__), "..", "DAILY_LOG.md")


def append_entry(
    final: PortfolioProposal,
    snapshot: MarketSnapshot,
    prior: Optional[PortfolioProposal] = None,
) -> None:
    """Append today's portfolio entry to DIARY.md."""
    path = os.path.abspath(_DIARY_PATH)
    entry = _build_entry(final, snapshot, prior)

    # Create header if file doesn't exist yet
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write("# AlphaShark — Daily Portfolio Log\n\n")
            f.write("Each entry is written automatically after the daily run.\n\n")
            f.write("---\n\n")

    with open(path, "a") as f:
        f.write(entry)

    logger.info("Diary entry appended to %s", path)


def _build_entry(
    final: PortfolioProposal,
    snapshot: MarketSnapshot,
    prior: Optional[PortfolioProposal] = None,
) -> str:
    date = snapshot["as_of_date"]
    regime = snapshot.get("regime", "N/A")
    spx_vs = snapshot.get("spx_vs_200d", 0.0)
    vix = snapshot.get("vix_level", float("nan"))
    bench = snapshot["benchmark_return"]
    total_weight = sum(p.weight for p in final.positions)

    vix_str = "N/A" if math.isnan(vix) else f"{vix:.1f}"

    lines = [
        f"## {date}",
        "",
        f"**Market:** {regime} regime · SPX vs 200d SMA: {spx_vs:+.1%} · "
        f"VIX: {vix_str} · "
        f"S&P 500 20d: {bench:+.1%}",
        "",
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
