# AlphaShark — Daily Portfolio Log

Each entry is written automatically after the daily run.

---
 Tier 2 — Medium impact

  Devil's advocate 4th agent — a second free Gemini call with the opposite mandate: "Find the strongest argument against each of
   the top 5 picks. Why might they fail?" The risk manager reads both the proposal and the counterarguments before synthesising.
   Costs nothing (free Gemini tier), forces the AI to pressure-test its own picks.

  Signal regression learning — after ~20 runs, compute which signals actually predicted next-day returns in our historical data.
   Output as: "vol_ratio was the best predictor (0.68 correlation), RSI was noise (0.12 correlation)". Inject as signal weights
  so agents know which columns to trust most.

  pytrends (Google Search Trends) — free Python library, zero API cost. High Google search interest for a stock = retail
  crowding = the move is already priced in. Contrarian signal. Especially useful for deciding between two otherwise equal
  candidates.

  Tier 3 — Higher effort, very high impact


  Options implied volatility — yfinance provides free options chains for US stocks. High IV = market expects a big move (could
  be earnings, could be news). Compare IV to historical vol (IV rank) to find cheap vs expensive options as a signal.