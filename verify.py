"""
Daily portfolio verification tool.

Run this after updating your game portfolio to confirm the system's
record matches what you actually hold in the Äripäev/SEB game.

Usage:
    python verify.py          — show current portfolio + confirm / correct it
    python verify.py --show   — just print, no prompts
"""
import json
import os
import sys
from datetime import date
from typing import Optional

from data.verification_tracker import mark_verified

_STORE_PATH = os.path.join(os.path.dirname(__file__), "portfolio_history.json")


def load() -> Optional[dict]:
    if not os.path.exists(_STORE_PATH):
        return None
    with open(_STORE_PATH) as f:
        return json.load(f)


def save(data: dict) -> None:
    with open(_STORE_PATH, "w") as f:
        json.dump(data, f, indent=2)


def print_portfolio(data: dict) -> None:
    print()
    print(f"  AlphaShark — recorded portfolio (as of {data.get('date', '?')})")
    print(f"  {'#':<3} {'Ticker':<12} {'Weight':>8}  Rationale")
    print("  " + "-" * 70)
    total = 0.0
    for i, p in enumerate(data.get("positions", []), 1):
        w = p["weight"]
        total += w
        rationale = p.get("rationale", "")[:50]
        print(f"  {i:<3} {p['ticker']:<12} {w:>7.1%}  {rationale}")
    print("  " + "-" * 70)
    print(f"  {'TOTAL':<16} {total:>7.1%}")
    print(f"\n  Thesis: {data.get('reasoning', 'N/A')}")
    print()


def main() -> None:
    show_only = "--show" in sys.argv

    data = load()
    if data is None:
        print("\n  No portfolio on record yet. Run python main.py first.\n")
        return

    print_portfolio(data)

    if show_only:
        return

    print("  Does this match your actual game portfolio? (y = yes / n = no / e = edit)")
    answer = input("  > ").strip().lower()

    if answer == "y":
        mark_verified(data.get("date", date.today().isoformat()))
        print("\n  ✅ Portfolio confirmed. Record is up to date.\n")

    elif answer == "n":
        print("\n  The system will use its record for tomorrow's decisions.")
        print("  If your game portfolio is VERY different, you can reset it.")
        print("  Reset and re-enter from scratch? (y = reset / any key = keep)")
        if input("  > ").strip().lower() == "y":
            _enter_manual(data)

    elif answer == "e":
        _enter_manual(data)

    else:
        print("\n  Skipped.\n")


def _enter_manual(existing: dict) -> None:
    """Let the user type in their actual game portfolio."""
    print()
    print("  Enter your actual game portfolio below.")
    print("  Format per line:  TICKER WEIGHT%   (e.g. NVDA 20)")
    print("  Empty line when done.")
    print()

    positions = []
    while True:
        line = input("  > ").strip()
        if not line:
            break
        parts = line.split()
        if len(parts) != 2:
            print("  Bad format — use: TICKER WEIGHT  (e.g. NVDA 20)")
            continue
        ticker = parts[0].upper()
        try:
            weight = float(parts[1].replace("%", "")) / 100
        except ValueError:
            print("  Weight must be a number (e.g. 20 for 20%)")
            continue
        positions.append({"ticker": ticker, "weight": weight, "rationale": "manually entered"})

    if not positions:
        print("  Nothing entered — keeping existing record.\n")
        return

    total = sum(p["weight"] for p in positions)
    print(f"\n  Entered {len(positions)} positions, total {total:.1%}")

    data = {
        "date": date.today().isoformat(),
        "positions": positions,
        "reasoning": existing.get("reasoning", "manually entered portfolio"),
        "confidence": existing.get("confidence", 0.5),
    }
    save(data)
    mark_verified(data["date"])
    print("  ✅ Saved. The system will use this as the baseline for tomorrow.\n")


if __name__ == "__main__":
    main()
