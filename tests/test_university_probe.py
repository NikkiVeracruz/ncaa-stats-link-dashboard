import unittest
from university_probe import index,resolve,identity,host
class TestUniversity(unittest.TestCase):
    def test_no_ambiguous_school(self):
        idx=index([{"key":"a","name":"Same"},{"key":"b","name":"Same"}])
        self.assertIsNone(resolve({"location":"Same"},idx))
    def test_no_substring(self):
        self.assertIsNone(resolve({"location":"Montana"},index([{"key":"montana_state","name":"Montana State"}])))
    def test_domain(self):
        self.assertEqual(host("https://www.example.edu/path"),"example.edu")
        self.assertNotEqual(host("https://example.edu.evil.com"),"example.edu")
    def test_identity(self):
        g={"completed":True,"date_et":"2026-11-21","sports":["FBS"],"away_score":28,"home_score":31}
        r={"sport":"FBS","date":"2026-11-21","teams":[["Ohio State",28],["Nebraska",31]]}
        names={"away":{"ohiostate"},"home":{"nebraska"}}
        self.assertTrue(identity(g,r,names))
        self.assertFalse(identity(dict(g,home_score=30),r,names))
        self.assertFalse(identity(dict(g,completed=False),r,names))
        self.assertFalse(identity(dict(g,date_et="2026-11-22"),r,names))

    def test_exact_aliases(self):
        idx=index([{"key":"texas_san_antonio","name":"University of Texas at San Antonio"},{"key":"alabama_birmingham","name":"University of Alabama at Birmingham"}])
        self.assertEqual(resolve({"location":"UTSA"},idx),"texas_san_antonio")
        self.assertEqual(resolve({"location":"UAB"},idx),"alabama_birmingham")
        self.assertIsNone(resolve({"location":"UTSA","displayName":"UAB Blazers"},idx))
