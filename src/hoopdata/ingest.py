import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from importlib.resources import files
from pathlib import Path

import pandas as pd
from nba_api.stats.static import teams as static_teams

from hoopdata import transform
from hoopdata.source import GAME, PLAY_IN, PLAYER, PLAYOFFS, REGULAR_SEASON, SEASON_TYPES, TEAM
from hoopdata.store import ALL_SEASONS, CORE, FAILED, SUCCEEDED

PLAYER_BOX_SCORES = "player_box_scores"
TEAM_BOX_SCORES = "team_box_scores"
GAMES = "games"
PLAYERS = "players"
TEAMS = "teams"
PLAYER_ADVANCED_BOX_SCORES = "player_advanced_box_scores"
TEAM_ADVANCED_BOX_SCORES = "team_advanced_box_scores"
SHOTS = "shots"
OFFICIAL_ROSTERS = "official_rosters"
COACH_SEASONS = "coach_seasons"
PLAY_BY_PLAY = "play_by_play"

ADVANCED = "advanced"
ROSTERS = "rosters"
PBP = "pbp"

FIRST_SEASON_START_YEAR = 1996

# Play-In games only exist from this season on, so earlier seasons never get a Play-In item.
FIRST_PLAY_IN_SEASON = "2019-20"

# Bios are written to players.parquet after every this many players.
BIOS_PER_WRITE = 20

# The source paces requests about this far apart, which the time estimate assumes.
SECONDS_PER_REQUEST = 1

# The estimate's guess at how many new players' bios a season held for the first time needs.
NEW_PLAYERS_PER_SEASON = 90

# Rough requests for each dataset's full backfill of every season, shown in --help.
# Core: ~135 game logs (30 seasons, regular season and playoffs, Play-In from 2019-20, 2 kinds) plus ~2,700 player
# bios (NEW_PLAYERS_PER_SEASON for each season).
# Advanced: ~135 requests, counted like core's game logs: one league-wide request per table (player and team) for
# each season and season type (30 seasons, regular season and playoffs, Play-In from 2019-20).
# Shots: one shot chart per team per season and season type, ~1,400 requests (30 teams in a regular season, 16 in
# the playoffs, 8 in the Play-In).
# Rosters: one team roster per team per season, ~930 requests (31 seasons of about 30 teams).
# Pbp: one request per game, ~38,000 requests (about 1,230 games a season since 1996-97, plus the playoffs and
# Play-In).
FULL_BACKFILL_REQUESTS = {CORE: 2_800, ADVANCED: 135, SHOTS: 1_400, ROSTERS: 930, PBP: 38_000}

log = logging.getLogger(__name__)

# Each game log kind feeds these tables, each with its transform.
TABLES = {
    PLAYER: [(PLAYER_BOX_SCORES, transform.player_box_scores)],
    TEAM: [(TEAM_BOX_SCORES, transform.team_box_scores), (GAMES, transform.games)],
}


@dataclass
class Dataset:
    """A group of tables and views loaded or left out together.

    Like core's game logs, a dataset is fetched once per season, season type and kind. ``tables``
    maps each kind to the ``(table, transform)`` pairs its response feeds, ``fetch`` gets the
    response as ``fetch(source, store, season, season_type, kind)``, and ``views`` is the SQL that
    publishes its views, with ``{root}`` standing for the data root. A fetch can make several
    requests, reading what to ask for from ``store``. A ``None`` transform means the fetch writes
    that table itself, as it goes, and returns its row count. Such a fetch can skip what's already
    held, so refetching the latest season only fetches what's new (play-by-play, ADR 0003).

    ``season_types`` are the season types the dataset has items for. ``(None,)`` makes the items
    season-only: one per table and season, fetched with ``season_type`` ``None``.
    ``requests(store, season, season_type)`` is how many requests one fetch makes, for the estimate.
    """

    name: str
    tables: dict
    fetch: object
    views: str
    season_types: tuple = tuple(SEASON_TYPES)
    requests: object = lambda store, season, season_type: 1

    @property
    def table_names(self):
        """Every table the dataset writes."""
        return {table for tables in self.tables.values() for table, _ in tables}

    def to_fetch(self, store, seasons, latest):
        """The fetches with failed or missing items in ``seasons``, as ``(season, season_type, kind, tables)``.

        Each fetch is one call to ``fetch``, which can make several requests.

        ``tables`` lists only the ``(table, transform)`` pairs to write. A season with every item
        succeeded is skipped, except ``latest``, which is fetched in full.
        """
        return [
            (season, season_type, kind, tables)
            for season in seasons
            for season_type, kind, tables in self._fetches(store, season, season == latest)
        ]

    def request_count(self, store, to_fetch):
        """How many requests fetching ``to_fetch``, from ``to_fetch()``, makes."""
        return sum(self.requests(store, season, season_type) for season, season_type, _, _ in to_fetch)

    def _fetches(self, store, season, refetch_complete):
        """``season``'s fetches with failed or missing items, as ``(season_type, kind, tables)``."""
        season_types = [t for t in [*_season_types(season), None] if t in self.season_types]
        all_items = {(table, season_type) for season_type in season_types for table in self.table_names}
        to_fetch = all_items - store.succeeded_items(season) or (all_items if refetch_complete else set())
        fetches = []
        for season_type in season_types:
            for kind, tables in self.tables.items():
                tables = [(table, to_table) for table, to_table in tables if (table, season_type) in to_fetch]
                if tables:
                    fetches.append((season_type, kind, tables))
        return fetches


