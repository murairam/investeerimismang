"""
WebhookDispatcher — formats a PortfolioProposal as a Discord embed and POSTs it.
"""
import logging
import math
import os
import re
from datetime import datetime
from typing import Optional

import requests

from data.fetcher import MarketSnapshot
from data.symbol_master import get_symbol_record
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
_MAX_FIELD_VALUE = 1024


def _ensure_complete_sentence(text: str) -> str:
    """Return text ending in punctuation to avoid half-sentence output."""
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return "No rationale provided."
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _truncate_on_sentence_boundary(text: str, limit: int) -> str:
    """Truncate without cutting mid-sentence where possible."""
    if len(text) <= limit:
        return _ensure_complete_sentence(text)

    clipped = text[:limit].rstrip()
    boundary = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if boundary >= max(0, int(limit * 0.6)):
        return _ensure_complete_sentence(clipped[: boundary + 1])

    fallback = clipped[: max(0, limit - 1)].rstrip()
    if fallback and fallback[-1] not in ".!?":
        fallback += "."
    return fallback


def _chunk_lines(lines: list[str], limit: int = _MAX_FIELD_VALUE) -> list[str]:
    """Pack lines into Discord-sized chunks without splitting lines."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        safe_line = line if len(line) <= limit else _truncate_on_sentence_boundary(line, limit)
        candidate_len = current_len + (1 if current else 0) + len(safe_line)
        if current and candidate_len > limit:
            chunks.append("\n".join(current))
            current = [safe_line]
            current_len = len(safe_line)
        else:
            current.append(safe_line)
            current_len = candidate_len if current_len else len(safe_line)

    if current:
        chunks.append("\n".join(current))

    return chunks or ["N/A"]

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
    "MU": "Micron Technology", "APA": "APA Corporation", "DVN": "Devon Energy",
    "CIEN": "Ciena", "EOG": "EOG Resources", "COP": "ConocoPhillips",
    "OXY": "Occidental Petroleum", "HAL": "Halliburton", "SLB": "SLB",
    "FANG": "Diamondback Energy", "MRO": "Marathon Oil", "HES": "Hess",
    "STX": "Seagate Technology", "WDC": "Western Digital", "SNDK": "SanDisk",
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
    "AKRBP.OL": "Aker BP", "KOG.OL": "Kongsberg", "PGSOL.OL": "PGS",
    "TGS.OL": "TGS", "BORR.OL": "Borr Drilling",
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


def _prettify_ticker(ticker: str) -> str:
    base = ticker.split(".", 1)[0]
    parts = [part for part in base.replace("-", " ").split() if part]
    if not parts:
        return ticker
    pretty = " ".join(
        part.upper() if len(part) <= 3 else part.capitalize()
        for part in parts
    )
    if "." in ticker:
        suffix = ticker.rsplit(".", 1)[-1]
        market_label = {
            "HE": " (FI)",
            "ST": " (SE)",
            "OL": " (NO)",
            "CO": " (DK)",
            "TL": " (EE)",
            "VS": " (LT)",
        }.get(suffix, "")
        return pretty + market_label
    return pretty


def _display(ticker: str) -> str:
    """Return game display name for a ticker, fallback to ticker itself."""
    record = get_symbol_record(ticker)
    if record and record.get("company_name"):
        return str(record["company_name"]).strip()
    return GAME_NAMES.get(ticker, _prettify_ticker(ticker))


def display_security_name(ticker: str) -> str:
    return _display(ticker)


def format_security_label(ticker: str) -> str:
    return f"{_display(ticker)} ({ticker})"


class WebhookDispatcher:
    def __init__(self) -> None:
        self.webhook_url = os.environ["DISCORD_WEBHOOK_URL"]
        raw_uid = os.environ.get("DISCORD_USER_ID", "").strip()
        # Discord snowflake IDs are 17–20 digits; reject anything else to prevent injection
        import re as _re
        self.user_id: Optional[str] = raw_uid if _re.fullmatch(r"\d{17,20}", raw_uid) else None
        if raw_uid and not self.user_id:
            logger.warning("DISCORD_USER_ID '%s' is not a valid snowflake — ignoring", raw_uid)

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
        clean_vs = [v for v in selected_vs_index if v is not None and not math.isnan(v)]
        avg_vs_index = sum(clean_vs) / len(clean_vs) if clean_vs else None

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
        vix_str = "N/A" if math.isnan(vix_level) else f"{vix_level:.1f}"
        context_line = (
            f"📊 Context: {regime} regime · VIX {vix_str} · Candidates {len(snapshot['candidates'])} · Run {run_time_str}"
        )

        rounded_pcts = _round_weights(proposal.positions)
        rows = ["```", f"{'#':<3} {'Stock':<42} {'%':>4}", "-" * 52]
        for i, (pos, w_int) in enumerate(zip(proposal.positions, rounded_pcts), 1):
            name = format_security_label(pos.ticker)
            if len(name) > 42:
                name = name[:41] + "…"
            rows.append(f"{i:<3} {name:<42} {w_int:>3}%")
        rows.append("-" * 52)
        rows.append(f"{'TOTAL':<46} {sum(rounded_pcts):>3}%")
        rows.append("```")
        holdings_table = "\n".join(rows)

        rationale_lines = []
        for i, pos in enumerate(proposal.positions, 1):
            rationale = _truncate_on_sentence_boundary(pos.rationale.strip(), 280)
            rationale_lines.append(f"{i}. {_display(pos.ticker)} — {rationale}")

        # Build actionable changes summary
        change_lines: list[str] = []
        action_summary: list[str] = []

        if prior_proposal and prior_proposal.positions:
            prior_map = {p.ticker: p.weight for p in prior_proposal.positions}
            current_map = {p.ticker: p.weight for p in proposal.positions}
            current_pos_map = {p.ticker: p for p in proposal.positions}

            def _signal_commentary(ticker: str) -> list[str]:
                candidate = candidate_map.get(ticker)
                if not candidate:
                    return []

                notes: list[str] = []
                mom_5d = candidate.get("mom_5d", float("nan"))
                vs_index = candidate.get("vs_index", float("nan"))
                vol_ratio = candidate.get("vol_ratio", float("nan"))
                rsi_14 = candidate.get("rsi_14", float("nan"))
                pct_high = candidate.get("pct_from_52w_high", float("nan"))

                if not math.isnan(mom_5d):
                    if mom_5d >= 0.03:
                        notes.append(f"strong 5d momentum ({mom_5d:+.1%})")
                    elif mom_5d <= 0.0:
                        notes.append(f"weak 5d momentum ({mom_5d:+.1%})")

                if not math.isnan(vs_index):
                    if vs_index > 0.0:
                        notes.append(f"outperforming index ({vs_index:+.1%})")
                    elif vs_index < 0.0:
                        notes.append(f"lagging index ({vs_index:+.1%})")

                if not math.isnan(vol_ratio):
                    if vol_ratio >= 1.2:
                        notes.append(f"volume confirmation ({vol_ratio:.2f}x)")
                    elif vol_ratio < 0.8:
                        notes.append(f"low volume confirmation ({vol_ratio:.2f}x)")

                overbought = (
                    not math.isnan(rsi_14)
                    and not math.isnan(pct_high)
                    and rsi_14 > 82
                    and pct_high >= -0.02
                    and (math.isnan(vol_ratio) or vol_ratio <= 1.8)
                )
                if overbought:
                    notes.append("overbought near 52w high")

                return notes

            def _reason_for_add(ticker: str) -> str:
                pos = current_pos_map.get(ticker)
                rationale = _truncate_on_sentence_boundary(pos.rationale.strip(), 120) if pos else ""
                signal_notes = _signal_commentary(ticker)
                if signal_notes:
                    return "; ".join(signal_notes[:2]) + "."
                if rationale and rationale != "No rationale provided.":
                    return rationale
                return "New high-conviction entry versus alternatives."

            def _reason_for_remove(ticker: str) -> str:
                signal_notes = _signal_commentary(ticker)
                negative = [
                    note
                    for note in signal_notes
                    if any(token in note for token in ("weak", "lagging", "low volume", "overbought"))
                ]
                if negative:
                    return "; ".join(negative[:2]) + "."
                return "Capital reallocated to stronger opportunities (slot-cost upgrade)."

            def _reason_for_resize(ticker: str, diff: float) -> str:
                signal_notes = _signal_commentary(ticker)
                rationale = _truncate_on_sentence_boundary(
                    current_pos_map[ticker].rationale.strip(),
                    120,
                ) if ticker in current_pos_map else ""
                if diff > 0:
                    if signal_notes:
                        return "Conviction increased: " + "; ".join(signal_notes[:2]) + "."
                    if rationale and rationale != "No rationale provided.":
                        return f"Conviction increased: {rationale}"
                    return "Conviction increased after proposal synthesis."
                risk_notes = [
                    note
                    for note in signal_notes
                    if any(token in note for token in ("weak", "lagging", "low volume", "overbought"))
                ]
                if risk_notes:
                    return "Risk trim: " + "; ".join(risk_notes[:2]) + "."
                return "Risk-rebalanced to fund higher-conviction names."

            added = [ticker for ticker in current_map if ticker not in prior_map]
            removed = [ticker for ticker in prior_map if ticker not in current_map]
            resized = [
                ticker
                for ticker in current_map
                if ticker in prior_map and abs(current_map[ticker] - prior_map[ticker]) >= 0.01
            ]

            if added or removed or resized:
                # Action summary header
                if added:
                    action_summary.append(f"**ADD {len(added)}:** {', '.join(_display(t) for t in added)}")
                if removed:
                    action_summary.append(f"**REMOVE {len(removed)}:** {', '.join(_display(t) for t in removed)}")
                if resized:
                    action_summary.append(f"**RESIZE {len(resized)}:** {', '.join(_display(t) for t in resized)}")

                change_lines.append("\n".join(action_summary))
                change_lines.append("")  # blank line

                # Detailed changes
                for ticker in added:
                    reason = _reason_for_add(ticker)
                    change_lines.append(
                        f"➕ **{_display(ticker)}** → {int(current_map[ticker] * 100)}% — {reason}"
                    )
                for ticker in removed:
                    reason = _reason_for_remove(ticker)
                    change_lines.append(
                        f"➖ **{_display(ticker)}** (was {int(prior_map[ticker] * 100)}%) — {reason}"
                    )
                for ticker in resized:
                    diff = current_map[ticker] - prior_map[ticker]
                    arrow = "▲" if diff > 0 else "▼"
                    reason = _reason_for_resize(ticker, diff)
                    change_lines.append(
                        f"{arrow} **{_display(ticker)}** {int(prior_map[ticker] * 100)}%→{int(current_map[ticker] * 100)}% — {reason}"
                    )
            else:
                change_lines.append("✅ **No changes** — portfolio unchanged from yesterday")
        else:
            change_lines.append("📋 **First run** — no prior portfolio to compare")

        changes_chunks = _chunk_lines(change_lines)

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

        thesis = _truncate_on_sentence_boundary(proposal.reasoning.strip(), 500)

        description = (
            f"**Thesis:** {thesis}\n\n"
            f"{context_line}\n"
            f"{alpha_line}\n"
            f"{blended_line}\n"
            f"{cash_line}{paper_line}"
        )
        if len(description) > _MAX_EMBED_DESCRIPTION:
            description = description[: _MAX_EMBED_DESCRIPTION - 3] + "…"

        game_search_lines = [
            f"{i}. {_display(pos.ticker)}"
            for i, pos in enumerate(proposal.positions, 1)
        ]

        fields: list[dict] = []

        for idx, chunk in enumerate(changes_chunks, 1):
            fields.append(
                {
                    "name": "Changes from Yesterday" if idx == 1 else f"Changes from Yesterday (cont. {idx})",
                    "value": chunk,
                    "inline": False,
                }
            )

        fields.append(
            {
                "name": "Game Search Terms (use on website)",
                "value": "\n".join(game_search_lines[:20]),
                "inline": False,
            }
        )

        fields.append(
            {
                "name": "Current Holdings",
                "value": holdings_table[:_MAX_FIELD_VALUE],
                "inline": False,
            }
        )

        key_chunks = _chunk_lines(rationale_lines)
        for idx, chunk in enumerate(key_chunks, 1):
            fields.append(
                {
                    "name": "Key Points (all selected stocks)" if idx == 1 else f"Key Points (cont. {idx})",
                    "value": chunk,
                    "inline": False,
                }
            )

        fields.append(
            {
                "name": "Next Steps",
                "value": (
                    "1) Review changes above\n"
                    "2) Update portfolio on game website\n"
                    "3) Run python scripts/verify.py to confirm"
                ),
                "inline": False,
            }
        )

        return {
            "title": f"🦈 AlphaShark Portfolio — {today} {run_time_str}",
            "description": description,
            "color": _EMBED_COLOUR,
            "fields": fields,
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
