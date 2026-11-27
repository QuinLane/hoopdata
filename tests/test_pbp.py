from datetime import date
from pathlib import Path

import duckdb
import pytest

from hoopdata.ingest import ingest
from hoopdata.source import ReplaySource
from hoopdata.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
SUMMER = date(2024, 7, 1)
# 2023-24 is the latest season, so core refetches it on every run.
IN_SEASON = date(2024, 3, 1)
JOKIC = 203999
NUGGETS = 1610612743
# Denver's 2023-24 opener at home to Dallas.
OPENER = "0022300006"


@pytest.fixture
def db(tmp_path):
    """Ingest 2023-24 with pbp from the replay source and open the published file read-only."""
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], datasets=["pbp"], today=SUMMER)
    con = duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True)
    yield con
    con.close()


def test_play_by_play_holds_each_action_as_given_with_only_the_kept_columns(db):
    columns = db.execute("select column_name, column_type from (describe play_by_play)").fetchall()
    rows = db.execute(
        "select * exclude (season) from play_by_play where game_id = ? and action_id in (9, 13, 186) order by action_id",
        [OPENER],
    ).fetchall()

    assert columns == [
        ("season", "VARCHAR"), ("game_id", "VARCHAR"), ("action_id", "BIGINT"), ("action_number", "BIGINT"),
        ("period", "BIGINT"), ("clock", "VARCHAR"), ("team_id", "BIGINT"), ("person_id", "BIGINT"),
        ("action_type", "VARCHAR"), ("sub_type", "VARCHAR"), ("description", "VARCHAR"), ("is_field_goal", "BIGINT"),
        ("shot_value", "BIGINT"), ("shot_result", "VARCHAR"), ("shot_distance", "BIGINT"), ("x_legacy", "BIGINT"),
        ("y_legacy", "BIGINT"), ("location", "VARCHAR"), ("score_home", "INTEGER"), ("score_away", "INTEGER"),
        ("points_total", "BIGINT"),
    ]
    # Jokic's opening layup, his steal (actionType is empty for steals and blocks) and his block, as the fixture gives
    # them. Blank scores are NULL.
    assert rows == [
        (OPENER, 9, 14, 1, "PT10M55.00S", NUGGETS, JOKIC, "Made Shot", "Driving Layup Shot",
         "Jokic 3' Driving Layup (2 PTS)", 1, 2, "Made", 3, 31, 7, "h", 2, 4, 6),
        (OPENER, 13, 18, 1, "PT10M22.00S", NUGGETS, JOKIC, "", "", "Jokic STEAL (1 STL)", 0, 0, "", 0, 0, 0, "h",
         None, None, 0),
        (OPENER, 186, 255, 2, "PT06M26.00S", NUGGETS, JOKIC, "", "", "Jokic BLOCK (1 BLK)", 0, 2, "", 0, 0, 0, "h",
         None, None, 0),
    ]


def test_team_level_actions_carry_the_team_in_team_id_and_other_team_id_0_actions_stay_as_given(db):
    rows = db.execute(
        """
        select action_id, team_id, person_id, description from play_by_play
        where game_id = ? and action_id in (67, 162, 218) order by action_id
        """,
        [OPENER],
    ).fetchall()

    # NBA gives the team rebound and team turnover with Denver in personId and 0 in teamId. The instant replay has
    # teamId 0 and a small personId that isn't a team, so it's kept.
    assert rows == [
        (67, NUGGETS, None, "NUGGETS Rebound"),
        (162, 0, 222, "Instant Replay2nd Period (11:00 PM EST)"),
        (218, NUGGETS, None, "NUGGETS Turnover: Shot Clock (T#11)"),
    ]


class PlayByPlaySource(ReplaySource):
    """Replay source that logs play-by-play requests and times out on ``failing_game``."""

    def __init__(self, fixtures_dir, failing_game=None):
        super().__init__(fixtures_dir)
        self.failing_game = failing_game
        self.play_by_play_requests = []

    def play_by_play(self, game_id):
        self.play_by_play_requests.append(game_id)
        if game_id == self.failing_game:
            raise ConnectionError("stats.nba.com timed out")
        return super().play_by_play(game_id)


