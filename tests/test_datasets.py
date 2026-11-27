import json
import shutil
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from hoopdata.cli import main
from hoopdata.ingest import DATASETS, Dataset, ingest
from hoopdata.source import ReplaySource
from hoopdata.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
SUMMER = date(2024, 7, 1)


class FakeDataset(Dataset):
    """A test-only dataset: one ``fake_scores`` table, one request per season and season type."""

    def __init__(self):
        super().__init__(
            name="fake",
            tables={"fake": [("fake_scores", self._to_table)]},
            fetch=self._fetch,
            views="""
                create view fake_scores as
                select * from read_parquet(
                    '{root}/fake/fake_scores/*/*.parquet',
                    hive_partitioning = true,
                    hive_types = {'season': varchar}
                );
            """,
        )
        self.requests_made = []

    def _fetch(self, source, season, season_type, kind):
        self.requests_made.append((season, season_type))
        return {"score": 7}

    @staticmethod
    def _to_table(raw, season, season_type):
        return pd.DataFrame({"season": [season], "season_type": [season_type], "score": [raw["score"]]})


@pytest.fixture
def fake(monkeypatch):
    dataset = FakeDataset()
    monkeypatch.setitem(DATASETS, "fake", dataset)
    return dataset


def manifest(data_root):
    return json.loads((Path(data_root) / "manifest.json").read_text(encoding="utf-8"))


def test_adding_a_dataset_fetches_it_for_the_seasons_already_held_and_publishes_its_views(tmp_path, fake):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"], today=SUMMER)

    ingest(ReplaySource(FIXTURES), store, datasets=["fake"], today=SUMMER)

    assert manifest(tmp_path)["selection"] == {"datasets": ["core", "fake"], "seasons": ["2022-23", "2023-24"]}
    assert (tmp_path / "fake").is_dir()
    assert fake.requests_made == [
        ("2022-23", "Regular Season"), ("2022-23", "PlayIn"), ("2022-23", "Playoffs"),
        ("2023-24", "Regular Season"), ("2023-24", "PlayIn"), ("2023-24", "Playoffs"),
    ]
    with duckdb.connect(str(tmp_path / "hoopdata.duckdb"), read_only=True) as con:
        rows = con.execute("select season, season_type, score from fake_scores order by all").fetchall()
    assert rows == [
        ("2022-23", "PlayIn", 7), ("2022-23", "Playoffs", 7), ("2022-23", "Regular Season", 7),
        ("2023-24", "PlayIn", 7), ("2023-24", "Playoffs", 7), ("2023-24", "Regular Season", 7),
    ]


def test_a_first_run_with_no_datasets_loads_core_only(tmp_path, fake):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], today=SUMMER)

    assert manifest(tmp_path)["selection"]["datasets"] == ["core"]
    assert not (tmp_path / "fake").exists()
    assert fake.requests_made == []


def test_the_datasets_flag_adds_a_comma_separated_list(tmp_path, fake):
    main(["ingest", "--data-root", str(tmp_path), "--season", "2023-24"], source=ReplaySource(FIXTURES))

    exit_code = main(["ingest", "--data-root", str(tmp_path), "--datasets", "core,fake"], source=ReplaySource(FIXTURES))

    assert exit_code == 0
    assert manifest(tmp_path)["selection"]["datasets"] == ["core", "fake"]


def test_an_unknown_dataset_exits_non_zero_and_changes_nothing(tmp_path, fake, capsys):
    main(["ingest", "--data-root", str(tmp_path), "--season", "2023-24"], source=ReplaySource(FIXTURES))
    before = (tmp_path / "manifest.json").read_text(encoding="utf-8")

    exit_code = main(["ingest", "--data-root", str(tmp_path), "--datasets", "fake,bogus"], source=ReplaySource(FIXTURES))

    assert exit_code != 0
    assert "bogus" in capsys.readouterr().err
    assert (tmp_path / "manifest.json").read_text(encoding="utf-8") == before
    assert not (tmp_path / "fake").exists()
    assert fake.requests_made == []


