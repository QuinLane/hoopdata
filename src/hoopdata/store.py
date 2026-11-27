"""Everything inside the data root: Parquet partitions, the manifest and the published DuckDB file."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import duckdb

DATABASE_NAME = "hoopdata.duckdb"
MANIFEST_NAME = "manifest.json"
LOGS_FOLDER = "logs"

# Bump on any breaking schema change: a column renamed or removed, or its meaning changed.
SCHEMA_VERSION = 1

SUCCEEDED = "succeeded"
FAILED = "failed"

# The dataset every data root holds, and the season set that means every season, including future ones.
CORE = "core"
ALL_SEASONS = "all"

# The file name of a season-only partition, one whose source doesn't split by season type.
SEASON_ONLY_FILE = "season"


class Store:
    def __init__(self, data_root):
        self.root = Path(data_root).resolve()

    @property
    def database_path(self):
        return self.root / DATABASE_NAME

    @property
    def manifest_path(self):
        return self.root / MANIFEST_NAME

    def dataset_root(self, dataset):
        """Where ``dataset``'s tables live: the data root for core, its own top-level folder for the others."""
        return self.root if dataset == CORE else self.root / dataset

    def has_data(self, dataset, tables):
        """Whether each of ``dataset``'s ``tables`` has any Parquet files yet. DuckDB can't create a view over none."""
        return all(any((self.dataset_root(dataset) / table).rglob("*.parquet")) for table in tables)

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

    def read_selection(self):
        """The saved selection as ``{"datasets": [...], "seasons": "all" or [...]}``, or ``None`` for an empty data root.

        A v1 manifest with items but no selection holds core with all seasons.
        """
        manifest = self.read_manifest()
        if "selection" in manifest:
            return manifest["selection"]
        if manifest["items"]:
            return {"datasets": [CORE], "seasons": ALL_SEASONS}
        return None

    def write_selection(self, selection):
        self._write_manifest_key("selection", selection)

    def write_datasets(self, datasets):
        """Record each selected dataset's status, a list of ``{"dataset", "last_updated", "complete"}``, for ``hoopdata_datasets``."""
        self._write_manifest_key("datasets", datasets)

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

    def drop_items(self, tables):
        """Remove every item of ``tables`` from the manifest."""
        manifest = self.read_manifest()
        manifest["items"] = [i for i in manifest["items"] if i["table"] not in tables]
        _write_atomically(self.manifest_path, json.dumps(manifest, indent=2))

    def write_partition(self, table, season, season_type, df, dataset=CORE):
        """Atomically write one table/season/season_type partition of ``dataset`` as Parquet.

        ``season`` lives in the hive folder name, so it is left out of the file. A ``season_type`` of
        ``None`` is a season-only partition.
        """
        _write_parquet(df.drop(columns="season"), self._partition_path(table, season, season_type, dataset))

    def read_partition(self, table, season, season_type, dataset=CORE):
        """Read one table/season/season_type partition of ``dataset``, or ``None`` if it hasn't been written yet."""
        return _read_parquet(self._partition_path(table, season, season_type, dataset))

    def write_game(self, table, season, season_type, game_id, df, dataset):
        """Atomically write one game of a per-game table, in a folder named like the season type's partition file."""
        _write_parquet(df, self._games_folder(table, season, season_type, dataset) / f"{game_id}.parquet")

    def held_games(self, table, season, season_type, dataset):
        """The game IDs a per-game table holds for ``season`` and ``season_type``."""
        return {path.stem for path in self._games_folder(table, season, season_type, dataset).glob("*.parquet")}

    def write_table(self, table, df):
        """Atomically write a whole unpartitioned table as one Parquet file."""
        _write_parquet(df, self.root / f"{table}.parquet")

    def read_table(self, table):
        """Read an unpartitioned table, or ``None`` if it hasn't been written yet."""
        return _read_parquet(self.root / f"{table}.parquet")

    def _partition_path(self, table, season, season_type, dataset):
        """The Parquet file of one table/season/season_type partition of ``dataset``, ``season.parquet`` if season-only."""
        folder = self.dataset_root(dataset) / table / f"season={season}"
        name = SEASON_ONLY_FILE if season_type is None else season_type.replace(" ", "_").lower()
        return folder / f"{name}.parquet"

    def _games_folder(self, table, season, season_type, dataset):
        """Like ``season=2023-24/regular_season``: the partition file's path without ``.parquet``."""
        return self._partition_path(table, season, season_type, dataset).with_suffix("")

    def distinct_values(self, table, column):
        """The distinct values of ``column`` across every partition of ``table``, empty if none are written."""
        if not list((self.root / table).glob("*/*.parquet")):
            return set()
        with duckdb.connect() as con:
            pattern = _sql_path(self.root / table / "*" / "*.parquet")
            return {row[0] for row in con.execute(f"select distinct {column} from read_parquet('{pattern}')").fetchall()}

    def publish(self, views):
        """Build the views-only DuckDB file that consumers open read-only, from the selected datasets' ``views`` SQL.

        The file is rebuilt only when the views, the schema version, the selection or the data root
        have changed since it was last built. New data shows up through the views anyway.
        """
        sql = "\n".join(views).replace("{root}", _sql_path(self.root))
        manifest = self.read_manifest()
        selection = json.dumps(manifest.get("selection"))
        views_hash = hashlib.sha256(f"{SCHEMA_VERSION}\n{selection}\n{sql}".encode()).hexdigest()
        if self.database_path.exists() and manifest.get("views_hash") == views_hash:
            return

        temp = self.database_path.with_name(DATABASE_NAME + ".tmp")
        temp.unlink(missing_ok=True)
        with duckdb.connect(str(temp)) as con:
            con.execute(sql)
        os.replace(temp, self.database_path)
        self._write_manifest_key("views_hash", views_hash)

    def _write_manifest_key(self, key, value):
        """Set one top-level key of the manifest, keeping the rest."""
        manifest = self.read_manifest()
        manifest[key] = value
        _write_atomically(self.manifest_path, json.dumps(manifest, indent=2))


def _write_atomically(path, text):
    _replace_atomically(path, lambda temp: temp.write_text(text, encoding="utf-8"))


def _write_parquet(df, path):
    def write(temp):
        with duckdb.connect() as con:
            con.register("data", df)
            con.execute(f"copy data to '{_sql_path(temp)}' (format parquet)")

    _replace_atomically(path, write)


def _read_parquet(path):
    """Read one Parquet file, or ``None`` if it hasn't been written yet."""
    if not path.exists():
        return None
    with duckdb.connect() as con:
        return con.execute(f"select * from read_parquet('{_sql_path(path)}')").df()


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
