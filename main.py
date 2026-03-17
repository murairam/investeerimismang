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

from orchestrator import AlphaSharkOrchestrator  # noqa: E402 (after dotenv)


def main() -> None:
    AlphaSharkOrchestrator().run()


if __name__ == "__main__":
    main()
