"""
OpenAIStrategist — GPT-5.4-powered alpha generator.
Uses gpt-5.4 with JSON mode for reliable structured output.

Cost estimate: ~$0.055 per run, ~$4.10 for the full game (75 days).
"""
import json
import logging
import math
import os
from datetime import date
from typing import Optional

import openai
from openai import APIConnectionError, APITimeoutError, OpenAI

from agents.base_agent import BaseAgent, conviction_to_weight
from config import (
    API_TIMEOUT_SECONDS,
    MOMENTUM_WINDOW,
    VIX_HIGH_THRESHOLD,
    VIX_LOW_THRESHOLD,
    VIX_NEUTRAL_THRESHOLD,
)
from data.cost_tracker import log_usage
from data.fetcher import MarketSnapshot, sanitize_ticker
from data.portfolio_store import load_performance_history
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

# ── Regime guidance ────────────────────────────────────────────────────────────
_REGIME_GUIDANCE = {
    "BULL": (
        "Market regime: BULL (SPX above 50d SMA by ≥2%). "
        "TARGET 5 positions for maximum conviction — only add a 6th if genuinely high-conviction (score ≥ 8). "
        "Favour high-beta names (beta up to 2.0). This is the regime for big gains. Do NOT add filler to reach 7–8."
    ),
    "BEAR": (
        "Market regime: BEAR (SPX below 50d SMA by ≥2%). "
        "Concentrate on 5–8 positions in whatever IS working — sectors/stocks with positive momentum regardless of regime. "
        "In a 75-day competition, the goal is to find the winners in any environment, not to fall less than others."
    ),
    "NEUTRAL": (
        "Market regime: NEUTRAL (SPX near 50d SMA). "
        "5–8 positions — concentrate in genuine strength and avoid weak filler names. "
        "Quality over quantity: do not pad with weak names, and keep the book tight unless conviction breadth is truly high."
    ),
}

def _vix_guidance(vix: float) -> str:
    if math.isnan(vix):
        return "VIX data unavailable — use regime signals only."
    if vix > VIX_HIGH_THRESHOLD:
        return (
            f"VIX is {vix:.1f} — extreme fear. Reduce overall beta. "
            "Lower conviction on high-beta speculative picks. Prefer names with strong earnings visibility. "
            "This is not the time for speculative breakouts."
        )
    if vix > VIX_NEUTRAL_THRESHOLD:
        return (
            f"VIX is {vix:.1f} — elevated uncertainty. "
            "Be selective: only add a position if its Sharpe_20d is clearly above the median. "
            "Slightly prefer quality over pure momentum."
        )
    if vix < VIX_LOW_THRESHOLD:
        return (
            f"VIX is {vix:.1f} — market complacency. "
            "Momentum strategy works well here but ensure every position has a genuine Sharpe edge. "
            "Avoid names that are 'up on nothing' — confirm with vs_index > 0."
        )
    return f"VIX is {vix:.1f} — normal range. Standard momentum strategy applies."


