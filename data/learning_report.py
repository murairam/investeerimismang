"""
Pre-game learning report generator based on structured decision history.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime

from data.learning_state import generate_learning_state
from data.portfolio_store import load_decision_history, load_performance_history

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PAPER_ACCOUNT_PATH = os.path.join(_ROOT, "paper_account.json")
_REPORT_PATH = os.path.join(_ROOT, "PREGAME_LEARNING.md")
_MIN_STRONG_DAILY_OBSERVATIONS = 5


def _safe_load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        drawdown = (value / peak - 1) if peak > 0 else 0.0
        if drawdown < max_dd:
            max_dd = drawdown
    return abs(max_dd)


def _to_float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def generate_pregame_learning_report(target_date: str = "2026-04-06") -> dict:
    history = load_decision_history(max_days=60)
    legacy_performance = load_performance_history(max_days=60)
    state = generate_learning_state()
    paper_payload = _safe_load_json(_PAPER_ACCOUNT_PATH)
    paper_history = paper_payload.get("history", [])

    today = date.today()
    deadline = datetime.strptime(target_date, "%Y-%m-%d").date()
    days_left = (deadline - today).days

    daily_entries = []
    for item in history:
        outcome = (item.get("outcomes", {}) or {}).get("1d", {})
        performance = item.get("performance", {})
        alpha = outcome.get("alpha", performance.get("alpha_1d"))
        if alpha is None:
            continue
        daily_entries.append(
            {
                "date": item.get("date"),
                "alpha_1d": float(alpha),
                "position_returns": outcome.get("position_returns", performance.get("position_returns", {})),
            }
        )
    if len(daily_entries) < len(legacy_performance):
        fallback_entries = []
        for item in legacy_performance:
            if "alpha_1d" not in item:
                continue
            alpha_value = _to_float_or_none(item.get("alpha_1d"))
            if alpha_value is None:
                continue
            fallback_entries.append(
                {
                    "date": item.get("date"),
                    "alpha_1d": alpha_value,
                    "position_returns": item.get("position_returns", {}),
                }
            )
        daily_entries = fallback_entries

    wins = [entry for entry in daily_entries if entry["alpha_1d"] > 0]
    losses = [entry for entry in daily_entries if entry["alpha_1d"] < 0]
    avg_alpha = sum(entry["alpha_1d"] for entry in daily_entries) / len(daily_entries) if daily_entries else 0.0

    best_day = max(daily_entries, key=lambda entry: entry["alpha_1d"], default=None)
    worst_day = min(daily_entries, key=lambda entry: entry["alpha_1d"], default=None)

    equity_curve = [float(entry.get("equity", 0.0)) for entry in paper_history if entry.get("equity") is not None]
    turnovers = [float(entry.get("turnover", 0.0)) for entry in paper_history if entry.get("turnover") is not None]
    avg_turnover = sum(turnovers) / len(turnovers) if turnovers else 0.0

    initial_capital = float(paper_payload.get("initial_capital", 10000.0))
    latest_equity = float(paper_payload.get("last_equity", initial_capital))
    paper_return = (latest_equity / initial_capital - 1) if initial_capital > 0 else 0.0
    max_dd = _max_drawdown(equity_curve)

    action_items = []
    if len(daily_entries) >= _MIN_STRONG_DAILY_OBSERVATIONS and state.get("hard_rules"):
        action_items.extend(state["hard_rules"][:2])
    if len(daily_entries) >= _MIN_STRONG_DAILY_OBSERVATIONS and state.get("biases_to_avoid"):
        action_items.extend(state["biases_to_avoid"][:2])
    if not action_items:
        action_items.append("Collect at least 3-5 daily observations before changing the strategy rules.")

    winners = state.get("validated_winners", [])
    losers = state.get("recurring_losers", [])
    changed_rules = state.get("changed_hard_rules", [])
    sample_status = "actionable" if len(daily_entries) >= _MIN_STRONG_DAILY_OBSERVATIONS else "insufficient_data"
    latest_record = history[-1] if history else {}
    verification_note = (
        "Latest day is verified against the actual game portfolio."
        if latest_record.get("provenance") == "verified"
        else "Latest day is still experimental / unverified."
    )

    lines = [
        "# Pre-Game Learning Report",
        "",
        f"Generated: {today.isoformat()}",
        f"Target go-live date: {target_date}",
        f"Days remaining: {days_left if days_left >= 0 else 0}",
        "",
        "## Scoreboard",
        f"- Training days with measurable alpha: {len(daily_entries)}",
        f"- Win days (alpha > 0): {len(wins)}",
        f"- Loss days (alpha < 0): {len(losses)}",
        f"- Average daily alpha: {avg_alpha:+.2%}",
        f"- Paper account equity: €{latest_equity:,.2f} (from €{initial_capital:,.2f}, return {paper_return:+.2%})",
        f"- Max drawdown (paper): {max_dd:.2%}",
        f"- Average turnover: {avg_turnover:.2%}",
        "",
        "## Confidence note",
        f"- Evidence status: {sample_status}",
        f"- Minimum daily observations for strong conclusions: {_MIN_STRONG_DAILY_OBSERVATIONS}",
        f"- {verification_note}",
        "",
        "## Best and worst day",
        f"- Best alpha day: {best_day.get('date')} ({best_day.get('alpha_1d', 0.0):+.2%})" if best_day else "- Best alpha day: N/A",
        f"- Worst alpha day: {worst_day.get('date')} ({worst_day.get('alpha_1d', 0.0):+.2%})" if worst_day else "- Worst alpha day: N/A",
        "",
        "## Structured learning state",
        f"- Active hard rules: {len(state.get('hard_rules', []))}",
        f"- Changed hard rules since yesterday: {len(changed_rules)}",
        f"- Confidence notes: {len(state.get('confidence_notes', []))}",
        "",
        "## Ticker lessons",
    ]

    if winners or losers:
        lines.append("| Ticker | Bucket | Obs | Avg 1d return | Hit rate |")
        lines.append("|---|---|---:|---:|---:|")
        for item in winners[:5]:
            lines.append(
                f"| {item['ticker']} | winner | {item['observations']} | {item['avg_return_1d']:+.2%} | {item['hit_rate']:.0%} |"
            )
        for item in losers[:5]:
            lines.append(
                f"| {item['ticker']} | loser | {item['observations']} | {item['avg_return_1d']:+.2%} | {item['hit_rate']:.0%} |"
            )
    else:
        lines.append("No validated ticker lessons yet — sample is still too small for strong promotion to winner/loser status.")

    lines += ["", "## Action plan until April 6"]
    lines.extend(f"- {item}" for item in action_items)
    lines += [
        "",
        "## Daily routine",
        "- Run: `python main.py`",
        "- Refresh report: `python scripts/pregame_review.py`",
        "- Review `learning_state.json` when new hard rules appear.",
        "",
    ]

    with open(_REPORT_PATH, "w") as f:
        f.write("\n".join(lines))

    return {
        "days_left": max(days_left, 0),
        "avg_alpha": avg_alpha,
        "paper_return": paper_return,
        "max_drawdown": max_dd,
        "avg_turnover": avg_turnover,
        "report_path": _REPORT_PATH,
    }
