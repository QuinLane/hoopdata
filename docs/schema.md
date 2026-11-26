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
- **`season_type`** is `Regular Season` or `Playoffs`.
- **Stored tables hold raw counts only.** Every percentage is calculated in a view.
- **Missing values** are `NULL`; integer columns stay integers.

## Tables

### `player_box_scores`

One row per player per game. Source: the stats.nba.com league game log (players). Stored as Parquet under `player_box_scores/season=<season>/`.

| Column | Type | Meaning |
|---|---|---|
| `season` | VARCHAR | Season, like `2023-24` |
| `season_type` | VARCHAR | `Regular Season` or `Playoffs` |
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
