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
MALONE = 2610
POPEYE_JONES = 202434
HAM = 203005  # Lakers head coach in 2022-23; their 2023-24 report, made after he was fired, lists no head coach
BORREGO = 202435  # Pelicans associate head coach in 2023-24
NUGGETS = 1610612743
LAKERS = 1610612747
PELICANS = 1610612740


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


def test_coach_seasons_hold_only_coaches_as_given_with_only_the_kept_columns(db):
    columns = db.execute("select column_name, column_type from (describe coach_seasons)").fetchall()
    rows = db.execute(
        "select * from coach_seasons where season = '2023-24' and team_id = ? order by coach_id", [NUGGETS]
    ).fetchall()
    coach_types = db.execute("select distinct coach_type from coach_seasons order by 1").fetchall()

    assert columns == [
        ("season", "VARCHAR"), ("team_id", "BIGINT"), ("coach_id", "BIGINT"), ("first_name", "VARCHAR"),
        ("last_name", "VARCHAR"), ("coach_name", "VARCHAR"), ("coach_type", "VARCHAR"),
    ]
    # Dan Shimensky, the trainer, is left out.
    assert rows == [
        ("2023-24", NUGGETS, MALONE, "Michael", "Malone", "Michael Malone", "Head Coach"),
        ("2023-24", NUGGETS, 202434, "Popeye", "Jones", "Popeye Jones", "Assistant Coach"),
        ("2023-24", NUGGETS, 202443, "Ryan", "Saunders", "Ryan Saunders", "Assistant Coach"),
        ("2023-24", NUGGETS, 202894, "Charles", "Klask", "Charles Klask", "Assistant Coach"),
        ("2023-24", NUGGETS, 203391, "Ryan", "Bowen", "Ryan Bowen", "Assistant Coach"),
        ("2023-24", NUGGETS, 203600, "David", "Adelman", "David Adelman", "Assistant Coach"),
        ("2023-24", NUGGETS, 1630491, "John", "Beckett", "John Beckett", "Assistant Coach"),
        ("2023-24", NUGGETS, 1630932, "Ognjen", "Stojakovic", "Ognjen Stojakovic", "Assistant Coach"),
        ("2023-24", NUGGETS, 1641545, "Elvis", "Valcarcel", "Elvis Valcarcel", "Assistant Coach"),
    ]
    # Trainers and assistant trainers are dropped.
    assert coach_types == [
        ("Assistant Coach",), ("Assistant Coach for Player Development",), ("Associate Head Coach",),
        ("Head Coach",), ("Lead Assistant Coach",),
    ]


def test_coach_views_follow_each_coach_across_teams_and_seasons(db):
    coaches = db.execute(
        "select * from coaches where coach_id in (?, ?, ?) order by coach_id", [MALONE, POPEYE_JONES, HAM]
    ).fetchall()
    coach_teams = db.execute(
        "select * from coach_teams where coach_id in (?, ?, ?, ?) order by coach_id",
        [MALONE, POPEYE_JONES, BORREGO, HAM],
    ).fetchall()
    team_coaches = db.execute(
        "select * from team_coaches where coach_id = ? order by season", [MALONE]
    ).fetchall()

    assert coaches == [
        (MALONE, "Michael", "Malone", "Michael Malone", "2022-23", "2023-24"),
        (POPEYE_JONES, "Popeye", "Jones", "Popeye Jones", "2022-23", "2023-24"),
        (HAM, "Darvin", "Ham", "Darvin Ham", "2022-23", "2022-23"),
    ]
    # An associate head coach isn't the head coach.
    assert coach_teams == [
        (MALONE, "Michael Malone", NUGGETS, "DEN", "2022-23", "2023-24", 2, 2),
        (POPEYE_JONES, "Popeye Jones", NUGGETS, "DEN", "2022-23", "2023-24", 2, 0),
        (BORREGO, "James Borrego", PELICANS, "NOP", "2023-24", "2023-24", 1, 0),
        (HAM, "Darvin Ham", LAKERS, "LAL", "2022-23", "2022-23", 1, 1),
    ]
    assert team_coaches == [
        ("2022-23", NUGGETS, MALONE, "Michael", "Malone", "Michael Malone", "Head Coach", "DEN"),
        ("2023-24", NUGGETS, MALONE, "Michael", "Malone", "Michael Malone", "Head Coach", "DEN"),
    ]


class OfficialRosterSource(ReplaySource):
    """Replay source that logs official roster requests, times out on the Lakers' while ``lakers_fail``, and while
    ``core_missing`` holds no game logs for that season."""

    def __init__(self, fixtures_dir, lakers_fail=False, core_missing=None):
        super().__init__(fixtures_dir)
        self.lakers_fail = lakers_fail
        self.core_missing = core_missing
        self.official_roster_requests = []

    def game_log(self, season, season_type, kind):
        if season == self.core_missing:
            raise ConnectionError("stats.nba.com timed out")
        return super().game_log(season, season_type, kind)

    def official_roster(self, season, team_id):
        self.official_roster_requests.append((season, team_id))
        if self.lakers_fail and team_id == LAKERS:
            raise ConnectionError("stats.nba.com timed out")
        return super().official_roster(season, team_id)


def official_roster_team_count(data_root, season):
    with duckdb.connect(str(data_root / "hoopdata.duckdb"), read_only=True) as con:
        return con.execute(
            "select count(distinct team_id) from official_rosters where season = ?", [season]
        ).fetchone()[0]


def test_one_failed_team_call_fails_both_items_which_are_retried_and_only_the_latest_season_is_refetched(tmp_path):
    store = Store(tmp_path)
    report = ingest(
        OfficialRosterSource(FIXTURES, lakers_fail=True), store, seasons=["2022-23", "2023-24"],
        datasets=["rosters"], today=SUMMER,
    )

    retry = OfficialRosterSource(FIXTURES)
    ingest(retry, store, today=SUMMER)
    nightly = OfficialRosterSource(FIXTURES)
    ingest(nightly, store, today=SUMMER)

    assert [item.name for item in report.failed] == [
        "official_rosters 2022-23", "coach_seasons 2022-23", "official_rosters 2023-24", "coach_seasons 2023-24",
    ]
    # One call per team and season fills both tables: 3 teams in 2022-23 and 11 in 2023-24.
    assert len(retry.official_roster_requests) == 14
    assert {season for season, _ in retry.official_roster_requests} == {"2022-23", "2023-24"}
    assert {season for season, _ in nightly.official_roster_requests} == {"2023-24"}
    assert official_roster_team_count(tmp_path, "2022-23") == 3


def test_a_season_core_doesnt_hold_fails_without_roster_requests_and_succeeds_once_core_has_it(tmp_path):
    store = Store(tmp_path)
    source = OfficialRosterSource(FIXTURES, core_missing="2022-23")
    report = ingest(source, store, seasons=["2022-23", "2023-24"], datasets=["rosters"], today=SUMMER)

    later = OfficialRosterSource(FIXTURES)
    later_report = ingest(later, store, today=SUMMER)

    assert {"official_rosters 2022-23", "coach_seasons 2022-23"} <= {item.name for item in report.failed}
    assert {season for season, _ in source.official_roster_requests} == {"2023-24"}
    assert later_report.failed == []
    assert official_roster_team_count(tmp_path, "2022-23") == 3


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
    assert not views & {
        "official_rosters", "official_roster_details", "coach_seasons", "coaches", "coach_teams", "team_coaches",
    }
