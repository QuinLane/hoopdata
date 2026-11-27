import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest

from hoopdata import transform
from hoopdata.ingest import EmptySelectionError, ingest
from hoopdata.source import PLAY_IN, PLAYER, PLAYOFFS, REGULAR_SEASON, ReplaySource
from hoopdata.store import ALL_SEASONS, Store

FIXTURES = Path(__file__).parent / "fixtures"
JOKIC = 203999
PELICANS = 1610612740
MAVERICKS = 1610612742
DENVER = 1610612743
CLIPPERS = 1610612746
LAKERS = 1610612747
SIAKAM = 1627783
RAPTORS = 1610612761
PACERS = 1610612754
AUSTIN_REAVES = 1630559  # undrafted
NUGGETS = 1610612743
CELTICS = 1610612738
SUNS = 1610612756
BLAZERS = 1610612757
JAZZ = 1610612762
HEAT = 1610612748
WIZARDS = 1610612764


@pytest.fixture
def db(tmp_path):
    """Ingest 2023-24 from the replay source and open the published file read-only."""
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"])
    con = duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True)
    yield con
    con.close()


class CountingSource(ReplaySource):
    """Replay source that counts player-info requests and can leave players out of the box scores."""

    def __init__(self, fixtures_dir, hidden_player_ids=()):
        super().__init__(fixtures_dir)
        self.hidden_player_ids = set(hidden_player_ids)
        self.player_info_requests = []

    def game_log(self, season, season_type, kind):
        raw = super().game_log(season, season_type, kind)
        result = raw["resultSets"][0]
        if kind == PLAYER:
            player_id = result["headers"].index("PLAYER_ID")
            result["rowSet"] = [row for row in result["rowSet"] if row[player_id] not in self.hidden_player_ids]
        return raw

    def player_info(self, player_id):
        self.player_info_requests.append(player_id)
        return super().player_info(player_id)


class FailingSource(ReplaySource):
    """Replay source that fails the given (season_type, kind) game logs and records every game-log request."""

    def __init__(self, fixtures_dir, failing=()):
        super().__init__(fixtures_dir)
        self.failing = set(failing)
        self.game_log_requests = []

    def game_log(self, season, season_type, kind):
        self.game_log_requests.append((season, season_type, kind))
        if (season_type, kind) in self.failing:
            raise ConnectionError("stats.nba.com timed out")
        return super().game_log(season, season_type, kind)


def manifest_items(data_root):
    manifest = json.loads((Path(data_root) / "manifest.json").read_text(encoding="utf-8"))
    return {(i["table"], i["season"], i["season_type"]): i for i in manifest["items"]}


def test_a_failed_item_is_recorded_and_the_other_items_complete(tmp_path):
    report = ingest(FailingSource(FIXTURES, failing=[(PLAYOFFS, PLAYER)]), Store(tmp_path), seasons=["2023-24"])

    failed = manifest_items(tmp_path)[("player_box_scores", "2023-24", "Playoffs")]
    assert failed["status"] == "failed"
    assert failed["error"] == "ConnectionError: stats.nba.com timed out"
    assert failed["rows"] is None
    assert [(i.table, i.season_type, i.status) for i in report.items if i.status != "succeeded"] == [
        ("player_box_scores", "Playoffs", "failed")
    ]
    assert len(report.items) == 10
    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        player_rows = con.execute("select count(*) from player_box_scores").fetchone()[0]
        games = con.execute("select count(*) from games").fetchone()[0]
    assert player_rows == 64 + 4
    assert games == 10


