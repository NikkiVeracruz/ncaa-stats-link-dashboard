import unittest
from alternate_assets import inspect
class TestAssets(unittest.TestCase):
    def test_same_date_only_and_unique_ids(self):
        rows=[{"game_date":"2026-11-21","contest_id":"123","espn_game_id":"456"}]*2
        refs=[{"sport":"FBS","date":"2026-11-21","id":"123"},{"sport":"FCS","date":"2026-11-22","id":"123"}]
        r,m=inspect(rows,refs)
        self.assertEqual(r["saved_reference_matches"],{"FBS":1})
        self.assertEqual(r["dates"],{"2026-11-21":1})
        self.assertEqual(m["456"],{"123"})