# The ``datasets`` value that means every dataset in ``DATASETS``.
ALL_DATASETS = "all"

# Every dataset a data root can hold, by name.
DATASETS = {
    CORE: Dataset(
        CORE,
        TABLES,
        lambda source, store, season, season_type, kind: source.game_log(season, season_type, kind),
        files("hoopdata").joinpath("views.sql").read_text(encoding="utf-8"),
    ),
    ADVANCED: Dataset(
        ADVANCED,
        {
            PLAYER: [(PLAYER_ADVANCED_BOX_SCORES, transform.player_advanced_box_scores)],
            TEAM: [(TEAM_ADVANCED_BOX_SCORES, transform.team_advanced_box_scores)],
        },
        lambda source, store, season, season_type, kind: source.advanced_box_scores(season, season_type, kind),
        files("hoopdata").joinpath("advanced_views.sql").read_text(encoding="utf-8"),
    ),
    SHOTS: Dataset(
        SHOTS,
        {TEAM: [(SHOTS, transform.shots)]},
        lambda source, store, season, season_type, kind: _fetch_shot_charts(source, store, season, season_type),
        files("hoopdata").joinpath("shots_views.sql").read_text(encoding="utf-8"),
        requests=lambda store, season, season_type: {REGULAR_SEASON: 30, PLAY_IN: 8, PLAYOFFS: 16}[season_type],
    ),
    ROSTERS: Dataset(
        ROSTERS,
        {TEAM: [(OFFICIAL_ROSTERS, transform.official_rosters), (COACH_SEASONS, transform.coach_seasons)]},
        lambda source, store, season, season_type, kind: _fetch_team_rosters(source, store, season),
        files("hoopdata").joinpath("rosters_views.sql").read_text(encoding="utf-8"),
        season_types=(None,),
        requests=lambda store, season, season_type: 30,
    ),
    PBP: Dataset(
        PBP,
        {GAME: [(PLAY_BY_PLAY, None)]},
        lambda source, store, season, season_type, kind: _fetch_play_by_play(source, store, season, season_type),
        files("hoopdata").joinpath("pbp_views.sql").read_text(encoding="utf-8"),
        requests=lambda store, season, season_type: len(_games_without_play_by_play(store, season, season_type)),
    ),
}


class MissingCoreError(Exception):
    """Core doesn't hold the games a dataset's fetch reads from it, so the item fails and is retried."""


def _fetch_shot_charts(source, store, season, season_type):
    """Each team's shot chart, for every team in core's team box scores of ``season`` and ``season_type``."""
    team_box_scores = store.read_partition(TEAM_BOX_SCORES, season, season_type)
    if team_box_scores is None:
        raise MissingCoreError(f"core holds no team box scores for {season} {season_type}")
    return [source.shot_chart(season, season_type, team_id) for team_id in sorted(set(team_box_scores["team_id"]))]


def _fetch_team_rosters(source, store, season):
    """Each team's roster, for every team in core's team box scores of ``season``, any season type."""
    partitions = [store.read_partition(TEAM_BOX_SCORES, season, season_type) for season_type in _season_types(season)]
    team_ids = sorted({team_id for df in partitions if df is not None for team_id in df["team_id"]})
    if not team_ids:
        raise MissingCoreError(f"core holds no games for {season} yet")
    return [source.team_roster(season, team_id) for team_id in team_ids]


