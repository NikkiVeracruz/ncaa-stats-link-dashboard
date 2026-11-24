"""Standalone NCAA tracking; ESPN game data only. No school-site retrieval.
A single atomic feed contains current games and forward-only completed records.
The caller supplies an explicit archive start date; no backfill or deployment.
"""
import argparse,csv,json,os,shutil,tempfile
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlsplit
from ncaa_poc import SPORTS,EASTERN,fetch_bytes,parse_event,scoreboard_url,clean_id
from university_probe import ROOT,index,resolve,identity,norm,host
from published_link_probe import allowed_url

SCOREBOARDS={"FBS":"https://stats.ncaa.org/contests/scoreboards?division=11&sport_code=MFB","FCS":"https://stats.ncaa.org/contests/scoreboards?division=12&sport_code=MFB","MBB":"https://stats.ncaa.org/contests/scoreboards?division=1&sport_code=MBB","WBB":"https://stats.ncaa.org/contests/scoreboards?division=1&sport_code=WBB"}
SLUGS={"FBS":"football","FCS":"football","MBB":"mens-basketball","WBB":"womens-basketball"}
TERMINAL={"STATUS_CANCELED","STATUS_CANCELLED","STATUS_POSTPONED","STATUS_ABANDONED"}
FINAL={"STATUS_FINAL","STATUS_FULL_TIME","STATUS_FINAL_OVERTIME"}

def directory():
    with (ROOT/"school_directory.csv").open(newline="") as f: rows=list(csv.DictReader(f))
    return index(rows),{r["key"]:r for r in rows}

def school_link(key,rows,group):
    if key not in rows:return None
    r=rows[key]; base="https://"+r["site"]
    u=urlsplit(base)
    if not u.hostname or u.path or u.query or u.fragment or not allowed_url(base,r["site"]):return None
    # Common platform navigation path, NOT a verified game report.
    schedule=base+"/sports/"+SLUGS[group]+"/schedule" if r["platform"] in ("sidearm","sidearm_legacy","wmt") else None
    return {"name":r["name"],"website":base,"schedule_shortcut":schedule}

def read_overrides(path):
    if not path.exists():return []
    rows=json.loads(path.read_text())
    if not isinstance(rows,list):raise ValueError("Reviewed links must be a list")
    return rows

def from_event(event,group,idx,rows,overrides):
    g=parse_event(event,group)
    if not g:raise ValueError("Malformed game")
    comp=event["competitions"][0]
    sides={s["homeAway"]:s["team"] for s in comp["competitors"]}
    if any(not clean_id(sides[s].get("id")) or not sides[s].get("displayName") for s in ("home","away")):raise ValueError("Missing team identity")
    family=SPORTS[group][2]
    g["key"]=family+":"+g["espn_game_id"]
    g["start_utc"]=event["date"]
    rawstatus=event.get("status") or {}
    typ=rawstatus.get("type") or {}
    state=typ.get("state")
    if state not in ("pre","in","post"):raise ValueError("Unknown game state")
    g["state"]=state
    g["status_text"]=typ.get("shortDetail") or typ.get("description") or g["status"]
    g["completed"]=bool(typ.get("completed")) and g["status"] in FINAL and state=="post" and g["home_score"] is not None and g["away_score"] is not None
    g["neutral_site"]=bool(comp.get("neutralSite"))
    if state=="pre":g["home_score"]=g["away_score"]=None
    g["clock"]=rawstatus.get("displayClock") if state=="in" else None
    g["period"]=rawstatus.get("period") if state=="in" else None
    g["team_ids"]={s:str(sides[s]["id"]) for s in ("home","away")}
    keys={s:resolve(sides[s],idx) for s in ("home","away")}
    g["schools"]={s:school_link(keys[s],rows,group) for s in keys}
    g["scoreboards"]={group:SCOREBOARDS[group]}
    names={s:{norm(sides[s].get(f)) for f in ("displayName","shortDisplayName","location")} for s in sides}
    g["reports"]=[]
    for r in overrides:
        school=r.get("school")
        if r.get("espn_game_id")!=g["espn_game_id"] or school not in keys.values() or school not in rows:continue
        if r.get("report")!="box_score" or r.get("reviewed") is not True or not identity(g,r,names):continue
        if not allowed_url(r.get("url",""),rows[school]["site"]):continue
        g["reports"].append({"url":r["url"],"school":rows[school]["name"],"side":"home" if school==keys["home"] else "away"})
    g["reports"].sort(key=lambda r:(r["side"]!="home",r["url"]))
    return g

