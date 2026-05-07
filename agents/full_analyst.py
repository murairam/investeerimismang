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
import time
from datetime import date
from typing import Optional

from openai import APIConnectionError, APITimeoutError, BadRequestError, OpenAI

from agents.base_agent import BaseAgent, conviction_to_weight
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
    "BULL": "BULL regime — TARGET 5 positions for maximum conviction. Only add a 6th if genuinely high-conviction (score ≥ 8). 5 names at full conviction is ideal. Do NOT add filler for diversification — diversification loses competitions.",
    "BEAR": "BEAR regime — 6–12 positions. Spread risk broadly. Lower conviction on high-beta names. Prefer names with earnings visibility.",
    "NEUTRAL": "NEUTRAL regime — 5–10 positions. Quality over quantity — only add a position if signals are genuinely compelling.",
}

_SYSTEM_PROMPT = """You are an INDEPENDENT FULL-SIGNAL ANALYST for the Äripäev/SEB Investment Game (Estonia). Game ends 19 June 2026. Goal: highest absolute return.

Today: {today}. This is a competition with {n_participants} participants. Only #1 wins — median returns = losing. INTELLIGENT AGGRESSION is required: concentration is correct, diversification loses competitions. Find the 5 best picks across all signals, not a safe diversified 10-stock portfolio.

You provide a completely fresh second opinion — you see ALL signals (momentum, catalyst, and everything in between). Your job is to find the best portfolio across every signal dimension, not just momentum OR catalysts.

You are one of THREE independent analysts:
1. Momentum Strategist — sees only trend/Sharpe signals
2. Catalyst Hunter (Gemini) — sees only catalyst signals (vol_ratio, RSI, short interest, IV)
3. YOU — full analyst, sees everything, fresh independent view

The Risk Manager will synthesize all three. Your value is finding picks that neither specialist might surface — stocks with good all-round signals across both momentum and catalyst dimensions.

## Game rules
- 5 to 20 stocks. No duplicates.
- Markets: US S&P 500, OMX Helsinki, OMX Stockholm, OBX Norway, OMX Copenhagen, Baltic.
- Regime-based position count: {regime_guidance}

## Signal guide — use ALL columns
- **Sharpe_20d**: risk-adjusted 20d momentum. High Sharpe = smooth persistent uptrend.
- **5d Ret / 60d Ret**: recent acceleration vs longer trend.
- **RSI**: > 75 with vol_ratio > 1.5 = confirmed breakout (bullish). RSI > 82 AND 52wH% ≥ -2% AND vol_ratio < 1.8 = exhaustion risk, not a fresh entry — lower conviction (score ≤ 5).
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
- Non-US names are optional alpha sources — include them only when they beat available US alternatives on current signals
- ShortInt and IV fields are shown only when available in today's data

## Sizing — MANDATORY
Output `conviction` (integer 1–10), NOT a weight. Python converts conviction to position size.
- 10 = max conviction (4+ positive signals, clear cross-signal consensus)
- 8–9 = high conviction (strong on ≥3 signals)
- 5–7 = medium conviction (solid signals, worth a slot)
- 1–4 = speculative / diversifier
Every position must have a DIFFERENT conviction score.
Conviction → weight mapping (Python-computed): 10→~25% | 9→~22% | 8→~20% | 7→~18% | 6→~16% | 5→~13% | 4→~11% | 3→~9% | 2→~7% | 1→~5%

## Macro context
Follow the signals — no hardcoded sector or stock bias. Whatever has the strongest combined signal today is your focus.

## Output — valid JSON only, no other text
{{"positions":[{{"ticker":"X","conviction":9,"rationale":"why this pick at this conviction score based on specific signals"}}],"reasoning":"2-3 sentence thesis","confidence":0.80,"learning_reflection":"One sentence: how today's picks adapt based on recent learning context."}}"""


