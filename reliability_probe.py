"""Bounded, read-only multi-date NCAA crosswalk coverage snapshot."""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from ncaa_poc import SPORTS, fetch_bytes, process_day


def snapshot(end, days, fetcher=fetch_bytes):
    if not 1 <= days <= 14:
        raise ValueError("days must be between 1 and 14")
    cache = {}
    def cached(url):
        # Reuse exactly the same release bytes for all dates in one observation.
        if url not in cache:
            cache[url] = fetcher(url)
        return cache[url]
    reports = []
    for offset in range(days - 1, -1, -1):
        report = process_day(end - timedelta(days=offset), fetcher=cached)
        reports.append(report)
    return {"read_only": True, "reports": reports,
            "source_errors": [error for r in reports for error in r["source_errors"]]}


def summarize(result):
    for report in result["reports"]:
        print(report["probe_date_et"], "unique games:", report["unique_games"])
        for group in SPORTS:
            counts = report["group_status_counts"][group]
            print(" ", group, counts)
        for family in ("football", "mbb", "wbb"):
            source = report["data_sources"][family]
            print(" ", family, "sha256:", source.get("sha256"), "rows:", source.get("mapping_rows"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--days", type=int, default=7, choices=range(1, 15))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = snapshot(args.end, args.days)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    summarize(result)
    if result["source_errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
