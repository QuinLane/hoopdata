"""Everything inside the data root: Parquet partitions and the published DuckDB file."""

import os
from importlib.resources import files
from pathlib import Path

import duckdb

DATABASE_NAME = "hoopdata.duckdb"


class Store:
    def __init__(self, data_root):
        self.root = Path(data_root).resolve()

    @property
    def database_path(self):
        return self.root / DATABASE_NAME

    def write_partition(self, table, season, season_type, df):
        """Atomically write one table/season/season_type partition as Parquet.

        ``season`` lives in the hive folder name, so it is left out of the file.
        """
        folder = self.root / table / f"season={season}"
        path = folder / f"{season_type.replace(' ', '_').lower()}.parquet"
        _write_parquet(df.drop(columns="season"), path)

    def write_table(self, table, df):
        """Atomically write a whole unpartitioned table as one Parquet file."""
        _write_parquet(df, self.root / f"{table}.parquet")

    def read_table(self, table):
        """Read an unpartitioned table, or ``None`` if it hasn't been written yet."""
        path = self.root / f"{table}.parquet"
        if not path.exists():
            return None
        with duckdb.connect() as con:
            return con.execute(f"select * from read_parquet('{_sql_path(path)}')").df()

    def publish(self):
        """Build the views-only DuckDB file that consumers open read-only."""
        sql = files("hoopdata").joinpath("views.sql").read_text(encoding="utf-8")
        temp = self.database_path.with_name(DATABASE_NAME + ".tmp")
        temp.unlink(missing_ok=True)
        with duckdb.connect(str(temp)) as con:
            con.execute(sql.replace("{root}", _sql_path(self.root)))
        os.replace(temp, self.database_path)


def _write_parquet(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        with duckdb.connect() as con:
            con.register("data", df)
            con.execute(f"copy data to '{_sql_path(temp)}' (format parquet)")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _sql_path(path):
    return path.as_posix().replace("'", "''")
