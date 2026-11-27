import io
from pathlib import Path

import pytest

from hoopdata.cli import main
from hoopdata.source import PLAYER, PLAYOFFS, ReplaySource

FIXTURES = Path(__file__).parent / "fixtures"
JOKIC = 203999


class FailingPlayoffsSource(ReplaySource):
    def game_log(self, season, season_type, kind):
        if (season_type, kind) == (PLAYOFFS, PLAYER):
            raise ConnectionError("stats.nba.com timed out")
        return super().game_log(season, season_type, kind)


def test_ingest_command_prints_each_item_and_exits_non_zero_when_one_failed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NBA_DATA_ROOT", str(tmp_path))

    exit_code = main(["ingest", "--season", "2023-24"], source=FailingPlayoffsSource(FIXTURES))

    out = capsys.readouterr().out
    assert exit_code == 1
    assert (tmp_path / "hoopdata.duckdb").exists()
    assert "player_box_scores 2023-24 Regular Season: 64 rows" in out
    assert "player_box_scores 2023-24 Playoffs: FAILED (ConnectionError: stats.nba.com timed out)" in out


class FailingJokicBioSource(ReplaySource):
    def player_info(self, player_id):
        if player_id == JOKIC:
            raise ConnectionError("stats.nba.com timed out")
        return super().player_info(player_id)


def test_ingest_command_reports_a_failed_bio_fetch(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NBA_DATA_ROOT", str(tmp_path))

    exit_code = main(["ingest", "--season", "2023-24"], source=FailingJokicBioSource(FIXTURES))

    out = capsys.readouterr().out
    assert exit_code == 1
    assert (tmp_path / "hoopdata.duckdb").exists()
    assert "players: FAILED (1 of 53 bios failed, first: ConnectionError: stats.nba.com timed out)" in out


def test_ingest_help_lists_the_full_backfill_cost_per_dataset(capsys):
    with pytest.raises(SystemExit):
        main(["ingest", "--help"])

    out = " ".join(capsys.readouterr().out.split())
    assert "core: about 2,800 requests, roughly 47 min" in out
    assert "advanced: about 135 requests, roughly 2 min" in out


def test_ingest_never_prompts(tmp_path, monkeypatch, capsys):
    def no_prompt(*args):
        raise AssertionError("ingest prompted")

    monkeypatch.setattr("builtins.input", no_prompt)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    exit_code = main(["ingest", "--season", "2023-24", "--data-root", str(tmp_path)], source=ReplaySource(FIXTURES))

    assert exit_code == 0
    assert "About 96 requests" in capsys.readouterr().out


def test_plain_ingest_on_an_empty_data_root_is_refused_and_fetches_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NBA_DATA_ROOT", str(tmp_path))
    source = FailingPlayoffsSource(FIXTURES)

    exit_code = main(["ingest"], source=source)

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "--season" in err and "--all-seasons" in err
    assert not (tmp_path / "manifest.json").exists()
    assert not (tmp_path / "hoopdata.duckdb").exists()