class OpenAIFullAnalyst(BaseAgent):
    MAX_RETRIES = 3
    MAX_CANDIDATES = 200  # allow full table per user preference
    LONG_MAX_TOKENS = 10000
    FAST_MAX_TOKENS = 4096
    LONG_TIMEOUT = 300  # cap DeepSeek request to ~5 minutes to avoid hanging runs
    FAST_TIMEOUT = 150  # seconds
    FAST_TRIGGER_SECONDS = 240  # if primary exceeds this wall time, jump to fast fallback
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
        # Once on OpenAI, disable OpenRouter path to avoid flip-flop.
        self._openrouter_enabled = False

    def _repair_with_openai_gpt54(self, raw_text: str) -> Optional[dict]:
        """Repair non-JSON or truncated output using gpt-5.4."""
        if not raw_text.strip():
            return None
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "Convert the provided text to valid JSON with keys: "
                    "positions (array of {ticker, conviction (int 1-10), rationale}), "
                    "reasoning, confidence, learning_reflection. Return JSON only."
                ),
            },
            {"role": "user", "content": raw_text[:16000]},
        ]
        try:
            repair_response = self.client.chat.completions.create(
                model="gpt-5.4",
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout=API_TIMEOUT_SECONDS,
                messages=prompt_messages,
            )
            repaired = repair_response.choices[0].message.content or ""
            return _extract_json(repaired)
        except Exception as exc:
            logger.warning("FullAnalyst gpt-5.4 JSON repair failed: %s", exc)
            return None

    def propose(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        user_message = self._build_user_message(snapshot, prior_proposal)
        regime = snapshot.get("regime", "NEUTRAL")
        learning_context = snapshot.get("learning_context", "")
        n_participants = snapshot.get("n_participants", 844)

        # Attempt 1: OpenRouter/DeepSeek with reasoning
        start_time = time.perf_counter()
        try:
            proposal = self._call_openai(user_message, regime, learning_context, fast_mode=False, n_participants=n_participants)
            logger.info(
                "FullAnalyst produced %d positions (confidence %.0f%%, model: %s)",
                len(proposal.positions),
                proposal.confidence * 100,
                self.model,
            )
            return proposal
        except (json.JSONDecodeError, KeyError, ValueError, BadRequestError, APIConnectionError, APITimeoutError) as exc:
            logger.warning("FullAnalyst primary attempt failed: %s", exc)
            # If using OpenRouter, switch to OpenAI fast fallback
            if self._openrouter_enabled and self.model != self.MODEL:
                self._switch_to_openai_fallback()

        # If primary took too long, trigger fast fallback to keep wall-clock bounded
        elapsed = time.perf_counter() - start_time
        if elapsed > self.FAST_TRIGGER_SECONDS and self.model != self.MODEL:
            self._switch_to_openai_fallback()

        # Attempt 2: Fast OpenAI fallback (no reasoning mode, smaller token/timeout)
        try:
            proposal = self._call_openai(user_message, regime, learning_context, fast_mode=True, n_participants=n_participants)
            logger.info(
                "FullAnalyst produced %d positions (confidence %.0f%%, model: %s, fast_fallback=True)",
                len(proposal.positions),
                proposal.confidence * 100,
                self.model,
            )
            return proposal
        except (json.JSONDecodeError, KeyError, ValueError, BadRequestError, APIConnectionError, APITimeoutError) as exc2:
            logger.warning("FullAnalyst fast fallback failed: %s", exc2)
            logger.warning("FullAnalyst exhausted retries — returning empty proposal")
            return PortfolioProposal()

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

        preprocessed_rows: list[dict] = []
        for c in ranked:
            ticker = c["ticker"]
            preprocessed_rows.append(
                {
                    "candidate": c,
                    "short_interest": short_interest.get(ticker),
                    "premarket_gap": premarket_gap.get(ticker),
                    "iv_proxy": iv_proxy.get(ticker),
                }
            )

        if self.MAX_CANDIDATES and len(preprocessed_rows) > self.MAX_CANDIDATES:
            logger.info(
                "FullAnalyst truncating candidate table: %d → %d rows",
                len(preprocessed_rows),
                self.MAX_CANDIDATES,
            )
            preprocessed_rows = preprocessed_rows[: self.MAX_CANDIDATES]

        show_short_interest = any(row["short_interest"] is not None for row in preprocessed_rows)
        show_premarket_gap = any(row["premarket_gap"] is not None for row in preprocessed_rows)
        show_iv = any(row["iv_proxy"] is not None for row in preprocessed_rows)
        show_wsb = any(
            not math.isnan(row["candidate"].get("reddit_hype_score", float("nan")))
            and row["candidate"].get("reddit_hype_score", 0) > 0
            for row in preprocessed_rows
        )

        header_fields = [
            "Ticker", "Market", "Sector", "20d(σ)", "Sh(σ)", "5d(σ)", "60dRet", "RSI", "vIdx(σ)",
            "52wH%", "Beta", "VR(σ)", "MACD", "ATR%",
        ]
        if show_short_interest:
            header_fields.append("ShrtInt")
        if show_premarket_gap:
            header_fields.append("PreMkt")
        if show_iv:
            header_fields.append("IV")
        if show_wsb:
            header_fields.append("WsbHype")
        header_fields += ["DivYld", "AnaRtg", "AnaUp%", "Price"]
        header = ",".join(header_fields)

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
            f"Regime: {regime} | SPX vs 50d SMA: {spx_vs:.1%} | VIX: {vix_str}",
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
            "ShrtInt / PreMkt / IV columns are included only when available in today's data.",
            "AnaRtg: analyst consensus 1=StrongBuy→5=StrongSell. AnaUp%: implied upside to mean target. High momentum + positive upside = conviction. High momentum + negative upside = stretched/crowded.",
            "WsbHype: Reddit/WSB mention rank score 0-100 (rank 1→100, off-list→0, Nordic/Baltic→N/A). Rising trajectory = growing retail attention.",
            "",
            header
        ]

        def fmt(v: float, fmt_str: str = ".1%") -> str:
            return "N/A" if (v is None or (isinstance(v, float) and math.isnan(v))) else format(v, fmt_str)

        def fmt_opt(v: "float | None", fmt_str: str = ".1%") -> str:
            return "" if v is None else format(v, fmt_str)

        def fmtz(v: float) -> str:
            return "N/A" if (v is None or (isinstance(v, float) and math.isnan(v))) else f"{v:+.1f}"

        for row in preprocessed_rows:
            c = row["candidate"]
            safe_ticker = sanitize_ticker(c["ticker"])
            values = [
                safe_ticker,
                c["market"],
                c.get("sector", "?"),
                fmtz(c.get("z_momentum", float("nan"))),
                fmtz(c.get("z_sharpe_20d", float("nan"))),
                fmtz(c.get("z_mom_5d", float("nan"))),
                fmt(c["mom_60d"]),
                fmt(c["rsi_14"], ".1f"),
                fmtz(c.get("z_vs_index", float("nan"))),
                fmt(c["pct_from_52w_high"]),
                fmt(c["beta"], ".2f"),
                fmtz(c.get("z_vol_ratio", float("nan"))),
                fmt(c.get("macd_hist", float("nan"))),
                fmt(c.get("atr_pct", float("nan"))),
            ]
            if show_short_interest:
                values.append(fmt_opt(row["short_interest"], ".1%"))
            if show_premarket_gap:
                values.append(fmt_opt(row["premarket_gap"], "+.1%"))
            if show_iv:
                values.append(fmt_opt(row["iv_proxy"], ".2f"))
            if show_wsb:
                hype = c.get("reddit_hype_score", float("nan"))
                traj = c.get("momentum_trajectory", "flat")
                if math.isnan(hype):
                    values.append("N/A")
                else:
                    traj_sym = "↑" if traj == "rising" else ("↓" if traj == "falling" else "→")
                    values.append(f"{hype:.0f}{traj_sym}")
            values += [
                fmt(c.get("dividend_yield", float("nan"))),
                fmt(c.get("analyst_rating", float("nan")), ".1f"),
                fmt(c.get("analyst_upside", float("nan"))),
                f"{c['last_price']:.2f}",
            ]
            lines.append(",".join(values))

        if prior_proposal and prior_proposal.positions:
            lines += ["", "Yesterday's holdings (for continuity reference):"]
            for pos in prior_proposal.positions:
                lines.append(f"{sanitize_ticker(pos.ticker)},{pos.weight:.1%}")

        # Late-game mode and groupthink alerts
        late_game_mode = snapshot.get("late_game_mode", "NORMAL")
        if late_game_mode == "RECOUP":
            lines += ["", "LATE-GAME MODE: RECOUP — portfolio underperforming, final 3 weeks. Favour higher-beta/catalyst names."]
        elif late_game_mode == "LOCK_IN":
            lines += ["", "LATE-GAME MODE: LOCK_IN — portfolio outperforming, final 3 weeks. Favour beta 1.0-1.4 with confirmed momentum."]
        if snapshot.get("groupthink_risk"):
            lines += ["", "⚠ GROUPTHINK ALERT: >60% consensus across agents — look for overlooked high-signal picks not in the obvious consensus."]

        # Signal flags for novel signals
        _new_signal_lines = []
        for c in snapshot.get("candidates", []):
            parts = []
            if c.get("mom_aligned") == 1:
                parts.append("MOM_ALIGNED")
            if c.get("breakout_score") == 1:
                parts.append("BREAKOUT")
            rel = c.get("rel_sector", float("nan"))
            if not isinstance(rel, float):
                rel = float("nan")
            if not math.isnan(rel):
                if rel > 0.03:
                    parts.append(f"SECTOR_LEADER(+{rel:.1%})")
                elif rel < -0.03:
                    parts.append(f"SECTOR_LAGGARD({rel:.1%})")
            if parts:
                _new_signal_lines.append(f"  {sanitize_ticker(c['ticker'])}: {', '.join(parts)}")
        if _new_signal_lines:
            lines += ["", "Signal flags (MOM_ALIGNED=all timeframes up, BREAKOUT=quality breakout, SECTOR_LEADER/LAGGARD=vs sector median):"]
            lines += _new_signal_lines

        if snapshot.get("earnings_warning"):
            lines += ["", snapshot["earnings_warning"]]

        if snapshot.get("news_headlines"):
            lines += ["", snapshot["news_headlines"]]

        if snapshot.get("insider_context"):
            lines += ["", snapshot["insider_context"]]

        if snapshot.get("trends_context"):
            lines += ["", snapshot["trends_context"]]

        lines += ["", "Build your portfolio using all available signals. Return valid JSON only."]
        message = "\n".join(lines)
        logger.info(
            "FullAnalyst prompt size: %d chars, %d candidates",
            len(message),
            len(preprocessed_rows),
        )
        return message

    def _call_openai(
        self,
        user_message: str,
        regime: str = "NEUTRAL",
        learning_context: str = "",
        fast_mode: bool = False,
        n_participants: int = 844,
    ) -> PortfolioProposal:
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = _SYSTEM_PROMPT.format(
            today=date.today().isoformat(),
            regime_guidance=regime_guidance,
            n_participants=n_participants,
        )
        if learning_context:
            system_prompt += (
                "\n\n## ═══ LIVE LEARNING CONSTRAINTS — HIGHEST PRIORITY ═══\n"
                "These rules are derived from verified game performance and OVERRIDE any base instruction above.\n"
                + learning_context
            )

        from agents._prompt_blocks import RATIONALE_GUIDANCE_BLOCK
        system_prompt += RATIONALE_GUIDANCE_BLOCK

        # OpenRouter does not reliably enforce response_format or handle long outputs —
        # use max_tokens to prevent truncation and omit response_format for OR calls.
        openrouter_call = self._openrouter_enabled and self.model != self.MODEL and not fast_mode
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
            call_kwargs["max_tokens"] = self.LONG_MAX_TOKENS
            if "deepseek" in self.model.lower():
                call_kwargs["extra_body"] = {"reasoning": {"enabled": True}}
                call_kwargs["timeout"] = self.LONG_TIMEOUT  # allow long reasoning but under orchestrator window
        else:
            call_kwargs["response_format"] = {"type": "json_object"}
            if fast_mode:
                call_kwargs["max_completion_tokens"] = self.FAST_MAX_TOKENS
                call_kwargs["timeout"] = self.FAST_TIMEOUT
            else:
                call_kwargs["timeout"] = API_TIMEOUT_SECONDS

        try:
            response = self.client.chat.completions.create(model=self.model, **call_kwargs)
        except (BadRequestError, APIConnectionError, APITimeoutError) as exc:
            if self._openrouter_enabled and self.model != self.MODEL:
                logger.warning("OpenRouter FullAnalyst request failed (%s). Falling back to OpenAI.", exc)
                self._switch_to_openai_fallback()
                call_kwargs.pop("max_tokens", None)
                call_kwargs.pop("extra_body", None)  # OpenRouter-specific; not valid for OpenAI
                call_kwargs["timeout"] = API_TIMEOUT_SECONDS  # reset any DeepSeek-specific timeout override
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
        # OpenRouter (DeepSeek) returns text; parse to JSON, with repair via GPT-5.4 if needed.
        try:
            data = _extract_json(raw_content)
        except ValueError:
            logger.warning("FullAnalyst primary output not valid JSON — attempting repair with gpt-5.4")
            data = self._repair_with_openai_gpt54(raw_content)
            if data is None:
                raise ValueError("FullAnalyst could not repair non-JSON output")
        raw_positions = data.get("positions", [])

        positions = []
        for p in raw_positions:
            # Accept conviction (new schema) or weight (defensive fallback for stale model output).
            # Guard: float in (0, 1] means the model returned a weight decimal — map it back.
            raw_conv = p.get("conviction") or p.get("weight")
            if isinstance(raw_conv, float) and 0.0 < raw_conv <= 1.0:
                conviction = max(1, min(10, round(raw_conv * 40)))
            elif raw_conv is not None:
                conviction = max(1, min(10, int(raw_conv)))
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
        _snapshot: MarketSnapshot,
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
