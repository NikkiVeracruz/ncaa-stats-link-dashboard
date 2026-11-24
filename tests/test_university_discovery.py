import copy
import unittest
from datetime import datetime, timedelta
from urllib.error import HTTPError
from unittest.mock import patch

from university_discovery import eligible, enrich, acquire, SOURCE_NAME

NOW = datetime.fromisoformat("2026-11-24T14:00:00+00:00")
REPORT = {"kind": "pdf_box_score", "url": "https://storage.googleapis.com/vucommodores-prod/example.pdf",
          "school": "Vanderbilt University", "side": "home", "verification": "automatic_final_pdf_identity"}


def fixture():
    g = {"key": "wbb:401913059", "sports": ["WBB"], "date_et": "2026-11-23",
         "completed": True, "final_seen_at": "2026-11-24T02:51:30+00:00",
         "school_keys": {"home": "vanderbilt", "away": "arizona"},
         "team_ids": {"home": "238", "away": "12"},
         "team_names": {"home": ["vanderbilt"], "away": ["arizona"]},
         "home_score": 93, "away_score": 62, "reports": []}
    return {"archive_start": "2026-11-23", "current": [g], "archive": [copy.deepcopy(g)]}


class UniversityDiscoveryTests(unittest.TestCase):
    def test_verified_link_in_both_views_preserves_game(self):
        feed = fixture()
        before = copy.deepcopy(feed["archive"][0])
        self.assertEqual(enrich(feed, NOW, lambda g, side: REPORT), REPORT)
        self.assertEqual(feed["current"][0]["reports"], [REPORT])
        self.assertEqual(feed["archive"][0]["reports"], [REPORT])
        self.assertEqual({k:v for k,v in feed["archive"][0].items() if k != "reports"},
                         {k:v for k,v in before.items() if k != "reports"})
        self.assertEqual(feed["optional_discovery_source"], SOURCE_NAME)
        self.assertFalse(eligible(feed, NOW + timedelta(hours=1)))

    def test_no_result_retries_only_in_next_slot(self):
        feed = fixture()
        self.assertIsNone(enrich(feed, NOW, lambda g, side: None))
        self.assertFalse(eligible(feed, NOW + timedelta(minutes=1)))
        self.assertTrue(eligible(feed, NOW + timedelta(hours=1)))

    def test_not_eligible_outside_24h_or_before_cutoff(self):
        feed = fixture()
        self.assertFalse(eligible(feed, NOW + timedelta(hours=24)))
        feed["archive_start"] = "2026-11-24"
        self.assertFalse(eligible(feed, NOW))

    def test_other_schools_sports_and_incomplete_games_skipped(self):
        for change in ({"sports":["MBB"]}, {"completed":False},
                       {"school_keys":{"home":"other","away":"arizona"}}):
            feed = fixture()
            for g in feed["current"] + feed["archive"]:
                g.update(change)
            self.assertFalse(eligible(feed, NOW))

    def test_ambiguous_same_day_matchup_skipped(self):
        feed = fixture()
        feed["archive"].append(dict(feed["archive"][0], key="wbb:other"))
        self.assertFalse(eligible(feed, NOW))

    def test_access_denial_blocks_future_requests(self):
        feed = fixture()
        def deny(g, side):
            raise HTTPError("https://vucommodores.com", 403, "Forbidden", {}, None)
        self.assertIsNone(enrich(feed, NOW, deny))
        self.assertTrue(feed["university_discovery"]["blocked"])
        self.assertFalse(eligible(feed, NOW + timedelta(hours=1)))
        self.assertFalse(feed["archive"][0]["reports"])

    def test_temporary_failure_preserves_game_and_retries_next_slot(self):
        feed = fixture()
        def fail(g, side):
            raise HTTPError("https://vucommodores.com", 503, "Unavailable", {}, None)
        self.assertIsNone(enrich(feed, NOW, fail))
        self.assertFalse(feed["university_discovery"].get("blocked", False))
        self.assertTrue(eligible(feed, NOW + timedelta(hours=1)))
        self.assertEqual(feed["archive"][0]["home_score"], 93)

    def test_invalid_saved_state_disables_only_optional_source(self):
        feed = fixture()
        feed["university_discovery"] = "invalid"
        self.assertIsNone(enrich(feed, NOW))
        self.assertTrue(feed["university_discovery"]["blocked"])
        self.assertEqual(len(feed["archive"]), 1)

    @patch("university_discovery.shutil.which", return_value="/usr/bin/pdftotext")
    @patch("university_discovery.get_pdf", return_value="Official Basketball Box Score - Final 2026-27 Women's Basketball 11/23/26 Vanderbilt - 93 Record: 6-1 Arizona - 62 Record: 4-2")
    @patch("university_discovery.get")
    def test_acquisition_uses_published_links_and_exact_pdf_identity(self, get, pdf, tool):
        get.side_effect = [
            "User-agent: *\nDisallow:\n",
            "<h1>2026-27 Women's Basketball Schedule</h1><div><span>Nov 23</span><span>Arizona</span><span>Win 93-62</span><a href='/documents/control.pdf'>Box Score (PDF)</a></div>",
            "<a href='https://storage.googleapis.com/vucommodores-prod/control.pdf'>Download PDF</a>",
        ]
        result = acquire(fixture()["archive"][0], "home")
        self.assertEqual(result["url"], "https://storage.googleapis.com/vucommodores-prod/control.pdf")
        self.assertEqual(result["verification"], "automatic_final_pdf_identity")

if __name__ == "__main__":
    unittest.main()
