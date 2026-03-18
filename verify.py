"""
verify.py — Sync your actual game portfolio to the learning loop.

Run this AFTER you update your portfolio on the game website.
It saves your real holdings as the verified source of truth so
tomorrow's P&L tracking (and AI learning) reflects actual performance,
not the AI's hypothetical suggestions.

Usage:
    python verify.py                  # shows current AI proposal, prompts for confirmation
    python verify.py --auto           # auto-confirms AI proposal as verified (if you followed it exactly)
"""
import argparse
import json
import logging
import os
import sys
from datetime import date

import yfinance as yf

from data.portfolio_store import _STORE_PATH, save_verified

logging.basicConfig(level=logging.WARNING)

_STORE_ABS = os.path.abspath(_STORE_PATH)


def _load_current() -> dict:
    if not os.path.exists(_STORE_ABS):
        print("No portfolio_history.json found. Run main.py first.")
        sys.exit(1)
    with open(_STORE_ABS) as f:
        return json.load(f)


def _fetch_prices(tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    try:
        data = yf.download(tickers, period="2d", auto_adjust=True, progress=False)
        close = data["Close"] if "Close" in data else data
        prices = {}
        for t in tickers:
            if t in close.columns:
                s = close[t].dropna()
                if not s.empty:
                    prices[t] = float(s.iloc[-1])
        return prices
    except Exception as exc:
        print(f"Warning: could not fetch prices ({exc})")
        return {}


def _print_portfolio(positions: list[dict], label: str) -> None:
    print(f"\n{label}")
    print(f"  {'Ticker':<14} {'Weight':>8}")
    print("  " + "-" * 25)
    for p in positions:
        print(f"  {p['ticker']:<14} {p['weight']:>7.1%}")
    print(f"  {'TOTAL':<14} {sum(p['weight'] for p in positions):>7.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify actual game portfolio")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-confirm: treat today's AI proposal as verified")
    args = parser.parse_args()

    state = _load_current()
    today = date.today().isoformat()
    saved_date = state.get("date", "")
    saved_source = state.get("source", "ai")
    saved_positions = state.get("positions", [])

    print(f"\n=== AlphaShark Portfolio Verification — {today} ===")

    if saved_source == "verified" and saved_date == today:
        _print_portfolio(saved_positions, f"Already verified today ({today}):")
        print("\nTo re-verify with different positions, enter them below.")
        print("Press Ctrl+C to keep the existing verified portfolio.")

    if saved_date != today:
        print(f"\nNote: last saved portfolio is from {saved_date} (no run yet today).")

    _print_portfolio(saved_positions, "Current AI proposal / saved portfolio:")

    if args.auto:
        # Trust the AI proposal — mark it as verified as-is
        verified_positions = [
            {"ticker": p["ticker"], "weight": float(p["weight"])}
            for p in saved_positions
        ]
        print("\n--auto flag: marking AI proposal as verified.")
    else:
        print("\nEnter your ACTUAL game portfolio.")
        print("Press Enter to keep a ticker at the suggested weight.")
        print("Type 0 to remove a ticker. Type a weight (e.g. 0.15) to change it.")
        print("Type 'add TICKER WEIGHT' to add a new position (e.g. 'add AAPL 0.10').")
        print("Type 'done' when finished.\n")

        working = {p["ticker"]: float(p["weight"]) for p in saved_positions}

        for ticker, weight in list(working.items()):
            try:
                raw = input(f"  {ticker:<14} {weight:.1%}  → ").strip()
            except EOFError:
                break
            if not raw:
                continue
            try:
                new_weight = float(raw)
                if new_weight == 0:
                    del working[ticker]
                    print(f"    Removed {ticker}")
                else:
                    working[ticker] = new_weight
            except ValueError:
                if raw.lower().startswith("add "):
                    parts = raw.split()
                    if len(parts) == 3:
                        working[parts[1].upper()] = float(parts[2])
                        print(f"    Added {parts[1].upper()} at {float(parts[2]):.1%}")

        # Handle any "add" commands after the loop
        while True:
            try:
                raw = input("  add more? (ticker weight, or done): ").strip().lower()
            except EOFError:
                break
            if raw in ("done", ""):
                break
            parts = raw.split()
            if len(parts) == 2:
                try:
                    working[parts[0].upper()] = float(parts[1])
                    print(f"    Added {parts[0].upper()} at {float(parts[1]):.1%}")
                except ValueError:
                    pass

        total = sum(working.values())
        if abs(total - 1.0) > 0.05:
            print(f"\nWarning: total weight is {total:.1%} (expected ~100%). Continuing anyway.")

        verified_positions = [
            {"ticker": t, "weight": w} for t, w in working.items()
        ]

    _print_portfolio(verified_positions, "\nVerified portfolio to save:")
    tickers = [p["ticker"] for p in verified_positions]
    print("\nFetching current prices for tomorrow's P&L tracking...")
    prices = _fetch_prices(tickers)

    save_verified(verified_positions, today, close_prices=prices)

    print(f"\n✅ Portfolio verified and saved for {today}.")
    print("   Tomorrow's P&L will track these exact holdings.")
    print("   The AI learning loop now reflects your real game performance.\n")


if __name__ == "__main__":
    main()