def test_a_second_run_retries_only_the_failed_item(tmp_path):
    store = Store(tmp_path)
    ingest(FailingSource(FIXTURES, failing=[(PLAYOFFS, PLAYER)]), store, seasons=["2023-24"])

    retry = FailingSource(FIXTURES)
    report = ingest(retry, store, seasons=["2023-24"])

    assert retry.game_log_requests == [("2023-24", "Playoffs", "player")]
    assert [(i.table, i.season_type, i.status) for i in report.items] == [
        ("player_box_scores", "Playoffs", "succeeded"),
        ("players", None, "succeeded"),
    ]
    assert {i["status"] for i in manifest_items(tmp_path).values()} == {"succeeded"}
    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        player_rows = con.execute("select count(*) from player_box_scores").fetchone()[0]
    assert player_rows == 64 + 4 + 19


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows refuses to replace a file that is open")
def test_a_parquet_file_held_open_by_a_consumer_fails_its_item_and_leaves_no_partial_file(tmp_path):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"], today=date(2024, 7, 1))
    ingest(FailingSource(FIXTURES, failing=[(PLAYOFFS, PLAYER)]), store, today=date(2024, 7, 1))

    held = tmp_path / "player_box_scores" / "season=2023-24" / "playoffs.parquet"
    with open(held, "rb"):
        report = ingest(ReplaySource(FIXTURES), store, today=date(2024, 7, 1))

    assert [(i.table, i.season_type, i.status) for i in report.items] == [
        ("player_box_scores", "Playoffs", "failed")
    ]
    assert manifest_items(tmp_path)[("player_box_scores", "2023-24", "Playoffs")]["error"].startswith(
        "PermissionError"
    )
    assert not list(tmp_path.rglob("*.tmp"))
    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        player_rows = con.execute("select count(*) from player_box_scores").fetchone()[0]
    assert player_rows == 64 + 4 + 19


def test_each_run_writes_its_own_log_file(tmp_path):
    store = Store(tmp_path)
    first = ingest(FailingSource(FIXTURES, failing=[(PLAYOFFS, PLAYER)]), store, seasons=["2023-24"])
    second = ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"])

    assert first.log_path != second.log_path
    first_log = first.log_path.read_text(encoding="utf-8")
    assert "player_box_scores 2023-24 Playoffs failed" in first_log
    assert "ConnectionError: stats.nba.com timed out" in first_log
    assert "player_box_scores 2023-24 Playoffs succeeded: 19 rows" in second.log_path.read_text(encoding="utf-8")


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
    assert rows == 64 + 4 + 19


def test_reingesting_a_season_replaces_it_rather_than_duplicating(tmp_path):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"], today=date(2024, 7, 1))
    ingest(ReplaySource(FIXTURES), store, today=date(2024, 7, 2))

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        rows = con.execute("select count(*) from player_box_scores").fetchone()[0]

    assert rows == 64 + 4 + 19
    assert not list(tmp_path.rglob("*.tmp"))


def test_players_hold_bios_with_height_in_inches(db):
    row = db.execute(
        """
        select first_name, last_name, display_name, birthdate, height_in, weight_lb, position,
               country, school, draft_year, draft_round, draft_number, from_year, to_year
        from players where player_id = ?
        """,
        [JOKIC],
    ).fetchone()

    assert row == (
        "Nikola", "Jokić", "Nikola Jokić", date(1995, 2, 19), 6 * 12 + 11, 284, "Center",
        "Serbia", "Mega Basket", 2014, 2, 41, 2015, 2026,
    )


def test_undrafted_players_have_empty_draft_fields_and_drafted_ones_keep_integers(db):
    undrafted = db.execute(
        "select draft_year, draft_round, draft_number from players where player_id = ?", [AUSTIN_REAVES]
    ).fetchone()
    draft_number_type = db.execute(
        "select column_type from (describe players) where column_name = 'draft_number'"
    ).fetchone()[0]

    assert undrafted == (None, None, None)
    assert draft_number_type == "BIGINT"


class BlankSizeSource(ReplaySource):
    """Replay source whose player infos have no height and a weight of one space, as some old players' do."""

    def player_info(self, player_id):
        raw = super().player_info(player_id)
        result = raw["resultSets"][0]
        row = result["rowSet"][0]
        row[result["headers"].index("HEIGHT")] = ""
        row[result["headers"].index("WEIGHT")] = " "
        return raw


def test_blank_heights_and_weights_are_stored_as_empty(tmp_path):
    # Luc Longley's recorded bio has HEIGHT "" and WEIGHT " ".
    ingest(BlankSizeSource(FIXTURES), Store(tmp_path), seasons=["2023-24"])

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        row = con.execute("select height_in, weight_lb from players where player_id = ?", [JOKIC]).fetchone()

    assert row == (None, None)


