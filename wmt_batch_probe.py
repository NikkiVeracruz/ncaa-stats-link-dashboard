"""One-time read-only WMT candidate batch. Never writes a production feed.

Tests only public school schedule navigation, exact matched final-game rows,
and explicitly published report links. No guessed document URLs, redirects,
retries on denial, stored PDFs, or historical archive import.
"""
import argparse
import json
import re
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from tracker import collect, directory
from ncaa_poc import fetch_bytes
from university_probe import norm
from university_source_registry import load_registry
from university_link_acquisition_probe import (
    AGENT, Tree, normalized, allowed, get, candidates, cdn_allowed,
    download_link, get_pdf, pdf_identity,
)

MANIFEST = Path(__file__).parent / "research/wmt_batch_candidates.json"
SPORTS = ("WBB", "MBB")
LABELS = ("box score (pdf)", "box score (.pdf)", "gamebook", "box score pdf", "pdf box score")
MAX_CONTROLS = 3
WORKERS = 3

def validate_manifest(data, rows, active):
    baseline = {"vanderbilt", "iowa", "miami_florida", "lsu", "san_jose_state"}
    if not baseline <= set(active):
        raise ValueError("Baseline source registry changed")
    expected = {k for k, v in rows.items() if v["platform"] == "wmt"} - baseline
    if data["schema_version"] != 1 or len(expected) != 24:
        raise ValueError("Candidate scope changed; review directory and active registry")
    items = data["schools"]
    if len(items) != 24 or {x["school"] for x in items} != expected:
        raise ValueError("Batch must cover all 24 remaining schools exactly once")
    for item in items:
        if item["host"] != rows[item["school"]]["site"] or set(item["paths"]) != set(SPORTS):
            raise ValueError("Invalid candidate host or sports")
        if not all(re.fullmatch(r"/sports/[a-z0-9-]+/schedule", p) for p in item["paths"].values()):
            raise ValueError("Invalid schedule navigation path")
    return items

def observed_bucket(url):
    """Only a literal published, well-formed Google Storage PDF URL."""
    try:
        u = urlsplit(url)
        m = re.match(r"^/([a-z0-9][a-z0-9-]{1,100})/", u.path)
        prefix = m.group(0) if m else None
        return prefix if prefix and cdn_allowed(url, prefix) else None
    except ValueError:
        return None

def published_buckets(html, source, labels):
    tree = Tree()
    tree.feed(html)
    return {p for a in tree.root.walk() if a.tag == "a"
            and normalized(a.text()).removeprefix("opens in a new window ").removesuffix(" opens in a new window").strip() in labels
            if (p := observed_bucket(urljoin(source, a.attrs.get("href", ""))))}

def control_rows(games, school, sport, idx):
    def identity(g):
        return (g["date_et"], tuple(sorted(g["team_ids"].values())))
    rows = [g for g in games if g.get("completed") and g["sports"] == [sport]
            and all(g.get("team_ids", {}).get(s) for s in ("home", "away"))]
    counts = Counter(identity(g) for g in rows)
    found = []
    for g in rows:
        sides = g.get("school_keys", {})
        own = [s for s in ("home", "away") if sides.get(s) == school]
        if len(own) != 1 or counts[identity(g)] != 1:
            continue
        side = own[0]
        other = "away" if side == "home" else "home"
        aliases = {a for a in g["team_names"][other] if idx.get(a) == {sides.get(other)}}
        if not sides.get(other) or not aliases or g[side+"_score"] == g[other+"_score"]:
            continue
        found.append((g, side, aliases))
    return sorted(found, key=lambda x: (x[0]["date_et"], x[0]["start_utc"], x[0]["key"]), reverse=True)[:MAX_CONTROLS]

def select_published(html, source, sport, controls):
    """Return one exact published candidate and the parser options used.

    All attempts below operate on the same already-fetched HTML. No extra
    network requests are made for alternate parsing profiles.
    """
    tree = Tree()
    tree.feed(html)
    season = "2026-27"
    sport_name = "women's basketball" if sport == "WBB" else "men's basketball"
    headings = [normalized(n.text()) for n in tree.root.walk() if n.tag in ("h1", "h2")]
    orders = []
    for order, expected in (("season_first", season+" "+sport_name+" schedule"),
                            ("sport_first", sport_name+" "+season+" schedule")):
        if any(expected in h for h in headings):
            orders.append(order)
    if not orders:
        return None, "unsupported_schedule_heading"
    buckets = published_buckets(html, source, LABELS)
    # Multiple unrelated CDN buckets on the page are not blindly followed.
    if len(buckets) > 4:
        return None, "too_many_published_buckets"
    for g, side, aliases in controls:
        other = "away" if side == "home" else "home"
        day = date.fromisoformat(g["date_et"])
        score, opp = g[side+"_score"], g[other+"_score"]
        result = f"{'Win' if score > opp else 'Loss'} {score}-{opp}"
        for order in orders:
            for short in (False, True):
                for flexible in (False, True):
                    opts = {"heading_order": order, "short_result": short,
                            "repeat_date": flexible, "compact_date": flexible,
                            "pdf_labels": list(LABELS)}
                    matches = {}
                    for prefix in [None, *sorted(buckets)]:
                        links = candidates(html, source=source, cdn_prefix=prefix, sport=sport,
                            season=season, day=f"{day.strftime('%b')} {day.day}", result=result,
                            aliases=aliases, include_labels=True, **opts)
                        parent = links.get("pdf_candidate")
                        if parent:
                            matches[parent] = links
                    if len(matches) > 1:
                        return None, "ambiguous_published_pdf"
                    if matches:
                        parent, links = next(iter(matches.items()))
                        return (g, side, parent, links["opponent_labels"], opts), "candidate"
    return None, "no_matching_pdf_link"

