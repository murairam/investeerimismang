"""
Refresh and print the pre-game learning report.

Usage:
    python pregame_review.py
"""
from data.learning_report import generate_pregame_learning_report


def main() -> None:
    summary = generate_pregame_learning_report(target_date="2026-04-06")
    print("\nPre-game learning report updated.")
    print(f"Days left: {summary['days_left']}")
    print(f"Average daily alpha: {summary['avg_alpha']:+.2%}")
    print(f"Paper return: {summary['paper_return']:+.2%}")
    print(f"Max drawdown: {summary['max_drawdown']:.2%}")
    print(f"Average turnover: {summary['avg_turnover']:.2%}")
    print(f"Report: {summary['report_path']}\n")


if __name__ == "__main__":
    main()