"""
Mode guard for pre-game and live operation.

Behavior:
- Before game start date: PRE-GAME mode (training and experimentation allowed).
- On/after game start date: LIVE mode with strict parameter freeze.

In LIVE mode, protected strategy files are fingerprinted and locked. Any change
after lock creation raises an error to prevent accidental parameter drift.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime

from data.learning_report import generate_pregame_learning_report

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_LOCK_PATH = os.path.join(_ROOT, "live_mode_lock.json")
_GAME_START_DATE = "2026-04-06"
_PROTECTED_FILES = [
    "config.py",
    "docs/rules.txt",
    "agents/openai_strategist.py",
    "agents/gemini_challenger.py",
    "agents/openai_risk_manager.py",
]


def _parse_iso_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def _sha256_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _collect_fingerprints() -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for rel_path in _PROTECTED_FILES:
        abs_path = os.path.join(_ROOT, rel_path)
        if os.path.exists(abs_path):
            fingerprints[rel_path] = _sha256_file(abs_path)
    return fingerprints


def enforce_mode_and_freeze(as_of_date: str, game_start_date: str = _GAME_START_DATE) -> dict:
    current = _parse_iso_date(as_of_date)
    live_date = _parse_iso_date(game_start_date)

    if current < live_date:
        return {
            "mode": "PREGAME",
            "days_to_live": (live_date - current).days,
            "lock_status": "not_required",
        }

    current_fp = _collect_fingerprints()
    if not os.path.exists(_LOCK_PATH):
        payload = {
            "created_on": as_of_date,
            "game_start_date": game_start_date,
            "protected_files": _PROTECTED_FILES,
            "fingerprints": current_fp,
        }
        with open(_LOCK_PATH, "w") as f:
            json.dump(payload, f, indent=2)
        return {
            "mode": "LIVE",
            "days_to_live": 0,
            "lock_status": "initialized",
            "lock_path": _LOCK_PATH,
        }

    with open(_LOCK_PATH, "r") as f:
        locked = json.load(f)

    locked_fp = locked.get("fingerprints", {})
    changed_files = [
        rel for rel, sha in current_fp.items()
        if locked_fp.get(rel) != sha
    ]
    if changed_files:
        changed_list = ", ".join(changed_files)
        raise RuntimeError(
            "LIVE mode parameter freeze violation. "
            f"These protected files changed after lock: {changed_list}. "
            "If this was intentional, review carefully and recreate live_mode_lock.json manually."
        )

    return {
        "mode": "LIVE",
        "days_to_live": 0,
        "lock_status": "verified",
        "lock_path": _LOCK_PATH,
    }


def generate_live_handoff_if_due(as_of_date: str, game_start_date: str = _GAME_START_DATE) -> dict | None:
    current = _parse_iso_date(as_of_date)
    live_date = _parse_iso_date(game_start_date)
    if current < live_date:
        return None

    output_path = os.path.join(_ROOT, f"LIVE_HANDOFF_{game_start_date}.md")
    if os.path.exists(output_path):
        return {"generated": False, "path": output_path}

    summary = generate_pregame_learning_report(target_date=game_start_date)

    lines = [
        f"# Live Trading Handoff — {game_start_date}",
        "",
        "This document freezes pre-game learnings and marks transition to live mode.",
        "",
        "## Training outcome",
        f"- Avg daily alpha: {summary['avg_alpha']:+.2%}",
        f"- Paper return: {summary['paper_return']:+.2%}",
        f"- Max drawdown: {summary['max_drawdown']:.2%}",
        f"- Avg turnover: {summary['avg_turnover']:.2%}",
        "",
        "## Live mode rules",
        "- Protected strategy files are lock-checked on every run.",
        "- Parameter/prompt changes require explicit lock reset and review.",
        "- Keep reviewing DAILY_LOG.md and PREGAME_LEARNING.md signals each day.",
        "",
        "## First live-day checklist",
        "- Confirm API keys and Discord webhook are healthy.",
        "- Run `python main.py` and verify output completes without validation fallback loops.",
        "- Confirm portfolio updates are reflected in your real game submission process.",
        "",
    ]

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    return {"generated": True, "path": output_path}