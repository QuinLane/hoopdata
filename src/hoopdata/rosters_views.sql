-- The rosters dataset's views, published in hoopdata.duckdb when rosters is in the selection.
-- {root} is replaced with the absolute data root path when the file is built.

create view official_rosters as
select season, team_id, player_id, player_name, jersey_number, position, experience, how_acquired
from read_parquet(
    '{root}/rosters/official_rosters/*/*.parquet',
    hive_partitioning = true,
    hive_types = {'season': varchar}
);

create view coach_seasons as
select season, team_id, coach_id, first_name, last_name, coach_name, coach_type
from read_parquet(
    '{root}/rosters/coach_seasons/*/*.parquet',
    hive_partitioning = true,
    hive_types = {'season': varchar}
);

-- The team's abbreviation for the season is its latest in core. Bios come from players, so a player who
-- never appeared in a box score has none.
create view official_roster_details as
select
    official_rosters.*,
    teams.team_abbreviation,
    players.first_name, players.last_name, players.display_name, players.birthdate,
    players.height_in, players.weight_lb, players.country, players.school,
    players.draft_year, players.draft_round, players.draft_number, players.from_year, players.to_year
from official_rosters
left join (
    select season, team_id, arg_max(team_abbreviation, game_date) as team_abbreviation
    from team_box_scores
    group by season, team_id
) as teams using (season, team_id)
left join players using (player_id);

-- The team's abbreviation for the season is its latest in core.
create view team_coaches as
select coach_seasons.*, teams.team_abbreviation
from coach_seasons
left join (
    select season, team_id, arg_max(team_abbreviation, game_date) as team_abbreviation
    from team_box_scores
    group by season, team_id
) as teams using (season, team_id);

create view coaches as
select
    coach_id,
    arg_max(first_name, season) as first_name,
    arg_max(last_name, season) as last_name,
    arg_max(coach_name, season) as coach_name,
    min(season) as first_season,
    max(season) as last_season
from coach_seasons
group by coach_id;

-- Only the head coach counts toward head_coach_seasons, not an associate head coach.
create view coach_teams as
select
    coach_id,
    arg_max(coach_name, season) as coach_name,
    team_id,
    arg_max(team_abbreviation, season) as team_abbreviation,
    min(season) as first_season,
    max(season) as last_season,
    count(*) as seasons,
    count(*) filter (where coach_type = 'Head Coach') as head_coach_seasons
from team_coaches
group by coach_id, team_id;
