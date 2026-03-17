"""
Reads PREGAME_LEARNING.md and AI_SELF_CRITIQUE.md and extracts a concise
summary for injection into agent system prompts each morning.

This is what makes the AI actually improve over the pre-game training period —
it sees what rationales worked, which tickers underperformed, and what
systematic biases to correct, before generating today's proposal.
"""
import logging
import os

logger = logging.getLogger(__name__)

_LEARNING_PATH = os.path.join(os.path.dirname(__file__), "..", "PREGAME_LEARNING.md")
_CRITIQUE_PATH = os.path.join(os.path.dirname(__file__), "..", "AI_SELF_CRITIQUE.md")


def get_learning_context() -> str:
    """
    Returns a concise string summarising past performance and AI self-critique,
    suitable for injection into agent prompts.
    Returns empty string if no data is available yet (first run).
    """
    sections = []

    learning = _extract_learning_summary()
    if learning:
        sections.append(learning)

    critique = _extract_critique_summary()
    if critique:
        sections.append(critique)

    if not sections:
        return ""

    header = "=== LEARNING FROM PREVIOUS RUNS (use to improve today's picks) ==="
    footer = "=== END LEARNING ==="
    return header + "\n" + "\n\n".join(sections) + "\n" + footer


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
    """Extract bullet lines from a markdown section by heading substring."""
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

    # Scoreboard stats
    scoreboard = _extract_section(content, "Scoreboard")
    if scoreboard:
        parts.append("Training scoreboard:\n" + "\n".join(scoreboard[:6]))

    # Ticker lessons — best and worst only
    ticker_lines = _extract_section(content, "Ticker lessons")
    if ticker_lines:
        parts.append("Ticker lessons (best/worst performers so far):\n" + "\n".join(ticker_lines[:6]))

    # Action plan
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
