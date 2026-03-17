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
    "min_total_weight": 0.75,  # 75% — game allows max 25% cash (earns no return)
}

# Preferred stock-count bands by market regime (still bounded by GAME_CONSTRAINTS)
POSITION_TARGETS_BY_REGIME = {
    "BULL": {"min_stocks": 6, "max_stocks": 8},
    "NEUTRAL": {"min_stocks": 8, "max_stocks": 10},
    "BEAR": {"min_stocks": 10, "max_stocks": 12},
}

# Cash policy (used when proposed allocation is below 100%)
CASH_POLICY = {
    "min_cash_gap": 0.01,                 # ignore tiny residual cash below 1%
    "high_vix_threshold": 26.0,           # keep more cash in high-volatility regimes
    "weak_benchmark_threshold": -0.02,    # if benchmark momentum is weaker than -2%
    "strong_alpha_threshold": 0.03,       # deploy cash when selected names show strong alpha
}

# ── Signal parameters ────────────────────────────────────────────────────────
MOMENTUM_WINDOW = 20        # trading days for momentum calculation
BETA_WINDOW = 60            # trading days for beta calculation
BETA_BENCHMARK = "^GSPC"    # S&P 500 as benchmark
TOP_N_CANDIDATES = 30       # screened stocks passed to Claude
RSI_WINDOW = 14             # RSI lookback period
MOM_SHORT = 5               # short-term momentum window (days)
MOM_LONG = 60               # long-term momentum window (days)
SMA_REGIME_WINDOW = 200     # days for market regime SMA
REGIME_THRESHOLD = 0.02     # 2% band for BULL/BEAR classification
SP500_MARKET_CAP = 15       # max SP500 candidates in top-30
OTHER_MARKET_CAP = 5        # max candidates per other market in top-30
CORR_WINDOW = 60            # days for correlation filter
CORR_THRESHOLD = 0.85       # correlation above this → keep higher Sharpe

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
        "SALM.OL", "RECSI.OL",
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
