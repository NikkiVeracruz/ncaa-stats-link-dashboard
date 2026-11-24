# Standalone NCAA tracker — initial implementation

This is a staged, practical navigation aid for trained agents, not a statistical authority. The user approved building it Nov 23, 2026. Keep the professional Mega Board unchanged. No automated university-page requests, no SportsDataverse runtime dependency, no individual player data, no paid services.

Run from the repository root:
```sh
python tracker.py --archive-start "$(TZ=America/New_York date +%F)" --output preview/feed.json
cp site/index.html site/app.js site/style.css preview/
python -m http.server 8000 --directory preview
```

The preview uses today's and yesterday's Eastern dates; current display includes scheduled, live and completed games. The initial archive cutoff is today's date and cannot be silently changed. No backfill. Completed games are archived independent of links. Reuse the original archive start on later runs with the same feed. A failed source read leaves the existing file unchanged. Pending games retained from earlier runs are not inferred final; longer outage reconciliation and production scheduling are future activation details. Use the actual current date when activating; do not seed with historical research fixtures.

Common platform schedule paths are explicitly labeled navigation shortcuts, not verified destinations. Athletics homepages and official NCAA division scoreboards remain fallbacks. Optional reviewed_reports.json accepts reviewed game-specific links with exact ESPN ID, school key, sport, date, two teams with scores, report=box_score and reviewed=true; never guessed or automatically retrieved from restricted pages. The file starts empty. Agents are not required to submit links. Search/archive separate, sections collapsed, refresh manually or once per minute from the generated feed. Preview refresh is not an upstream polling schedule.

Pre-merge creates a disposable live-data preview artifact. No Pages deployment or scheduled data writer is enabled yet. Approval of production activation/rollover and deployment verification remain separate. Existing research and safeguards remain intact.
