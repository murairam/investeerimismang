"""
Verification tracking system.

Tracks when the user last verified their portfolio sync.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_TRACKER_PATH = os.path.join(_ROOT, "verification_tracker.json")


def mark_verified(date: str) -> None:
    """Mark that verification was completed for a given date."""
    data = {
        "last_verified_date": date,
        "verified_at": datetime.now().isoformat(),
    }
    with open(_TRACKER_PATH, "w") as f:
        json.dump(data, f, indent=2)


def is_verified_today(today: str) -> bool:
    """Check if verification was done for today."""
    if not os.path.exists(_TRACKER_PATH):
        return False

    try:
        with open(_TRACKER_PATH, "r") as f:
            data = json.load(f)
        return data.get("last_verified_date") == today
    except Exception:
        return False


def get_last_verification() -> dict:
    """Get last verification info."""
    if not os.path.exists(_TRACKER_PATH):
        return {"verified": False, "last_date": None}

    try:
        with open(_TRACKER_PATH, "r") as f:
            data = json.load(f)
        return {
            "verified": True,
            "last_date": data.get("last_verified_date"),
            "verified_at": data.get("verified_at"),
        }
    except Exception:
        return {"verified": False, "last_date": None}
