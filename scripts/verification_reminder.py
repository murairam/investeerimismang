"""
Verification reminder script.

Checks if portfolio verification was done today.
If not, sends a Discord reminder.

This is called by GitHub Actions 30 minutes after the main run.
Runs in both pregame (mock game) and live mode.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from data.mode_guard import enforce_mode_and_freeze
from data.verification_tracker import is_verified_today


def send_discord_reminder(webhook_url: str, pregame: bool = False) -> None:
    """Send a Discord reminder that verification is needed."""
    mode_label = "📝 PREGAME" if pregame else "🔴 LIVE"
    payload = {
        "embeds": [{
            "title": f"⚠️ Portfolio Verification Reminder  {mode_label}",
            "description": (
                "**You haven't verified your portfolio yet today.**\n\n"
                "Without verification, tomorrow's AI decisions may be based on outdated holdings."
            ),
            "fields": [
                {
                    "name": "Do This Now",
                    "value": (
                        "1. Open the game portfolio.\n"
                        "2. Confirm it matches the latest AlphaShark recommendation.\n"
                        "3. Run `python scripts/verify.py`."
                    ),
                    "inline": False,
                },
                {
                    "name": "Deadline",
                    "value": "**10:00 EET**",
                    "inline": True,
                },
                {
                    "name": "Why It Matters",
                    "value": "Verification keeps tomorrow's learning and portfolio decisions synced with reality.",
                    "inline": True,
                },
            ],
            "color": 0xF39C12 if pregame else 0xE74C3C,  # Orange for pregame, red for live
        }]
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ Reminder sent to Discord")
    except Exception as e:
        print(f"❌ Failed to send Discord reminder: {e}", file=sys.stderr)


def main() -> None:
    today_str = date.today().isoformat()

    mode_info = enforce_mode_and_freeze(today_str, game_start_date="2026-04-06")
    is_pregame = mode_info["mode"] != "LIVE"

    # Check if verification was done
    if is_verified_today(today_str):
        print(f"✅ Portfolio verified for {today_str} - no reminder needed")
        return

    # Send reminder
    mode_str = f"pregame ({mode_info['days_to_live']} days to live)" if is_pregame else "live"
    print(f"⚠️ Portfolio NOT verified for {today_str} ({mode_str}) - sending Discord reminder...")

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("❌ DISCORD_WEBHOOK_URL not set", file=sys.stderr)
        return

    send_discord_reminder(webhook_url, pregame=is_pregame)


if __name__ == "__main__":
    main()
