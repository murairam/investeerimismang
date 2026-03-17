# AlphaShark Setup Guide

Complete step-by-step guide to automate your daily trading agent.

---

## 🎯 Goal

By the end of this guide:
- ✅ GitHub Actions runs `python main.py` **automatically every weekday at 09:30 EEST**
- ✅ You receive a **Discord notification** with the AI's portfolio recommendation
- ✅ You have a **verification workflow** to ensure system accuracy
- ✅ The system **learns daily** from wins/losses until April 6

---

## Part 1: GitHub Actions Setup (5 minutes)

### Step 1: Verify Your GitHub Repository

```bash
# Check that your repo is connected
git remote -v

# Should show: git@github.com:murairam/investeerimismang.git
```

### Step 2: Add GitHub Secrets

1. Go to your repo on GitHub: https://github.com/murairam/investeerimismang
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** for each of these:

| Secret Name | Where to Get It |
|-------------|-----------------|
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| `GEMINI_API_KEY` | https://aistudio.google.com/app/apikey |
| `DISCORD_WEBHOOK_URL` | Discord → Server Settings → Integrations → Webhooks |

**How to create a Discord webhook:**
1. Open Discord, go to your server
2. Right-click the channel where you want notifications → **Edit Channel**
3. Go to **Integrations** → **Webhooks** → **New Webhook**
4. Copy the webhook URL
5. Paste it as `DISCORD_WEBHOOK_URL` in GitHub

### Step 3: Commit and Push Your Code

```bash
# Add all changes
gaa

# Commit with a message
gc -m "feat: add pregame learning mode and GitHub Actions automation"

# Push to GitHub
gp
```

### Step 4: Test the Workflow

**Option A: Wait for automatic run**
- The workflow runs automatically **Mon-Fri at 09:30 EEST** (06:30 UTC)

**Option B: Trigger it manually NOW (recommended for testing)**
1. Go to GitHub: https://github.com/murairam/investeerimismang/actions
2. Click **AlphaShark Daily Run** in the left sidebar
3. Click **Run workflow** → **Run workflow**
4. Watch it run (takes ~2-3 minutes)
5. Check Discord for the notification

---

## Part 2: Daily Verification Workflow

### ⚠️ Important: Game vs System Sync

The AI proposes a portfolio, but:
- **Before April 6**: It's virtual (paper trading only)
- **On/After April 6**: You must manually enter positions on the game website

### Verification Process (2 minutes daily)

**Every day after the automated run:**

1. **Check Discord** for the portfolio recommendation (arrives at 09:30 EEST)

2. **Before April 6 (Pregame)**:
   ```bash
   # Just review the learning report
   python pregame_review.py
   ```
   - No action needed — it's virtual training
   - Watch the learning metrics improve

3. **On/After April 6 (Live Game)**:

   **Step A: Update the game website**
   - Go to the Äripäev/SEB Investment Game website
   - Manually enter the positions from the Discord message
   - Submit before 10:00 EET cutoff

   **Step B: Verify system sync**
   ```bash
   python verify.py
   ```

   **What verify.py does:**
   - Shows what the system thinks you hold
   - Asks if it matches your actual game portfolio
   - If mismatched, lets you correct it manually

   **Example session:**
   ```
   AlphaShark — recorded portfolio (as of 2026-04-06)
   #   Ticker       Weight  Rationale
   ------------------------------------------------------------------
   1   NOKIA.HE       25.0%  Strong momentum and breakout
   2   FORTUM.HE      20.0%  High Sharpe ratio
   ...

   Does this match your actual game portfolio? (y = yes / n = no / e = edit)
   > y

   Portfolio confirmed. Record is up to date.
   ```

   **If you need to correct it:**
   ```
   > e

   Enter your actual game portfolio below.
   Format per line:  TICKER WEIGHT%   (e.g. NVDA 20)
   Empty line when done.

   > NOKIA.HE 25
   > FORTUM.HE 20
   > MAERSK-B.CO 18
   >

   Saved. The system will use this as the baseline for tomorrow.
   ```

