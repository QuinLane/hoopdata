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
    # The other games were written as they were fetched, and are kept.
    assert held_after_first == [("2022-23", 1), ("2023-24", 7)]
    assert retry.play_by_play_requests == ["0022300540"]
    assert retry_report.failed == []
    # 2023-24 is the latest season, but every one of its games is held, so none is requested again.
    assert nightly.play_by_play_requests == []
    assert games_held(tmp_path) == [("2022-23", 1), ("2023-24", 8)]


def test_the_estimate_counts_one_request_per_core_game_not_held_yet(tmp_path, capsys):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"], today=IN_SEASON)
    capsys.readouterr()

    ingest(PlayByPlaySource(FIXTURES, failing_game="0022300540"), store, datasets=["pbp"], today=IN_SEASON)
    first = capsys.readouterr().out
    ingest(PlayByPlaySource(FIXTURES), store, today=IN_SEASON)
    retry = capsys.readouterr().out

    # Core refetches the latest season's 6 game logs each run. Pbp first needs all 1 + 8 core games, then the one
    # that failed.
    assert "About 15 requests, roughly 15 s (core: 6 · pbp: 9)" in first
    assert "About 7 requests, roughly 7 s (core: 6 · pbp: 1)" in retry


def test_without_pbp_selected_play_by_play_doesnt_exist(tmp_path):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], datasets=["shots"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        views = {row[0] for row in con.execute("select view_name from duckdb_views() where not internal").fetchall()}
    assert "shots" in views
    assert "play_by_play" not in views
