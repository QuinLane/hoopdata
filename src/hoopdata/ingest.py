from dataclasses import dataclass, field

import pandas as pd
from nba_api.stats.static import teams as static_teams

from hoopdata import transform
from hoopdata.source import PLAYER, SEASON_TYPES
from hoopdata.store import SUCCEEDED

PLAYER_BOX_SCORES = "player_box_scores"
PLAYERS = "players"
TEAMS = "teams"


@dataclass
class Item:
    table: str
    season: str
    season_type: str
    rows: int


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)


def ingest(source, store, seasons):
    """Fetch each season's player box scores, bios for new players and the team list, and publish the views."""
    report = Report()
    player_ids = set()
    for season in seasons:
        for season_type in SEASON_TYPES:
            raw = source.game_log(season, season_type, PLAYER)
            df = transform.player_box_scores(raw, season, season_type)
            store.write_partition(PLAYER_BOX_SCORES, season, season_type, df)
            store.record_item(PLAYER_BOX_SCORES, season, season_type, SUCCEEDED, rows=len(df))
            report.items.append(Item(PLAYER_BOX_SCORES, season, season_type, len(df)))
            player_ids.update(df["player_id"])
    _add_new_players(source, store, player_ids)
    store.write_table(TEAMS, transform.teams(static_teams.get_teams()))
    store.publish()
    return report


def _add_new_players(source, store, player_ids):
    """Fetch bios only for players not yet stored. Existing bios are never refreshed."""
    stored = store.read_table(PLAYERS)
    new_ids = sorted(player_ids - set(stored["player_id"] if stored is not None else []))
    if not new_ids:
        return
    infos = [source.player_info(player_id) for player_id in new_ids]
    new = transform.players(source.all_players(), infos)
    store.write_table(PLAYERS, pd.concat([stored, new]) if stored is not None else new)
