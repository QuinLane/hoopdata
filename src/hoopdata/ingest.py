import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
from nba_api.stats.static import teams as static_teams

from hoopdata import transform
from hoopdata.source import PLAY_IN, PLAYER, SEASON_TYPES, TEAM
from hoopdata.store import FAILED, SUCCEEDED

PLAYER_BOX_SCORES = "player_box_scores"
TEAM_BOX_SCORES = "team_box_scores"
GAMES = "games"
PLAYERS = "players"
TEAMS = "teams"

FIRST_SEASON_START_YEAR = 1996

# Play-In games only exist from this season on, so earlier seasons never get a Play-In item.
FIRST_PLAY_IN_SEASON = "2019-20"

# Bios are written to players.parquet after every this many players.
BIOS_PER_WRITE = 20

log = logging.getLogger(__name__)

# Each game log kind feeds these tables, each with its transform.
TABLES = {
    PLAYER: [(PLAYER_BOX_SCORES, transform.player_box_scores)],
    TEAM: [(TEAM_BOX_SCORES, transform.team_box_scores), (GAMES, transform.games)],
}


@dataclass
class Item:
    """One fetched table, season and season type. ``players`` is one item with no season."""

    table: str
    season: str | None
    season_type: str | None
    status: str
    rows: int | None = None
    error: str | None = None

    @property
    def name(self):
        return self.table if self.season is None else f"{self.table} {self.season} {self.season_type}"


@dataclass
class Report:
    log_path: Path
    items: list[Item] = field(default_factory=list)

    @property
    def failed(self):
        return [item for item in self.items if item.status == FAILED]


def ingest(source, store, seasons=None, today=None):
    """Fetch each season's player and team box scores, bios for new players and the team list, and publish the views.

    A failed item (table + season + season type) is recorded and skipped, and the run continues.
    A season with failed or missing items is resumed: only those items are fetched again, and
    every player in the stored box scores without a bio gets one.

    Passing ``seasons`` forces a refetch of those seasons. With no ``seasons``, every season from
    1996-97 through the latest one (the season containing ``today``) is considered: the latest is
    refetched every run, and a completed older season is skipped.
    """
    if seasons is None:
        seasons = _all_seasons(today or date.today())
        refetch = {seasons[-1]}
    else:
        refetch = set(seasons)
    report = Report(store.new_log_path())
    with _logging_to(report.log_path):
        for season in seasons:
            for season_type, kind, tables in _game_logs_to_fetch(store, season, season in refetch):
                _fetch_game_log(source, store, report, season, season_type, kind, tables)
        _add_new_players(source, store, report)
        store.write_table(TEAMS, transform.teams(static_teams.get_teams()))
        store.publish()
    return report


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


def _game_logs_to_fetch(store, season, refetch_complete):
    """The game logs of ``season`` with failed or missing items, as ``(season_type, kind, tables)``.

    ``tables`` lists only the ``(table, transform)`` pairs to write. A season with every item
    succeeded is fetched in full if ``refetch_complete``, otherwise skipped.
    """
    season_types = _season_types(season)
    all_items = {(table, season_type) for season_type in season_types for tables in TABLES.values() for table, _ in tables}
    to_fetch = all_items - store.succeeded_items(season) or (all_items if refetch_complete else set())
    game_logs = []
    for season_type in season_types:
        for kind, tables in TABLES.items():
            tables = [(table, to_table) for table, to_table in tables if (table, season_type) in to_fetch]
            if tables:
                game_logs.append((season_type, kind, tables))
    return game_logs


def _season_types(season):
    """The season types ``season`` has: Play-In only from 2019-20 on."""
    return [t for t in SEASON_TYPES if t != PLAY_IN or season >= FIRST_PLAY_IN_SEASON]


def _fetch_game_log(source, store, report, season, season_type, kind, tables):
    """Fetch one game log and write each of its tables, recording each as an item."""
    try:
        raw = source.game_log(season, season_type, kind)
    except Exception as e:
        for table, _ in tables:
            _fail(store, report, table, season, season_type, e)
        return
    for table, to_table in tables:
        try:
            df = to_table(raw, season, season_type)
            store.write_partition(table, season, season_type, df)
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
    stored_ids = set(stored["player_id"]) if stored is not None else set()
    new_ids = sorted(store.distinct_values(PLAYER_BOX_SCORES, "player_id") - stored_ids)
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