def games_held(data_root):
    with duckdb.connect(str(data_root / "hoopdata.duckdb"), read_only=True) as con:
        return con.execute("select season, count(distinct game_id) from play_by_play group by all order by 1").fetchall()


def test_one_failed_game_fails_the_item_and_the_next_run_fetches_only_that_game_even_in_the_latest_season(tmp_path):
    store = Store(tmp_path)
    first = PlayByPlaySource(FIXTURES, failing_game="0022300540")
    report = ingest(first, store, seasons=["2022-23", "2023-24"], datasets=["pbp"], today=IN_SEASON)
    held_after_first = games_held(tmp_path)

    retry = PlayByPlaySource(FIXTURES)
    retry_report = ingest(retry, store, today=IN_SEASON)
    nightly = PlayByPlaySource(FIXTURES)
    ingest(nightly, store, today=IN_SEASON)

    assert [item.name for item in report.failed] == ["play_by_play 2023-24 Regular Season"]
    assert "1 of 8 games failed" in report.failed[0].error
    # The other games were written as they were fetched, and are kept. Each season also has a playoff and a Play-In game.
    assert held_after_first == [("2022-23", 3), ("2023-24", 9)]
    assert retry.play_by_play_requests == ["0022300540"]
    assert retry_report.failed == []
    # 2023-24 is the latest season, but every one of its games is held, so none is requested again.
    assert nightly.play_by_play_requests == []
    assert games_held(tmp_path) == [("2022-23", 3), ("2023-24", 10)]


def test_the_estimate_counts_one_request_per_core_game_not_held_yet(tmp_path, capsys):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"], today=IN_SEASON)
    capsys.readouterr()

    ingest(PlayByPlaySource(FIXTURES, failing_game="0022300540"), store, datasets=["pbp"], today=IN_SEASON)
    first = capsys.readouterr().out
    ingest(PlayByPlaySource(FIXTURES), store, today=IN_SEASON)
    retry = capsys.readouterr().out

    # Core refetches the latest season's 6 game logs each run. Pbp first needs all 3 + 10 core games, a regular season,
    # playoff and Play-In game in 2022-23 and 8 + 1 + 1 in 2023-24, then the one that failed.
    assert "About 19 requests, roughly 19 s (core: 6 · pbp: 13)" in first
    assert "About 7 requests, roughly 7 s (core: 6 · pbp: 1)" in retry


def test_playoff_and_play_in_games_are_stored_under_their_own_season_type_with_the_same_columns_and_rules(tmp_path):
    store = Store(tmp_path)
    report = ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"], datasets=["pbp"], today=SUMMER)

    folder = tmp_path / "pbp" / "play_by_play" / "season=2023-24"
    with duckdb.connect() as con:
        def describe(path):
            return con.execute(f"describe select * from read_parquet('{path.as_posix()}')").fetchall()

        regular_season = describe(folder / "regular_season" / f"{OPENER}.parquet")
        playoffs = describe(folder / "playoffs" / "0042300151.parquet")
        play_in = describe(folder / "playin" / "0052300121.parquet")
        team_ids_as_person_ids = con.execute(
            f"select count(*) from read_parquet('{folder.as_posix()}/playoffs/0042300151.parquet') "
            f"where person_id // 1000 = 1610612"
        ).fetchone()[0]

    assert report.failed == []
    assert playoffs == regular_season
    assert play_in == regular_season
    assert (tmp_path / "pbp" / "play_by_play" / "season=2022-23" / "playoffs" / "0042200311.parquet").exists()
    assert (tmp_path / "pbp" / "play_by_play" / "season=2022-23" / "playin" / "0052200121.parquet").exists()
    assert team_ids_as_person_ids == 0


