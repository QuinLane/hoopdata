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

RATES = [
    "off_rating", "def_rating", "net_rating", "ast_pct", "ast_to", "ast_ratio", "oreb_pct", "dreb_pct",
    "reb_pct", "tm_tov_pct", "efg_pct", "ts_pct", "usg_pct", "pace", "pace_per40", "pie",
]


@pytest.fixture
def db(tmp_path):
    """Ingest 2023-24 with advanced from the replay source and open the published file read-only."""
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], datasets=["advanced"], today=SUMMER)
    con = duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True)
    yield con
    con.close()


def test_player_advanced_box_scores_hold_the_official_rates_as_given_with_only_the_kept_columns(db):
    columns = db.execute("select column_name, column_type from (describe player_advanced_box_scores)").fetchall()
    row = db.execute(
        "select * from player_advanced_box_scores where game_id = '0022300034' and player_id = ?", [JOKIC]
    ).fetchall()

    assert columns == [
        ("season", "VARCHAR"), ("season_type", "VARCHAR"), ("game_id", "VARCHAR"),
        ("player_id", "BIGINT"), ("team_id", "BIGINT"),
        *[(rate, "DOUBLE") for rate in RATES if rate != "pie"], ("poss", "BIGINT"), ("pie", "DOUBLE"),
    ]
    # Jokic at New Orleans on 2023-11-17, exactly as the fixture gives it: ast_pct a fraction, tm_tov_pct a percent.
    assert row == [(
        "2023-24", "Regular Season", "0022300034", JOKIC, NUGGETS,
        129.2, 122.2, 6.9, 0.621, 4.5, 41.9, 0.063, 0.4, 0.239, 9.3, 0.525, 0.586, 0.313, 95.56, 79.63, 72, 0.234,
    )]


def test_player_advanced_game_stats_carries_cores_name_team_date_and_result(db):
    row = db.execute(
        """
        select player_name, team_abbreviation, game_date, wl, off_rating, poss
        from player_advanced_game_stats where game_id = '0022300034' and player_id = ?
        """,
        [JOKIC],
    ).fetchone()

    assert row == ("Nikola Jokić", "DEN", date(2023, 11, 17), "L", 129.2, 72)


def test_every_advanced_row_joins_a_core_box_score_and_every_core_box_score_has_one(tmp_path):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2022-23", "2023-24"], datasets=["advanced"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        advanced_only, core_only, matched = con.execute(
            """
            select
                count(*) filter (where core.game_id is null),
                count(*) filter (where advanced.game_id is null),
                count(*) filter (where core.game_id is not null and advanced.game_id is not null)
            from player_advanced_box_scores as advanced
            full join player_box_scores as core using (game_id, player_id)
            """
        ).fetchone()

    assert (advanced_only, core_only) == (0, 0)
    assert matched == 27 + 2 + 16 + 64 + 4 + 19


class BackfillSource(ReplaySource):
    """Replay source that logs advanced requests and stands in 2022-23 for game logs without fixtures."""

    def __init__(self, fixtures_dir):
        super().__init__(fixtures_dir)
        self.advanced_requests = []

    def game_log(self, season, season_type, kind):
        try:
            return super().game_log(season, season_type, kind)
        except FileNotFoundError:
            return super().game_log("2022-23", season_type, kind)

    def player_advanced_game_log(self, season, season_type):
        self.advanced_requests.append((season, season_type))
        try:
            return super().player_advanced_game_log(season, season_type)
        except FileNotFoundError:
            return super().player_advanced_game_log("2022-23", season_type)


def test_play_in_is_its_own_season_type_and_is_never_requested_before_2019_20(tmp_path):
    source = BackfillSource(FIXTURES)

    ingest(source, Store(tmp_path), seasons=["2018-19", "2019-20"], datasets=["advanced"], today=SUMMER)

    assert source.advanced_requests == [
        ("2018-19", "Regular Season"), ("2018-19", "Playoffs"),
        ("2019-20", "Regular Season"), ("2019-20", "PlayIn"), ("2019-20", "Playoffs"),
    ]
    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        # The 2019-20 bubble game Portland won against Memphis, which NBA labels Play-In.
        season_types = con.execute(
            "select distinct season, season_type from player_advanced_game_stats where game_id = '0051900111'"
        ).fetchall()
    assert season_types == [("2019-20", "PlayIn")]


class FailingAdvancedPlayoffsSource(BackfillSource):
    def __init__(self, fixtures_dir, failing=True):
        super().__init__(fixtures_dir)
        self.failing = failing

    def player_advanced_game_log(self, season, season_type):
        if self.failing and season_type == "Playoffs":
            self.advanced_requests.append((season, season_type))
            raise ConnectionError("stats.nba.com timed out")
        return super().player_advanced_game_log(season, season_type)


def test_a_failed_advanced_item_is_retried_and_succeeded_ones_are_refetched_only_for_the_latest_season(tmp_path):
    store = Store(tmp_path)
    ingest(
        FailingAdvancedPlayoffsSource(FIXTURES), store, seasons=["2022-23", "2023-24"], datasets=["advanced"],
        today=SUMMER,
    )

    retry = FailingAdvancedPlayoffsSource(FIXTURES, failing=False)
    ingest(retry, store, today=SUMMER)
    nightly = FailingAdvancedPlayoffsSource(FIXTURES, failing=False)
    ingest(nightly, store, today=SUMMER)

    assert retry.advanced_requests == [("2022-23", "Playoffs"), ("2023-24", "Playoffs")]
    assert nightly.advanced_requests == [("2023-24", "Regular Season"), ("2023-24", "PlayIn"), ("2023-24", "Playoffs")]


def test_the_estimate_counts_one_request_per_advanced_item(tmp_path, capsys):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"], today=SUMMER)
    capsys.readouterr()

    ingest(ReplaySource(FIXTURES), store, datasets=["advanced"], today=SUMMER)

    # 2023-24 is the latest season, so core refetches its 6 game logs. advanced has 3 per season, all missing.
    assert "About 12 requests, roughly 12 s (core: 6 · advanced: 6)" in capsys.readouterr().out


def test_without_advanced_selected_its_views_dont_exist(tmp_path):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        views = {row[0] for row in con.execute("select view_name from duckdb_views() where not internal").fetchall()}
    assert "player_advanced_game_stats" not in views
    assert "player_advanced_box_scores" not in views
