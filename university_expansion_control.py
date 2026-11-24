"""Read-only expansion controls, matching already tracked games. No production writes."""
import copy
from datetime import datetime
from university_discovery import enrich, SOURCES

NOW = datetime.fromisoformat("2026-11-24T14:00:00+00:00")
CONTROLS = (
    ("wbb:401921427", "utah", "iowa", "254", "2294", "utah", "iowa", 66, 75),
    ("wbb:401913729", "michigan", "miami_florida", "130", "2390", "michigan", "miami", 79, 58),
)

def fixture():
    rows = []
    for key, home, away, hid, aid, hname, aname, hs, ass in CONTROLS:
        rows.append({"key": key, "sports": ["WBB"], "date_et": "2026-11-23",
                     "completed": True, "final_seen_at": "2026-11-24T02:51:30+00:00",
                     "school_keys": {"home": home, "away": away},
                     "team_ids": {"home": hid, "away": aid},
                     "team_names": {"home": [hname], "away": [aname]},
                     "home_score": hs, "away_score": ass, "reports": []})
    return {"archive_start": "2026-11-23", "current": copy.deepcopy(rows), "archive": rows}

def main():
    feed = fixture()
    enrich(feed, NOW)
    for g, current in zip(feed["archive"], feed["current"]):
        if not g["reports"] or current["reports"] != g["reports"]:
            raise SystemExit("Expansion live control not verified: " + g["key"])
        print("EXPANSION VERIFIED", g["key"], g["reports"][0]["url"], flush=True)

if __name__ == "__main__":
    main()
