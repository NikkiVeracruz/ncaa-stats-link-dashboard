"""Read-only upstream schedule experiment; never publish candidate links."""
import argparse
import io
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from ncaa_poc import SPORTS, clean_id, fetch_bytes, scoreboard_url, season_for, process_day

RAW = "https://raw.githubusercontent.com/sportsdataverse"
SOURCES = {
    "mbb": "ncaa-mbb-hoops-raw/main/mbb/schedules/parquet/{season}.parquet",
    "wbb": "ncaa-wbb-hoops-raw/main/wbb/schedules/parquet/{season}.parquet",
    "football": "ncaa-mfb-football-raw/main/mfb/schedules/parquet/{season}.parquet",
}


def normalize_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value or "").strip()
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def key(day, a, b):
    a, b = clean_id(a), clean_id(b)
    day = normalize_date(day)
    if not day or not a or not b or a == b:
        return None
    return day, *sorted((a, b))


def index_rows(rows, date_column):
    index = defaultdict(set)
    for row in rows:
        k = key(row.get(date_column), row.get("espn_team_id"),
                row.get("opponent_espn_team_id"))
        contest = clean_id(row.get("contest_id"))
        if k and contest:
            index[k].add(contest)
    return index


def index_football(rows, date_column):
    index = defaultdict(set)
    for row in rows:
        day = normalize_date(row.get(date_column))
        event = clean_id(row.get("espn_game_id"))
        contest = clean_id(row.get("contest_id"))
        if day and event and contest:
            index[(day, event)].add(contest)
    return index


def unique(values):
    return next(iter(values)) if len(values) == 1 else None


def candidate(index, day, a, b):
    return unique(index.get(key(day, a, b), set()))


def inspect_rows(rows, date_column, family):
    fields = ["contest_id", date_column] + (
        ["espn_game_id"] if family == "football" else
        ["espn_team_id", "opponent_espn_team_id"])
    counts = Counter()
    dates = Counter()
    contest_dates = Counter()
    samples = {f: [] for f in fields}
    for row in rows:
        day = normalize_date(row.get(date_column))
        contest = clean_id(row.get("contest_id"))
        if day:
            dates[day] += 1
            if contest:
                contest_dates[day] += 1
        for field in fields:
            value = row.get(field)
            if value is not None and len(samples[field]) < 5:
                item = {"value": str(value), "type": type(value).__name__}
                if item not in samples[field]:
                    samples[field].append(item)
            valid = normalize_date(value) if field == date_column else clean_id(value)
            if valid:
                counts[field] += 1
    return {"valid_fields": {f: counts[f] for f in fields},
            "samples": samples, "rows_by_date": dict(sorted(dates.items())),
            "contest_rows_by_date": dict(sorted(contest_dates.items())),
            "latest_schedule_date": max(dates, default=None),
            "latest_contest_date": max(contest_dates, default=None)}


