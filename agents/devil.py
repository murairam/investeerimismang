"""
OpenAIDevil — Devil's Advocate pressure-tester (GPT-5.4-nano).

Receives the merged strategist + challenger proposals and argues AGAINST
each top pick. Forces the Risk Manager to confront the bear case before
committing to a weight. All-OpenAI: no Gemini dependency.
"""
import json
import logging
import math
import os
import re
from typing import Optional

import openai
from openai import APIConnectionError, APITimeoutError, BadRequestError, OpenAI

import config
from data.cost_tracker import log_usage
from data.fetcher import MarketSnapshot, sanitize_ticker
from portfolio.models import PortfolioProposal

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict:
    """Parse JSON from model output, tolerating prose prefix/suffix and truncation.

    Also strips Qwen3 <think>...</think> blocks which appear before the JSON answer.
    """
    text = text.strip()
    # Strip thinking blocks emitted by Qwen3 even when /no_think is sent
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
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


_SYSTEM_PROMPT = """You are a BEAR-CASE analyst and dead-money detector. Your ONLY job is to find reasons why each stock pick might FAIL or UNDERPERFORM.

You are NOT building a portfolio. You are stress-testing someone else's picks.

For each ticker provided, give:
1. The single strongest bear case (1-2 sentences max)
2. A risk level: HIGH, MEDIUM, or LOW

**Dead-money rule**: Only call a stock dead money if vol_ratio < 0.8, flat momentum (|mom_5d| < 1%), and beta < 0.5. If vol_ratio is above 1.0, do NOT describe it as low volume or dead money.

Be specific — cite the actual signal data (momentum, RSI, vol_ratio, beta, pct_from_52w_high) to justify your bear case.
Never write contradictory text like "vol_ratio 2.1 is low". If a metric is not bearish, do not force it into the bear case.

**Signal direction guide — read carefully:**
- pct_from_52w_high is ALWAYS ≤ 0%. It measures how far BELOW the 52-week high the stock is.
  - 0.0% = AT the 52-week high (bullish breakout, NOT a bear signal by itself)
  - -10% = 10% below the high
  - -50% = deeply below the high (bearish)
  A stock CANNOT be "above its 52-week high" by this metric. Do NOT write that.
- RSI > 75 alone is not a HIGH risk — it signals momentum. Only flag RSI if combined with vol_ratio < 0.8 (move not confirmed) or mom_5d turning negative.
- mom_5d: positive = accelerating, negative = losing steam. Use it.
- If vol_ratio is N/A or unavailable, do NOT claim low/weak volume and do NOT use volume-confirmation arguments. In that case, base risk on RSI, momentum, beta, and distance from 52-week high.

Examples of good bear cases:
- "RSI 78 but vol_ratio 0.6 — breakout not confirmed by volume; likely fading."
- "Beta 1.8 in NEUTRAL regime — high downside sensitivity. Mom_60d -4% shows longer trend weakness."
- "pct_from_52w_high -45% — deep in correction, no recovery catalyst visible."
- "Vol_ratio 0.5, mom_5d +0.2%, beta 0.3 — dead money. Holding costs rank."

Bad bear cases (too vague or factually wrong):
- "Stock is above its 52-week high" — impossible, check signal direction guide above
- "Market conditions could change" — not specific enough
- Calling RSI > 75 HIGH risk when vol_ratio is also > 1.5 — that's a breakout, not a risk

Output ONLY valid JSON, no other text:
{"bears": [{"ticker": "X", "bear_case": "...", "risk": "HIGH|MEDIUM|LOW"}, ...]}"""


