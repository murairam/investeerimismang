"""
Structured learning state derived from daily decision history.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from collections import defaultdict
from typing import Optional

from data.portfolio_store import (
    RATIONALE_TAGS,
    load_decision_history,
    load_performance_history,
    load_competition_standing_history,
    save_learning_state_to_db,
    load_learning_state_from_db,
)
import config as config_module

logger = logging.getLogger(__name__)

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_STATE_PATH = os.path.join(_ROOT, "learning_state.json")
_MIN_STRONG_DAILY_OBSERVATIONS = 7       # 7 trading days ≈ 1.5 weeks before daily conclusions are actionable
_MIN_STRONG_TICKER_OBSERVATIONS = 8      # Raised from 5 — prevents 2-day noise from promoting a ticker bias to a hard rule
_MIN_STRONG_RATIONALE_OBSERVATIONS = 5  # Rationale tags share observations across many positions — 5 obs is enough signal
_MIN_MANDATORY_RATIONALE_OBSERVATIONS = 8   # ~1.5 weeks before a rationale-tag cap becomes code-enforced (75-day game moves fast)


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_signal_importance(rows: list[dict]) -> dict:
    """
    For each signal, compute directional accuracy vs next-day return (0.5 = random, 1.0 = perfect).
    Returns {"global": {signal: score}, "per_regime": {"BULL": {signal: score}, ...}}.
    """
    SIGNALS = ["momentum", "mom_5d", "sharpe_20d", "rsi_14", "vs_index", "vol_ratio", "beta"]
    hits_global: dict[str, list[float]] = {s: [] for s in SIGNALS}
    hits_regime: dict[str, dict[str, list[float]]] = {
        r: {s: [] for s in SIGNALS} for r in ("BULL", "NEUTRAL", "BEAR")
    }
    for row in rows:
        ret = row["return_1d"]
        sig = row.get("signal", {})
        regime = row.get("regime") or "UNKNOWN"
        for s in SIGNALS:
            val = sig.get(s)
            if val is not None:
                hit = 1.0 if (val > 0 and ret > 0) or (val < 0 and ret < 0) else 0.0
                hits_global[s].append(hit)
                if regime in hits_regime:
                    hits_regime[regime][s].append(hit)
    # Require a minimum number of observations before promoting a signal as important.
    # With only 5 obs (1 trading week), directional accuracy is pure noise — a signal
    # hitting 4/5 times is easily explained by coincidence, not edge.
    _MIN_SIGNAL_OBS = config_module.SIGNAL_IMPORTANCE_MIN_OBS
    global_imp = {s: round(sum(v) / len(v), 4) for s, v in hits_global.items() if len(v) >= _MIN_SIGNAL_OBS}
    per_regime = {
        regime: {s: round(sum(v) / len(v), 4) for s, v in sig_hits.items() if len(v) >= _MIN_SIGNAL_OBS}
        for regime, sig_hits in hits_regime.items()
    }
    per_regime = {r: imp for r, imp in per_regime.items() if imp}
    return {"global": global_imp, "per_regime": per_regime}


def compute_confidence_calibration(history: list[dict]) -> dict:
    """
    Compare actual 1d portfolio returns on high-confidence (>=0.75) vs
    low-confidence (<0.75) days. Returns calibration dict.
    """
    high_conf_returns: list[float] = []
    low_conf_returns: list[float] = []
    for day in history:
        conf = float((day.get("final_portfolio") or {}).get("confidence", 0.0))
        ret = (day.get("outcomes", {}) or {}).get("1d", {}).get("portfolio_return", None)
        if ret is None:
            ret = (day.get("performance") or {}).get("portfolio_return_1d", None)
        if ret is None:
            continue
        if conf >= 0.75:
            high_conf_returns.append(float(ret))
        else:
            low_conf_returns.append(float(ret))

    if not high_conf_returns or not low_conf_returns:
        return {"status": "insufficient_data"}

    high_avg = _avg(high_conf_returns)
    low_avg = _avg(low_conf_returns)
    overconfident = high_avg < low_avg and len(high_conf_returns) >= 3

    return {
        "status": "actionable" if len(high_conf_returns) >= 3 else "early_data",
        "high_confidence_avg_return": round(high_avg, 6),
        "low_confidence_avg_return": round(low_avg, 6),
        "high_confidence_observations": len(high_conf_returns),
        "low_confidence_observations": len(low_conf_returns),
        "overconfidence_detected": overconfident,
    }


def _position_records(history: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for day in history:
        portfolio = day.get("final_portfolio", {})
        positions = portfolio.get("positions", [])
        outcomes = (day.get("outcomes", {}) or {}).get("1d", {})
        pos_returns = outcomes.get("position_returns", {}) or day.get("performance", {}).get("position_returns", {})
        signal_snapshot = day.get("signal_snapshot", {})
        regime = day.get("regime")
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
                    "regime": regime,
                }
            )
    return rows


def load_learning_state() -> dict:
    db_state = load_learning_state_from_db()
    if db_state is not None:
        return db_state
    if not os.path.exists(_STATE_PATH):
        return {}
    try:
        with open(_STATE_PATH, "r") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Could not load learning state from JSON: %s", exc)
        return {}


def save_learning_state(state: dict) -> None:
    save_learning_state_to_db(state)
    dir_ = os.path.dirname(_STATE_PATH)
    try:
        with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as f:
            json.dump(state, f, indent=2)
            tmp = f.name
        os.replace(tmp, _STATE_PATH)
    except Exception as exc:
        logger.warning("Could not save learning state to JSON: %s", exc)


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

    early_warning_notes: list[str] = []
    _RATIONALE_CAP_HIT_RATE_THRESHOLD = 0.30
    for tag, stats in rationale_stats.items():
        observations = stats["observations"]
        hit_rate = stats["hit_rate"]
        weak_signal = stats["avg_return_1d"] < -0.003 or hit_rate < 0.4
        # Promote to hard weight cap when hit rate is genuinely poor with sufficient data.
        # This is stronger than a bias-to-avoid (which is advisory) — the cap is code-enforced.
        if observations >= _MIN_MANDATORY_RATIONALE_OBSERVATIONS and hit_rate < _RATIONALE_CAP_HIT_RATE_THRESHOLD:
            hard_rules.append(
                f"RATIONALE CAP: cap any position whose primary thesis is '{tag}' at 15% — "
                f"hit rate {hit_rate:.0%} over {observations} observations (threshold: {_RATIONALE_CAP_HIT_RATE_THRESHOLD:.0%})."
            )
            weight_caps.append({
                "scope": "rationale_tag",
                "tag": tag,
                "max_weight": 0.15,
                "reason": f"{tag}_hit_rate_{hit_rate:.0%}_over_{observations}_obs",
            })
        elif observations >= _MIN_MANDATORY_RATIONALE_OBSERVATIONS and weak_signal:
            biases_to_avoid.append(
                f"Avoid overusing {tag} rationales until their hit rate recovers above 40%."
            )
        elif observations >= _MIN_STRONG_RATIONALE_OBSERVATIONS and weak_signal:
            early_warning_notes.append(
                f"EARLY WARNING: {tag} has weak hit quality ({hit_rate:.0%} over {observations} obs)."
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
        "biases_to_avoid": biases_to_avoid[:4],  # Cap at 4 — prevents unbounded list growth
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
        "early_warning_notes": early_warning_notes[:5],
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
        "signal_importance": compute_signal_importance(rows),
        "confidence_calibration": compute_confidence_calibration(history),
        "competition_standing": derive_competition_posture(load_competition_standing_history(max_days=5)),
        "agent_accuracy": _agent_accuracy(history),
        "yesterday_postmortem": _build_postmortem(history),
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
            risk_level = (bear_cases.get(ticker) or {}).get("risk", "LOW")
            if risk_level == "HIGH":
                high_returns.append(float(ret))
            else:
                low_returns.append(float(ret))

    # Track repeat HIGH-flag offenders over the last 5 days (always computed)
    recent_high_flagged: dict[str, int] = {}
    for day in history[-5:]:
        bear_cases_day: dict = day.get("bear_cases", {}) or {}
        for ticker, info in bear_cases_day.items():
            if (info or {}).get("risk") == "HIGH":
                recent_high_flagged[ticker] = recent_high_flagged.get(ticker, 0) + 1
    high_flagged_tickers_recent = [
        {"ticker": t, "flag_count": n}
        for t, n in sorted(recent_high_flagged.items(), key=lambda x: -x[1])
        if n >= 2
    ]

    if not high_returns or not low_returns:
        return {
            "status": "insufficient_data",
            "observations": 0,
            "high_flagged_tickers_recent": high_flagged_tickers_recent,
        }

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
        "devil_is_accurate": accuracy >= 0.60 and len(high_returns) >= _MIN_STRONG_TICKER_OBSERVATIONS,
        "high_flagged_tickers_recent": high_flagged_tickers_recent,
    }


def _agent_accuracy(history: list[dict]) -> dict:
    """
    Compute virtual 1d returns for each agent's proposal vs the final portfolio.
    Uses pre-computed agent_returns_1d stored during _attach_outcomes_to_prior_record.
    """
    agent_buckets: dict[str, list[float]] = {"strategist": [], "challenger": [], "full_analyst": []}
    final_returns: list[float] = []

    for day in history:
        ar = day.get("agent_returns_1d", {})
        outcomes = (day.get("outcomes", {}) or {}).get("1d", {})
        final_ret = outcomes.get("portfolio_return")
        if final_ret is not None:
            final_returns.append(float(final_ret))
        for key in agent_buckets:
            val = ar.get(key)
            if val is not None:
                agent_buckets[key].append(float(val))

    final_avg = _avg(final_returns)
    result: dict[str, dict] = {}
    for key, returns in agent_buckets.items():
        if len(returns) < 3:
            result[key] = {"status": "insufficient_data", "observations": len(returns)}
            continue
        avg_ret = _avg(returns)
        result[key] = {
            "status": "actionable",
            "observations": len(returns),
            "avg_return_1d": round(avg_ret, 6),
            "vs_final_portfolio": round(avg_ret - final_avg, 6) if final_returns else None,
        }
    return result


def _build_postmortem(history: list[dict]) -> dict:
    """
    Specific post-mortem from the most recent day with position-level outcomes.
    Identifies which positions won/lost, their entry signals and rationale tags,
    and derives a one-line actionable lesson.
    """
    for day in reversed(history):
        outcomes = (day.get("outcomes", {}) or {}).get("1d", {})
        pos_returns = outcomes.get("position_returns", {})
        if not pos_returns:
            continue

        portfolio = day.get("final_portfolio", {})
        positions = portfolio.get("positions", [])
        signal_snap = day.get("signal_snapshot", {})
        benchmark = float(outcomes.get("benchmark_return", 0.0) or 0.0)

        winners: list[dict] = []
        losers: list[dict] = []
        for pos in positions:
            ticker = pos.get("ticker")
            ret = pos_returns.get(ticker)
            if ret is None:
                continue
            ret = float(ret)
            sig = signal_snap.get(ticker, {})
            entry = {
                "ticker": ticker,
                "return_1d": round(ret, 4),
                "vs_benchmark": round(ret - benchmark, 4),
                "tags": pos.get("tags", []),
                "rationale_snippet": (pos.get("rationale") or "")[:100],
                "rsi_at_entry": sig.get("rsi_14"),
                "vol_ratio_at_entry": sig.get("vol_ratio"),
            }
            (winners if ret >= 0 else losers).append(entry)

        winners.sort(key=lambda x: -x["return_1d"])
        losers.sort(key=lambda x: x["return_1d"])

        # Derive lesson: compare tag hit rates on winners vs losers
        winning_tags: dict[str, int] = {}
        losing_tags: dict[str, int] = {}
        for w in winners:
            for tag in w["tags"]:
                winning_tags[tag] = winning_tags.get(tag, 0) + 1
        for lo in losers:
            for tag in lo["tags"]:
                losing_tags[tag] = losing_tags.get(tag, 0) + 1

        # Build lesson string
        lesson_parts = []
        for tag, count in losing_tags.items():
            if count >= 2 and losing_tags.get(tag, 0) > winning_tags.get(tag, 0):
                lesson_parts.append(f"'{tag}' entries underperformed — review sizing for this thesis today")
        for tag, count in winning_tags.items():
            if count >= 2 and winning_tags.get(tag, 0) > losing_tags.get(tag, 0):
                lesson_parts.append(f"'{tag}' entries outperformed — continue favouring this setup")
        lesson = "; ".join(lesson_parts[:2]) if lesson_parts else "no strong tag signal"

        portfolio_return = float(outcomes.get("portfolio_return", 0.0) or 0.0)
        return {
            "date": day.get("date"),
            "portfolio_return_1d": round(portfolio_return, 4),
            "benchmark_return_1d": round(benchmark, 4),
            "alpha_1d": round(portfolio_return - benchmark, 4),
            "winners": winners,
            "losers": losers,
            "lesson": lesson,
        }

    return {}


def _changed_rules(previous: list[str], current: list[str]) -> list[str]:
    previous_set = set(previous)
    return [rule for rule in current if rule not in previous_set]


def derive_competition_posture(standings: list[dict]) -> dict:
    """
    Convert a history of competition standings into an actionable posture for today.

    Postures:
      DEFEND  — top 10%: protect the lead, avoid unnecessary tail risk
      CLIMB   — 11–35%: differentiated picks, high conviction, no filler
      CHASE   — 36–100%: concentrated high-beta; median rank = losing
    """
    if not standings:
        return {"status": "no_data"}

    latest = standings[-1]
    rank = latest.get("rank")
    total = latest.get("total")
    if not rank or not total or total == 0:
        return {"status": "no_data"}

    percentile = (rank - 1) / total * 100  # 0 = rank 1, 100 = last place

    if percentile <= 10:
        posture = "DEFEND"
        instruction = (
            f"You are in the TOP {percentile:.1f}% (rank {rank}/{total}). "
            "PROTECT this lead — a flat day when others lose is a win. "
            "Favour high-momentum names with strong risk/reward. "
            "Avoid extreme high-beta tail bets unless all signals are exceptional."
        )
    elif percentile <= 35:
        posture = "CLIMB"
        instruction = (
            f"You are in the top {percentile:.1f}% (rank {rank}/{total}). "
            "Well-positioned but you need to keep climbing to win. "
            "Favour differentiated picks over the consensus portfolio. "
            "No filler positions — every slot must earn its place."
        )
    else:
        posture = "CHASE"
        instruction = (
            f"You are at rank {rank}/{total} (bottom {100 - percentile:.1f}%). "
            f"Median rank = losing by design with {total} participants. "
            "You MUST take concentrated, differentiated, high-beta picks. "
            f"A well-diversified portfolio at this rank will finish near rank {rank}. "
            "Be aggressive — safe picks guarantee you lose."
        )

    # Rank trend: compare latest vs up to 5 days ago
    trend_text = "no prior data"
    if len(standings) >= 2:
        compare = standings[max(-5, -len(standings))]
        prev_rank = compare.get("rank")
        if prev_rank:
            delta = prev_rank - rank  # positive = climbing, negative = falling
            days = min(5, len(standings) - 1)
            if delta > 0:
                trend_text = f"improving (+{delta} positions over {days} day{'s' if days > 1 else ''})"
            elif delta < 0:
                trend_text = f"falling ({delta} positions over {days} day{'s' if days > 1 else ''})"
            else:
                trend_text = f"stagnant (no change over {days} day{'s' if days > 1 else ''})"

    return {
        "status": "actionable",
        "rank": rank,
        "total": total,
        "percentile_from_top": round(percentile, 1),
        "posture": posture,
        "instruction": instruction,
        "trend_text": trend_text,
        "date": latest.get("date"),
    }


def build_prompt_learning_context(
    strategy_text: str = "",
    fallback_sections: Optional[list[str]] = None,
    current_regime: str = "NEUTRAL",
) -> str:
    state = load_learning_state()
    fallback_sections = fallback_sections or []
    sections: list[str] = []

    if strategy_text:
        sections.append("=== PERMANENT STRATEGY PRINCIPLES (highest priority) ===\n" + strategy_text.strip())

    if state:
        lines = ["=== STRUCTURED LEARNING STATE (apply in priority order) ==="]
        standing = state.get("competition_standing", {})
        if standing.get("status") == "actionable":
            lines.append(
                f"COMPETITION STANDING ({standing['date']}, rank {standing['rank']}/{standing['total']}, "
                f"top {standing['percentile_from_top']}%, trend: {standing['trend_text']}):\n"
                f"  POSTURE: {standing['posture']} — {standing['instruction']}"
            )

        # Yesterday's post-mortem — specific wins/losses with entry signals
        pm = state.get("yesterday_postmortem", {})
        if pm.get("date") and (pm.get("winners") or pm.get("losers")):
            pm_lines = [
                f"YESTERDAY'S POST-MORTEM ({pm['date']}, portfolio {pm['portfolio_return_1d']:+.2%} "
                f"vs benchmark {pm['benchmark_return_1d']:+.2%}, alpha {pm['alpha_1d']:+.2%}):"
            ]
            if pm.get("winners"):
                winner_strs = [
                    f"{w['ticker']} {w['return_1d']:+.1%} [{','.join(w['tags'][:3])}]"
                    for w in pm["winners"][:3]
                ]
                pm_lines.append(f"  Winners: {' | '.join(winner_strs)}")
            if pm.get("losers"):
                loser_strs = [
                    f"{lo['ticker']} {lo['return_1d']:+.1%} [{','.join(lo['tags'][:3])}]"
                    for lo in pm["losers"][:3]
                ]
                pm_lines.append(f"  Losers: {' | '.join(loser_strs)}")
                # Inject a soft advisory for each loser to prevent reflexive doubling-down
                for lo in pm["losers"][:3]:
                    ret = lo["return_1d"]
                    if ret < -0.008:  # -0.8% threshold
                        pm_lines.append(
                            f"  SOFT ADVISORY: {lo['ticker']} returned {ret:+.1%} yesterday — "
                            f"do not allocate above 15% without vol_ratio > 1.0 confirmation."
                        )
            if pm.get("lesson"):
                pm_lines.append(f"  Lesson: {pm['lesson']}")
            lines.append("\n".join(pm_lines))

        # Per-agent accuracy — tell Risk Manager which agent to trust more
        aa = state.get("agent_accuracy", {})
        actionable_agents = {k: v for k, v in aa.items() if v.get("status") == "actionable"}
        if actionable_agents:
            agent_line_parts = []
            for agent, stats in sorted(actionable_agents.items(), key=lambda x: -x[1].get("avg_return_1d", 0)):
                vs = stats.get("vs_final_portfolio")
                vs_str = f", {vs:+.2%} vs final" if vs is not None else ""
                agent_line_parts.append(
                    f"{agent}: avg {stats['avg_return_1d']:+.2%}/day ({stats['observations']} obs{vs_str})"
                )
            best = max(actionable_agents, key=lambda k: actionable_agents[k].get("avg_return_1d", 0))
            lines.append(
                "Agent accuracy (virtual returns on own proposals, last N days):\n"
                + "\n".join(f"  {p}" for p in agent_line_parts)
                + f"\n  → {best.title()} has been most accurate recently — Risk Manager should weight its picks higher."
            )

        # Regime-specific signal importance
        sig_imp = state.get("signal_importance", {})
        regime_imp = (sig_imp.get("per_regime") or {}).get(current_regime, {})
        global_imp = sig_imp.get("global", {})
        if regime_imp:
            top_regime = sorted(regime_imp.items(), key=lambda x: -x[1])[:5]
            lines.append(
                f"Signal importance in {current_regime} regime (current) — directional accuracy vs next-day return:\n"
                + "  " + " | ".join(f"{s}: {v:.0%}" for s, v in top_regime)
                + "\n  Focus on high-accuracy signals above. Signals near 50% are no better than random."
            )
        elif global_imp:
            top_global = sorted(global_imp.items(), key=lambda x: -x[1])[:5]
            lines.append(
                "Signal importance (global, no regime breakdown yet):\n"
                + "  " + " | ".join(f"{s}: {v:.0%}" for s, v in top_global)
            )

        if state.get("hard_rules"):
            lines.append("Hard constraints:")
            lines.extend(f"- {rule}" for rule in state["hard_rules"][:4])
        if state.get("biases_to_avoid"):
            lines.append("Biases to avoid (MANDATORY):")
            lines.extend(
                f"- MANDATORY: DO NOT use this as a primary thesis driver today — {rule}"
                for rule in state["biases_to_avoid"][:3]
            )
        if state.get("early_warning_notes"):
            lines.append("Biases under watch (EARLY WARNING):")
            lines.extend(f"- {note}" for note in state["early_warning_notes"][:3])
        weight_caps = state.get("weight_caps", [])
        ticker_caps = [cap for cap in weight_caps if isinstance(cap, dict) and cap.get("scope") == "ticker"]
        rationale_tag_caps = [cap for cap in weight_caps if isinstance(cap, dict) and cap.get("scope") == "rationale_tag"]
        if ticker_caps:
            lines.append("Ticker weight caps (MANDATORY — code-enforced):")
            for cap in ticker_caps[:5]:
                ticker = cap.get("ticker")
                max_weight = cap.get("max_weight")
                reason = cap.get("reason", "learning_state_cap")
                if not isinstance(ticker, str):
                    continue
                try:
                    max_weight_float = float(max_weight)
                except (TypeError, ValueError):
                    continue
                lines.append(
                    f"- HARD CAP: {ticker} <= {max_weight_float:.0%} ({reason})"
                )
        if rationale_tag_caps:
            lines.append("Rationale-tag weight caps (MANDATORY — code-enforced for positions using these as primary thesis):")
            for cap in rationale_tag_caps[:4]:
                tag = cap.get("tag")
                max_weight = cap.get("max_weight")
                reason = cap.get("reason", "learning_state_cap")
                if not isinstance(tag, str):
                    continue
                try:
                    max_weight_float = float(max_weight)
                except (TypeError, ValueError):
                    continue
                lines.append(
                    f"- HARD CAP: positions with '{tag}' as primary thesis <= {max_weight_float:.0%} ({reason})"
                )
        winners = state.get("validated_winners", [])
        if winners:
            winner_tickers = [item["ticker"] for item in winners[:5]]
            lines.append(
                f"Validated winners — WINNER LOCKUP in effect for: {', '.join(winner_tickers)}. "
                "Do NOT drop these names without a clear signal deterioration: mom_5d turning negative, "
                "RSI < 50, or vs_index clearly negative. Do NOT exit a validated winner just because another "
                "name has marginally stronger signals today — the switching cost (T+1 fills) is real. "
                "Hold unless the thesis is broken, not merely slightly weaker:"
            )
            lines.extend(
                f"- {item['ticker']}: avg {item['avg_return_1d']:+.2%} over {item['observations']} obs"
                for item in winners[:5]
            )
        losers = state.get("recurring_losers", [])
        if losers:
            lines.append("Recurring losers:")
            lines.extend(
                f"- {item['ticker']}: avg {item['avg_return_1d']:+.2%} over {item['observations']} obs"
                for item in losers[:5]
            )
        devil = state.get("devil_accuracy", {})
        devil_repeat_flag_suppressed = False
        if devil.get("status") in ("actionable", "early_data") and devil.get("observations", 0) > 0:
            da = devil
            if da.get("devil_is_accurate"):
                lines.append(
                    f"Devil's advocate accuracy: HIGH-risk flags have been correct {da['high_risk_negative_rate']:.0%} of the time "
                    f"({da['observations']} obs). HIGH-risk picks avg {da['high_risk_avg_return_1d']:+.2%}/day vs "
                    f"LOW-risk {da['low_risk_avg_return_1d']:+.2%}/day. TREAT HIGH-RISK FLAGS AS A 10% WEIGHT CAP TODAY."
                )
            else:
                accuracy_rate = da.get("high_risk_negative_rate", 0)
                lines.append(
                    f"Devil's advocate accuracy so far: {accuracy_rate:.0%} of HIGH-risk flags went negative "
                    f"({da['observations']} obs, threshold for action: 60%). Use your own judgement on flagged picks."
                )
                # When Devil is clearly WRONG (accuracy < 40%), repeat flags are ANTI-signals —
                # explicitly tell agents NOT to penalise momentum picks the Devil has been flagging.
                if accuracy_rate < 0.40:
                    recent_flags = devil.get("high_flagged_tickers_recent", [])
                    if recent_flags:
                        flagged_str = ", ".join(f"{f['ticker']} (x{f['flag_count']})" for f in recent_flags[:5])
                        lines.append(
                            f"DEVIL OVERRIDE — accuracy {accuracy_rate:.0%} (<40%): the Devil has been WRONG on "
                            f"HIGH-risk flags. Repeat-flagged tickers {flagged_str} have been OUTPERFORMING — "
                            "do NOT cut conviction or reduce weight based on Devil HIGH flags for these names. "
                            "Size them by momentum and consensus signals alone."
                        )
                    devil_repeat_flag_suppressed = True
                else:
                    devil_repeat_flag_suppressed = False

        # Recent repeat flags shown when Devil accuracy is neutral (not clearly wrong)
        recent_flags = devil.get("high_flagged_tickers_recent", [])
        if (
            recent_flags
            and devil.get("status") in ("actionable", "early_data")
            and devil.get("observations", 0) > 0
            and not devil_repeat_flag_suppressed
        ):
            flagged_str = ", ".join(f"{f['ticker']} (x{f['flag_count']})" for f in recent_flags[:5])
            lines.append(
                f"Repeat HIGH-risk flags (last 5 days): {flagged_str}. "
                "These tickers have been Devil-flagged multiple times recently — size cautiously (<=12% each)."
            )
        cal = state.get("confidence_calibration", {})
        if cal.get("overconfidence_detected"):
            lines.append(
                f"Confidence calibration warning: high-confidence proposals (>=75%) have averaged "
                f"{cal['high_confidence_avg_return']:+.2%}/day vs {cal['low_confidence_avg_return']:+.2%}/day "
                f"for lower-confidence proposals ({cal['high_confidence_observations']} obs). "
                "Confidence > 0.75 has historically preceded worse outcomes — calibrate down today."
            )
        sections.append("\n".join(lines))

    if fallback_sections and not state:
        sections.extend(section for section in fallback_sections if section)

    if not sections:
        return ""
    return "=== LEARNING FROM PREVIOUS RUNS (use to improve today's picks) ===\n" + "\n\n".join(sections) + "\n=== END LEARNING ==="
