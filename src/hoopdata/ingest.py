from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from nba_api.stats.static import teams as static_teams

from hoopdata import transform
from hoopdata.source import PLAYER, SEASON_TYPES, TEAM
from hoopdata.store import SUCCEEDED

PLAYER_BOX_SCORES = "player_box_scores"
TEAM_BOX_SCORES = "team_box_scores"
GAMES = "games"
PLAYERS = "players"
TEAMS = "teams"

FIRST_SEASON_START_YEAR = 1996


@dataclass
class Item:
    table: str
    season: str
    season_type: str
    rows: int


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)


def ingest(source, store, seasons=None, today=None):
    """Fetch each season's player and team box scores, bios for new players and the team list, and publish the views.

    Passing ``seasons`` forces a refetch of exactly those seasons. With no ``seasons``, the refresh
    policy picks from 1996-97 through the latest season: the latest one (the season containing
    ``today``) every run, older ones only if any of their items is missing or didn't succeed.
    """
    if seasons is None:
        seasons = _seasons_to_refresh(store, today or date.today())
    report = Report()
    player_ids = set()
    for season in seasons:
        for season_type in SEASON_TYPES:
            players = transform.player_box_scores(source.game_log(season, season_type, PLAYER), season, season_type)
            store.write_partition(PLAYER_BOX_SCORES, season, season_type, players)
            store.record_item(PLAYER_BOX_SCORES, season, season_type, SUCCEEDED, rows=len(players))
            report.items.append(Item(PLAYER_BOX_SCORES, season, season_type, len(players)))
            player_ids.update(players["player_id"])

            team_log = source.game_log(season, season_type, TEAM)
            teams = transform.team_box_scores(team_log, season, season_type)
            store.write_partition(TEAM_BOX_SCORES, season, season_type, teams)
            store.record_item(TEAM_BOX_SCORES, season, season_type, SUCCEEDED, rows=len(teams))
            report.items.append(Item(TEAM_BOX_SCORES, season, season_type, len(teams)))

            games = transform.games(team_log, season, season_type)
            store.write_partition(GAMES, season, season_type, games)
            store.record_item(GAMES, season, season_type, SUCCEEDED, rows=len(games))
            report.items.append(Item(GAMES, season, season_type, len(games)))
    _add_new_players(source, store, player_ids)
    store.write_table(TEAMS, transform.teams(static_teams.get_teams()))
    store.publish()
    return report


def _seasons_to_refresh(store, today):
    """The latest season, plus every older season with an item that is missing or didn't succeed."""
    succeeded = {
        (i["table"], i["season"], i["season_type"])
        for i in store.read_manifest()["items"]
        if i["status"] == SUCCEEDED
    }

    def complete(season):
        return all(
            (table, season, season_type) in succeeded
            for table in (PLAYER_BOX_SCORES, TEAM_BOX_SCORES, GAMES)
            for season_type in SEASON_TYPES
        )

    *older, latest = _all_seasons(today)
    return [season for season in older if not complete(season)] + [latest]


def _all_seasons(today):
    """Every season from 1996-97 through the latest one, like ``["1996-97", ..., "2024-25"]``."""
    return [_season(year) for year in range(FIRST_SEASON_START_YEAR, _latest_season_start_year(today) + 1)]


def _latest_season_start_year(today):
    """Seasons start in October, so before October the latest season is the one that started last year."""
    return today.year if today.month >= 10 else today.year - 1


def _season(start_year):
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _add_new_players(source, store, player_ids):
    """Fetch bios only for players not yet stored. Existing bios are never refreshed."""
    stored = store.read_table(PLAYERS)
    new_ids = sorted(player_ids - set(stored["player_id"] if stored is not None else []))
    if not new_ids:
        return
    infos = [source.player_info(player_id) for player_id in new_ids]
    new = transform.players(source.all_players(), infos)
    store.write_table(PLAYERS, pd.concat([stored, new]) if stored is not None else new)
