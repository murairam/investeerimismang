"""
Helpers for game-specific ticker availability overrides.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_EXCLUSIONS_PATH = os.path.join(_ROOT, "game_exclusions.json")


def load_unavailable_tickers() -> dict[str, str]:
    if not os.path.exists(_EXCLUSIONS_PATH):
        return {}
    try:
        with open(_EXCLUSIONS_PATH, "r") as f:
            data = json.load(f)
        unavailable = data.get("unavailable_tickers", {})
        return {
            str(ticker).upper(): str(reason)
            for ticker, reason in unavailable.items()
            if str(ticker).strip()
        }
    except Exception as exc:
        logger.warning("Could not load game exclusions: %s", exc)
        return {}


def filter_unavailable_tickers(universe: dict[str, list[str]]) -> dict[str, list[str]]:
    unavailable = load_unavailable_tickers()
    if not unavailable:
        return universe

    filtered: dict[str, list[str]] = {}
    removed_total = 0
    for market, tickers in universe.items():
        kept = [ticker for ticker in tickers if ticker.upper() not in unavailable]
        removed_total += len(tickers) - len(kept)
        filtered[market] = kept

    if removed_total:
        logger.info(
            "Filtered %d unavailable game tickers from configured universe",
            removed_total,
        )
    return filtered
