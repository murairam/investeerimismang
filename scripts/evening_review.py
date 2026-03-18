"""
Evening portfolio review.

Runs at 21:00 EET Mon-Fri. Fetches current prices, computes today's
return vs benchmark, and sends a Discord summary with an AI recommendation.

By 21:00 EET:
  - Baltic / Scandinavian markets: closed → final prices
  - US markets: still open (close 23:00 EET / 22:00 EEST) → intraday prices
"""
import json
import logging
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

_PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio_history.json")
_BENCHMARK = "^GSPC"
_EMBED_COLOUR = 0x3498DB  # Blue


def _load_portfolio() -> dict | None:
    path = os.path.abspath(_PORTFOLIO_PATH)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _fetch_prices(tickers: list[str]) -> dict[str, tuple[float, float]]:
    """Return {ticker: (prev_close, latest_price)} for each ticker."""
    all_tickers = list(set(tickers + [_BENCHMARK]))
    raw = yf.download(
        tickers=all_tickers,
        period="5d",
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    close = raw["Close"] if "Close" in raw else raw

    result: dict[str, tuple[float, float]] = {}
    for t in all_tickers:
        if t not in close.columns:
            continue
        series = close[t].dropna()
        if len(series) < 2:
            continue
        result[t] = (float(series.iloc[-2]), float(series.iloc[-1]))
    return result


def _ai_take(positions_summary: str, portfolio_ret: float, benchmark_ret: float, alpha: float) -> str:
    """One-sentence AI recommendation via OpenAI gpt-4o-mini (~$0.0005/call)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "_AI recommendation unavailable (no API key)._"
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise trading advisor for a stock market game. "
                        "Give direct, actionable advice in exactly 1-2 sentences. No fluff."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Portfolio today: {portfolio_ret:+.2%}, "
                        f"benchmark: {benchmark_ret:+.2%}, alpha: {alpha:+.2%}.\n"
                        f"Position returns: {positions_summary}\n\n"
                        "Should I update my portfolio for tomorrow? "
                        "Name any specific positions worth dropping or keeping."
                    ),
                },
            ],
            max_tokens=90,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("AI take failed: %s", exc)
        return "_AI recommendation unavailable._"


def _send(embed: dict, webhook_url: str) -> None:
    resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
    resp.raise_for_status()
    logger.info("Evening review sent to Discord (status %d)", resp.status_code)


def main() -> None:
    portfolio = _load_portfolio()
    if not portfolio:
        logger.error("No portfolio found — run main.py first")
        return

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.error("DISCORD_WEBHOOK_URL not set")
        return

    positions = portfolio.get("positions", [])
    if not positions:
        logger.error("Portfolio has no positions")
        return

    tickers = [p["ticker"] for p in positions]
    prices = _fetch_prices(tickers)

    # Compute per-position and aggregate returns
    pos_returns: list[tuple[str, float, float, float]] = []  # (ticker, weight, return, price)
    portfolio_ret = 0.0
    for p in positions:
        t, w = p["ticker"], float(p["weight"])
        if t not in prices:
            logger.warning("No price data for %s — skipping", t)
            continue
        prev, curr = prices[t]
        ret = (curr / prev - 1) if prev > 0 else 0.0
        pos_returns.append((t, w, ret, curr))
        portfolio_ret += w * ret

    benchmark_ret = 0.0
    if _BENCHMARK in prices:
        prev, curr = prices[_BENCHMARK]
        benchmark_ret = (curr / prev - 1) if prev > 0 else 0.0

    alpha = portfolio_ret - benchmark_ret

    # Sort by return descending for easy scanning on mobile
    pos_returns.sort(key=lambda x: x[2], reverse=True)

    # Position table
    rows = ["```", f"{'Ticker':<12} {'Wt':>5}  {'Today':>7}  Price", "-" * 38]
    for ticker, weight, ret, price in pos_returns:
        arrow = "▲" if ret > 0.001 else ("▼" if ret < -0.001 else " ")
        rows.append(f"{ticker:<12} {weight:>4.0%}  {arrow}{abs(ret):>5.1%}  {price:.2f}")
    rows.append("```")
    table = "\n".join(rows)

    # Performance headline
    alpha_emoji = "🟢" if alpha > 0.003 else ("🔴" if alpha < -0.003 else "🟡")
    perf_line = (
        f"**Today:** {portfolio_ret:+.2%} portfolio · "
        f"{benchmark_ret:+.2%} benchmark · "
        f"**{alpha:+.2%} alpha** {alpha_emoji}"
    )

    # US intraday warning
    us_tickers = [t for t, *_ in pos_returns if "." not in t]
    us_note = ""
    if us_tickers:
        us_note = f"\n_US positions ({', '.join(us_tickers)}) are intraday — markets still open._"

    # AI recommendation
    positions_summary = ", ".join(f"{t} {r:+.1%}" for t, _, r, _ in pos_returns)
    recommendation = _ai_take(positions_summary, portfolio_ret, benchmark_ret, alpha)

    action_note = "\n\n📋 **To change tomorrow's portfolio:** update on the game website.\nDeadline: **10:00 EET** (orders before 10:00 execute at tomorrow's open)."

    # Weekly prize awareness (snapshot taken Monday 09:00 EET)
    prize_note = ""
    weekday = datetime.today().weekday()  # 0=Mon, 3=Thu, 4=Fri
    if weekday in (3, 4):
        prize_note = "\n\n🏆 **Weekly prize heads-up:** leaderboard snapshot is Monday 09:00 EET. If you need to climb the weekly ranking, consider higher-conviction bets tomorrow. If you're already near the top, protect the lead with lower-beta positions."

    description = f"{perf_line}{us_note}\n\n{table}\n💬 {recommendation}{prize_note}{action_note}"

    embed = {
        "title": f"🌙 AlphaShark Evening Review — {date.today().isoformat()}",
        "description": description,
        "color": _EMBED_COLOUR,
        "footer": {
            "text": f"{len(pos_returns)} positions · Changes before 10:00 EET execute at tomorrow's open"
        },
    }

    _send(embed, webhook_url)


if __name__ == "__main__":
    main()
