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
# On Denver's 2022-23 roster but out all season with a broken leg, so never in a box score.
GILLESPIE = 1631221
NUGGETS = 1610612743
LAKERS = 1610612747


@pytest.fixture
def db(tmp_path):
    """Ingest 2022-23 and 2023-24 with rosters from the replay source and open the published file read-only."""
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2022-23", "2023-24"], datasets=["rosters"], today=SUMMER)
    con = duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True)
    yield con
    con.close()


def test_official_rosters_hold_each_player_as_given_with_only_the_kept_columns(db):
    columns = db.execute("select column_name, column_type from (describe official_rosters)").fetchall()
    rows = db.execute(
        "select * from official_rosters where team_id = ? and player_id in (?, ?) order by season, player_id",
        [NUGGETS, JOKIC, GILLESPIE],
    ).fetchall()
    teams = db.execute("select season, count(distinct team_id) from official_rosters group by all order by 1").fetchall()

    assert columns == [
        ("season", "VARCHAR"), ("team_id", "BIGINT"), ("player_id", "BIGINT"), ("player_name", "VARCHAR"),
        ("jersey_number", "VARCHAR"), ("position", "VARCHAR"), ("experience", "VARCHAR"), ("how_acquired", "VARCHAR"),
    ]
    assert rows == [
        ("2022-23", NUGGETS, JOKIC, "Nikola Jokić", "15", "C", "7", "#41 Pick in 2014 Draft"),
        ("2022-23", NUGGETS, GILLESPIE, "Collin Gillespie", "21", "G", "R", None),
        ("2023-24", NUGGETS, JOKIC, "Nikola Jokić", "15", "C", "8", "#41 Pick in 2014 Draft"),
        ("2023-24", NUGGETS, GILLESPIE, "Collin Gillespie", "21", "G", "R", None),
    ]
    # Every team in core's team box scores, across season types: DEN, LAL, MIN in 2022-23; 11 teams in 2023-24.
    assert teams == [("2022-23", 3), ("2023-24", 11)]


def test_official_roster_details_adds_cores_team_and_the_bio_only_for_players_who_appeared(db):
    rows = db.execute(
        """
        select player_name, jersey_number, position, team_abbreviation, display_name, birthdate, height_in, draft_number
        from official_roster_details where season = '2022-23' and player_id in (?, ?) order by player_id
        """,
        [JOKIC, GILLESPIE],
    ).fetchall()

    assert rows == [
        ("Nikola Jokić", "15", "C", "DEN", "Nikola Jokić", date(1995, 2, 19), 6 * 12 + 11, 41),
        ("Collin Gillespie", "21", "G", "DEN", None, None, None, None),
    ]


class RosterSource(ReplaySource):
    """Replay source that logs team roster requests, times out on the Lakers' while ``lakers_fail``, and while
    ``core_missing`` holds no game logs for that season."""

    def __init__(self, fixtures_dir, lakers_fail=False, core_missing=None):
        super().__init__(fixtures_dir)
        self.lakers_fail = lakers_fail
        self.core_missing = core_missing
        self.team_roster_requests = []

    def game_log(self, season, season_type, kind):
        if season == self.core_missing:
            raise ConnectionError("stats.nba.com timed out")
        return super().game_log(season, season_type, kind)

    def team_roster(self, season, team_id):
        self.team_roster_requests.append((season, team_id))
        if self.lakers_fail and team_id == LAKERS:
            raise ConnectionError("stats.nba.com timed out")
        return super().team_roster(season, team_id)


def roster_teams(data_root, season):
    with duckdb.connect(str(data_root / "hoopdata.duckdb"), read_only=True) as con:
        return con.execute(
            "select count(distinct team_id) from official_rosters where season = ?", [season]
        ).fetchone()[0]


def test_one_failed_team_call_fails_the_item_which_is_retried_and_only_the_latest_season_is_refetched(tmp_path):
    store = Store(tmp_path)
    report = ingest(
        RosterSource(FIXTURES, lakers_fail=True), store, seasons=["2022-23", "2023-24"], datasets=["rosters"],
        today=SUMMER,
    )

    retry = RosterSource(FIXTURES)
    ingest(retry, store, today=SUMMER)
    nightly = RosterSource(FIXTURES)
    ingest(nightly, store, today=SUMMER)

    assert [item.name for item in report.failed] == ["official_rosters 2022-23", "official_rosters 2023-24"]
    assert {season for season, _ in retry.team_roster_requests} == {"2022-23", "2023-24"}
    assert {season for season, _ in nightly.team_roster_requests} == {"2023-24"}
    assert roster_teams(tmp_path, "2022-23") == 3


def test_a_season_core_doesnt_hold_fails_without_roster_requests_and_succeeds_once_core_has_it(tmp_path):
    store = Store(tmp_path)
    source = RosterSource(FIXTURES, core_missing="2022-23")
    report = ingest(source, store, seasons=["2022-23", "2023-24"], datasets=["rosters"], today=SUMMER)

    later = RosterSource(FIXTURES)
    later_report = ingest(later, store, today=SUMMER)

    assert "official_rosters 2022-23" in [item.name for item in report.failed]
    assert {season for season, _ in source.team_roster_requests} == {"2023-24"}
    assert later_report.failed == []
    assert roster_teams(tmp_path, "2022-23") == 3


def test_the_estimate_counts_30_requests_per_rosters_season(tmp_path, capsys):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"], today=SUMMER)
    capsys.readouterr()

    ingest(ReplaySource(FIXTURES), store, datasets=["rosters"], today=SUMMER)

    # 2023-24 is the latest season, so core refetches its 6 game logs. rosters has one item per season.
    assert "About 66 requests, roughly 1 min (core: 6 · rosters: 60)" in capsys.readouterr().out


def test_without_rosters_selected_its_views_dont_exist(tmp_path):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        views = {row[0] for row in con.execute("select view_name from duckdb_views() where not internal").fetchall()}
    assert "official_rosters" not in views
    assert "official_roster_details" not in views
