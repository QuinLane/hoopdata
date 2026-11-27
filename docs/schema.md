# hoopdata schema

Consumers open `hoopdata.duckdb` in the data root **read-only** and query the views below. The file holds only views. They read the Parquet files in the data root by absolute path, so new data shows up without rebuilding anything.

```python
import duckdb
con = duckdb.connect("path/to/data/hoopdata.duckdb", read_only=True)
con.sql("select * from player_season_averages").df()
```

## Conventions

- **Keys** are NBA's own IDs. `game_id` is a string with leading zeros kept (`0022300061`). `player_id` and `team_id` are integers.
- **`season`** is a string like `2023-24`.
- **`season_type`** is `Regular Season`, `PlayIn` or `Playoffs`. Play-In games exist from 2019-20 on (including the 2019-20 bubble game NBA labels Play-In); earlier seasons have none.
- **Stored tables hold raw counts only.** Every percentage is calculated in a view.
- **Missing values** are `NULL`; integer columns stay integers.

## Tables

### `player_box_scores`

One row per player per game. Source: the stats.nba.com league game log (players). Stored as Parquet under `player_box_scores/season=<season>/`, one file per season type (`regular_season.parquet`, `playin.parquet`, `playoffs.parquet`).

| Column | Type | Meaning |
|---|---|---|
| `season` | VARCHAR | Season, like `2023-24` |
| `season_type` | VARCHAR | `Regular Season`, `PlayIn` or `Playoffs` |
| `game_id` | VARCHAR | NBA game ID, leading zeros kept |
| `game_date` | DATE | Date the game was played |
| `player_id` | BIGINT | NBA player ID |
| `player_name` | VARCHAR | Player's name as listed in that game |
| `team_id` | BIGINT | NBA team ID the player played for in that game |
| `team_abbreviation` | VARCHAR | Team abbreviation at the time of the game (`SEA`, not `OKC`) |
| `team_name` | VARCHAR | Team name at the time of the game |
| `wl` | VARCHAR | `W` or `L` for the player's team |
| `min` | BIGINT | Minutes played |
| `fgm`, `fga` | BIGINT | Field goals made, attempted |
| `fg3m`, `fg3a` | BIGINT | Three-pointers made, attempted |
| `ftm`, `fta` | BIGINT | Free throws made, attempted |
| `oreb`, `dreb`, `reb` | BIGINT | Offensive, defensive, total rebounds |
| `ast` | BIGINT | Assists |
| `stl` | BIGINT | Steals |
| `blk` | BIGINT | Blocks |
| `tov` | BIGINT | Turnovers |
| `pf` | BIGINT | Personal fouls |
| `pts` | BIGINT | Points |
| `plus_minus` | BIGINT | Point differential while the player was on court |

Not stored from the source: per-game percentages, fantasy points, video-available and the matchup text.

### `team_box_scores`

One row per team per game. Source: the stats.nba.com league game log (teams). Stored as Parquet under `team_box_scores/season=<season>/`.

The same columns as `player_box_scores` without `player_id` and `player_name`. `team_abbreviation` and `team_name` are as they were at the time of the game, `wl` is the team's result, `min` is total team minutes (240 for a regulation game), and `plus_minus` is the final point margin.

Not stored from the source: per-game percentages, video-available and the matchup text.

### `games`

One row per game. Derived from the team game log with no extra requests: the team whose matchup reads `vs.` is home, the one whose matchup reads `@` is away. At a neutral site (Mexico City, Paris, the NBA Cup semifinals in Las Vegas) both matchups read `@`, so the game is flagged `neutral_site`, and home and away only put the two teams in order: the lower team ID is home. Stored as Parquet under `games/season=<season>/`.

| Column | Type | Meaning |
|---|---|---|
| `game_id` | VARCHAR | NBA game ID, leading zeros kept |
| `season` | VARCHAR | Season, like `2023-24` |
| `season_type` | VARCHAR | `Regular Season`, `PlayIn` or `Playoffs` |
| `game_date` | DATE | Date the game was played |
| `neutral_site` | BOOLEAN | Played at a neutral site. When true, home and away only order the teams: the lower team ID is home |
| `home_team_id` | BIGINT | Home team's NBA team ID |
| `away_team_id` | BIGINT | Away team's NBA team ID |
| `home_pts` | BIGINT | Home team's points |
| `away_pts` | BIGINT | Away team's points |

### `players`

One row per player who appears in a box score. Bio only; stats live in the box scores. Source: the stats.nba.com all-players list (name and career span) joined with each player's info (the rest). Stored as one Parquet file, `players.parquet`. Bios are fetched only for players not yet stored, and are never refreshed. Each run fetches a bio for every player in the stored box scores who has none, so bios missed by a failure or a crash are caught up on the next run.

