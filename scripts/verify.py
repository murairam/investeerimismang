"""
Daily portfolio verification tool.

Run this after updating your game portfolio to confirm the system's
record matches what you actually hold in the Äripäev/SEB game.

Usage:
    python verify.py                                      — show + confirm interactively
    python verify.py --show                               — print only, no prompts
    python verify.py --input "EQNR.OL 25, APA 20" --equity 9978   — one-liner confirm
"""
import json
import os
import sys
from datetime import date
from typing import Optional

# Ensure project root is on the path regardless of where the script is invoked from
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from output.dispatcher import GAME_NAMES
from data.symbol_master import load_symbol_master

def _norm(s: str) -> str:
    """Lowercase + replace Nordic chars so 'maersk' matches 'Mærsk', 'orsted' matches 'Ørsted'."""
    s = s.lower()
    for old, new in [("æ", "ae"), ("ø", "o"), ("å", "a"), ("ö", "o"), ("ä", "a"), ("ü", "u")]:
        s = s.replace(old, new)
    return s


def _build_name_map() -> dict[str, str]:
    """Reverse map: normalised name → ticker, from GAME_NAMES + full symbol master."""
    result: dict[str, str] = {_norm(name): ticker for ticker, name in GAME_NAMES.items()}
    master = load_symbol_master()
    for ticker, record in master.get("tickers", {}).items():
        name = record.get("company_name", "")
        if name:
            result[_norm(name)] = ticker
    return result


# Reverse map: normalised game name → ticker
_NAME_TO_TICKER: dict[str, str] = _build_name_map()


def _resolve_ticker(raw: str) -> Optional[str]:
    """
    Accept a ticker symbol OR a game display name and return the canonical ticker.
    Tries exact match first, then prefix/substring match on normalised game names.
    """
    # Exact ticker match (e.g. "CVX", "MAERSK-B.CO")
    upper = raw.upper()
    if upper in GAME_NAMES:
        return upper

    normed = _norm(raw)

    # Exact normalised name match
    if normed in _NAME_TO_TICKER:
        return _NAME_TO_TICKER[normed]

    # Prefix match (e.g. "maersk" → "a.p. moller - maersk b")
    matches = [t for name, t in _NAME_TO_TICKER.items() if name.startswith(normed)]
    if len(matches) == 1:
        return matches[0]

    # Substring match (e.g. "alfa" → "alfa laval")
    matches = [t for name, t in _NAME_TO_TICKER.items() if normed in name]
    if len(matches) == 1:
        return matches[0]

    return None

from data.portfolio_store import save_verified
from data.verification_tracker import mark_verified
from data.paper_account import sync_verified_positions
from data.diary import mark_verified_entry

_STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio_history.json")


def load() -> Optional[dict]:
    if not os.path.exists(_STORE_PATH):
        return None
    with open(_STORE_PATH) as f:
        return json.load(f)


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


def _parse_input_arg() -> Optional[str]:
    for i, arg in enumerate(sys.argv):
        if arg == "--input" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def _parse_equity_arg() -> Optional[float]:
    for i, arg in enumerate(sys.argv):
        if arg == "--equity" and i + 1 < len(sys.argv):
            try:
                return float(sys.argv[i + 1].replace(",", ".").replace("€", "").strip())
            except ValueError:
                pass
    return None


def _input_from_string(raw: str, equity: Optional[float]) -> None:
    """Parse 'TICKER WEIGHT, TICKER WEIGHT, …' and save directly."""
    positions = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.rsplit(None, 1)
        if len(parts) != 2:
            print(f"  Bad entry '{entry}' — expected 'TICKER WEIGHT'")
            sys.exit(1)
        name_raw, weight_raw = parts
        try:
            weight = float(weight_raw.replace("%", "")) / 100
        except ValueError:
            print(f"  Bad weight '{weight_raw}'")
            sys.exit(1)
        ticker = _resolve_ticker(name_raw.strip())
        if ticker is None:
            print(f"  ❓ Could not recognise '{name_raw}' — use the ticker symbol directly")
            sys.exit(1)
        game_name = GAME_NAMES.get(ticker, ticker)
        print(f"  ✓ {game_name} ({ticker}) {weight:.0%}")
        positions.append({"ticker": ticker, "weight": weight, "rationale": "manually entered"})

    total = sum(p["weight"] for p in positions)
    print(f"\n  {len(positions)} positions, total {total:.1%}")

    if equity is None:
        equity = _ask_equity()

    today = date.today().isoformat()
    save_verified(positions, today)

    price_map = _fetch_prices([p["ticker"] for p in positions])
    if price_map and equity > 0:
        sync_verified_positions(positions, equity, today, price_map)
        print(f"  Paper account synced: equity €{equity:.0f}, {len(price_map)} prices fetched.")
    else:
        print("  ⚠️  Could not fetch prices — paper account not updated.")

    mark_verified(today)
    mark_verified_entry(today, mode=_mode_for_date(today))
    print("  ✅ Saved.\n")


