"""Everything inside the data root: Parquet partitions, the manifest and the published DuckDB file."""

import hashlib
import json
import os
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import duckdb

DATABASE_NAME = "hoopdata.duckdb"
MANIFEST_NAME = "manifest.json"
LOGS_FOLDER = "logs"

# Bump on any breaking schema change: a column renamed or removed, or its meaning changed.
SCHEMA_VERSION = 1

SUCCEEDED = "succeeded"
FAILED = "failed"


class Store:
    def __init__(self, data_root):
        self.root = Path(data_root).resolve()

    @property
    def database_path(self):
        return self.root / DATABASE_NAME

    @property
    def manifest_path(self):
        return self.root / MANIFEST_NAME

    def new_log_path(self):
        """A fresh log file path for one run, named by its start time."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.root / LOGS_FOLDER / f"ingest-{stamp}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def read_manifest(self):
        """The manifest as a dict, or an empty one if nothing has been recorded yet."""
        if not self.manifest_path.exists():
            return {"schema_version": SCHEMA_VERSION, "last_updated": None, "items": []}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def succeeded_items(self, season):
        """The ``(table, season_type)`` items of ``season`` whose latest fetch succeeded."""
        return {
            (i["table"], i["season_type"])
            for i in self.read_manifest()["items"]
            if i["season"] == season and i["status"] == SUCCEEDED
        }

    def record_item(self, table, season, season_type, status, rows=None, error=None):
        """Record one item's outcome in the manifest and bump the last-updated time."""
        now = datetime.now(timezone.utc).isoformat()
        key = (table, season, season_type)
        manifest = self.read_manifest()
        items = [i for i in manifest["items"] if (i["table"], i["season"], i["season_type"]) != key]
        items.append({
            "table": table,
            "season": season,
            "season_type": season_type,
            "status": status,
            "fetched_at": now,
            "rows": rows,
            "error": error,
        })
        manifest["schema_version"] = SCHEMA_VERSION
        manifest["last_updated"] = now
        manifest["items"] = sorted(items, key=lambda i: (i["table"], i["season"], i["season_type"]))
        _write_atomically(self.manifest_path, json.dumps(manifest, indent=2))

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

    def distinct_values(self, table, column):
        """The distinct values of ``column`` across every partition of ``table``, empty if none are written."""
        if not list((self.root / table).glob("*/*.parquet")):
            return set()
        with duckdb.connect() as con:
            pattern = _sql_path(self.root / table / "*" / "*.parquet")
            return {row[0] for row in con.execute(f"select distinct {column} from read_parquet('{pattern}')").fetchall()}

    def publish(self):
        """Build the views-only DuckDB file that consumers open read-only.

        The file is rebuilt only when the views, the schema version or the data root
        have changed since it was last built. New data shows up through the views anyway.
        """
        sql = files("hoopdata").joinpath("views.sql").read_text(encoding="utf-8")
        sql = sql.replace("{root}", _sql_path(self.root))
        views_hash = hashlib.sha256(f"{SCHEMA_VERSION}\n{sql}".encode()).hexdigest()
        manifest = self.read_manifest()
        if self.database_path.exists() and manifest.get("views_hash") == views_hash:
            return

        temp = self.database_path.with_name(DATABASE_NAME + ".tmp")
        temp.unlink(missing_ok=True)
        with duckdb.connect(str(temp)) as con:
            con.execute(sql)
        os.replace(temp, self.database_path)
        manifest["views_hash"] = views_hash
        _write_atomically(self.manifest_path, json.dumps(manifest, indent=2))


def _write_atomically(path, text):
    _replace_atomically(path, lambda temp: temp.write_text(text, encoding="utf-8"))


def _write_parquet(df, path):
    def write(temp):
        with duckdb.connect() as con:
            con.register("data", df)
            con.execute(f"copy data to '{_sql_path(temp)}' (format parquet)")

    _replace_atomically(path, write)


def _replace_atomically(path, write):
    """Call ``write`` with a temp path next to ``path``, then swap it in, so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        write(temp)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _sql_path(path):
    return path.as_posix().replace("'", "''")
