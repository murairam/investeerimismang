"""
WebhookDispatcher — formats a PortfolioProposal as a Discord embed and POSTs it.
"""
import logging
import os
from datetime import datetime
from typing import Optional

import requests

from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal

logger = logging.getLogger(__name__)


def _round_weights(positions: list) -> list[int]:
    """Round position weights to integers using the largest-remainder method.

    Guarantees the rounded values sum to round(total * 100) so the numbers
    the user sees in Discord add up cleanly (e.g. 100% instead of 95%).
    """
    raw = [p.weight * 100 for p in positions]
    total_pct = round(sum(raw))
    floors = [int(w) for w in raw]
    needed = total_pct - sum(floors)
    indices_by_remainder = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
    result = floors[:]
    for i in indices_by_remainder[:needed]:
        result[i] += 1
    return result


_EMBED_COLOUR = 0x2ECC71
_MAX_EMBED_DESCRIPTION = 4096

# Display names as they appear in the Äripäev game UI
GAME_NAMES: dict[str, str] = {
    # S&P 500
    "AAPL": "Apple", "NVDA": "Nvidia", "MSFT": "Microsoft", "AMZN": "Amazon",
    "GOOGL": "Alphabet", "META": "Meta", "TSLA": "Tesla", "AVGO": "Broadcom",
    "JPM": "JPMorgan Chase", "LLY": "Eli Lilly", "UNH": "UnitedHealth",
    "XOM": "Exxon Mobil", "V": "Visa", "MA": "Mastercard", "JNJ": "Johnson & Johnson",
    "WMT": "Walmart", "PG": "Procter & Gamble", "HD": "Home Depot",
    "MRK": "Merck", "COST": "Costco", "ABBV": "AbbVie", "CVX": "Chevron",
    "CRM": "Salesforce", "NFLX": "Netflix", "AMD": "AMD",
    "BAC": "Bank of America", "PEP": "PepsiCo", "KO": "Coca-Cola",
    "TMO": "Thermo Fisher", "ORCL": "Oracle", "CSCO": "Cisco",
    "ACN": "Accenture", "MCD": "McDonald's", "ABT": "Abbott",
    "TXN": "Texas Instruments", "DHR": "Danaher", "NKE": "Nike",
    "INTC": "Intel", "PM": "Philip Morris", "NEE": "NextEra Energy",
    "UPS": "UPS", "LOW": "Lowe's", "QCOM": "Qualcomm",
    "AMGN": "Amgen", "IBM": "IBM", "GS": "Goldman Sachs",
    "CAT": "Caterpillar", "HON": "Honeywell", "BA": "Boeing", "SPGI": "S&P Global",
    # Finland
    "NOKIA.HE": "Nokia", "FORTUM.HE": "Fortum", "SAMPO.HE": "Sampo A",
    "NESTE.HE": "Neste", "KNEBV.HE": "Kone B", "WRT1V.HE": "Wärtsilä",
    "STERV.HE": "Stora Enso R", "OUT1V.HE": "Outokumpu A", "ELISA.HE": "Elisa",
    "ORNBV.HE": "Orion B", "UPM.HE": "UPM-Kymmene", "METSO.HE": "Metso",
    # Sweden
    "ERIC-B.ST": "Ericsson B", "VOLV-B.ST": "Volvo B", "ATCO-A.ST": "Atlas Copco A",
    "SEB-A.ST": "SEB A", "SWED-A.ST": "Swedbank A", "INVE-B.ST": "Investor B",
    "HM-B.ST": "H&M B", "SHB-A.ST": "Handelsbanken A", "ESSITY-B.ST": "Essity B",
    "ABB.ST": "ABB", "SAND.ST": "Sandvik", "SKF-B.ST": "SKF B",
    "ALFA.ST": "Alfa Laval", "TELIA.ST": "Telia", "BOL.ST": "Boliden",
    "NIBE-B.ST": "NIBE B", "EVO.ST": "Evolution", "SSAB-A.ST": "SSAB A",
    # Norway
    "EQNR.OL": "Equinor", "DNB.OL": "DNB", "NHY.OL": "Norsk Hydro",
    "TEL.OL": "Telenor", "MOWI.OL": "Mowi", "ORK.OL": "Orkla",
    "YAR.OL": "Yara", "SCATC.OL": "Scatec", "SUBC.OL": "Subsea 7",
    "SALM.OL": "SalMar", "RECSI.OL": "REC Silicon",
    # Denmark
    "NOVO-B.CO": "Novo Nordisk B", "DSV.CO": "DSV", "ORSTED.CO": "Ørsted",
    "CARL-B.CO": "Carlsberg B", "GMAB.CO": "Genmab", "MAERSK-B.CO": "A.P. Møller - Mærsk B",
    "COLO-B.CO": "Coloplast B", "GN.CO": "GN Store Nord", "DEMANT.CO": "Demant",
    "PNDORA.CO": "Pandora", "ISS.CO": "ISS",
    # Baltic
    "LHV1T.TL": "LHV Group", "PRF1T.TL": "Premia Foods", "TKM1T.TL": "Tallinna Kaubamaja",
    "MRK1T.TL": "Merko Ehitus", "ARC1T.TL": "Arco Vara", "TAL1T.TL": "Tallink Grupp",
    "GRG1L.VS": "Grigeo", "APG1L.VS": "Apranga", "VLP1L.VS": "Vilkyškių pieninė",
}


