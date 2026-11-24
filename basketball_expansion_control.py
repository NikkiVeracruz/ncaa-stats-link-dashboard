"""Read-only live controls for the two basketball sports; no production writes."""
import copy
from datetime import datetime
from university_discovery import enrich

NOW = datetime.fromisoformat("2026-11-24T15:10:00+00:00")
CONTROLS = (
    ("wbb:401912970", "WBB", "lsu", "belmont", "99", "2057", "lsu", "belmont", 103, 45),
    ("mbb:401921664", "MBB", "uc_san_diego", "san_jose_state", "28", "23", "ucsandiego", "sanjosst", 79, 88),
    ("wbb:401916019", "WBB", "tennessee_martin", "virginia_tech", "2630", "259", "utmartin", "virginiatech", 41, 85),
)

def fixture():
    rows = []
    for key, sport, home, away, hid, aid, hname, aname, hs, ass in CONTROLS:
        rows.append({"key": key, "sports": [sport], "date_et": "2026-11-23",
                     "completed": True, "final_seen_at": "2026-11-24T08:06:13+00:00",
                     "school_keys": {"home": home, "away": away},
                     "team_ids": {"home": hid, "away": aid},
                     "team_names": {"home": [hname], "away": [aname]},
                     "home_score": hs, "away_score": ass, "reports": []})
    return {"archive_start": "2026-11-23", "current": copy.deepcopy(rows), "archive": rows}

def main():
    feed = fixture()
    enrich(feed, NOW)
    missing = []
    for g, current in zip(feed["archive"], feed["current"]):
        if not g["reports"] or current["reports"] != g["reports"]:
            missing.append(g["key"])
        else:
            print("BASKETBALL EXPANSION VERIFIED", g["key"], g["reports"][0]["url"], flush=True)
    if missing:
        raise SystemExit("Expansion controls not verified: " + ", ".join(missing))

if __name__ == "__main__":
    main()
