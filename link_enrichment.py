"""Optional link enrichment. Only reviewed observations; no school HTTP access.
Cadence slots are eligibility targets, not a claim of actual remote retrieval.
"""
from datetime import datetime
from urllib.parse import urlsplit
from published_link_probe import allowed_url
from university_probe import norm

KINDS=("game_center","box_score","pdf_box_score")

def slot(g,now):
    if g.get("completed"):
        stamp=g.get("final_seen_at")
        if not stamp:return None
        minutes=(now-datetime.fromisoformat(stamp)).total_seconds()/60
        if minutes<0 or minutes>=1440:return None
        if minutes<60:return ("post",int(minutes//5)*5)
        if minutes<240:return ("post",60+int((minutes-60)//15)*15)
        return ("post",240+int((minutes-240)//60)*60)
    if g.get("status") in ("STATUS_CANCELED","STATUS_CANCELLED","STATUS_POSTPONED","STATUS_ABANDONED"):return None
    return ("pre",int(now.timestamp()//3600))

def match(g,r,kind):
    if r.get("reviewed") is not True or r.get("kind")!=kind or r.get("date")!=g["date_et"] or r.get("sport") not in g["sports"]:return False
    if r.get("espn_game_id") and str(r["espn_game_id"])!=g["espn_game_id"]:return False
    if kind!="game_center" and not g["completed"]:return False
    if not isinstance(r.get("teams"),list) or len(r["teams"])!=2:return False
    try:
        a,b=r["teams"]
        for x,y in ((a,b),(b,a)):
            if norm(x[0]) not in g.get("team_names",{}).get("away",[]) or norm(y[0]) not in g.get("team_names",{}).get("home",[]):continue
            if kind!="game_center" and (x[1]!=g["away_score"] or y[1]!=g["home_score"]):continue
            return True
    except (TypeError,IndexError):pass
    return False

def apply_links(g,observations,now):
    due=slot(g,now)
    if due is None:return
    state=g.setdefault("discovery",{})
    reports=g.setdefault("reports",[])
    for kind in KINDS:
        if any(r.get("kind","box_score")==kind for r in reports):continue
        if kind!="game_center" and not g["completed"]:continue
        if state.get(kind)==list(due):continue
        # Review local explicitly sourced observations only. A missing source is not a web check.
        state[kind]=list(due)
        for side in ("home","away"):
            key=g.get("school_keys",{}).get(side)
            school=g.get("schools",{}).get(side)
            if not key or not school:continue
            choices=set()
            for r in observations:
                if r.get("school")!=key or not match(g,r,kind):continue
                url=r.get("url","")
                # PDFs may live on a separate CDN: only explicit independently reviewed URL
                # and exact reviewed parent-school page are accepted; never generate a URL.
                if kind=="pdf_box_score":
                    parent=r.get("parent_url","")
                    u=urlsplit(url)
                    if not allowed_url(parent,school["website"]) or u.scheme!="https" or not u.hostname or u.username or u.password or u.port not in (None,443) or not u.path.lower().endswith(".pdf"):continue
                elif not allowed_url(url,school["website"]):continue
                choices.add(url)
            if len(choices)>1:break
            if choices:
                reports.append({"kind":kind,"url":next(iter(choices)),"school":school["name"],"side":side})
                break
