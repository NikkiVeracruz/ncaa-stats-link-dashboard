"""Individually exercise production acquisition and queue for seven research controls.

Fixtures are read-only evidence. Simulated historical time never affects the real
archive cutoff, and no production feed is read or written.
"""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from university_discovery import enrich, eligible

RESULTS = Path(__file__).parent / "research/wmt_batch_results.json"

def cases():
    return [r for r in json.loads(RESULTS.read_text())["results"] if r["status"] == "verified"]

def fixture(r):
    g = copy.deepcopy(r["game"])
    final_seen = datetime.fromisoformat(g["date_et"]).replace(tzinfo=timezone.utc)+timedelta(days=1)
    g["final_seen_at"] = final_seen.isoformat()
    g["reports"] = []
    return {"archive_start":g["date_et"],"current":[copy.deepcopy(g)],"archive":[g]},final_seen+timedelta(minutes=30)

def main():
    failures = []
    for r in cases():
        feed, now = fixture(r)
        before = copy.deepcopy(feed["archive"][0])
        due = eligible(feed, now)
        if len(due) != 1 or due[0][1] != r["side"]:
            failures.append(r["control"]+": incorrect eligibility")
            continue
        report = enrich(feed, now)
        if (not report or report["url"] != r["pdf"] or report["verification"] != "automatic_final_pdf_identity" or
                feed["current"][0]["reports"] != feed["archive"][0]["reports"] or
                {k:v for k,v in feed["archive"][0].items() if k!="reports"} != {k:v for k,v in before.items() if k!="reports"}):
            failures.append(r["control"]+": live report not verified")
        else:
            print("ACTIVATION VERIFIED",r["school"],r["sport"],r["control"],report["url"],flush=True)
    if failures:
        raise SystemExit("Activation controls failed: "+"; ".join(failures))

if __name__ == "__main__":
    main()