class MissingCorePlayoffsSource(PlayByPlaySource):
    """Replay source whose 2022-23 playoffs team game log times out while ``failing``."""

    def __init__(self, fixtures_dir, failing=True):
        super().__init__(fixtures_dir)
        self.core_failing = failing

    def game_log(self, season, season_type, kind):
        if self.core_failing and (season, season_type, kind) == ("2022-23", "Playoffs", "team"):
            raise ConnectionError("stats.nba.com timed out")
        return super().game_log(season, season_type, kind)


def test_a_pbp_item_whose_core_season_type_isnt_held_fails_without_requests_and_succeeds_once_core_has_it(tmp_path):
    store = Store(tmp_path)
    first = MissingCorePlayoffsSource(FIXTURES)
    report = ingest(first, store, seasons=["2022-23"], datasets=["pbp"], today=SUMMER)

    retry = MissingCorePlayoffsSource(FIXTURES, failing=False)
    retry_report = ingest(retry, store, today=SUMMER)

    pbp_failed = [item for item in report.failed if item.table == "play_by_play"]
    assert [item.name for item in pbp_failed] == ["play_by_play 2022-23 Playoffs"]
    assert "core holds no team box scores for 2022-23 Playoffs" in pbp_failed[0].error
    assert "0042200311" not in first.play_by_play_requests
    assert retry.play_by_play_requests == ["0042200311"]
    assert retry_report.failed == []


class EmptyCorePlayoffsSource(PlayByPlaySource):
    """Replay source whose 2022-23 playoffs game logs come back with no games, as before the playoffs start."""

    def game_log(self, season, season_type, kind):
        response = super().game_log(season, season_type, kind)
        if (season, season_type) == ("2022-23", "Playoffs"):
            response["resultSets"][0]["rowSet"] = []
        return response


def test_a_pbp_item_whose_core_season_type_holds_no_games_fails_without_requests(tmp_path):
    source = EmptyCorePlayoffsSource(FIXTURES)
    report = ingest(source, Store(tmp_path), seasons=["2022-23"], datasets=["pbp"], today=SUMMER)

    assert [item.name for item in report.failed] == ["play_by_play 2022-23 Playoffs"]
    assert "core holds no team box scores for 2022-23 Playoffs" in report.failed[0].error
    assert "0042200311" not in source.play_by_play_requests


def test_there_are_no_play_in_items_before_2019_20(tmp_path):
    # No core fixtures exist for 2018-19, so core holds nothing and every pbp item of the season fails.
    report = ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2018-19"], datasets=["pbp"], today=SUMMER)

    assert sorted(item.name for item in report.failed if item.table == "play_by_play") == [
        "play_by_play 2018-19 Playoffs", "play_by_play 2018-19 Regular Season",
    ]


def test_without_pbp_selected_play_by_play_and_its_views_dont_exist(tmp_path):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], datasets=["shots"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        views = {row[0] for row in con.execute("select view_name from duckdb_views() where not internal").fetchall()}
    assert "shots" in views
    assert {"play_by_play", "pbp_reconciliation", "pbp_reconciliation_seasons"}.isdisjoint(views)


STATS = ["pts", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "reb", "ast", "stl", "blk", "tov", "pf"]


@pytest.fixture
def both_seasons(tmp_path):
    """Ingest 2022-23 and 2023-24 with pbp and open the published file read-only."""
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2022-23", "2023-24"], datasets=["pbp"], today=SUMMER)
    con = duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True)
    yield con
    con.close()


