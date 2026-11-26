from dataclasses import dataclass, field

from hoopdata import transform
from hoopdata.source import PLAYER, SEASON_TYPES, TEAM

PLAYER_BOX_SCORES = "player_box_scores"
TEAM_BOX_SCORES = "team_box_scores"
GAMES = "games"


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
    """Fetch each season's player and team box scores, store them, and publish the views."""
    report = Report()
    for season in seasons:
        for season_type in SEASON_TYPES:
            players = transform.player_box_scores(source.game_log(season, season_type, PLAYER), season, season_type)
            store.write_partition(PLAYER_BOX_SCORES, season, season_type, players)
            report.items.append(Item(PLAYER_BOX_SCORES, season, season_type, len(players)))

            team_log = source.game_log(season, season_type, TEAM)
            teams = transform.team_box_scores(team_log, season, season_type)
            store.write_partition(TEAM_BOX_SCORES, season, season_type, teams)
            report.items.append(Item(TEAM_BOX_SCORES, season, season_type, len(teams)))

            games = transform.games(team_log, season, season_type)
            store.write_partition(GAMES, season, season_type, games)
            report.items.append(Item(GAMES, season, season_type, len(games)))
    store.publish()
    return report
