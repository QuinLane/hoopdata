from dataclasses import dataclass, field

from hoopdata import transform
from hoopdata.source import PLAYER, SEASON_TYPES

PLAYER_BOX_SCORES = "player_box_scores"


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
    """Fetch each season's player box scores, store them, and publish the views."""
    report = Report()
    for season in seasons:
        for season_type in SEASON_TYPES:
            raw = source.game_log(season, season_type, PLAYER)
            df = transform.player_box_scores(raw, season, season_type)
            store.write_partition(PLAYER_BOX_SCORES, season, season_type, df)
            report.items.append(Item(PLAYER_BOX_SCORES, season, season_type, len(df)))
    store.publish()
    return report
