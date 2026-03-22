"""
Meta-learning report generated from structured daily decision history.
"""
from __future__ import annotations

import os
from datetime import date, datetime

from data.learning_state import generate_learning_state, load_learning_state
from data.portfolio_store import RATIONALE_TAGS, load_decision_history, load_performance_history

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_META_REPORT_PATH = os.path.join(_ROOT, "AI_SELF_CRITIQUE.md")
_MIN_STRONG_DAILY_OBSERVATIONS = 5
_MIN_STRONG_RATIONALE_OBSERVATIONS = 5


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _collect_rows(history: list[dict]) -> tuple[list[dict], list[dict]]:
    daily_entries = []
    position_rows = []
    for day in history:
        outcome_1d = (day.get("outcomes", {}) or {}).get("1d", {})
        performance = day.get("performance", {})
        alpha = outcome_1d.get("alpha", performance.get("alpha_1d"))
        if alpha is None:
            continue
        daily_entries.append(
            {
                "date": day.get("date"),
                "alpha_1d": float(alpha),
                "portfolio_return_1d": float(outcome_1d.get("portfolio_return", performance.get("portfolio_return_1d", 0.0))),
            }
        )
        pos_returns = outcome_1d.get("position_returns", performance.get("position_returns", {})) or {}
        for pos in day.get("final_portfolio", {}).get("positions", []):
            ticker = pos.get("ticker")
            if ticker not in pos_returns:
                continue
            position_rows.append(
                {
                    "date": day.get("date"),
                    "ticker": ticker,
                    "weight": float(pos.get("weight", 0.0)),
                    "return_1d": float(pos_returns[ticker]),
                    "tags": pos.get("tags", []),
                }
            )
    return daily_entries, position_rows


