# v2 plan

v2 adds the data the v1 spec (#1) left out of scope. Each new source becomes an optional **dataset** on top of **core**, and a data root holds whatever **selection** its user asked for. Terms are defined in `GLOSSARY.md`. The two lasting decisions are in `docs/adr/0001` and `docs/adr/0002`.

"v2" names this set of work. It is not a schema version: `schema_version` stays `1` unless a change is breaking under the rules in `docs/schema.md`. Every addition planned here (new tables, views and season-type value) is not breaking.

## Scope

| Dataset | What | Likely endpoint | Request grain | Rough first backfill |
|---|---|---|---|---|
| core (+ Play-In) | v1, plus Play-In games as a new season type `PlayIn` | `leaguegamelog`, `season_type=PlayIn` | season × kind | ~14 more requests |
| `advanced` | Official advanced box scores, player and team | `playergamelogs` / `teamgamelogs`, `measure_type=Advanced` | season × season type × kind | ~125 requests |
| `shots` | Shot charts | `shotchartdetail`, per team, player=0 | season × season type × team | ~1,400 requests, ~25 min |
| `rosters` | Official rosters, including players who never appeared, and jersey numbers; head and assistant coaches | `commonteamroster` | team × season | ~930 requests, ~16 min |
| `pbp` | Play-by-play, plus views only it can give (lineups, on/off, who assisted whom) | `playbyplayv3` | game | ~38,000 requests, ~11 h |

Every dataset covers 1996-97 to now (Play-In from when it started). Endpoints were checked against `nba_api` 1.12.0. The league-wide `advanced` calls and the per-team `shots` calls were checked against the live API in their specs (#22, #25). A league-wide `shotchartdetail` returns HTTP 500 for every regular season, so `shots` fetches per team.

Still out of scope: live in-game data, Summer League, seasons before 1996-97, remote storage, GitHub Actions, a REST API, client libraries, notifications and publicly hosted data.

## Findings so far

- **Play-In games are missing today.** The stored data has no `005…` game IDs. `leaguegamelog`'s regular season and playoffs leave them out.
- **Play-by-play v3 goes back to 1996-97.** The 1996-97 opener (`0029600001`) has 500 events, the final score matches the box score (98–107), and 47 substitutions are recorded. `PlayByPlayV2` returns nothing now and is deprecated, so v3 is the only option.
- **Early shot coordinates are sparse.** In that 1996-97 game only 59 of 158 shots have a location in play-by-play, against 170 of 174 in 2024-25. `shotchartdetail` has the same gaps and codes a missing location as (0,0), Restricted Area, 0 ft: 32% of shots in 1996-97, 23% in 2001-02 and 2% in 2024-25 (mostly real tip-ins). Its shot counts match core FGA exactly in every era, and `GAME_EVENT_ID` + player match play-by-play v3's `actionNumber` + player.

## Shared decisions

- **Ratings:** official advanced stats are the only ratings. Play-by-play never recomputes them (ADR 0001).
- **Reconciliation:** summing play-by-play should reproduce the basic box scores. It reports the play-by-play quality for each era instead of us guessing at a cutoff.
- **Play-In:** a new `season_type` value, `PlayIn`, part of core. It starts in 2019-20: NBA labels the bubble game (`0051900111`) `PlayIn`. Earlier seasons have no Play-In items. `standings` filters it out, as NBA's standings do. The averages views already group by `season_type`, so it never mixes into the regular season. `schema.md` notes that `season_type` now has three values.
- **Selection (ADR 0002):** saved as `selection` in `manifest.json`.
  - One season set for the whole data root: every dataset holds the same seasons, either all of them (including future ones) or a fixed list. The selection only grows.
  - `--datasets pbp,shots` or `--datasets all` adds datasets for the seasons already held. `--season X` adds X to every dataset, and `--all-seasons` widens a fixed list to all.
  - Every run does the same thing: fetch failed or missing items in the selection, and refetch the latest season (except `pbp`, which never refetches a game it holds: ADR 0003). `--season X` doesn't force a refetch of a season already held. To redo a season after a bug fix, delete that table's `season=X` folder and run `ingest`.
  - A first run with no `--datasets` loads core only. Plain `ingest` on an empty data root is refused (pass `--season` or `--all-seasons`). A v1 data root with no saved selection becomes core, all seasons.
  - Each dataset except core has its own top-level folder, created as soon as it's added. There is no remove command: delete a dataset's folder and run `ingest` again.
  - Every run prints an estimate of its requests and time per dataset (~1 s per request) before fetching, and `--help` lists each dataset's full-backfill cost. It only warns; it never asks.
- **Consumers:** a dataset outside the selection has no tables or views in `hoopdata.duckdb`. A new `hoopdata_datasets` view lists each loaded dataset, core included, with its `last_updated` and whether it is complete (every item in the selection succeeded). `hoopdata_info` gains `seasons` (`all`, or the list). A partly backfilled dataset is published straight away.
- **One process:** nothing locks `manifest.json`, so two `ingest` runs must never run at once on the same data root. The nightly job stays one command that runs every dataset one after another.

## Order and parallel work

1. **Selection and Play-In first, on their own.** Play-In adds to the shared season-type list that `advanced` and `shots` loop over. The selection changes the CLI and the nightly script that every dataset relies on. Changes:
   - plain `ingest` works without a season flag
   - the nightly script runs plain `ingest`
   - `hoopdata_datasets`
2. **Then `advanced`, `shots`, `rosters` and `pbp` in parallel branches**, merged in that order where possible. They share no design. They touch the same files (`source.py`, the ingest loop, `views.sql`, `schema.md`), so expect small merge conflicts.

## Next steps

Each step gets its own grill session, which produces a GitHub spec issue like #1, broken into vertical-slice tickets:

1. **Selection + Play-In.** Done: spec #15 (tickets #16–#20).
2. **`advanced`.** Done: spec #22 (tickets #23–#24).
3. **`shots`.** Done: spec #25 (tickets #26–#27).
4. **`rosters`.** Done: spec #28 (tickets #29–#30).
5. **`pbp`.** Done: spec #31 (tickets #32–#35). Fetched games are never refetched (ADR 0003).
6. **Lineups and on/off.** Open: needs substitutions parsed (play-by-play names the incoming player only by surname) and the players on the floor at each period start inferred, since play-by-play doesn't record them.
