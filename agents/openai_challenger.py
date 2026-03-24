"""
OpenAIFullAnalyst — Independent Full-Signal Analyst (Qwen3-32B via OpenRouter, fallback gpt-5.4-nano).

Sees ALL signals (momentum + catalyst) and provides a completely independent
second opinion on portfolio construction. Not constrained to momentum-only or
catalyst-only — finds the best picks across every signal dimension.
"""
import json
import logging
import math
import os
from datetime import date
from typing import Optional

from openai import APIConnectionError, APITimeoutError, BadRequestError, OpenAI

from agents.base_agent import BaseAgent
from config import (
    API_TIMEOUT_SECONDS,
    MOMENTUM_WINDOW,
    OPENROUTER_ANALYST_MODEL,
    OPENROUTER_BASE_URL,
    USE_OPENROUTER_FOR_SECONDARY_AGENTS,
)
from data.cost_tracker import log_usage
from data.fetcher import MarketSnapshot, sanitize_ticker
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict:
    """
    Parse JSON from model output, handling prose prefix/suffix and truncation.
    Tries json.loads first; on failure, locates the first '{' and attempts
    progressively shorter substrings until a valid object is found.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find first '{' — model may have output prose before the JSON
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model response")
    candidate = text[start:]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Truncated JSON: walk backwards from the end to find last '}' that closes the root object
    for end in range(len(candidate) - 1, 0, -1):
        if candidate[end] == "}":
            try:
                return json.loads(candidate[: end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("Could not extract valid JSON from model response")


_REGIME_GUIDANCE = {
    "BULL": "BULL regime — TARGET 5 positions for maximum conviction. Only add a 6th if genuinely high-conviction. Push top picks to 20–25%. 5 names at 20% each is ideal. Do NOT add filler for diversification — diversification loses competitions.",
    "BEAR": "BEAR regime — 6–12 positions. Spread risk broadly. Cap individual positions at 15%. Prefer names with earnings visibility.",
    "NEUTRAL": "NEUTRAL regime — 5–10 positions. Quality over quantity — only add a position if signals are genuinely compelling.",
}

_SYSTEM_PROMPT = """You are an INDEPENDENT FULL-SIGNAL ANALYST for the Äripäev/SEB Investment Game (Estonia). Game ends 19 June 2026. Goal: highest absolute return.

Today: {today}. This is a competition with 844 participants. Only #1 wins — median returns = losing. INTELLIGENT AGGRESSION is required: concentration is correct, diversification loses competitions. Find the 5 best picks across all signals, not a safe diversified 10-stock portfolio.

You provide a completely fresh second opinion — you see ALL signals (momentum, catalyst, and everything in between). Your job is to find the best portfolio across every signal dimension, not just momentum OR catalysts.

You are one of THREE independent analysts:
1. Momentum Strategist — sees only trend/Sharpe signals
2. Catalyst Hunter (Gemini) — sees only catalyst signals (vol_ratio, RSI, short interest, IV)
3. YOU — full analyst, sees everything, fresh independent view

The Risk Manager will synthesize all three. Your value is finding picks that neither specialist might surface — stocks with good all-round signals across both momentum and catalyst dimensions.

## Game rules
- 5 to 20 stocks. Each position: 5%–25%. Total weight: ≤100%. No duplicates.
- Markets: US S&P 500, OMX Helsinki, OMX Stockholm, OBX Norway, OMX Copenhagen, Baltic.
- Regime-based position count: {regime_guidance}

## Signal guide — use ALL columns
- **Sharpe_20d**: risk-adjusted 20d momentum. High Sharpe = smooth persistent uptrend.
- **5d Ret / 60d Ret**: recent acceleration vs longer trend.
- **RSI**: > 75 with vol_ratio > 1.5 = confirmed breakout (bullish). RSI > 82 AND 52wH% ≥ -2% AND vol_ratio < 1.8 = exhaustion risk — cap at 15%, this is a hold not a fresh entry.
- **vs Idx**: stock beat its own market benchmark. Pure alpha signal.
- **52wH%**: always ≤ 0%. 0.0% = AT 52-week high. Bullish when vol_ratio > 1.5 confirms the move. Without volume, at-peak = no cushion for a pullback.
- **Beta**: amplifies gains in bull market. Target high beta in BULL regime.
- **vol_ratio**: > 1.5 = high-volume confirmation of the move. < 0.7 = weak unconfirmed move.
- **MACD**: positive histogram = accelerating momentum. Negative = decelerating.
- **ATR%**: daily expected move. High ATR% = volatile active mover.
- **ShortInt**: short % of float. > 15% + positive momentum + vol_ratio > 1.5 = squeeze setup.
- **PreMktGap**: positive gap vs prior close = opening momentum confirmation.
- **IV**: implied vol (US options) or 20d realized vol (Nordic/Baltic fallback). Spike = event catalyst.
- **DivYld**: game auto-reinvests dividends. 4% yield = ~1.5% free return over 75 days.

