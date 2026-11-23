"""Read-only NCAA contest link probe regression tests (no network)."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ncaa_poc import (clean_id, parse_event, process_day, read_mapping,
                      release_name, scoreboard_url, season_for)


def event(game_id, home="Home University", away="Away College",
          timestamp="2026-11-24T00:30:00Z"):
    return {
        "id": game_id, "date": timestamp,
        "status": {"type": {"name": "STATUS_FINAL", "completed": True}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "score": "72", "team": {"displayName": home}},
            {"homeAway": "away", "score": "68", "team": {"displayName": away}},
        ]}],
    }


def fixture_dir(root, *, football=None, mbb=None, wbb=None, groups=None):
    (root / "football_mapping.csv").write_text(
        football if football is not None else "espn_game_id,contest_id\n")
    (root / "mbb_mapping.csv").write_text(
        mbb if mbb is not None else "espn_game_id,ncaa_contest_id\n")
    (root / "wbb_mapping.csv").write_text(
        wbb if wbb is not None else "espn_game_id,ncaa_contest_id\n")
    groups = groups or {}
    for league in ("FBS", "FCS", "MBB", "WBB"):
        (root / f"{league}_scoreboard.json").write_text(
            json.dumps({"events": groups.get(league, [])}))


class NCAAProofOfConceptTests(unittest.TestCase):
    def test_seasons(self):
        self.assertEqual(season_for("football", date(2026, 11, 23)), 2026)
        self.assertEqual(season_for("football", date(2027, 1, 1)), 2026)
        self.assertEqual(season_for("mbb", date(2026, 11, 23)), 2027)
        self.assertEqual(season_for("wbb", date(2027, 3, 1)), 2027)

    def test_sources_are_separate_and_bounded(self):
        self.assertEqual(release_name("football", 2026),
                         "ncaa_mfb_schedule/ncaa_mfb_schedule_2026.csv.gz")
        self.assertEqual(release_name("mbb", 2027),
                         "mbb_crosswalk/mbb_schedule_crosswalk_2027.csv")
        self.assertIn("groups=80", scoreboard_url("football/college-football", 80, date(2026, 11, 23)))
        self.assertNotIn("stats.ncaa.org", scoreboard_url("football/college-football", 80, date(2026, 11, 23)))

    def test_ids_are_numeric_without_guesswork(self):
        self.assertEqual(clean_id("123.0"), "123")
        for value in ("", "0", "0012", "nan", "23-10", "www.example/a", "2e7", "-7", "1/2"):
            self.assertIsNone(clean_id(value), value)

    def test_crosswalk_deduplicates_and_identifies_conflicts(self):
        sample = b"espn_game_id,contest_id\n401234567,600001\n401234567,600001\n401234568,600002\n401234568,600003\n"
        mapping, report = read_mapping(sample, compressed=False, sport="football")
        self.assertEqual(mapping["401234567"], {"600001"})
        self.assertEqual(report["ambiguous_espn_ids"], 1)

    def test_missing_schema_is_error_not_silent_empty_dataset(self):
        with self.assertRaisesRegex(ValueError, "Required columns"):
            read_mapping(b"espn_game_id,wrong_id\n1,2\n",
                         compressed=False, sport="mbb")

    def test_eastern_date_and_no_player_statistics(self):
        result = parse_event(event("401234567"), "FBS")
        self.assertEqual(result["date_et"], "2026-11-23")
        self.assertTrue(result["completed"])
        self.assertNotIn("player_stats", result)
        self.assertNotIn("participation", result)

    def test_four_groups_duplicate_fbs_fcs_and_unverified_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture_dir(root,
                football="espn_game_id,contest_id\n401234567,600001\n401234568,600002\n401234570,600004\n401234570,600005\n",
                mbb="espn_game_id,ncaa_contest_id\n401234569,700001\n",
                wbb="espn_game_id,ncaa_contest_id\n401234571,800001\n",
                groups={
                    "FBS": [event("401234567"), event("401234568")],
                    "FCS": [event("401234568"), event("401234570")],
                    "MBB": [event("401234569"), event("401234572")],
                    "WBB": [event("401234571")],
                })
            results = process_day(date(2026, 11, 23), offline=root)
            self.assertEqual(results["unique_games"], 6)
            self.assertFalse(results["source_errors"])
            self.assertFalse(results["ncaa_stats_pages_verified"])
            lookup = {row["espn_game_id"]: row for row in results["games"]}
            self.assertEqual(lookup["401234568"]["sports"], ["FBS", "FCS"])
            self.assertEqual(lookup["401234567"]["ncaa_stats_url"],
                             "https://stats.ncaa.org/contests/600001/box_score")
            self.assertEqual(lookup["401234567"]["link_status"],
                             "id_matched_page_not_verified")
            self.assertEqual(lookup["401234570"]["link_status"], "ambiguous_contest_id")
            self.assertNotIn("ncaa_stats_url", lookup["401234570"])
            self.assertEqual(lookup["401234572"]["link_status"], "no_contest_id")
            self.assertNotIn("ncaa_stats_url", lookup["401234572"])

    def test_missing_source_does_not_generate_a_link(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture_dir(root, groups={"FBS": [event("401234567")]})
            (root / "football_mapping.csv").unlink()
            report = process_day(date(2026, 11, 23), offline=root)
            self.assertEqual(report["games"][0]["link_status"], "source_unavailable")
            self.assertNotIn("ncaa_stats_url", report["games"][0])
            self.assertTrue(report["source_errors"])

    def test_cross_sport_id_conflict_suppresses_url(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture_dir(root,
                football="espn_game_id,contest_id\n401234567,600001\n",
                mbb="espn_game_id,ncaa_contest_id\n401234567,700001\n",
                groups={"FBS": [event("401234567")], "MBB": [event("401234567")]})
            report = process_day(date(2026, 11, 23), offline=root)
            self.assertEqual(report["games"][0]["link_status"], "cross_sport_conflict")
            self.assertNotIn("ncaa_stats_url", report["games"][0])


if __name__ == "__main__":
    unittest.main()
