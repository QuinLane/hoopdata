# v1 implementation summary

The spec in #1 was built on the integration branch `issue-001` and merged through PR #12, which closes #1 and tickets #3–#10. Ticket #2, the first slice, had already been merged through PR #11. When the work finished, all 37 tests passed.

## What was built

| Ticket | What |
|---|---|
| #3 | A TypeScript example that prints the same `player_season_averages` as the Python example |
| #4 | Team box scores, a `games` table (home and away worked out from the matchup text), and the `team_game_stats`, `team_season_averages` and `standings` views |
| #5 | The `player_teams` and `team_rosters` views. The test data includes Pascal Siakam's mid-season trade from Toronto to Indiana |
| #6 | The `players` and `teams` tables. Bios are fetched only for players not yet stored, and undrafted players get empty draft fields |
| #7 | The manifest and the `hoopdata_info` view. The DuckDB file is rebuilt only when the views change or the data root moves |
| #8 | Multiple seasons and the refresh policy. The latest season is refetched every run; completed older seasons are fetched once |
| #9 | A failed item is recorded and skipped, and the next run retries only that item. The CLI exits 1 when anything failed, and each run writes its own log file |
| #10 | `scripts/register-nightly.ps1` sets up a daily 6am Task Scheduler job that runs after a missed start |

## What the code review fixed

- **Bio failures:** a failed bio download no longer crashes the run. It is recorded as a `players` item in the manifest, and the run still finishes.
- **Resumable bios:**
  - Bios are saved every 20 players.
  - Missing bios are worked out from every stored box score, not just this run's.
  - Before this, a crash during the first backfill lost all the bios fetched, and players from completed older seasons never got bios afterwards.
- **Trade games in the test data:** the team test data now covers all of Siakam's trade games. A new test checks that every box-score game has exactly one `games` row.
- **Cleanups:**
  - Clearer names.
  - A flatter ingest loop.
  - The manifest queries moved into `Store`.
  - One shared atomic-write helper.
  - Column typing driven by one map in `transform`.

## Left unchanged on purpose

- **Rebuild hash:** the hash that decides whether to rebuild the DuckDB file stays. #7's rebuild rule needs it.
- **`teams` outside `source`:** `teams` comes straight from `nba_api`'s bundled team list. The spec limits `source` to three calls.
- **Duplicated SQL:** the team views largely repeat the player views' SQL.
- **Extra request:** each run with new players also fetches the full player list once. The per-player call already has every bio field, so dropping it would be a small change.

## Things to know

- **Slow tests:** the suite takes about 50 seconds, because some tests run a full 1996-97-onwards ingest against the test data.
- **Unicode names on Windows:** the Python example crashes on names like "Dončić" in a Windows console unless `PYTHONIOENCODING=utf-8` is set. The problem predates v1 and was left as is.

## First real ingest (test 001)

v1 was tested against the real stats.nba.com API on 2026-11-26. The details are in `docs/ingest_test001.md`.

- **2024-25 smoke run:** passed in 9.6 minutes. All 7 items succeeded and the exit code was 0. The game logs took 4 seconds and the 569 bios took the rest, at about 1 second each. Running it again took 5 seconds and refetched no bios. The Python example's numbers match reality, and the logs have no errors.
- **2026-27 empty playoffs:** passed in 2.3 minutes. The in-progress season's playoff items came back as 0 rows, not failures. The views query fine with the empty partitions, so no fix was needed. Only the 129 players without bios were fetched.
- **Bug, neutral-site games (fixed):** the `games` table dropped games played at neutral sites (Mexico City, Paris, the NBA Cup semifinals in Las Vegas): 5 games in 2024-25 and 1 so far in 2026-27. `transform.games` needs one team's `vs.` matchup and the other's `@`, and these games don't have that pair, because both matchups read `@`. Standings and averages were unaffected because no view reads `games`. The test data has no neutral-site games, so the tests missed it. The fix keeps them with a new `neutral_site` column, and the lower team ID is listed as home.
