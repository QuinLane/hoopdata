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
- **Stored tables hold raw counts only.** Every percentage is calculated in a view. The exception is the `advanced` dataset's tables, which hold NBA's official advanced rates exactly as given, with no rescaling (ADR 0001). Some are fractions and some are percents; each column's scale is documented with its table.
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

### `player_advanced_box_scores` (advanced dataset)

One row per player per game, holding NBA's official advanced stats exactly as given. Only in a data root whose selection includes `advanced`. Source: the stats.nba.com player game logs with the Advanced measure type, one league-wide request per season and season type. Stored as Parquet under `advanced/player_advanced_box_scores/season=<season>/`, one file per season type.

Keys only for identity: names, dates, results and team abbreviations come from core (see `player_advanced_game_stats`). The `(game_id, player_id)` keys match `player_box_scores` exactly: every advanced row has a core row and every core row has an advanced row. This was checked against the live API (1996-97 Regular Season, 2024-25 Playoffs), which also found no NULLs in `off_rating`, `poss`, `pie` or `pace`; there's no runtime check.

| Column | Type | Meaning | Scale |
|---|---|---|---|
| `season` | VARCHAR | Season, like `2023-24` | |
| `season_type` | VARCHAR | `Regular Season`, `PlayIn` or `Playoffs` | |
| `game_id` | VARCHAR | NBA game ID, leading zeros kept | |
| `player_id` | BIGINT | NBA player ID | |
| `team_id` | BIGINT | NBA team ID the player played for in that game | |
| `off_rating` | DOUBLE | Offensive rating: team points per 100 possessions while on court | Points per 100 (`129.2`) |
| `def_rating` | DOUBLE | Defensive rating: opponent points per 100 possessions while on court | Points per 100 (`122.2`) |
| `net_rating` | DOUBLE | `off_rating - def_rating` | Points per 100 (`6.9`) |
| `ast_pct` | DOUBLE | Share of teammates' field goals the player assisted while on court | Fraction (`0.621`) |
| `ast_to` | DOUBLE | Assists per turnover | Ratio (`4.5`) |
| `ast_ratio` | DOUBLE | Assists per 100 of the player's possessions | Per 100 (`41.9`) |
| `oreb_pct` | DOUBLE | Share of available offensive rebounds grabbed while on court | Fraction (`0.063`) |
| `dreb_pct` | DOUBLE | Share of available defensive rebounds grabbed while on court | Fraction (`0.4`) |
| `reb_pct` | DOUBLE | Share of available rebounds grabbed while on court | Fraction (`0.239`) |
| `tm_tov_pct` | DOUBLE | Turnovers per 100 of the player's possessions | Percent (`9.3`) |
| `efg_pct` | DOUBLE | Effective field goal percentage | Fraction (`0.525`) |
| `ts_pct` | DOUBLE | True shooting percentage | Fraction (`0.586`) |
| `usg_pct` | DOUBLE | Share of team possessions the player used while on court | Fraction (`0.313`) |
| `pace` | DOUBLE | Possessions per 48 minutes | Per 48 (`95.56`) |
| `pace_per40` | DOUBLE | Possessions per 40 minutes | Per 40 (`79.63`) |
| `poss` | BIGINT | Possessions played | Count (`72`) |
| `pie` | DOUBLE | Player Impact Estimate: share of the game's events the player contributed | Fraction (`0.234`) |

Not stored from the source: the `E_*` estimated versions (a second estimate of the same stat, ADR 0001), the `sp_work_*` internal copies, every `*_RANK` column (ranks only mean something inside one response), the copies of core data (`FGM`, `FGA`, `FGM_PG`, `FGA_PG`, `FG_PCT`, `MIN`, names, date, matchup, `WL`) and `AVAILABLE_FLAG`, `MIN_SEC` and `TEAM_COUNT`.

### `team_advanced_box_scores` (advanced dataset)

One row per team per game, holding NBA's official advanced stats exactly as given. Only in a data root whose selection includes `advanced`. Source: the stats.nba.com team game logs with the Advanced measure type, one league-wide request per season and season type. Stored as Parquet under `advanced/team_advanced_box_scores/season=<season>/`, one file per season type.

