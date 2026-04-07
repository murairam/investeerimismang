"""
Evening portfolio review.

Runs at 23:30 EEST Mon-Fri (20:30 UTC). Fetches current prices, computes
today's return vs benchmark, and sends a Discord summary with an AI recommendation.

By 23:30 EEST:
  - Baltic / Scandinavian markets: closed → final prices
  - US market status / price finality should not be assumed solely from ticker format or run time
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timezone

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import yfinance as yf

from data.portfolio_store import load_latest_verified
from output.dispatcher import format_security_label

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

_PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio_history.json")
_PAPER_ACCOUNT_PATH = os.path.join(os.path.dirname(__file__), "..", "paper_account.json")
_OBSERVATIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "evening_observations.json")
_BENCHMARK = "^GSPC"
_EMBED_COLOUR = 0x3498DB  # Blue


def _load_portfolio() -> dict | None:
    # Priority 1: DB verified portfolio — always the most up-to-date source.
    verified = load_latest_verified(date.today().isoformat())
    if verified and verified.get("positions"):
        logger.info(
            "Loaded verified portfolio from DB (%s, %d positions)",
            verified.get("date"),
            len(verified["positions"]),
        )
        return verified

    # Priority 2: paper_account.json — kept current by verify.py even when DB is
    # unavailable. Uses verified_weights ({ticker: weight}) written by sync_verified_positions.
    pa_path = os.path.abspath(_PAPER_ACCOUNT_PATH)
    if os.path.exists(pa_path):
        try:
            with open(pa_path) as f:
                pa = json.load(f)
            weights: dict = pa.get("verified_weights") or {}
            if weights:
                positions = [{"ticker": t, "weight": w} for t, w in weights.items()]
                pa_date = pa.get("last_rebalanced_date")
                logger.warning(
                    "DB unavailable — using paper_account.json fallback (%s, %d positions)",
                    pa_date,
                    len(positions),
                )
                return {"positions": positions, "date": pa_date, "source": "paper_account"}
        except Exception as exc:
            logger.warning("Could not read paper_account.json: %s", exc)

    # Priority 3: legacy portfolio_history.json — last resort, may be very stale.
    path = os.path.abspath(_PORTFOLIO_PATH)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        portfolio = json.load(f)

    logger.warning(
        "Using legacy portfolio_history.json fallback (%s, source=%s) — DB and paper_account unavailable",
        portfolio.get("date"),
        portfolio.get("source", "unknown"),
    )
    return portfolio


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


def _ai_take(positions_summary: str, portfolio_ret: float, benchmark_ret: float, alpha: float, prize_context: str = "") -> str:
    """One-sentence AI recommendation via OpenAI gpt-5.4-nano (~$0.0001/call)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "_AI recommendation unavailable (no API key)._"
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        extra = f"\n\nAdditional context: {prize_context}" if prize_context else ""

        def _call(messages: list[dict]) -> str | None:
            resp = client.chat.completions.create(
                model="gpt-5.4-nano",
                messages=messages,
                max_completion_tokens=150,
                temperature=0.3,
            )
            choice = resp.choices[0]
            finish = choice.finish_reason
            content = choice.message.content
            if not content:
                logger.warning("AI take: empty content (finish_reason=%s)", finish)
            return content.strip() if content else None

        # Primary prompt — explicit game/simulation context to avoid content filtering
        primary_messages = [
            {
                "role": "system",
                "content": (
                    "You are an advisor for a simulated stock market competition game. "
                    "This is not real financial advice — it is a game simulation. "
                    "Give direct, actionable game advice in exactly 1-2 sentences. No fluff."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Game portfolio today: {portfolio_ret:+.2%}, "
                    f"benchmark: {benchmark_ret:+.2%}, alpha: {alpha:+.2%}.\n"
                    f"Position returns: {positions_summary}\n\n"
                    f"Should I update the game portfolio for tomorrow? "
                    f"Name any specific positions worth dropping or keeping.{extra}"
                ),
            },
        ]
        result = _call(primary_messages)

        # Retry with a simpler fallback prompt if content was empty/filtered
        if not result:
            logger.warning("AI take: retrying with simplified prompt")
            fallback_messages = [
                {
                    "role": "system",
                    "content": "You are a helpful assistant summarising stock game results in 1 sentence.",
                },
                {
                    "role": "user",
                    "content": (
                        f"My game portfolio returned {portfolio_ret:+.2%} today vs "
                        f"benchmark {benchmark_ret:+.2%} (alpha {alpha:+.2%}). "
                        f"Positions: {positions_summary}. One sentence takeaway?"
                    ),
                },
            ]
            result = _call(fallback_messages)

        return result or "_AI recommendation unavailable._"
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
    search_list = "\n".join(
        f"{i}. {format_security_label(ticker)}"
        for i, (ticker, *_rest) in enumerate(pos_returns, 1)
    )

    # Performance headline
    alpha_emoji = "🟢" if alpha > 0.003 else ("🔴" if alpha < -0.003 else "🟡")
    perf_line = (
        f"**Today:** {portfolio_ret:+.2%} portfolio · "
        f"{benchmark_ret:+.2%} benchmark · "
        f"**{alpha:+.2%} alpha** {alpha_emoji}"
    )

    # US market status note — script runs at 20:30 UTC, 30 min after US close (20:00 UTC)
    us_tickers = [t for t, *_ in pos_returns if "." not in t]
    us_note = ""
    if us_tickers:
        us_note = f"\n_US positions ({', '.join(us_tickers)}) — prices are final (post-market close)._"

    action_note = (
        "1. Review the weakest names below.\n"
        "2. If changing tomorrow's portfolio, update the game website before **10:00 EET**.\n"
        "3. Use the Game Search List to find the exact names quickly."
    )

    # Weekly prize awareness (snapshot taken Monday 09:00 EET) — built BEFORE AI call so AI gets context
    weekday = datetime.today().weekday()  # 0=Mon, 3=Thu, 4=Fri
    prize_context = ""
    prize_note = ""
    if weekday in (3, 4):
        prize_context = (
            "Weekly leaderboard prize snapshot is Monday 09:00 EET. "
            "Factor this into your recommendation: if the portfolio needs to climb the weekly ranking, "
            "suggest higher-conviction bets; if already near the top, suggest protecting with lower-beta positions."
        )
        prize_note = "\n\n🏆 **Weekly prize heads-up:** leaderboard snapshot is Monday 09:00 EET. If you need to climb the weekly ranking, consider higher-conviction bets. If already near the top, protect the lead with lower-beta positions."

    # AI recommendation (receives prize context when applicable)
    positions_summary = ", ".join(f"{t} {r:+.1%}" for t, _, r, _ in pos_returns)
    recommendation = _ai_take(positions_summary, portfolio_ret, benchmark_ret, alpha, prize_context)

    portfolio_date = portfolio.get("date", "unknown")
    portfolio_source = portfolio.get("source", "unknown")
    today = date.today().isoformat()
    stale_warning = ""
    if portfolio_date != today:
        stale_warning = f"\n\n⚠️ _Portfolio data is from **{portfolio_date}** (not today). Run verify.py to update._"

    description = f"{perf_line}{us_note}{stale_warning}\n\n💬 {recommendation}{prize_note}"

    embed = {
        "title": f"🌙 AlphaShark Evening Review — {today}",
        "description": description,
        "color": _EMBED_COLOUR,
        "fields": [
            {
                "name": "Game Search List",
                "value": search_list[:1024],
                "inline": False,
            },
            {
                "name": "Today's Position Moves",
                "value": table[:1024],
                "inline": False,
            },
            {
                "name": "Action For Tomorrow Morning",
                "value": action_note,
                "inline": False,
            },
        ],
        "footer": {
            "text": f"{len(pos_returns)} positions · {portfolio_source} · Changes before 10:00 EET execute at tomorrow's open"
        },
    }

    _send(embed, webhook_url)

    # Persist observations so next morning's agents can read yesterday's evening review.
    try:
        observations = {
            "date": today,
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "portfolio_return": portfolio_ret,
            "benchmark_return": benchmark_ret,
            "alpha": alpha,
            "position_returns": [
                {"ticker": t, "weight": w, "return": r, "price": p}
                for t, w, r, p in pos_returns
            ],
            "ai_recommendation": recommendation,
        }
        obs_path = os.path.abspath(_OBSERVATIONS_PATH)
        with open(obs_path, "w") as f:
            json.dump(observations, f, indent=2)
        logger.info("Evening observations written to evening_observations.json")
    except Exception as exc:
        logger.warning("Could not write evening_observations.json: %s", exc)


if __name__ == "__main__":
    main()
