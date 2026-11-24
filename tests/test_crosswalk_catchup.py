import unittest
from crosswalk_catchup import compare
R={"sport":"FBS","date":"2026-11-21","id":"100","teams":[{"name":"Ohio St.","score":28},{"name":"Nebraska","score":31}]}
G={"espn_game_id":"200","date_et":R["date"],"sports":["FBS"],"completed":True,"away_score":28,"home_score":31,"link_status":"id_matched_page_not_verified","ncaa_contest_id":"100"}
N={("FBS","200"):{"away":{"ohiostate"},"home":{"nebraska"}}}
class ReferenceTests(unittest.TestCase):
    def check(self,game,status):
        self.assertEqual(compare([R],[{"games":[game]}],N)[0]["status"],status)
    def test_correct(self): self.check(G,"correct_id")
    def test_wrong_id(self): self.check(dict(G,ncaa_contest_id="999"),"wrong_id")
    def test_pending(self): self.check(dict(G,link_status="no_contest_id"),"no_contest_id")
    def test_wrong_date(self): self.check(dict(G,date_et="2026-11-22"),"identity_unmatched")
    def test_wrong_score(self): self.check(dict(G,away_score=29),"identity_unmatched")
    def test_live(self): self.check(dict(G,completed=False),"identity_unmatched")
    def test_wrong_sport(self): self.check(dict(G,sports=["MBB"]),"identity_unmatched")
    def test_duplicate(self):
        self.assertEqual(compare([R],[{"games":[G,G]}],N)[0]["status"],"correct_id")
