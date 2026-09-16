"""Focused metadata-interface checks; no fitting or real outcome access."""
import unittest

from scripts.run_nba_gen1_rest_2026 import project_context


class NbaGen1Rest2026ContextTests(unittest.TestCase):
    def setUp(self):
        self.event = {"game_id": "nba-espn:game:123", "source_game_id": 123,
                      "game_date": "2025-12-16", "season_end": 2026,
                      "team_ids": ["UNIT_TEAM_A", "UNIT_TEAM_B"],
                      "classification": "NBA_CUP_FINAL_DATE_ONLY"}

    def test_known_source_alias_is_projected_without_mutating_evidence(self):
        result = project_context([self.event])[0]
        self.assertNotIn("source_game_id", result)
        self.assertEqual(self.event["source_game_id"], 123)
        self.assertEqual(result, {k: v for k, v in self.event.items() if k != "source_game_id"})
        self.assertEqual(project_context([result]), [result])

    def test_outcomes_and_unknown_fields_are_rejected_before_projection(self):
        for field in ("home_score", "outcome", "unknown_metadata"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                project_context([{**self.event, field: 100}])

    def test_mismatched_or_malformed_source_alias_fails(self):
        for value in (124, True, -1, "123"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                project_context([{**self.event, "source_game_id": value}])


if __name__ == "__main__":
    unittest.main()
