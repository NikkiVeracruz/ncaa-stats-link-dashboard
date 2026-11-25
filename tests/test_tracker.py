import json, tempfile, unittest
from datetime import date,datetime,timezone,timedelta
from pathlib import Path
from link_enrichment import slot,apply_links
from tracker import directory,from_event,merge_game,make_feed,school_link,write_feed,collect,display_day,window_days,requested_days
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

    def test_rollover_thursday(self):
        before=datetime(2026,11,26,7,59,tzinfo=timezone.utc)
        after=before+timedelta(minutes=1)
        self.assertIn(date(2026,11,21),window_days("FBS",display_day(before)))
        self.assertNotIn(date(2026,11,21),window_days("FBS",display_day(after)))
        self.assertIn(date(2026,11,28),window_days("FCS",display_day(after)))
    def test_basketball_rollover(self):
        before=datetime(2026,11,24,7,59,tzinfo=timezone.utc)
        after=before+timedelta(minutes=1)
        self.assertEqual(window_days("MBB",display_day(before)),{date(2026,11,22),D,date(2026,11,24)})
        self.assertEqual(window_days("WBB",display_day(after)),{D,date(2026,11,24),date(2026,11,25)})
    def test_due_slots(self):
        start=datetime(2026,11,23,21,tzinfo=timezone.utc)
        g=dict(self.game(),final_seen_at=start.isoformat())
        for m,expected in [(0,0),(4,0),(5,5),(59,55),(60,60),(74,60),(75,75),(239,225),(240,240),(299,240),(300,300),(1439,1380),(1440,None)]:
            self.assertEqual(slot(g,start+timedelta(minutes=m)),None if expected is None else ("post",expected))
    def test_pregame_center_and_expiry(self):
        now=datetime(2026,11,23,16,tzinfo=timezone.utc)
        g=self.game(event("pre","STATUS_SCHEDULED",False))
        r={"kind":"game_center","sport":"FBS","date":D.isoformat(),"school":"nebraska","teams":[["Nebraska",None],["Ohio State",None]],"url":"https://huskers.com/game-center/123","reviewed":True}
        apply_links(g,[r],now);self.assertEqual(g["reports"][0]["kind"],"game_center")
        self.assertEqual(len(g["reports"]),1)
        apply_links(g,[r],now+timedelta(hours=1));self.assertEqual(len(g["reports"]),1)
        f=self.game();f["final_seen_at"]=now.isoformat()
        apply_links(f,[r],now+timedelta(hours=24));self.assertEqual(f["reports"],[])
    def test_archive_enrichment_after_rollover(self):
        start=datetime(2026,11,25,23,tzinfo=timezone.utc)
        g=self.game();g["date_et"]="2026-11-25";g["start_utc"]="2026-11-25T18:00:00Z"
        r={"kind":"pdf_box_score","sport":"FBS","date":"2026-11-25","school":"nebraska","teams":[["Nebraska",31],["Ohio State",28]],"url":"https://cdn.example.org/report.pdf","parent_url":"https://huskers.com/game-center/123","reviewed":True}
        first=make_feed({g["key"]:g},{},D,date(2026,11,25),start)
        nxt=make_feed({},first,D,date(2026,11,26),start+timedelta(hours=10),[r])
        self.assertEqual(nxt["current"],[])
        self.assertEqual(nxt["archive"][0]["reports"][0]["kind"],"pdf_box_score")
        self.assertEqual(nxt["archive"][0]["final_seen_at"],start.isoformat())
        last=make_feed({},nxt,D,date(2026,11,28),start+timedelta(days=3),[])
        self.assertEqual(last["archive"][0]["reports"],nxt["archive"][0]["reports"])
    def test_ambiguous_same_day(self):
        now=datetime(2026,11,23,16,tzinfo=timezone.utc)
        a=self.game(event("pre","STATUS_SCHEDULED",False))
        b=dict(a,key="football:124",espn_game_id="124")
        r={"kind":"game_center","sport":"FBS","date":D.isoformat(),"school":"nebraska","teams":[["Nebraska",None],["Ohio State",None]],"url":"https://huskers.com/game-center/123","reviewed":True}
        out=make_feed({a["key"]:a,b["key"]:b},{},D,D,now,[r])
        self.assertFalse(any(g["reports"] for g in out["current"]))
    def test_single_date_requests(self):
        groups=requested_days(datetime(2026,11,23,21,tzinfo=timezone.utc),{})
        calls=[]
        def fetch(url):
            calls.append(url);return b'{"events":[]}'
        collect(sorted(groups),self.idx,self.rows,[],fetch,groups)
        self.assertEqual(len(calls),20)
        self.assertTrue(all(len(u.split('dates=')[1].split('&')[0])==8 for u in calls))

    def test_scheduled_placeholder(self):
        e=event("pre","STATUS_SCHEDULED",False)
        e["competitions"][0]["competitors"][1]["team"]={"displayName":"TBD"}
        g=self.game(e);self.assertEqual(g["away_team"],"TBD");self.assertIsNone(g["team_ids"]["away"])
        self.assertIsNone(g["schools"]["away"]);self.assertFalse(g["completed"])
        resolved=merge_game(g,self.game(event("pre","STATUS_SCHEDULED",False)))
        self.assertEqual(resolved["team_ids"]["away"],"2")
    def test_invalid_final_identity(self):
        e=event();e["competitions"][0]["competitors"][1]["team"]={"displayName":"TBD"}
        with self.assertRaisesRegex(ValueError,"Missing team identity"):self.game(e)

    def test_neutral_scheduled_side_reversal(self):
        old=self.game(event("pre","STATUS_SCHEDULED",False),group="MBB")
        old["neutral_site"]=True
        new=self.game(group="MBB")
        new["neutral_site"]=True
        for field in ("team_ids","team_names","school_keys","schools"):
            new[field]={"home":new[field]["away"],"away":new[field]["home"]}
        for a,b in (("home_team","away_team"),("home_score","away_score")):
            new[a],new[b]=new[b],new[a]
        prior={"archive_start":D.isoformat(),"current":[old],"archive":[]}
        out=make_feed({new["key"]:new},prior,D,D,datetime.now(timezone.utc))
        self.assertEqual(out["archive"][0]["team_ids"],new["team_ids"])
        self.assertEqual(out["archive"][0]["home_score"],28)
        self.assertEqual(out["archive"][0]["away_score"],31)
        for change in ({"neutral_site":False},{"state":"in"},{"reports":[{"url":"https://example.org/old"}]}):
            prior["current"]=[dict(old,**change)]
            with self.assertRaisesRegex(ValueError,"Game identity conflict"):
                make_feed({new["key"]:new},prior,D,D,datetime.now(timezone.utc))
        prior["current"]=[old]
        other=dict(new,team_ids={"home":"2","away":"999"})
        with self.assertRaisesRegex(ValueError,"Game identity conflict"):
            make_feed({other["key"]:other},prior,D,D,datetime.now(timezone.utc))
        prior["archive"]=[dict(old,completed=True,state="post")]
        with self.assertRaisesRegex(ValueError,"Game identity conflict"):
            make_feed({new["key"]:new},prior,D,D,datetime.now(timezone.utc))
