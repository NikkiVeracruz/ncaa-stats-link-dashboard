import unittest
from published_link_probe import select,allowed_url
G={"completed":True,"date_et":"2026-11-21","sports":["FBS"],"away_score":10,"home_score":20}
N={"away":{"away"},"home":{"home"}}
S={"home":"h","away":"a"}
D={"h":"home.edu","a":"away.edu"}
def row(s="h",url="/boxscore/1"):
    domain=D[s]
    data={"sport":"FBS","date":"2026-11-21","teams":[["Away",10],["Home",20]]}
    return {**data,"school":s,"source":"https://"+domain+"/schedule","links":[{"label":"Box Score","href":url}],"destination":{**data,"url":"https://"+domain+url,"final":True,"report":"box_score"}}
class Tests(unittest.TestCase):
    def test_home_first(self): self.assertEqual(select(G,N,S,D,[row("a"),row()])["side"],"home")
    def test_away_fallback(self): self.assertEqual(select(G,N,S,D,[row("a")])["side"],"away")
    def test_unverified(self):
        r=row();r["destination"]=None
        self.assertEqual(select(G,N,S,D,[r])["status"],"candidate_unverified")
    def test_bad_score(self):
        r=row();r["destination"]["teams"]=[["Away",11],["Home",20]]
        self.assertIsNone(select(G,N,S,D,[r])["url"])
    def test_wrong_sport(self):
        r=row();r["destination"]["sport"]="WBB"
        self.assertIsNone(select(G,N,S,D,[r])["url"])
    def test_wrong_date(self):
        r=row();r["destination"]["date"]="2026-11-20"
        self.assertIsNone(select(G,N,S,D,[r])["url"])
    def test_ambiguous(self): self.assertEqual(select(G,N,S,D,[row(),row(url="/boxscore/2")])["status"],"ambiguous")
    def test_url_security(self):
        for u in ("https://home.edu.evil.com/x","https://home.edu@evil.com/x","http://home.edu/x","https://home.edu:444/x"):
            self.assertFalse(allowed_url(u,"home.edu"))
    def test_non_final(self): self.assertEqual(select(dict(G,completed=False),N,S,D,[row()])["status"],"not_final")
    def test_non_boxscore(self):
        r=row();r["links"][0]["label"]="Live Stats"
        self.assertEqual(select(G,N,S,D,[r])["status"],"no_link")
