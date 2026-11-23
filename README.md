# NCAA Stats link dashboard — proof of concept

This is an **isolated, read-only feasibility study**, not a deployed dashboard.
No NFL, NBA, WNBA, NHL, MLB or Mega Board source file, workflow or data is
referenced or changed. NCAA will remain a separate site unless expressly approved later.

## Goal

For newly tracked FBS and FCS football games and NCAA Division I men's and women's
basketball games, create a **candidate link to the existing NCAA Stats box score**
without scraping NCAA Stats, collecting player statistics, downloading gamebooks,
or restoring historical games.

A unique SportsDataverse crosswalk mapping from an ESPN game ID to an NCAA contest ID
allows constructing a URL of the form
`https://stats.ncaa.org/contests/1234567/box_score`.
A generated URL is **not** called verified: these reports may be inaccessible,
absent, or different from the expected game. NCAA Stats itself may block automation.
Never guess an NCAA ID from a matchup or date.

## Standalone design

- ESPN scoreboards: football FBS group 80, FCS group 81; men's/women's D-I
  basketball group 50. An ESPN football crossover appearing twice is deduplicated.
- SportsDataverse public 2026 football schedule and 2026–27 MBB/WBB schedule
  crosswalk releases: ESPN IDs and NCAA Stats IDs. A release missing, a changed
  schema, an ambiguous mapping or an identity conflict suppresses links.
- Only a **single explicitly requested date** is processed. There is no scheduled
  action, archival persistence, Pages deployment, scoreboard publishing, or writeback.
- JSON diagnostics report games, source errors and matched IDs separately for
  FBS, FCS, MBB and WBB, for coverage assessment. Zero returned events does
  *not* prove a complete schedule.
- Python 3.11+ standard library only. All requests are public HTTPS.
  No credentials, proxy bypasses, paid services or external repositories required.

## Run locally

```bash
python -m unittest discover -s tests -v
python ncaa_poc.py --date 2026-11-23 --output report.json
```

This creates only a local report. If upstream sources fail, the command exits
nonzero and clearly marks those sources unavailable; it still writes diagnostics.

## GitHub checks

`.github/workflows/pre-merge-safety.yml` runs offline tests, plus two **read-only**
source trials (2026-11-21 football and 2026-11-22 basketball), on pull requests.
A failed source validation must be investigated before merging; it is not
acceptable to bypass or weaken the checks for a green mark.

`.github/workflows/probe.yml` provides a **manual** workflow for one selected
Eastern date and uploads its JSON result as a temporary diagnostic artifact.
It has no schedule. The manual workflow may require navigating GitHub's
Actions tab; GitHub connector support for launching arbitrary workflows varies.

## Link-status meanings

- `id_matched_page_not_verified`: unique ESPN → NCAA ID mapping published;
  generated link **not independently browser-verified**.
- `no_contest_id`: tracked game lacks a published NCAA contest ID.
- `ambiguous_contest_id`: more than one NCAA ID; no URL is shown.
- `source_unavailable`: mapping unavailable; no URL shown.
- `identity_conflict` or `cross_sport_conflict`: inconsistent game identities;
  suppress links rather than guess.

## Sources

- https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/ncaa_mfb_schedule
- https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/mbb_crosswalk
- https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/wbb_crosswalk
- https://stats.ncaa.org/

These are third-party ID mappings and NCAA-operated destinations. Before a
dashboard is approved, check live season coverage, data freshness, smaller
conference coverage, correct ID-to-game matches, links in an ordinary browser,
and any relevant access or reuse terms. Do not publish a link just because
it fits the URL pattern.

## No-go boundaries

Do **not** deploy a production board, introduce NCAA into the existing Mega Board,
or claim that every completed game has an NCAA Stats page on the basis of this
prototype. That requires its own evidence and explicit approval.

Governance decision: `NCAA-POC-001` in
[the central Mega Board register](https://github.com/NikkiVeracruz/nfl-gamebook-dashboard/blob/main/PROJECT_REGISTER.md).