class FailedGamesError(Exception):
    """Some of a play-by-play item's games failed. The games fetched are kept, and the next run fetches the rest."""


def _fetch_play_by_play(source, store, season, season_type):
    """Fetch and write each game's play-by-play that isn't held yet, returning the rows written.

    The games are those in core's team box scores of ``season`` and ``season_type``. Each game is
    written as soon as it's fetched, and a held game is never fetched again (ADR 0003). A failed
    game is logged and the rest are still fetched, then the item fails. If core holds no games for
    them, the item fails without any requests.
    """
    if store.read_partition(TEAM_BOX_SCORES, season, season_type) is None:
        raise MissingCoreError(f"core holds no team box scores for {season} {season_type}")
    game_ids = _games_without_play_by_play(store, season, season_type)
    rows, errors = 0, []
    for game_id in game_ids:
        try:
            df = transform.play_by_play(source.play_by_play(game_id))
            store.write_game(PLAY_BY_PLAY, season, season_type, game_id, df, dataset=PBP)
            rows += len(df)
        except Exception as e:
            errors.append(e)
            log.error("play-by-play for game %s failed", game_id, exc_info=e)
    if errors:
        raise FailedGamesError(f"{len(errors)} of {len(game_ids)} games failed, first: {_describe(errors[0])}")
    return rows


def _games_without_play_by_play(store, season, season_type):
    """The games in core's team box scores of ``season`` and ``season_type`` with no play-by-play held yet, sorted."""
    team_box_scores = store.read_partition(TEAM_BOX_SCORES, season, season_type)
    games = set(team_box_scores["game_id"]) if team_box_scores is not None else set()
    return sorted(games - store.held_games(PLAY_BY_PLAY, season, season_type, dataset=PBP))


class EmptySelectionError(Exception):
    """Plain ``ingest`` on a data root with no selection yet: there is nothing to keep current."""


class UnknownDatasetError(Exception):
    """A dataset name that isn't one of ``DATASETS``."""


@dataclass
class Item:
    """One fetched table, season and season type. ``players`` is one item with no season, and a season-only item has
    no season type."""

    table: str
    season: str | None
    season_type: str | None
    status: str
    rows: int | None = None
    error: str | None = None

    @property
    def name(self):
        return " ".join(part for part in [self.table, self.season, self.season_type] if part is not None)


@dataclass
class Report:
    log_path: Path
    items: list[Item] = field(default_factory=list)

    @property
    def failed(self):
        return [item for item in self.items if item.status == FAILED]


def ingest(source, store, seasons=None, datasets=None, today=None):
    """Fetch each season's player and team box scores, bios for new players and the team list, and publish the views.

    The data root remembers its selection (ADR 0002). ``seasons`` adds to it: a list of seasons, or
    ``"all"`` for every season from 1996-97 on, including future ones. With no ``seasons`` the saved
    selection is kept as it is, and an empty data root raises ``EmptySelectionError``. ``datasets``
    adds names from ``DATASETS`` for the seasons already held; an unknown name, passed or in the saved
    selection, raises ``UnknownDatasetError`` before anything changes.

    Every run fetches the failed or missing items of the selected seasons, and refetches the latest
    season (the one containing ``today``) if the selection includes it. A failed item (table +
    season + season type) is recorded and skipped, and the run continues. Every player in the stored
    box scores without a bio gets one.
    """
    if datasets is not None and ALL_DATASETS in datasets:
        datasets = list(DATASETS)
    unknown = sorted(set(datasets or []) - set(DATASETS))
    if unknown:
        raise UnknownDatasetError(f"Unknown dataset: {', '.join(unknown)}. Choose from {', '.join(DATASETS)} or all.")
    selection = store.read_selection()
    unregistered = sorted(set(selection["datasets"]) - set(DATASETS)) if selection else []
    if unregistered:
        raise UnknownDatasetError(
            f"The data root's selection has a dataset this hoopdata doesn't know: {', '.join(unregistered)}."
        )
    selection = _drop_deleted_datasets(store, selection)
    selection = _add_datasets(_add_seasons(selection, seasons), datasets)
    for name in selection["datasets"]:
        store.dataset_root(name).mkdir(parents=True, exist_ok=True)
    store.write_selection(selection)
    today = today or date.today()
    latest = _season(_latest_season_start_year(today))
    selected = _all_seasons(today) if selection["seasons"] == ALL_SEASONS else selection["seasons"]
    fetches = {name: DATASETS[name].to_fetch(store, selected, latest) for name in selection["datasets"]}
    counts = {name: DATASETS[name].request_count(store, to_fetch) for name, to_fetch in fetches.items()}
    counts[CORE] += len(_players_without_bios(store)) + NEW_PLAYERS_PER_SEASON * len(
        _seasons_without_box_scores(store, fetches[CORE])
    )
    print(_estimate(counts))
    report = Report(store.new_log_path())
    with _logging_to(report.log_path):
        for name, to_fetch in fetches.items():
            for season, season_type, kind, tables in to_fetch:
                _fetch_and_write(source, store, report, DATASETS[name], season, season_type, kind, tables)
        _add_new_players(source, store, report)
        store.write_table(TEAMS, transform.teams(static_teams.get_teams()))
        store.write_datasets([_dataset_status(store, name, selected) for name in selection["datasets"]])
        # A dataset's views are published once each of its tables has data, so a partly backfilled one shows up early.
        store.publish([
            DATASETS[name].views for name in selection["datasets"] if store.has_data(name, DATASETS[name].table_names)
        ])
    return report