def generate_meta_learning_report(target_date: str = "2026-04-06") -> dict:
    history = load_decision_history(max_days=60)
    legacy_performance = load_performance_history(max_days=60)
    state = generate_learning_state()
    daily_entries, position_rows = _collect_rows(history)
    if len(daily_entries) < len(legacy_performance):
        daily_entries = [
            {
                "date": item.get("date"),
                "alpha_1d": float(item.get("alpha_1d", 0.0)),
                "portfolio_return_1d": float(item.get("portfolio_return_1d", 0.0)),
            }
            for item in legacy_performance
            if "portfolio_return_1d" in item
        ]

    today = date.today()
    deadline = datetime.strptime(target_date, "%Y-%m-%d").date()
    days_left = (deadline - today).days
    latest_record = history[-1] if history else {}

    rationale_performance = {tag: [] for tag in RATIONALE_TAGS}
    tier1_returns: list[float] = []
    tier2_returns: list[float] = []
    tier3_returns: list[float] = []

    for row in position_rows:
        for tag in row["tags"]:
            if tag in rationale_performance:
                rationale_performance[tag].append(row["return_1d"])
        if row["weight"] >= 0.20:
            tier1_returns.append(row["return_1d"])
        elif row["weight"] >= 0.12:
            tier2_returns.append(row["return_1d"])
        else:
            tier3_returns.append(row["return_1d"])

    total_days = len(daily_entries)
    positive_alpha_days = len([entry for entry in daily_entries if entry["alpha_1d"] > 0])
    alpha_hit_rate = positive_alpha_days / total_days if total_days > 0 else 0.0

    insights: list[str] = []
    biases: list[str] = []

    for tag, values in rationale_performance.items():
        if len(values) < _MIN_STRONG_RATIONALE_OBSERVATIONS:
            continue
        avg_ret = _avg(values)
        hit_rate = len([ret for ret in values if ret > 0]) / len(values)
        if avg_ret > 0.003 and hit_rate >= 0.55:
            insights.append(f"'{tag}' rationale is working: {avg_ret:+.1%} avg, {hit_rate:.0%} hit rate")
        elif avg_ret < -0.003 or hit_rate < 0.4:
            biases.append(f"'{tag}' rationale is weak: {avg_ret:+.1%} avg, {hit_rate:.0%} hit rate")

    tier1_avg = _avg(tier1_returns)
    tier2_avg = _avg(tier2_returns)
    tier3_avg = _avg(tier3_returns)
    if len(tier1_returns) >= _MIN_STRONG_DAILY_OBSERVATIONS and len(tier3_returns) >= _MIN_STRONG_DAILY_OBSERVATIONS:
        if tier1_avg < tier3_avg:
            biases.append(
                f"INVERTED CONVICTION: Tier 1 averaged {tier1_avg:+.1%} vs Tier 3 {tier3_avg:+.1%}. Cap large weights."
            )
        elif tier1_avg > tier3_avg + 0.005:
            insights.append(f"Conviction sizing is working: Tier 1 {tier1_avg:+.1%} > Tier 3 {tier3_avg:+.1%}")

    if total_days < _MIN_STRONG_DAILY_OBSERVATIONS:
        insights.append(
            f"Only {total_days} day(s) of data — this report is descriptive, not yet reliable enough for strong policy changes."
        )
    elif alpha_hit_rate >= 0.60:
        insights.append(f"Strategy is producing alpha {alpha_hit_rate:.0%} of days.")
    else:
        biases.append(f"Alpha hit rate is low: {alpha_hit_rate:.0%}.")

    action_items = list(state.get("hard_rules", [])) if total_days >= _MIN_STRONG_DAILY_OBSERVATIONS else []
    if total_days >= _MIN_STRONG_DAILY_OBSERVATIONS:
        action_items.extend(state.get("biases_to_avoid", [])[:3])
    if not action_items:
        if total_days < _MIN_STRONG_DAILY_OBSERVATIONS:
            action_items.append("Keep collecting data. Do not make large strategic changes from this report yet.")
        else:
            action_items.append("No strong structured bias detected yet. Keep monitoring before changing strategy.")

    lines = [
        "# AI Self-Critique Report",
        "",
        f"Generated: {today.isoformat()}",
        f"Training days analyzed: {total_days}",
        f"Days until live mode: {days_left if days_left >= 0 else 0}",
        "",
        "## Meta-Learning Question",
        "**Is the AI's reasoning accurate, or just lucky/unlucky?**",
        "",
        "This report evaluates whether the AI's stated rationales and conviction levels correlate with outcomes.",
        "",
        "## Confidence note",
        f"- Evidence status: {'actionable' if total_days >= _MIN_STRONG_DAILY_OBSERVATIONS else 'insufficient_data'}",
        f"- Minimum daily observations for strong conclusions: {_MIN_STRONG_DAILY_OBSERVATIONS}",
        f"- Minimum rationale observations for bias claims: {_MIN_STRONG_RATIONALE_OBSERVATIONS}",
        f"- Latest day status: {'verified' if latest_record.get('provenance') == 'verified' else 'experimental / unverified'}",
        "",
        "## What's Working ✅",
    ]

    if insights:
        lines.extend(f"- {insight}" for insight in insights)
    else:
        lines.append("- Not enough structured history yet to identify strong patterns.")

    lines += ["", "## Systematic Biases / Errors ⚠️"]
    if biases:
        lines.extend(f"- {bias}" for bias in biases)
    else:
        lines.append("- None detected yet, or the sample is still too small for a strong claim.")

    lines += ["", "## Rationale Performance Breakdown"]
    lines.append("| Rationale Type | Observations | Avg Return | Hit Rate |")
    lines.append("|---|---:|---:|---:|")
    wrote_rationale = False
    for tag, values in rationale_performance.items():
        if not values:
            continue
        wrote_rationale = True
        hit_rate = len([ret for ret in values if ret > 0]) / len(values)
        lines.append(f"| {tag} | {len(values)} | {_avg(values):+.2%} | {hit_rate:.0%} |")
    if not wrote_rationale:
        lines.append("| insufficient data | 0 | 0.00% | 0% |")

    lines += ["", "## Conviction Sizing Accuracy"]
    lines.append("| Tier | Weight Range | Observations | Avg Return |")
    lines.append("|---|---|---:|---:|")
    lines.append(f"| Tier 1 (high conviction) | 20-25% | {len(tier1_returns)} | {tier1_avg:+.2%} |")
    lines.append(f"| Tier 2 (medium conviction) | 12-18% | {len(tier2_returns)} | {tier2_avg:+.2%} |")
    lines.append(f"| Tier 3 (low conviction) | 5-10% | {len(tier3_returns)} | {tier3_avg:+.2%} |")

    lines += ["", "## Structured Learning State"]
    lines.append(f"- Active hard rules: {len(state.get('hard_rules', []))}")
    lines.append(f"- Changed hard rules since yesterday: {len(state.get('changed_hard_rules', []))}")
    lines.append(f"- Validated winners tracked: {len(state.get('validated_winners', []))}")
    lines.append(f"- Recurring losers tracked: {len(state.get('recurring_losers', []))}")

    lines += ["", "## Action Items for the AI"]
    lines.extend(f"- {item}" for item in action_items)
    lines.append("")

    with open(_META_REPORT_PATH, "w") as f:
        f.write("\n".join(lines))

    evidence_status = "actionable" if total_days >= _MIN_STRONG_DAILY_OBSERVATIONS else "insufficient_data"
    accuracy_score = None
    if evidence_status == "actionable":
        if insights and biases:
            accuracy_score = len(insights) / (len(insights) + len(biases))
        elif insights:
            accuracy_score = 1.0
        else:
            accuracy_score = 0.0

    return {
        "accuracy_score": accuracy_score,
        "evidence_status": evidence_status,
        "insights_count": len(insights),
        "biases_count": len(biases),
        "alpha_hit_rate": alpha_hit_rate,
        "action_items": action_items,
        "report_path": _META_REPORT_PATH,
    }


