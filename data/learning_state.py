"""
Structured learning state derived from daily decision history.
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections import defaultdict
from typing import Optional

from data.portfolio_store import RATIONALE_TAGS, load_decision_history, load_performance_history

logger = logging.getLogger(__name__)

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_STATE_PATH = os.path.join(_ROOT, "learning_state.json")
_MIN_STRONG_DAILY_OBSERVATIONS = 5
_MIN_STRONG_TICKER_OBSERVATIONS = 5
_MIN_STRONG_RATIONALE_OBSERVATIONS = 5


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _position_records(history: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for day in history:
        portfolio = day.get("final_portfolio", {})
        positions = portfolio.get("positions", [])
        outcomes = (day.get("outcomes", {}) or {}).get("1d", {})
        pos_returns = outcomes.get("position_returns", {}) or day.get("performance", {}).get("position_returns", {})
        signal_snapshot = day.get("signal_snapshot", {})
        for pos in positions:
            ticker = pos.get("ticker")
            ret = pos_returns.get(ticker)
            if ret is None:
                continue
            rows.append(
                {
                    "date": day.get("date"),
                    "ticker": ticker,
                    "weight": float(pos.get("weight", 0.0)),
                    "return_1d": float(ret),
                    "tags": pos.get("tags", []),
                    "signal": signal_snapshot.get(ticker, {}),
                }
            )
    return rows


def load_learning_state() -> dict:
    if not os.path.exists(_STATE_PATH):
        return {}
    try:
        with open(_STATE_PATH, "r") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Could not load learning state: %s", exc)
        return {}


def save_learning_state(state: dict) -> None:
    with open(_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def generate_learning_state() -> dict:
    history = load_decision_history(max_days=60)
    previous = load_learning_state()
    rows = _position_records(history)
    legacy_performance = load_performance_history(max_days=60)

    ticker_returns: dict[str, list[float]] = defaultdict(list)
    rationale_returns: dict[str, list[float]] = {tag: [] for tag in RATIONALE_TAGS}
    tier_returns: dict[str, list[float]] = {"tier1": [], "tier2": [], "tier3": []}
    hold_vs_replace: list[float] = []
    slot_costs: list[float] = []
    turnover_samples: list[float] = []

    for row in rows:
        ticker_returns[row["ticker"]].append(row["return_1d"])
        for tag in row["tags"]:
            if tag in rationale_returns:
                rationale_returns[tag].append(row["return_1d"])
        if row["weight"] >= 0.20:
            tier_returns["tier1"].append(row["return_1d"])
        elif row["weight"] >= 0.12:
            tier_returns["tier2"].append(row["return_1d"])
        else:
            tier_returns["tier3"].append(row["return_1d"])

    for day in history:
        evaluation = day.get("decision_evaluation", {}) or {}
        metrics = day.get("decision_metrics", {}) or {}
        if evaluation.get("hold_vs_replace_1d") is not None:
            hold_vs_replace.append(float(evaluation["hold_vs_replace_1d"]))
        if evaluation.get("slot_opportunity_cost_1d") is not None:
            slot_costs.append(float(evaluation["slot_opportunity_cost_1d"]))
        if metrics.get("turnover_estimate") is not None:
            turnover_samples.append(float(metrics["turnover_estimate"]))

    for entry in legacy_performance:
        for ticker, ret in (entry.get("position_returns", {}) or {}).items():
            ticker_returns[ticker].append(float(ret))

    winners = []
    losers = []
    for ticker, values in ticker_returns.items():
        if len(values) < _MIN_STRONG_TICKER_OBSERVATIONS:
            continue
        avg_ret = _avg(values)
        hit_rate = sum(1 for value in values if value > 0) / len(values)
        item = {
            "ticker": ticker,
            "observations": len(values),
            "avg_return_1d": round(avg_ret, 6),
            "hit_rate": round(hit_rate, 4),
        }
        if avg_ret > 0 and hit_rate >= 0.5:
            winners.append(item)
        if avg_ret < 0:
            losers.append(item)

    winners.sort(key=lambda item: (item["avg_return_1d"], item["hit_rate"]), reverse=True)
    losers.sort(key=lambda item: (item["avg_return_1d"], -item["hit_rate"]))

    rationale_stats = {}
    for tag, values in rationale_returns.items():
        if not values:
            continue
        rationale_stats[tag] = {
            "observations": len(values),
            "avg_return_1d": round(_avg(values), 6),
            "hit_rate": round(sum(1 for value in values if value > 0) / len(values), 4),
        }

    hard_rules: list[str] = []
    biases_to_avoid: list[str] = []
    weight_caps: list[dict] = []

    tier1_avg = _avg(tier_returns["tier1"])
    tier3_avg = _avg(tier_returns["tier3"])
    if (
        len(tier_returns["tier1"]) >= _MIN_STRONG_DAILY_OBSERVATIONS
        and len(tier_returns["tier3"]) >= _MIN_STRONG_DAILY_OBSERVATIONS
        and tier1_avg < tier3_avg
    ):
        hard_rules.append("Cap all positions at 15% until Tier 1 returns exceed Tier 3 returns over recent history.")
        weight_caps.append({"scope": "global", "max_weight": 0.15, "reason": "inverted_conviction"})

    for tag, stats in rationale_stats.items():
        if stats["observations"] >= _MIN_STRONG_RATIONALE_OBSERVATIONS and (stats["avg_return_1d"] < -0.003 or stats["hit_rate"] < 0.4):
            biases_to_avoid.append(
                f"Avoid overusing {tag} rationales until their hit rate recovers above 40%."
            )

    for loser in losers[:3]:
        if loser["observations"] >= _MIN_STRONG_TICKER_OBSERVATIONS:
            weight_caps.append(
                {
                    "scope": "ticker",
                    "ticker": loser["ticker"],
                    "max_weight": 0.07,
                    "reason": "recurring_underperformer",
                }
            )

    turnover_guidance = {
        "instruction": "Keep at least 50% of weight in existing holdings unless a replacement has materially stronger signals.",
        "min_hold_weight": 0.50,
        "replacement_sharpe_delta": 0.20,
    }
    if len(hold_vs_replace) >= _MIN_STRONG_DAILY_OBSERVATIONS and _avg(hold_vs_replace) < 0:
        turnover_guidance = {
            "instruction": "Recent replacements have underperformed dropped names. Prefer holding unless the replacement has clearly stronger 5d momentum and volume confirmation.",
            "min_hold_weight": 0.65,
            "replacement_sharpe_delta": 0.30,
        }
        hard_rules.append(
            "Do not replace an existing holding unless the incoming candidate is materially stronger on both 5d momentum and volume confirmation."
        )

    if len(slot_costs) >= _MIN_STRONG_DAILY_OBSERVATIONS and _avg(slot_costs) > 0.002:
        biases_to_avoid.append(
            "Recent selected baskets have lagged nearby alternatives. Re-check the weakest slot against the next-best candidate before finalizing."
        )

    confidence_notes = []
    for tag, stats in rationale_stats.items():
        if stats["observations"] >= _MIN_STRONG_RATIONALE_OBSERVATIONS and stats["avg_return_1d"] > 0:
            confidence_notes.append(
                {
                    "tag": tag,
                    "instruction": f"Prefer {tag} setups when other signals are comparable.",
                    "observations": stats["observations"],
                }
            )

    devil_accuracy = _devil_accuracy(history)

    state = {
        "generated_from_days": max(len(history), len(legacy_performance)),
        "position_observations": len(rows),
        "minimums": {
            "strong_daily_observations": _MIN_STRONG_DAILY_OBSERVATIONS,
            "strong_ticker_observations": _MIN_STRONG_TICKER_OBSERVATIONS,
            "strong_rationale_observations": _MIN_STRONG_RATIONALE_OBSERVATIONS,
        },
        "hard_rules": hard_rules,
        "biases_to_avoid": biases_to_avoid,
        "validated_winners": winners[:5],
        "recurring_losers": losers[:5],
        "weight_caps": weight_caps,
        "turnover_guidance": turnover_guidance,
        "decision_quality": {
            "avg_hold_vs_replace_1d": round(_avg(hold_vs_replace), 6) if hold_vs_replace else 0.0,
            "positive_hold_vs_replace_rate": round(sum(1 for value in hold_vs_replace if value > 0) / len(hold_vs_replace), 4)
            if hold_vs_replace else 0.0,
            "avg_slot_opportunity_cost_1d": round(_avg(slot_costs), 6) if slot_costs else 0.0,
            "avg_turnover_estimate": round(_avg(turnover_samples), 6) if turnover_samples else 0.0,
            "observations": len(hold_vs_replace),
            "status": "actionable" if len(hold_vs_replace) >= _MIN_STRONG_DAILY_OBSERVATIONS else "insufficient_data",
        },
        "confidence_notes": confidence_notes[:5],
        "rationale_stats": rationale_stats,
        "conviction_tiers": {
            "tier1_avg_return_1d": round(tier1_avg, 6),
            "tier2_avg_return_1d": round(_avg(tier_returns["tier2"]), 6),
            "tier3_avg_return_1d": round(tier3_avg, 6),
            "tier1_observations": len(tier_returns["tier1"]),
            "tier2_observations": len(tier_returns["tier2"]),
            "tier3_observations": len(tier_returns["tier3"]),
        },
        "changed_hard_rules": _changed_rules(previous.get("hard_rules", []), hard_rules),
        "devil_accuracy": devil_accuracy,
    }
    save_learning_state(state)
    return state


def _devil_accuracy(history: list[dict]) -> dict:
    """
    Compare 1d returns of HIGH vs LOW/unflagged positions across all days
    where bear_cases + position_returns are both present.
    Returns accuracy stats for injecting into agent prompts.
    """
    high_returns: list[float] = []
    low_returns: list[float] = []  # LOW-flagged or unflagged (in portfolio but not HIGH)

    for day in history:
        bear_cases: dict = day.get("bear_cases", {}) or {}
        outcomes = (day.get("outcomes", {}) or {}).get("1d", {})
        pos_returns: dict = outcomes.get("position_returns", {}) or day.get("performance", {}).get("position_returns", {})
        if not pos_returns:
            continue
        for ticker, ret in pos_returns.items():
            risk_level = (bear_cases.get(ticker) or {}).get("risk_level", "LOW")
            if risk_level == "HIGH":
                high_returns.append(float(ret))
            else:
                low_returns.append(float(ret))

    if not high_returns or not low_returns:
        return {"status": "insufficient_data", "observations": 0}

    high_avg = _avg(high_returns)
    low_avg = _avg(low_returns)
    high_neg_rate = sum(1 for r in high_returns if r < 0) / len(high_returns)
    accuracy = high_neg_rate  # % of HIGH-risk flags that correctly predicted negative return

    return {
        "status": "actionable" if len(high_returns) >= 5 else "early_data",
        "observations": len(high_returns),
        "high_risk_avg_return_1d": round(high_avg, 6),
        "low_risk_avg_return_1d": round(low_avg, 6),
        "high_risk_negative_rate": round(high_neg_rate, 4),
        "accuracy": round(accuracy, 4),
        "devil_is_accurate": accuracy >= 0.60 and len(high_returns) >= 5,
    }


def _changed_rules(previous: list[str], current: list[str]) -> list[str]:
    previous_set = set(previous)
    return [rule for rule in current if rule not in previous_set]


def build_prompt_learning_context(
    strategy_text: str = "",
    fallback_sections: Optional[list[str]] = None,
) -> str:
    state = load_learning_state()
    fallback_sections = fallback_sections or []
    sections: list[str] = []

    if strategy_text:
        sections.append("=== PERMANENT STRATEGY PRINCIPLES (highest priority) ===\n" + strategy_text.strip())

    if state:
        lines = ["=== STRUCTURED LEARNING STATE (apply in priority order) ==="]
        if state.get("hard_rules"):
            lines.append("Hard constraints:")
            lines.extend(f"- {rule}" for rule in state["hard_rules"][:4])
        if state.get("biases_to_avoid"):
            lines.append("Biases to avoid:")
            lines.extend(f"- {rule}" for rule in state["biases_to_avoid"][:4])
        winners = state.get("validated_winners", [])
        if winners:
            lines.append("Validated winners:")
            lines.extend(
                f"- {item['ticker']}: avg {item['avg_return_1d']:+.2%} over {item['observations']} obs"
                for item in winners[:3]
            )
        losers = state.get("recurring_losers", [])
        if losers:
            lines.append("Recurring losers:")
            lines.extend(
                f"- {item['ticker']}: avg {item['avg_return_1d']:+.2%} over {item['observations']} obs"
                for item in losers[:3]
            )
        devil = state.get("devil_accuracy", {})
        if devil.get("status") in ("actionable", "early_data") and devil.get("observations", 0) > 0:
            da = devil
            if da.get("devil_is_accurate"):
                lines.append(
                    f"Devil's advocate accuracy: HIGH-risk flags have been correct {da['high_risk_negative_rate']:.0%} of the time "
                    f"({da['observations']} obs). HIGH-risk picks avg {da['high_risk_avg_return_1d']:+.2%}/day vs "
                    f"LOW-risk {da['low_risk_avg_return_1d']:+.2%}/day. TREAT HIGH-RISK FLAGS AS A 10% WEIGHT CAP TODAY."
                )
            else:
                lines.append(
                    f"Devil's advocate accuracy so far: {da.get('high_risk_negative_rate', 0):.0%} of HIGH-risk flags went negative "
                    f"({da['observations']} obs, threshold for action: 60%). Use your own judgement on flagged picks."
                )
        sections.append("\n".join(lines))

    if fallback_sections and not state:
        sections.extend(section for section in fallback_sections if section)

    if not sections:
        return ""
    return "=== LEARNING FROM PREVIOUS RUNS (use to improve today's picks) ===\n" + "\n\n".join(sections) + "\n=== END LEARNING ==="
