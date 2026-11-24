"""Select explicitly published report links from normalized source observations.
Research only. No university requests, no source acquisition, no player data.
Observations are independently reviewed facts, NOT raw HTML or live feed results.
"""
import csv,json,re
from datetime import date
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from university_probe import ROOT, index, resolve, identity, norm, host
from ncaa_poc import SPORTS, fetch_bytes, parse_event, scoreboard_url

def allowed_url(url,domain):
    try:
        u=urlsplit(url)
        return u.scheme=="https" and not u.username and not u.password and u.port in (None,443) and host(url)==host(domain)
    except ValueError:
        return False

def select(g,names,schools,domains,rows):
    verified=[]; pending=[]
    if not g["completed"]: return {"status":"not_final","url":None}
    for r in rows:
        school=r["school"]
        if school not in schools.values() or school not in domains: continue
        domain=domains[school]
        if not allowed_url(r["source"],domain) or not identity(g,r,names): continue
        for link in r["links"]:
            if norm(link["label"])!="boxscore": continue
            url=urljoin(r["source"],link["href"])
            if not allowed_url(url,domain): continue
            # Label alone never verifies the destination. Require independently obtained evidence.
            d=r.get("destination")
            if d and d.get("url")==url and d.get("final") is True and d.get("report")=="box_score" and identity(g,d,names):
                verified.append((school,url))
            else: pending.append(url)
    # If more than one verified URL at a single school, refuse ambiguous choice.
    for side in ("home","away"):
        options={u for s,u in verified if s==schools.get(side)}
        if len(options)>1:return {"status":"ambiguous","url":None}
        if options:return {"status":"reviewed_destination_match","url":next(iter(options)),"side":side}
    return {"status":"candidate_unverified" if pending else "no_link","url":None,"candidates":sorted(set(pending))}

def main():
    rows=json.loads((ROOT/"published_link_observations.json").read_text())
    with (ROOT/"school_directory.csv").open(newline="") as f: directory=list(csv.DictReader(f))
    idx=index(directory); domains={r["key"]:r["site"] for r in directory}
    results=[]
    for group,(sport,groupid,_) in SPORTS.items():
        payload=json.loads(fetch_bytes(scoreboard_url(sport,groupid,date(2026,11,21)),attempts=1))
        for event in payload["events"]:
            g=parse_event(event,group)
            if not g: raise ValueError("malformed event")
            sides={s["homeAway"]:s["team"] for s in event["competitions"][0]["competitors"]}
            names={k:{norm(t.get(f)) for f in ("displayName","shortDisplayName","location")} for k,t in sides.items()}
            schools={k:resolve(t,idx) for k,t in sides.items()}
            relevant=[r for r in rows if r["sport"]==group and r["school"] in schools.values()]
            # Only count target matchups, not the entire ESPN sample as retrieval coverage.
            if not any(identity(g,r,names) for r in relevant):continue
            result=select(g,names,schools,domains,relevant)
            results.append({"group":group,"espn_id":g["espn_game_id"],**result})
    print("PUBLISHED_LINK_REPLAY",json.dumps(results),flush=True)
    Path("diagnostics").mkdir(exist_ok=True)
    Path("diagnostics/published-link-replay.json").write_text(json.dumps({"results":results,"school_requests":0,"live_discovery":False},indent=2))
    expected={"FBS":"reviewed_destination_match","FCS":"reviewed_destination_match","MBB":"candidate_unverified","WBB":"reviewed_destination_match"}
    return 0 if len(results)==4 and {r["group"]:r["status"] for r in results}==expected else 2

if __name__=="__main__": raise SystemExit(main())
