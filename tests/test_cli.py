from pathlib import Path

from hoopdata.cli import main
from hoopdata.source import PLAYER, PLAYOFFS, ReplaySource

FIXTURES = Path(__file__).parent / "fixtures"


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