Keys only for identity: team abbreviations, dates and results come from core (see `team_advanced_game_stats`). The `(game_id, team_id)` keys match `team_box_scores` exactly: every advanced row has a core row and every core row has an advanced row. This was checked against the live API (1996-97 Regular Season, 2024-25 Playoffs), which also found no NULLs in `off_rating`, `poss`, `pie` or `pace`; there's no runtime check.

The columns are the player table's without `player_id` and `usg_pct` (NBA gives no usage for teams). Note `tm_tov_pct` is a fraction here but a percent in `player_advanced_box_scores`; both are as NBA gives them.

| Column | Type | Meaning | Scale |
|---|---|---|---|
| `season` | VARCHAR | Season, like `2023-24` | |
| `season_type` | VARCHAR | `Regular Season`, `PlayIn` or `Playoffs` | |
| `game_id` | VARCHAR | NBA game ID, leading zeros kept | |
| `team_id` | BIGINT | NBA team ID | |
| `off_rating` | DOUBLE | Offensive rating: points per 100 possessions | Points per 100 (`111.1`) |
| `def_rating` | DOUBLE | Defensive rating: opponent points per 100 possessions | Points per 100 (`113.9`) |
| `net_rating` | DOUBLE | `off_rating - def_rating` | Points per 100 (`-2.8`) |
| `ast_pct` | DOUBLE | Share of the team's field goals that were assisted | Fraction (`0.787`) |
| `ast_to` | DOUBLE | Assists per turnover | Ratio (`2.85`) |
| `ast_ratio` | DOUBLE | Assists per 100 possessions | Per 100 (`24.8`) |
| `oreb_pct` | DOUBLE | Share of available offensive rebounds grabbed | Fraction (`0.245`) |
| `dreb_pct` | DOUBLE | Share of available defensive rebounds grabbed | Fraction (`0.824`) |
| `reb_pct` | DOUBLE | Share of available rebounds grabbed | Fraction (`0.529`) |
| `tm_tov_pct` | DOUBLE | Turnovers per possession | Fraction (`0.131`) |
| `efg_pct` | DOUBLE | Effective field goal percentage | Fraction (`0.542`) |
| `ts_pct` | DOUBLE | True shooting percentage | Fraction (`0.543`) |
| `pace` | DOUBLE | Possessions per 48 minutes | Per 48 (`100.0`) |
| `pace_per40` | DOUBLE | Possessions per 40 minutes | Per 40 (`83.33`) |
| `poss` | BIGINT | Possessions played | Count (`99`) |
| `pie` | DOUBLE | Team's share of the game's events (NBA's PIE for a team) | Fraction (`0.479`) |

Not stored from the source: the `E_*` estimated versions (ADR 0001), every `*_RANK` column, the copies of core data (`MIN`, team abbreviation and name, date, matchup, `WL`) and `AVAILABLE_FLAG`.

### `shots` (shots dataset)

One row per field-goal attempt (a shot), with where and how it was taken, exactly as NBA gives it. Free throws aren't shots. Only in a data root whose selection includes `shots`. Source: stats.nba.com `shotchartdetail` with `player_id=0` and the FGA measure, one request per team in core's `team_box_scores` for that season and season type (a league-wide request is too large for a regular season). Stored as Parquet under `shots/shots/season=<season>/`, one file per season type. An item fails as a whole if any of its team requests fails, and fails without requests if core doesn't hold its season and season type yet; either way it's retried on the next run.

Keys only for identity: names, dates, results and team abbreviations come from core (see `shot_details`). A game's shots add up to core's box scores: per team, the count equals `fga` and the sum of `shot_made_flag` equals `fgm`. This was checked against the live API (1996-97, 2001-02 and 2024-25); there's no runtime check.

| Column | Type | Meaning |
|---|---|---|
| `season` | VARCHAR | Season, like `2023-24` |
| `season_type` | VARCHAR | `Regular Season`, `PlayIn` or `Playoffs` |
| `game_id` | VARCHAR | NBA game ID, leading zeros kept |
| `game_event_id` | BIGINT | The shot's event number within the game |
| `player_id` | BIGINT | NBA player ID of the shooter |
| `team_id` | BIGINT | NBA team ID of the shooter's team |
| `period` | BIGINT | Period: 1-4, then 5 on for overtimes |
| `minutes_remaining` | BIGINT | Minutes left on the period clock |
| `seconds_remaining` | BIGINT | Seconds left on the period clock, past `minutes_remaining` |
| `action_type` | VARCHAR | How the shot was taken, like `Driving Layup Shot` |
| `shot_type` | VARCHAR | `2PT Field Goal` or `3PT Field Goal` |
| `shot_zone_basic` | VARCHAR | Court zone, like `Restricted Area` or `Above the Break 3` |
| `shot_zone_area` | VARCHAR | Side of the court, like `Left Side Center(LC)` |
| `shot_zone_range` | VARCHAR | Distance band, like `Less Than 8 ft.` or `24+ ft.` |
| `shot_distance` | BIGINT | Distance from the basket in feet |
| `loc_x` | BIGINT | Court x, side to side, in tenths of a foot from the basket |
| `loc_y` | BIGINT | Court y, toward half court, in tenths of a foot from the basket |
| `shot_made_flag` | BIGINT | `1` made, `0` missed, so `sum()` gives FGM |

**Missing locations look like shots at the rim.** A shot with no recorded location comes back at (0,0), `Restricted Area`, 0 ft, the same as a real shot at the rim. They are stored as given: no cutoff, `NULL` or flag. Shots at (0,0), measured live: 32% in 1996-97, 23% in 2001-02 and 2% in 2024-25 (mostly real tip-ins). Play-by-play has the same gaps, so treat early-season locations as incomplete.

**Matching play-by-play.** `game_event_id` and `player_id` match play-by-play v3's `actionNumber` and `personId` (`actionNumber` alone isn't unique there). Every shot matched in the samples checked (`0029600001` and a 2024-25 game).

