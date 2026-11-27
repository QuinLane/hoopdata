# Ingest test 001

The first run of v1 against the real stats.nba.com API. It checks that one season ingests end to end before the full backfill.

## Setup

- Run from the repo root. The data goes to `./data`, which is gitignored. `NBA_DATA_ROOT` is unset.
- All 37 tests pass first: `uv run pytest -q`.

## Step 1: smoke run on 2024-25

```bash
uv run hoopdata ingest --season 2024-25
```

Expected time: about 10–15 minutes. That's 4 game-log requests plus one bio request per player (about 570 players). Requests are paced 1 second apart, so the bios take most of the time.

Then check:

- [ ] Every item prints "N rows", none says "FAILED", and the exit code is 0. There are 7 items: `player_box_scores`, `team_box_scores` and `games` for both regular season and playoffs, plus `players`.
- [ ] The row counts look right: about 1,230 regular-season games → about 2,460 team box-score rows and about 26,000 player box-score rows.
- [ ] `examples/python` prints averages: `PYTHONIOENCODING=utf-8 uv run examples/python/season_averages.py`
- [ ] Running the same command again doesn't refetch bios. It should take under a minute and print no `players` item.
- [ ] The log file under `data/logs/` has no `ERROR` lines.

## Step 2: empty playoffs on 2026-27

```bash
uv run hoopdata ingest --season 2026-27
```

The 2026-27 season is in progress, so its playoff game logs come back empty. This checks that an empty response gives 0-row items rather than a failure. If it breaks, fix it test-first with an empty fixture.

## Step 3: full backfill

Add the backfill steps to the README, then:

```bash
uv run hoopdata ingest --all-seasons
```

This takes about 45 minutes, mostly bios. After it finishes, register the nightly job with `scripts/register-nightly.ps1`.

## Results

Run on 2026-11-26.

### Step 1: passed, 9.6 minutes

```
player_box_scores 2024-25 Regular Season: 26306 rows
team_box_scores 2024-25 Regular Season: 2460 rows
games 2024-25 Regular Season: 1225 rows
player_box_scores 2024-25 Playoffs: 1804 rows
team_box_scores 2024-25 Playoffs: 168 rows
games 2024-25 Playoffs: 84 rows
players: 569 rows
0 of 7 items failed.
```

- [x] 7 items, none failed, exit code 0. The game logs took 4 seconds and the 569 bios took the rest.
- [x] `examples/python` works, and the numbers match reality (Gilgeous-Alexander 32.7 ppg over 76 games). "Dončić" prints correctly with `PYTHONIOENCODING=utf-8`.
- [x] The rerun took 5 seconds and printed no `players` item, so no bios were refetched.
- [x] Both logs have no `ERROR` lines.

### Step 2: passed, 2.3 minutes

All three 2026-27 playoff items gave 0 rows, not a failure. 129 new players got bios. `player_season_averages` and `standings` query fine with the empty partitions. No fix needed.

### Bug found and fixed: neutral-site games were missing from `games`

2024-25 has 2,460 team box-score rows (1,230 games) but only 1,225 `games` rows. The 5 missing games were all played at neutral sites:

| game_id | Date | Teams | Where |
|---|---|---|---|
| 0022400147 | 2024-11-02 | MIA, WAS | Mexico City |
| 0022401229 | 2024-12-14 | ATL, MIL | NBA Cup semifinal, Las Vegas |
| 0022401230 | 2024-12-14 | HOU, OKC | NBA Cup semifinal, Las Vegas |
| 0022400621 | 2025-01-23 | IND, SAS | Paris |
| 0022400633 | 2025-01-25 | IND, SAS | Paris |

2026-27 is also missing one (540 team rows, 269 `games` rows). `transform.games` pairs one team's ` vs. ` matchup with the other's ` @ `. A neutral-site game doesn't have that pair, so it is silently dropped. The views don't read `games`, so standings and averages are unaffected. The fixtures cover no neutral-site games, so the tests didn't catch it.

The real response shows both matchups read `@` (`MIA @ WAS` and `WAS @ MIA`), so the team game log can't say which team is home. Fixed test-first: these games are now kept with a new `neutral_site` column, and the lower team ID is listed as home. On the real 2024-25 response that gives 1,230 games, 5 of them flagged.

### Step 3: first backfill crashed on a blank bio field (fixed)

The box scores for all 31 seasons were fetched in about 2 minutes. Then the bio step crashed on the first batch: Luc Longley's recorded bio has `WEIGHT` set to one space (`" "`), which `transform.players` didn't treat as empty, so turning it into a number failed. Many older players also have a blank `HEIGHT` and `WEIGHT` (`""`), which was already handled. Because the failure happens while turning the batch into a table, not while fetching a bio, it isn't caught per bio and stops the whole run before it publishes. Fixed test-first by treating `" "` as empty too. 2,220 players still needed bios at that point, about 37 minutes.
