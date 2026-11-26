import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
from nba_api.stats.static import teams as static_teams

from hoopdata import transform
from hoopdata.source import PLAYER, SEASON_TYPES, TEAM
from hoopdata.store import FAILED, SUCCEEDED

PLAYER_BOX_SCORES = "player_box_scores"
TEAM_BOX_SCORES = "team_box_scores"
GAMES = "games"
PLAYERS = "players"
TEAMS = "teams"

FIRST_SEASON_START_YEAR = 1996

log = logging.getLogger(__name__)

# Each game log kind feeds these tables, each with its transform.
TABLES = {
    PLAYER: [(PLAYER_BOX_SCORES, transform.player_box_scores)],
    TEAM: [(TEAM_BOX_SCORES, transform.team_box_scores), (GAMES, transform.games)],
}


@dataclass
class Item:
    table: str
    season: str
    season_type: str
    status: str
    rows: int | None = None
    error: str | None = None


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
    A season with failed or missing items is resumed: only those items are fetched again.

    Passing ``seasons`` forces a refetch of those seasons. With no ``seasons``, every season from
    1996-97 through the latest one (the season containing ``today``) is considered: the latest is
    refetched every run, and a completed older season is skipped.
    """
    if seasons is None:
        *older, latest = _all_seasons(today or date.today())
        plan = [(season, False) for season in older] + [(latest, True)]
    else:
        plan = [(season, True) for season in seasons]
    report = Report(store.new_log_path())
    handler = logging.FileHandler(report.log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        _ingest(source, store, plan, report)
    finally:
        log.removeHandler(handler)
        handler.close()
    return report


def _ingest(source, store, plan, report):
    player_ids = set()
    for season, refetch_complete in plan:
        todo = _items_to_fetch(store, season, refetch_complete)
        for season_type in SEASON_TYPES:
            for kind, all_tables in TABLES.items():
                tables = [(table, make) for table, make in all_tables if (table, season_type) in todo]
                if not tables:
                    continue
                try:
                    raw = source.game_log(season, season_type, kind)
                except Exception as e:
                    for table, _ in tables:
                        _fail(store, report, table, season, season_type, e)
                    continue
                for table, make in tables:
                    try:
                        df = make(raw, season, season_type)
                        store.write_partition(table, season, season_type, df)
                    except Exception as e:
                        _fail(store, report, table, season, season_type, e)
                        continue
                    _record(store, report, Item(table, season, season_type, SUCCEEDED, rows=len(df)))
                    log.info("%s %s %s succeeded: %d rows", table, season, season_type, len(df))
                    if table == PLAYER_BOX_SCORES:
                        player_ids.update(df["player_id"])
    _add_new_players(source, store, player_ids)
    store.write_table(TEAMS, transform.teams(static_teams.get_teams()))
    store.publish()


def _items_to_fetch(store, season, refetch_complete):
    """The (table, season_type) items of ``season`` that are failed or missing.

    A season with every item succeeded is fetched in full if ``refetch_complete``, otherwise skipped.
    """
    every = {(table, season_type) for season_type in SEASON_TYPES for tables in TABLES.values() for table, _ in tables}
    succeeded = {
        (i["table"], i["season_type"])
        for i in store.read_manifest()["items"]
        if i["season"] == season and i["status"] == SUCCEEDED
    }
    return every - succeeded or (every if refetch_complete else set())


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


def _fail(store, report, table, season, season_type, error):
    _record(store, report, Item(table, season, season_type, FAILED, error=f"{type(error).__name__}: {error}"))
    log.error("%s %s %s failed", table, season, season_type, exc_info=error)


def _add_new_players(source, store, player_ids):
    """Fetch bios only for players not yet stored. Existing bios are never refreshed."""
    stored = store.read_table(PLAYERS)
    new_ids = sorted(player_ids - set(stored["player_id"] if stored is not None else []))
    if not new_ids:
        return
    infos = [source.player_info(player_id) for player_id in new_ids]
    new = transform.players(source.all_players(), infos)
    store.write_table(PLAYERS, pd.concat([stored, new]) if stored is not None else new)