Not stored from the source: `GRID_TYPE`, the copies of core data (`PLAYER_NAME`, `TEAM_NAME`, `GAME_DATE`, `HTM`, `VTM`), `EVENT_TYPE` (the same as `shot_made_flag`) and `SHOT_ATTEMPTED_FLAG` (always 1), and the league-average zones in the second result set.

### `official_rosters` (rosters dataset)

One row per season, team and player on the team's official roster, as NBA last reported it: usually the end-of-season roster for a past season, the current roster for the current one. Unlike core's `team_rosters`, it includes players who never appeared in a game. Only in a data root whose selection includes `rosters`. Source: stats.nba.com `commonteamroster` (its first result set), one request per team in core's `team_box_scores` for that season, any season type. Stored as Parquet under `rosters/official_rosters/season=<season>/season.parquet`, one file per season: the source doesn't split by season type, so each season is one item. An item fails as a whole if any of its team requests fails, and fails without any requests if core holds no games for that season yet; either way it is retried on the next run.

| Column | Type | Meaning |
|---|---|---|
| `season` | VARCHAR | Season, like `2023-24` |
| `team_id` | BIGINT | NBA team ID |
| `player_id` | BIGINT | NBA player ID |
| `player_name` | VARCHAR | Player's name as listed on the official roster |
| `jersey_number` | VARCHAR | Jersey number as given, so `0` and `00` stay different |
| `position` | VARCHAR | Position as given, like `G` or `F-C` |
| `experience` | VARCHAR | Seasons of NBA experience as given, `R` for a rookie |
| `how_acquired` | VARCHAR | How the team got the player as given, like `#21 Pick in 2022 Draft`; often `NULL`, always in early seasons |