---

## Part 3: Understanding the Learning System

### Files Updated Daily (Automatically)

| File | Purpose |
|------|---------|
| `portfolio_history.json` | Yesterday's decisions + P&L |
| `paper_account.json` | Virtual €10k account ledger |
| `PREGAME_LEARNING.md` | Win rate, best tickers, action items |
| `DAILY_LOG.md` | Human-readable decision diary |

### How the AI Learns

**Day 1** (today):
- AI sees market data, proposes portfolio
- System saves the decision

**Day 2** (tomorrow):
- AI sees yesterday's P&L: MAERSK +3.2%, NHY -0.8%
- Learns: "MAERSK is working, keep it"

**Day 5**:
- AI sees 5-day pattern: MAERSK won 4/5 days
- Learns: "MAERSK is a consistent winner, increase conviction"

**Day 20** (April 6):
- AI has 20 days of Nordic/Baltic stock patterns
- Knows which tickers work in this regime
- Knows optimal position sizing
- **System switches to LIVE mode** with parameter freeze

---

## Part 4: Daily Routine

### Pregame Mode (Now → April 6)

**Fully automated:**
```
09:30 EEST: GitHub Actions runs main.py
            ↓ AI proposes portfolio
            ↓ Updates paper account
            ↓ Saves learning data
            ↓ Sends Discord notification

You: Check Discord, review PREGAME_LEARNING.md (optional)
```

**Optional daily:**
```bash
# Refresh the learning summary
python pregame_review.py
```

### Live Mode (April 6 → June 19)

**Semi-automated (requires your action):**
```
09:30 EEST: GitHub Actions runs main.py
            ↓ AI proposes portfolio based on 20 days of learning
            ↓ Sends Discord notification with ⚠️ ACTION REQUIRED

09:35-09:55: YOU manually enter positions on game website

09:55: Run verification:
       python verify.py

10:00: Game submission deadline
```

---

## Part 5: Troubleshooting

### GitHub Actions not running?

1. Check **Actions** tab: https://github.com/murairam/investeerimismang/actions
2. Look for error messages in the workflow logs
3. Common issues:
   - Missing API key secrets → Add them in Settings → Secrets
   - API quota exceeded → Check OpenAI/Gemini billing

### Discord not receiving messages?

1. Test the webhook manually:
   ```bash
   curl -X POST "$DISCORD_WEBHOOK_URL" \
     -H "Content-Type: application/json" \
     -d '{"content": "AlphaShark test message"}'
   ```
2. If it fails, regenerate the webhook in Discord

### Portfolio verification out of sync?

1. Run `python verify.py`
2. Choose `e` to manually edit
3. Enter your actual game positions
4. System will use this as the baseline tomorrow

---

## Part 6: Key Commands Reference

```bash
# Daily commands
python main.py              # Run the full pipeline (GitHub does this automatically)
python pregame_review.py    # Refresh learning summary (pregame only)
python verify.py            # Verify portfolio sync (live mode only)

# Git commands (if you make changes)
gs                          # Check status
gaa                         # Stage all changes
gc -m "message"             # Commit
gp                          # Push to GitHub

# View files
cat PREGAME_LEARNING.md     # Learning report
cat DAILY_LOG.md | tail -50 # Recent decisions
cat paper_account.json      # Virtual account state
```

---

## ✅ Setup Complete!

**Next steps:**
1. ✅ Push your code to GitHub
2. ✅ Add the 3 secrets in GitHub Settings
3. ✅ Trigger a manual workflow run to test
4. ✅ Confirm Discord notification works
5. ✅ Run daily until April 6 to build learning data
6. ✅ On April 6, switch to the live workflow (update game + verify)

**Questions?** Check the main [README.md](README.md) or run `python main.py` locally to test.
