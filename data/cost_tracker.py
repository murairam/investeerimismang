"""
OpenAI cost tracking.

Tracks token usage and costs for each agent run.
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Optional

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_COST_LOG_PATH = os.path.join(_ROOT, "cost_log.json")

# OpenAI pricing (as of Jan 2025)
PRICING = {
    "gpt-4o": {
        "input": 2.50 / 1_000_000,   # $2.50 per 1M input tokens
        "output": 10.0 / 1_000_000,  # $10.00 per 1M output tokens
    },
    "gpt-4o-mini": {
        "input": 0.150 / 1_000_000,  # $0.15 per 1M input tokens
        "output": 0.600 / 1_000_000, # $0.60 per 1M output tokens
    },
    "gemini-2.0-flash-exp": {
        "input": 0.0,  # Free tier (1500 req/day)
        "output": 0.0,
    },
}


def _safe_load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {"runs": [], "total_cost": 0.0}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {"runs": [], "total_cost": 0.0}


def log_usage(
    agent_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    run_date: Optional[str] = None,
) -> float:
    """
    Log token usage and return the cost for this call.

    Args:
        agent_name: e.g., "OpenAIStrategist", "OpenAIRiskManager"
        model: e.g., "gpt-4o", "gpt-4o-mini"
        input_tokens: number of input tokens
        output_tokens: number of output tokens
        run_date: ISO date string (defaults to today)

    Returns:
        Cost in USD for this call
    """
    if run_date is None:
        run_date = date.today().isoformat()

    pricing = PRICING.get(model, {"input": 0.0, "output": 0.0})
    cost = input_tokens * pricing["input"] + output_tokens * pricing["output"]

    data = _safe_load_json(_COST_LOG_PATH)

    data["runs"].append({
        "date": run_date,
        "agent": agent_name,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
    })

    data["total_cost"] = round(data.get("total_cost", 0.0) + cost, 6)

    with open(_COST_LOG_PATH, "w") as f:
        json.dump(data, f, indent=2)

    return cost


def get_total_cost() -> dict:
    """
    Get cumulative cost statistics.

    Returns:
        dict with keys: total_cost, run_count, daily_breakdown
    """
    data = _safe_load_json(_COST_LOG_PATH)

    runs = data.get("runs", [])
    total_cost = data.get("total_cost", 0.0)

    # Daily breakdown
    daily_costs = {}
    for run in runs:
        d = run.get("date", "unknown")
        daily_costs[d] = daily_costs.get(d, 0.0) + run.get("cost_usd", 0.0)

    # Agent breakdown
    agent_costs = {}
    for run in runs:
        agent = run.get("agent", "unknown")
        agent_costs[agent] = agent_costs.get(agent, 0.0) + run.get("cost_usd", 0.0)

    return {
        "total_cost": round(total_cost, 4),
        "run_count": len(runs),
        "daily_breakdown": {d: round(c, 4) for d, c in sorted(daily_costs.items())},
        "agent_breakdown": {a: round(c, 4) for a, c in sorted(agent_costs.items())},
        "log_path": _COST_LOG_PATH,
    }


def print_cost_summary() -> None:
    """Print a human-readable cost summary."""
    summary = get_total_cost()

    print("\n" + "=" * 60)
    print("💰 AlphaShark Cost Summary")
    print("=" * 60)
    print(f"Total runs: {summary['run_count']}")
    print(f"Total cost: ${summary['total_cost']:.4f}\n")

    print("Daily breakdown:")
    for day, cost in summary['daily_breakdown'].items():
        print(f"  {day}: ${cost:.4f}")

    print("\nAgent breakdown:")
    for agent, cost in summary['agent_breakdown'].items():
        print(f"  {agent}: ${cost:.4f}")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    print_cost_summary()
