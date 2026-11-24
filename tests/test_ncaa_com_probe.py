import unittest
from ncaa_com_probe import compare

REF=[{"id":"123","date":"2026-11-21","teams":[{"name":"Alpha","score":31},{"name":"Beta","score":29}]}]
def game(id="123",score="31",day="2026-11-21",state="final"):
    return {"game":{"gameID":id,"startDate":day,"gameState":state,
      "away":{"names":{"short":"Beta"},"score":"29"},
      "home":{"names":{"short":"Alpha"},"score":score}}}

class Comparison(unittest.TestCase):
    def check(self,games,status):
        self.assertEqual(compare(REF,{"games":games})["results"],{status:1})
    def test_equal(self): self.check([game()],"equal")
    def test_different(self): self.check([game("999")],"different")
    def test_wrong_score(self): self.check([game(score="30")],"unmatched")
    def test_wrong_day(self): self.check([game(day="2026-11-22")],"unmatched")
    def test_not_final(self): self.check([game(state="live")],"unmatched")
    def test_duplicate(self): self.check([game(),game()],"ambiguous")
    def test_invalid_id(self): self.check([game(id="abc")],"unmatched")
    def test_empty(self):
        with self.assertRaises(ValueError): compare(REF,{"games":[]})
