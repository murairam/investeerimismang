"""
Meta-learning report: AI evaluates the quality of its own past analysis.

This goes beyond "which stocks won" to ask:
- Were the rationales accurate predictions?
- Did the AI's reasoning match what actually happened?
- Are there systematic biases in signal interpretation?
- What mistakes keep recurring and how to fix them?
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime
from typing import Optional

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PORTFOLIO_HISTORY_PATH = os.path.join(_ROOT, "portfolio_history.json")
_DAILY_LOG_PATH = os.path.join(_ROOT, "DAILY_LOG.md")
_META_REPORT_PATH = os.path.join(_ROOT, "AI_SELF_CRITIQUE.md")


def _safe_load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _extract_daily_entries_from_log() -> list[dict]:
    """Parse DAILY_LOG.md to extract rationales and market context."""
    if not os.path.exists(_DAILY_LOG_PATH):
        return []

    with open(_DAILY_LOG_PATH, "r") as f:
        content = f.read()

    entries = []
    sections = content.split("---\n##")

    for section in sections[1:]:  # Skip header
        lines = section.strip().split("\n")
        if not lines:
            continue

        entry = {"date": "", "thesis": "", "positions": {}}

        # Extract date from first line
        date_line = lines[0].strip()
        if date_line:
            # Format: "2026-03-17" or "2026-03-17 16:25:26"
            parts = date_line.split()
            if parts:
                entry["date"] = parts[0]

        # Extract thesis
        for i, line in enumerate(lines):
            if line.startswith("**Thesis:**"):
                entry["thesis"] = line.replace("**Thesis:**", "").strip()
                break

        # Extract position rationales
        in_table = False
        for line in lines:
            if "| **" in line and "|" in line:
                in_table = True
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 3:
                    # Format: | 1 | **TICKER** | 25.0% | rationale |
                    ticker = parts[1].replace("**", "").strip()
                    if ticker and not ticker.startswith("#"):
                        rationale = parts[3] if len(parts) > 3 else ""
                        entry["positions"][ticker] = rationale

        if entry["date"]:
            entries.append(entry)

    return entries


def generate_meta_learning_report(target_date: str = "2026-04-06") -> dict:
    """
    Generate a meta-learning report that critiques the AI's own analysis quality.

    Returns:
        dict with keys: accuracy_score, systematic_biases, action_items, report_path
    """
    history_payload = _safe_load_json(_PORTFOLIO_HISTORY_PATH)
    performance = history_payload.get("performance_history", [])
    daily_entries = [e for e in performance if "portfolio_return_1d" in e]

    log_entries = _extract_daily_entries_from_log()

    today = date.today()
    deadline = datetime.strptime(target_date, "%Y-%m-%d").date()
    days_left = (deadline - today).days

    # Analysis 1: Rationale quality check
    # Did stocks that were given "strong momentum" rationales actually perform well?
    rationale_performance = {
        "breakout": [],
        "momentum": [],
        "high_sharpe": [],
        "recovery": [],
        "diversifier": [],
    }

    for entry in daily_entries:
        entry_date = entry.get("date")
        pos_returns = entry.get("position_returns", {})

        # Find matching log entry
        log_entry = next((le for le in log_entries if le["date"] == entry_date), None)
        if not log_entry:
            continue

        for ticker, ret in pos_returns.items():
            rationale = log_entry["positions"].get(ticker, "").lower()

            if "breakout" in rationale or "52-week high" in rationale:
                rationale_performance["breakout"].append(ret)
            if "momentum" in rationale or "sharpe" in rationale:
                rationale_performance["momentum"].append(ret)
            if "sharpe" in rationale:
                rationale_performance["high_sharpe"].append(ret)
            if "recovery" in rationale or "recovering" in rationale:
                rationale_performance["recovery"].append(ret)
            if "diversif" in rationale or "diversifier" in rationale:
                rationale_performance["diversifier"].append(ret)

    # Analysis 2: Conviction vs reality
    # Did high-weight positions (Tier 1: 20-25%) outperform low-weight (Tier 3: 5-10%)?
    tier1_returns = []  # 20-25% positions
    tier2_returns = []  # 12-18% positions
    tier3_returns = []  # 5-10% positions

    for entry in daily_entries:
        entry_date = entry.get("date")
        pos_returns = entry.get("position_returns", {})

        # Find positions in portfolio_history to get weights
        if entry_date == history_payload.get("date"):
            positions = history_payload.get("positions", [])
            for pos in positions:
                ticker = pos["ticker"]
                weight = pos["weight"]
                ret = pos_returns.get(ticker)

                if ret is not None and not math.isnan(ret):
                    if weight >= 0.20:
                        tier1_returns.append(ret)
                    elif weight >= 0.12:
                        tier2_returns.append(ret)
                    else:
                        tier3_returns.append(ret)

    # Analysis 3: Thesis accuracy
    # Count how often the stated thesis played out
    total_days = len(daily_entries)
    positive_alpha_days = len([e for e in daily_entries if e.get("alpha_1d", 0) > 0])
    alpha_hit_rate = positive_alpha_days / total_days if total_days > 0 else 0.0

    # Generate insights
    insights = []
    biases = []

    # Insight 1: Which rationale types work best?
    for rationale_type, returns in rationale_performance.items():
        if len(returns) >= 3:
            avg_ret = sum(returns) / len(returns)
            hit_rate = len([r for r in returns if r > 0]) / len(returns)

            if avg_ret > 0.01 and hit_rate > 0.6:
                insights.append(
                    f"✅ '{rationale_type}' rationale is working well: {avg_ret:+.1%} avg, {hit_rate:.0%} hit rate"
                )
            elif avg_ret < -0.005 or hit_rate < 0.4:
                biases.append(
                    f"⚠️ '{rationale_type}' rationale is underperforming: {avg_ret:+.1%} avg, {hit_rate:.0%} hit rate"
                )

    # Insight 2: Is conviction sizing accurate?
    def avg(lst):
        return sum(lst) / len(lst) if lst else 0.0

    tier1_avg = avg(tier1_returns)
    tier2_avg = avg(tier2_returns)
    tier3_avg = avg(tier3_returns)

    if tier1_returns and tier3_returns:
        if tier1_avg < tier3_avg:
            biases.append(
                f"⚠️ Conviction sizing is INVERTED: Tier 1 (20-25%) averaged {tier1_avg:+.1%}, "
                f"but Tier 3 (5-10%) averaged {tier3_avg:+.1%}. Lower conviction beats higher!"
            )
        elif tier1_avg > tier3_avg + 0.01:
            insights.append(
                f"✅ Conviction sizing is working: Tier 1 {tier1_avg:+.1%} > Tier 3 {tier3_avg:+.1%}"
            )

    # Insight 3: Overall strategy health
    if alpha_hit_rate > 0.6:
        insights.append(f"✅ Strategy is producing alpha {alpha_hit_rate:.0%} of days (target: >60%)")
    else:
        biases.append(f"⚠️ Alpha hit rate is low: {alpha_hit_rate:.0%} (target: >60%)")

    # Action items for the AI
    action_items = []

    if not insights:
        action_items.append("Collect at least 3-5 days of data before making strategy adjustments.")

    if any("recovery" in b for b in biases):
        action_items.append(
            "Reduce weight on 'recovery' plays. Favor proven momentum over speculative reversals."
        )

    if any("INVERTED" in b for b in biases):
        action_items.append(
            "Re-calibrate conviction: If low-conviction picks are winning, increase their weights. "
            "If high-conviction picks are losing, reduce tier 1 sizing or improve stock selection."
        )

    if alpha_hit_rate < 0.5:
        action_items.append(
            "Alpha generation is inconsistent. Tighten entry criteria: require Sharpe_20d > 0.4 "
            "AND vs_index > +2% AND near 52-week high."
        )

    if total_days >= 5 and not [i for i in insights if "Conviction" in i]:
        action_items.append(
            "Review position sizing methodology. Conviction levels may not correlate with performance."
        )

    if not action_items:
        action_items.append("Continue current strategy. Performance signals are healthy.")

    # Write report
    lines = [
        "# AI Self-Critique Report",
        "",
        f"Generated: {today.isoformat()}",
        f"Training days analyzed: {len(daily_entries)}",
        f"Days until live mode: {days_left if days_left >= 0 else 0}",
        "",
        "## Meta-Learning Question",
        "**Is the AI's reasoning accurate, or just lucky/unlucky?**",
        "",
        "This report evaluates whether the AI's stated rationales (e.g., 'strong momentum', 'breakout') "
        "actually correlate with strong performance. If not, the AI needs to adjust its analysis framework.",
        "",
        "## What's Working ✅",
    ]

    if insights:
        for insight in insights:
            lines.append(f"- {insight}")
    else:
        lines.append("- Not enough data yet to identify patterns (need 3+ days)")

    lines += ["", "## Systematic Biases / Errors ⚠️"]

    if biases:
        for bias in biases:
            lines.append(f"- {bias}")
    else:
        lines.append("- None detected yet")

    lines += ["", "## Rationale Performance Breakdown"]

    if rationale_performance:
        lines.append("| Rationale Type | Observations | Avg Return | Hit Rate |")
        lines.append("|---|---:|---:|---:|")
        for rationale_type, returns in rationale_performance.items():
            if returns:
                avg_ret = avg(returns)
                hit_rate = len([r for r in returns if r > 0]) / len(returns)
                lines.append(
                    f"| {rationale_type} | {len(returns)} | {avg_ret:+.2%} | {hit_rate:.0%} |"
                )
    else:
        lines.append("No rationale data yet.")

    lines += ["", "## Conviction Sizing Accuracy"]

    if tier1_returns or tier2_returns or tier3_returns:
        lines.append("| Tier | Weight Range | Observations | Avg Return |")
        lines.append("|---|---|---:|---:|")
        if tier1_returns:
            lines.append(f"| Tier 1 (high conviction) | 20-25% | {len(tier1_returns)} | {tier1_avg:+.2%} |")
        if tier2_returns:
            lines.append(f"| Tier 2 (medium conviction) | 12-18% | {len(tier2_returns)} | {tier2_avg:+.2%} |")
        if tier3_returns:
            lines.append(f"| Tier 3 (low conviction) | 5-10% | {len(tier3_returns)} | {tier3_avg:+.2%} |")
    else:
        lines.append("No conviction data yet.")

    lines += ["", "## Action Items for the AI"]

    for item in action_items:
        lines.append(f"- {item}")

    lines += [
        "",
        "## How This Improves the AI",
        "This report is automatically fed into the AI's system prompt on each run, so it learns to:",
        "- Trust signals that have proven accurate (e.g., 'high Sharpe' if it's working)",
        "- De-emphasize signals that haven't worked (e.g., 'recovery' if it keeps losing)",
        "- Adjust conviction sizing based on actual tier performance",
        "- Recognize when it's overconfident or underconfident",
        "",
    ]

    with open(_META_REPORT_PATH, "w") as f:
        f.write("\n".join(lines))

    # Calculate accuracy score
    accuracy_score = 0.0
    if insights and biases:
        accuracy_score = len(insights) / (len(insights) + len(biases))
    elif insights:
        accuracy_score = 1.0

    return {
        "accuracy_score": accuracy_score,
        "insights_count": len(insights),
        "biases_count": len(biases),
        "alpha_hit_rate": alpha_hit_rate,
        "action_items": action_items,
        "report_path": _META_REPORT_PATH,
    }


def generate_ticker_performance_report(performance_history: list[dict]) -> str:
    """
    Analyze per-ticker performance across tracked runs to identify which tickers
    have been reliable vs consistently disappointing.

    Returns a formatted string suitable for injection into agent prompts.
    Note: this is ticker-level hit-rate tracking, not signal-to-return correlation.
    Full signal correlation (Sharpe/vs_index/vol_ratio vs returns) requires stored
    signal snapshots and will be added once enough runs accumulate.
    """
    if not performance_history:
        return ""

    # Aggregate per-ticker returns across all tracked days
    ticker_returns: dict[str, list[float]] = {}
    for entry in performance_history:
        for ticker, ret in entry.get("position_returns", {}).items():
            if not math.isnan(ret):
                ticker_returns.setdefault(ticker, []).append(ret)

    # Need at least a few tickers with multi-day observations
    multi_obs = {t: rets for t, rets in ticker_returns.items() if len(rets) >= 2}
    if len(multi_obs) < 3:
        return ""

    ticker_stats = {
        t: {
            "avg": sum(rets) / len(rets),
            "hit_rate": sum(1 for ret in rets if ret > 0) / len(rets),
            "obs": len(rets),
        }
        for t, rets in multi_obs.items()
    }

    sorted_by_avg = sorted(ticker_stats.items(), key=lambda x: x[1]["avg"], reverse=True)
    n_days = len(performance_history)

    lines = [
        f"## Per-ticker performance ({n_days} tracked days, tickers with ≥2 observations)",
        "",
        "**Consistent performers** (keep unless signals deteriorate):",
    ]
    for ticker, s in sorted_by_avg:
        if s["avg"] > 0.002 and s["hit_rate"] >= 0.6:
            lines.append(
                f"  {ticker:<12} avg {s['avg']:+.2%}  hit-rate {s['hit_rate']:.0%}  ({s['obs']} obs) ✅"
            )

    lines.append("")
    lines.append("**Persistent underperformers** (consider avoiding):")
    for ticker, s in reversed(sorted_by_avg):
        if s["avg"] < -0.002 or s["hit_rate"] < 0.35:
            lines.append(
                f"  {ticker:<12} avg {s['avg']:+.2%}  hit-rate {s['hit_rate']:.0%}  ({s['obs']} obs) ⚠️"
            )

    # Signal-level notes (placeholder until signal_snapshot is stored per run)
    lines += [
        "",
        "_Note: full signal-to-return correlation (Sharpe, vs_index, vol_ratio) will appear here_",
        "_once signal snapshots are accumulated across 5+ runs._",
    ]

    result = "\n".join(lines)
    # Only return if there's meaningful content (at least one entry in either section)
    if "✅" in result or "⚠️" in result:
        return result
    return ""


if __name__ == "__main__":
    result = generate_meta_learning_report()
    print(f"\n✅ Meta-learning report generated: {result['report_path']}")
    print(f"   Accuracy score: {result['accuracy_score']:.0%}")
    print(f"   Insights: {result['insights_count']}, Biases detected: {result['biases_count']}")
    print(f"   Alpha hit rate: {result['alpha_hit_rate']:.0%}\n")