**What the snapshot leaves out.** The official roster is one snapshot, stored as given and not repaired:
- Players gone before NBA's last report are missing. SEA 1996-97 lists 12 players where core has 16 who appeared: Craig Ehlo (62 games) isn't there. OKC 2024-25 misses Alex Reese and Malevy Leons.
- A new season's official rosters arrive only after its first game, since the teams come from core.
- Players who never appeared in a game have no bio, since bios come from `players`, which only covers players in a box score. Nikola Topić (OKC 2024-25) is on the official roster, but `official_roster_details` has `NULL` bio columns for him.

Not stored from the source: `LeagueID`, the source `SEASON` (the start year), `NICKNAME`, `PLAYER_SLUG`, `SUPPLEMENTAL_STATUS` and the bio columns `HEIGHT`, `WEIGHT`, `BIRTH_DATE`, `AGE` and `SCHOOL` (bios live in `players`), and the second result set, the team's staff (its coaches are stored in `coach_seasons`).

### `coach_seasons` (rosters dataset)

One row per season, team and coach on the team's staff, as NBA last reported it. Only in a data root whose selection includes `rosters`. Source: the second result set of the same `commonteamroster` requests as `official_rosters`, so no extra requests are made and the two items for a season succeed or fail together. Stored as Parquet under `rosters/coach_seasons/season=<season>/season.parquet`, one file per season.

Only head and assistant coaches are kept: rows whose `COACH_TYPE` contains `Head Coach` or `Assistant Coach` (Head, Associate Head, Lead Assistant, Assistant, and Assistant Coach for Player Development). Trainers, assistant trainers and the strength and conditioning coach are dropped. The rule is on the name, so a new coaching title is kept.

| Column | Type | Meaning |
|---|---|---|
| `season` | VARCHAR | Season, like `2023-24` |
| `team_id` | BIGINT | NBA team ID |
| `coach_id` | BIGINT | NBA coach ID |
| `first_name` | VARCHAR | Coach's first name |
| `last_name` | VARCHAR | Coach's last name |
| `coach_name` | VARCHAR | Coach's full name |
| `coach_type` | VARCHAR | Role as given, like `Head Coach` or `Lead Assistant Coach` |

**What the snapshot leaves out.** The coaches are one snapshot, stored as given and not repaired:
- Coaches gone before NBA's last report are missing. MEM 2024-25 lists only Tuomas Iisalo: Taylor Jenkins, fired in March 2025, isn't there.
- The report can come after the season. NYK 2024-25 lists no head coach, since Tom Thibodeau was removed after his June 2025 firing.
- Early seasons list only the head coach, like SEA 1996-97.

Not stored from the source: `IS_ASSISTANT` (a role code that repeats `coach_type`), `SORT_SEQUENCE`, `SUB_SORT_SEQUENCE` and the source `SEASON`.

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

### `player_advanced_game_stats` (advanced dataset)

Per-game player advanced stats with core's names, dates and results: every `player_advanced_box_scores` column, plus these from the matching `player_box_scores` row (joined on `game_id` and `player_id`). Only published when `advanced` is in the selection. There are no season-level advanced views: averaging per-game ratings isn't the official season rating.

| Column | Type | Meaning |
|---|---|---|
| `player_name` | VARCHAR | Player's name as listed in that game |
| `team_abbreviation` | VARCHAR | Team abbreviation at the time of the game |
| `game_date` | DATE | Date the game was played |
| `wl` | VARCHAR | `W` or `L` for the player's team |

### `team_advanced_game_stats` (advanced dataset)

Per-game team advanced stats with core's team abbreviation, date and result: every `team_advanced_box_scores` column, plus these from the matching `team_box_scores` row (joined on `game_id` and `team_id`). Only published when `advanced` is in the selection.

| Column | Type | Meaning |
|---|---|---|
| `team_abbreviation` | VARCHAR | Team abbreviation at the time of the game |
| `game_date` | DATE | Date the game was played |
| `wl` | VARCHAR | `W` or `L` |

### `shot_details` (shots dataset)

Every shot with core's names, dates and results: every `shots` column, plus these from the matching `player_box_scores` row (joined on `game_id` and `player_id`). Only published when `shots` is in the selection.

