from datetime import date
from pathlib import Path

import duckdb
import pytest

from hoopdata.ingest import ingest
from hoopdata.source import ReplaySource
from hoopdata.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
SUMMER = date(2024, 7, 1)
JOKIC = 203999
NUGGETS = 1610612743
LAKERS = 1610612747


@pytest.fixture
def db(tmp_path):
    """Ingest 2022-23 and 2023-24 with shots from the replay source and open the published file read-only."""
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2022-23", "2023-24"], datasets=["shots"], today=SUMMER)
    con = duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True)
    yield con
    con.close()


def test_shots_hold_each_shot_as_given_with_only_the_kept_columns(db):
    columns = db.execute("select column_name, column_type from (describe shots)").fetchall()
    row = db.execute(
        "select * from shots where game_id = '0022300034' and game_event_id = 13 and player_id = ?", [JOKIC]
    ).fetchall()

    assert columns == [
        ("season", "VARCHAR"), ("season_type", "VARCHAR"), ("game_id", "VARCHAR"), ("game_event_id", "BIGINT"),
        ("player_id", "BIGINT"), ("team_id", "BIGINT"), ("period", "BIGINT"), ("minutes_remaining", "BIGINT"),
        ("seconds_remaining", "BIGINT"), ("action_type", "VARCHAR"), ("shot_type", "VARCHAR"),
        ("shot_zone_basic", "VARCHAR"), ("shot_zone_area", "VARCHAR"), ("shot_zone_range", "VARCHAR"),
        ("shot_distance", "BIGINT"), ("loc_x", "BIGINT"), ("loc_y", "BIGINT"), ("shot_made_flag", "BIGINT"),
    ]
    # Jokic's first shot at New Orleans on 2023-11-17, a missed three, exactly as the fixture gives it.
    assert row == [(
        "2023-24", "Regular Season", "0022300034", 13, JOKIC, NUGGETS, 1, 10, 35,
        "Jump Shot", "3PT Field Goal", "Above the Break 3", "Left Side Center(LC)", "24+ ft.", 25, -88, 240, 0,
    )]


def test_each_games_shots_add_up_to_core_fga_and_fgm(db):
    mismatches = db.execute(
        """
        select core.game_id, core.team_id, core.fga, core.fgm, count(shots.game_id), sum(shots.shot_made_flag)
        from team_box_scores as core
        left join shots using (game_id, team_id)
        group by all
        having count(shots.game_id) != core.fga or sum(shots.shot_made_flag) != core.fgm
        """
    ).fetchall()
    games = db.execute("select season_type, count(distinct game_id) from shots group by all order by all").fetchall()

    assert mismatches == []
    assert games == [("PlayIn", 2), ("Playoffs", 2), ("Regular Season", 1 + 8)]


