"""Limited production PDF discovery: explicitly configured basketball sources.

Uses the same bounded, robots-aware source as the successful read-only probe.
Never modifies game identities, scores, archive membership, or existing reports.
No stored source documents, no guessed destinations, no NCAA Stats access.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import math
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.robotparser import RobotFileParser

from link_enrichment import slot
from tracker import directory, write_feed
from university_source_registry import load_registry
from university_link_acquisition_probe import (
    AGENT, BASE, SOURCE, candidates, get, download_link, get_pdf, pdf_identity, cdn_allowed,
)

SOURCE_NAME = "reviewed_links_plus_verified_basketball_pdf_sources"
STATE_KEY = "university_discovery"
# Invalid configuration disables only optional discovery; CI validates strictly.
try:
    SOURCES = load_registry()
except (OSError, ValueError, TypeError, KeyError) as exc:
    SOURCES = {}
    print("OPTIONAL UNIVERSITY REGISTRY UNAVAILABLE:", str(exc), file=sys.stderr, flush=True)

MAX_SOURCES_PER_RUN = 5
QUEUE_START_BUDGET_SECONDS = 120

def sport_of(g):
    sports = g.get("sports", [])
    return sports[0] if len(sports) == 1 and sports[0] in ("WBB", "MBB") else None

def source_for(g, side):
    return SOURCES.get(g.get("school_keys", {}).get(side), {}).get(sport_of(g))



def state_for(feed):
    state = feed.setdefault(STATE_KEY, {})
    if not isinstance(state, dict) or not isinstance(state.setdefault("slots", {}), dict) or not isinstance(state.setdefault("blocked_sources", {}), dict) or not isinstance(state.setdefault("school_attempts", {}), dict) or not isinstance(state.setdefault("game_attempts", {}), dict):
        state = {"blocked": True, "slots": {}, "blocked_sources": {}, "school_attempts": {}, "game_attempts": {}, "last_attempt": {"result": "invalid_optional_state"}}
        feed[STATE_KEY] = state
        print("OPTIONAL UNIVERSITY SOURCE DISABLED: invalid saved state", file=sys.stderr, flush=True)
    return state


def eligible(feed, now):
    state = state_for(feed)
    if state.get("blocked"):
        return []
    pool = {g["key"]: g for g in feed["current"] + feed["archive"]}
    result = []
    def identity(g):
        ids = g.get("team_ids", {})
        if not all(ids.get(s) for s in ("home", "away")):
            return None
        return (g["date_et"], sport_of(g), tuple(sorted((ids["home"], ids["away"]))))
    counts = Counter(identity(g) for g in pool.values())
    for g in pool.values():
        if (not g.get("completed") or not sport_of(g) or
                g["date_et"] < feed["archive_start"] or
                any(r.get("kind") == "pdf_box_score" for r in g.get("reports", []))):
            continue
        sides = g.get("school_keys", {})
        own = [s for s in ("home", "away") if source_for(g, s) and sides[s] not in state["blocked_sources"]]
        if not own or not all(g.get("team_ids", {}).get(s) for s in ("home", "away")):
            continue
        # A same-day repeat matchup is not safe to identify by schedule row.
        if counts[identity(g)] != 1:
            continue
        due = slot(g, now)
        if due is None:
            continue
        for side in own:
            school = sides[side]
            other = "away" if side == "home" else "home"
            if not sides.get(other) or not g.get("team_names", {}).get(other):
                continue
            key = g["key"] + "|" + school
            if state["slots"].get(key) == list(due) or (school == "vanderbilt" and state["slots"].get(g["key"]) == list(due)):
                continue
            result.append((g, side, due))
            break
    # Unserved/least recently served schools first; within each school favor
    # unattempted games, then oldest attempt, then recently completed games.
    def stamp(mapping, key):
        value = mapping.get(key, -1)
        return value if type(value) in (int, float) and math.isfinite(value) else -1
    def priority(item):
        g, side, _ = item
        school = g["school_keys"][side]
        key = g["key"] + "|" + school
        return (stamp(state["school_attempts"], school),
                stamp(state["game_attempts"], key),
                -datetime.fromisoformat(g["final_seen_at"]).timestamp(), g["key"], school)
    return sorted(result, key=priority)


def acquire(g, own):
    if not shutil.which("pdftotext"):
        raise OSError("PDF verification dependency unavailable")
    config = source_for(g, own)
    if not config:
        return None
    sport = sport_of(g)
    base = "https://" + config["host"]
    source = base + config["path"]
    def school_get(url, media):
        return get(url, media) if config["host"] == "vucommodores.com" else get(url, media, host=config["host"])
    other = "away" if own == "home" else "home"
    day = date.fromisoformat(g["date_et"])
    first_year = day.year if day.month >= 7 else day.year - 1
    season = f"{first_year}-{(first_year + 1) % 100:02}"
    own_score, other_score = g[own + "_score"], g[other + "_score"]
    if not isinstance(own_score, int) or not isinstance(other_score, int) or own_score == other_score:
        return None
    # Accept only exact aliases that independently resolve to the opposing school.
    idx, _ = directory()
    aliases = {a for a in g["team_names"][other] if idx.get(a) == {g["school_keys"][other]}}
    if not aliases:
        return None
    rules = school_get(base + "/robots.txt", "text/plain")
    if not re.search(r"(?im)^\s*user-agent\s*:", rules):
        raise ValueError("Unparseable robots rules")
    robots = RobotFileParser()
    robots.parse(rules.splitlines())
    if not robots.can_fetch(AGENT, source):
        raise ValueError("Robots disallows schedule")
    links = candidates(
        school_get(source, "text/html"), aliases=aliases, include_labels=True, season=season,
        source=source, cdn_prefix=config["prefix"], heading_order=config.get("heading_order", "season_first"),
        short_result=config.get("short_result", False), pdf_labels=config.get("pdf_labels", ("box score (pdf)",)),
        sport=sport, repeat_date=config.get("repeat_date", False), compact_date=config.get("compact_date", False),
        day=f"{day.strftime('%b')} {day.day}",
        result=f"{'Win' if own_score > other_score else 'Loss'} {own_score}-{other_score}",
    )
    parent = links.get("pdf_candidate")
    if not parent:
        return None
    if cdn_allowed(parent, config["prefix"]):
        pdf_url = parent
    else:
        if not robots.can_fetch(AGENT, parent):
            raise ValueError("Robots disallows PDF wrapper")
        pdf_url = download_link(school_get(parent, "text/html"), parent, config["prefix"])
        if not pdf_url:
            return None
    pdf_text = get_pdf(pdf_url, config["prefix"])
    if not any(pdf_identity(pdf_text, opponent=label, day=f"{day.month}/{day.day}/{day.year % 100:02}",
                            own_score=own_score, opponent_score=other_score, season=season, own_name=config["pdf_name"], sport=sport)
               for label in links["opponent_labels"]):
        return None
    return {"kind": "pdf_box_score", "url": pdf_url, "school": config["name"],
            "side": own, "verification": "automatic_final_pdf_identity",
            "source_url": source, "parent_url": parent}


def enrich(feed, now, fetcher=acquire, *, clock=time.monotonic):
    state = state_for(feed)
    feed["optional_discovery_source"] = SOURCE_NAME
    # Keep state only for the short eligibility window; links live in the archive.
    pool = {g["key"]: g for g in feed["current"] + feed["archive"]}
    state["slots"] = {k: v for k, v in state["slots"].items()
                      if k.split("|", 1)[0] in pool and pool[k.split("|", 1)[0]].get("completed")
                      and slot(pool[k.split("|", 1)[0]], now) is not None}
    state["school_attempts"] = {k:v for k,v in state["school_attempts"].items() if k in SOURCES}
    state["game_attempts"] = {k:v for k,v in state["game_attempts"].items() if k in state["slots"]}
    due = eligible(feed, now)
    started = clock()
    used = set()
    first_report = None
    for g, own, current_slot in due:
        school = g["school_keys"][own]
        if school in used or school in state["blocked_sources"]:
            continue
        if len(used) >= MAX_SOURCES_PER_RUN or clock() - started >= QUEUE_START_BUDGET_SECONDS:
            break
        used.add(school)
        key = g["key"] + "|" + school
        state["slots"][key] = list(current_slot)
        state["school_attempts"][school] = now.timestamp()
        state["game_attempts"][key] = now.timestamp()
        state["last_attempt"] = {"key": g["key"], "school": school, "at": now.isoformat()}
        try:
            report = fetcher(g, own)
        except (OSError, ValueError, UnicodeError, RecursionError, subprocess.SubprocessError) as exc:
            if (isinstance(exc, HTTPError) and 300 <= exc.code < 500) or "robots" in str(exc).lower():
                state["blocked_sources"][school] = str(exc)
            state["last_attempt"]["result"] = "source_unavailable"
            print("OPTIONAL UNIVERSITY SOURCE UNAVAILABLE:", school, str(exc), flush=True)
            continue
        if report is None:
            state["last_attempt"]["result"] = "no_verified_pdf"
            print("OPTIONAL UNIVERSITY SOURCE: no verified PDF for", g["key"], school, flush=True)
            continue
        for row in feed["current"] + feed["archive"]:
            if row["key"] == g["key"] and not any(r.get("kind") == "pdf_box_score" for r in row.get("reports", [])):
                row.setdefault("reports", []).append(dict(report))
        state["last_attempt"]["result"] = "verified_pdf"
        print("OPTIONAL UNIVERSITY PDF VERIFIED:", json.dumps({"key": g["key"], "school": school, "url": report["url"]}), flush=True)
        if first_report is None:
            first_report = report
    state["queue"] = {"eligible_games": len(due), "attempted_schools": len(used), "deferred_games": len(due) - len(used)}
    print("OPTIONAL UNIVERSITY QUEUE:", json.dumps(state["queue"]), flush=True)
    return first_report


def live_control():
    """Exercise the production path with one known matchup, in memory only."""
    g = {"key": "wbb:401913059", "sports": ["WBB"], "date_et": "2026-11-23",
         "completed": True, "final_seen_at": "2026-11-24T02:51:30+00:00",
         "school_keys": {"home": "vanderbilt", "away": "arizona"},
         "team_ids": {"home": "238", "away": "12"},
         "team_names": {"home": ["vanderbilt"], "away": ["arizona"]},
         "home_score": 93, "away_score": 62, "reports": []}
    feed = {"archive_start": "2026-11-23", "current": [g], "archive": [dict(g, reports=[])]}
    now = datetime.fromisoformat("2026-11-24T14:00:00+00:00")
    report = enrich(feed, now)
    if not report or feed["archive"][0]["reports"] != feed["current"][0]["reports"]:
        raise SystemExit("Live pilot did not produce an identical verified PDF in both views")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--feed", type=Path)
    p.add_argument("--live-control", action="store_true")
    p.add_argument("--check-due", action="store_true")
    a = p.parse_args()
    if a.live_control:
        live_control()
        return
    if not a.feed:
        p.error("--feed is required")
    feed = json.loads(a.feed.read_text())
    now = datetime.now(timezone.utc)
    if a.check_due:
        print("due=" + ("true" if eligible(feed, now) else "false"))
    else:
        enrich(feed, now)
        write_feed(a.feed, feed)


if __name__ == "__main__":
    main()
