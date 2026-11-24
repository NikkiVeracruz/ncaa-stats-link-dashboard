"""One-date read-only directory and independently reviewed URL pilot.
No university HTTP requests, no NCAA Stats requests, no player data or archives.
Directory is a candidate source, not proof of official domain ownership.
"""
import csv, json, re, unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from ncaa_poc import SPORTS, fetch_bytes, scoreboard_url, parse_event

ROOT=Path(__file__).parent/"research"
ALIASES={"nebraska":["Nebraska"],"montana_state_university_bozeman":["Montana State"],"columbia_university_barnard":["Columbia"],"winthrop":["Winthrop"]}
def norm(s):
    return re.sub(r"[^a-z0-9]","",unicodedata.normalize("NFKC",str(s or "")).casefold())
def host(s):
    return (urlsplit(s if "://" in s else "https://"+s).hostname or "").removeprefix("www.")
def index(rows):
    idx=defaultdict(set)
    for r in rows:
        for v in [r["key"],r["name"],*ALIASES.get(r["key"],[])]:
            if norm(v): idx[norm(v)].add(r["key"])
    return idx
def resolve(team,idx):
    keys=set()
    for k in ("displayName","shortDisplayName","location"):
        keys.update(idx.get(norm(team.get(k)),set()))
    return next(iter(keys)) if len(keys)==1 else None
def identity(g, r, names):
    if not g["completed"] or g["date_et"]!=r["date"] or r["sport"] not in g["sports"]: return False
    a,b=r["teams"]
    return any(norm(x[0]) in names["away"] and x[1]==g["away_score"] and norm(y[0]) in names["home"] and y[1]==g["home_score"] for x,y in ((a,b),(b,a)))
def main():
    with (ROOT/"school_directory.csv").open(newline="") as f: rows=list(csv.DictReader(f))
    idx=index(rows); bykey={r["key"]:r for r in rows}
    refs=json.loads((ROOT/"university_controls.json").read_text())
    results=[]; errors=[]
    for group,(sport,groupid,_) in SPORTS.items():
        try:
            payload=json.loads(fetch_bytes(scoreboard_url(sport,groupid,date(2026,11,21)),attempts=1))
            for event in payload["events"]:
                g=parse_event(event,group)
                if not g: raise ValueError("malformed event")
                if not g["completed"]: continue
                sides={s["homeAway"]:s["team"] for s in event["competitions"][0]["competitors"]}
                keys={k:resolve(sides[k],idx) for k in ("home","away")}
                names={k:{norm(sides[k].get(f)) for f in ("displayName","shortDisplayName","location")} for k in sides}
                controls=[r for r in refs if identity(g,r,names) and r["school"] in bykey and host(r["url"])==host(bykey[r["school"]]["site"]) and urlsplit(r["url"]).scheme=="https"]
                results.append({"sport":group,"espn_id":g["espn_game_id"],"teams":[g["away_team"],g["home_team"]],"directory":keys,"reviewed_control_urls":[r["url"] for r in controls]})
        except Exception as exc:
            errors.append(group+": "+str(exc))
    for group in SPORTS:
        rs=[r for r in results if r["sport"]==group]
        print("DIRECTORY",group,json.dumps({"completed":len(rs),"home_candidate":sum(bool(r["directory"]["home"]) for r in rs),"either_candidate":sum(any(r["directory"].values()) for r in rs),"both_candidates":sum(all(r["directory"].values()) for r in rs),"reviewed_controls":sum(bool(r["reviewed_control_urls"]) for r in rs)}))
    print("UNIQUE",len(set(r["espn_id"] for r in results)))
    print("CONTROL_MATCHES",json.dumps([r for r in results if r["reviewed_control_urls"]]))
    print("ERRORS",errors)
    Path("diagnostics").mkdir(exist_ok=True)
    Path("diagnostics/university-directory.json").write_text(json.dumps({"rows":results,"errors":errors,"directory_only":True,"automatic_link_discovery":False},indent=2))
    return 2 if errors or len({u for r in results for u in r["reviewed_control_urls"]})!=len(refs) else 0
if __name__=="__main__":
    raise SystemExit(main())
