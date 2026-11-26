from datetime import date
from pathlib import Path

import duckdb
import pytest

from hoopdata.ingest import ingest
from hoopdata.source import ReplaySource
from hoopdata.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
JOKIC = 203999
SIAKAM = 1627783
RAPTORS = 1610612761
PACERS = 1610612754
NUGGETS = 1610612743


@pytest.fixture
def db(tmp_path):
    """Ingest 2023-24 from the replay source and open the published file read-only."""
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"])
    con = duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True)
    yield con
    con.close()


def test_season_shooting_percentage_comes_from_summed_makes_and_attempts(db):
    # Jokic, first 3 games: 14/16, 8/23, 10/20. Summed: 32/59 = .542.
    # Averaging the per-game percentages would give .574.
    games, pts, fg_pct = db.execute(
        """
        select games_played, pts, fg_pct from player_season_averages
        where player_id = ? and season = '2023-24' and season_type = 'Regular Season'
        """,
        [JOKIC],
    ).fetchone()

    assert games == 3
    assert pts == pytest.approx((33 + 32 + 26) / 3)
    assert fg_pct == pytest.approx(32 / 59)


def test_box_scores_keep_nba_ids_and_integer_counts(db):
    types = dict(db.execute("select column_name, column_type from (describe player_box_scores)").fetchall())

    assert types["game_id"] == "VARCHAR"
    assert types["game_date"] == "DATE"
    assert types["season"] == "VARCHAR"
    for column in ["player_id", "team_id", "min", "fgm", "fga", "pts", "plus_minus"]:
        assert types[column] == "BIGINT", column

    game_ids = [row[0] for row in db.execute(
        "select distinct game_id from player_box_scores where player_id = ? order by game_id", [JOKIC]
    ).fetchall()]
    assert game_ids == ["0022300006", "0022300024", "0022300034", "0042300151"]


def test_regular_season_and_playoffs_are_told_apart(db):
    rows = db.execute(
        """
        select season_type, games_played, pts from player_season_averages
        where player_id = ? order by season_type
        """,
        [JOKIC],
    ).fetchall()

    assert rows == [("Playoffs", 1, 32.0), ("Regular Season", 3, pytest.approx(91 / 3))]


def test_per_game_percentages_and_source_extras_are_not_stored(db):
    columns = {row[0] for row in db.execute("select column_name from (describe player_box_scores)").fetchall()}

    assert columns.isdisjoint(
        {"fg_pct", "fg3_pct", "ft_pct", "fantasy_pts", "video_available", "matchup", "season_id"}
    )


def test_player_game_stats_calculates_per_game_percentages(db):
    fg_pct, ft_pct = db.execute(
        "select fg_pct, ft_pct from player_game_stats where player_id = ? and game_id = '0022300024'",
        [JOKIC],
    ).fetchone()

    assert fg_pct == pytest.approx(8 / 23)
    assert ft_pct == 1.0


def test_player_teams_shows_a_mid_season_trade_as_one_row_per_team(db):
    # Siakam was traded from Toronto to Indiana in January 2024.
    rows = db.execute(
        """
        select team_id, team_abbreviation, games_played, first_game_date, last_game_date
        from player_teams
        where player_id = ? and season = '2023-24' and season_type = 'Regular Season'
        order by first_game_date
        """,
        [SIAKAM],
    ).fetchall()

    assert rows == [
        (RAPTORS, "TOR", 2, date(2024, 1, 12), date(2024, 1, 15)),
        (PACERS, "IND", 3, date(2024, 1, 19), date(2024, 1, 23)),
    ]


def test_team_rosters_lists_players_who_appeared_with_games_played(db):
    rows = db.execute(
        """
        select player_name, games_played from team_rosters
        where team_id = ? and season = '2023-24' and season_type = 'Regular Season'
        order by player_name
        """,
        [NUGGETS],
    ).fetchall()

    assert rows == [
        ("Aaron Gordon", 3),
        ("Christian Braun", 3),
        ("Jalen Pickett", 2),
        ("Jamal Murray", 1),
        ("Julian Strawther", 1),
        ("Justin Holiday", 1),
        ("Kentavious Caldwell-Pope", 3),
        ("Michael Porter Jr.", 3),
        ("Nikola Jokić", 3),
        ("Peyton Watson", 3),
        ("Reggie Jackson", 3),
        ("Zeke Nnaji", 3),
    ]


def test_published_file_holds_only_views_that_work_from_any_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ingest(ReplaySource(FIXTURES), Store("data"), seasons=["2023-24"])
    data_root = tmp_path / "data"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    with duckdb.connect(str(data_root / "hoopdata.duckdb"), read_only=True) as con:
        table_types = {row[0] for row in con.execute("select table_type from information_schema.tables").fetchall()}
        rows = con.execute("select count(*) from player_box_scores").fetchone()[0]

    assert table_types == {"VIEW"}
    assert rows == 64 + 19


def test_reingesting_a_season_replaces_it_rather_than_duplicating(tmp_path):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"])
    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"])

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        rows = con.execute("select count(*) from player_box_scores").fetchone()[0]

    assert rows == 64 + 19
    assert not list(tmp_path.rglob("*.tmp"))
