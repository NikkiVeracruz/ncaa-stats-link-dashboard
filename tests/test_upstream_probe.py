import unittest
from datetime import date
from upstream_probe import key, index_rows, candidate, normalize_date, index_football, inspect_rows, unique, team_crosswalk


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

    def test_explicit_date_formats(self):
        for value in ("11/21/2026", "11/21/26", "11/21/2026 07:30 PM", "11/21/2026 TBA", "20261121", date(2026, 11, 21), "2026-11-21T00:00:00Z"):
            self.assertEqual(normalize_date(value), "2026-11-21")
        self.assertIsNone(normalize_date("not a date"))

    def test_direct_football_match_and_conflict(self):
        rows = [{"date": "11/21/2026", "espn_game_id": "401234567", "contest_id": "987"}]
        idx = index_football(rows, "date")
        self.assertEqual(unique(idx[("2026-11-21", "401234567")]), "987")
        self.assertIsNone(unique(idx.get(("2026-11-22", "401234567"), set())))
        rows.append(dict(rows[0], contest_id="988"))
        self.assertIsNone(unique(index_football(rows, "date")[("2026-11-21", "401234567")]))

    def test_schedule_and_contest_dates_independent_of_join_keys(self):
        rows = [{"game_date": "11/21/2026", "contest_id": "987", "espn_team_id": None, "opponent_espn_team_id": None}]
        stats = inspect_rows(rows, "game_date", "mbb")
        self.assertEqual(stats["latest_contest_date"], "2026-11-21")
        self.assertEqual(stats["valid_fields"]["espn_team_id"], 0)
        self.assertFalse(index_rows(rows, "game_date"))

    def test_season_specific_crosswalk_and_conflicting_direct_id(self):
        rows = [{"season":"2026-27","ncaa_team_id":"10","espn_team_id":"123"},
                {"season":"2026-27","ncaa_team_id":"20","espn_team_id":"456"},
                {"season":"2025-26","ncaa_team_id":"10","espn_team_id":"777"},
                {"season":"2026-27","ncaa_team_id":"30","espn_team_id":"900"},
                {"season":"2026-27","ncaa_team_id":"30","espn_team_id":"901"}]
        mapping = team_crosswalk(rows, 2027)
        self.assertEqual(mapping, {"10":"123","20":"456"})
        game = {"game_date":"11/21/2026 07:30 PM","team_id":"10","opponent_id":"20","contest_id":"987"}
        self.assertEqual(candidate(index_rows([game],"game_date",mapping),"2026-11-21","123","456"),"987")
        self.assertFalse(index_rows([dict(game,espn_team_id="555")],"game_date",mapping))
