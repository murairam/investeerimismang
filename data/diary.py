"""
Diary writer — maintains one canonical human-readable entry per date and,
in pregame mode, appends every rerun to a separate debug log.
"""
import logging
import math
import os
import re
from datetime import datetime
from typing import Optional

from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal

logger = logging.getLogger(__name__)

_PREGAME_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "PREGAME_LOG.md")
_LIVE_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "DAILY_LOG.md")
_PREGAME_RUNS_PATH = os.path.join(os.path.dirname(__file__), "..", "PREGAME_RUNS.md")


def append_entry(
    final: PortfolioProposal,
    snapshot: MarketSnapshot,
    prior: Optional[PortfolioProposal] = None,
    performance: Optional[dict] = None,
    paper_metrics: Optional[dict] = None,
    mode: str = "PREGAME",
) -> None:
    """Upsert today's canonical portfolio entry to the appropriate log file.

    PREGAME runs update PREGAME_LOG.md and append debug entries to PREGAME_RUNS.md.
    LIVE runs update DAILY_LOG.md.
    """
    if mode == "LIVE":
        path = os.path.abspath(_LIVE_LOG_PATH)
        title = "AlphaShark — Daily Portfolio Log"
        subtitle = "One canonical entry per date. Verified entries reflect the actual submitted portfolio."
        debug_path = None
    else:
        path = os.path.abspath(_PREGAME_LOG_PATH)
        title = "AlphaShark — Pre-Game Training Log"
        subtitle = "One canonical entry per date. Same-day reruns update that day's entry; full rerun history lives in PREGAME_RUNS.md."
        debug_path = os.path.abspath(_PREGAME_RUNS_PATH)

    entry = _build_entry(final, snapshot, prior, performance, paper_metrics)

    _ensure_log_file(path, title, subtitle)
    _upsert_entry(path, snapshot["as_of_date"], entry)

    if debug_path:
        _ensure_log_file(
            debug_path,
            "AlphaShark — Pregame Run Debug Log",
            "Every pregame run is appended here for debugging. This file does not drive learning.",
        )
        with open(debug_path, "a") as f:
            f.write(entry)

    logger.info("Diary entry updated in %s", path)


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
    spx_vs = snapshot.get("spx_vs_sma", 0.0)
    vix = snapshot.get("vix_level", float("nan"))
    bench = snapshot["benchmark_return"]
    total_weight = sum(p.weight for p in final.positions)

    vix_str = "N/A" if math.isnan(vix) else f"{vix:.1f}"

    lines = [
        f"## {date} {run_time_str}",
        "",
        f"**Market:** {regime} regime · SPX vs 50d SMA: {spx_vs:+.1%} · "
        f"VIX: {vix_str} · "
        f"S&P 500 20d: {bench:+.1%}",
        "",
        "**Verification:** Pending manual confirmation via `python scripts/verify.py`.",
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


def mark_verified_entry(date: str, mode: str = "PREGAME", verified_at: Optional[str] = None) -> None:
    path = os.path.abspath(_LIVE_LOG_PATH if mode == "LIVE" else _PREGAME_LOG_PATH)
    if not os.path.exists(path):
        return

    try:
        with open(path, "r") as f:
            content = f.read()
    except Exception as exc:
        logger.warning("Could not read diary for verification update: %s", exc)
        return

    pattern = re.compile(rf"(^## {re.escape(date)}[^\n]*\n)(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(content)
    if not match:
        return

    section = match.group(2)
    timestamp = verified_at or datetime.now().strftime("%H:%M:%S")
    verified_line = f"**Verification:** Verified against actual game holdings at {timestamp}."

    if "**Verification:**" in section:
        section = re.sub(r"^\*\*Verification:\*\*.*$", verified_line, section, count=1, flags=re.MULTILINE)
    else:
        section = verified_line + "\n\n" + section

    updated = content[:match.start(2)] + section + content[match.end(2):]
    with open(path, "w") as f:
        f.write(updated)


def _ensure_log_file(path: str, title: str, subtitle: str) -> None:
    if os.path.exists(path):
        return
    with open(path, "w") as f:
        f.write(f"# {title}\n\n{subtitle}\n\n---\n\n")


def _upsert_entry(path: str, date: str, entry: str) -> None:
    with open(path, "r") as f:
        content = f.read()

    pattern = re.compile(rf"^## {re.escape(date)}[^\n]*\n.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    matches = list(pattern.finditer(content))
    if matches:
        first = matches[0]
        rebuilt = []
        cursor = 0
        rebuilt.append(content[:first.start()])
        rebuilt.append(entry.rstrip() + "\n\n")
        cursor = first.end()
        for match in matches[1:]:
            rebuilt.append(content[cursor:match.start()])
            cursor = match.end()
        rebuilt.append(content[cursor:])
        content = "".join(rebuilt)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += entry

    with open(path, "w") as f:
        f.write(content)
