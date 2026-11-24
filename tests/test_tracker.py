import json, tempfile, unittest
from datetime import date,datetime,timezone
from pathlib import Path
from tracker import directory,from_event,merge_game,make_feed,school_link,write_feed,collect
D=date(2026,11,23)
def event(state="post",status="STATUS_FINAL",completed=True,score=31):
    return {"id":"123","date":"2026-11-23T18:00:00Z","status":{"type":{"state":state,"name":status,"completed":completed},"displayClock":"5:13","period":2},"competitions":[{"neutralSite":False,"competitors":[{"homeAway":"home","team":{"id":"1","displayName":"Nebraska Cornhuskers","location":"Nebraska"},"score":str(score)},{"homeAway":"away","team":{"id":"2","displayName":"Ohio State Buckeyes","location":"Ohio State"},"score":"28"}]}]}
class TrackerTests(unittest.TestCase):
    def setUp(self):self.idx,self.rows=directory()
    def game(self,e=None,group="FBS",overrides=[]):return from_event(e or event(),group,self.idx,self.rows,overrides)
    def test_final(self):
        g=self.game();self.assertTrue(g["completed"]);self.assertEqual(g["schools"]["home"]["schedule_shortcut"],"https://huskers.com/sports/football/schedule");self.assertFalse(g["reports"])
    def test_pre_scores_blank(self):
        g=self.game(event("pre","STATUS_SCHEDULED",False));self.assertIsNone(g["home_score"]);self.assertFalse(g["completed"])
    def test_live(self):
        g=self.game(event("in","STATUS_IN_PROGRESS",False));self.assertEqual(g["clock"],"5:13");self.assertFalse(g["completed"])
    def test_cancel(self):
        self.assertFalse(self.game(event("post","STATUS_CANCELED",True))["completed"])
    def test_crossover(self):
        g=merge_game(self.game(),self.game(group="FCS"));self.assertEqual(set(g["sports"]),{"FBS","FCS"})
    def test_conflict(self):
        with self.assertRaises(ValueError):merge_game(self.game(),self.game(event(score=32)))
    def test_archive_forward_only(self):
        g=self.game();old=dict(g,key="football:321",date_et="2026-11-22")
        result=make_feed({g["key"]:g,old["key"]:old},{},D,D,datetime.now(timezone.utc))
        self.assertEqual(len(result["current"]),2);self.assertEqual(len(result["archive"]),1)
    def test_archive_no_link_required(self):
        g=self.game();out=make_feed({g["key"]:g},{},D,D,datetime.now(timezone.utc));self.assertEqual(out["archive"][0]["reports"],[])
    def test_cutoff_fixed(self):
        with self.assertRaises(ValueError):make_feed({},{"archive_start":"2026-11-22"},D,D,datetime.now(timezone.utc))
    def test_invalid_feed(self):
        with self.assertRaises(ValueError):collect([D],self.idx,self.rows,[],lambda _:b'{"not_events":[]}')
    def test_reviewed_link(self):
        r={"espn_game_id":"123","school":"nebraska","sport":"FBS","date":"2026-11-23","teams":[["Nebraska",31],["Ohio State",28]],"reviewed":True,"report":"box_score","url":"https://huskers.com/boxscore/123"}
        self.assertEqual(len(self.game(overrides=[r])["reports"]),1)
        self.assertEqual(self.game(overrides=[dict(r,url="https://huskers.com.evil.com/x")])["reports"],[])
        self.assertEqual(self.game(overrides=[dict(r,reviewed=False)])["reports"],[])
    def test_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"feed.json";write_feed(p,{"archive":[]});self.assertEqual(json.loads(p.read_text()),{"archive":[]})