## What to look for
- Perfect setups: high Sharpe + vol_ratio > 1.5 + RSI > 70 + positive MACD + vs_index > 0
- Good setups: any 3-4 of the above
- Avoid: negative vs_index AND vol_ratio < 0.8 AND negative MACD (dead momentum)
- Diversify: at least 2 picks from non-US markets (unless US signals are overwhelmingly dominant)
- Baltic/Nordic: do NOT penalize for N/A short interest or IV — evaluate on volume, momentum, RSI

## Sizing — MANDATORY
- Highest conviction (4+ positive signals): 20–25%
- Strong signals (3 positive): 12–18%
- Speculative / diversifier: 5–10%
Every position must have a different weight.

## Macro context
Follow the signals — no hardcoded sector or stock bias. Whatever has the strongest combined signal today is your focus.

## Output — valid JSON only, no other text
{{"positions":[{{"ticker":"X","weight":0.20,"rationale":"why this pick at this weight based on specific signals"}}],"reasoning":"2-3 sentence thesis","confidence":0.80,"learning_reflection":"One sentence: how today's picks adapt based on recent learning context."}}"""


class OpenAIFullAnalyst(BaseAgent):
    MAX_RETRIES = 3
    MODEL = "gpt-5.4-nano"

    def __init__(self) -> None:
        self._openrouter_enabled = USE_OPENROUTER_FOR_SECONDARY_AGENTS and bool(os.environ.get("OPENROUTER_API_KEY"))
        if self._openrouter_enabled:
            self.client = OpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url=OPENROUTER_BASE_URL,
            )
            self.model = OPENROUTER_ANALYST_MODEL
        else:
            self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            self.model = self.MODEL

    def _switch_to_openai_fallback(self) -> None:
        if self.model == self.MODEL:
            return
        logger.warning(
            "Switching FullAnalyst from OpenRouter model '%s' to OpenAI fallback '%s'",
            self.model,
            self.MODEL,
        )
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = self.MODEL

    def propose(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        user_message = self._build_user_message(snapshot, prior_proposal)
        regime = snapshot.get("regime", "NEUTRAL")
        learning_context = snapshot.get("learning_context", "")

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                proposal = self._call_openai(user_message, regime, learning_context)
                logger.info(
                    "FullAnalyst[%s] produced %d positions (confidence %.0f%%)",
                    self.model,
                    len(proposal.positions),
                    proposal.confidence * 100,
                )
                return proposal
            except (json.JSONDecodeError, KeyError, ValueError, BadRequestError, APIConnectionError, APITimeoutError) as exc:
                logger.warning("FullAnalyst attempt %d/%d failed: %s", attempt, self.MAX_RETRIES, exc)
                if attempt == self.MAX_RETRIES:
                    logger.warning("FullAnalyst exhausted retries — returning empty proposal")
                    return PortfolioProposal()

        return PortfolioProposal()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_user_message(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> str:
        vix = snapshot.get("vix_level", float("nan"))
        spx_vs = snapshot.get("spx_vs_200d", 0.0)
        regime = snapshot.get("regime", "NEUTRAL")
        vix_str = f"{vix:.1f}" if not math.isnan(vix) else "N/A"
        rscore = snapshot.get("regime_score", 50)
        score_label = (
            "DEFENSIVE" if rscore < 30 else
            "CAUTIOUS"  if rscore < 50 else
            "NEUTRAL"   if rscore < 70 else
            "BULLISH"
        )

        short_interest = snapshot.get("short_interest", {})
        premarket_gap = snapshot.get("premarket_gap", {})
        iv_proxy = snapshot.get("iv_proxy", {})

        ranked_source = snapshot.get("ranked_candidates", snapshot.get("candidates", []))
        candidate_map = {c["ticker"]: c for c in snapshot.get("candidates", [])}
        ranked: list[dict] = []
        for item in ranked_source:
            if not isinstance(item, dict):
                continue
            ticker = item.get("ticker")
            if isinstance(ticker, str) and ticker in candidate_map:
                ranked.append(candidate_map[ticker])
        if not ranked:
            ranked = snapshot.get("candidates", [])

        header = "Ticker,Market,Sector,20dRet,Sharpe,5dRet,60dRet,RSI,vsIdx,52wH%,Beta,VolR,MACD,ATR%,ShrtInt,PreMkt,IV,DivYld,AnaRtg,AnaUp%,Price"

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

        # Sector rotation context
        sector_mom = snapshot.get("sector_momentum", {})
        sector_rotation_line = ""
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
                _lag = [s for s, d in _valid if d["avg_mom_20d"] < 0]
                sector_rotation_line = f"Sector rotation (20d, breadth): {' | '.join(_parts[:5])}"
                if _lag:
                    sector_rotation_line += f"  |  Laggards: {', '.join(_lag[:4])}"
                sector_rotation_line += (
                    "\nSector action rule: if a sector's breadth is below 40%, it is losing internal momentum — "
                    "reduce or exit your weakest performer in that sector and redeploy into the leading sector."
                )

        lines = [
            f"Market snapshot as of {snapshot['as_of_date']}",
            f"Benchmark (S&P 500) {MOMENTUM_WINDOW}-day return: {snapshot['benchmark_return']:.1%}",
            f"Regime: {regime} | SPX vs 200d SMA: {spx_vs:.1%} | VIX: {vix_str}",
            f"Composite regime score: {rscore}/100 — {score_label}",
        ]
        portfolio_state_context = snapshot.get("portfolio_state_context", "")
        if portfolio_state_context:
            lines += ["", portfolio_state_context]
        if comm_line:
            lines.append(comm_line)
        if sector_rotation_line:
            lines.append(sector_rotation_line)
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
        lines += [
            "",
            "Top candidates (sorted by combined score) — ALL signals:",
            "ShrtInt = short % of float (N/A for Baltic/Nordic). PreMkt = premarket gap. IV = implied vol or realized HV fallback.",
            "AnaRtg: analyst consensus 1=StrongBuy→5=StrongSell. AnaUp%: implied upside to mean target. High momentum + positive upside = conviction. High momentum + negative upside = stretched/crowded.",
            "",
            header
        ]

        def fmt(v: float, fmt_str: str = ".1%") -> str:
            return "N/A" if (v is None or (isinstance(v, float) and math.isnan(v))) else format(v, fmt_str)

        def fmt_opt(v: "float | None", fmt_str: str = ".1%") -> str:
            return "N/A" if v is None else format(v, fmt_str)

        for c in ranked:
            t = c["ticker"]
            safe_ticker = sanitize_ticker(t)
            si = short_interest.get(t)
            pm = premarket_gap.get(t)
            iv = iv_proxy.get(t)
            lines.append(
                f"{safe_ticker},{c['market']},{c.get('sector', '?')},"
                f"{fmt(c['momentum'])},{fmt(c['sharpe_20d'], '.2f')},"
                f"{fmt(c['mom_5d'])},{fmt(c['mom_60d'])},{fmt(c['rsi_14'], '.1f')},"
                f"{fmt(c['vs_index'])},{fmt(c['pct_from_52w_high'])},"
                f"{fmt(c['beta'], '.2f')},{fmt(c['vol_ratio'], '.2f')},"
                f"{fmt(c.get('macd_hist', float('nan')))},{fmt(c.get('atr_pct', float('nan')))},"
                f"{fmt_opt(si, '.1%')},{fmt_opt(pm, '+.1%')},{fmt_opt(iv, '.2f')},"
                f"{fmt(c.get('dividend_yield', float('nan')))},{fmt(c.get('analyst_rating', float('nan')), '.1f')},"
                f"{fmt(c.get('analyst_upside', float('nan')))},{c['last_price']:.2f}"
            )

        if prior_proposal and prior_proposal.positions:
            lines += ["", "Yesterday's holdings (for continuity reference):"]
            for pos in prior_proposal.positions:
                lines.append(f"{sanitize_ticker(pos.ticker)},{pos.weight:.1%}")

        if snapshot.get("earnings_warning"):
            lines += ["", snapshot["earnings_warning"]]

        if snapshot.get("news_headlines"):
            lines += ["", snapshot["news_headlines"]]

        if snapshot.get("insider_context"):
            lines += ["", snapshot["insider_context"]]

        if snapshot.get("trends_context"):
            lines += ["", snapshot["trends_context"]]

        lines += ["", "Build your portfolio using all available signals. Return valid JSON only."]
        return "\n".join(lines)

    def _call_openai(
        self,
        user_message: str,
        regime: str = "NEUTRAL",
        learning_context: str = "",
    ) -> PortfolioProposal:
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = _SYSTEM_PROMPT.format(
            today=date.today().isoformat(),
            regime_guidance=regime_guidance,
        )
        if learning_context:
            system_prompt += f"\n\n## Live learning — MANDATORY overrides from past runs\n{learning_context}"

        # OpenRouter does not reliably enforce response_format or handle long outputs —
        # use max_tokens to prevent truncation and omit response_format for OR calls.
        openrouter_call = self._openrouter_enabled and self.model != self.MODEL
        # Qwen3 runs in "thinking" mode by default — disable it to avoid 3+ minute hangs
        effective_user_message = ("/no_think\n\n" + user_message) if openrouter_call and "qwen3" in self.model.lower() else user_message
        call_kwargs: dict = dict(
            temperature=0.2,
            timeout=API_TIMEOUT_SECONDS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": effective_user_message},
            ],
        )
        if openrouter_call:
            call_kwargs["max_tokens"] = 3000
            if "deepseek" in self.model.lower():
                call_kwargs["extra_body"] = {"reasoning": {"enabled": True}}
        else:
            call_kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self.client.chat.completions.create(model=self.model, **call_kwargs)
        except (BadRequestError, APIConnectionError, APITimeoutError) as exc:
            if self._openrouter_enabled and self.model != self.MODEL:
                logger.warning("OpenRouter FullAnalyst request failed (%s). Falling back to OpenAI.", exc)
                self._switch_to_openai_fallback()
                call_kwargs.pop("max_tokens", None)
                call_kwargs["response_format"] = {"type": "json_object"}
                response = self.client.chat.completions.create(model=self.model, **call_kwargs)
            else:
                raise

        if response is None:
            raise ValueError("Empty response from model")

        finish_reason = (response.choices[0].finish_reason or "").lower()
        if finish_reason == "length":
            logger.warning("FullAnalyst response truncated (finish_reason=length) — attempting partial JSON parse")

        usage = response.usage
        cost = log_usage(
            agent_name="OpenAIFullAnalyst",
            model=self.model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
        )
        logger.info(
            "FullAnalyst tokens — in: %d, out: %d (cost: $%.4f)",
            usage.prompt_tokens,
            usage.completion_tokens,
            cost,
        )

        raw_content = response.choices[0].message.content or ""
        data = _extract_json(raw_content)
        raw_positions = data.get("positions", [])

        # Auto-fix: if any weight > 1.0 the model output percentages
        if any(float(p["weight"]) > 1.0 for p in raw_positions):
            logger.warning("FullAnalyst returned percentage weights — auto-converting to decimals")
            for p in raw_positions:
                p["weight"] = float(p["weight"]) / 100.0

        positions = [
            Position(
                ticker=p["ticker"],
                weight=float(p["weight"]),
                rationale=p.get("rationale", ""),
            )
            for p in raw_positions
        ]
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
            call_kwargs: dict = {
                "temperature": 0.0,
                "messages": [
                    {"role": "system", "content": "You are a portfolio analyst. Return JSON only."},
                    {"role": "user", "content": prompt},
                ],
            }
            if self._openrouter_enabled and self.model != self.MODEL:
                call_kwargs["max_tokens"] = 1200
            else:
                call_kwargs["response_format"] = {"type": "json_object"}

            response = self.client.chat.completions.create(model=self.model, **call_kwargs)
            log_usage("OpenAIFullAnalyst_crosscheck", self.model,
                      response.usage.prompt_tokens, response.usage.completion_tokens)
            raw_text = response.choices[0].message.content or ""
            return _extract_json(raw_text)
        except Exception as exc:
            logger.warning("FullAnalyst cross_check failed (non-fatal): %s", exc)
            if self.model != self.MODEL:
                try:
                    fallback_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
                    response = fallback_client.chat.completions.create(
                        model=self.MODEL,
                        response_format={"type": "json_object"},
                        temperature=0.0,
                        messages=[
                            {"role": "system", "content": "You are a portfolio analyst. Return JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                    )
                    log_usage(
                        "OpenAIFullAnalyst_crosscheck_fallback",
                        self.MODEL,
                        response.usage.prompt_tokens,
                        response.usage.completion_tokens,
                    )
                    return json.loads(response.choices[0].message.content)
                except Exception as exc2:
                    logger.warning("FullAnalyst cross_check OpenAI fallback failed (non-fatal): %s", exc2)
            return {}


# Backwards-compatibility alias (orchestrator imports OpenAIChallenger)
OpenAIChallenger = OpenAIFullAnalyst
