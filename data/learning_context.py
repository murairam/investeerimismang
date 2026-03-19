"""
Build prompt-ready learning context from structured learning state first,
with markdown summaries as a backward-compatible fallback.
"""
import logging
import os

from data.learning_state import build_prompt_learning_context

logger = logging.getLogger(__name__)

_LEARNING_PATH = os.path.join(os.path.dirname(__file__), "..", "PREGAME_LEARNING.md")
_CRITIQUE_PATH = os.path.join(os.path.dirname(__file__), "..", "AI_SELF_CRITIQUE.md")
_STRATEGY_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "strategy_principles.md")


def get_learning_context() -> str:
    strategy = _read_file(_STRATEGY_PATH)
    fallback_sections = []

    learning = _extract_learning_summary()
    if learning:
        fallback_sections.append(learning)

    critique = _extract_critique_summary()
    if critique:
        fallback_sections.append(critique)

    return build_prompt_learning_context(strategy_text=strategy, fallback_sections=fallback_sections)


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