def _display(ticker: str) -> str:
    """Return game display name for a ticker, fallback to ticker itself."""
    return GAME_NAMES.get(ticker, ticker)


class WebhookDispatcher:
    def __init__(self) -> None:
        self.webhook_url = os.environ["DISCORD_WEBHOOK_URL"]
        self.user_id = os.environ.get("DISCORD_USER_ID")  # Optional Discord user ID for @mentions

    def format_embed(
        self,
        proposal: PortfolioProposal,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
        paper_metrics: Optional[dict] = None,
    ) -> dict:
        total_weight = sum(p.weight for p in proposal.positions)
        confidence_pct = int(proposal.confidence * 100)

        run_time = datetime.now()
        today = run_time.strftime("%Y-%m-%d")
        run_time_str = run_time.strftime("%H:%M:%S")

        candidate_map = {c["ticker"]: c for c in snapshot["candidates"]}
        selected_vs_index = [
            candidate_map[p.ticker]["vs_index"]
            for p in proposal.positions
            if p.ticker in candidate_map
        ]
        avg_vs_index = (
            sum(selected_vs_index) / len(selected_vs_index)
            if selected_vs_index
            else None
        )

        market_momentum_buckets: dict[str, list[float]] = {}
        for candidate in snapshot["candidates"]:
            market_momentum_buckets.setdefault(candidate["market"], []).append(candidate["momentum"])
        market_mean_momentum = {
            market: sum(vals) / len(vals)
            for market, vals in market_momentum_buckets.items()
            if vals
        }

        blended_benchmark_proxy = 0.0
        blended_has_data = False
        for position in proposal.positions:
            candidate = candidate_map.get(position.ticker)
            if not candidate:
                continue
            market = candidate["market"]
            if market in market_mean_momentum:
                blended_benchmark_proxy += position.weight * market_mean_momentum[market]
                blended_has_data = True

        regime = snapshot.get("regime", "N/A")
        vix_level = snapshot.get("vix_level", float("nan"))
        vix_str = "N/A" if (vix_level != vix_level) else f"{vix_level:.1f}"
        context_line = (
            f"📊 Context: {regime} regime · VIX {vix_str} · Candidates {len(snapshot['candidates'])} · Run {run_time_str}"
        )

        rounded_pcts = _round_weights(proposal.positions)
        rows = ["```", f"{'#':<3} {'Stock':<26} {'%':>4}", "-" * 36]
        for i, (pos, w_int) in enumerate(zip(proposal.positions, rounded_pcts), 1):
            name = _display(pos.ticker)
            rows.append(f"{i:<3} {name:<26} {w_int:>3}%")
        rows.append("-" * 36)
        rows.append(f"{'TOTAL':<30} {sum(rounded_pcts):>3}%")
        rows.append("```")
        holdings_table = "\n".join(rows)

        rationale_lines = []
        for i, pos in enumerate(proposal.positions, 1):
            rationale = pos.rationale.strip()
            if len(rationale) > 90:
                rationale = rationale[:89] + "…"
            rationale_lines.append(f"{i}. **{_display(pos.ticker)}** — {rationale}")
        rationale_block = "\n".join(rationale_lines[:8])

        change_lines: list[str] = []
        if prior_proposal and prior_proposal.positions:
            prior_map = {p.ticker: p.weight for p in prior_proposal.positions}
            current_map = {p.ticker: p.weight for p in proposal.positions}

            added = [ticker for ticker in current_map if ticker not in prior_map]
            removed = [ticker for ticker in prior_map if ticker not in current_map]
            resized = [
                ticker
                for ticker in current_map
                if ticker in prior_map and abs(current_map[ticker] - prior_map[ticker]) >= 0.01
            ]

            if added or removed or resized:
                for ticker in added[:3]:
                    change_lines.append(f"➕ {_display(ticker)} {int(current_map[ticker] * 100)}%")
                for ticker in removed[:3]:
                    change_lines.append(f"➖ {_display(ticker)} (was {int(prior_map[ticker] * 100)}%)")
                for ticker in resized[:4]:
                    diff = current_map[ticker] - prior_map[ticker]
                    arrow = "▲" if diff > 0 else "▼"
                    change_lines.append(
                        f"{arrow} {_display(ticker)} {int(prior_map[ticker] * 100)}%→{int(current_map[ticker] * 100)}% ({diff:+.0%})"
                    )
            else:
                change_lines.append("No material changes vs yesterday")
        else:
            change_lines.append("First run / no prior portfolio")

        changes_block = "\n".join(change_lines[:8])

        alpha_line = (
            f"🧠 Alpha (avg selected vs index, 20d): {avg_vs_index:+.1%}"
            if avg_vs_index is not None
            else "🧠 Alpha (avg selected vs index, 20d): N/A"
        )
        blended_line = (
            f"⚖️ Blend benchmark proxy (market-mix 20d): {blended_benchmark_proxy:+.1%}"
            if blended_has_data
            else "⚖️ Blend benchmark proxy (market-mix 20d): N/A"
        )

        cash_pct = max(0.0, 1.0 - total_weight)
        cash_line = f"💶 Cash buffer: {cash_pct:.1%}" if cash_pct > 1e-6 else "💶 Cash buffer: 0.0%"

        paper_line = ""
        if paper_metrics:
            equity = paper_metrics.get("equity")
            daily_return = paper_metrics.get("daily_return")
            since_start = paper_metrics.get("return_since_start")
            if equity is not None and daily_return is not None and since_start is not None:
                paper_line = (
                    f"\n📒 Paper account: €{equity:,.2f} "
                    f"({daily_return:+.2%} today, {since_start:+.2%} since start)"
                )

        description = (
            f"**Thesis:** {proposal.reasoning}\n\n"
            f"{context_line}\n"
            f"{alpha_line}\n"
            f"{blended_line}\n"
            f"{cash_line}{paper_line}\n\n"
            f"**Changes Since Yesterday**\n{changes_block}\n\n"
            f"**Holdings**\n{holdings_table}\n"
            f"**Rationales**\n{rationale_block}"
        )
        if len(description) > _MAX_EMBED_DESCRIPTION:
            description = description[: _MAX_EMBED_DESCRIPTION - 3] + "…"

        verification_reminder = (
            "\n\n⚠️ **ACTION REQUIRED:** Update your game portfolio on the website, then run `python verify.py` to confirm sync."
        )

        return {
            "title": f"🦈 AlphaShark Portfolio — {today} {run_time_str}",
            "description": description + verification_reminder,
            "color": _EMBED_COLOUR,
            "footer": {
                "text": (
                    f"Confidence: {confidence_pct}% · "
                    f"{len(proposal.positions)} positions · "
                    f"Total weight: {total_weight:.1%} · "
                    f"S&P 500 20d: {snapshot['benchmark_return']:+.1%} · "
                    f"Run: {run_time_str}"
                )
            },
        }

    def send(self, embed: dict, mention_user: bool = False) -> None:
        """
        Send embed to Discord.

        Args:
            embed: Discord embed dict
            mention_user: If True and DISCORD_USER_ID is set, mentions the user (pings their phone)
        """
        payload = {"embeds": [embed]}

        # Add user mention for LIVE mode alerts
        if mention_user and self.user_id:
            payload["content"] = f"<@{self.user_id}>"

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
