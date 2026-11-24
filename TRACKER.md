# Standalone NCAA tracker

Approved Nov 23, 2026. A navigation aid for trained agents; no player statistics extraction, no SportsDataverse runtime dependency, no historical backfill, no changes to the professional Mega Board.

## Current windows and archive
FBS/FCS: Thursday through Wednesday, rollover Thursday 3 AM Eastern. Men's/women's basketball: yesterday, today and tomorrow, rollover daily 3 AM Eastern. Unresolved tracked games survive rollover. Source requests use proven single-day scoreboard queries; truncated responses fail without overwriting prior state. Multi-day range requests returned HTTP 400 in staging and are not used. Completed games archive immediately independent of links. First-run archive start is the actual Eastern calendar date; subsequent runs reuse it. Old dates fetched solely for previously tracked pending games cannot import new historical records. A failed source fetch leaves the prior durable feed intact. The feed is atomically written; git history on ncaa-data retains prior versions.

## Link hierarchy and optional discovery
Every game gets NCAA division scoreboard navigation, and school schedules/homepages when unambiguously mapped. Standard schedule paths are navigation shortcuts, not verified game report destinations. Individual reviewed Game Center, online box score and PDF box score/gamebook links can be added independently. Prefer home school, then away; keep existing links. Missing optional links are not failures. The timing engine targets hourly pregame Game Center eligibility; after final first observed, 5 minutes for hour one, 15 minutes for the next three hours, hourly until 24 hours total, then no further enrichment. Persist final_seen_at and last slots; archive rollover doesn't cancel the window. Actual times may vary with scheduler delay. Reviewed sources only: reviewed_game_links.json contains independently reviewed observations, with kind, sport, date, school, both team names and scores for final reports, URL and reviewed=true. PDFs require a reviewed official school parent URL. Exact ESPN ID is preferred; same-day ambiguities without ID are rejected. No guessed game IDs, no school scraping or blocked-access retries. At present no authorized automatic university source is configured: the timing engine processes reviewed observations, not new remote school reports. School schedule and NCAA navigation remain fully useful; no routine manual submissions required. The Ohio State/Michigan Game Center observation is a current upcoming example, not a backfill.

## Preview
Run from root:
```sh
python tracker.py --output preview/feed.json
cp site/index.html site/app.js site/style.css preview/
python -m http.server 8000 --directory preview
```
Current and archive filters are separate; sport dropdowns retain expanded state and contain full instructions even when no games are present. Browser polls the feed once per minute; upstream updates target every five minutes after activation.

## Activate standalone Pages
Repo Settings > Pages > Build and deployment > Source: GitHub Actions. Then Actions > NCAA tracker update and publish > Run workflow on main. Verify first successful update and deployment, check live URL and data branch. Once verified, Settings > Secrets and variables > Actions > Variables > New repository variable: NCAA_TRACKER_ENABLED=true. This enables the five-minute scheduled workflow (GitHub may delay runs). The workflow serializes updates, loads prior ncaa-data/feed.json, persists new data before Pages publish, and never commits to main. Manual runs work without the schedule variable. No pre-merge workflow writes production data. If first activation fails, investigate; do not enable recurring execution before the cause is resolved. No paid services.

## Scheduling experiment
Observed Nov 23–24: ten successful scheduled runs, roughly 54–86 minutes apart despite a five-minute cron. Offset to `2-57/5 * * * *` (minutes 02, 07, …, 57), preserving all 12 slots per hour; GitHub's documented best-effort schedule may still delay/drop events. This is a mitigation trial, not a guaranteed timing fix. No additional scheduler, paid service, or monitoring changes. Verify actual scheduled run intervals after merge.