def generate_ticker_performance_report(performance_history: list[dict]) -> str:
    state = load_learning_state()
    winners = state.get("validated_winners", [])
    losers = state.get("recurring_losers", [])
    if not winners and not losers:
        return ""

    lines = ["## Per-ticker performance (structured learning state)"]
    if winners:
        lines.append("")
        lines.append("**Consistent performers**")
        for item in winners[:5]:
            lines.append(
                f"  {item['ticker']:<12} avg {item['avg_return_1d']:+.2%}  hit-rate {item['hit_rate']:.0%}  ({item['observations']} obs)"
            )
    if losers:
        lines.append("")
        lines.append("**Persistent underperformers**")
        for item in losers[:5]:
            lines.append(
                f"  {item['ticker']:<12} avg {item['avg_return_1d']:+.2%}  hit-rate {item['hit_rate']:.0%}  ({item['observations']} obs)"
            )
    return "\n".join(lines)


def detect_strategy_decay(history: list[dict], window_recent: int = 5, window_prior: int = 10) -> dict:
    """
    Compare alpha over the most recent `window_recent` days vs the prior `window_prior` days.
    Returns a decay status dict. Positive decay_magnitude = recent alpha dropped.
    """
    alpha_series: list[tuple[str, float]] = []
    for day in history:
        outcomes = (day.get("outcomes", {}) or {}).get("1d", {})
        perf = day.get("performance", {}) or {}
        alpha = outcomes.get("alpha") or perf.get("alpha_1d")
        day_date = day.get("date", "")
        if alpha is not None and day_date:
            alpha_series.append((day_date, float(alpha)))

    alpha_series.sort(key=lambda x: x[0])
    recent = [a for _, a in alpha_series[-window_recent:]]
    prior = [a for _, a in alpha_series[-(window_recent + window_prior):-window_recent]]

    if len(recent) < 3 or len(prior) < 3:
        return {"status": "insufficient_data", "decay_detected": False}

    recent_avg = _avg(recent)
    prior_avg = _avg(prior)
    decay = prior_avg - recent_avg  # positive = recent alpha dropped

    return {
        "status": "decay_detected" if decay > 0.002 else "stable",
        "recent_avg_alpha": round(recent_avg, 6),
        "prior_avg_alpha": round(prior_avg, 6),
        "decay_magnitude": round(decay, 6),
        "recent_days": len(recent),
        "prior_days": len(prior),
        "decay_detected": decay > 0.002,
    }


if __name__ == "__main__":
    result = generate_meta_learning_report()
    print(f"\nMeta-learning report generated: {result['report_path']}")