def test_player_bios_are_fetched_only_for_players_not_yet_stored(tmp_path):
    store = Store(tmp_path)
    ingest(CountingSource(FIXTURES, hidden_player_ids=[JOKIC]), store, seasons=["2023-24"], today=date(2024, 7, 1))

    unchanged = CountingSource(FIXTURES, hidden_player_ids=[JOKIC])
    ingest(unchanged, store, today=date(2024, 7, 1))
    with_jokic = CountingSource(FIXTURES)
    ingest(with_jokic, store, today=date(2024, 7, 1))

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        players = con.execute("select count(*), count(distinct player_id) from players").fetchone()

    assert unchanged.player_info_requests == []
    assert with_jokic.player_info_requests == [JOKIC]
    assert players == (53, 53)


class FailingBioSource(ReplaySource):
    """Replay source that fails the player info of the given players."""

    def __init__(self, fixtures_dir, failing_player_ids=()):
        super().__init__(fixtures_dir)
        self.failing_player_ids = set(failing_player_ids)

    def player_info(self, player_id):
        if player_id in self.failing_player_ids:
            raise ConnectionError("stats.nba.com timed out")
        return super().player_info(player_id)


def test_a_failed_bio_is_recorded_and_the_run_still_publishes(tmp_path):
    report = ingest(FailingBioSource(FIXTURES, failing_player_ids=[JOKIC]), Store(tmp_path), seasons=["2023-24"])

    assert [(i.table, i.status, i.rows, i.error) for i in report.failed] == [
        ("players", "failed", 52, "1 of 53 bios failed, first: ConnectionError: stats.nba.com timed out")
    ]
    assert manifest_items(tmp_path)[("players", None, None)]["status"] == "failed"
    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        players = con.execute("select count(*) from players").fetchone()[0]
        teams = con.execute("select count(*) from teams").fetchone()[0]
    assert players == 52
    assert teams == 30


def test_a_failed_bio_is_fetched_on_the_next_run(tmp_path):
    store = Store(tmp_path)
    ingest(FailingBioSource(FIXTURES, failing_player_ids=[JOKIC]), store, seasons=["2023-24"])

    retry = CountingSource(FIXTURES)
    report = ingest(retry, store, seasons=["2023-24"])

    assert retry.player_info_requests == [JOKIC]
    assert report.failed == []
    assert manifest_items(tmp_path)[("players", None, None)]["rows"] == 1


class Crash(BaseException):
    """Stands in for the process dying: not an ``Exception``, so ingest doesn't record and skip it."""


class CrashingBioSource(CountingSource):
    """Replay source that crashes on the player-info request after ``crash_after`` succeeded."""

    def __init__(self, fixtures_dir, crash_after):
        super().__init__(fixtures_dir)
        self.crash_after = crash_after

    def player_info(self, player_id):
        if len(self.player_info_requests) == self.crash_after:
            raise Crash()
        return super().player_info(player_id)