def test_a_saved_dataset_that_is_no_longer_registered_exits_non_zero_naming_it(tmp_path, capsys):
    main(["ingest", "--data-root", str(tmp_path), "--season", "2023-24"], source=ReplaySource(FIXTURES))
    saved = manifest(tmp_path)
    saved["selection"]["datasets"].append("retired")
    (tmp_path / "manifest.json").write_text(json.dumps(saved), encoding="utf-8")
    (tmp_path / "retired").mkdir()

    exit_code = main(["ingest", "--data-root", str(tmp_path)], source=ReplaySource(FIXTURES))

    assert exit_code != 0
    assert "retired" in capsys.readouterr().err


def test_all_adds_every_dataset(tmp_path, fake):
    main(["ingest", "--data-root", str(tmp_path), "--season", "2023-24"], source=ReplaySource(FIXTURES))

    main(["ingest", "--data-root", str(tmp_path), "--datasets", "all"], source=ReplaySource(FIXTURES))

    assert manifest(tmp_path)["selection"]["datasets"] == ["core", "fake"]


def published_views(data_root):
    with duckdb.connect(str(Path(data_root) / "hoopdata.duckdb"), read_only=True) as con:
        return {row[0] for row in con.execute("select view_name from duckdb_views() where not internal").fetchall()}


def test_deleting_a_datasets_folder_removes_it_from_the_selection_the_manifest_and_the_views(tmp_path, fake):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"], datasets=["fake"], today=SUMMER)
    assert "fake_scores" in published_views(tmp_path)
    shutil.rmtree(tmp_path / "fake")

    ingest(ReplaySource(FIXTURES), store, today=SUMMER)

    assert manifest(tmp_path)["selection"]["datasets"] == ["core"]
    assert {i["table"] for i in manifest(tmp_path)["items"]} == {"player_box_scores", "team_box_scores", "games", "players"}
    assert "fake_scores" not in published_views(tmp_path)
    assert "player_box_scores" in published_views(tmp_path)


class Crash(BaseException):
    """Stands in for the process dying, so nothing catches it."""


class CrashingFakeDataset(FakeDataset):
    def _fetch(self, source, season, season_type, kind):
        raise Crash()


def test_a_dataset_added_in_a_run_that_crashes_before_writing_data_keeps_its_folder_and_stays_selected(
    tmp_path, monkeypatch, fake
):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"], today=SUMMER)
    monkeypatch.setitem(DATASETS, "fake", CrashingFakeDataset())
    with pytest.raises(Crash):
        ingest(ReplaySource(FIXTURES), store, datasets=["fake"], today=SUMMER)
    assert (tmp_path / "fake").is_dir()
    monkeypatch.setitem(DATASETS, "fake", fake)

    ingest(ReplaySource(FIXTURES), store, today=SUMMER)

    assert manifest(tmp_path)["selection"]["datasets"] == ["core", "fake"]
    assert fake.requests_made == [("2023-24", "Regular Season"), ("2023-24", "PlayIn"), ("2023-24", "Playoffs")]


def test_the_published_file_is_rebuilt_when_the_selection_changes_and_not_otherwise(tmp_path, fake):
    store = Store(tmp_path)
    database = tmp_path / "hoopdata.duckdb"
    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"], today=SUMMER)
    first = database.stat().st_mtime_ns

    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"], today=SUMMER)
    unchanged = database.stat().st_mtime_ns
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23"], today=SUMMER)
    new_season = database.stat().st_mtime_ns
    ingest(ReplaySource(FIXTURES), store, datasets=["fake"], today=SUMMER)
    new_dataset = database.stat().st_mtime_ns

    assert unchanged == first
    assert new_season != unchanged
    assert new_dataset != new_season


class CountingSource(ReplaySource):
    def __init__(self, fixtures_dir):
        super().__init__(fixtures_dir)
        self.game_log_requests = 0

    def game_log(self, season, season_type, kind):
        self.game_log_requests += 1
        return super().game_log(season, season_type, kind)


