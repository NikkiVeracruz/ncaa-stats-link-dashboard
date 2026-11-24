"""Bounded public release comparison; no destination requests or publication."""
import io,json,hashlib
from collections import defaultdict,Counter
from pathlib import Path
from datetime import date, datetime
from ncaa_poc import RELEASES,fetch_bytes,clean_id,process_day
import pyarrow.parquet as pq

def date_key(value):
    for fmt in ("%Y-%m-%d","%m/%d/%Y"):
        try:
            return datetime.strptime(str(value)[:10],fmt).date().isoformat()
        except ValueError:
            pass
    return None

def inspect(rows,refs):
    ids=defaultdict(set)
    maps=defaultdict(set)
    for r in rows:
        d=date_key(r.get("game_date") or r.get("date"))
        c=clean_id(r.get("contest_id"))
        e=clean_id(r.get("espn_game_id"))
        if c:
            if d: ids[d].add(c)
            if e: maps[e].add(c)
    return {"latest_date":max(ids,default=None),"dates":{d:len(v) for d,v in sorted(ids.items()) if "2026-11-14"<=d<="2026-11-23"},
            "saved_reference_matches":dict(Counter(r["sport"] for r in refs if r["id"] in ids.get(r["date"],set()))),
            "ambiguous_espn_ids":sum(len(v)>1 for v in maps.values())},maps

def main():
    refs=json.loads(Path("research/official_link_reference.json").read_text())
    reports={d:process_day(date.fromisoformat(d)) for d in ("2026-11-14","2026-11-21","2026-11-23")}
    result={}
    errors=[]
    for tag,season,sports in [
        ("ncaa_mfb_linescore",2026,("FBS","FCS")),
        ("ncaa_mbb_schedule",2027,("MBB",)),
        ("ncaa_wbb_schedule",2027,("WBB",)),
        ("ncaa_mbb_team_box",2027,("MBB",)),
        ("ncaa_wbb_team_box",2027,("WBB",))]:
        try:
            raw=fetch_bytes(f"{RELEASES}/{tag}/{tag}_{season}.parquet",attempts=1)
            t=pq.read_table(io.BytesIO(raw))
            if "contest_id" not in t.column_names or not {"game_date","date","espn_game_id"}.intersection(t.column_names):
                raise ValueError(f"missing required columns: {t.column_names}")
            r,m=inspect(t.to_pylist(),[x for x in refs if x["sport"] in sports])
            r.update(date_available=bool({"game_date","date"}.intersection(t.column_names)),rows=t.num_rows,columns=t.column_names,sha256=hashlib.sha256(raw).hexdigest())
            r["espn_comparison"]={}
            for d,report in reports.items():
                for sport in sports:
                    games=[g for g in report["games"] if sport in g["sports"] and g["completed"]]
                    r["espn_comparison"][d+":"+sport]={"completed":len(games),"unique_candidates":sum(len(m.get(g["espn_game_id"],set()))==1 for g in games),"new_candidates":sum(len(m.get(g["espn_game_id"],set()))==1 and not g.get("ncaa_contest_id") for g in games)}
            result[tag]=r
        except Exception as exc:
            result[tag]={"error":f"{type(exc).__name__}: {exc}"}
            errors.append(tag)
        print("ASSET",tag,json.dumps(result[tag]),flush=True)
    Path("diagnostics").mkdir(exist_ok=True)
    Path("diagnostics/alternate-assets.json").write_text(json.dumps(result,indent=2))
    return int(bool(errors or any(r["source_errors"] for r in reports.values())))

if __name__=="__main__":
    raise SystemExit(main())