def merge_game(g,h):
    if any(g[k]!=h[k] for k in ("date_et","team_ids","start_utc")):raise ValueError("Conflicting game identity "+g["key"])
    if g["completed"] and h["completed"] and any(g[k]!=h[k] for k in ("home_score","away_score")):raise ValueError("Conflicting final scores "+g["key"])
    # Within a poll, prefer final over live, live over scheduled.
    rank=lambda x: (x["completed"],x["state"]=="in")
    best=dict(max((g,h),key=rank))
    best["sports"]=sorted(set(g["sports"]+h["sports"]))
    best["scoreboards"]={**g["scoreboards"],**h["scoreboards"]}
    return best

def collect(days,idx,rows,overrides,fetcher=fetch_bytes):
    games={}
    for day in days:
        for group,(sport,groupid,_) in SPORTS.items():
            payload=json.loads(fetcher(scoreboard_url(sport,groupid,day)))
            events=payload.get("events")
            if not isinstance(events,list) or len(events)>=500:raise ValueError("Incomplete scoreboard "+group)
            for event in events:
                g=from_event(event,group,idx,rows,overrides)
                if g["date_et"] not in {d.isoformat() for d in days}:continue
                key=g["key"]
                games[key]=merge_game(games[key],g) if key in games else g
    return games

def make_feed(games,prior,cutoff,today,now):
    cutoff=cutoff.isoformat()
    if prior and prior.get("archive_start")!=cutoff:raise ValueError("Archive start cannot change silently")
    archive={g["key"]:g for g in prior.get("archive",[]) if g["completed"] and g["date_et"]>=cutoff}
    # Preserve past current games that remain unresolved; never infer final from age.
    active={g["key"]:g for g in prior.get("current",[]) if g["date_et"]>=cutoff and not g["completed"] and g["status"] not in TERMINAL}
    for key,g in games.items():
        if key in archive:
            old=archive[key]
            if old["team_ids"]!=g["team_ids"] or old["date_et"]!=g["date_et"]:raise ValueError("Archive identity conflict "+key)
            if not g["completed"]:g=old
        active[key]=g
        if g["completed"] and g["date_et"]>=cutoff:archive[key]=g
    yesterday=(today-timedelta(days=1)).isoformat()
    current=[g for g in active.values() if g["date_et"]>=yesterday or (not g["completed"] and g["status"] not in TERMINAL)]
    order=lambda g:(g["date_et"],g["start_utc"],g["key"])
    return {"archive_start":cutoff,"updated_at":now.isoformat(),"current":sorted(current,key=order),"archive":sorted(archive.values(),key=order,reverse=True),"scoreboards":SCOREBOARDS}

def write_feed(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",dir=path.parent,delete=False) as f:
        tmp=Path(f.name);json.dump(data,f,ensure_ascii=False,separators=(",",":"));f.write("\n")
    try:os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--archive-start",required=True,type=date.fromisoformat)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    now=datetime.now(timezone.utc);today=now.astimezone(EASTERN).date()
    if a.archive_start>today:raise ValueError("Archive start is in the future")
    prior=json.loads(a.output.read_text()) if a.output.exists() else {}
    if not prior and a.archive_start!=today:raise ValueError("New archive starts today; no historical backfill")
    idx,rows=directory()
    # Yesterday is current display only; archive cutoff still applies.
    days=[today-timedelta(days=1),today]
    games=collect(days,idx,rows,read_overrides(ROOT.parent/"reviewed_reports.json"))
    data=make_feed(games,prior,a.archive_start,today,now)
    write_feed(a.output,data)
    print("TRACKER",json.dumps({"today":today.isoformat(),"current":len(data["current"]),"archive":len(data["archive"]),"schedule_shortcuts":sum(any(s and s["schedule_shortcut"] for s in g["schools"].values()) for g in data["current"]),"reviewed_reports":sum(bool(g["reports"]) for g in data["current"]),"source":"ESPN only"}))
if __name__=="__main__":main()
