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
import re
import sys
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import yfinance as yf

from data.portfolio_store import load_latest_verified, save_competition_standing
from data.paper_account import sync_verified_positions
from data.leaderboard_fetcher import CompetitorSnapshot
from output.dispatcher import format_security_label

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

def _coerce_float(val: object) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)  # type: ignore[arg-type]
        return f if f == f else None  # filter NaN
    except (TypeError, ValueError):
        return None


def _coerce_int(val: object) -> int | None:
    if val is None:
        return None
    try:
        return int(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


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


def _norkon_jwt(aripaev_jwt: str, base_headers: dict) -> str | None:
    """Exchange Äripäev session JWT for a Norkon game JWT via the initialize endpoint."""
    try:
        url = (
            "https://www.aripaev.ee/investeerimismang/api/v1/user/initialize"
            f"?token={aripaev_jwt}"
        )
        resp = requests.get(url, headers=base_headers, timeout=10)
        if resp.ok:
            data = resp.json()
            if isinstance(data, dict):
                token = data.get("jwtToken") or data.get("token") or data.get("jwt")
                if token:
                    logger.info("Norkon JWT obtained via initialize endpoint")
                    return str(token)
    except Exception as exc:
        logger.debug("JWT exchange failed: %s", exc)
    return None


def _parse_fund_fields(
    data: dict,
    fund_id: str | None,
    value_eur: float | None,
    rank: int | None,
    today_return_pct: float | None,
    week_return_pct: float | None,
    month_return_pct: float | None,
) -> tuple[float | None, int | None, float | None, float | None, float | None]:
    """Try to extract value/rank/returns from a dict, honoring the target fund_id if given."""
    value_eur = value_eur or _coerce_float(
        data.get("value") or data.get("portfolioValue") or data.get("totalValue")
        or data.get("equity") or data.get("currentValue")
    )
    rank = rank or _coerce_int(
        data.get("rank") or data.get("placement") or data.get("rankPosition")
        or data.get("position")
    )
    today_return_pct = today_return_pct or _coerce_float(
        data.get("todayReturn") or data.get("dailyReturn") or data.get("returnToday")
        or data.get("dayChange") or data.get("changeToday")
    )
    week_return_pct = week_return_pct or _coerce_float(
        data.get("weekReturn") or data.get("weeklyReturn") or data.get("returnWeek")
        or data.get("weekChange")
    )
    month_return_pct = month_return_pct or _coerce_float(
        data.get("monthReturn") or data.get("monthlyReturn") or data.get("returnMonth")
        or data.get("monthChange")
    )
    return value_eur, rank, today_return_pct, week_return_pct, month_return_pct


def _fetch_own_game_stats() -> CompetitorSnapshot | None:
    """Fetch rank, portfolio value, and returns via REST API (site is a Nuxt SPA — HTML scraping doesn't work)."""
    try:
        import config
        url = getattr(config, "MY_PROFILE_URL", "").strip()
    except Exception:
        return None
    if not url:
        return None


    parsed = urlparse(url)
    player_match = re.search(r"/mangija/(\d+)", parsed.path)
    if not player_match:
        logger.warning("Could not parse player ID from MY_PROFILE_URL: %s", url)
        return None
    player_id = player_match.group(1)
    fund_id = (parse_qs(parsed.query).get("portfell") or [None])[0]

    ff_base = "https://www.aripaev.ee/investeerimismang/api/FantasyFunds"
    api_base = "https://www.aripaev.ee/investeerimismang/api"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AlphaShark/1.0)",
        "Accept": "application/json",
        "Referer": "https://www.aripaev.ee/",
    }
    cookie = os.environ.get("ARIPAEV_COOKIE", "")
    if cookie:
        headers["Cookie"] = cookie

    total_players: int | None = None
    rank: int | None = None
    value_eur: float | None = None
    today_return_pct: float | None = None
    week_return_pct: float | None = None
    month_return_pct: float | None = None
    portfolio_name = "unknown"

    try:
        # ── Public: total player count ──────────────────────────────────────────
        resp = requests.get(
            f"{ff_base}/PlayerBadges?playerId={player_id}", headers=headers, timeout=10
        )
        if resp.ok:
            logger.info("PlayerBadges response: %s", resp.text[:400])
            data = resp.json()
            # Unwrap Norkon envelope {"success": true, "result": {...}}
            if isinstance(data, dict) and data.get("success") and isinstance(data.get("result"), dict):
                data = data["result"]
            if isinstance(data, dict):
                total_players = _coerce_int(
                    data.get("playerCount") or data.get("totalPlayers")
                    or data.get("count") or data.get("total")
                )

        # ── Public: player profile (contains player name + activity log) ──────
        resp = requests.get(f"{ff_base}/PlayerData/{player_id}", headers=headers, timeout=10)
        if resp.ok:
            logger.info("PlayerData response: %s", resp.text[:600])
            data = resp.json()
            # Unwrap Norkon envelope
            if isinstance(data, dict) and data.get("success") and isinstance(data.get("result"), dict):
                data = data["result"]
            if isinstance(data, dict):
                player = data.get("player") or {}
                portfolio_name = (
                    player.get("name") or data.get("name") or data.get("playerName") or "unknown"
                )
                # Extract fund name from activity log (value/rank not present here)
                for act in (data.get("activity") or []):
                    contents = act.get("contents") or {}
                    if str(contents.get("fid") or "") == str(fund_id):
                        portfolio_name = contents.get("fname") or portfolio_name
                        break

        # ── Authenticated: exchange Äripäev JWT → Norkon JWT ───────────────────
        if cookie and (value_eur is None or rank is None):
            jwt_match = re.search(r"\bjwt=([^;]+)", cookie)
            if jwt_match:
                nk_token = _norkon_jwt(jwt_match.group(1).strip(), headers)
                if nk_token:
                    auth = {**headers, "Authorization": f"Bearer {nk_token}"}
                    # userdata → confirms fund id
                    ud_resp = requests.get(
                        f"{api_base}/fantasyfunds/userdata", headers=auth, timeout=10
                    )
                    if ud_resp.ok:
                        logger.info("userdata response: %s", ud_resp.text[:400])

                    # Authenticated fund-specific endpoints — log responses to aid discovery
                    for ep in [
                        f"{api_base}/fantasyfunds/fund/{fund_id}",
                        f"{api_base}/FantasyFunds/FundDetails/{fund_id}",
                        f"{api_base}/FantasyFunds/GetFundData?fid={fund_id}",
                        f"{api_base}/FantasyFunds/FundStats?fid={fund_id}",
                        f"{api_base}/FantasyFunds/Fund/{fund_id}",
                        f"{api_base}/fantasyfunds/portfolio/{fund_id}",
                        f"{api_base}/FantasyFunds/PlayerData/{player_id}",
                    ]:
                        try:
                            r = requests.get(ep, headers=auth, timeout=5)
                            ep_name = ep.split("/")[-1].split("?")[0]
                            if not r.ok:
                                logger.info("Auth endpoint %s → HTTP %s", ep_name, r.status_code)
                                continue
                            body = r.text.strip()
                            if body in ("null", "", "[]"):
                                logger.info("Auth endpoint %s → empty", ep_name)
                                continue
                            logger.info("Auth endpoint %s → %s", ep_name, body[:400])
                            try:
                                d = r.json()
                            except Exception:
                                continue
                            if not isinstance(d, dict):
                                continue
                            # Unwrap Norkon envelope
                            if d.get("success") and isinstance(d.get("result"), dict):
                                d = d["result"]
                            value_eur, rank, today_return_pct, week_return_pct, month_return_pct = (
                                _parse_fund_fields(
                                    d, fund_id,
                                    value_eur, rank, today_return_pct, week_return_pct, month_return_pct,
                                )
                            )
                            if value_eur is not None and rank is not None:
                                break
                        except Exception:
                            continue

        # ── Fallback: unauthenticated fund endpoints ───────────────────────────
        if fund_id and (value_eur is None or rank is None):
            for ep in [
                f"{ff_base}/FundStats?fid={fund_id}",
                f"{ff_base}/GetFundData?fid={fund_id}",
                f"{ff_base}/historical-fund-performance?fid={fund_id}",
            ]:
                try:
                    r = requests.get(ep, headers=headers, timeout=5)
                    if not r.ok or r.text.strip() in ("null", "", "[]"):
                        continue
                    d = r.json()
                    if not isinstance(d, dict):
                        continue
                    value_eur, rank, today_return_pct, week_return_pct, month_return_pct = (
                        _parse_fund_fields(
                            d, fund_id,
                            value_eur, rank, today_return_pct, week_return_pct, month_return_pct,
                        )
                    )
                    if value_eur is not None and rank is not None:
                        break
                except Exception:
                    continue

    except Exception as exc:
        logger.warning("Own game profile API fetch failed: %s", exc)
        return None

    if total_players is None and rank is None and value_eur is None:
        logger.warning("Own game profile API returned no usable data for player %s", player_id)
        return None

    logger.info(
        "Own game profile fetched via API: rank=%s/%s, value=%s EUR",
        rank,
        total_players,
        f"{value_eur:.0f}" if value_eur is not None else "n/a",
    )
    return CompetitorSnapshot(
        url=url,
        portfolio_name=portfolio_name,
        rank=rank,
        total_players=total_players,
        value_eur=value_eur,
        today_return_pct=today_return_pct,
        week_return_pct=week_return_pct,
        month_return_pct=month_return_pct,
        visible_holdings=[],
        holdings_total_count=None,
    )


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

    today = date.today().isoformat()
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

    # ── Auto-fetch own game profile (rank, equity, game-reported returns) ───
    game_stats = _fetch_own_game_stats()
    if game_stats is not None:
        # Auto-save competition standing so verify.py rank prompt can be skipped.
        if game_stats.rank is not None and game_stats.total_players is not None:
            try:
                save_competition_standing(game_stats.rank, game_stats.total_players, today)
                logger.info(
                    "Competition standing auto-saved: rank %d / %d",
                    game_stats.rank,
                    game_stats.total_players,
                )
            except Exception as exc:
                logger.warning("Could not auto-save competition standing: %s", exc)

        # Auto-sync paper account equity using game-reported portfolio value.
        if game_stats.value_eur is not None and game_stats.value_eur > 0:
            price_map = {t: float(prices[t][1]) for t in tickers if t in prices}
            if price_map:
                try:
                    sync_verified_positions(positions, game_stats.value_eur, today, price_map)
                    logger.info(
                        "Paper account equity auto-synced: €%.0f", game_stats.value_eur
                    )
                except Exception as exc:
                    logger.warning("Could not auto-sync paper account equity: %s", exc)

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
    stale_warning = ""
    if portfolio_date != today:
        stale_warning = f"\n\n⚠️ _Portfolio data is from **{portfolio_date}** (not today). Run verify.py to update._"

    description = f"{perf_line}{us_note}{stale_warning}\n\n💬 {recommendation}{prize_note}"

    # Build game standing field if profile data was fetched.
    game_standing_field: dict | None = None
    if game_stats is not None:
        rank_str = f"#{game_stats.rank} / {game_stats.total_players}" if game_stats.rank else "n/a"
        value_str = f"€{game_stats.value_eur:,.0f}".replace(",", " ") if game_stats.value_eur else "n/a"
        ret_today = f"{game_stats.today_return_pct:+.2f}%" if game_stats.today_return_pct is not None else "n/a"
        ret_week = f"{game_stats.week_return_pct:+.2f}%" if game_stats.week_return_pct is not None else "n/a"
        ret_month = f"{game_stats.month_return_pct:+.2f}%" if game_stats.month_return_pct is not None else "n/a"
        game_standing_field = {
            "name": "📊 Game Standing (auto-fetched)",
            "value": (
                f"**Rank:** {rank_str}\n"
                f"**Portfolio value:** {value_str}\n"
                f"**Game returns:** today {ret_today} · week {ret_week} · month {ret_month}"
            ),
            "inline": False,
        }

    fields = []
    if game_standing_field:
        fields.append(game_standing_field)
    fields += [
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
    ]

    embed = {
        "title": f"🌙 AlphaShark Evening Review — {today}",
        "description": description,
        "color": _EMBED_COLOUR,
        "fields": fields,
        "footer": {
            "text": f"{len(pos_returns)} positions · {portfolio_source} · Changes before 10:00 EET execute at tomorrow's open"
        },
    }

    _send(embed, webhook_url)

    # Persist observations so next morning's agents can read yesterday's evening review.
    try:
        observations: dict = {
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
        if game_stats is not None:
            observations["game_standing"] = {
                "rank": game_stats.rank,
                "total_players": game_stats.total_players,
                "value_eur": game_stats.value_eur,
                "today_return_pct": game_stats.today_return_pct,
                "week_return_pct": game_stats.week_return_pct,
                "month_return_pct": game_stats.month_return_pct,
            }
        obs_path = os.path.abspath(_OBSERVATIONS_PATH)
        with open(obs_path, "w") as f:
            json.dump(observations, f, indent=2)
        logger.info("Evening observations written to evening_observations.json")
    except Exception as exc:
        logger.warning("Could not write evening_observations.json: %s", exc)


if __name__ == "__main__":
    main()