_SYSTEM_PROMPT_TEMPLATE = """You are AlphaShark, an elite quantitative portfolio manager competing in the Äripäev/SEB Investment Game (Estonia). Your mandate is to build a high-conviction, momentum-driven portfolio that maximises returns by game end (19 June 2026).

Today's date: {today}. The market snapshot provided below is your ONLY source of truth for current price action — do not rely on training-data knowledge of stock prices or recent news.

## Competition context — {n_participants} participants, only #1 wins
This is a competition, not wealth management. Only #1 wins — median returns = losing. Your job is INTELLIGENT AGGRESSION: concentration is correct, diversification loses competitions. Do not concentrate into low-conviction names, but 5–6 high-conviction bets have far higher expected return than 12 diluted ones.

You are the Momentum Strategist — your signal table shows trend/momentum signals only (Sharpe, returns, vs_index, 52wH%, beta, MACD). A separate Catalyst agent evaluates RSI, vol_ratio, short interest, and IV. Focus on smooth, persistent uptrends with strong Sharpe and positive vs_index.

## Game rules you MUST follow
- Portfolio must hold between 5 and 20 different stocks.
- Orders submitted before 10:00 EET execute at the same day's open price.
- Available markets: Baltic Main List, US S&P 500, OMX Helsinki Large Cap (Finland), OMX Stockholm 30 (Sweden), OBX (Norway), OMX Copenhagen 25 (Denmark).

## Investment strategy
Focus on MOMENTUM + HIGH-BETA BREAKOUT:
- Favour stocks with the strongest risk-adjusted momentum (Sharpe_20d = 20d return / annualised vol).
- High Sharpe means a smooth, persistent uptrend — much better than a volatile spike.
- Prefer high-beta names in bull-market conditions — they amplify gains.
- Regime-based position count: BULL target 5 (max 6), NEUTRAL 5–8, BEAR 5–8. You decide the exact count based on signal quality — more positions only if multiple names genuinely earn their slot. Daily rebalancing replaces diversification — rotate out losers tomorrow. No token 5% picks unless a name has a clear catalyst reason.
- Single-market concentration is fine if signals are concentrated there. Do NOT add positions in other markets just for geographic diversification.
- Stocks near 52-week highs (pct_from_52w_high close to 0%) are breaking out — favour them IF 5d momentum is strong (> 5%). If a stock is at its 52w high but 5d momentum is weak (< 3%) and MACD is flat or negative, the move is likely exhausted — treat it as a hold candidate, not a fresh entry at full size.
- vs_index > 0 means the stock beat its own market — pure alpha signal.
- MACD histogram: positive = accelerating momentum, negative = decelerating. Use it to distinguish fresh breakouts from fading moves.
- Goal: BEAT other game participants — take conviction bets, not passive exposure.
- **Diversify from the crowd**: consider non-US markets (Nordic, Baltic) — they often carry differentiated alpha and are overlooked by other participants. But do not force non-US picks if US signals are clearly stronger.
- **No sector cap**: The game enforces no sector concentration limit. If a single sector (e.g. Energy, Tech, AI) has extreme momentum, you are fully authorized to put 100% of the portfolio into that sector (e.g. 4 stocks at 25% each). Concentrate wherever the alpha is.

## Macro regime
Follow the signals — no hardcoded sector or stock bias. Whatever has the strongest momentum, Sharpe, and volume confirmation today is the right pick. The market snapshot is your only source of truth.

## Baltic market specialist guidance
Baltic stocks behave differently from US/Nordic names — apply specific caution:
- **Most liquid & reliable**: LHV1T.TL (banking, strong fundamentals), TAL1T.TL (tech/growth, highest Baltic liquidity)
- **Thin-volume names** (use only with strong signals): PRF1T.TL, MRK1T.TL, ARC1T.TL — low daily volume means ATR% is misleadingly small; do NOT apply standard ATR-based sizing to these
- **Baltic edge**: local competitors may overlook Baltic stocks; if fundamentals and momentum align, Baltic picks are differentiated alpha
- **Dividend strength**: LHV1T.TL, GRG1L.VS, APG1L.VS often carry 3–6% yields — genuine free return in this game

## Portfolio turnover
Let winners ride. Only exit a current holding if momentum has broken (negative vs_index, declining MACD, and 5d return turning negative) or a clearly superior alternative exists (Sharpe_20d ≥ 20% higher). Do not rotate for marginal gains — each trade executes at next-day open price.

## Position sizing — MANDATORY RULES
Output `conviction` (integer 1–10), NOT a weight. Python converts conviction to position size.
- 10 = max conviction (your single best momentum idea today — clear breakout + Sharpe leader)
- 8–9 = high conviction (strong smooth trend, beats index)
- 5–7 = medium conviction (solid signals, worth a slot)
- 1–4 = low conviction / speculative (include only if genuinely additive)
Every position must have a DIFFERENT conviction score — equal scoring across all positions is not acceptable.
Conviction → weight mapping (Python-computed): 10→~25% | 9→~22% | 8→~20% | 7→~18% | 6→~16% | 5→~13% | 4→~11% | 3→~9% | 2→~7% | 1→~5%

## Market regime
{regime_guidance}

## VIX volatility filter
{vix_guidance}

## Output format
You must respond with a valid JSON object and nothing else.

{{
  "positions": [
    {{
      "ticker": "TICKER",
      "conviction": 9,
      "rationale": "One-sentence reason for THIS ticker at THIS specific conviction score."
    }}
  ],
  "reasoning": "2-3 sentence thesis: which are your top picks and why are they your highest conviction.",
  "confidence": 0.75,
  "learning_reflection": "One sentence: how today's picks adapt based on recent learning context."
}}

Rules:
- "conviction" is an integer from 1 to 10.
- "confidence" is between 0.0 and 1.0.
- Include between 5 and 20 positions.
- No duplicate tickers.
- Positions MUST have varied conviction scores — equal scoring across all positions is not acceptable.
"""