def main() -> None:
    show_only = "--show" in sys.argv
    input_str = _parse_input_arg()

    if input_str is not None:
        equity = _parse_equity_arg()
        _input_from_string(input_str, equity)
        return

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
        today = date.today().isoformat()
        save_verified(data.get("positions", []), today, close_prices=data.get("close_prices"))
        mark_verified(today)
        mark_verified_entry(today, mode=_mode_for_date(today))
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


def _ask_equity() -> float:
    print("  What is your current game portfolio value in EUR? (e.g. 9965)")
    raw = input("  > ").strip().replace(",", ".").replace("€", "").replace("EUR", "").strip()
    try:
        return float(raw)
    except ValueError:
        print("  Could not parse — using 10000 as fallback.")
        return 10000.0


def _fetch_prices(tickers: list[str]) -> dict[str, float]:
    try:
        import yfinance as yf
        print(f"  Fetching prices for {len(tickers)} tickers…")
        raw = yf.download(tickers, period="2d", auto_adjust=True, progress=False)
        close = raw["Close"] if "Close" in raw else raw
        price_map: dict[str, float] = {}
        for t in tickers:
            if t in close.columns:
                series = close[t].dropna()
                if not series.empty:
                    price_map[t] = float(series.iloc[-1])
        return price_map
    except Exception as exc:
        print(f"  Price fetch failed: {exc}")
        return {}


def _enter_manual(existing: dict) -> None:
    """Let the user type in their actual game portfolio."""
    print()
    print("  Enter your actual game portfolio below.")
    print("  Format per line:  NAME WEIGHT   (e.g. 'Chevron 20' or 'CVX 20')")
    print("  Stock names can be partial (e.g. 'maersk 24', 'alfa 5', 'exxon 12')")
    print("  Empty line when done.")
    print()

    positions = []
    while True:
        line = input("  > ").strip()
        if not line:
            break
        # Split on last whitespace-separated token as weight, rest is name
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            print("  Bad format — e.g. 'Chevron 20' or 'maersk 24'")
            continue
        name_raw, weight_raw = parts
        try:
            weight = float(weight_raw.replace("%", "")) / 100
        except ValueError:
            print("  Weight must be a number (e.g. 20 for 20%)")
            continue
        ticker = _resolve_ticker(name_raw.strip())
        if ticker is None:
            print(f"  ❓ Could not recognise '{name_raw}' — try the ticker symbol (e.g. MAERSK-B.CO)")
            continue
        game_name = GAME_NAMES.get(ticker, ticker)
        print(f"     ✓ {game_name} ({ticker}) {weight:.0%}")
        positions.append({"ticker": ticker, "weight": weight, "rationale": "manually entered"})

    if not positions:
        print("  Nothing entered — keeping existing record.\n")
        return

    total = sum(p["weight"] for p in positions)
    print(f"\n  Entered {len(positions)} positions, total {total:.1%}")

    equity = _ask_equity()

    today = date.today().isoformat()
    save_verified(positions, today)

    # Also sync paper account so equity tracking matches the real game
    price_map = _fetch_prices([p["ticker"] for p in positions])
    if price_map and equity > 0:
        sync_verified_positions(positions, equity, today, price_map)
        print(f"  Paper account synced: equity €{equity:.0f}, {len(price_map)} prices fetched.")
    else:
        print("  ⚠️  Could not fetch prices — paper account not updated.")

    mark_verified(today)
    mark_verified_entry(today, mode=_mode_for_date(today))
    print("  ✅ Saved. The system will use this as the baseline for tomorrow.\n")


def _mode_for_date(day: str) -> str:
    return "LIVE" if day >= "2026-04-06" else "PREGAME"


if __name__ == "__main__":
    main()