def test_a_crash_while_fetching_bios_keeps_most_of_the_bios_fetched_so_far(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(Crash):
        ingest(CrashingBioSource(FIXTURES, crash_after=50), store, seasons=["2023-24"])

    resumed = CountingSource(FIXTURES)
    ingest(resumed, store, seasons=["2023-24"])

    assert len(resumed.player_info_requests) <= 53 - 40


def test_players_left_without_bios_by_a_crash_get_them_on_a_later_run(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(Crash):
        ingest(CrashingBioSource(FIXTURES, crash_after=0), store, seasons=["2022-23"])

    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"])

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        without_bios = con.execute(
            "select count(distinct player_id) from player_box_scores anti join players using (player_id)"
        ).fetchone()[0]
        seasons = con.execute("select count(distinct season) from player_box_scores").fetchone()[0]
    assert seasons == 2
    assert without_bios == 0


def test_teams_hold_current_identities(db):
    row = db.execute(
        "select abbreviation, city, nickname, full_name, year_founded from teams where team_id = ?",
        [NUGGETS],
    ).fetchone()
    teams = db.execute("select count(*) from teams").fetchone()[0]

    assert row == ("DEN", "Denver", "Nuggets", "Denver Nuggets", 1976)
    assert teams == 30


def test_manifest_records_each_item_and_the_schema_version(tmp_path):
    before = datetime.now(timezone.utc)
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"])
    after = datetime.now(timezone.utc)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 1
    assert before <= datetime.fromisoformat(manifest["last_updated"]) <= after
    items = {(i["table"], i["season"], i["season_type"]): i for i in manifest["items"]}
    assert set(items) == {
        ("player_box_scores", "2023-24", "Regular Season"),
        ("player_box_scores", "2023-24", "Playoffs"),
        ("player_box_scores", "2023-24", "PlayIn"),
        ("team_box_scores", "2023-24", "Regular Season"),
        ("team_box_scores", "2023-24", "PlayIn"),
        ("team_box_scores", "2023-24", "Playoffs"),
        ("games", "2023-24", "Regular Season"),
        ("games", "2023-24", "PlayIn"),
        ("games", "2023-24", "Playoffs"),
        ("players", None, None),
    }
    regular = items[("player_box_scores", "2023-24", "Regular Season")]
    assert regular["status"] == "succeeded"
    assert regular["rows"] == 64
    assert regular["error"] is None
    assert before <= datetime.fromisoformat(regular["fetched_at"]) <= after
    assert items[("player_box_scores", "2023-24", "Playoffs")]["rows"] == 19


def test_hoopdata_info_reports_the_manifest_schema_version_and_last_updated(db, tmp_path):
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    schema_version, last_updated = db.execute(
        "select schema_version, last_updated from hoopdata_info"
    ).fetchone()

    assert schema_version == 1
    assert last_updated == datetime.fromisoformat(manifest["last_updated"])


def test_later_ingest_updates_hoopdata_info_without_rebuilding_the_file(tmp_path):
    store = Store(tmp_path)
    database = tmp_path / "hoopdata.duckdb"
    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"])
    with duckdb.connect(str(database), read_only=True) as con:
        first = con.execute("select last_updated from hoopdata_info").fetchone()[0]
    built = database.stat().st_mtime_ns

    ingest(ReplaySource(FIXTURES), store, today=date(2024, 7, 1))
    with duckdb.connect(str(database), read_only=True) as con:
        second = con.execute("select last_updated from hoopdata_info").fetchone()[0]

    assert second > first
    assert database.stat().st_mtime_ns == built


def test_ingest_after_the_data_root_moves_rebuilds_the_file(tmp_path):
    ingest(ReplaySource(FIXTURES), Store(tmp_path / "old"), seasons=["2023-24"])
    (tmp_path / "old").rename(tmp_path / "new")

    ingest(ReplaySource(FIXTURES), Store(tmp_path / "new"), seasons=["2023-24"])

    with duckdb.connect(str(tmp_path / "new" / "hoopdata.duckdb"), read_only=True) as con:
        rows = con.execute("select count(*) from player_box_scores").fetchone()[0]
        schema_version = con.execute("select schema_version from hoopdata_info").fetchone()[0]

    assert rows == 64 + 4 + 19
    assert schema_version == 1


def test_standings_count_wins_and_losses_per_season_type(db):
    # Fixture games: DEN beat DAL and LAC at home, lost at NOP, won at IND, then beat LAL in the playoffs.
    # Siakam's games: TOR lost at UTA and to BOS at home, then IND lost at POR, at PHX and to DEN at home.
    # LAL's Play-In win at NOP is left out, as in NBA's standings.
    rows = db.execute(
        """
        select season_type, team_id, wins, losses from standings
        where season = '2023-24' order by season_type, team_id
        """
    ).fetchall()

    assert rows == [
        ("Playoffs", DENVER, 1, 0),
        ("Playoffs", LAKERS, 0, 1),
        ("Regular Season", CELTICS, 1, 0),
        ("Regular Season", PELICANS, 1, 0),
        ("Regular Season", MAVERICKS, 0, 1),
        ("Regular Season", DENVER, 3, 1),
        ("Regular Season", CLIPPERS, 0, 1),
        ("Regular Season", PACERS, 0, 3),
        ("Regular Season", SUNS, 1, 0),
        ("Regular Season", BLAZERS, 1, 0),
        ("Regular Season", RAPTORS, 0, 2),
        ("Regular Season", JAZZ, 1, 0),
    ]


def test_games_have_one_row_each_with_home_and_away_from_the_matchup(db):
    rows = db.execute(
        """
        select game_id, season, season_type, game_date, home_team_id, away_team_id, home_pts, away_pts
        from games order by game_id
        """
    ).fetchall()

    assert rows == [
        ("0022300006", "2023-24", "Regular Season", date(2023, 11, 3), DENVER, MAVERICKS, 125, 114),
        ("0022300024", "2023-24", "Regular Season", date(2023, 11, 14), DENVER, CLIPPERS, 111, 108),
        ("0022300034", "2023-24", "Regular Season", date(2023, 11, 17), PELICANS, DENVER, 115, 110),
        ("0022300540", "2023-24", "Regular Season", date(2024, 1, 12), JAZZ, RAPTORS, 145, 113),
        ("0022300563", "2023-24", "Regular Season", date(2024, 1, 15), RAPTORS, CELTICS, 96, 105),
        ("0022300590", "2023-24", "Regular Season", date(2024, 1, 19), BLAZERS, PACERS, 118, 115),
        ("0022300604", "2023-24", "Regular Season", date(2024, 1, 21), SUNS, PACERS, 117, 110),
        ("0022300614", "2023-24", "Regular Season", date(2024, 1, 23), PACERS, DENVER, 109, 114),
        ("0042300151", "2023-24", "Playoffs", date(2024, 4, 20), DENVER, LAKERS, 114, 103),
        ("0052300111", "2023-24", "PlayIn", date(2024, 4, 16), PELICANS, LAKERS, 106, 110),
    ]
    assert db.execute("select distinct neutral_site from games").fetchall() == [(False,)]


def test_a_neutral_site_game_is_kept_and_flagged_with_the_lower_team_id_as_home():
    # Recorded rows: Heat vs Wizards in Mexico City, where both matchups read "@", and a normal game.
    raw = {"resultSets": [{
        "name": "LeagueGameLog",
        "headers": ["GAME_ID", "GAME_DATE", "TEAM_ID", "MATCHUP", "PTS"],
        "rowSet": [
            ["0022400148", "2024-11-02", DENVER, "DEN vs. UTA", 129],
            ["0022400147", "2024-11-02", HEAT, "MIA @ WAS", 118],
            ["0022400148", "2024-11-02", JAZZ, "UTA @ DEN", 103],
            ["0022400147", "2024-11-02", WIZARDS, "WAS @ MIA", 98],
        ],
    }]}

    df = transform.games(raw, "2024-25", REGULAR_SEASON).sort_values("game_id")

    rows = df[["game_id", "neutral_site", "home_team_id", "away_team_id", "home_pts", "away_pts"]]
    assert [tuple(row) for row in rows.itertuples(index=False)] == [
        ("0022400147", True, HEAT, WIZARDS, 118, 98),
        ("0022400148", False, DENVER, JAZZ, 129, 103),
    ]


def test_every_game_in_the_player_box_scores_has_exactly_one_games_row(tmp_path):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2022-23", "2023-24"])

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        rows_per_game = con.execute(
            """
            select p.game_id, count(g.game_id)
            from (select distinct game_id from player_box_scores) p
            left join games g using (game_id)
            group by p.game_id order by p.game_id
            """
        ).fetchall()

    assert len(rows_per_game) == 13
    assert {count for _, count in rows_per_game} == {1}


def test_team_box_scores_are_player_box_scores_without_the_player_fields(db):
    player_columns = [row[0] for row in db.execute("select column_name from (describe player_box_scores)").fetchall()]
    team_columns = [row[0] for row in db.execute("select column_name from (describe team_box_scores)").fetchall()]

    assert team_columns == [c for c in player_columns if c not in ("player_id", "player_name")]
    assert db.execute(
        "select team_abbreviation, team_name from team_box_scores where team_id = ? and game_id = '0022300006'",
        [MAVERICKS],
    ).fetchone() == ("DAL", "Dallas Mavericks")


def test_team_season_percentages_come_from_summed_makes_and_attempts(db):
    # Denver, 4 regular season games: 49/93, 39/73, 47/96, 44/88. Summed: 179/350.
    games, pts, fg_pct = db.execute(
        """
        select games_played, pts, fg_pct from team_season_averages
        where team_id = ? and season = '2023-24' and season_type = 'Regular Season'
        """,
        [DENVER],
    ).fetchone()

    assert games == 4
    assert pts == pytest.approx((125 + 111 + 110 + 114) / 4)
    assert fg_pct == pytest.approx(179 / 350)


def test_team_game_stats_calculates_per_game_percentages(db):
    fg_pct, ft_pct = db.execute(
        "select fg_pct, ft_pct from team_game_stats where team_id = ? and game_id = '0022300024'",
        [DENVER],
    ).fetchone()

    assert fg_pct == pytest.approx(39 / 73)
    assert ft_pct == pytest.approx(25 / 32)


class BackfillSource(ReplaySource):
    """Replay source that logs which seasons it was asked for and stands in 2022-23 for seasons without fixtures."""

    def __init__(self, fixtures_dir):
        super().__init__(fixtures_dir)
        self.seasons_requested = []
        self.play_in_seasons_requested = []

    def game_log(self, season, season_type, kind):
        if season_type == REGULAR_SEASON and kind == PLAYER:
            self.seasons_requested.append(season)
        if season_type == PLAY_IN and kind == PLAYER:
            self.play_in_seasons_requested.append(season)
        if season not in ("2022-23", "2023-24"):
            season = "2022-23"
        return super().game_log(season, season_type, kind)


ALL_SEASONS_TO_2023_24 = [
    "1996-97", "1997-98", "1998-99", "1999-00", "2000-01", "2001-02", "2002-03",
    "2003-04", "2004-05", "2005-06", "2006-07", "2007-08", "2008-09", "2009-10",
    "2010-11", "2011-12", "2012-13", "2013-14", "2014-15", "2015-16", "2016-17",
    "2017-18", "2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24",
]


def test_all_seasons_run_covers_1996_97_through_the_latest_season(tmp_path):
    source = BackfillSource(FIXTURES)

    ingest(source, Store(tmp_path), seasons=ALL_SEASONS, today=date(2024, 11, 26))

    assert source.seasons_requested == ALL_SEASONS_TO_2023_24 + ["2024-25"]


def test_in_summer_only_the_season_that_just_ended_is_refetched(tmp_path):
    store = Store(tmp_path)
    backfill = BackfillSource(FIXTURES)
    ingest(backfill, store, seasons=ALL_SEASONS, today=date(2024, 7, 1))

    nightly = BackfillSource(FIXTURES)
    ingest(nightly, store, today=date(2024, 7, 2))

    assert backfill.seasons_requested == ALL_SEASONS_TO_2023_24
    assert nightly.seasons_requested == ["2023-24"]


def test_all_seasons_run_fetches_older_seasons_that_are_missing(tmp_path):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"])

    source = BackfillSource(FIXTURES)
    ingest(source, store, seasons=ALL_SEASONS, today=date(2024, 7, 1))

    assert source.seasons_requested == ALL_SEASONS_TO_2023_24[:-2] + ["2023-24"]
    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        seasons = con.execute("select count(distinct season) from player_box_scores").fetchone()[0]
    assert seasons == len(ALL_SEASONS_TO_2023_24)


def selection(data_root):
    return json.loads((Path(data_root) / "manifest.json").read_text(encoding="utf-8"))["selection"]


def test_plain_ingest_on_an_empty_data_root_is_refused_and_fetches_nothing(tmp_path):
    source = BackfillSource(FIXTURES)

    with pytest.raises(EmptySelectionError, match="--season or --all-seasons"):
        ingest(source, Store(tmp_path))

    assert source.seasons_requested == []
    assert not (tmp_path / "manifest.json").exists()


def test_a_season_on_an_empty_data_root_is_saved_as_a_fixed_list_and_fetched(tmp_path):
    source = BackfillSource(FIXTURES)

    ingest(source, Store(tmp_path), seasons=["2023-24"], today=date(2024, 11, 26))

    assert selection(tmp_path) == {"datasets": ["core"], "seasons": ["2023-24"]}
    assert source.seasons_requested == ["2023-24"]


def test_passing_a_completed_season_fetches_nothing_already_succeeded(tmp_path):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23"], today=date(2024, 7, 1))

    source = FailingSource(FIXTURES)
    ingest(source, store, seasons=["2022-23"], today=date(2024, 7, 1))

    assert source.game_log_requests == []
    assert selection(tmp_path)["seasons"] == ["2022-23"]


def test_passing_a_season_fetches_only_its_failed_items(tmp_path):
    store = Store(tmp_path)
    ingest(FailingSource(FIXTURES, failing=[(PLAYOFFS, PLAYER)]), store, seasons=["2022-23"], today=date(2024, 7, 1))

    source = FailingSource(FIXTURES)
    ingest(source, store, seasons=["2022-23"], today=date(2024, 7, 1))

    assert source.game_log_requests == [("2022-23", "Playoffs", "player")]


def test_passing_a_season_with_all_seasons_selected_keeps_all_and_fetches_nothing_already_succeeded(tmp_path):
    store = Store(tmp_path)
    ingest(BackfillSource(FIXTURES), store, seasons=ALL_SEASONS, today=date(2024, 11, 26))

    source = BackfillSource(FIXTURES)
    ingest(source, store, seasons=["2022-23"], today=date(2024, 11, 26))

    assert source.seasons_requested == ["2024-25"]
    assert selection(tmp_path)["seasons"] == "all"


def test_adding_a_season_to_a_fixed_list_fetches_only_the_new_season(tmp_path):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23"], today=date(2024, 11, 26))

    source = BackfillSource(FIXTURES)
    ingest(source, store, seasons=["2023-24"], today=date(2024, 11, 26))

    assert source.seasons_requested == ["2023-24"]
    assert selection(tmp_path)["seasons"] == ["2022-23", "2023-24"]


def test_all_seasons_widens_a_fixed_list_to_all(tmp_path):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"], today=date(2024, 7, 1))

    source = BackfillSource(FIXTURES)
    ingest(source, store, seasons=ALL_SEASONS, today=date(2024, 7, 1))

    assert selection(tmp_path)["seasons"] == "all"
    assert source.seasons_requested == ALL_SEASONS_TO_2023_24[:-2] + ["2023-24"]


def test_a_fixed_list_does_not_gain_a_new_season(tmp_path):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"], today=date(2024, 7, 1))

    source = BackfillSource(FIXTURES)
    ingest(source, store, today=date(2024, 11, 26))

    assert source.seasons_requested == []
    assert selection(tmp_path)["seasons"] == ["2023-24"]


def test_all_seasons_gains_a_new_season(tmp_path):
    store = Store(tmp_path)
    ingest(BackfillSource(FIXTURES), store, seasons=ALL_SEASONS, today=date(2024, 7, 1))

    source = BackfillSource(FIXTURES)
    ingest(source, store, today=date(2024, 11, 26))

    assert source.seasons_requested == ["2024-25"]


def test_plain_ingest_refetches_the_latest_season_when_the_selection_includes_it(tmp_path):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"], today=date(2024, 7, 1))

    source = BackfillSource(FIXTURES)
    ingest(source, store, today=date(2024, 7, 2))

    assert source.seasons_requested == ["2023-24"]


def test_plain_ingest_leaves_a_completed_older_season_alone(tmp_path):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23"], today=date(2024, 7, 1))

    source = BackfillSource(FIXTURES)
    ingest(source, store, today=date(2024, 7, 2))

    assert source.seasons_requested == []


def test_a_v1_manifest_without_a_selection_is_saved_as_core_with_all_seasons(tmp_path):
    store = Store(tmp_path)
    ingest(BackfillSource(FIXTURES), store, seasons=ALL_SEASONS, today=date(2024, 7, 1))
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    del manifest["selection"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    source = BackfillSource(FIXTURES)
    ingest(source, store, today=date(2024, 11, 26))

    assert selection(tmp_path) == {"datasets": ["core"], "seasons": "all"}
    assert source.seasons_requested == ["2024-25"]


class FailingPlayoffsAndJokicSource(FailingSource):
    """Replay source that fails the player playoffs game log and Jokic's bio."""

    def __init__(self, fixtures_dir):
        super().__init__(fixtures_dir, failing=[(PLAYOFFS, PLAYER)])

    def player_info(self, player_id):
        if player_id == JOKIC:
            raise ConnectionError("stats.nba.com timed out")
        return super().player_info(player_id)


def test_the_estimate_counts_one_request_per_failed_game_log_and_missing_bio(tmp_path, capsys):
    store = Store(tmp_path)
    ingest(FailingPlayoffsAndJokicSource(FIXTURES), store, seasons=["2023-24"], today=date(2024, 11, 26))
    capsys.readouterr()

    ingest(ReplaySource(FIXTURES), store, today=date(2024, 11, 26))

    assert "About 2 requests, roughly 2 s (core: 2)" in capsys.readouterr().out


class PrintedBeforeRequestSource(ReplaySource):
    """Replay source that captures what has been printed when the first request is made."""

    def __init__(self, fixtures_dir, capsys):
        super().__init__(fixtures_dir)
        self.capsys = capsys
        self.printed_before_first_request = None

    def game_log(self, season, season_type, kind):
        if self.printed_before_first_request is None:
            self.printed_before_first_request = self.capsys.readouterr().out
        return super().game_log(season, season_type, kind)


def test_refetching_only_the_latest_season_prints_its_small_estimate_before_any_request(tmp_path, capsys):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"], today=date(2024, 7, 1))
    capsys.readouterr()

    source = PrintedBeforeRequestSource(FIXTURES, capsys)
    ingest(source, store, today=date(2024, 7, 2))

    assert "About 6 requests, roughly 6 s (core: 6)" in source.printed_before_first_request


def test_a_first_all_seasons_run_estimates_one_request_per_game_log_in_minutes(tmp_path, capsys):
    ingest(BackfillSource(FIXTURES), Store(tmp_path), seasons=ALL_SEASONS, today=date(2024, 11, 26))

    assert "About 128 requests, roughly 2 min (core: 128)" in capsys.readouterr().out


def test_play_in_games_are_stored_as_their_own_season_type(db):
    # Fixture Play-In game: the Lakers won at New Orleans, 110-106.
    game = db.execute(
        "select game_id, season_type, home_team_id, away_team_id, home_pts, away_pts from games where game_id = '0052300111'"
    ).fetchone()
    team_rows = db.execute(
        "select season_type, team_id, pts from team_box_scores where game_id = '0052300111' order by team_id"
    ).fetchall()
    player_rows = db.execute(
        "select distinct season_type from player_box_scores where game_id = '0052300111'"
    ).fetchall()

    assert game == ("0052300111", "PlayIn", PELICANS, LAKERS, 106, 110)
    assert team_rows == [("PlayIn", PELICANS, 106), ("PlayIn", LAKERS, 110)]
    assert player_rows == [("PlayIn",)]


def test_play_in_is_fetched_only_from_2019_20_and_earlier_seasons_are_complete_without_it(tmp_path):
    store = Store(tmp_path)
    backfill = BackfillSource(FIXTURES)
    ingest(backfill, store, seasons=ALL_SEASONS, today=date(2024, 7, 1))

    nightly = BackfillSource(FIXTURES)
    ingest(nightly, store, today=date(2024, 7, 2))

    assert backfill.play_in_seasons_requested == ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24"]
    assert nightly.seasons_requested == ["2023-24"]
    assert ("player_box_scores", "2018-19", "PlayIn") not in manifest_items(tmp_path)


class NoPlayInYetSource(ReplaySource):
    """Replay source whose Play-In game logs have no rows yet, as the current season's do until April."""

    def game_log(self, season, season_type, kind):
        raw = super().game_log(season, season_type, kind)
        if season_type == PLAY_IN:
            raw["resultSets"][0]["rowSet"] = []
        return raw


def test_a_play_in_with_no_games_yet_is_recorded_as_succeeded(tmp_path):
    report = ingest(NoPlayInYetSource(FIXTURES), Store(tmp_path), seasons=["2023-24"])

    items = manifest_items(tmp_path)
    assert report.failed == []
    for table in ["player_box_scores", "team_box_scores", "games"]:
        assert (items[(table, "2023-24", "PlayIn")]["status"], items[(table, "2023-24", "PlayIn")]["rows"]) == (
            "succeeded", 0
        ), table


ZION = 1629627


def test_season_averages_keep_play_in_as_its_own_rows(db):
    # Zion scored 26 against Denver in the regular season and 40 in the Play-In.
    player_rows = db.execute(
        "select season_type, games_played, pts from player_season_averages where player_id = ? order by season_type",
        [ZION],
    ).fetchall()
    # The Pelicans scored 115 against Denver in the regular season and 106 in the Play-In.
    team_rows = db.execute(
        "select season_type, games_played, pts from team_season_averages where team_id = ? order by season_type",
        [PELICANS],
    ).fetchall()

    assert player_rows == [("PlayIn", 1, 40.0), ("Regular Season", 1, 26.0)]
    assert team_rows == [("PlayIn", 1, 106.0), ("Regular Season", 1, 115.0)]
