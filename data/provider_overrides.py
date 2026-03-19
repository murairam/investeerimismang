"""
Per-ticker market-data provider overrides.
"""
from __future__ import annotations

import json
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_OVERRIDES_PATH = os.path.join(_ROOT, "provider_overrides.json")


def load_provider_overrides() -> dict[str, dict]:
    if not os.path.exists(_OVERRIDES_PATH):
        return {}
    try:
        with open(_OVERRIDES_PATH, "r") as f:
            data = json.load(f)
        overrides = data.get("tickers", {})
        return {
            str(ticker).upper(): value
            for ticker, value in overrides.items()
            if str(ticker).strip() and isinstance(value, dict)
        }
    except Exception:
        return {}


def get_provider_override(ticker: str) -> dict:
    return load_provider_overrides().get(ticker.upper(), {})