def test_the_estimate_counts_each_datasets_requests(tmp_path, fake, capsys):
    store = Store(tmp_path)
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23", "2023-24"], today=SUMMER)
    capsys.readouterr()

    source = CountingSource(FIXTURES)
    ingest(source, store, datasets=["fake"], today=SUMMER)

    # 2023-24 is the latest season, so core refetches its 6 game logs. fake has 3 per season, all missing.
    assert "About 12 requests, roughly 12 s (core: 6 · fake: 6)" in capsys.readouterr().out
    assert source.game_log_requests == 6
    assert len(fake.requests_made) == 6


def query(data_root, sql):
    with duckdb.connect(str(Path(data_root) / "hoopdata.duckdb"), read_only=True) as con:
        return con.execute(sql).fetchall()


def test_hoopdata_datasets_lists_core_and_every_selected_dataset(tmp_path, fake):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], datasets=["fake"], today=SUMMER)

    assert query(tmp_path, "select dataset from hoopdata_datasets order by dataset") == [("core",), ("fake",)]


def test_hoopdata_datasets_leaves_out_datasets_not_selected(tmp_path, fake):
    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], today=SUMMER)

    assert query(tmp_path, "select dataset from hoopdata_datasets") == [("core",)]


class FailingFakeDataset(FakeDataset):
    def _fetch(self, source, season, season_type, kind):
        raise ConnectionError("timed out")


def test_a_dataset_is_incomplete_while_an_item_has_failed_and_complete_once_all_succeed(tmp_path, monkeypatch, fake):
    store = Store(tmp_path)
    monkeypatch.setitem(DATASETS, "fake", FailingFakeDataset())
    ingest(ReplaySource(FIXTURES), store, seasons=["2023-24"], datasets=["fake"], today=SUMMER)
    failed = query(tmp_path, "select dataset, complete from hoopdata_datasets order by dataset")
    monkeypatch.setitem(DATASETS, "fake", fake)

    ingest(ReplaySource(FIXTURES), store, today=SUMMER)

    assert failed == [("core", True), ("fake", False)]
    assert query(tmp_path, "select dataset, complete from hoopdata_datasets order by dataset") == [
        ("core", True), ("fake", True),
    ]


def test_last_updated_is_when_each_dataset_last_fetched_an_item(tmp_path, fake):
    store = Store(tmp_path)
    # 2022-23 isn't the latest season, so once it's complete core fetches nothing more.
    ingest(ReplaySource(FIXTURES), store, seasons=["2022-23"], today=SUMMER)
    core_fetched = max(datetime.fromisoformat(i["fetched_at"]) for i in manifest(tmp_path)["items"])

    ingest(ReplaySource(FIXTURES), store, datasets=["fake"], today=SUMMER)

    fake_fetched = max(
        datetime.fromisoformat(i["fetched_at"]) for i in manifest(tmp_path)["items"] if i["table"] == "fake_scores"
    )
    assert query(tmp_path, "select dataset, last_updated from hoopdata_datasets order by dataset") == [
        ("core", core_fetched), ("fake", fake_fetched),
    ]
    assert fake_fetched > core_fetched


class TwoTableFakeDataset(FakeDataset):
    """A fake dataset with a second table, ``fake_extras``, whose requests always fail."""

    def __init__(self):
        super().__init__()
        self.tables = {**self.tables, "extras": [("fake_extras", self._to_table)]}
        self.views += """
            create view fake_extras as
            select * from read_parquet(
                '{root}/fake/fake_extras/*/*.parquet',
                hive_partitioning = true,
                hive_types = {'season': varchar}
            );
        """

    def _fetch(self, source, season, season_type, kind):
        if kind == "extras":
            raise ConnectionError("timed out")
        return super()._fetch(source, season, season_type, kind)


def test_a_datasets_views_wait_until_every_one_of_its_tables_has_data(tmp_path, monkeypatch):
    monkeypatch.setitem(DATASETS, "fake", TwoTableFakeDataset())

    ingest(ReplaySource(FIXTURES), Store(tmp_path), seasons=["2023-24"], datasets=["fake"], today=SUMMER)

    assert (tmp_path / "fake" / "fake_scores").is_dir()
    assert "fake_scores" not in published_views(tmp_path)
    assert "fake_extras" not in published_views(tmp_path)
    assert "player_box_scores" in published_views(tmp_path)
