from datetime import date
from pathlib import Path

import duckdb
import pytest

from hoopdata.ingest import ingest
from hoopdata.source import ReplaySource
from hoopdata.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
SUMMER = date(2024, 7, 1)
NUGGETS = 1610612743
MAVERICKS = 1610612742
MURRAY = 1627750
PORTER = 1629008
DONCIC = 1629029
LIVELY = 1641726
# Denver's 2023-24 opener at home to Dallas.
OPENER = "0022300006"


@pytest.fixture
def db(tmp_path):
    """Ingest 2023-24 with pbp from the replay source and open the published file read-only."""
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], datasets=["pbp"], today=SUMMER)
    con = duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True)
    yield con
    con.close()


def test_each_assisted_made_shot_names_its_assister_matched_to_a_teammate(db):
    rows = db.execute(
        "select * from assists where game_id = ? and action_id in (8, 25) order by action_id", [OPENER]
    ).fetchall()

    # "(Doncic 1 AST)" matches Luka Dončić, whose box score name has the accent the description leaves out.
    assert rows == [
        ("2023-24", "Regular Season", OPENER, 8, 1, "PT11M06.00S", MAVERICKS, LIVELY, DONCIC, "Doncic", 2),
        ("2023-24", "Regular Season", OPENER, 25, 1, "PT08M44.00S", NUGGETS, PORTER, MURRAY, "Murray", 2),
    ]


def test_every_assisted_made_shot_is_in_assists_and_resolved_where_the_box_score_holds_the_team(tmp_path):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2022-23", "2023-24"], datasets=["pbp"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        total = con.execute("select count(*) from assists").fetchone()[0]
        # The four Denver regular season games and the two playoff games have both teams' full box scores. The other
        # regular season games hold one player, so their assisters have no teammate to match.
        resolved = con.execute(
            """
            select game_id, count(*), count(assist_player_id) from assists
            where game_id in ('0022200064', '0022300006', '0022300024', '0022300034', '0042200311', '0042300151')
            group by game_id order by game_id
            """
        ).fetchall()

    # The fixtures' play-by-play has 710 descriptions ending "AST)", all on made shots.
    assert total == 710
    assert resolved == [
        ("0022200064", 59, 59), ("0022300006", 60, 60), ("0022300024", 47, 47), ("0022300034", 70, 70),
        ("0042200311", 59, 59), ("0042300151", 49, 49),
    ]


class SharedSurnameSource(ReplaySource):
    """Replay source whose opener box score gives Reggie Jackson Jamal Murray's surname."""

    def game_log(self, season, season_type, kind):
        response = super().game_log(season, season_type, kind)
        for row in response["resultSets"][0]["rowSet"]:
            if row[2] == "Reggie Jackson" and row[6] == OPENER:
                row[2] = "Reggie Murray"
        return response


def test_an_assister_whose_surname_two_teammates_share_is_left_unresolved_with_the_parsed_name(tmp_path):
    ingest(SharedSurnameSource(FIXTURES), Store(tmp_path), seasons=["2023-24"], datasets=["pbp"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        row = con.execute(
            "select player_id, assist_player_id, assist_player_name from assists where game_id = ? and action_id = 25",
            [OPENER],
        ).fetchone()

    assert row == (PORTER, None, "Murray")


def test_assist_pairs_total_the_resolved_assists_per_assister_and_scorer(db):
    pair = db.execute(
        """
        select * from assist_pairs
        where season = '2023-24' and team_id = ? and assist_player_id = ? and player_id = ?
        order by season_type
        """,
        [NUGGETS, MURRAY, PORTER],
    ).fetchall()
    pair_totals = db.execute("select sum(assists), sum(points) from assist_pairs").fetchone()
    resolved_totals = db.execute(
        "select count(*), sum(shot_value) from assists where assist_player_id is not null"
    ).fetchone()
    unresolved_in_pairs = db.execute("select count(*) from assist_pairs where assist_player_id is null").fetchone()[0]

    # Murray set up Porter Jr. for a dunk and three 3s in the opener, the only regular season game of theirs the
    # fixtures hold, and twice more in the playoff game.
    assert pair == [
        ("2023-24", "Playoffs", NUGGETS, MURRAY, PORTER, 2, 5),
        ("2023-24", "Regular Season", NUGGETS, MURRAY, PORTER, 4, 11),
    ]
    assert pair_totals == resolved_totals
    assert unresolved_in_pairs == 0


def test_without_pbp_selected_neither_assist_view_exists(tmp_path):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], today=SUMMER)

    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        views = {row[0] for row in con.execute("select view_name from duckdb_views() where not internal").fetchall()}
    assert "player_box_scores" in views
    assert not {"assists", "assist_pairs"} & views
