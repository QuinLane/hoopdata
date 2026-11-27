-- The shared queries every consumer uses, published as views in hoopdata.duckdb.
-- {root} is replaced with the absolute data root path when the file is built.

create view hoopdata_info as
select schema_version, last_updated
from read_json(
    '{root}/manifest.json',
    columns = {schema_version: 'INTEGER', last_updated: 'TIMESTAMPTZ'}
);

create view player_box_scores as
select
    season, season_type, game_id, game_date,
    player_id, player_name, team_id, team_abbreviation, team_name,
    wl, min, fgm, fga, fg3m, fg3a, ftm, fta,
    oreb, dreb, reb, ast, stl, blk, tov, pf, pts, plus_minus
from read_parquet(
    '{root}/player_box_scores/*/*.parquet',
    hive_partitioning = true,
    hive_types = {'season': varchar}
);

create view players as
select
    player_id, first_name, last_name, display_name, birthdate,
    height_in, weight_lb, position, country, school,
    draft_year, draft_round, draft_number, from_year, to_year
from read_parquet('{root}/players.parquet');

create view teams as
select team_id, abbreviation, city, nickname, full_name, year_founded
from read_parquet('{root}/teams.parquet');

create view player_game_stats as
select
    *,
    fgm / nullif(fga, 0) as fg_pct,
    fg3m / nullif(fg3a, 0) as fg3_pct,
    ftm / nullif(fta, 0) as ft_pct
from player_box_scores;

create view player_season_averages as
select
    season,
    season_type,
    player_id,
    arg_max(player_name, game_date) as player_name,
    count(*) as games_played,
    avg(min) as min,
    avg(fgm) as fgm,
    avg(fga) as fga,
    sum(fgm) / nullif(sum(fga), 0) as fg_pct,
    avg(fg3m) as fg3m,
    avg(fg3a) as fg3a,
    sum(fg3m) / nullif(sum(fg3a), 0) as fg3_pct,
    avg(ftm) as ftm,
    avg(fta) as fta,
    sum(ftm) / nullif(sum(fta), 0) as ft_pct,
    avg(oreb) as oreb,
    avg(dreb) as dreb,
    avg(reb) as reb,
    avg(ast) as ast,
    avg(stl) as stl,
    avg(blk) as blk,
    avg(tov) as tov,
    avg(pf) as pf,
    avg(pts) as pts,
    avg(plus_minus) as plus_minus
from player_box_scores
group by season, season_type, player_id;

create view team_box_scores as
select
    season, season_type, game_id, game_date,
    team_id, team_abbreviation, team_name,
    wl, min, fgm, fga, fg3m, fg3a, ftm, fta,
    oreb, dreb, reb, ast, stl, blk, tov, pf, pts, plus_minus
from read_parquet(
    '{root}/team_box_scores/*/*.parquet',
    hive_partitioning = true,
    hive_types = {'season': varchar}
);

create view team_game_stats as
select
    *,
    fgm / nullif(fga, 0) as fg_pct,
    fg3m / nullif(fg3a, 0) as fg3_pct,
    ftm / nullif(fta, 0) as ft_pct
from team_box_scores;

create view team_season_averages as
select
    season,
    season_type,
    team_id,
    arg_max(team_abbreviation, game_date) as team_abbreviation,
    arg_max(team_name, game_date) as team_name,
    count(*) as games_played,
    avg(min) as min,
    avg(fgm) as fgm,
    avg(fga) as fga,
    sum(fgm) / nullif(sum(fga), 0) as fg_pct,
    avg(fg3m) as fg3m,
    avg(fg3a) as fg3a,
    sum(fg3m) / nullif(sum(fg3a), 0) as fg3_pct,
    avg(ftm) as ftm,
    avg(fta) as fta,
    sum(ftm) / nullif(sum(fta), 0) as ft_pct,
    avg(oreb) as oreb,
    avg(dreb) as dreb,
    avg(reb) as reb,
    avg(ast) as ast,
    avg(stl) as stl,
    avg(blk) as blk,
    avg(tov) as tov,
    avg(pf) as pf,
    avg(pts) as pts,
    avg(plus_minus) as plus_minus
from team_box_scores
group by season, season_type, team_id;

create view games as
select
    game_id, season, season_type, game_date, neutral_site,
    home_team_id, away_team_id, home_pts, away_pts
from read_parquet(
    '{root}/games/*/*.parquet',
    hive_partitioning = true,
    hive_types = {'season': varchar}
);

create view standings as
select
    season,
    season_type,
    team_id,
    arg_max(team_abbreviation, game_date) as team_abbreviation,
    arg_max(team_name, game_date) as team_name,
    count(*) filter (where wl = 'W') as wins,
    count(*) filter (where wl = 'L') as losses
from team_box_scores
where season_type <> 'PlayIn'
group by season, season_type, team_id;

create view player_teams as
select
    season,
    season_type,
    player_id,
    arg_max(player_name, game_date) as player_name,
    team_id,
    arg_max(team_abbreviation, game_date) as team_abbreviation,
    count(*) as games_played,
    min(game_date) as first_game_date,
    max(game_date) as last_game_date
from player_box_scores
group by season, season_type, player_id, team_id;

create view team_rosters as
select season, season_type, team_id, team_abbreviation, player_id, player_name, games_played
from player_teams;
