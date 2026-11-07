import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from replay_quality_audit import category_counts, merge_scenario_results  # noqa: E402


class QualityAuditTest(unittest.TestCase):
    def test_category_counts_distinguishes_complete_persisted_set_from_top20(self):
        rows = [
            *({"discovery_result_category": "actionable"} for _ in range(9)),
            *({"discovery_result_category": "review_required"} for _ in range(6)),
            *({"discovery_result_category": "excluded"} for _ in range(6)),
        ]
        self.assertEqual(category_counts(rows), {"actionable": 9, "review_required": 6, "excluded": 6})
        self.assertEqual(category_counts(rows[:20]), {"actionable": 9, "review_required": 6, "excluded": 5})

    def test_duplicate_posting_uses_best_scenario_result(self):
        job = {"application_priority_score": 0, "discovery_result_category": "excluded"}
        merged = merge_scenario_results(job, [
            {"scenario": "canada_remote", "application_priority_score": 0, "discovery_result_category": "excluded", "remote_search_eligible": "false"},
            {"scenario": "toronto_hybrid", "application_priority_score": 44, "discovery_result_category": "actionable", "remote_search_eligible": "unknown"},
        ])
        self.assertEqual(merged["application_priority_score"], 44)
        self.assertEqual(merged["discovery_result_category"], "actionable")
        self.assertEqual(merged["scenario_application_priority_scores"]["canada_remote"], 0)


if __name__ == "__main__":
    unittest.main()
