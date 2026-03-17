"""
WebhookDispatcher — formats a PortfolioProposal as a Discord embed and POSTs it.
"""
import logging
import os
from datetime import date

import requests

from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal

logger = logging.getLogger(__name__)

# Discord embed colour (green)
_EMBED_COLOUR = 0x2ECC71
_MAX_EMBED_DESCRIPTION = 4096   # Discord limit


class WebhookDispatcher:
    def __init__(self) -> None:
        self.webhook_url = os.environ["DISCORD_WEBHOOK_URL"]

    def format_embed(
        self,
        proposal: PortfolioProposal,
        snapshot: MarketSnapshot,
    ) -> dict:
        total_weight = sum(p.weight for p in proposal.positions)
        confidence_pct = int(proposal.confidence * 100)
        today = date.today().isoformat()

        # ── Ticker table ─────────────────────────────────────────────────────
        rows = ["```", f"{'#':<3} {'Ticker':<10} {'Weight':>7}  Rationale", "-" * 70]
        for i, pos in enumerate(proposal.positions, 1):
            rationale = pos.rationale[:45] + "…" if len(pos.rationale) > 46 else pos.rationale
            rows.append(f"{i:<3} {pos.ticker:<10} {pos.weight:>6.1%}  {rationale}")
        rows.append("-" * 70)
        rows.append(f"{'TOTAL':<14} {total_weight:>6.1%}")
        rows.append("```")
        table = "\n".join(rows)

        # ── Benchmark line ────────────────────────────────────────────────────
        bench_arrow = "📈" if snapshot["benchmark_return"] >= 0 else "📉"
        bench_line = (
            f"{bench_arrow} S&P 500 20-day return: {snapshot['benchmark_return']:.1%} "
            f"(as of {snapshot['as_of_date']})"
        )

        description = (
            f"**Thesis:** {proposal.reasoning}\n\n"
            f"{bench_line}\n\n"
            f"{table}"
        )
        if len(description) > _MAX_EMBED_DESCRIPTION:
            description = description[: _MAX_EMBED_DESCRIPTION - 3] + "…"

        embed = {
            "title": f"🦈 AlphaShark Portfolio — {today}",
            "description": description,
            "color": _EMBED_COLOUR,
            "footer": {
                "text": (
                    f"Confidence: {confidence_pct}% · "
                    f"{len(proposal.positions)} positions · "
                    f"Total weight: {total_weight:.1%}"
                )
            },
        }
        return embed

    def send(self, embed: dict) -> None:
        payload = {"embeds": [embed]}
        try:
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError("Discord webhook: connection failed — check DISCORD_WEBHOOK_URL") from exc
        except requests.exceptions.Timeout as exc:
            raise RuntimeError("Discord webhook: request timed out after 10s") from exc
        except requests.exceptions.HTTPError as exc:
            raise RuntimeError(
                f"Discord webhook: HTTP {response.status_code} — {response.text[:200]}"
            ) from exc
        logger.info("Discord embed sent (status %d)", response.status_code)
