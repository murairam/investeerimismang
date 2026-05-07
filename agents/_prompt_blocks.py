"""Shared static prompt blocks injected into agent system prompts.

These reflect the live-evidence learning loop output (rationale_stats from
learning_state.json). Updated 2026-05-07 after rank-trajectory diagnosis.
"""
from __future__ import annotations

RATIONALE_GUIDANCE_BLOCK = """

RATIONALE BLACKLIST (live evidence — do not propose primary thesis matching these):
- non_us_differentiator: 27% hit rate over 37 obs, avg -0.31% next-day return.
  Foreign tickers OK only when momentum/volume signals stand on their own.
- diversifier: 40% hit rate over 5 obs, avg -0.42%. Sector-balance picks lose.
- catalyst (earnings drift): 40% hit rate over 20 obs, avg -0.47%. Cap pre-earnings
  exposure at 12% per name (was 20%) and 30% total (was 40%).

RATIONALE WHITELIST (62% hit rate, avg +0.81% — lean into):
- at_52w_high + overbought (RSI>80) + vol_ratio>=1.5 + mom_5d>=10%
  = LEADERSHIP confirmation, not exhaustion. Maximum conviction allowed at
  RSI>85 with these conditions.

VALIDATED CORE TICKERS (live hit rate >=73%):
- ON (10 obs, 100% hit), INTC (8, 100%), AMD (12, 83%), XOM (8, 75%), STX (22, 73%)
- Use as default candidates when signals are otherwise comparable.

BANNED TICKERS (recurring losers):
- EQNR.OL: 20% hit over 10 obs — do not propose.
- DOW: 50% hit, drag history — soft cap 7%.
- VWS.CO: 33% hit over 12 obs — soft cap 7%.
"""


def render_devil_contrarian_block(devil_inversion_active: bool) -> str:
    """Risk-Manager-only block: warn when Devil's HIGH flags are contrarian-buy signals."""
    if not devil_inversion_active:
        return ""
    return """

DEVIL CONTRARIAN MODE ACTIVE (live n>=30, accuracy <50%):
Devil's Advocate has been empirically inverted: HIGH-risk flags have averaged
+1.06% next-day return; LOW flagged averaged -0.07%. Bear cases are prefixed
[CONTRARIAN-INVERTED]. Treat HIGH flags as momentum confirmation, NOT warning.
Do NOT downweight HIGH-flagged tickers in synthesis. Devil's bear narrative is
unreliable in the current regime — weight your own signals over its prose.
"""


def render_rank_context_block(rank_history: list[dict]) -> str:
    """Risk-Manager-only block: rank-trajectory feedback so synthesis adapts to field movement."""
    if not rank_history:
        return ""
    rows = []
    for entry in rank_history:
        d = entry.get("date")
        rank = entry.get("rank")
        total = entry.get("total_participants")
        delta = entry.get("rank_delta")
        if d is None or rank is None or total is None:
            continue
        if delta is None:
            rows.append(f"  {d}: rank {rank}/{total} (no prior comparison)")
        else:
            arrow = "▼" if delta < 0 else ("▲" if delta > 0 else "•")
            rows.append(f"  {d}: rank {rank}/{total}  delta {delta:+d} {arrow}")
    if not rows:
        return ""
    return (
        "\n\nRANK CONTEXT (last 5 sessions vs full field):\n"
        + "\n".join(rows)
        + "\nIf rank slipping despite positive alpha — field running hotter than us; "
        "INCREASE concentration / beta / right-tail breakouts. "
        "If rank gaining — current strategy working, maintain.\n"
    )