def test_the_2019_20_bubble_game_has_play_in_shots_and_no_earlier_season_requests_play_in(tmp_path):
    source = FailingLakersSource(FIXTURES, failing=False)
    ingest(source, Store(tmp_path), seasons=["2018-19", "2019-20"], datasets=["shots"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        mismatches = con.execute(
            """
            select core.game_id, core.team_id
            from team_box_scores as core
            left join shots using (game_id, team_id, season_type)
            group by all
            having count(shots.game_id) != any_value(core.fga) or sum(shots.shot_made_flag) != any_value(core.fgm)
            """
        ).fetchall()
        season_types = con.execute("select distinct season, season_type from shots").fetchall()

    assert mismatches == []
    # The bubble game Portland won against Memphis, which NBA labels Play-In.
    assert season_types == [("2019-20", "PlayIn")]
    assert {(season, season_type) for season, season_type, _ in source.shot_chart_requests} == {("2019-20", "PlayIn")}


def test_shot_details_carries_cores_name_team_date_and_result(db):
    row = db.execute(
        """
        select player_name, team_abbreviation, game_date, wl, action_type, shot_made_flag
        from shot_details where game_id = '0022300034' and game_event_id = 13 and player_id = ?
        """,
        [JOKIC],
    ).fetchone()

    assert row == ("Nikola Jokić", "DEN", date(2023, 11, 17), "L", "Jump Shot", 0)


class FailingLakersSource(ReplaySource):
    """Replay source that logs shot chart requests and, while ``failing``, times out on the Lakers' regular season."""

    def __init__(self, fixtures_dir, failing=True):
        super().__init__(fixtures_dir)
        self.failing = failing
        self.shot_chart_requests = []

    def shot_chart(self, season, season_type, team_id):
        self.shot_chart_requests.append((season, season_type, team_id))
        if self.failing and team_id == LAKERS and season_type == "Regular Season":
            raise ConnectionError("stats.nba.com timed out")
        return super().shot_chart(season, season_type, team_id)


def test_one_failed_team_request_fails_the_item_which_is_retried_and_only_the_latest_season_is_refetched(tmp_path):
    store = Store(tmp_path)
    report = ingest(
        FailingLakersSource(FIXTURES), store, seasons=["2022-23", "2023-24"], datasets=["shots"], today=SUMMER
    )

    retry = FailingLakersSource(FIXTURES, failing=False)
    ingest(retry, store, today=SUMMER)
    nightly = FailingLakersSource(FIXTURES, failing=False)
    ingest(nightly, store, today=SUMMER)

    assert [item.name for item in report.failed] == ["shots 2022-23 Regular Season"]
    assert [(season, team) for season, season_type, team in retry.shot_chart_requests if season == "2022-23"] == [
        ("2022-23", NUGGETS), ("2022-23", LAKERS),
    ]
    assert {season for season, _, _ in nightly.shot_chart_requests} == {"2023-24"}
    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        games = con.execute(
            "select count(distinct game_id) from shots where season = '2022-23' and season_type = 'Regular Season'"
        ).fetchone()[0]
    assert games == 1


class MissingCorePlayoffsSource(FailingLakersSource):
    """Replay source whose 2022-23 playoffs team game log times out while ``failing``."""

    def __init__(self, fixtures_dir, failing=True):
        super().__init__(fixtures_dir, failing=False)
        self.core_failing = failing

    def game_log(self, season, season_type, kind):
        if self.core_failing and (season, season_type, kind) == ("2022-23", "Playoffs", "team"):
            raise ConnectionError("stats.nba.com timed out")
        return super().game_log(season, season_type, kind)


def test_a_shots_item_whose_core_season_isnt_held_fails_without_requests_and_succeeds_once_core_has_it(tmp_path):
    store = Store(tmp_path)
    first = MissingCorePlayoffsSource(FIXTURES)
    report = ingest(first, store, seasons=["2022-23"], datasets=["shots"], today=SUMMER)

    retry = MissingCorePlayoffsSource(FIXTURES, failing=False)
    ingest(retry, store, today=SUMMER)

    shots_failed = [item for item in report.failed if item.table == "shots"]
    assert [item.name for item in shots_failed] == ["shots 2022-23 Playoffs"]
    assert "core holds no team box scores for 2022-23 Playoffs" in shots_failed[0].error
    assert [request for request in first.shot_chart_requests if request[1] == "Playoffs"] == []
    assert retry.shot_chart_requests == [("2022-23", "Playoffs", NUGGETS), ("2022-23", "Playoffs", LAKERS)]
    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        games = con.execute("select count(distinct game_id) from shots where season_type = 'Playoffs'").fetchone()[0]
    assert games == 1


class EmptyCorePlayoffsSource(FailingLakersSource):
    """Replay source whose 2022-23 playoffs game logs come back with no games, as before the playoffs start."""

    def game_log(self, season, season_type, kind):
        response = super().game_log(season, season_type, kind)
        if (season, season_type) == ("2022-23", "Playoffs"):
            response["resultSets"][0]["rowSet"] = []
        return response


def test_a_shots_item_whose_core_season_type_holds_no_games_fails_without_requests(tmp_path):
    source = EmptyCorePlayoffsSource(FIXTURES, failing=False)
    report = ingest(source, Store(tmp_path), seasons=["2022-23"], datasets=["shots"], today=SUMMER)

    assert [item.name for item in report.failed] == ["shots 2022-23 Playoffs"]
    assert "core holds no team box scores for 2022-23 Playoffs" in report.failed[0].error
    assert [request for request in source.shot_chart_requests if request[1] == "Playoffs"] == []


def test_the_estimate_counts_30_16_and_8_requests_per_regular_season_playoffs_and_play_in_shots_item(
    tmp_path, capsys
):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"], today=SUMMER)
    capsys.readouterr()

    ingest(ReplaySource(FIXTURES), store, datasets=["shots"], today=SUMMER)

    # 2023-24 is the latest season, so core refetches its 6 game logs. Each season's shots items take 30 + 16 + 8.
    assert "About 114 requests, roughly 2 min (core: 6 · shots: 108)" in capsys.readouterr().out


def test_without_shots_selected_shot_details_doesnt_exist(tmp_path):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        views = {row[0] for row in con.execute("select view_name from duckdb_views() where not internal").fetchall()}
    assert "shot_details" not in views
    assert "shots" not in views
