"""
Verification reminder script.

Checks if portfolio verification was done today.
If not, sends a Discord reminder.

This is called by GitHub Actions 30 minutes after the main run.
"""
import os
import sys
from datetime import date

import requests

from data.mode_guard import enforce_mode_and_freeze
from data.verification_tracker import is_verified_today


def send_discord_reminder(webhook_url: str) -> None:
    """Send a Discord reminder that verification is needed."""
    payload = {
        "embeds": [{
            "title": "⚠️ Portfolio Verification Reminder",
            "description": (
                "**You haven't verified your portfolio yet today!**\n\n"
                "Please:\n"
                "1. Confirm your game portfolio matches the recommendation\n"
                "2. Run `python verify.py` to sync the system\n\n"
                "⏰ **Deadline: 10:00 EEST**\n\n"
                "Without verification, tomorrow's AI decisions may be based on outdated data."
            ),
            "color": 0xE74C3C,  # Red
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

    # Check if we're in LIVE mode (only send reminders after April 6)
    mode_info = enforce_mode_and_freeze(today_str, game_start_date="2026-04-06")

    if mode_info["mode"] != "LIVE":
        print(f"📝 Pregame mode - no verification needed (days to live: {mode_info['days_to_live']})")
        return

    # Check if verification was done
    if is_verified_today(today_str):
        print(f"✅ Portfolio verified for {today_str} - no reminder needed")
        return

    # Send reminder
    print(f"⚠️ Portfolio NOT verified for {today_str} - sending Discord reminder...")

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("❌ DISCORD_WEBHOOK_URL not set", file=sys.stderr)
        return

    send_discord_reminder(webhook_url)


if __name__ == "__main__":
    main()