| Column | Type | Meaning |
|---|---|---|
| `player_id` | BIGINT | NBA player ID |
| `first_name`, `last_name` | VARCHAR | First and last name |
| `display_name` | VARCHAR | Full name as NBA displays it |
| `birthdate` | DATE | Date of birth |
| `height_in` | BIGINT | Height in inches (`6-11` becomes `83`) |
| `weight_lb` | BIGINT | Weight in pounds |
| `position` | VARCHAR | Position, like `Center` or `Forward-Guard` |
| `country` | VARCHAR | Country |
| `school` | VARCHAR | College, or last team before the NBA |
| `draft_year`, `draft_round`, `draft_number` | BIGINT | Draft year, round and pick; `NULL` for undrafted players |
| `from_year`, `to_year` | BIGINT | First and last NBA season, by starting year |

### `teams`

One row per current NBA team. Current identity only; historical names live on the box score rows. Source: `nba_api`'s bundled static team list. Stored as one Parquet file, `teams.parquet`, rewritten on every ingest.

| Column | Type | Meaning |
|---|---|---|
| `team_id` | BIGINT | NBA team ID |
| `abbreviation` | VARCHAR | Current abbreviation, like `OKC` |
| `city` | VARCHAR | Current city |
| `nickname` | VARCHAR | Current nickname, like `Thunder` |
| `full_name` | VARCHAR | City and nickname |
| `year_founded` | BIGINT | Year the franchise was founded |

## Views

### `player_game_stats`

Per-game player stats: every `player_box_scores` column, plus:

| Column | Type | Meaning |
|---|---|---|
| `fg_pct` | DOUBLE | `fgm / fga`; `NULL` with no attempts |
| `fg3_pct` | DOUBLE | `fg3m / fg3a`; `NULL` with no attempts |
| `ft_pct` | DOUBLE | `ftm / fta`; `NULL` with no attempts |

### `player_season_averages`

One row per player per season and season type. A player traded mid-season has one row covering all their teams.

| Column | Type | Meaning |
|---|---|---|
| `season`, `season_type`, `player_id` | | Grain |
| `player_name` | VARCHAR | Name in the player's latest game of the season |
| `games_played` | BIGINT | Games with a box score row |
| `min`, `fgm`, `fga`, `fg3m`, `fg3a`, `ftm`, `fta`, `oreb`, `dreb`, `reb`, `ast`, `stl`, `blk`, `tov`, `pf`, `pts`, `plus_minus` | DOUBLE | Per-game averages |
| `fg_pct` | DOUBLE | `sum(fgm) / sum(fga)` over the season |
| `fg3_pct` | DOUBLE | `sum(fg3m) / sum(fg3a)` over the season |
| `ft_pct` | DOUBLE | `sum(ftm) / sum(fta)` over the season |

Season percentages come from summed makes and attempts, not from averaging per-game percentages.

### `team_game_stats`

Per-game team stats: every `team_box_scores` column, plus `fg_pct`, `fg3_pct` and `ft_pct` calculated as in `player_game_stats`.

### `team_season_averages`

One row per team per season and season type.

| Column | Type | Meaning |
|---|---|---|
| `season`, `season_type`, `team_id` | | Grain |
| `team_abbreviation`, `team_name` | VARCHAR | As in the team's latest game of the season |
| `games_played` | BIGINT | Games with a box score row |
| `min`, `fgm`, `fga`, `fg3m`, `fg3a`, `ftm`, `fta`, `oreb`, `dreb`, `reb`, `ast`, `stl`, `blk`, `tov`, `pf`, `pts`, `plus_minus` | DOUBLE | Per-game averages |
| `fg_pct`, `fg3_pct`, `ft_pct` | DOUBLE | From summed makes and attempts over the season, as in `player_season_averages` |

### `standings`

Wins and losses per team, season and season type. Play-In games are left out, as in NBA's standings.

| Column | Type | Meaning |
|---|---|---|
| `season`, `season_type`, `team_id` | | Grain |
| `team_abbreviation`, `team_name` | VARCHAR | As in the team's latest game of the season |
| `wins` | BIGINT | Games won |
| `losses` | BIGINT | Games lost |

### `player_teams`

One row per player per team per season and season type. A player traded mid-season has one row for each team.

| Column | Type | Meaning |
|---|---|---|
| `season`, `season_type`, `player_id`, `team_id` | | Grain |
| `player_name` | VARCHAR | Name in the player's latest game for that team |
| `team_abbreviation` | VARCHAR | Team abbreviation in the player's latest game for that team |
| `games_played` | BIGINT | Games with a box score row for that team |
| `first_game_date` | DATE | Date of the player's first game for that team |
| `last_game_date` | DATE | Date of the player's last game for that team |

