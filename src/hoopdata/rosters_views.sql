-- The rosters dataset's views, published in hoopdata.duckdb when rosters is in the selection.
-- {root} is replaced with the absolute data root path when the file is built.

create view official_rosters as
select season, team_id, player_id, player_name, jersey_number, position, experience, how_acquired
from read_parquet(
    '{root}/rosters/official_rosters/*/*.parquet',
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
