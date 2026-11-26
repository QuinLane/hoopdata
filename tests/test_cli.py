from pathlib import Path

from hoopdata.cli import main
from hoopdata.source import ReplaySource

FIXTURES = Path(__file__).parent / "fixtures"


def test_ingest_command_falls_back_to_nba_data_root(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NBA_DATA_ROOT", str(tmp_path))

    exit_code = main(["ingest", "--season", "2023-24"], source=ReplaySource(FIXTURES))

    assert exit_code == 0
    assert (tmp_path / "hoopdata.duckdb").exists()
    assert "player_box_scores 2023-24 Playoffs: 19 rows" in capsys.readouterr().out