class OpenAIDevil:
    MODEL = "gpt-5.4-nano"
    MAX_RETRIES = 2
    OPENROUTER_MAX_TICKERS = 15   # expanded from 10 to cover mid-ranked positions
    OPENAI_MAX_TICKERS = 20       # expanded from 12 for full top-20 coverage
    OPENROUTER_MAX_TOKENS = 3500  # increased from 2600 to handle larger candidate set

    def __init__(self) -> None:
        self._openrouter_enabled = config.USE_OPENROUTER_FOR_SECONDARY_AGENTS and bool(os.environ.get("OPENROUTER_API_KEY"))
        if self._openrouter_enabled:
            self.client = OpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url=config.OPENROUTER_BASE_URL,
            )
            self.model = config.OPENROUTER_DEVIL_MODEL
        else:
            self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            self.model = self.MODEL

    def _switch_to_openai_fallback(self) -> None:
        if self.model == self.MODEL:
            return
        logger.warning(
            "Switching Devil from OpenRouter model '%s' to OpenAI fallback '%s'",
            self.model,
            self.MODEL,
        )
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = self.MODEL

    def challenge(
        self,
        strategist: PortfolioProposal,
        challenger: PortfolioProposal,
        snapshot: MarketSnapshot,
    ) -> dict[str, dict]:
        """
        Returns {ticker: {"bear_case": str, "risk": "HIGH|MEDIUM|LOW"}}
        for the union of top picks from both proposals.
        Returns empty dict on failure (non-fatal).
        """
        # Collect unique tickers from both proposals, ranked by combined weight
        seen: dict[str, float] = {}
        for p in strategist.positions:
            seen[p.ticker] = seen.get(p.ticker, 0.0) + p.weight
        for p in (challenger.positions or []):
            seen[p.ticker] = seen.get(p.ticker, 0.0) + p.weight

        max_tickers = self.OPENROUTER_MAX_TICKERS if (self._openrouter_enabled and self.model != self.MODEL) else self.OPENAI_MAX_TICKERS
        top_tickers = sorted(seen, key=lambda t: -seen[t])[:max_tickers]
        if not top_tickers:
            return {}

        user_message = self._build_message(top_tickers, snapshot)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = self._call_openai(user_message)
                result = self._postprocess_bear_cases(result, snapshot)
                logger.info(
                    "Devil's advocate challenged %d picks: %d HIGH, %d MEDIUM, %d LOW risk (model: %s)",
                    len(result),
                    sum(1 for v in result.values() if v["risk"] == "HIGH"),
                    sum(1 for v in result.values() if v["risk"] == "MEDIUM"),
                    sum(1 for v in result.values() if v["risk"] == "LOW"),
                    self.model,
                )
                return result
            except Exception as exc:
                logger.warning("Devil's advocate attempt %d/%d failed: %s", attempt, self.MAX_RETRIES, exc)

        logger.info("Devil's advocate unavailable — Risk Manager will proceed without bear cases")
        return {}

    @staticmethod
    def _ensure_sentence(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
        cleaned = re.sub(r"([.,;:!?]){2,}", r"\1", cleaned)
        if not cleaned:
            return "Risk based on momentum and beta; volume data unavailable."
        if cleaned[-1] not in ".!?":
            cleaned += "."
        return cleaned

    def _postprocess_bear_cases(self, bears: dict[str, dict], snapshot: MarketSnapshot) -> dict[str, dict]:
        """Normalize awkward volume wording when vol_ratio is missing (N/A)."""
        signal_map = {c["ticker"]: c for c in snapshot.get("candidates", [])}
        out: dict[str, dict] = {}

        for ticker, item in bears.items():
            bear_case = item.get("bear_case", "")
            risk = item.get("risk", "MEDIUM").upper()

            signal = signal_map.get(ticker, {})
            vol_ratio = signal.get("vol_ratio", float("nan"))
            vol_missing = vol_ratio is None or (isinstance(vol_ratio, float) and math.isnan(vol_ratio))

            if vol_missing and bear_case:
                text = bear_case
                text = re.sub(r"vol[_ ]?ratio\s*(?:is|=)?\s*n/?a", "volume data unavailable", text, flags=re.IGNORECASE)
                text = re.sub(r"\(\s*volume data unavailable\s*\)", "", text, flags=re.IGNORECASE)
                text = re.sub(
                    r"\b(?:with|and|but)\s+(?:no|weak|low|strong)\s+volume(?:\s+(?:confirmation|support|signal))?\b",
                    "",
                    text,
                    flags=re.IGNORECASE,
                )
                text = re.sub(r"\b(?:no|without)\s+volume\s+(?:confirmation|support|signal)\b", "", text, flags=re.IGNORECASE)
                text = re.sub(r"\blacks?\s+volume\s+(?:confirmation|support|signal)\b", "", text, flags=re.IGNORECASE)
                text = re.sub(r"\bvolume data unavailable\b", "", text, flags=re.IGNORECASE)
                text = re.sub(r"\s*[,;:]\s*", ", ", text)
                text = re.sub(r"\s{2,}", " ", text).strip(" ,")

                sentences = re.split(r"(?<=[.!?])\s+", text)
                filtered = []
                for sentence in sentences:
                    s = sentence.strip()
                    if not s:
                        continue
                    lowered = s.lower()
                    if any(
                        phrase in lowered
                        for phrase in (
                            "no volume confirmation",
                            "weak volume",
                            "low volume",
                            "volume data unavailable",
                            "volume confirmation",
                            "volume support",
                            "volume signal",
                            "without volume support",
                        )
                    ):
                        continue
                    filtered.append(s)

                text = " ".join(filtered)
                if not text:
                    text = "Volume data unavailable; assess downside via momentum, RSI, beta, and 52-week-high distance."
                bear_case = text

            out[ticker] = {
                "bear_case": self._ensure_sentence(bear_case),
                "risk": risk,
            }

        return out

    def _build_message(self, tickers: list[str], snapshot: MarketSnapshot) -> str:
        signal_map = {c["ticker"]: c for c in snapshot["candidates"]}

        lines = [
            f"Stress-test these {len(tickers)} picks. Give the bear case for each.",
            "",
            f"{'Ticker':<12} {'20d Ret':>8} {'Sharpe':>7} {'RSI':>6} {'vs Idx':>8} "
            f"{'52wH%':>7} {'Beta':>6} {'VolR':>6} {'Mom5d':>7}",
            "-" * 75,
        ]

        def fmt(v: float, f: str = ".1%") -> str:
            return "N/A" if math.isnan(v) else format(v, f)

        for ticker in tickers:
            c = signal_map.get(ticker)
            safe_ticker = sanitize_ticker(ticker)
            if c:
                lines.append(
                    f"{safe_ticker:<12} {fmt(c['momentum']):>8} {fmt(c['sharpe_20d'], '.2f'):>7} "
                    f"{fmt(c['rsi_14'], '.1f'):>6} {fmt(c['vs_index']):>8} "
                    f"{fmt(c['pct_from_52w_high']):>7} {fmt(c['beta'], '.2f'):>6} "
                    f"{fmt(c['vol_ratio'], '.2f'):>6} {fmt(c['mom_5d']):>7}"
                )
            else:
                lines.append(f"{safe_ticker:<12} (not in today's candidate list)")

        lines += ["", "For each ticker, give the strongest reason it might FAIL. Cite the numbers. Only flag dead-money picks as HIGH risk when vol_ratio < 0.8, |mom_5d| < 1%, and beta < 0.5. Do not call vol_ratio above 1.0 low."]
        return "\n".join(lines)

    def _call_openai(self, user_message: str) -> dict[str, dict]:
        openrouter_call = self._openrouter_enabled and self.model != self.MODEL
        # Qwen3 runs in "thinking" mode by default — disable it to avoid long hangs
        effective_user_message = ("/no_think\n\n" + user_message) if openrouter_call and "qwen3" in self.model.lower() else user_message
        call_kwargs: dict = dict(
            temperature=0.1,
            timeout=config.API_TIMEOUT_SECONDS,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": effective_user_message},
            ],
        )
        if openrouter_call:
            call_kwargs["max_tokens"] = self.OPENROUTER_MAX_TOKENS
        else:
            call_kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self.client.chat.completions.create(model=self.model, **call_kwargs)
        except (BadRequestError, APIConnectionError, APITimeoutError, openai.RateLimitError, openai.InternalServerError) as exc:
            if self._openrouter_enabled and self.model != self.MODEL:
                logger.warning("OpenRouter Devil request failed (%s). Falling back to OpenAI.", exc)
                self._switch_to_openai_fallback()
                call_kwargs.pop("max_tokens", None)
                call_kwargs["response_format"] = {"type": "json_object"}
                response = self.client.chat.completions.create(model=self.model, **call_kwargs)
            else:
                raise

        if (response.choices[0].finish_reason or "").lower() == "length":
            logger.warning("Devil response truncated (finish_reason=length) — retrying with fallback model")
            if self._openrouter_enabled and self.model != self.MODEL:
                logger.warning(
                    "Switching Devil from OpenRouter '%s' to OpenAI fallback '%s' due to truncation",
                    self.model, self.MODEL,
                )
                self._switch_to_openai_fallback()
            raise RuntimeError("Devil response truncated (finish_reason=length)")

        usage = response.usage
        cost = log_usage(
            agent_name="OpenAIDevil",
            model=self.model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
        )
        logger.info(
            "Devil tokens — in: %d, out: %d (cost: $%.5f)",
            usage.prompt_tokens,
            usage.completion_tokens,
            cost,
        )

        raw_content = response.choices[0].message.content or ""
        data = _extract_json(raw_content)
        bears = data.get("bears", data) if isinstance(data, dict) else data
        return {
            item["ticker"]: {
                "bear_case": item.get("bear_case", ""),
                "risk": item.get("risk", "MEDIUM").upper(),
            }
            for item in (bears if isinstance(bears, list) else [])
            if "ticker" in item
        }