### `team_rosters`

Each team's roster per season and season type: only players who appeared in a game for the team. A player traded mid-season is on both teams' rosters.

| Column | Type | Meaning |
|---|---|---|
| `season`, `season_type`, `team_id`, `player_id` | | Grain |
| `team_abbreviation` | VARCHAR | Team abbreviation in the player's latest game for that team |
| `player_name` | VARCHAR | Name in the player's latest game for that team |
| `games_played` | BIGINT | Games the player appeared in for that team |

### `hoopdata_info`

One row describing the data. It reads `manifest.json` at query time, so it shows the latest run without reopening or rebuilding anything.

| Column | Type | Meaning |
|---|---|---|
| `schema_version` | INTEGER | Version of this schema (see below) |
| `last_updated` | TIMESTAMP WITH TIME ZONE | When an item was last recorded in the manifest |
| `seasons` | VARCHAR[] | The seasons the data root holds: `['all']` (every season, including future ones), or the fixed list, like `['2022-23', '2023-24']` |

```sql
select schema_version, last_updated, seasons from hoopdata_info
```

### `hoopdata_datasets`

One row per dataset in the data root's selection, core included. Like `hoopdata_info`, it reads `manifest.json` at query time. It is written at the end of every ingest. A selected dataset's own views are published once it has any data.

| Column | Type | Meaning |
|---|---|---|
| `dataset` | VARCHAR | Dataset name, like `core` |
| `last_updated` | TIMESTAMP WITH TIME ZONE | When one of the dataset's items was last fetched |
| `complete` | BOOLEAN | As of the dataset's last ingest, every item in the selection had succeeded: every selected season (with `all`, every season through the latest) and season type, and for core a bio for every player. With `all`, it stays true when a new season starts until the next ingest fetches it |

```sql
select dataset, last_updated, complete from hoopdata_datasets
```

## Manifest

`manifest.json` in the data root is part of the contract. It records what the pipeline has fetched:

```json
{
  "schema_version": 1,
  "last_updated": "2026-11-26T11:00:00.123456+00:00",
  "selection": {"datasets": ["core"], "seasons": ["2022-23", "2023-24"]},
  "items": [
    {
      "table": "player_box_scores",
      "season": "2023-24",
      "season_type": "Regular Season",
      "status": "succeeded",
      "fetched_at": "2026-11-26T11:00:00.123456+00:00",
      "rows": 64,
      "error": null
    }
  ],
  "datasets": [
    {"dataset": "core", "last_updated": "2026-11-26T11:00:00.123456+00:00", "complete": true}
  ],
  "views_hash": "..."
}
```

- **`schema_version`**: the version of this schema.
- **`last_updated`**: UTC time the latest item was recorded.
- **`selection`**: what the data root holds, saved by every ingest and added to by `--season`, `--all-seasons` and `--datasets`. `datasets` lists the selected datasets, core first. `seasons` is `"all"` (every season from 1996-97 on, including future ones) or a list of seasons. A selection only grows. Deleting a dataset's folder removes it on the next ingest. A v1 manifest without `selection` is read as core with all seasons.
- **`items`**: one entry per table, season and season type (no `PlayIn` items before 2019-20), holding the outcome of its latest fetch: `status` (`succeeded` or `failed`), `fetched_at` (UTC), `rows` (`null` when it failed) and `error` (`null` when it succeeded). A failed item keeps its previous Parquet file, if any, and is retried on the next run.
- **The `players` item** has `season` and `season_type` set to `null`, and covers the bios fetched in the latest run that had new players to fetch. `rows` is the number of bios stored by that run. It is `failed` if any bio failed, with `error` like `2 of 120 bios failed, first: ConnectionError: ...`. Bios that failed are fetched again on the next run.
- **`datasets`**: each selected dataset's status as of the latest run, read by `hoopdata_datasets`.
- **`views_hash`**: internal. A fingerprint of the published views, the schema version and the selection, used to decide when `hoopdata.duckdb` must be rebuilt.

## When `hoopdata.duckdb` is rebuilt

Only when the views, the schema version or the selection change (a season or dataset added, or a dataset's folder deleted), or on the next ingest after the data root moves (the views hold absolute paths). New data needs no rebuild: the views read the Parquet files and the manifest at query time.

## Schema version

The schema version is bumped on any breaking change: a column renamed or removed, or its meaning changed. Adding a table, view or column is not breaking. Check `hoopdata_info.schema_version` and fail loudly when it isn't the version your project was written against.
