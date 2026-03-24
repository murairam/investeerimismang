#!/usr/bin/env python3
"""
Model connectivity smoke test for AlphaShark.

Purpose:
- Validate that configured model routes are reachable without running full main.py.
- Catch provider/model config issues early (OpenRouter routing, key problems, model typos).

Usage:
    python scripts/check_models.py
    python scripts/check_models.py --json
    python scripts/check_models.py --allow-fail
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from typing import Callable

from google import genai
from google.genai import types
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


@dataclass
class CheckResult:
    name: str
    provider: str
    model: str
    status: str  # PASS | FAIL | SKIP
    latency_ms: int
    detail: str


def _now_ms() -> int:
    return int(time.perf_counter() * 1000)


def _check_openai_model(client: OpenAI, model: str, name: str) -> CheckResult:
    start = _now_ms()
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=24,
            messages=[
                {"role": "system", "content": "Return short valid JSON only."},
                {"role": "user", "content": "Return {'ok': true} as JSON."},
            ],
        )
        latency = _now_ms() - start
        text = (response.choices[0].message.content or "").strip()
        if not text:
            return CheckResult(name, "openai", model, "FAIL", latency, "Empty response")
        return CheckResult(name, "openai", model, "PASS", latency, "OK")
    except Exception as exc:
        latency = _now_ms() - start
        return CheckResult(name, "openai", model, "FAIL", latency, str(exc))


def _check_openrouter_model(client: OpenAI, model: str, name: str) -> CheckResult:
    start = _now_ms()
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            timeout=min(config.API_TIMEOUT_SECONDS, 30),
            max_tokens=24,
            messages=[
                {"role": "system", "content": "Return short valid JSON only."},
                {"role": "user", "content": "Return {'ok': true} as JSON."},
            ],
        )
        latency = _now_ms() - start
        text = (response.choices[0].message.content or "").strip()
        if not text:
            return CheckResult(name, "openrouter", model, "FAIL", latency, "Empty response")
        return CheckResult(name, "openrouter", model, "PASS", latency, "OK")
    except Exception as exc:
        latency = _now_ms() - start
        return CheckResult(name, "openrouter", model, "FAIL", latency, str(exc))


def _check_gemini_model(client: genai.Client, model: str, name: str) -> CheckResult:
    start = _now_ms()
    try:
        response = client.models.generate_content(
            model=model,
            contents="Return {'ok': true} as JSON only.",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
                max_output_tokens=24,
            ),
        )
        latency = _now_ms() - start
        text = (response.text or "").strip()
        if not text:
            return CheckResult(name, "gemini", model, "FAIL", latency, "Empty response")
        return CheckResult(name, "gemini", model, "PASS", latency, "OK")
    except Exception as exc:
        latency = _now_ms() - start
        return CheckResult(name, "gemini", model, "FAIL", latency, str(exc))


def _print_table(results: list[CheckResult]) -> None:
    print("\nModel Smoke Check")
    print("=" * 96)
    print(f"{'Status':<6}  {'Name':<28}  {'Provider':<10}  {'Model':<38}  {'Latency':>7}")
    print("-" * 96)
    for result in results:
        latency = f"{result.latency_ms}ms" if result.latency_ms > 0 else "-"
        print(
            f"{result.status:<6}  {result.name:<28}  {result.provider:<10}  {result.model:<38}  {latency:>7}"
        )
    print("=" * 96)

    failed = [result for result in results if result.status == "FAIL"]
    skipped = [result for result in results if result.status == "SKIP"]
    if failed:
        print("\nFailures:")
        for result in failed:
            print(f"- {result.name} ({result.model}): {result.detail}")
    if skipped:
        print("\nSkipped:")
        for result in skipped:
            print(f"- {result.name}: {result.detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test model routes without running full pipeline")
    parser.add_argument("--json", action="store_true", help="Print JSON results")
    parser.add_argument(
        "--allow-fail",
        action="store_true",
        help="Always exit 0 even if checks fail",
    )
    args = parser.parse_args()

    results: list[CheckResult] = []

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")

    if openai_key:
        openai_client = OpenAI(api_key=openai_key)
        results.append(_check_openai_model(openai_client, "gpt-5.4", "strategist/risk-manager"))
        results.append(_check_openai_model(openai_client, config.OPENAI_FALLBACK_MODEL, "openai-fallback"))
    else:
        results.append(
            CheckResult(
                "strategist/risk-manager",
                "openai",
                "gpt-5.4",
                "SKIP",
                0,
                "OPENAI_API_KEY missing",
            )
        )
        results.append(
            CheckResult(
                "openai-fallback",
                "openai",
                config.OPENAI_FALLBACK_MODEL,
                "SKIP",
                0,
                "OPENAI_API_KEY missing",
            )
        )

    if config.USE_OPENROUTER_FOR_SECONDARY_AGENTS and openrouter_key:
        openrouter_client = OpenAI(api_key=openrouter_key, base_url=config.OPENROUTER_BASE_URL)
        results.append(
            _check_openrouter_model(
                openrouter_client,
                config.OPENROUTER_CHALLENGER_MODEL,
                "challenger-primary",
            )
        )
        results.append(
            _check_openrouter_model(
                openrouter_client,
                config.OPENROUTER_ANALYST_MODEL,
                "full-analyst-primary",
            )
        )
        results.append(
            _check_openrouter_model(
                openrouter_client,
                config.OPENROUTER_DEVIL_MODEL,
                "devil-primary",
            )
        )
    else:
        reason = "OPENROUTER_API_KEY missing" if not openrouter_key else "OpenRouter disabled in config"
        results.append(
            CheckResult(
                "challenger-primary",
                "openrouter",
                config.OPENROUTER_CHALLENGER_MODEL,
                "SKIP",
                0,
                reason,
            )
        )
        results.append(
            CheckResult(
                "full-analyst-primary",
                "openrouter",
                config.OPENROUTER_ANALYST_MODEL,
                "SKIP",
                0,
                reason,
            )
        )
        results.append(
            CheckResult(
                "devil-primary",
                "openrouter",
                config.OPENROUTER_DEVIL_MODEL,
                "SKIP",
                0,
                reason,
            )
        )

    if gemini_key:
        gemini_client = genai.Client(api_key=gemini_key)
        results.append(_check_gemini_model(gemini_client, "gemini-2.5-flash", "challenger-fallback"))
    else:
        results.append(
            CheckResult(
                "challenger-fallback",
                "gemini",
                "gemini-2.5-flash",
                "SKIP",
                0,
                "GEMINI_API_KEY missing",
            )
        )

    if args.json:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        _print_table(results)

    has_failures = any(result.status == "FAIL" for result in results)
    return 0 if (args.allow_fail or not has_failures) else 1


if __name__ == "__main__":
    raise SystemExit(main())
