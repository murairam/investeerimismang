"""
Refresh and print the pre-game learning reports.

Usage:
    python pregame_review.py

Shows:
- Performance learning (win rate, alpha)
- Meta-learning (AI reasoning quality)
- Cost tracking (API spending)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.learning_report import generate_pregame_learning_report
from data.meta_learning import generate_meta_learning_report
from data.cost_tracker import get_total_cost


def main() -> None:
    print("\n" + "=" * 70)
    print("🦈 AlphaShark Pregame Review")
    print("=" * 70)

    # Performance Learning
    print("\n📊 Performance Learning Report")
    summary = generate_pregame_learning_report(target_date="2026-04-06")
    print(f"   Days left until live: {summary['days_left']}")
    print(f"   Average daily alpha: {summary['avg_alpha']:+.2%}")
    print(f"   Paper account return: {summary['paper_return']:+.2%}")
    print(f"   Max drawdown: {summary['max_drawdown']:.2%}")
    print(f"   Average turnover: {summary['avg_turnover']:.2%}")
    print(f"   📄 Full report: {summary['report_path']}")

    # Meta-Learning
    print("\n🧠 Meta-Learning Report (AI Self-Critique)")
    meta_summary = generate_meta_learning_report(target_date="2026-04-06")
    print(f"   Reasoning accuracy score: {meta_summary['accuracy_score']:.0%}")
    print(f"   Insights (what's working): {meta_summary['insights_count']}")
    print(f"   Biases detected (what's failing): {meta_summary['biases_count']}")
    print(f"   Alpha hit rate: {meta_summary['alpha_hit_rate']:.0%}")
    print(f"   📄 Full report: {meta_summary['report_path']}")

    if meta_summary['action_items']:
        print("\n   Action items for the AI:")
        for item in meta_summary['action_items'][:3]:
            print(f"   • {item}")

    # Cost Tracking
    print("\n💰 Cost Tracking")
    cost_summary = get_total_cost()
    print(f"   Total API cost: ${cost_summary['total_cost']:.4f}")
    print(f"   Total runs: {cost_summary['run_count']}")
    if cost_summary['run_count'] > 0:
        avg_cost = cost_summary['total_cost'] / cost_summary['run_count']
        print(f"   Average per run: ${avg_cost:.4f}")

    if cost_summary['daily_breakdown']:
        latest_date = max(cost_summary['daily_breakdown'].keys())
        latest_cost = cost_summary['daily_breakdown'][latest_date]
        print(f"   Latest run ({latest_date}): ${latest_cost:.4f}")

    print("\n" + "=" * 70)
    print("\n💡 Tip: Run 'python status.py' for a full project dashboard\n")


if __name__ == "__main__":
    main()