"""Read-only crosswalk catch-up and saved official identity comparison."""
import argparse
from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path
import re
import unicodedata
from ncaa_poc import SPORTS, fetch_bytes, scoreboard_url, parse_event
from reliability_probe import snapshot

REFERENCE = Path(__file__).parent / "research/official_link_reference.json"
MATCHED = "id_matched_page_not_verified"

def norm(name):
    name = unicodedata.normalize("NFKC", name).casefold()
    name = re.sub(r"\bst\.", "state", name)
    return re.sub(r"[^a-z0-9]", "", name)

def aliases(event):
    comp = (event.get("competitions") or [{}])[0]
    return {s.get("homeAway"): {norm(t) for t in
             [(s.get("team") or {}).get(k) for k in ("displayName","shortDisplayName","location","name","abbreviation")]
             if isinstance(t,str) and norm(t)}
            for s in comp.get("competitors",[])}

def matches(reference, game, names):
    if reference["sport"] not in game["sports"] or reference["date"] != game["date_et"] or not game["completed"]:
        return False
    a,b = reference["teams"]
    return any(norm(x["name"]) in names.get("away",set()) and x["score"] == game["away_score"]
               and norm(y["name"]) in names.get("home",set()) and y["score"] == game["home_score"]
               for x,y in ((a,b),(b,a)))

def compare(references, reports, name_index):
    result = []
    for r in references:
        games = [g for day in reports for g in day["games"] if matches(r,g,name_index.get((r["sport"],g["espn_game_id"]),{}))]
        # An event might be returned by two daily feeds around midnight; deduplicate only identical records.
        unique = {json.dumps(g,sort_keys=True):g for g in games}
        games = list(unique.values())
        if len(games) != 1:
            state = "identity_unmatched" if not games else "identity_ambiguous"
        else:
            g = games[0]
            if g["link_status"] == MATCHED:
                state = "correct_id" if g.get("ncaa_contest_id") == r["id"] else "wrong_id"
            else:
                state = g["link_status"]
        result.append({"sport":r["sport"],"date":r["date"],"reference_id":r["id"],"status":state,
                       "espn_ids":[g["espn_game_id"] for g in games],
                       "candidate_ids":[g.get("ncaa_contest_id") for g in games]})
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    cache={}
    def cached(url):
        if url not in cache:
            cache[url]=fetch_bytes(url)
        return cache[url]
    # Same 12 dates as previous observation, no historical archive.
    result=snapshot(date(2026,11,23),12,fetcher=cached)
    names={}
    for report in result["reports"]:
        day=date.fromisoformat(report["probe_date_et"])
        for group,(sport,group_id,_) in SPORTS.items():
            raw=cache.get(scoreboard_url(sport,group_id,day))
            if raw is None: continue
            for event in json.loads(raw)["events"]:
                g=parse_event(event,group)
                if g: names[(group,g["espn_game_id"])]=aliases(event)
    refs=json.loads(REFERENCE.read_text())
    rows=compare(refs,result["reports"],names)
    for report in result["reports"]:
        games=report["games"]
        finals=[g for g in games if g["completed"]]
        print("DAY",report["probe_date_et"],"all",len(games),"candidate",sum(g["link_status"]==MATCHED for g in games),
              "completed",len(finals),"completed_candidate",sum(g["link_status"]==MATCHED for g in finals))
        for group in SPORTS:
            f=[g for g in finals if group in g["sports"]]
            print(" GROUP",group,"completed",len(f),"candidate",sum(g["link_status"]==MATCHED for g in f))
        for family in ("football","mbb","wbb"):
            print(" HASH",family,report["data_sources"][family].get("sha256"))
    for group in SPORTS:
        print("REFERENCE",group,dict(Counter(r["status"] for r in rows if r["sport"]==group)))
    print("REFERENCE TOTAL",dict(Counter(r["status"] for r in rows)))
    print("SOURCE ERRORS",result["source_errors"])
    for r in rows:
        if r["status"] in ("wrong_id","identity_ambiguous"): print("CONFLICT",r)
    result["reference_comparisons"]=rows
    result["destination_pages_verified"]=False
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+"\n")
    # Missing IDs are measured, not silently treated as successful verification.
    return 2 if result["source_errors"] or any(r["status"]=="wrong_id" for r in rows) else 0

if __name__=="__main__":
    raise SystemExit(main())