def _add_seasons(selection, seasons):
    """``selection`` with ``seasons`` added. A selection only grows: ``"all"`` stays ``"all"``."""
    if selection is None:
        if seasons is None:
            raise EmptySelectionError("This data root has no selection yet. Pass --season or --all-seasons.")
        selection = {"datasets": [CORE], "seasons": []}
    if seasons is None or selection["seasons"] == ALL_SEASONS:
        return selection
    if seasons == ALL_SEASONS:
        return {**selection, "seasons": ALL_SEASONS}
    return {**selection, "seasons": sorted(set(selection["seasons"]) | set(seasons))}


def _drop_deleted_datasets(store, selection):
    """A selected dataset whose folder is gone has been deleted: it leaves ``selection`` and its items are dropped."""
    if selection is None:
        return None
    deleted = [name for name in selection["datasets"] if not store.dataset_root(name).is_dir()]
    if not deleted:
        return selection
    store.drop_items({table for name in deleted for table in DATASETS[name].table_names})
    return {**selection, "datasets": [name for name in selection["datasets"] if name not in deleted]}


def _add_datasets(selection, datasets):
    """``selection`` with ``datasets`` added, core first."""
    if datasets is None:
        return selection
    names = set(selection["datasets"]) | set(datasets)
    return {**selection, "datasets": sorted(names, key=lambda name: (name != CORE, name))}


def _dataset_status(store, name, seasons):
    """``name``'s row in ``hoopdata_datasets``: complete once every item in ``seasons`` has succeeded.

    Core also needs a bio for every player in its box scores. ``last_updated`` is when one of its
    items was last fetched.
    """
    tables = set(DATASETS[name].table_names)
    complete = not DATASETS[name].to_fetch(store, seasons, latest=None)
    if name == CORE:
        tables.add(PLAYERS)
        complete = complete and not _players_without_bios(store)
    fetched = [i["fetched_at"] for i in store.read_manifest()["items"] if i["table"] in tables]
    return {"dataset": name, "last_updated": max(fetched, default=None), "complete": complete}


def _seasons_without_box_scores(store, to_fetch):
    """The seasons in core's ``to_fetch`` with no stored player box scores yet, whose new players are only a guess."""
    seasons = {season for season, _, _, _ in to_fetch}
    return {
        season for season in seasons
        if not any(table == PLAYER_BOX_SCORES for table, _ in store.succeeded_items(season))
    }


def _estimate(requests):
    """A line like ``About 38,400 requests, roughly 11 h (pbp: 37,900 · core: 500)`` from requests per dataset."""
    total = sum(requests.values())
    breakdown = " · ".join(f"{dataset}: {count:,}" for dataset, count in requests.items())
    return f"About {total:,} requests, roughly {_duration(total * SECONDS_PER_REQUEST)} ({breakdown})"


def full_backfill_costs():
    """Each dataset's full-backfill cost, like ``core: about 2,800 requests, roughly 47 min``."""
    return "; ".join(
        f"{dataset}: about {count:,} requests, roughly {_duration(count * SECONDS_PER_REQUEST)}"
        for dataset, count in FULL_BACKFILL_REQUESTS.items()
    )


