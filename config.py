"""
Global configuration: game constraints, ticker universe, signal parameters.
"""

# ── Game constraints ─────────────────────────────────────────────────────────
GAME_CONSTRAINTS = {
    "min_stocks": 5,
    "max_stocks": 20,
    "min_weight": 0.05,        # 5%
    "max_weight": 0.25,        # 25%
    "max_total_weight": 1.00,  # 100%
    "min_total_weight": 0.75,  # 75% game-rule minimum; cash policy targets higher deployment

}

# Preferred stock-count bands by market regime (still bounded by GAME_CONSTRAINTS)
# Competition logic: daily rebalancing replaces insurance positions.
# Concentrate on highest-signal picks; no token 5% diversifiers.
POSITION_TARGETS_BY_REGIME = {
    "BULL":    {"min_stocks": 5, "max_stocks": 6},   # tight concentration — 5 is the target, 6 only if genuinely high-conviction
    "NEUTRAL": {"min_stocks": 5, "max_stocks": 10},  # AI decides — more candidates = more range
    "BEAR":    {"min_stocks": 6, "max_stocks": 12},  # spread risk in downturns
}

# Cash policy (used when proposed allocation is below 100%)
CASH_POLICY = {
    "min_cash_gap": 0.01,                 # ignore tiny residual cash below 1%
    "high_vix_threshold": 26.0,           # keep more cash in high-volatility regimes
    "weak_benchmark_threshold": -0.02,    # if benchmark momentum is weaker than -2%
    "strong_alpha_threshold": 0.03,       # deploy cash when selected names show strong alpha
}

OPENAI_FALLBACK_MODEL = "gpt-4o-mini"  # used if primary model unavailable
API_TIMEOUT_SECONDS = 45

USE_OPENROUTER_FOR_SECONDARY_AGENTS = True  # set False to revert to OpenAI for all
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEVIL_MODEL = "qwen/qwen3-32b"
OPENROUTER_ANALYST_MODEL = "qwen/qwen3-32b"

# Risk control thresholds
OVERBOUGHT_RSI_THRESHOLD = 79   # was 82; lowered to catch RSI 79-82 exhaustion before full overbought
OVERBOUGHT_HIGH_PCT = 0.02      # within 2% of 52w high
OVERBOUGHT_VOLUME_EXCEPTION = 1.8  # vol_ratio above this bypasses cap
OVERBOUGHT_WEIGHT_CAP = 0.15
DEAD_MONEY_VOL_RATIO = 0.90
DEAD_MONEY_MOM_5D = 0.01
DEVIL_ACCURACY_CAP_WEIGHT = 0.10
BETA_CHECK_MIN_US_WEIGHT = 0.25
NON_US_ASSUMED_BETA = 0.30
FALLBACK_REPLACEMENT_WEIGHT = 0.05
MIN_CANDIDATE_SCORE_FOR_SLOT = 0.15
ROTATION_RISK_HIGH_SECTOR_CAP = 0.60    # max sector weight when rotation risk = HIGH
ROTATION_RISK_MEDIUM_SECTOR_CAP = 0.75  # max sector weight when rotation risk = MEDIUM
LOW_VOLUME_VOL_RATIO_THRESHOLD = 0.80   # low-volume confirmation floor for concentration caps
LOW_VOLUME_MAX_WEIGHT = 0.18
PORTFOLIO_MIN_AVG_VOL_RATIO = 0.85

# Regime thresholds
VIX_HIGH_THRESHOLD = 30
VIX_NEUTRAL_THRESHOLD = 22
VIX_LOW_THRESHOLD = 15

# ── Signal parameters ────────────────────────────────────────────────────────
MOMENTUM_WINDOW = 20        # trading days for momentum calculation
BETA_WINDOW = 60            # trading days for beta calculation
BETA_MIN_OBSERVATIONS = 30  # minimum aligned return observations required for beta estimation
BETA_BENCHMARK = "^GSPC"    # S&P 500 as benchmark
TOP_N_CANDIDATES = 200      # max candidates passed to agents — pure signal meritocracy, no per-market caps
RSI_WINDOW = 14             # RSI lookback period
MOM_SHORT = 5               # short-term momentum window (days)
MOM_LONG = 60               # long-term momentum window (days)
SMA_REGIME_WINDOW = 200     # days for market regime SMA
REGIME_THRESHOLD = 0.02     # 2% band for BULL/BEAR classification
CORR_WINDOW = 60            # days for correlation filter
CORR_THRESHOLD = 0.93       # correlation above this → keep higher Sharpe; 0.93 catches near-identical series (dual-class shares, same-commodity pure plays) without filtering distinct large-caps that merely co-move in bull markets