def test_every_fixture_game_reconciles_with_its_box_scores_on_every_stat(both_seasons):
    rows = both_seasons.execute("select game_id, team_id, matches from pbp_reconciliation order by all").fetchall()
    opener_denver = both_seasons.execute(
        f"select {', '.join(f'pbp_{stat}, box_{stat}' for stat in STATS)} from pbp_reconciliation "
        "where game_id = ? and team_id = ?",
        [OPENER, NUGGETS],
    ).fetchone()

    # Thirteen games, two teams each: nine regular season, two playoff and two Play-In. The fixtures hold technicals,
    # a defensive three seconds, flopping, a flagrant, team rebounds and team turnovers, so the counting rules are all
    # exercised.
    assert len(rows) == 26
    assert all(matches for _, _, matches in rows)
    # Denver's opener box score: 125 PTS, 49-93 FG, 13-30 3PT, 14-19 FT, 51 REB, 33 AST, 11 STL, 6 BLK, 20 TOV, 17 PF.
    assert opener_denver == (
        125, 125, 49, 49, 93, 93, 13, 13, 30, 30, 14, 14, 19, 19, 51, 51, 33, 33, 11, 11, 6, 6, 20, 20, 17, 17,
    )


def test_the_fixtures_hold_every_action_the_counting_rules_treat_specially(both_seasons):
    def count(where):
        return both_seasons.execute(f"select count(*) from play_by_play where {where}").fetchone()[0]

    assert count("action_type = 'Foul' and sub_type = 'Technical'") > 0
    assert count("action_type = 'Rebound' and person_id is null") > 0
    assert count("action_type = 'Turnover' and person_id is null") > 0
    assert count("description like '%STEAL%'") > 0
    assert count("description like '%BLOCK%'") > 0


def test_the_2019_20_bubble_game_is_stored_as_play_in_and_reconciles(tmp_path):
    # Only the bubble game has 2019-20 core fixtures, so the regular season and playoff items fail.
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2019-20"], datasets=["pbp"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        rows = con.execute("select * from pbp_reconciliation_seasons").fetchall()

    assert (tmp_path / "pbp" / "play_by_play" / "season=2019-20" / "playin" / "0051900111.parquet").exists()
    assert rows == [("2019-20", "PlayIn", 1, 1, 1.0)]


class DroppedShotSource(ReplaySource):
    """Replay source whose opener play-by-play is missing Jokic's opening layup (action 9, a made 2)."""

    def play_by_play(self, game_id):
        response = super().play_by_play(game_id)
        if game_id == OPENER:
            actions = response["game"]["actions"]
            response["game"]["actions"] = [action for action in actions if action["actionId"] != 9]
        return response


def test_a_dropped_made_shot_shows_as_a_mismatch_in_pts_fgm_and_fga_without_failing_any_item(tmp_path):
    report = ingest(DroppedShotSource(FIXTURES), Store(tmp_path), seasons=["2023-24"], datasets=["pbp"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        mismatches = con.execute("select game_id, team_id from pbp_reconciliation where not matches").fetchall()
        denver = con.execute(
            f"select {', '.join(f'pbp_{stat} - box_{stat}' for stat in STATS)} from pbp_reconciliation "
            "where game_id = ? and team_id = ?",
            [OPENER, NUGGETS],
        ).fetchone()

    assert report.failed == []
    assert mismatches == [(OPENER, NUGGETS)]
    # Only PTS, FGM and FGA are off, by the layup's 2 points and one shot.
    assert dict(zip(STATS, denver)) == {stat: 0 for stat in STATS} | {"pts": -2, "fgm": -1, "fga": -1}


def test_the_season_rollup_counts_games_and_games_where_both_teams_match(tmp_path):
    ingest(DroppedShotSource(FIXTURES), Store(tmp_path), seasons=["2022-23", "2023-24"], datasets=["pbp"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        rows = con.execute("select * from pbp_reconciliation_seasons order by season, season_type").fetchall()

    # The opener's Dallas side still matches, but the game doesn't.
    assert rows == [
        ("2022-23", "PlayIn", 1, 1, 1.0),
        ("2022-23", "Playoffs", 1, 1, 1.0),
        ("2022-23", "Regular Season", 1, 1, 1.0),
        ("2023-24", "PlayIn", 1, 1, 1.0),
        ("2023-24", "Playoffs", 1, 1, 1.0),
        ("2023-24", "Regular Season", 8, 7, 0.875),
    ]