class OpenAIStrategist(BaseAgent):
    MAX_RETRIES = 3
    MODEL = "gpt-5.4"

    def __init__(self) -> None:
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def propose(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        user_message = self._build_user_message(snapshot, prior_proposal)
        regime = snapshot.get("regime", "NEUTRAL")
        vix = snapshot.get("vix_level", float("nan"))
        learning_context = snapshot.get("learning_context", "")

        n_participants = snapshot.get("n_participants", 844)
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                proposal = self._call_openai(user_message, regime, vix, learning_context, n_participants)
                logger.info(
                    "Strategist[%s] produced %d positions (confidence %.0f%%)",
                    self.MODEL,
                    len(proposal.positions),
                    proposal.confidence * 100,
                )
                return proposal
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning("Attempt %d/%d failed: %s", attempt, self.MAX_RETRIES, exc)
                if attempt == self.MAX_RETRIES:
                    raise RuntimeError("OpenAIStrategist: exhausted retries") from exc
            except (APIConnectionError, APITimeoutError, openai.RateLimitError, openai.InternalServerError) as exc:
                logger.warning("Strategist API attempt %d/%d failed: %s", attempt, self.MAX_RETRIES, exc)
                if attempt == self.MAX_RETRIES:
                    logger.error("Strategist failed after %d retries — no fallback", self.MAX_RETRIES)
                    raise RuntimeError(
                        f"Strategist failed after {self.MAX_RETRIES} retries — no fallback"
                    ) from exc

        raise RuntimeError("OpenAIStrategist: unreachable")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_user_message(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> str:
        vix = snapshot.get("vix_level", float("nan"))
        spx_vs = snapshot.get("spx_vs_sma", 0.0)
        regime = snapshot.get("regime", "NEUTRAL")
        vix_str = f"{vix:.1f}" if not math.isnan(vix) else "N/A"

        breadth = snapshot.get("breadth_pct", float("nan"))
        term = snapshot.get("vix_term_ratio", float("nan"))
        credit = snapshot.get("credit_change", float("nan"))
        rscore = snapshot.get("regime_score", 50)
        breadth_str = f"{breadth:.0%}" if not math.isnan(breadth) else "N/A"
        term_str = f"{term:.2f}" if not math.isnan(term) else "N/A"
        credit_str = f"{credit:+.2%}" if not math.isnan(credit) else "N/A"
        score_label = (
            "DEFENSIVE" if rscore < 30 else
            "CAUTIOUS"  if rscore < 50 else
            "NEUTRAL"   if rscore < 70 else
            "BULLISH"
        )

        header = (
            f"{'Ticker':<12} {'Market':<12} {'Sector':<7} {'20d(σ)':>7} {'Sh(σ)':>6} "
            f"{'5d(σ)':>6} {'60dRet':>7} {'vIdx(σ)':>8} "
            f"{'52wH%':>7} {'Beta':>6} {'MACD':>7} {'Price':>10}"
        )
        fx = snapshot.get("fx_context", {})
        fx_line = ""
        eurusd = fx.get("eurusd_price", float("nan"))
        if not math.isnan(eurusd):
            eurusd_20d = fx.get("eurusd_20d", float("nan"))
            eurusd_1d = fx.get("eurusd_1d", float("nan"))
            fx_line = (
                f"EUR/USD: {eurusd:.4f} ({eurusd_20d:+.2%} 20d, {eurusd_1d:+.2%} 1d) — "
                "US equity signals shown above are already EUR-adjusted (USD returns minus FX drag)"
                if not math.isnan(eurusd_20d) else f"EUR/USD: {eurusd:.4f}"
            )

        comm = snapshot.get("commodity_context", {})
        comm_line = ""
        brent = comm.get("brent_price", float("nan"))
        if not math.isnan(brent):
            brent_20d = comm.get("brent_20d", float("nan"))
            wti = comm.get("wti_price", float("nan"))
            wti_20d = comm.get("wti_20d", float("nan"))
            natgas = comm.get("natgas_price", float("nan"))
            natgas_20d = comm.get("natgas_20d", float("nan"))
            comm_line = (
                f"Commodities: Brent ${brent:.1f} ({brent_20d:+.1%} 20d) | "
                f"WTI ${wti:.1f} ({wti_20d:+.1%} 20d) | "
                f"NatGas ${natgas:.2f} ({natgas_20d:+.1%} 20d)"
                if not math.isnan(wti) and not math.isnan(natgas) else
                f"Commodities: Brent ${brent:.1f} ({brent_20d:+.1%} 20d)"
            )

        game_equity = snapshot.get("game_equity", 10000.0)
        game_ret = snapshot.get("game_return_pct", 0.0)
        lines = [
            f"Market snapshot as of {snapshot['as_of_date']}",
            f"Game account: €{game_equity:,.0f} ({game_ret:+.2%} since start, started €10,000)",
            f"Benchmark (S&P 500) {MOMENTUM_WINDOW}-day return: {snapshot['benchmark_return']:.1%}",
            f"Regime: {regime} | SPX vs 50d SMA: {spx_vs:.1%} | VIX: {vix_str}",
            f"Breadth: {breadth_str} above 50d SMA | VIX term: {term_str} (>1=calm, <0.9=fear) | Credit spreads 20d: {credit_str} (positive=risk-on)",
            f"Composite regime score: {rscore}/100 — {score_label} (0–30=defensive, 31–49=cautious, 50–69=neutral, 70+=bullish)",
        ]
        portfolio_state_context = snapshot.get("portfolio_state_context", "")
        if portfolio_state_context:
            lines += ["", portfolio_state_context]
        if fx_line:
            lines.append(fx_line)
        if comm_line:
            lines.append(comm_line)
        # Sector rotation context
        sector_mom = snapshot.get("sector_momentum", {})
        if sector_mom:
            _valid = sorted(
                [(s, d) for s, d in sector_mom.items()
                 if not math.isnan(d.get("avg_mom_20d", float("nan"))) and d.get("count", 0) >= 2],
                key=lambda x: x[1]["avg_mom_20d"], reverse=True,
            )
            if _valid:
                _parts = []
                for s, d in _valid[:5]:
                    br = d.get("breadth", float("nan"))
                    br_s = f" ({br:.0%})" if not math.isnan(br) else ""
                    _parts.append(f"{s} {d['avg_mom_20d']:+.1%}{br_s}")
                lines += ["", f"Sector rotation (20d avg, % bullish breadth): {' | '.join(_parts[:5])}"]
                _lag = [s for s, d in _valid if d["avg_mom_20d"] < 0]
                if _lag:
                    lines.append(f"  Losing momentum: {', '.join(_lag[:4])}")
                lines.append(
                    "Sector action rule: if a sector's breadth is below 40%, it is losing internal momentum — "
                    "reduce or exit your weakest performer in that sector and redeploy into the leading sector."
                )

        rotation_risk = snapshot.get("rotation_risk", {})
        if rotation_risk:
            high = [(s, i) for s, i in rotation_risk.items() if i["level"] == "HIGH"]
            med = [(s, i) for s, i in rotation_risk.items() if i["level"] == "MEDIUM"]
            alert_lines = ["ROTATION RISK ALERT:"]
            for s, i in sorted(high + med, key=lambda x: x[1]["level"]):
                alert_lines.append(f"  {i['level']}: {s} — {i['reason']}")
            if high:
                alert_lines.append(f"  Action: Reduce or exit {', '.join(s for s, _ in high)} before rotation completes.")
            lines += [""] + alert_lines

        late_game_mode = snapshot.get("late_game_mode", "NORMAL")
        if late_game_mode != "NORMAL":
            _lgm_msg = {
                "RECOUP": "LATE-GAME MODE: RECOUP — portfolio is underperforming, final 3 weeks. Favour higher-beta/catalyst names to close the gap. Avoid defensive low-beta filler.",
                "LOCK_IN": "LATE-GAME MODE: LOCK_IN — portfolio is outperforming, final 3 weeks. Favour beta 1.0-1.4 names with positive momentum to preserve gains. Avoid high-beta concentration.",
            }.get(late_game_mode, "")
            if _lgm_msg:
                lines += ["", _lgm_msg]

        if snapshot.get("groupthink_risk"):
            lines += ["", "⚠ GROUPTHINK ALERT: >60% of picks are consensus across agents — the obvious momentum names may already be crowded. Actively consider non-consensus picks from the signal table."]

        lines += [
            "",
            "Top candidates (sorted by competition score) — MOMENTUM signals only:",
            "",
            header,
            "-" * len(header),
        ]

        def fmt(v: float, fmt_str: str = ".1%") -> str:
            return "N/A" if math.isnan(v) else format(v, fmt_str)

        def fmtz(v: float) -> str:
            return "N/A" if math.isnan(v) else f"{v:+.1f}σ"

        for c in snapshot["candidates"]:
            safe_ticker = sanitize_ticker(c["ticker"])
            lines.append(
                f"{safe_ticker:<12} {c['market']:<12} {c.get('sector', '?'):<7} "
                f"{fmtz(c.get('z_momentum', float('nan'))):>7} "
                f"{fmtz(c.get('z_sharpe_20d', float('nan'))):>6} "
                f"{fmtz(c.get('z_mom_5d', float('nan'))):>6} "
                f"{fmt(c['mom_60d']):>7} "
                f"{fmtz(c.get('z_vs_index', float('nan'))):>8} "
                f"{fmt(c['pct_from_52w_high']):>7} "
                f"{fmt(c['beta'], '.2f'):>6} "
                f"{fmt(c.get('macd_hist', float('nan'))):>7} "
                f"{c['last_price']:>10.2f}"
            )

        if prior_proposal and prior_proposal.positions:
            lines += [
                "",
                "## Current holdings (from yesterday's portfolio)",
                f"{'Ticker':<12} {'Weight':>8}",
                "-" * 22,
            ]
            for pos in prior_proposal.positions:
                lines.append(f"{sanitize_ticker(pos.ticker):<12} {pos.weight:>8.1%}")
            lines += [
                "",
                "Turnover rule: to EXIT a current holding, the replacement must have a Sharpe_20d "
                "at least 20% higher than the stock being replaced. "
                "Do not swap positions for marginal gains — each trade executes at next-day open price.",
            ]

        # Performance context — full daily P&L review
        perf_history = load_performance_history(max_days=5)
        daily_entries = [e for e in perf_history if "portfolio_return_1d" in e]
        if daily_entries:
            lines += ["", "## Performance review (last %d days)" % len(daily_entries)]
            col_header = f"{'Date':<12} {'Portfolio':>10} {'Benchmark':>10} {'Alpha':>8}    Key movers"
            lines.append(col_header)
            lines.append("-" * len(col_header))

            def _as_float_or_none(value: object) -> Optional[float]:
                if value is None:
                    return None
                if isinstance(value, (int, float)):
                    numeric = float(value)
                    return None if math.isnan(numeric) else numeric
                return None

            for entry in daily_entries:
                p_ret = _as_float_or_none(entry.get("portfolio_return_1d"))
                b_ret = _as_float_or_none(entry.get("benchmark_return_1d"))
                a_ret = _as_float_or_none(entry.get("alpha_1d"))
                pos_rets = entry.get("position_returns", {})

                p_str = f"{p_ret:+.1%}" if p_ret is not None else "N/A"
                b_str = f"{b_ret:+.1%}" if b_ret is not None else "N/A"
                a_str = f"{a_ret:+.1%}" if a_ret is not None else "N/A"

                movers = []
                if pos_rets:
                    top_w = sorted(pos_rets.items(), key=lambda x: -x[1])[:2]
                    top_l = sorted(pos_rets.items(), key=lambda x: x[1])[:1]
                    for t, r in top_w:
                        if r > 0:
                            movers.append(f"{sanitize_ticker(t)} {r:+.1%} ▲")
                    for t, r in top_l:
                        if r < 0:
                            movers.append(f"{sanitize_ticker(t)} {r:+.1%} ▼")
                movers_str = "  ".join(movers) if movers else ""
                lines.append(
                    f"{entry['date']:<12} {p_str:>10} {b_str:>10} {a_str:>8}    {movers_str}"
                )

            # Cumulative stats
            cum_port = sum(
                p_ret for p_ret in (
                    _as_float_or_none(e.get("portfolio_return_1d")) for e in daily_entries
                ) if p_ret is not None
            )
            cum_bench = sum(
                b_ret for b_ret in (
                    _as_float_or_none(e.get("benchmark_return_1d")) for e in daily_entries
                ) if b_ret is not None
            )
            cum_alpha = cum_port - cum_bench
            lines.append(
                f"\nCumulative since tracking: portfolio {cum_port:+.1%}, "
                f"benchmark {cum_bench:+.1%}, alpha {cum_alpha:+.1%}"
            )

            # Consistent winners/losers across days
            ticker_returns: dict = {}
            for entry in daily_entries:
                for t, r in entry.get("position_returns", {}).items():
                    ticker_returns.setdefault(t, []).append(r)
            consistent_winners = [
                t for t, rets in ticker_returns.items()
                if len(rets) >= 2 and all(r > 0 for r in rets)
            ]
            consistent_losers = [
                t for t, rets in ticker_returns.items()
                if len(rets) >= 2 and all(r < 0 for r in rets)
            ]
            if consistent_winners:
                lines.append(
                    f"Consistent winners this week: {', '.join(sanitize_ticker(t) for t in consistent_winners)}"
                )
            if consistent_losers:
                lines.append(
                    f"Consistent underperformers: {', '.join(sanitize_ticker(t) for t in consistent_losers)}"
                )

            # Strategy adaptation signal
            if len(daily_entries) >= 2:
                recent_alpha = [
                    a for a in (
                        _as_float_or_none(e.get("alpha_1d")) for e in daily_entries[-3:]
                    ) if a is not None
                ]
                if recent_alpha:
                    avg_alpha = sum(recent_alpha) / len(recent_alpha)
                    if avg_alpha > 0.003:
                        lines.append(
                            "Strategy adaptation signal: recent alpha is positive — "
                            "current momentum picks are working. Maintain conviction."
                        )
                    elif avg_alpha < -0.003:
                        lines.append(
                            "Strategy adaptation signal: recent alpha is negative — "
                            "consider reviewing position sizing and reviewing losers for exit."
                        )
                    else:
                        lines.append(
                            "Strategy adaptation signal: alpha is near zero — "
                            "monitor for regime change signals before making large shifts."
                        )
        elif len(perf_history) >= 2:
            # Fallback: show old-style benchmark trend if no P&L data yet
            lines += ["", "## Recent benchmark trend (S&P 500 20d return over last runs)"]
            for entry in perf_history:
                bret = _as_float_or_none(entry.get("benchmark_return_20d"))
                bret_str = f"{bret:+.1%}" if bret is not None else "N/A"
                lines.append(f"  {entry['date']}: S&P 500 20d = {bret_str}")
            first_bret = _as_float_or_none(perf_history[0].get("benchmark_return_20d"))
            last_bret = _as_float_or_none(perf_history[-1].get("benchmark_return_20d"))
            if first_bret is not None and last_bret is not None:
                delta = last_bret - first_bret
                trend = "improving" if delta > 0.005 else ("deteriorating" if delta < -0.005 else "flat")
                lines.append(f"  Trend: benchmark momentum is {trend} ({delta:+.1%} over {len(perf_history)} days).")

        # New signals — supplement line after table for stocks with notable values
        _new_signal_lines = []
        for c in snapshot["candidates"]:
            parts = []
            if c.get("mom_aligned") == 1:
                parts.append("MOM_ALIGNED")
            if c.get("breakout_score") == 1:
                parts.append("BREAKOUT")
            rel = c.get("rel_sector", float("nan"))
            if not math.isnan(rel):
                if rel > 0.03:
                    parts.append(f"SECTOR_LEADER(+{rel:.1%})")
                elif rel < -0.03:
                    parts.append(f"SECTOR_LAGGARD({rel:.1%})")
            if parts:
                _new_signal_lines.append(f"  {sanitize_ticker(c['ticker'])}: {', '.join(parts)}")
        if _new_signal_lines:
            lines += ["", "Signal flags (MOM_ALIGNED=all 3 timeframes up, BREAKOUT=volume+momentum+SMA+RSI, SECTOR_LEADER/LAGGARD=vs sector median):"]
            lines += _new_signal_lines

        if snapshot.get("earnings_warning"):
            lines += ["", snapshot["earnings_warning"]]

        if snapshot.get("news_headlines"):
            lines += ["", snapshot["news_headlines"]]

        if snapshot.get("insider_context"):
            lines += ["", snapshot["insider_context"]]

        if snapshot.get("trends_context"):
            lines += ["", snapshot["trends_context"]]

        lines += [
            "",
            "Generate a portfolio from the candidates above following the game rules and "
            "strategy mandate in your system prompt. Respond ONLY with the JSON object.",
        ]
        return "\n".join(lines)

    def _call_openai(
        self,
        user_message: str,
        regime: str = "NEUTRAL",
        vix: float = float("nan"),
        learning_context: str = "",
        n_participants: int = 844,
    ) -> PortfolioProposal:
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            today=date.today().isoformat(),
            regime_guidance=regime_guidance,
            vix_guidance=_vix_guidance(vix),
            n_participants=n_participants,
        )
        # Inject learning context into the system prompt so it has mandatory-instruction weight.
        # Placed after the strategy rules so it acts as a live override, not a soft suggestion.
        if learning_context:
            system_prompt += (
                "\n\n## ═══ LIVE LEARNING CONSTRAINTS — HIGHEST PRIORITY ═══\n"
                "These rules are derived from verified game performance and OVERRIDE any base instruction above.\n"
                + learning_context
            )

        from agents._prompt_blocks import RATIONALE_GUIDANCE_BLOCK
        system_prompt += RATIONALE_GUIDANCE_BLOCK

        response = self.client.chat.completions.create(
            model=self.MODEL,
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=API_TIMEOUT_SECONDS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )

        usage = response.usage
        cost = log_usage(
            agent_name="OpenAIStrategist",
            model=self.MODEL,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
        )
        logger.info(
            "Strategist tokens — in: %d, out: %d (cost: $%.4f)",
            usage.prompt_tokens,
            usage.completion_tokens,
            cost,
        )

        data = json.loads(response.choices[0].message.content)

        positions = []
        for p in data["positions"]:
            # Accept conviction (new schema) or weight (defensive fallback for stale model output).
            # Guard: float in (0, 1] means the model returned a weight decimal (e.g. 0.20) — map it back.
            raw_conviction = p.get("conviction") or p.get("weight")
            if isinstance(raw_conviction, float) and 0.0 < raw_conviction <= 1.0:
                conviction = max(1, min(10, round(raw_conviction * 40)))
            elif raw_conviction is not None:
                conviction = max(1, min(10, int(raw_conviction)))
            else:
                conviction = 5
            positions.append(Position(
                ticker=p["ticker"],
                weight=conviction_to_weight(conviction),
                rationale=p.get("rationale", ""),
                conviction=conviction,
            ))
        return PortfolioProposal(
            positions=positions,
            reasoning=data.get("reasoning", ""),
            confidence=float(data.get("confidence", 0.5)),
            learning_reflection=data.get("learning_reflection", ""),
        )

    def cross_check(
        self,
        snapshot: MarketSnapshot,
        own_proposal: PortfolioProposal,
        peer_proposals: list[PortfolioProposal],
    ) -> dict:
        """Lightweight second-pass debate: identify agreements and disagreements with peer proposals."""
        own_str = ", ".join(f"{sanitize_ticker(p.ticker)} {p.weight:.0%}" for p in own_proposal.positions)
        peer_lines = []
        for i, peer in enumerate(peer_proposals, 1):
            peer_lines.append(
                f"Peer {i}: " + ", ".join(f"{sanitize_ticker(p.ticker)} {p.weight:.0%}" for p in peer.positions)
            )
        peer_str = "\n".join(peer_lines)
        prompt = (
            f"Your portfolio: {own_str}\n\n"
            f"{peer_str}\n\n"
            "Identify:\n"
            "(a) tickers from your portfolio that also appear in at least one peer portfolio\n"
            "(b) any ticker a peer proposes at >=15% that you excluded — one-sentence reason you disagree or concede\n\n"
            'Return JSON only: {"agrees": ["TICKER1", ...], "disagrees": [{"ticker": "X", "reason": "..."}]}'
        )
        try:
            response = self.client.chat.completions.create(
                model="gpt-5.4-nano",
                response_format={"type": "json_object"},
                temperature=0.0,
                messages=[
                    {"role": "system", "content": "You are a portfolio analyst. Return JSON only."},
                    {"role": "user", "content": prompt},
                ],
            )
            log_usage("OpenAIStrategist_crosscheck", "gpt-5.4-nano",
                      response.usage.prompt_tokens, response.usage.completion_tokens)
            return json.loads(response.choices[0].message.content)
        except Exception as exc:
            logger.warning("Strategist cross_check failed (non-fatal): %s", exc)
            return {}