# ── Competition ranking weights ──────────────────────────────────────────────
# Z-score normalized weights for competition-optimized candidate ranking.
# BULL: reward momentum × beta (competition winners in bull runs).
# NEUTRAL: balanced Sharpe + relative strength. BEAR: Sharpe + low-beta defense.
# inv_beta = (1 − beta): computed BEFORE Z-scoring in BEAR regime.
COMPETITION_SORT_WEIGHTS: dict[str, dict[str, float]] = {
    "BULL":    {"mom_20d": 0.35, "mom_5d": 0.25, "sharpe_20d": 0.20, "beta": 0.20},
    "NEUTRAL": {"sharpe_20d": 0.40, "vs_index": 0.30, "mom_20d": 0.20, "beta": 0.10},
    "BEAR":    {"sharpe_20d": 0.50, "vs_index": 0.30, "inv_beta": 0.20},
}

# ── Sector map ───────────────────────────────────────────────────────────────
SECTOR_MAP: dict[str, str] = {
    # SP500 — Technology
    "AAPL": "Tech", "NVDA": "Tech", "MSFT": "Tech", "GOOGL": "Tech",
    "META": "Tech", "AVGO": "Tech", "AMD": "Tech", "CRM": "Tech",
    "ORCL": "Tech", "CSCO": "Tech", "QCOM": "Tech", "IBM": "Tech",
    "TXN": "Tech", "ACN": "Tech", "INTC": "Tech",
    # SP500 — Consumer (discretionary + staples)
    "AMZN": "Cons", "TSLA": "Cons", "NFLX": "Cons", "NKE": "Cons",
    "MCD": "Cons", "KO": "Cons", "PEP": "Cons", "WMT": "Cons",
    "HD": "Cons", "LOW": "Cons", "COST": "Cons", "PG": "Cons", "PM": "Cons",
    # SP500 — Healthcare
    "LLY": "Health", "UNH": "Health", "JNJ": "Health", "MRK": "Health",
    "ABBV": "Health", "TMO": "Health", "ABT": "Health", "DHR": "Health",
    "AMGN": "Health",
    # SP500 — Financials
    "JPM": "Fin", "V": "Fin", "MA": "Fin", "BAC": "Fin", "GS": "Fin", "SPGI": "Fin",
    # SP500 — Energy / Utilities
    "XOM": "Energy", "CVX": "Energy", "APA": "Energy", "VLO": "Energy",
    "DVN": "Energy", "LYB": "Chem", "NEE": "Util",
    "MU": "Tech",
    # SP500 — Industrials
    "HON": "Ind", "CAT": "Ind", "UPS": "Ind", "BA": "Ind",
    # Finland — OMXHLCPI
    "NOKIA.HE": "Tech", "FORTUM.HE": "Util", "SAMPO.HE": "Fin",
    "NESTE.HE": "Energy", "KNEBV.HE": "Ind", "WRT1V.HE": "Ind",
    "STERV.HE": "Mat", "OUT1V.HE": "Mat", "ELISA.HE": "Tel",
    "ORNBV.HE": "Health", "UPM.HE": "Mat", "METSO.HE": "Ind",
    # Sweden — OMXS30
    "ERIC-B.ST": "Tech", "VOLV-B.ST": "Ind", "ATCO-A.ST": "Ind",
    "SEB-A.ST": "Fin", "SWED-A.ST": "Fin", "INVE-B.ST": "Fin",
    "HM-B.ST": "Cons", "SHB-A.ST": "Fin", "ESSITY-B.ST": "Cons",
    "ABB.ST": "Ind", "SAND.ST": "Ind", "SKF-B.ST": "Ind",
    "ALFA.ST": "Ind", "TELIA.ST": "Tel", "BOL.ST": "Mat",
    "NIBE-B.ST": "Ind", "EVO.ST": "Cons", "SSAB-A.ST": "Mat",
    # Norway — OBX
    "EQNR.OL": "Energy", "DNB.OL": "Fin", "NHY.OL": "Mat",
    "TEL.OL": "Tel", "MOWI.OL": "Cons", "ORK.OL": "Cons",
    "YAR.OL": "Mat", "SCATC.OL": "Energy", "SUBC.OL": "Energy",
    "SALM.OL": "Cons", "RECSI.OL": "Energy",
    "KOG.OL": "Ind", "AKRBP.OL": "Energy",  # Kongsberg (defense/tech) + Aker BP (oil) — top OBX performers 2026
    # Denmark — OMXC25
    "NOVO-B.CO": "Health", "DSV.CO": "Ind", "ORSTED.CO": "Energy",
    "CARL-B.CO": "Cons", "GMAB.CO": "Health", "MAERSK-B.CO": "Ind",
    "COLO-B.CO": "Health", "GN.CO": "Health", "DEMANT.CO": "Health",
    "PNDORA.CO": "Cons", "ISS.CO": "Ind",
    # Baltic
    "LHV1T.TL": "Fin", "PRF1T.TL": "Cons", "TKM1T.TL": "Cons",
    "MRK1T.TL": "Ind", "ARC1T.TL": "RE", "TAL1T.TL": "Cons",
    "GRG1L.VS": "Mat", "APG1L.VS": "Cons", "VLP1L.VS": "Cons",
}

