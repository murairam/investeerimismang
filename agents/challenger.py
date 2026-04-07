"""
Challenger — Catalyst Hunter (OpenRouter primary).

Independent second opinion focused on explosive near-term catalysts:
short squeeze setups, premarket gap-ups, IV spikes, vol_ratio breakouts.
Signal table shows CATALYST signals only (vol_ratio, RSI, short interest,
premarket gap, IV, ATR%, dividend yield) — complementing the momentum-only
Strategist for genuine signal divergence.

Fallback chain: OpenRouter (NVIDIA Nemotron) -> Gemini -> OpenAI gpt-5.4-nano.
Model: nvidia/nemotron-3-super-120b-a12 primary.
SDK: google-genai (replaces deprecated google.generativeai).
"""
import json
import logging
import math
import os
from datetime import date
from typing import Optional

from google import genai
from google.genai import types
from openai import OpenAI

import config
from agents.base_agent import BaseAgent, conviction_to_weight
from data.cost_tracker import log_usage
from data.fetcher import MarketSnapshot, sanitize_ticker
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict:
    """Parse JSON from model output, tolerating prose prefix/suffix and truncation."""
    import re as _re
    text = text.strip()
    # Strip thinking blocks emitted by reasoning models (Qwen3, Nemotron, etc.)
    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()
    # Strip markdown code fences (```json ... ```)
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model response")
    candidate = text[start:]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    for end in range(len(candidate) - 1, 0, -1):
        if candidate[end] == "}":
            try:
                return json.loads(candidate[: end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("Could not extract valid JSON from model response")

def _sanitize_positions(raw: list) -> list:
    """Strip Z-score suffixes (σ) and other non-numeric chars from conviction/weight fields.
    Nemotron sometimes copies signal-table values (e.g. '-0.1σ') into numeric fields."""
    import re as _re
    cleaned = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        w = p.get("conviction") or p.get("weight")
        if isinstance(w, str):
            w = _re.sub(r"[^\d.\-]", "", w)
            if w == "":
                continue  # skip empty numeric strings
            try:
                w = float(w)
            except (ValueError, TypeError):
                continue  # skip malformed position
        try:
            w = float(w)
        except (ValueError, TypeError):
            continue
        if w <= 0:
            continue  # skip zero/negative values
        p["conviction"] = w
        cleaned.append(p)
    return cleaned


_REGIME_GUIDANCE = {
    "BULL": "BULL regime — TARGET 5 catalyst plays for maximum conviction. Only add a 6th if genuinely high-conviction (score ≥ 8). Vol_ratio > 1.5 + RSI > 75 = ideal breakout. No filler — diversification loses competitions.",
    "BEAR": "BEAR regime — 5-8 positions. Find stocks with positive momentum regardless of regime. Max-size the winners — going up in a bear market beats falling less.",
    "NEUTRAL": "NEUTRAL regime — 5-10 catalyst picks. Include a pick only if you have genuine conviction in its setup.",
}

_SYSTEM_PROMPT_BASE = """You are a CATALYST HUNTER for the Aripäev/SEB Investment Game (Estonia). Game ends 19 June 2026. Goal: highest absolute return by finding stocks with explosive near-term catalysts.

Today: TODAY_DATE. This is a competition with N_PARTICIPANTS participants. Only #1 wins — median returns = losing. INTELLIGENT AGGRESSION is required: concentration is correct, diversification loses competitions. Find the 5 best catalyst setups, not 10 mediocre ones.

You are a SECOND OPINION to a separate Momentum Strategist who sees trend/Sharpe signals. Your value is finding catalyst-driven opportunities — vol_ratio breakouts, short squeezes, premarket gap-ups, IV spikes — that a pure Sharpe ranker might miss. Mirroring a generic momentum portfolio is failure.

## Your mandate — find explosive setups
- Vol_ratio breakouts: vol_ratio > 1.5 = high-volume confirmation. RSI > 75 + vol_ratio > 1.5 = parabolic breakout in progress. CONFIRM these, do not avoid them.
- Short squeeze candidates: short_interest > 15% + positive momentum + vol_ratio > 1.5 = prime squeeze setup.
- Premarket gap-ups: positive premarket_gap = opening momentum confirmation — early movers beat the crowd.
- IV spike + momentum: iv_proxy spike = event-driven expectation — combine with RSI > 60 for confirmation.
- ATR%: high ATR% = volatile, active mover. Combine with positive RSI and vol_ratio for sizing decisions.
- Dividend yield edge: Baltic/Nordic stocks with 3-6% yield earn free return via auto-reinvestment. Factor into close-call decisions.

## Game rules
- 5 to 20 stocks. No duplicates.
- Markets: US S&P 500, OMX Helsinki, OMX Stockholm, OBX Norway, OMX Copenhagen, Baltic.
- Regime-based position count: REGIME_GUIDANCE

## Signal guidance
- RSI > 75 with vol_ratio > 1.5 = confirmed breakout (bullish). RSI > 82 AND pct_from_52w_high ≥ -2% AND vol_ratio < 1.8 = exhaustion risk, not a fresh breakout — lower conviction (score ≤ 5).
- vol_ratio > 1.5: move confirmed by volume — strong buy signal. vol_ratio > 1.8 overrides the exhaustion warning.
- pct_from_52w_high is ALWAYS <= 0%. 0.0% = AT 52-week high. Bullish only when vol_ratio confirms. Without volume, at-peak = no pullback cushion.
- ShortInt = short % of float when available.
- PreMktGap = gap vs prior close. Positive = opening momentum.
- IV = implied vol from options (US) or 20d annualized realized vol (non-US fallback), shown when available.

## Baltic market guidance
Baltic stocks are underrepresented in competitor portfolios — genuine edge:
- Most liquid: LHV1T.TL (banking), TAL1T.TL (tech/growth)
- Dividend edge: 3-6% yields — game auto-reinvests, generating free return

## Sizing — MANDATORY
Output `conviction` (integer 1–10), NOT a weight. Python converts conviction to position size.
- 10 = max conviction (explosive catalyst confirmed by high volume + momentum)
- 8–9 = high conviction (strong breakout setup, confirmed vol_ratio > 1.5)
- 5–7 = medium conviction (good signals but not perfect setup)
- 1–4 = speculative / weak setup
Every position must have a DIFFERENT conviction score.

## What to AVOID
- Do NOT fill the portfolio with US mega-cap names just because they are large.
- Non-US picks are optional alpha sources — include them only when their setup is stronger than available US alternatives.
- Do NOT simply choose the top Sharpe-ranked names — Sharpe is already covered by the Strategist.
- Do NOT avoid high-RSI stocks — they are the momentum leaders.

## Output — valid JSON only, no other text
{"positions":[{"ticker":"X","conviction":9,"rationale":"why this catalyst pick at this conviction score"}],"reasoning":"2-3 sentence catalyst thesis","confidence":0.80,"learning_reflection":"One sentence: how today's picks adapt based on recent learning context."}"""


class GeminiChallenger(BaseAgent):
    MAX_RETRIES = 3
    MAX_CANDIDATES = 200  # allow full candidate table when user prefers completeness
    MODEL = "gemini-2.5-flash"

    def __init__(self) -> None:
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        or_key = os.environ.get("OPENROUTER_API_KEY", "")
        self._openrouter_fallback = OpenAI(
            api_key=or_key,
            base_url=config.OPENROUTER_BASE_URL,
        ) if or_key else None
        self._openrouter_fallback_available = self._openrouter_fallback is not None
        self.model = config.OPENROUTER_CHALLENGER_MODEL if self._openrouter_fallback_available else self.MODEL
        self._openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def propose(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        regime = snapshot.get("regime", "NEUTRAL")
        learning_context = snapshot.get("learning_context", "")
        n_participants = snapshot.get("n_participants", 844)
        user_message = self._build_user_message(snapshot, prior_proposal)

        # Primary: OpenRouter challenger model
        try:
            proposal = self._call_openrouter_primary(user_message, regime, learning_context, n_participants)
            if proposal.positions:
                logger.info(
                    "Challenger produced %d positions (confidence %.0f%%, model: %s)",
                    len(proposal.positions),
                    proposal.confidence * 100,
                    self.model,
                )
                return proposal
            logger.warning("OpenRouter challenger returned empty proposal — checking for salvageable output")
        except Exception as exc:
            # Check for truncation and try to salvage output
            msg = str(exc)
            if "truncated" in msg or "max_tokens" in msg:
                logger.warning("OpenRouter challenger hit max_tokens/truncation: attempting to repair with Gemini")
                raw = getattr(exc, 'response', None)
                if raw:
                    try:
                        # Use Gemini to repair/complete the JSON
                        gemini_prompt = f"Fix or complete this truncated JSON for a portfolio proposal. Return only valid JSON.\n\n{raw}"
                        gemini_response = self.client.generate_content(
                            model=self.MODEL,
                            contents=[{"role": "user", "parts": [gemini_prompt]}],
                            generation_config=types.GenerationConfig(temperature=0.1, max_output_tokens=1024),
                        )
                        fixed_json = gemini_response.candidates[0].content.parts[0].text
                        data = _extract_json(fixed_json)
                        positions = _sanitize_positions(data.get("positions", []))
                        if positions:
                            proposal = PortfolioProposal(
                                positions=[Position(**p) for p in positions],
                                confidence=data.get("confidence", 0.5),
                                reasoning=data.get("reasoning", "[truncated output repaired by Gemini]"),
                                learning_reflection=data.get("learning_reflection", "[truncated output repaired by Gemini]"),
                            )
                            logger.warning("Challenger used Gemini to repair truncated OpenRouter output: %d positions (model: %s)", len(positions), self.model)
                            return proposal
                    except Exception as repair_exc:
                        logger.warning("Gemini repair of truncated OpenRouter output failed: %s", repair_exc)
            logger.warning("Challenger OpenRouter failed: %s", exc)

        # First fallback: Gemini
        logger.info("OpenRouter challenger unavailable — falling back to Gemini (%s)", self.MODEL)
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                proposal = self._call_gemini(user_message, regime, learning_context, n_participants)
                logger.info(
                    "Challenger produced %d positions (confidence %.0f%%, route: Gemini:%s)",
                    len(proposal.positions),
                    proposal.confidence * 100,
                    self.MODEL,
                )
                return proposal
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning("Challenger Gemini fallback attempt %d/%d failed: %s", attempt, self.MAX_RETRIES, exc)
            except Exception as exc:
                logger.warning("Challenger Gemini fallback attempt %d/%d API error: %s", attempt, self.MAX_RETRIES, exc)

        # Final fallback: OpenAI nano
        logger.info("Gemini fallback unavailable — final fallback to OpenAI (%s)", config.OPENAI_FALLBACK_MODEL)
        return self._call_openai_fallback(user_message, regime, learning_context, n_participants)

        return PortfolioProposal()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_user_message(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> str:
        regime = snapshot.get("regime", "NEUTRAL")
        vix = snapshot.get("vix_level", float("nan"))
        spx_vs = snapshot.get("spx_vs_sma", 0.0)
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
        catalyst_ranked: list[dict] = []
        for item in ranked_source:
            if not isinstance(item, dict):
                continue
            ticker = item.get("ticker")
            if isinstance(ticker, str) and ticker in candidate_map:
                catalyst_ranked.append(candidate_map[ticker])
        if not catalyst_ranked:
            catalyst_ranked = snapshot.get("candidates", [])

        preprocessed_rows: list[dict] = []
        for c in catalyst_ranked:
            ticker = c["ticker"]
            si = short_interest.get(ticker)
            pm = premarket_gap.get(ticker)
            iv = iv_proxy.get(ticker)
            preprocessed_rows.append(
                {
                    "candidate": c,
                    "short_interest": si,
                    "premarket_gap": pm,
                    "iv_proxy": iv,
                    "cat_score": self._catalyst_score(c, si, pm, iv),
                }
            )
        # Optional truncation guard: only apply if MAX_CANDIDATES is set below full universe.
        if self.MAX_CANDIDATES and len(preprocessed_rows) > self.MAX_CANDIDATES:
            logger.info(
                "Challenger truncating catalyst table: %d → %d rows",
                len(preprocessed_rows),
                self.MAX_CANDIDATES,
            )
            preprocessed_rows = preprocessed_rows[: self.MAX_CANDIDATES]

        show_short_interest = any(row["short_interest"] is not None for row in preprocessed_rows)
        show_premarket_gap = any(row["premarket_gap"] is not None for row in preprocessed_rows)
        show_iv = any(row["iv_proxy"] is not None for row in preprocessed_rows)

        header_parts = [
            f"{'Ticker':<12}",
            f"{'Market':<12}",
            f"{'Sector':<7}",
            f"{'5d(σ)':>6}",
            f"{'RSI':>6}",
            f"{'vIdx(σ)':>8}",
            f"{'52wH%':>7}",
            f"{'VR(σ)':>6}",
        ]
        if show_short_interest:
            header_parts.append(f"{'ShortInt':>9}")
        if show_premarket_gap:
            header_parts.append(f"{'PreMktGap':>10}")
        if show_iv:
            header_parts.append(f"{'IV':>7}")
        header_parts += [
            f"{'ATR%':>6}",
            f"{'DivYld':>7}",
            f"{'CatScore':>9}",
            f"{'Price':>10}",
        ]
        header = " ".join(header_parts)

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
            f"Regime: {regime} | SPX vs 50d SMA: {spx_vs:.1%} | VIX: {vix_str}",
            f"Composite regime score: {rscore}/100 — {score_label}",
        ]
        portfolio_state_context = snapshot.get("portfolio_state_context", "")
        if portfolio_state_context:
            lines += ["", portfolio_state_context]
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
            "Top candidates (sorted by catalyst score) — CATALYST signals only:",
            "ShortInt/PreMktGap/IV columns are shown only when available in today's data.",
            "PreMktGap = gap vs prior close (EU=morning gap, US=after-hours).",
            "IV = implied vol from options (US) or 20d annualized realized vol (non-US fallback), when available.",
            "CatScore = internal catalyst ranking. Use this as your primary ordering.",
            "",
            header,
            "-" * len(header),
        ]

        def fmt(v: float, fmt_str: str = ".1%") -> str:
            return "N/A" if (v is None or (isinstance(v, float) and math.isnan(v))) else format(v, fmt_str)

        def fmt_opt(v: "float | None", fmt_str: str = ".1%") -> str:
            return "" if v is None else format(v, fmt_str)

        def fmtz(v: float) -> str:
            return "N/A" if math.isnan(v) else f"{v:+.1f}σ"

        for row in preprocessed_rows:
            c = row["candidate"]
            safe_ticker = sanitize_ticker(c["ticker"])
            values = [
                f"{safe_ticker:<12}",
                f"{c['market']:<12}",
                f"{c.get('sector', '?'):<7}",
                f"{fmtz(c.get('z_mom_5d', float('nan'))):>6}",
                f"{fmt(c['rsi_14'], '.1f'):>6}",
                f"{fmtz(c.get('z_vs_index', float('nan'))):>8}",
                f"{fmt(c['pct_from_52w_high']):>7}",
                f"{fmtz(c.get('z_vol_ratio', float('nan'))):>6}",
            ]
            if show_short_interest:
                values.append(f"{fmt_opt(row['short_interest'], '.1%'):>9}")
            if show_premarket_gap:
                values.append(f"{fmt_opt(row['premarket_gap'], '+.1%'):>10}")
            if show_iv:
                values.append(f"{fmt_opt(row['iv_proxy'], '.2f'):>7}")
            values += [
                f"{fmt(c.get('atr_pct', float('nan'))):>6}",
                f"{fmt(c.get('dividend_yield', float('nan'))):>7}",
                f"{row['cat_score']:>9.2f}",
                f"{c['last_price']:>10.2f}",
            ]
            lines.append(" ".join(values))

        if prior_proposal and prior_proposal.positions:
            lines += ["", "Yesterday's holdings (for continuity reference):"]
            for pos in prior_proposal.positions:
                lines.append(f"  {sanitize_ticker(pos.ticker):<12} {pos.weight:.1%}")

        if snapshot.get("earnings_warning"):
            lines += ["", snapshot["earnings_warning"]]

        if snapshot.get("news_headlines"):
            lines += ["", snapshot["news_headlines"]]

        lines += ["", "Build your catalyst-driven portfolio. Return valid JSON only."]
        message = "\n".join(lines)
        logger.info(
            "Challenger prompt size: %d chars, %d candidates",
            len(message),
            len(preprocessed_rows),
        )
        return message

    @staticmethod
    def _catalyst_score(
        candidate: dict,
        short_interest: Optional[float],
        premarket_gap: Optional[float],
        iv_proxy: Optional[float],
    ) -> float:
        score = 0.0

        mom_5d = candidate.get("mom_5d", float("nan"))
        if not math.isnan(mom_5d):
            score += max(-1.0, min(2.0, mom_5d * 15.0))

        vs_index = candidate.get("vs_index", float("nan"))
        if not math.isnan(vs_index):
            score += max(-1.0, min(2.0, vs_index * 12.0))

        vol_ratio = candidate.get("vol_ratio", float("nan"))
        if not math.isnan(vol_ratio):
            score += max(-1.0, min(2.5, (vol_ratio - 1.0) * 2.5))

        rsi = candidate.get("rsi_14", float("nan"))
        if not math.isnan(rsi):
            score += 1.0 if rsi >= 75 else (0.5 if rsi >= 60 else 0.0)

        if short_interest is not None:
            score += max(0.0, min(2.0, short_interest * 8.0))

        if premarket_gap is not None:
            score += max(-0.5, min(2.0, premarket_gap * 25.0))

        if iv_proxy is not None:
            score += max(0.0, min(1.0, (iv_proxy - 0.35) * 2.0))

        return score

    def _call_openai_fallback(
        self,
        user_message: str,
        regime: str = "NEUTRAL",
        learning_context: str = "",
        n_participants: int = 844,
    ) -> PortfolioProposal:
        """OpenAI fallback when Gemini is unavailable."""
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = (
            _SYSTEM_PROMPT_BASE
            .replace("TODAY_DATE", date.today().isoformat())
            .replace("N_PARTICIPANTS", str(n_participants))
            .replace("REGIME_GUIDANCE", regime_guidance)
        )
        if learning_context:
            system_prompt += (
                "\n\n## ═══ LIVE LEARNING CONSTRAINTS — HIGHEST PRIORITY ═══\n"
                "These rules are derived from verified game performance and OVERRIDE any base instruction above.\n"
                + learning_context
            )

        for attempt in range(1, 3):
            try:
                response = self._openai.chat.completions.create(
                    model=config.OPENAI_FALLBACK_MODEL,
                    response_format={"type": "json_object"},
                    temperature=0.4,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                )
                usage = response.usage
                cost = log_usage(
                    agent_name="Challenger-OAIFallback",
                    model=config.OPENAI_FALLBACK_MODEL,
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                )
                logger.info(
                    "OpenAI fallback tokens — in: %d, out: %d (cost: $%.5f)",
                    usage.prompt_tokens, usage.completion_tokens, cost,
                )
                data = json.loads(response.choices[0].message.content)
                raw_positions = data.get("positions", [])
                positions = []
                for p in raw_positions:
                    raw_conv = p.get("conviction") or p.get("weight")
                    if isinstance(raw_conv, float) and 0.0 < raw_conv <= 1.0:
                        conviction = max(1, min(10, round(raw_conv * 40)))
                    elif raw_conv is not None:
                        conviction = max(1, min(10, int(raw_conv)))
                    else:
                        conviction = 5
                    positions.append(Position(ticker=p["ticker"], weight=conviction_to_weight(conviction), rationale=p.get("rationale", ""), conviction=conviction))
                logger.info("OpenAI fallback produced %d positions", len(positions))
                return PortfolioProposal(
                    positions=positions,
                    reasoning=data.get("reasoning", ""),
                    confidence=float(data.get("confidence", 0.5)),
                    learning_reflection=data.get("learning_reflection", ""),
                )
            except Exception as exc:
                logger.warning("OpenAI fallback attempt %d/2 failed: %s", attempt, exc)

        logger.warning("OpenAI fallback also failed — returning empty proposal")
        return PortfolioProposal()

    def _call_openrouter_primary(
        self,
        user_message: str,
        regime: str = "NEUTRAL",
        learning_context: str = "",
        n_participants: int = 844,
    ) -> PortfolioProposal:
        """OpenRouter primary challenger model (NVIDIA Nemotron)."""
        if self._openrouter_fallback is None or not self._openrouter_fallback_available:
            logger.warning("OpenRouter challenger unavailable (missing OPENROUTER_API_KEY)")
            return PortfolioProposal()

        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = (
            _SYSTEM_PROMPT_BASE
            .replace("TODAY_DATE", date.today().isoformat())
            .replace("N_PARTICIPANTS", str(n_participants))
            .replace("REGIME_GUIDANCE", regime_guidance)
        )
        if learning_context:
            system_prompt += (
                "\n\n## ═══ LIVE LEARNING CONSTRAINTS — HIGHEST PRIORITY ═══\n"
                "These rules are derived from verified game performance and OVERRIDE any base instruction above.\n"
                + learning_context
            )
        system_prompt += (
            "\n\nCRITICAL OUTPUT FORMAT: Return exactly one valid JSON object and nothing else. "
            "No markdown, no code fences, no prose before or after JSON. "
            "Required top-level keys: positions, reasoning, confidence, learning_reflection. "
            "For each position include a one-sentence RISK/EXIT trigger. "
            "After the positions, add a 1–2 sentence cross-check vs current sector rotation (which sectors to overweight/avoid today)."
        )

        effective_user_message = (
            "Return valid JSON only. No markdown, no commentary, no code fences.\n\n"
            + user_message
        )

        _PROPOSAL_SCHEMA = {
            "type": "json_schema",
            "json_schema": {
                "name": "portfolio_proposal",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "positions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "ticker": {"type": "string"},
                                    "conviction": {"type": "integer"},
                                    "rationale": {"type": "string"},
                                },
                                "required": ["ticker", "conviction", "rationale"],
                                "additionalProperties": False,
                            },
                        },
                        "reasoning": {"type": "string"},
                        "confidence": {"type": "number"},
                        "learning_reflection": {"type": "string"},
                    },
                    "required": ["positions", "reasoning", "confidence", "learning_reflection"],
                    "additionalProperties": False,
                },
            },
        }

        for attempt in range(1, 2):  # Single attempt only — truncation = fail fast to fallback
            try:
                max_tokens_limit = 30000  # maximized per user request
                request_kwargs = {
                    "model": config.OPENROUTER_CHALLENGER_MODEL,
                    "temperature": 0.45,  # slightly higher to avoid terse outputs
                    # Allow long OR runs; orchestrator timeout raised separately.
                    "timeout": max(config.API_TIMEOUT_SECONDS, 220),
                    "max_tokens": max_tokens_limit,
                    "response_format": _PROPOSAL_SCHEMA,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": effective_user_message},
                    ],
                }

                response = self._openrouter_fallback.chat.completions.create(**request_kwargs)
                usage = response.usage
                prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
                completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
                cost = log_usage(
                    agent_name="Challenger-ORPrimary",
                    model=config.OPENROUTER_CHALLENGER_MODEL,
                    input_tokens=prompt_tokens,
                    output_tokens=completion_tokens,
                )
                logger.info(
                    "OpenRouter challenger tokens — in: %d, out: %d (cost: $%.5f)",
                    prompt_tokens,
                    completion_tokens,
                    cost,
                )

                raw_text = response.choices[0].message.content or ""
                truncated = completion_tokens >= max_tokens_limit
                try:
                    data = _extract_json(raw_text)
                except ValueError:
                    logger.warning(
                        "OpenRouter challenger returned non-JSON output%s — attempting JSON repair pass",
                        " (truncated at max_tokens)" if truncated else "",
                    )
                    data = self._repair_openrouter_json(raw_text)
                    if data is None:
                        data = self._repair_with_openai_gpt54(raw_text)
                    if data is None and truncated:
                        # last-resort repair: ask gpt-5.4 to summarize into compact JSON (<=6 positions)
                        data = self._repair_with_openai_gpt54(
                            raw_text + "\n\nReturn ONLY JSON with keys positions, reasoning, confidence, learning_reflection. Max 6 positions."
                        )
                    if data is None:
                        raise ValueError("Model response could not be repaired")
                # Nemotron occasionally wraps the response in a JSON array
                if isinstance(data, list):
                    if data and isinstance(data[0], dict) and "positions" in data[0]:
                        data = data[0]
                    else:
                        data = {"positions": data, "reasoning": "", "confidence": 0.5, "learning_reflection": ""}
                raw_positions = _sanitize_positions(data.get("positions", []))
                positions = []
                for p in raw_positions:
                    raw_conv = p.get("conviction") or p.get("weight")
                    if isinstance(raw_conv, float) and 0.0 < raw_conv <= 1.0:
                        conviction = max(1, min(10, round(raw_conv * 40)))
                    elif raw_conv is not None:
                        conviction = max(1, min(10, int(raw_conv)))
                    else:
                        conviction = 5
                    positions.append(Position(ticker=p["ticker"], weight=conviction_to_weight(conviction), rationale=p.get("rationale", ""), conviction=conviction))
                return PortfolioProposal(
                    positions=positions,
                    reasoning=data.get("reasoning", ""),
                    confidence=float(data.get("confidence", 0.5)),
                    learning_reflection=data.get("learning_reflection", ""),
                )
            except Exception as exc:
                logger.warning("OpenRouter challenger failed: %s", exc)
                msg = str(exc)
                if "No endpoints found" in msg or "404" in msg:
                    logger.warning(
                        "OpenRouter model '%s' unavailable for this account/run with current request shape — disabling OpenRouter fallback until restart",
                        config.OPENROUTER_CHALLENGER_MODEL,
                    )
                    self._openrouter_fallback_available = False
                    break

        logger.warning("OpenRouter challenger failed — returning empty proposal")
        return PortfolioProposal()

    def _repair_openrouter_json(self, raw_text: str) -> Optional[dict]:
        """Best-effort conversion of non-JSON OpenRouter output into required schema."""
        if not raw_text.strip():
            return None
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "Convert the provided text to valid JSON with this exact schema keys: "
                    "positions (array of {ticker, conviction (int 1-10), rationale}), reasoning, confidence, learning_reflection. "
                    "Return JSON only."
                ),
            },
            {"role": "user", "content": raw_text[:12000]},
        ]
        try:
            repair_response = self._openai.chat.completions.create(
                model=config.OPENAI_FALLBACK_MODEL,
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout=config.API_TIMEOUT_SECONDS,
                messages=prompt_messages,
            )
            repaired = repair_response.choices[0].message.content or ""
            return _extract_json(repaired)
        except Exception as exc:
            logger.warning("OpenAI JSON repair failed: %s", exc)
            return None

    def _repair_with_openai_gpt54(self, raw_text: str) -> Optional[dict]:
        """Stronger repair using gpt-5.4 when nano fails."""
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
            repair_response = self._openai.chat.completions.create(
                model="gpt-5.4",
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout=config.API_TIMEOUT_SECONDS,
                messages=prompt_messages,
            )
            repaired = repair_response.choices[0].message.content or ""
            return _extract_json(repaired)
        except Exception as exc:
            logger.warning("OpenAI gpt-5.4 JSON repair failed: %s", exc)
            return None

    def _call_gemini(
        self,
        user_message: str,
        regime: str = "NEUTRAL",
        learning_context: str = "",
        n_participants: int = 844,
    ) -> PortfolioProposal:
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = (
            _SYSTEM_PROMPT_BASE
            .replace("TODAY_DATE", date.today().isoformat())
            .replace("N_PARTICIPANTS", str(n_participants))
            .replace("REGIME_GUIDANCE", regime_guidance)
        )
        if learning_context:
            system_prompt += (
                "\n\n## ═══ LIVE LEARNING CONSTRAINTS — HIGHEST PRIORITY ═══\n"
                "These rules are derived from verified game performance and OVERRIDE any base instruction above.\n"
                + learning_context
            )

        response = self.client.models.generate_content(
            model=self.MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=0.4,
            ),
        )

        raw_text = response.text.strip()

        # Strip accidental markdown fences
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        data = json.loads(raw_text)
        raw_positions = data.get("positions", [])

        positions = []
        for p in raw_positions:
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
        snapshot: MarketSnapshot,
        own_proposal: PortfolioProposal,
        peer_proposals: list[PortfolioProposal],
    ) -> dict:
        """Lightweight second-pass debate using OpenRouter, then Gemini, then OpenAI fallback."""
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
        _CROSSCHECK_SCHEMA = {
            "type": "json_schema",
            "json_schema": {
                "name": "cross_check",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "agrees": {"type": "array", "items": {"type": "string"}},
                        "disagrees": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "ticker": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["ticker", "reason"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["agrees", "disagrees"],
                    "additionalProperties": False,
                },
            },
        }
        try:
            if self._openrouter_fallback is not None and self._openrouter_fallback_available:
                resp = self._openrouter_fallback.chat.completions.create(
                    model=config.OPENROUTER_CHALLENGER_MODEL,
                    temperature=0.0,
                    max_tokens=1200,
                    response_format=_CROSSCHECK_SCHEMA,
                    messages=[
                        {"role": "system", "content": "You are a portfolio analyst. Return JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                )
                raw_text = resp.choices[0].message.content or ""
                return _extract_json(raw_text)
        except Exception as exc:
            logger.warning("OpenRouter Challenger cross_check failed (non-fatal): %s", exc)
            msg = str(exc)
            if "No endpoints found" in msg or "404" in msg:
                logger.warning(
                    "OpenRouter cross_check model '%s' unavailable — disabling OpenRouter challenger until restart",
                    config.OPENROUTER_CHALLENGER_MODEL,
                )
                self._openrouter_fallback_available = False

        try:
            response = self.client.models.generate_content(
                model=self.MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are a portfolio analyst. Return JSON only.",
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw)
        except Exception as exc2:
            logger.warning("Challenger cross_check fallback failed (non-fatal): %s", exc2)

        try:
            resp = self._openai.chat.completions.create(
                model=config.OPENAI_FALLBACK_MODEL,
                response_format={"type": "json_object"},
                temperature=0.0,
                messages=[
                    {"role": "system", "content": "You are a portfolio analyst. Return JSON only."},
                    {"role": "user", "content": prompt},
                ],
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as exc3:
            logger.warning("OpenAI cross_check fallback also failed: %s", exc3)
        return {}
