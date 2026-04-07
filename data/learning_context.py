"""
Build prompt-ready learning context from structured learning state first,
with markdown summaries as a backward-compatible fallback.
"""
import json
import logging
import os
import re
from datetime import date

from data.learning_state import build_prompt_learning_context

logger = logging.getLogger(__name__)

_MAX_LINE_LEN = 400
# Hard cap on total context characters injected into agent system prompts (~900 tokens).
# Prevents unbounded token bloat as learning_state.json grows over the 75-day game.
_MAX_CONTEXT_CHARS = 3_500
# Lines that could hijack LLM instruction-following when re-injected as system prompt
_INJECTION_RE = re.compile(
    r"^\s*(ignore|disregard|forget|override|system\s*:|<[^>]+>|\[inst\])",
    re.IGNORECASE,
)


def _sanitize_learning_text(text: str) -> str:
    """Sanitize LLM-generated text before re-injecting it into system prompts.

    Prevents second-order prompt injection: if a past LLM run produced adversarial
    content in rationale/reasoning fields, this stops it from being re-injected
    as a trusted 'MANDATORY override' in future system prompts.
    """
    sanitized = []
    for line in text.splitlines():
        if _INJECTION_RE.match(line):
            logger.warning("Stripped potential injection line from learning context: %.60s…", line)
            continue
        sanitized.append(line[:_MAX_LINE_LEN])
    return "\n".join(sanitized)

_LEARNING_PATH = os.path.join(os.path.dirname(__file__), "..", "PREGAME_LEARNING.md")
_CRITIQUE_PATH = os.path.join(os.path.dirname(__file__), "..", "AI_SELF_CRITIQUE.md")
_STRATEGY_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "strategy_principles.md")
_COMPETITOR_INTEL_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "competitor_intel.md")
_EVENING_OBS_PATH = os.path.join(os.path.dirname(__file__), "..", "evening_observations.json")


def get_learning_context(current_regime: str = "NEUTRAL") -> str:
    evening_obs = _extract_evening_observations()
    strategy = _read_file(_STRATEGY_PATH)
    fallback_sections = []

    learning = _extract_learning_summary()
    if learning:
        fallback_sections.append(learning)

    critique = _extract_critique_summary()
    if critique:
        fallback_sections.append(critique)

    competitor_intel = _extract_competitor_intel_summary()
    if competitor_intel:
        fallback_sections.append(competitor_intel)

    raw = build_prompt_learning_context(
        strategy_text=strategy,
        fallback_sections=fallback_sections,
        current_regime=current_regime,
    )

    if competitor_intel:
        raw += "\n\n=== COMPETITOR INTELLIGENCE (manual watchlist) ===\n" + competitor_intel

    sanitized = _sanitize_learning_text(raw)

    # Prepend evening observations so agents see yesterday's review first (before budget truncation).
    if evening_obs:
        sanitized = evening_obs + "\n\n" + sanitized

    # Enforce total character budget — truncate at a clean line boundary
    if len(sanitized) > _MAX_CONTEXT_CHARS:
        truncated = sanitized[:_MAX_CONTEXT_CHARS]
        last_newline = truncated.rfind("\n")
        if last_newline > 0:
            truncated = truncated[:last_newline]
        sanitized = truncated + "\n[...truncated — see learning_state.json for full state]"
        logger.info(
            "Learning context truncated from %d to %d chars (budget: %d)",
            len(raw),
            len(sanitized),
            _MAX_CONTEXT_CHARS,
        )

    return sanitized


def _read_file(path: str) -> str:
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        return ""
    try:
        with open(abs_path) as f:
            return f.read()
    except Exception as exc:
        logger.debug("Could not read %s: %s", path, exc)
        return ""


def _extract_section(content: str, heading: str) -> list[str]:
    lines = []
    in_section = False
    for line in content.splitlines():
        if heading in line and line.startswith("#"):
            in_section = True
            continue
        if in_section:
            if line.startswith("#"):
                break
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                lines.append(stripped)
    return lines


def _extract_learning_summary() -> str:
    content = _read_file(_LEARNING_PATH)
    if not content:
        return ""
    parts = []
    scoreboard = _extract_section(content, "Scoreboard")
    if scoreboard:
        parts.append("Training scoreboard:\n" + "\n".join(scoreboard[:6]))
    action = _extract_section(content, "Action plan")
    if action:
        parts.append("Action plan:\n" + "\n".join(action[:4]))
    return "\n\n".join(parts) if parts else ""


def _extract_critique_summary() -> str:
    content = _read_file(_CRITIQUE_PATH)
    if not content:
        return ""
    parts = []
    working = _extract_section(content, "What's Working")
    if working:
        parts.append("What's been working:\n" + "\n".join(working[:4]))
    biases = _extract_section(content, "Systematic Biases")
    if biases:
        parts.append("Biases to correct today:\n" + "\n".join(biases[:4]))
    actions = _extract_section(content, "Action Items for the AI")
    if actions:
        parts.append("Specific instructions from self-critique:\n" + "\n".join(actions[:4]))
    return "\n\n".join(parts) if parts else ""


def _extract_competitor_intel_summary() -> str:
    content = _read_file(_COMPETITOR_INTEL_PATH)
    if not content:
        return ""

    sections = []
    if content.strip():
        lines = [line.rstrip() for line in content.splitlines() if line.strip()]
        sections.append("Competitor intelligence snapshot:\n" + "\n".join(lines[:28]))

    return "\n\n".join(sections) if sections else ""


def _extract_evening_observations() -> str:
    """Return a formatted summary of last night's evening review, if fresh (today or yesterday)."""
    raw = _read_file(_EVENING_OBS_PATH)
    if not raw:
        return ""
    try:
        obs = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.debug("Could not parse evening_observations.json: %s", exc)
        return ""

    try:
        obs_date = date.fromisoformat(obs["date"])
    except (KeyError, ValueError) as exc:
        logger.debug("Invalid date in evening_observations.json: %s", exc)
        return ""

    if abs((date.today() - obs_date).days) > 1:
        logger.debug("evening_observations.json is stale (%s) — skipping injection", obs_date)
        return ""

    port_ret = obs.get("portfolio_return", 0.0)
    bench_ret = obs.get("benchmark_return", 0.0)
    alpha = obs.get("alpha", 0.0)
    pos_list = obs.get("position_returns", [])
    ai_note = obs.get("ai_recommendation", "")

    moves = ", ".join(
        f"{p['ticker']} {p['return']:+.1%}" for p in pos_list if "ticker" in p and "return" in p
    )
    lines = [
        f"Last night's review ({obs_date}): portfolio {port_ret:+.1%} vs benchmark {bench_ret:+.1%} (alpha {alpha:+.1%}).",
    ]
    if moves:
        lines.append(f"Position moves: {moves}")
    if ai_note:
        lines.append(f"AI note: {ai_note}")

    return "\n".join(lines)
