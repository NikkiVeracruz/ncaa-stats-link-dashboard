import unittest
from upstream_probe import key, index_rows, candidate


class UpstreamTests(unittest.TestCase):
    def test_order_independent_exact_match(self):
        rows = [
            {"date": "2026-11-21", "espn_team_id": "123", "opponent_espn_team_id": "456", "contest_id": "987"},
            {"date": "2026-11-21", "espn_team_id": "456", "opponent_espn_team_id": "123", "contest_id": "987"},
        ]
        idx = index_rows(rows, "date")
        self.assertEqual(candidate(idx, "2026-11-21", "456", "123"), "987")
        self.assertIsNone(candidate(idx, "2026-11-22", "456", "123"))
        self.assertIsNone(candidate(idx, "2026-11-21", "456", "789"))

    def test_ambiguous_ids_rejected(self):
        rows = [{"date": "2026-11-21", "espn_team_id": "123", "opponent_espn_team_id": "456", "contest_id": x} for x in ("987", "988")]
        self.assertIsNone(candidate(index_rows(rows, "date"), "2026-11-21", "123", "456"))

    def test_missing_and_invalid_values_rejected(self):
        self.assertIsNone(key("2026-11-21", None, "456"))
        self.assertIsNone(key("invalid", "123", "456"))
        self.assertIsNone(key("2026-11-21", "123", "123"))
