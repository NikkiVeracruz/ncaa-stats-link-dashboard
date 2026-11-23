"""Read-only upstream schedule experiment; never publish candidate links."""
import argparse
import io
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from ncaa_poc import SPORTS, clean_id, fetch_bytes, scoreboard_url, season_for

RAW = "https://raw.githubusercontent.com/sportsdataverse"
SOURCES = {
    "mbb": "ncaa-mbb-hoops-raw/main/mbb/schedules/parquet/{season}.parquet",
    "wbb": "ncaa-wbb-hoops-raw/main/wbb/schedules/parquet/{season}.parquet",
    "football": "ncaa-mfb-football-raw/main/mfb/schedules/parquet/{season}.parquet",
}


def key(day, a, b):
    a, b = clean_id(a), clean_id(b)
    if not a or not b or a == b:
        return None
    try:
        day = date.fromisoformat(str(day)[:10]).isoformat()
    except ValueError:
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


def candidate(index, day, a, b):
    matches = index.get(key(day, a, b), set())
    return next(iter(matches)) if len(matches) == 1 else None


def run(start, end):
    import pyarrow.parquet as pq
    result = {"read_only": True, "destination_pages_verified": False, "sources": {}, "days": []}
    indexes = {}
    for family, template in SOURCES.items():
        # Football raw repository uses an academic-year convention; probe both
        # plausible filenames, recording every outcome rather than guessing data.
        seasons = [season_for(family, end)]
        if family == "football":
            seasons.append(end.year + 1)
        observations = []
        for season in dict.fromkeys(seasons):
            url = RAW + "/" + template.format(season=season)
            try:
                table = pq.read_table(io.BytesIO(fetch_bytes(url)))
                columns = table.column_names
                date_column = next((c for c in ("date", "game_date", "contest_date") if c in columns), None)
                required = {"contest_id", "espn_team_id", "opponent_espn_team_id"}
                obs = {"url": url, "rows": table.num_rows, "columns": columns}
                if not date_column or not required.issubset(columns):
                    obs["status"] = "unsupported_schema"
                else:
                    idx = index_rows(table.select([date_column, *sorted(required)]).to_pylist(), date_column)
                    obs.update(status="loaded", keyed_games=len(idx), latest_date=max((k[0] for k in idx), default=None))
                    if family not in indexes:
                        indexes[family] = idx
                    else:
                        for k, values in idx.items():
                            indexes[family][k].update(values)
                observations.append(obs)
            except Exception as exc:
                observations.append({"url": url, "status": "unavailable", "error": f"{type(exc).__name__}: {exc}"})
        result["sources"][family] = observations
        print(family, json.dumps(observations), flush=True)
    day = start
    while day <= end:
        report = {"date": day.isoformat(), "groups": {}}
        for group, (sport, group_id, family) in SPORTS.items():
            try:
                events = json.loads(fetch_bytes(scoreboard_url(sport, group_id, day)))["events"]
                if not isinstance(events, list):
                    raise ValueError("invalid events list")
                matches = []
                for event in events:
                    comp = event.get("competitions", [{}])[0]
                    teams = [t.get("team", {}).get("id") for t in comp.get("competitors", [])]
                    if len(teams) == 2:
                        contest = candidate(indexes.get(family, {}), day, *teams)
                        if contest:
                            matches.append({"espn_game_id": event.get("id"), "candidate_contest_id": contest})
                report["groups"][group] = {"discovered": len(events), "candidate_count": len(matches), "candidates": matches}
            except Exception as exc:
                report["groups"][group] = {"status": "error", "error": str(exc)}
        result["days"].append(report)
        print(day, {g: {k:v for k,v in d.items() if k != "candidates"} for g,d in report["groups"].items()}, flush=True)
        day += timedelta(days=1)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if not 0 <= (a.end-a.start).days <= 7:
        p.error("select at most eight consecutive dates")
    result = run(a.start, a.end)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2)+"\n")
    # Diagnostic may establish that alternatives are unavailable, not a production pass.
    if any("error" in g for d in result["days"] for g in d["groups"].values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
