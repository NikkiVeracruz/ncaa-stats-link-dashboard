import json
import unittest
from datetime import date
from unittest.mock import patch

from reliability_probe import snapshot
from ncaa_poc import process_day


class ReliabilityTests(unittest.TestCase):
    def test_window_and_release_cache(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return b"payload"
        def process(day, fetcher):
            self.assertEqual(fetcher("release"), b"payload")
            fetcher(str(day))
            return {"probe_date_et": str(day), "source_errors": []}
        with patch("reliability_probe.process_day", side_effect=process):
            result = snapshot(date(2026, 11, 23), 3, fetcher=fetch)
        self.assertEqual(calls.count("release"), 1)
        self.assertEqual([r["probe_date_et"] for r in result["reports"]],
                         ["2026-11-21", "2026-11-22", "2026-11-23"])
        self.assertTrue(result["read_only"])

    def test_bounds(self):
        for days in (0, 15):
            with self.assertRaises(ValueError):
                snapshot(date(2026, 11, 23), days)

    def test_errors_preserved(self):
        with patch("reliability_probe.process_day", return_value={"source_errors": ["bad"]}):
            self.assertEqual(snapshot(date(2026, 11, 23), 2)["source_errors"], ["bad", "bad"])

    def test_malformed_event_is_reported(self):
        def fetch(url):
            if "scoreboard" in url:
                return json.dumps({"events": [{"id": "invalid"}]}).encode()
            raise OSError("unavailable mapping")
        result = process_day(date(2026, 11, 23), fetcher=fetch)
        self.assertEqual(result["unique_games"], 0)
        self.assertEqual(result["data_sources"]["FBS"]["rejected"], 1)
        self.assertTrue(any("malformed events" in e for e in result["source_errors"]))


if __name__ == "__main__":
    unittest.main()