# ── Ticker universe ──────────────────────────────────────────────────────────
# yfinance ticker symbols per market
UNIVERSE: dict[str, list[str]] = {
    # United States — S&P 500 large caps
    "SP500": [
        "AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
        "JPM", "LLY", "UNH", "XOM", "V", "MA", "JNJ", "WMT", "PG", "HD",
        "MRK", "COST", "ABBV", "CVX", "CRM", "NFLX", "AMD", "BAC", "PEP",
        "KO", "TMO", "ORCL", "CSCO", "ACN", "MCD", "ABT", "TXN", "DHR",
        "NKE", "INTC", "PM", "NEE", "UPS", "LOW", "QCOM", "AMGN", "IBM",
        "GS", "CAT", "HON", "BA", "SPGI",
    ],
    # Finland — OMX Helsinki Large Cap (OMXHLCPI)
    "OMXHLCPI": [
        "NOKIA.HE", "FORTUM.HE", "SAMPO.HE", "NESTE.HE", "KNEBV.HE",
        "WRT1V.HE", "STERV.HE", "OUT1V.HE", "ELISA.HE",
        "ORNBV.HE", "UPM.HE", "METSO.HE",
    ],
    # Sweden — OMX Stockholm 30 (OMXS30)
    "OMXS30": [
        "ERIC-B.ST", "VOLV-B.ST", "ATCO-A.ST", "SEB-A.ST", "SWED-A.ST",
        "INVE-B.ST", "HM-B.ST", "SHB-A.ST", "ESSITY-B.ST", "ABB.ST",
        "SAND.ST", "SKF-B.ST", "ALFA.ST", "TELIA.ST", "BOL.ST",
        "NIBE-B.ST", "EVO.ST", "SSAB-A.ST",
    ],
    # Norway — OBX Index
    "OBX": [
        "EQNR.OL", "DNB.OL", "NHY.OL", "TEL.OL", "MOWI.OL",
        "ORK.OL", "YAR.OL", "SCATC.OL", "SUBC.OL",
        "SALM.OL", "RECSI.OL", "KOG.OL", "AKRBP.OL",
    ],
    # Denmark — OMX Copenhagen 25 (OMXC25)
    "OMXC25": [
        "NOVO-B.CO", "DSV.CO", "ORSTED.CO", "CARL-B.CO",  # CARL-B.CO: data still loads
        "GMAB.CO", "MAERSK-B.CO", "COLO-B.CO", "GN.CO", "DEMANT.CO",
        "PNDORA.CO", "ISS.CO",
    ],
    # Baltic Main List (Tallinn, Riga, Vilnius)
    "BALTIC": [
        "LHV1T.TL", "PRF1T.TL", "TKM1T.TL",
        "MRK1T.TL", "ARC1T.TL", "TAL1T.TL",
        "GRG1L.VS", "APG1L.VS", "VLP1L.VS",
    ],
}
