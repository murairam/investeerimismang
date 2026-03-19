"""
Pre-game learning report generator.

Builds a concise markdown report from recorded daily performance and paper-account
history so the strategy can systematically improve before the real game starts.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PORTFOLIO_HISTORY_PATH = os.path.join(_ROOT, "portfolio_history.json")
_PAPER_ACCOUNT_PATH = os.path.join(_ROOT, "paper_account.json")
_REPORT_PATH = os.path.join(_ROOT, "PREGAME_LEARNING.md")


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


def generate_pregame_learning_report(target_date: str = "2026-04-06") -> dict:
    history_payload = _safe_load_json(_PORTFOLIO_HISTORY_PATH)
    paper_payload = _safe_load_json(_PAPER_ACCOUNT_PATH)

    performance = history_payload.get("performance_history", [])
    paper_history = paper_payload.get("history", [])

    today = date.today()
    deadline = datetime.strptime(target_date, "%Y-%m-%d").date()
    days_left = (deadline - today).days

    daily_entries = [entry for entry in performance if "alpha_1d" in entry]
    wins = [entry for entry in daily_entries if entry.get("alpha_1d", 0.0) > 0]
    losses = [entry for entry in daily_entries if entry.get("alpha_1d", 0.0) < 0]
    avg_alpha = (
        sum(entry.get("alpha_1d", 0.0) for entry in daily_entries) / len(daily_entries)
        if daily_entries
        else 0.0
    )

    best_day = max(daily_entries, key=lambda e: e.get("alpha_1d", -999), default=None)
    worst_day = min(daily_entries, key=lambda e: e.get("alpha_1d", 999), default=None)

    ticker_stats: dict[str, dict] = {}
    for entry in daily_entries:
        for ticker, ret in entry.get("position_returns", {}).items():
            stats = ticker_stats.setdefault(ticker, {"returns": []})
            stats["returns"].append(ret)

    ranked_tickers: list[dict] = []
    for ticker, data in ticker_stats.items():
        rets = data["returns"]
        observations = len(rets)
        avg_ret = sum(rets) / observations if observations else 0.0
        hit_rate = sum(1 for r in rets if r > 0) / observations if observations else 0.0
        ranked_tickers.append(
            {
                "ticker": ticker,
                "observations": observations,
                "avg_return": avg_ret,
                "hit_rate": hit_rate,
            }
        )

    ranked_tickers.sort(key=lambda row: row["avg_return"], reverse=True)
    strong_tickers = [row for row in ranked_tickers if row["observations"] >= 2 and row["avg_return"] > 0][:5]
    weak_tickers = [row for row in ranked_tickers if row["observations"] >= 2 and row["avg_return"] < 0][:5]

    equity_curve = [float(entry.get("equity", 0.0)) for entry in paper_history if entry.get("equity") is not None]
    turnovers = [float(entry.get("turnover", 0.0)) for entry in paper_history if entry.get("turnover") is not None]
    avg_turnover = sum(turnovers) / len(turnovers) if turnovers else 0.0

    initial_capital = float(paper_payload.get("initial_capital", 10000.0))
    latest_equity = float(paper_payload.get("last_equity", initial_capital))
    paper_return = (latest_equity / initial_capital - 1) if initial_capital > 0 else 0.0
    max_dd = _max_drawdown(equity_curve)

    action_items: list[str] = []
    if avg_alpha < 0:
        action_items.append(
            f"Alpha is negative ({avg_alpha:+.2%} avg). Require stronger edge before replacing positions: "
            "replacement must have Sharpe_20d ≥ 0.3 higher than the stock being exited."
        )
    if avg_turnover > 0.35:
        action_items.append(
            f"Turnover is {avg_turnover:.0%} — target ≤35%. Keep at least 50% of weight in yesterday's "
            "holdings. Only replace a position if the new pick's Sharpe_20d is ≥20% higher."
        )
    if max_dd > 0.05:
        action_items.append(
            f"Max drawdown is {max_dd:.1%} — above 5% threshold. Cap the largest position at 18% "
            "and avoid stocks with vol_ratio < 0.8 (low-volume moves have low conviction)."
        )
    if strong_tickers:
        winners = ", ".join(row["ticker"] for row in strong_tickers[:3])
        action_items.append(f"Core basket — keep these unless Sharpe_20d drops below 0.2: {winners}.")
    if weak_tickers:
        losers = ", ".join(row["ticker"] for row in weak_tickers[:3])
        action_items.append(
            f"Avoid or underweight these recurring underperformers (max 7% each if held at all): {losers}."
        )
    if not action_items:
        action_items.append("Collect at least 3-5 daily observations before changing the strategy rules.")

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
        "## Best and worst day",
    ]

    if best_day:
        lines.append(f"- Best alpha day: {best_day.get('date')} ({best_day.get('alpha_1d', 0.0):+.2%})")
    else:
        lines.append("- Best alpha day: N/A")

    if worst_day:
        lines.append(f"- Worst alpha day: {worst_day.get('date')} ({worst_day.get('alpha_1d', 0.0):+.2%})")
    else:
        lines.append("- Worst alpha day: N/A")

    lines += ["", "## Ticker lessons"]
    if ranked_tickers:
        lines.append("| Ticker | Obs | Avg 1d return | Hit rate |")
        lines.append("|---|---:|---:|---:|")
        for row in ranked_tickers[:10]:
            lines.append(
                f"| {row['ticker']} | {row['observations']} | {row['avg_return']:+.2%} | {row['hit_rate']:.0%} |"
            )
    else:
        lines.append("No ticker-level history yet.")

    lines += ["", "## Action plan until April 6"]
    for item in action_items:
        lines.append(f"- {item}")

    lines += [
        "",
        "## Daily routine",
        "- Run: `python main.py`",
        "- Refresh report: `python pregame_review.py`",
        "- Record what changed in weights and why before the next run.",
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