| Column | Type | Meaning |
|---|---|---|
| `player_name` | VARCHAR | Shooter's name as listed in that game |
| `team_abbreviation` | VARCHAR | Team abbreviation at the time of the game |
| `game_date` | DATE | Date the game was played |
| `wl` | VARCHAR | `W` or `L` for the shooter's team |

### `official_roster_details` (rosters dataset)

Every official roster row with core's team abbreviation and the player's bio: every `official_rosters` column, plus these. Only published when `rosters` is in the selection. Core's `team_rosters` (players who appeared, split by season type) isn't combined with it; join the two on `season`, `team_id` and `player_id`.

| Column | Type | Meaning |
|---|---|---|
| `team_abbreviation` | VARCHAR | Team abbreviation in the team's latest game of the season in `team_box_scores` |
| `first_name`, `last_name`, `display_name`, `birthdate`, `height_in`, `weight_lb`, `country`, `school`, `draft_year`, `draft_round`, `draft_number`, `from_year`, `to_year` | | As in `players`, joined on `player_id` |

**No bio for players who never appeared.** `players` only covers players in a box score, so a player who never appeared in a game (like Nikola Topić, OKC 2024-25) has his name and jersey number here but `NULL` bio columns. `players.position` is left out: the roster's own `position` is kept.

### `coaches` (rosters dataset)

One row per coach in `coach_seasons`. Only published when `rosters` is in the selection.

| Column | Type | Meaning |
|---|---|---|
| `coach_id` | BIGINT | Grain |
| `first_name`, `last_name`, `coach_name` | VARCHAR | As in the coach's latest season |
| `first_season` | VARCHAR | Coach's first season with any team |
| `last_season` | VARCHAR | Coach's latest season with any team |

### `coach_teams` (rosters dataset)

One row per coach and team. Only published when `rosters` is in the selection.

| Column | Type | Meaning |
|---|---|---|
| `coach_id`, `team_id` | BIGINT | Grain |
| `coach_name` | VARCHAR | Name in the coach's latest season with that team |
| `team_abbreviation` | VARCHAR | Team abbreviation, as in `team_coaches`, in the coach's latest season with that team |
| `first_season` | VARCHAR | Coach's first season with that team |
| `last_season` | VARCHAR | Coach's latest season with that team |
| `seasons` | BIGINT | Seasons coaching that team |
| `head_coach_seasons` | BIGINT | Of those, seasons as `Head Coach` (an associate head coach doesn't count) |

### `team_coaches` (rosters dataset)

Each team's coaches per season: every `coach_seasons` column, plus this. Only published when `rosters` is in the selection.

| Column | Type | Meaning |
|---|---|---|
| `team_abbreviation` | VARCHAR | Team abbreviation in the team's latest game of the season in `team_box_scores` |

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

One row per dataset in the data root's selection, core included. Like `hoopdata_info`, it reads `manifest.json` at query time. It is written at the end of every ingest. A selected dataset's own views are published once each of its tables has data.

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
- **Season-only items**, for a table whose source doesn't split by season type (`official_rosters`, `coach_seasons`), have `season_type` set to `null`: one item per table and season.
- **The `players` item** has `season` and `season_type` set to `null`, and covers the bios fetched in the latest run that had new players to fetch. `rows` is the number of bios stored by that run. It is `failed` if any bio failed, with `error` like `2 of 120 bios failed, first: ConnectionError: ...`. Bios that failed are fetched again on the next run.
- **`datasets`**: each selected dataset's status as of the latest run, read by `hoopdata_datasets`.
- **`views_hash`**: internal. A fingerprint of the published views, the schema version and the selection, used to decide when `hoopdata.duckdb` must be rebuilt.

## When `hoopdata.duckdb` is rebuilt

Only when the views, the schema version or the selection change (a season or dataset added, or a dataset's folder deleted), or on the next ingest after the data root moves (the views hold absolute paths). New data needs no rebuild: the views read the Parquet files and the manifest at query time.

## Schema version

The schema version is bumped on any breaking change: a column renamed or removed, or its meaning changed. Adding a table, view or column is not breaking. Check `hoopdata_info.schema_version` and fail loudly when it isn't the version your project was written against.
