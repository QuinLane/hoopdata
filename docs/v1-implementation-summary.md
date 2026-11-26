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
