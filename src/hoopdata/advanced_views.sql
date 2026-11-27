-- The advanced dataset's views, published in hoopdata.duckdb when advanced is in the selection.
-- {root} is replaced with the absolute data root path when the file is built.

create view player_advanced_box_scores as
select
    season, season_type, game_id, player_id, team_id,
    off_rating, def_rating, net_rating, ast_pct, ast_to, ast_ratio,
    oreb_pct, dreb_pct, reb_pct, tm_tov_pct, efg_pct, ts_pct, usg_pct,
    pace, pace_per40, poss, pie
from read_parquet(
    '{root}/advanced/player_advanced_box_scores/*/*.parquet',
    hive_partitioning = true,
    hive_types = {'season': varchar}
);

create view player_advanced_game_stats as
select
    advanced.*,
    core.player_name, core.team_abbreviation, core.game_date, core.wl
from player_advanced_box_scores as advanced
left join player_box_scores as core using (game_id, player_id);
