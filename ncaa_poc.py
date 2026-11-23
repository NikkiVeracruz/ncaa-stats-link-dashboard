#!/usr/bin/env python3
"""Read-only NCAA contest-ID link probe. Does NOT scrape stats.ncaa.org or gamebooks.

A published ID crosswalk establishes a candidate link only; it does not verify
the content, identity, accessibility or accuracy of an NCAA Stats box-score page.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
SPORTS = {
    "FBS": ("football/college-football", 80, "football"),
    "FCS": ("football/college-football", 81, "football"),
    "MBB": ("basketball/mens-college-basketball", 50, "mbb"),
    "WBB": ("basketball/womens-college-basketball", 50, "wbb"),
}
RELEASES = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
NUMERIC_ID = re.compile(r"^[1-9][0-9]{0,14}$")
USER_AGENT = "ncaa-stats-contest-link-poc/0.1 (read-only feasibility probe)"


def clean_id(value):
    """Require a positive, unambiguous, decimal identifier."""
    value = str(value or "").strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value if NUMERIC_ID.fullmatch(value) else None


def season_for(sport, day):
    if sport == "football":
        return day.year if day.month >= 7 else day.year - 1
    return day.year + 1 if day.month >= 7 else day.year


def release_name(sport, season):
    if sport == "football":
        return f"ncaa_mfb_schedule/ncaa_mfb_schedule_{season}.csv.gz"
    return f"{sport}_crosswalk/{sport}_schedule_crosswalk_{season}.csv"


def fetch_bytes(url, attempts=3):
    """Bound downloads and retries; never contact stats.ncaa.org."""
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,*/*"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read(12_000_001)
                if len(raw) > 12_000_000:
                    raise ValueError("Upstream response exceeds 12 MB limit")
                return raw
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
        time.sleep(min(2 ** attempt, 4))
    raise RuntimeError("Unreachable retry branch")


def read_mapping(raw, *, compressed, sport):
    if compressed:
        raw = gzip.decompress(raw)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    expected_ncaa = "contest_id" if sport == "football" else "ncaa_contest_id"
    expected = {"espn_game_id", expected_ncaa}
    if not reader.fieldnames or not expected.issubset(reader.fieldnames):
        raise ValueError(f"Required columns {sorted(expected)} missing: {reader.fieldnames}")
    mapping = defaultdict(set)
    invalid = rows = 0
    for line in reader:
        rows += 1
        espn = clean_id(line.get("espn_game_id"))
        ncaa = clean_id(line.get(expected_ncaa))
        if espn and ncaa:
            mapping[espn].add(ncaa)
        elif line.get("espn_game_id") and line.get(expected_ncaa):
            invalid += 1
    return dict(mapping), {
        "mapping_rows": rows,
        "invalid_id_rows": invalid,
        "unique_espn_games_in_mapping": len(mapping),
        "ambiguous_espn_ids": sum(len(ids) > 1 for ids in mapping.values()),
    }


def parse_event(event, group):
    eid = clean_id(event.get("id"))
    if not eid:
        return None
    comp = (event.get("competitions") or [{}])[0]
    sides = {x.get("homeAway"): x for x in (comp.get("competitors") or [])}
    if "home" not in sides or "away" not in sides:
        return None

    def team(which):
        return (sides[which].get("team") or {}).get("displayName") or "Unknown"

    def score(which):
        value = str(sides[which].get("score", "")).strip()
        return int(value) if value.isdecimal() else None

    try:
        timestamp = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return None
        date_et = timestamp.astimezone(EASTERN).date().isoformat()
    except (KeyError, AttributeError, ValueError):
        return None
    status = (event.get("status") or {}).get("type") or {}
    return {
        "espn_game_id": eid, "sports": [group], "date_et": date_et,
        "home_team": team("home"), "away_team": team("away"),
        "home_score": score("home"), "away_score": score("away"),
        "status": status.get("name") or status.get("description") or "Unknown",
        "completed": bool(status.get("completed", False)),
    }


def scoreboard_url(sport, group, day):
    base = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/scoreboard"
    return base + "?" + urllib.parse.urlencode({
        "dates": day.strftime("%Y%m%d"), "groups": group, "limit": 500})


def process_day(day, *, offline=None, fetcher=fetch_bytes):
    """One bounded day, no stored game history and no historical backfill."""
    mappings = {}
    games = {}
    sources = {}
    errors = []
    families = sorted({record[2] for record in SPORTS.values()})
    for family in families:
        season = season_for(family, day)
        url = f"{RELEASES}/{release_name(family, season)}"
        try:
            raw = ((offline / f"{family}_mapping.csv").read_bytes()
                   if offline else fetcher(url))
            mapping, metrics = read_mapping(raw, compressed=(family == "football" and not offline), sport=family)
            mappings[family] = mapping
            sources[family] = {"source": url, "season": season, "status": "loaded",
                               "sha256": hashlib.sha256(raw).hexdigest(), **metrics,
                               "sample_mapping_espn_ids": list(mapping)[:4]}
        except (OSError, UnicodeError, ValueError, EOFError) as exc:
            mappings[family] = None
            sources[family] = {"source": url, "season": season, "status": "error"}
            errors.append(f"{family} crosswalk: {type(exc).__name__}: {exc}")
    for group, (sport, espn_group, _) in SPORTS.items():
        url = scoreboard_url(sport, espn_group, day)
        try:
            raw = ((offline / f"{group}_scoreboard.json").read_bytes()
                   if offline else fetcher(url))
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                raise ValueError("ESPN response does not contain an events list")
            count = 0
            rejected = 0
            for event in payload["events"]:
                game = parse_event(event, group)
                if game is None:
                    rejected += 1
                    continue
                count += 1
                eid = game["espn_game_id"]
                if eid not in games:
                    games[eid] = game
                    continue
                existing = games[eid]
                if any(existing[key] != game[key] for key in
                       ("date_et", "home_team", "away_team")):
                    existing["identity_conflict"] = True
                    errors.append(f"Conflicting scoreboard identity for ESPN game {eid}")
                if group not in existing["sports"]:
                    existing["sports"].append(group)
            if rejected:
                errors.append(f"{group} scoreboard: {rejected} malformed events")
            sources[group] = {
                "source": url, "status": "loaded", "rejected": rejected,
                "events": len(payload["events"]), "accepted": count,
                "sample_scoreboard_espn_ids": [str(e.get("id")) for e in payload["events"][:4]],
            }
        except (OSError, UnicodeError, ValueError) as exc:
            sources[group] = {"source": url, "status": "error"}
            errors.append(f"{group} scoreboard: {type(exc).__name__}: {exc}")

    for game in games.values():
        if game.get("identity_conflict"):
            game["link_status"] = "identity_conflict"
            continue
        sport_families = {SPORTS[group][2] for group in game["sports"]}
        if len(sport_families) != 1:
            game["link_status"] = "cross_sport_conflict"
            errors.append(f"Cross-sport game ID conflict: {game['espn_game_id']}")
            continue
        mapping = mappings[next(iter(sport_families))]
        if mapping is None:
            game["link_status"] = "source_unavailable"
            continue
        candidates = mapping.get(game["espn_game_id"], set())
        if not candidates:
            game["link_status"] = "no_contest_id"
        elif len(candidates) > 1:
            game["link_status"] = "ambiguous_contest_id"
        else:
            contest = next(iter(candidates))
            game["ncaa_contest_id"] = contest
            game["ncaa_stats_url"] = f"https://stats.ncaa.org/contests/{contest}/box_score"
            game["link_status"] = "id_matched_page_not_verified"

    entries = sorted(games.values(), key=lambda game: (
        game["date_et"], game["sports"], game["espn_game_id"]))
    counts = {group: dict(Counter(
        game["link_status"] for game in entries if group in game["sports"]))
        for group in SPORTS}
    return {
        "probe_date_et": day.isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "ncaa_stats_pages_verified": False,
        "data_sources": sources,
        "source_errors": errors,
        "unique_games": len(entries),
        "link_status_counts": dict(Counter(game["link_status"] for game in entries)),
        "group_status_counts": counts,
        "games": entries,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=datetime.now(EASTERN).date().isoformat(),
                        help="Single game date in US Eastern, YYYY-MM-DD")
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("report.json"))
    parser.add_argument("--require-matches", action="store_true",
                        help="Fail if no contest IDs matched (use for older known-available test dates)")
    args = parser.parse_args()
    day = date.fromisoformat(args.date)
    report = process_day(day, offline=args.fixture_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{day}: {report['unique_games']} games, "
          f"{report['link_status_counts'].get('id_matched_page_not_verified', 0)} matched candidate links")
    for group, results in report["group_status_counts"].items():
        total = sum(results.values())
        matched = results.get("id_matched_page_not_verified", 0)
        print(f"  {group}: {matched}/{total} IDs matched (not browser verified)")
    for family in ("football", "mbb", "wbb"):
        source = report["data_sources"][family]
        print(f"  MAP {family}: {source.get('unique_espn_games_in_mapping', 0)} "
              f"ESPN IDs in {source.get('mapping_rows', 0)} rows; "
              f"sample={source.get('sample_mapping_espn_ids', [])}")
    for group in SPORTS:
        print(f"  FEED {group}: sample ESPN IDs "
              f"{report['data_sources'][group].get('sample_scoreboard_espn_ids', [])}")
    if report["source_errors"]:
        print("INCOMPLETE PROBE: " + " | ".join(report["source_errors"]), file=sys.stderr)
        raise SystemExit(2)
    # The upstream crosswalk can lag completed scoreboards; distinguish a
    # diagnostic warning from an assertion about known-available older dates.
    for group in SPORTS:
        examples = [game for game in report["games"] if group in game["sports"]
                    and game["link_status"] == "id_matched_page_not_verified"]
        if examples:
            game = examples[0]
            print(f"  CANDIDATE {group}: {game['away_team']} @ {game['home_team']} "
                  f"({game['date_et']}): {game['ncaa_stats_url']}")
    if report["unique_games"] and not report["link_status_counts"].get("id_matched_page_not_verified"):
        print("WARNING: No ID matches for this date; likely mapping publication lag. "
              "Do not treat as verified NCAA box-score coverage.", file=sys.stderr)
        if args.require_matches:
            raise SystemExit(3)


if __name__ == "__main__":
    main()
