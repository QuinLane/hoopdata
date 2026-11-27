-- The pbp dataset's views, published in hoopdata.duckdb when pbp is in the selection.
-- {root} is replaced with the absolute data root path when the file is built.

create view play_by_play as
select
    season, game_id, action_id, action_number, period, clock, team_id, person_id,
    action_type, sub_type, description, is_field_goal, shot_value, shot_result, shot_distance,
    x_legacy, y_legacy, location, score_home, score_away, points_total
from read_parquet(
    '{root}/pbp/play_by_play/*/*/*.parquet',
    hive_partitioning = true,
    hive_types = {'season': varchar}
);

-- One row per assisted made shot. Play-by-play gives the assister only as a surname, like "(White 1 AST)", so it's
-- matched to the scorer's teammates in that game's player box scores, ignoring accents. When no teammate or more
-- than one matches, assist_player_id is NULL and the parsed name is kept.
create view assists as
with assisted as (
    select
        game_id, action_id, period, clock, team_id, person_id as player_id, shot_value,
        regexp_extract(description, '\(([^()]*) \d+ AST\)', 1) as assist_player_name
    from play_by_play
    where action_type = 'Made Shot' and description like '%AST)'
)
select
    games.season, games.season_type, assisted.game_id, assisted.action_id, assisted.period, assisted.clock,
    assisted.team_id, assisted.player_id,
    case when count(teammates.player_id) = 1 then any_value(teammates.player_id) end as assist_player_id,
    assisted.assist_player_name, assisted.shot_value
from assisted
join games using (game_id)
left join player_box_scores as teammates
    on teammates.game_id = assisted.game_id
    and teammates.team_id = assisted.team_id
    and teammates.player_id <> assisted.player_id
    and ends_with(strip_accents(teammates.player_name), ' ' || assisted.assist_player_name)
group by all;

-- One row per season, season type, team, assister and scorer. Unresolved assisters are left out.
create view assist_pairs as
select
    season, season_type, team_id, assist_player_id, player_id,
    count(*) as assists,
    sum(shot_value)::bigint as points
from assists
where assist_player_id is not null
group by all;