def _duration(seconds):
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 60 * 60:
        return f"{round(seconds / 60)} min"
    return f"{round(seconds / 60 / 60)} h"


@contextmanager
def _logging_to(path):
    """Send this module's log to ``path`` while the block runs."""
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        yield
    finally:
        log.removeHandler(handler)
        handler.close()


def _season_types(season):
    """The season types ``season`` has: Play-In only from 2019-20 on."""
    return [t for t in SEASON_TYPES if t != PLAY_IN or season >= FIRST_PLAY_IN_SEASON]


def _fetch_and_write(source, store, report, dataset, season, season_type, kind, tables):
    """Make one of ``dataset``'s fetches, which can take several requests, and write and record each of its tables."""
    try:
        raw = dataset.fetch(source, store, season, season_type, kind)
    except Exception as e:
        for table, _ in tables:
            _fail(store, report, table, season, season_type, e)
        return
    for table, to_table in tables:
        if to_table is None:
            # The fetch wrote this table itself and returned its row count.
            _record(store, report, Item(table, season, season_type, SUCCEEDED, rows=raw))
            continue
        try:
            df = to_table(raw, season, season_type)
            store.write_partition(table, season, season_type, df, dataset=dataset.name)
        except Exception as e:
            _fail(store, report, table, season, season_type, e)
        else:
            _record(store, report, Item(table, season, season_type, SUCCEEDED, rows=len(df)))


def _all_seasons(today):
    """Every season from 1996-97 through the latest one, like ``["1996-97", ..., "2024-25"]``."""
    return [_season(year) for year in range(FIRST_SEASON_START_YEAR, _latest_season_start_year(today) + 1)]


def _latest_season_start_year(today):
    """Seasons start in October, so before October the latest season is the one that started last year."""
    return today.year if today.month >= 10 else today.year - 1


def _season(start_year):
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _record(store, report, item):
    store.record_item(item.table, item.season, item.season_type, item.status, rows=item.rows, error=item.error)
    report.items.append(item)
    if item.status == SUCCEEDED:
        log.info("%s succeeded: %d rows", item.name, item.rows)


def _fail(store, report, table, season, season_type, error):
    item = Item(table, season, season_type, FAILED, error=_describe(error))
    _record(store, report, item)
    log.error("%s failed", item.name, exc_info=error)


def _describe(error):
    return f"{type(error).__name__}: {error}"


def _add_new_players(source, store, report):
    """Fetch bios for players in the stored box scores who have none yet. Existing bios are never refreshed.

    Bios are written every ``BIOS_PER_WRITE`` players, so a crash loses few of them. A failed bio
    is logged and skipped, and the ``players`` item records how many failed.
    """
    stored = store.read_table(PLAYERS)
    new_ids = _players_without_bios(store)
    if not new_ids:
        return
    try:
        all_players = source.all_players()
    except Exception as e:
        _fail(store, report, PLAYERS, None, None, e)
        return
    rows, errors = 0, []
    for start in range(0, len(new_ids), BIOS_PER_WRITE):
        infos, batch_errors = _fetch_bios(source, new_ids[start:start + BIOS_PER_WRITE])
        errors += batch_errors
        if infos:
            new = transform.players(all_players, infos)
            stored = pd.concat([stored, new]) if stored is not None else new
            store.write_table(PLAYERS, stored)
            rows += len(new)
    if errors:
        error = f"{len(errors)} of {len(new_ids)} bios failed, first: {_describe(errors[0])}"
        _record(store, report, Item(PLAYERS, None, None, FAILED, rows=rows, error=error))
    else:
        _record(store, report, Item(PLAYERS, None, None, SUCCEEDED, rows=rows))


def _players_without_bios(store):
    """The ids of players in the stored box scores who have no bio yet, sorted."""
    stored = store.read_table(PLAYERS)
    stored_ids = set(stored["player_id"]) if stored is not None else set()
    return sorted(store.distinct_values(PLAYER_BOX_SCORES, "player_id") - stored_ids)


def _fetch_bios(source, player_ids):
    """Each player's info, and the errors of those that failed, which are logged and skipped."""
    infos, errors = [], []
    for player_id in player_ids:
        try:
            infos.append(source.player_info(player_id))
        except Exception as e:
            errors.append(e)
            log.error("bio for player %s failed", player_id, exc_info=e)
    return infos, errors
