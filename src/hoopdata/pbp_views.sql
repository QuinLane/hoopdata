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

-- One row per game and team: each stat summed from play-by-play next to the team box score. The counting rules are in
-- docs/schema.md.
create view pbp_reconciliation as
with pbp_sums as (
    select
        game_id,
        team_id,
        sum(case when action_type = 'Made Shot' then shot_value else 0 end)::bigint
            + count(*) filter (where action_type = 'Free Throw' and description not like 'MISS%') as pts,
        count(*) filter (where action_type = 'Made Shot') as fgm,
        count(*) filter (where action_type in ('Made Shot', 'Missed Shot')) as fga,
        count(*) filter (where action_type = 'Made Shot' and shot_value = 3) as fg3m,
        count(*) filter (where action_type in ('Made Shot', 'Missed Shot') and shot_value = 3) as fg3a,
        count(*) filter (where action_type = 'Free Throw' and description not like 'MISS%') as ftm,
        count(*) filter (where action_type = 'Free Throw') as fta,
        -- Player rebounds only: team rebounds have no person_id.
        count(*) filter (where action_type = 'Rebound' and person_id is not null) as reb,
        count(*) filter (where action_type = 'Made Shot' and description like '%AST)%') as ast,
        count(*) filter (where description like '%STEAL%') as stl,
        count(*) filter (where description like '%BLOCK%') as blk,
        count(*) filter (where action_type = 'Turnover') as tov,
        -- Technicals aren't personal fouls.
        count(*) filter (
            where action_type = 'Foul'
            and sub_type not in ('Technical', 'Double Technical', 'Defense 3 Second', 'Flopping')
        ) as pf
    from play_by_play
    group by game_id, team_id
)
select
    box.season, box.season_type, box.game_id, box.team_id,
    coalesce(pbp.pts, 0) as pbp_pts, box.pts as box_pts,
    coalesce(pbp.fgm, 0) as pbp_fgm, box.fgm as box_fgm,
    coalesce(pbp.fga, 0) as pbp_fga, box.fga as box_fga,
    coalesce(pbp.fg3m, 0) as pbp_fg3m, box.fg3m as box_fg3m,
    coalesce(pbp.fg3a, 0) as pbp_fg3a, box.fg3a as box_fg3a,
    coalesce(pbp.ftm, 0) as pbp_ftm, box.ftm as box_ftm,
    coalesce(pbp.fta, 0) as pbp_fta, box.fta as box_fta,
    coalesce(pbp.reb, 0) as pbp_reb, box.reb as box_reb,
    coalesce(pbp.ast, 0) as pbp_ast, box.ast as box_ast,
    coalesce(pbp.stl, 0) as pbp_stl, box.stl as box_stl,
    coalesce(pbp.blk, 0) as pbp_blk, box.blk as box_blk,
    coalesce(pbp.tov, 0) as pbp_tov, box.tov as box_tov,
    coalesce(pbp.pf, 0) as pbp_pf, box.pf as box_pf,
    -- A NULL box stat is a mismatch, not NULL.
    (pbp_pts, pbp_fgm, pbp_fga, pbp_fg3m, pbp_fg3a, pbp_ftm, pbp_fta, pbp_reb, pbp_ast, pbp_stl, pbp_blk, pbp_tov, pbp_pf)
        is not distinct from (box_pts, box_fgm, box_fga, box_fg3m, box_fg3a, box_ftm, box_fta, box_reb, box_ast, box_stl, box_blk, box_tov, box_pf)
        as matches
from team_box_scores as box
left join pbp_sums as pbp using (game_id, team_id)
where box.game_id in (select game_id from play_by_play);

-- One row per season and season type: how many held games reconcile, both teams matching.
create view pbp_reconciliation_seasons as
with game_matches as (
    select season, season_type, game_id, bool_and(matches) as matches
    from pbp_reconciliation
    group by all
)
select
    season,
    season_type,
    count(*) as games,
    count(*) filter (where matches) as matching_games,
    matching_games / games as matching_share
from game_matches
group by all;

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
    box.season, box.season_type, assisted.game_id, assisted.action_id, assisted.period, assisted.clock,
    assisted.team_id, assisted.player_id,
    case when count(teammates.player_id) = 1 then any_value(teammates.player_id) end as assist_player_id,
    assisted.assist_player_name, assisted.shot_value
from assisted
-- The season type comes from the team box scores, as in pbp_reconciliation: they hold every held game, games may not.
join (select distinct season, season_type, game_id from team_box_scores) as box using (game_id)
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
