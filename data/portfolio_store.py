"""
Persist and load the last accepted portfolio proposal.
"""
import json
import logging
import os
from typing import Optional

from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

_STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio_history.json")


def load_last() -> Optional[PortfolioProposal]:
    """Load the most recent saved portfolio, or None if no history exists."""
    path = os.path.abspath(_STORE_PATH)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
        positions = [
            Position(
                ticker=p["ticker"],
                weight=float(p["weight"]),
                rationale=p.get("rationale", ""),
            )
            for p in data.get("positions", [])
        ]
        proposal = PortfolioProposal(
            positions=positions,
            reasoning=data.get("reasoning", ""),
            confidence=float(data.get("confidence", 0.5)),
        )
        logger.info("Loaded previous portfolio (%d positions) from %s", len(positions), data.get("date", "?"))
        return proposal
    except Exception as exc:
        logger.warning("Could not load portfolio history: %s", exc)
        return None


def save(proposal: PortfolioProposal, date: str) -> None:
    """Save portfolio to portfolio_history.json."""
    path = os.path.abspath(_STORE_PATH)
    data = {
        "date": date,
        "positions": [
            {"ticker": p.ticker, "weight": p.weight, "rationale": p.rationale}
            for p in proposal.positions
        ],
        "reasoning": proposal.reasoning,
        "confidence": proposal.confidence,
    }
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Saved portfolio to %s", path)
    except Exception as exc:
        logger.warning("Could not save portfolio history: %s", exc)
