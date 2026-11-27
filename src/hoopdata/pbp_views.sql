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
