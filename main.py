"""
Entry point — called by GitHub Actions (and usable locally).
"""
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

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
