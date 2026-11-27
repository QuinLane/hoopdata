-- The shots dataset's views, published in hoopdata.duckdb when shots is in the selection.
-- {root} is replaced with the absolute data root path when the file is built.

create view shots as
select
    season, season_type, game_id, game_event_id, player_id, team_id,
    period, minutes_remaining, seconds_remaining, action_type, shot_type,
    shot_zone_basic, shot_zone_area, shot_zone_range, shot_distance, loc_x, loc_y, shot_made_flag
from read_parquet(
    '{root}/shots/shots/*/*.parquet',
    hive_partitioning = true,
    hive_types = {'season': varchar}
);

create view shot_details as
select
    shots.*,
    core.player_name, core.team_abbreviation, core.game_date, core.wl
from shots
left join player_box_scores as core using (game_id, player_id);
