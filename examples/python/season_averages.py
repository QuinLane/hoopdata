"""Print player season averages from a hoopdata data root.

    uv run examples/python/season_averages.py [DATA_ROOT]

DATA_ROOT defaults to $NBA_DATA_ROOT, then ./data.
"""

import os
import sys
from pathlib import Path

import duckdb

data_root = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NBA_DATA_ROOT") or "data")

with duckdb.connect(str(data_root / "hoopdata.duckdb"), read_only=True) as con:
    df = con.sql(
        """
        select season, season_type, player_name, games_played, pts, reb, ast, fg_pct
        from player_season_averages
        where games_played >= 20
        order by pts desc
        limit 20
        """
    ).df()

print(df.to_string(index=False))
