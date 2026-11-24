"""One bounded public demo API comparison; diagnostic only, never creates Stats URLs."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

URL = "https://ncaa-api.henrygd.me/scoreboard/football/fbs/2026/12/all-conf"
REFERENCE = Path(__file__).parent / "research/fbs_reference_2026-11-21.json"
DAY = "2026-11-21"
ET = ZoneInfo("America/New_York")

def name_key(name):
    name = unicodedata.normalize("NFKC", name).casefold()
    name = re.sub(r"\bst\.", "state", name)
    return re.sub(r"[^a-z0-9]", "", name)

def valid_id(value):
    return isinstance(value, (str, int)) and re.fullmatch(r"[1-9][0-9]{0,14}", str(value))

def key(teams):
    return tuple(sorted((name_key(t["name"]), int(t["score"])) for t in teams))

def game_date(game):
    epoch = game.get("startTimeEpoch")
    if epoch and str(epoch).isdigit():
        value = int(epoch)
        if value > 100000000000:
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc).astimezone(ET).date().isoformat()
    for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(game.get("startDate", ""), fmt).date().isoformat()
        except ValueError:
            pass
    return None

def compare(reference, payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list) or not payload["games"]:
        raise ValueError("Missing or empty games array")
    if len({r["id"] for r in reference}) != len(reference):
        raise ValueError("Duplicate reference ID")
    candidates = []
    rejected = Counter()
    for wrapper in payload["games"]:
        if not isinstance(wrapper, dict) or not isinstance(wrapper.get("game"), dict):
            raise ValueError("Unexpected scoreboard record")
        g = wrapper["game"]
        if game_date(g) != DAY:
            rejected["other_or_unknown_date"] += 1
            continue
        if g.get("gameState") != "final":
            rejected["not_final"] += 1
            continue
        try:
            sides = [g[s] for s in ("away", "home")]
            if not valid_id(g["gameID"]):
                raise ValueError("invalid ID")
            names = [s["names"]["short"] for s in sides]
            scores = [str(s["score"]) for s in sides]
            if any(not isinstance(x, str) or not name_key(x) for x in names) or any(not x.isdecimal() for x in scores):
                raise ValueError("invalid identity")
            candidates.append((str(g["gameID"]), key([{"name":n,"score":s} for n,s in zip(names,scores)])))
        except (KeyError, TypeError, ValueError):
            rejected["invalid_identity"] += 1
    ids = Counter(i for i,k in candidates)
    rows = []
    for r in reference:
        if r["date"] != DAY or not valid_id(r["id"]):
            raise ValueError("Invalid reference")
        matches = [i for i,k in candidates if k == key(r["teams"])]
        status = "unmatched"
        if len(matches) > 1 or any(ids[i] > 1 for i in matches):
            status = "ambiguous"
        elif matches:
            status = "equal" if matches[0] == r["id"] else "different"
        rows.append({"reference_id":r["id"],"teams":r["teams"],"ncaa_com_ids":matches,"status":status})
    return {"source":URL,"date":DAY,"reference_count":len(reference),"source_games":len(payload["games"]),
            "eligible_source_games":len(candidates),"rejected":dict(rejected),"results":dict(Counter(r["status"] for r in rows)),
            "comparisons":rows,"production_approved":False}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--offline", type=Path)
    a = p.parse_args()
    report = {"source":URL,"production_approved":False}
    try:
        reference = json.loads(REFERENCE.read_text())
        if len(reference) != 58:
            raise ValueError("Incomplete reference")
        if a.offline:
            raw = a.offline.read_bytes()
        else:
            # Public demo's documented scoreboard route, one request, no redirects or retries.
            with build_opener(NoRedirect()).open(Request(URL, headers={"Accept":"application/json","User-Agent":"ncaa-link-research/0.1"}), timeout=25) as response:
                raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Response size limit")
        report = compare(reference,json.loads(raw))
        report["offline"] = bool(a.offline)
    except (OSError, ValueError, TypeError, OverflowError) as e:
        report["error"] = f"{type(e).__name__}: {e}"
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k!="comparisons"},indent=2))
    for row in report.get("comparisons",[]):
        print(row["reference_id"],row["ncaa_com_ids"],row["status"])
    # A comparison with different IDs is meaningful evidence, not a deployment pass.
    # A failed retrieval or zero comparable games is inconclusive and fails CI.
    return 1 if "error" in report or not any(r["status"] in ("equal","different") for r in report.get("comparisons",[])) else 0

if __name__ == "__main__":
    raise SystemExit(main())
