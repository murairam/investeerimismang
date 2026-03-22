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
from typing import Optional

from openai import APIConnectionError, APITimeoutError, BadRequestError, OpenAI

import config
from data.cost_tracker import log_usage
from data.fetcher import MarketSnapshot, sanitize_ticker
from portfolio.models import PortfolioProposal

logger = logging.getLogger(__name__)

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

        top_tickers = sorted(seen, key=lambda t: -seen[t])[:12]
        if not top_tickers:
            return {}

        user_message = self._build_message(top_tickers, snapshot)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = self._call_openai(user_message)
                logger.info(
                    "Devil's advocate challenged %d picks: %d HIGH, %d MEDIUM, %d LOW risk",
                    len(result),
                    sum(1 for v in result.values() if v["risk"] == "HIGH"),
                    sum(1 for v in result.values() if v["risk"] == "MEDIUM"),
                    sum(1 for v in result.values() if v["risk"] == "LOW"),
                )
                return result
            except Exception as exc:
                logger.warning("Devil's advocate attempt %d/%d failed: %s", attempt, self.MAX_RETRIES, exc)

        logger.info("Devil's advocate unavailable — Risk Manager will proceed without bear cases")
        return {}

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
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                temperature=0.1,
                timeout=config.API_TIMEOUT_SECONDS,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
        except (BadRequestError, APIConnectionError, APITimeoutError) as exc:
            if self._openrouter_enabled and self.model != self.MODEL:
                logger.warning("OpenRouter Devil request failed (%s). Falling back to OpenAI.", exc)
                self._switch_to_openai_fallback()
                response = self.client.chat.completions.create(
                    model=self.model,
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    timeout=config.API_TIMEOUT_SECONDS,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                )
            else:
                raise

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

        data = json.loads(response.choices[0].message.content)
        bears = data.get("bears", data) if isinstance(data, dict) else data
        return {
            item["ticker"]: {
                "bear_case": item.get("bear_case", ""),
                "risk": item.get("risk", "MEDIUM").upper(),
            }
            for item in (bears if isinstance(bears, list) else [])
            if "ticker" in item
        }
