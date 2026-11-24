"""Validated school/sport configuration. No network I/O or URL guessing."""
import json
import re
from pathlib import Path

REGISTRY = Path(__file__).with_name("university_sources.json")

def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate university registry key: " + key)
        result[key] = value
    return result

def validate_registry(data, directory_rows):
    if not isinstance(data, dict) or set(data) != {"schema_version", "schools"} or data["schema_version"] != 1 or not isinstance(data["schools"], dict):
        raise ValueError("Invalid university registry schema")
    result = {}
    prefixes = set()
    for key, school in data["schools"].items():
        if not isinstance(school, dict) or set(school) != {"name", "host", "platform", "prefix", "sports"}:
            raise ValueError("Invalid school fields: " + key)
        row = directory_rows.get(key)
        host, prefix = school["host"], school["prefix"]
        if (not row or school["platform"] != "wmt" or row["platform"] != "wmt" or
                not isinstance(host, str) or host != row["site"] or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)+", host) or
                not isinstance(prefix, str) or not re.fullmatch(r"/[a-z0-9][a-z0-9-]{1,100}/", prefix) or prefix in prefixes or
                not isinstance(school["name"], str) or not school["name"].strip() or
                not isinstance(school["sports"], dict) or not school["sports"]):
            raise ValueError("Unverified school host/platform or invalid PDF bucket: " + key)
        prefixes.add(prefix)
        result[key] = {}
        for sport, cfg in school["sports"].items():
            required = {"pdf_name", "path", "status", "control", "validation_run"}
            optional = {"pdf_labels", "heading_order", "short_result", "repeat_date", "compact_date"}
            if (sport not in ("WBB", "MBB") or not isinstance(cfg, dict) or not required <= set(cfg) or set(cfg) - required - optional):
                raise ValueError("Invalid sport configuration: " + key)
            if (cfg["status"] != "verified" or not isinstance(cfg["control"], str) or
                    not re.fullmatch(sport.lower() + r":\d+", cfg["control"]) or
                    type(cfg["validation_run"]) is not int or cfg["validation_run"] <= 0 or
                    not isinstance(cfg["pdf_name"], str) or not cfg["pdf_name"].strip() or
                    not isinstance(cfg["path"], str) or not re.fullmatch(r"/sports/[a-z0-9-]+/schedule", cfg["path"])):
                raise ValueError("Missing valid source evidence: " + key)
            labels = cfg.get("pdf_labels", ["box score (pdf)"])
            if not isinstance(labels, list) or not labels or any(not isinstance(v, str) or not v.strip() or v != v.lower() for v in labels):
                raise ValueError("Invalid PDF link labels: " + key)
            if cfg.get("heading_order", "season_first") not in ("season_first", "sport_first"):
                raise ValueError("Invalid heading format: " + key)
            if any(type(cfg.get(flag, False)) is not bool for flag in ("short_result", "repeat_date", "compact_date")):
                raise ValueError("Invalid parser flags: " + key)
            result[key][sport] = {"name": school["name"], "host": host, "prefix": prefix, **cfg, "sport": sport}
    return result

def load_registry(path=REGISTRY):
    from tracker import directory
    _, rows = directory()
    return validate_registry(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs), rows)

if __name__ == "__main__":
    sources = load_registry()
    print("Validated school/sport combinations:", sum(len(v) for v in sources.values()))