def verified_own_name(text, school, g, side, labels, idx, sport):
    """Extract only the named final-score heading, never store page text."""
    other = "away" if side == "home" else "home"
    day = date.fromisoformat(g["date_et"])
    own_score = g[side+"_score"]
    names = set()
    pattern = r"(?im)^[ \t]*([^\r\n]{1,100}?)\s*-\s*" + str(own_score) + r"\s+record\s*:"
    for m in re.finditer(pattern, text):
        name = m.group(1).strip()
        if idx.get(norm(name)) == {school} and any(pdf_identity(
            text, opponent=label, day=f"{day.month}/{day.day}/{day.year%100:02}",
            own_score=own_score, opponent_score=g[other+"_score"],
            season="2026-27", own_name=name, sport=sport) for label in labels):
            names.add(name)
    return next(iter(names)) if len(names) == 1 else None

def probe_school(item, games, idx, rows, active_prefixes):
    school, host = item["school"], item["host"]
    base = "https://" + host
    results = []
    stop = None
    rules = None
    for sport in SPORTS:
        result = {"school": school, "sport": sport, "source": base+item["paths"][sport]}
        controls = control_rows(games, school, sport, idx)
        result["control_count"] = len(controls)
        if stop:
            result.update(status="source_stopped", reason=stop)
        elif not controls:
            result["status"] = "no_unambiguous_recent_final"
        else:
            try:
                if rules is None:
                    raw = get(base+"/robots.txt", "text/plain", host=host)
                    if not re.search(r"(?im)^\s*user-agent\s*:", raw):
                        raise ValueError("Unparseable robots rules")
                    rules = RobotFileParser()
                    rules.parse(raw.splitlines())
                source = result["source"]
                if not rules.can_fetch(AGENT, source):
                    raise ValueError("Robots disallows schedule")
                html = get(source, "text/html", host=host)
                matched, status = select_published(html, source, sport, controls)
                result["status"] = status
                if matched:
                    g, side, parent, labels, opts = matched
                    result.update(control=g["key"], parent=parent)
                    prefix = observed_bucket(parent)
                    pdf = parent
                    if prefix is None:
                        if not allowed(parent, host) or not rules.can_fetch(AGENT, parent):
                            raise ValueError("Robots disallows or unexpected PDF wrapper")
                        wrapper = get(parent, "text/html", host=host)
                        buckets = published_buckets(wrapper, parent, ("download", "download pdf"))
                        if len(buckets) == 1:
                            prefix = next(iter(buckets))
                            pdf = download_link(wrapper, parent, prefix)
                        else:
                            pdf = None
                    if not prefix or not pdf:
                        result["status"] = "unsupported_or_ambiguous_pdf_host"
                    elif prefix in active_prefixes:
                        result["status"] = "bucket_already_registered_to_other_school"
                    else:
                        pdf_text = get_pdf(pdf, prefix)
                        own_name = verified_own_name(pdf_text, school, g, side, labels, idx, sport)
                        if not own_name:
                            result["status"] = "pdf_identity_not_verified"
                        else:
                            result.update(status="verified", pdf=pdf, prefix=prefix,
                                          config={"pdf_name": own_name, "path":item["paths"][sport],
                                                  "control":g["key"], **opts},
                                          game={k:g[k] for k in ("key","sports","date_et","completed",
                                              "school_keys","team_ids","team_names","home_score","away_score")},
                                          side=side)
            except (OSError, ValueError, UnicodeError, RecursionError, subprocess.SubprocessError) as exc:
                result.update(status="source_unavailable", reason=str(exc))
                if (isinstance(exc, HTTPError) and 300 <= exc.code < 500) or "robots" in str(exc).lower():
                    stop = str(exc)
        results.append(result)
        print("WMT_CASE", json.dumps(result, ensure_ascii=False), flush=True)
    return results

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=Path("diagnostics/wmt-batch.json"))
    a = p.parse_args()
    idx, rows = directory()
    active = load_registry()
    manifest = json.loads(MANIFEST.read_text())
    items = validate_manifest(manifest, rows, active)
    start, end = (date.fromisoformat(manifest[k]) for k in ("control_start","control_end"))
    if not 0 <= (end-start).days <= 7:
        raise ValueError("Research control window must be bounded")
    days = [start+timedelta(days=i) for i in range((end-start).days+1)]
    games = list(collect(days, idx, rows, [], groups={d:set(SPORTS) for d in days},
                         fetcher=lambda url:fetch_bytes(url, attempts=1)).values())
    prefixes = {cfg["prefix"] for sports in active.values() for cfg in sports.values()}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = [row for group in pool.map(lambda i:probe_school(i,games,idx,rows,prefixes),items) for row in group]
    if len(results) != 48 or len({(r["school"],r["sport"]) for r in results}) != 48:
        raise ValueError("Incomplete batch results")
    summary = dict(Counter(r["status"] for r in results))
    print("WMT_BATCH_SUMMARY", json.dumps(summary, sort_keys=True), flush=True)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({"read_only":True,"results":results,"summary":summary},indent=2)+"\n")

if __name__ == "__main__":
    main()