def run(start, end):
    import pyarrow.parquet as pq
    result = {"read_only": True, "destination_pages_verified": False, "sources": {}, "days": []}
    indexes = {}
    # Test one positive-control date and the problem dates, plus future schedules.
    days = sorted(set([date(2026, 11, 14)] + [
        start + timedelta(days=i) for i in range((end-start).days + 1)]))
    for family, template in SOURCES.items():
        seasons = [season_for(family, end)]
        if family == "football":
            seasons = [season_for(family, end) + 1]
        observations = []
        for season in seasons:
            url = RAW + "/" + template.format(season=season)
            try:
                table = pq.read_table(io.BytesIO(fetch_bytes(url)))
                columns = table.column_names
                date_column = next((c for c in ("date", "game_date", "contest_date") if c in columns), None)
                required = {"contest_id", "espn_game_id"} if family == "football" else {
                    "contest_id", "espn_team_id", "opponent_espn_team_id"}
                obs = {"url": url, "rows": table.num_rows, "columns": columns,
                       "schema": str(table.schema)}
                if not date_column or not required.issubset(columns):
                    obs["status"] = "unsupported_schema"
                else:
                    rows = table.select([date_column, *sorted(required)]).to_pylist()
                    idx = index_football(rows, date_column) if family == "football" else index_rows(rows, date_column)
                    info = inspect_rows(rows, date_column, family)
                    obs.update(info, status="loaded" if idx else "no_usable_keys",
                               keyed_games=len(idx), latest_keyed_date=max((k[0] for k in idx), default=None),
                               ambiguous_keys=sum(len(v)>1 for v in idx.values()))
                    indexes[family] = idx
                observations.append(obs)
            except Exception as exc:
                observations.append({"url": url, "status": "unavailable", "error": f"{type(exc).__name__}: {exc}"})
        result["sources"][family] = observations
        for obs in observations:
            summary = {k:v for k,v in obs.items() if k not in ("rows_by_date","contest_rows_by_date","schema")}
            print(family, json.dumps(summary), flush=True)
            for day in days:
                ds = day.isoformat()
                print("SOURCE_DATE", family, ds, obs.get("rows_by_date",{}).get(ds,0),
                      obs.get("contest_rows_by_date",{}).get(ds,0), flush=True)
    for day in days:
        report = {"date": day.isoformat(), "groups": {}}
        # Existing exact-ID mapping is a comparison, never proof of destination identity.
        baseline = process_day(day)
        known = {g["espn_game_id"]:g.get("ncaa_contest_id") for g in baseline["games"]}
        report["baseline_errors"] = baseline["source_errors"]
        for group, (sport, group_id, family) in SPORTS.items():
            try:
                events = json.loads(fetch_bytes(scoreboard_url(sport, group_id, day)))["events"]
                if not isinstance(events, list):
                    raise ValueError("invalid events list")
                matches = []
                comparison = Counter()
                for event in events:
                    eid = clean_id(event.get("id"))
                    comp = event.get("competitions", [{}])[0]
                    teams = [t.get("team", {}).get("id") for t in comp.get("competitors", [])]
                    if not eid:
                        comparison["invalid_event_id"] += 1
                        continue
                    index = indexes.get(family, {})
                    contest = unique(index.get((day.isoformat(), eid), set())) if family == "football" else (
                        candidate(index, day, *teams) if len(teams)==2 else None)
                    old = known.get(eid)
                    if old:
                        comparison["baseline_matched"] += 1
                        if contest:
                            comparison["agree" if old == contest else "conflict"] += 1
                        else:
                            comparison["baseline_only"] += 1
                    elif contest:
                        comparison["upstream_only"] += 1
                    if contest:
                        matches.append({"espn_game_id": eid, "candidate_contest_id": contest,
                                        "baseline_id": old, "completed": bool(event.get("status",{}).get("type",{}).get("completed"))})
                report["groups"][group] = {"discovered": len(events), "candidate_count": len(matches),
                                           "comparison": dict(comparison), "candidates": matches,
                                           "nonfinal_candidates": sum(not m["completed"] for m in matches)}
            except Exception as exc:
                report["groups"][group] = {"status": "error", "error": str(exc)}
        result["days"].append(report)
        print("COMPARE", day, {g: {k:v for k,v in d.items() if k != "candidates"} for g,d in report["groups"].items()}, flush=True)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if not 0 <= (a.end-a.start).days <= 10:
        p.error("select at most eleven consecutive dates")
    result = run(a.start, a.end)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2)+"\n")
    control = next(d for d in result["days"] if d["date"] == "2026-11-14")
    for group in SPORTS:
        if not control["groups"][group].get("comparison",{}).get("agree"):
            print("POSITIVE CONTROL FAILED:", group, flush=True)
        else:
            print("POSITIVE CONTROL PASSED:", group, flush=True)
    if any(d["baseline_errors"] or any("error" in g for g in d["groups"].values()) for d in result["days"]):
        raise SystemExit(2)
    if any(not control["groups"][g].get("comparison",{}).get("agree") for g in SPORTS):
        raise SystemExit(3)
    if any(g.get("comparison",{}).get("conflict") for d in result["days"] for g in d["groups"].values()):
        raise SystemExit(4)


if __name__ == "__main__":
    main()
