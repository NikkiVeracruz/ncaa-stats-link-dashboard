"""Limited production PDF discovery: Vanderbilt women's basketball only.

Uses the same bounded, robots-aware source as the successful read-only probe.
Never modifies game identities, scores, archive membership, or existing reports.
No stored source documents, no guessed destinations, no NCAA Stats access.
"""
import argparse
import json
import re
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.robotparser import RobotFileParser

from link_enrichment import slot
from tracker import directory, write_feed
from university_probe import norm
from university_link_acquisition_probe import (
    AGENT, BASE, SOURCE, candidates, get, download_link, get_pdf, pdf_identity,
)

SOURCE_NAME = "reviewed_links_plus_vanderbilt_wbb_pdf_pilot"
STATE_KEY = "university_discovery"


def state_for(feed):
    state = feed.setdefault(STATE_KEY, {})
    if not isinstance(state, dict) or not isinstance(state.setdefault("slots", {}), dict):
        raise ValueError("Invalid optional source state")
    return state


def eligible(feed, now):
    state = state_for(feed)
    if state.get("blocked"):
        return []
    pool = {g["key"]: g for g in feed["current"] + feed["archive"]}
    result = []
    for g in pool.values():
        if (not g.get("completed") or "WBB" not in g["sports"] or
                g["date_et"] < feed["archive_start"] or
                any(r.get("kind") == "pdf_box_score" for r in g.get("reports", []))):
            continue
        sides = g.get("school_keys", {})
        own = [s for s in ("home", "away") if sides.get(s) == "vanderbilt"]
        if len(own) != 1 or not all(g.get("team_ids", {}).get(s) for s in ("home", "away")):
            continue
        other = "away" if own[0] == "home" else "home"
        if not sides.get(other) or not g.get("team_names", {}).get(other):
            continue
        # A same-day repeat matchup is not safe to identify by schedule row.
        if sum(h["date_et"] == g["date_et"] and "WBB" in h["sports"] and
               set(h.get("team_ids", {}).values()) == set(g["team_ids"].values())
               for h in pool.values()) != 1:
            continue
        due = slot(g, now)
        if due is None or state["slots"].get(g["key"]) == list(due):
            continue
        result.append((g, own[0], due))
    return sorted(result, key=lambda x: (x[0]["final_seen_at"], x[0]["key"]))


def acquire(g, own):
    if not shutil.which("pdftotext"):
        raise OSError("PDF verification dependency unavailable")
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
    rules = get(BASE + "/robots.txt", "text/plain")
    if not re.search(r"(?im)^\s*user-agent\s*:", rules):
        raise ValueError("Unparseable robots rules")
    robots = RobotFileParser()
    robots.parse(rules.splitlines())
    if not robots.can_fetch(AGENT, SOURCE):
        raise ValueError("Robots disallows schedule")
    links = candidates(
        get(SOURCE, "text/html"), aliases=aliases, include_labels=True, season=season,
        day=f"{day.strftime('%b')} {day.day}",
        result=f"{'Win' if own_score > other_score else 'Loss'} {own_score}-{other_score}",
    )
    parent = links.get("pdf_candidate")
    if not parent:
        return None
    if not robots.can_fetch(AGENT, parent):
        raise ValueError("Robots disallows PDF wrapper")
    pdf_url = download_link(get(parent, "text/html"), parent)
    if not pdf_url:
        return None
    pdf_text = get_pdf(pdf_url)
    if not any(pdf_identity(pdf_text, opponent=label, day=f"{day.month}/{day.day}/{day.year % 100:02}",
                            own_score=own_score, opponent_score=other_score, season=season)
               for label in links["opponent_labels"]):
        return None
    return {"kind": "pdf_box_score", "url": pdf_url, "school": "Vanderbilt University",
            "side": own, "verification": "automatic_final_pdf_identity",
            "source_url": SOURCE, "parent_url": parent}


def enrich(feed, now, fetcher=acquire):
    state = state_for(feed)
    feed["optional_discovery_source"] = SOURCE_NAME
    # Keep state only for the short eligibility window; links live in the archive.
    pool = {g["key"]: g for g in feed["current"] + feed["archive"]}
    state["slots"] = {k: v for k, v in state["slots"].items()
                      if k in pool and pool[k].get("completed") and slot(pool[k], now) is not None}
    due = eligible(feed, now)
    if not due:
        return None
    # One source/game per run, no retries within a slot and no concurrent requests.
    g, own, current_slot = due[0]
    state["slots"][g["key"]] = list(current_slot)
    state["last_attempt"] = {"key": g["key"], "at": now.isoformat()}
    try:
        report = fetcher(g, own)
    except (OSError, ValueError, UnicodeError, RecursionError, subprocess.SubprocessError) as exc:
        # Explicit access denial, rate limit, redirect, or robots failure disables
        # further requests until reviewed. Temporary errors are not hidden.
        if (isinstance(exc, HTTPError) and 300 <= exc.code < 500) or "robots" in str(exc).lower():
            state["blocked"] = True
        state["last_attempt"]["result"] = "source_unavailable"
        print("OPTIONAL UNIVERSITY SOURCE UNAVAILABLE:", str(exc), flush=True)
        return None
    if report is None:
        state["last_attempt"]["result"] = "no_verified_pdf"
        print("OPTIONAL UNIVERSITY SOURCE: no verified PDF for", g["key"], flush=True)
        return None
    # Current and archive arrays may contain separately deserialized copies.
    for row in feed["current"] + feed["archive"]:
        if row["key"] == g["key"] and not any(r.get("kind") == "pdf_box_score" for r in row.get("reports", [])):
            row.setdefault("reports", []).append(dict(report))
    state["last_attempt"]["result"] = "verified_pdf"
    print("OPTIONAL UNIVERSITY PDF VERIFIED:", json.dumps({"key": g["key"], "url": report["url"]}), flush=True)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--feed", required=True, type=Path)
    p.add_argument("--check-due", action="store_true")
    a = p.parse_args()
    feed = json.loads(a.feed.read_text())
    now = datetime.now(timezone.utc)
    if a.check_due:
        print("due=" + ("true" if eligible(feed, now) else "false"))
    else:
        enrich(feed, now)
        write_feed(a.feed, feed)


if __name__ == "__main__":
    main()
