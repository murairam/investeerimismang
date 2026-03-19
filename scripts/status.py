#!/usr/bin/env python3
"""
AlphaShark Status Dashboard

Shows:
- Project state (pregame/live mode)
- Cost tracking (OpenAI API spending)
- Learning progress (performance, meta-learning)
- File status (what's being written)
"""
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.game_availability import load_unavailable_tickers
from data.symbol_master import summarize_symbol_master
from data.universe_loader import load_game_universe
from data.verification_tracker import get_last_verification
from data.yahoo_symbols import get_eodhd_budget_status

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(filename):
    path = os.path.join(ROOT, filename)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    print("\n" + "=" * 70)
    print("🦈 AlphaShark Project Status Dashboard")
    print("=" * 70)

    # Mode & Timeline
    today = date.today()
    game_start = date.fromisoformat("2026-04-06")
    days_until_live = (game_start - today).days

    if days_until_live > 0:
        mode = "PREGAME (Training Mode)"
        status_icon = "📝"
    elif days_until_live == 0:
        mode = "LIVE (Game starts TODAY!)"
        status_icon = "🚨"
    else:
        mode = "LIVE (Game in progress)"
        status_icon = "🎯"

    print(f"\n{status_icon} Mode: {mode}")
    print(f"📅 Today: {today.isoformat()}")
    print(f"🎮 Game start: {game_start.isoformat()} ({days_until_live} days)")

    # Cost Tracking
    cost_log = load_json("cost_log.json")
    total_cost = cost_log.get("total_cost", 0.0)
    run_count = len(cost_log.get("runs", []))
    daily_breakdown = cost_log.get("daily_breakdown", {})

    print(f"\n💰 API Cost Tracking")
    print(f"   Total spent: ${total_cost:.4f}")
    print(f"   Total runs: {run_count}")
    if daily_breakdown:
        latest_date = max(daily_breakdown.keys())
        latest_cost = daily_breakdown[latest_date]
        print(f"   Latest run ({latest_date}): ${latest_cost:.4f}")
        print(f"   Average per run: ${total_cost/max(run_count,1):.4f}")

    # Learning Progress
    portfolio_history = load_json("portfolio_history.json")
    performance = portfolio_history.get("performance_history", [])

    if performance:
        wins = len([p for p in performance if p.get("alpha_1d", 0) > 0])
        losses = len([p for p in performance if p.get("alpha_1d", 0) < 0])
        avg_alpha = sum(p.get("alpha_1d", 0) for p in performance) / len(performance)

        print(f"\n📊 Performance Learning")
        print(f"   Training days: {len(performance)}")
        print(f"   Win days: {wins} | Loss days: {losses}")
        print(f"   Win rate: {wins/max(len(performance),1)*100:.1f}%")
        print(f"   Average daily alpha: {avg_alpha:+.2%}")
    else:
        print(f"\n📊 Performance Learning")
        print(f"   No performance data yet (run python main.py)")

    latest_record = (portfolio_history.get("history") or [])[-1] if portfolio_history.get("history") else None
    verification = get_last_verification()
    print(f"\n🗂️  Daily State")
    print(f"   Latest AI proposal date: {portfolio_history.get('date') or 'N/A'}")
    print(f"   Latest canonical provenance: {latest_record.get('provenance', 'N/A') if latest_record else 'N/A'}")
    print(f"   Latest verified date: {verification.get('last_date') or 'N/A'}")

    universe = load_game_universe()
    exclusions = load_unavailable_tickers()
    symbol_master = summarize_symbol_master()
    eodhd_budget = get_eodhd_budget_status()
    print(f"\n🌐 Game Universe")
    print(f"   Total tracked tickers: {sum(len(v) for v in universe.values())}")
    print(f"   By market: { {market: len(tickers) for market, tickers in universe.items()} }")
    print(f"   Manual game exclusions: {len(exclusions)}")
    print(f"   Symbol master: {symbol_master['total']} records ({symbol_master['status_counts']})")
    print(f"   EODHD budget: {eodhd_budget['used']}/{eodhd_budget['cap']} used today")

    # Paper Trading
    paper_account = load_json("paper_account.json")
    if paper_account:
        initial = paper_account.get("initial_capital", 10000)
        current = paper_account.get("last_equity", 10000)
        return_pct = (current - initial) / initial

        print(f"\n📒 Paper Trading Account")
        print(f"   Initial capital: €{initial:,.2f}")
        print(f"   Current equity: €{current:,.2f}")
        print(f"   Return: {return_pct:+.2%}")

    # Meta-Learning
    if os.path.exists(os.path.join(ROOT, "AI_SELF_CRITIQUE.md")):
        print(f"\n🧠 Meta-Learning (AI Self-Critique)")
        print(f"   Report generated: AI_SELF_CRITIQUE.md")
        print(f"   Run 'cat AI_SELF_CRITIQUE.md' to see insights")

    # Files Status
    print(f"\n📁 Data Files Status")
    files = [
        ("portfolio_history.json", "Portfolio decisions & P&L"),
        ("paper_account.json", "Virtual trading ledger"),
        ("PREGAME_LOG.md", "Canonical pregame daily log"),
        ("PREGAME_RUNS.md", "Pregame debug run log"),
        ("DAILY_LOG.md", "Human-readable decision log"),
        ("PREGAME_LEARNING.md", "Win rate & ticker lessons"),
        ("AI_SELF_CRITIQUE.md", "AI reasoning quality analysis"),
        ("cost_log.json", "OpenAI API spending tracker"),
    ]

    for filename, description in files:
        path = os.path.join(ROOT, filename)
        if os.path.exists(path):
            size = os.path.getsize(path)
            size_str = f"{size/1024:.1f}KB" if size > 1024 else f"{size}B"
            mod_time = datetime.fromtimestamp(os.path.getmtime(path))
            print(f"   ✅ {filename:<25} {size_str:<8} (updated {mod_time.strftime('%Y-%m-%d %H:%M')})")
            print(f"      → {description}")
        else:
            print(f"   ⚪ {filename:<25} (not created yet)")

    # Next Steps
    print(f"\n🎯 Next Steps")
    if days_until_live > 0:
        print(f"   1. System runs automatically Mon-Fri at 09:30 EEST")
        print(f"   2. One canonical daily record updates per day; rerun details can accumulate in PREGAME_RUNS.md")
        print(f"   3. Review progress: python scripts/status.py")
        print(f"   4. Check learning: cat PREGAME_LEARNING.md")
        print(f"   5. Check AI reasoning: cat AI_SELF_CRITIQUE.md")
        print(f"   6. On April 6, system switches to LIVE mode automatically")
    else:
        print(f"   1. Check Discord for daily portfolio recommendation")
        print(f"   2. Update game website before 10:00 EET")
        print(f"   3. Run: python scripts/verify.py to confirm sync")
        print(f"   4. Review meta-learning: cat AI_SELF_CRITIQUE.md")

    # Important Notes
    print(f"\n⚠️  Important Notes")
    if days_until_live > 0:
        print(f"   • Files ARE SUPPOSED to have data now (this is pregame training)")
        print(f"   • The AI needs {days_until_live} more days of learning before going live")
        print(f"   • Only one canonical record per date should drive learning")
    else:
        print(f"   • You are in LIVE mode - verify portfolio daily with: python scripts/verify.py")
        print(f"   • Game portfolio must be updated manually on the website")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
