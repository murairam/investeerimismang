"""
Entry point — called by GitHub Actions (and usable locally).
"""
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

if sys.version_info < (3, 10):
    sys.exit(
        "ERROR: AlphaShark requires Python 3.10+ (project venv is recommended). "
        "Run with: '/Users/mari/Documents/my projects/investeerimismang/.venv/bin/python' main.py"
    )

# Fail fast with a clear error if required secrets are missing,
# before any agent is initialised or API calls are made.
_REQUIRED_ENV = ["OPENAI_API_KEY", "GEMINI_API_KEY", "DISCORD_WEBHOOK_URL"]
_missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
if _missing:
    sys.exit(f"ERROR: Missing required environment variables: {', '.join(_missing)}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
# yfinance logs ERROR for individual ticker failures inside batch downloads
# (e.g. TypeError on NoneType). Our retry/except handlers already deal with
# these gracefully — suppress the noise so the log stays readable.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

from orchestrator import AlphaSharkOrchestrator  # noqa: E402 (after dotenv)


def main() -> None:
    AlphaSharkOrchestrator().run()


if __name__ == "__main__":
    main()
