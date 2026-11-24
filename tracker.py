"""Standalone NCAA tracker. ESPN data and independently reviewed optional links.
Atomic current/forward-only archive feed; no school-site scraping or historical backfill.
"""
import argparse,csv,json,os,tempfile
from link_enrichment import apply_links, match
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlsplit,urlencode
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
    g["school_keys"]=keys
    g["team_names"]={s:sorted({norm(sides[s].get(f)) for f in ("displayName","shortDisplayName","location")} - {""}) for s in sides}
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

def day_ranges(days):
    spans=[]
    for d in sorted(set(days)):
        if spans and d==spans[-1][-1]+timedelta(days=1):spans[-1].append(d)
        else:spans.append([d])
    return spans

def collect(days,idx,rows,overrides,fetcher=fetch_bytes,groups=None):
    games={}
    def read(group,sport,groupid,span):
        query=span[0].strftime("%Y%m%d")
        if len(span)>1:query+="-"+span[-1].strftime("%Y%m%d")
        url="https://site.api.espn.com/apis/site/v2/sports/"+sport+"/scoreboard?"+urlencode({"dates":query,"groups":groupid,"limit":500})
        payload=json.loads(fetcher(url))
        events=payload.get("events")
        if not isinstance(events,list):raise ValueError("Incomplete scoreboard "+group)
        if len(events)>=500:
            if len(span)==1:raise ValueError("Truncated scoreboard "+group)
            mid=len(span)//2
            read(group,sport,groupid,span[:mid]);read(group,sport,groupid,span[mid:])
            return
        allowed={d.isoformat() for d in span}
        for event in events:
            g=from_event(event,group,idx,rows,overrides)
            if g["date_et"] not in allowed:continue
            key=g["key"]
            games[key]=merge_game(games[key],g) if key in games else g
    for group,(sport,groupid,_) in SPORTS.items():
        for span in day_ranges(d for d in days if groups is None or group in groups.get(d,set())):
            read(group,sport,groupid,span)
    return games

def display_day(now):
    return (now.astimezone(EASTERN)-timedelta(hours=3)).date()

def football_start(day):
    return day-timedelta(days=(day.weekday()-3)%7)

def window_days(group,day):
    if group in ("FBS","FCS"):
        start=football_start(day)
        return {start+timedelta(days=i) for i in range(7)}
    return {day-timedelta(days=1),day,day+timedelta(days=1)}

def requested_days(now,prior):
    day=display_day(now)
    groups={}
    for group in SPORTS:
        for d in window_days(group,day):
            groups.setdefault(d,set()).add(group)
    # Reconcile only previously tracked unresolved games outside normal windows.
    for g in prior.get("current",[]):
        if not g["completed"] and g["status"] not in TERMINAL:
            d=date.fromisoformat(g["date_et"])
            if d<day and any(d not in window_days(s,day) for s in g["sports"]):
                groups.setdefault(d,set()).update(g["sports"])
    return groups

def make_feed(games,prior,cutoff,today,now,observations=None):
    cutoff=cutoff.isoformat()
    if prior and prior.get("archive_start")!=cutoff:raise ValueError("Archive start cannot change silently")
    archive={g["key"]:g for g in prior.get("archive",[]) if g["completed"] and g["date_et"]>=cutoff}
    previous={g["key"]:g for g in prior.get("current",[])}
    previous.update(archive)
    active={k:g for k,g in previous.items() if not g["completed"] and g["status"] not in TERMINAL}
    for key,g in games.items():
        old=previous.get(key)
        if old and old["team_ids"]!=g["team_ids"]:raise ValueError("Game identity conflict "+key)
        if key in archive:
            if old["date_et"]!=g["date_et"]:raise ValueError("Archived game date conflict "+key)
            if not g["completed"]:g=dict(old)
        if g["completed"]:
            g["final_seen_at"]=(old.get("final_seen_at") if old else None) or now.isoformat()
        if old and old["date_et"]==g["date_et"]:
            if old.get("discovery"):g["discovery"]=old["discovery"]
            g["reports"]=list({(r.get("kind","box_score"),r["url"]):r for r in old.get("reports",[])+g.get("reports",[])}.values())
        active[key]=g
        if g["completed"] and g["date_et"]>=cutoff:archive[key]=g
    # Archived games remain eligible for optional enrichment even after display rollover.
    pool={**active,**archive}
    # Disallow ambiguous same-day matchups when a reviewed observation lacks a unique event ID.
    eligible=[r for r in (observations or []) if r.get("espn_game_id") or sum(match(g,r,r.get("kind")) for g in pool.values())==1]
    for g in pool.values():
        if g["date_et"]>=cutoff:
            apply_links(g,eligible,now)
    current=[]
    for g in pool.values():
        d=date.fromisoformat(g["date_et"])
        if any(d in window_days(s,today) for s in g["sports"]) or (not g["completed"] and g["status"] not in TERMINAL and d<today):
            current.append(g)
    order=lambda g:(g["date_et"],g["start_utc"],g["key"])
    return {"archive_start":cutoff,"updated_at":now.isoformat(),"current":sorted(current,key=order),"archive":sorted(archive.values(),key=order,reverse=True),"scoreboards":SCOREBOARDS,"display_day":today.isoformat(),"optional_discovery_source":"reviewed_links_only"}

def write_feed(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",dir=path.parent,delete=False) as f:
        tmp=Path(f.name);json.dump(data,f,ensure_ascii=False,separators=(",",":"));f.write("\n")
    try:os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--archive-start",type=date.fromisoformat)
    p.add_argument("--observations",type=Path,default=ROOT.parent/"reviewed_game_links.json")
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    now=datetime.now(timezone.utc);today=display_day(now)
    prior=json.loads(a.output.read_text()) if a.output.exists() else {}
    cutoff=a.archive_start or (date.fromisoformat(prior["archive_start"]) if prior else now.astimezone(EASTERN).date())
    if cutoff>now.astimezone(EASTERN).date():raise ValueError("Archive start is in the future")
    if not prior and cutoff!=now.astimezone(EASTERN).date():raise ValueError("New archive starts today; no historical backfill")
    idx,rows=directory()
    groups=requested_days(now,prior)
    games=collect(sorted(groups),idx,rows,read_overrides(ROOT.parent/"reviewed_reports.json"),groups=groups)
    # Older dates outside display windows are only for resolving tracked games, not backfills.
    known={g["key"] for g in prior.get("current",[])+prior.get("archive",[])}
    games={k:g for k,g in games.items() if k in known or any(date.fromisoformat(g["date_et"]) in window_days(s,today) for s in g["sports"])}
    data=make_feed(games,prior,cutoff,today,now,read_overrides(a.observations))
    write_feed(a.output,data)
    print("TRACKER",json.dumps({"today":today.isoformat(),"current":len(data["current"]),"archive":len(data["archive"]),"schedule_shortcuts":sum(any(s and s["schedule_shortcut"] for s in g["schools"].values()) for g in data["current"]),"reviewed_reports":sum(bool(g["reports"]) for g in data["current"]),"source":"ESPN and reviewed link observations","display_day":today.isoformat(),"optional_discovery_source":data["optional_discovery_source"],"game_centers":sum(any(r.get("kind")=="game_center" for r in g["reports"]) for g in data["current"])}))
if __name__=="__main__":main()
