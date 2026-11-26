"""Turn raw stats.nba.com responses into normalized, exactly typed tables."""

import pandas as pd

STAT_COLUMNS = [
    "min", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta",
    "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pf", "pts", "plus_minus",
]

PLAYER_BOX_SCORE_COLUMNS = [
    "season", "season_type", "game_id", "game_date",
    "player_id", "player_name", "team_id", "team_abbreviation", "team_name",
    "wl", *STAT_COLUMNS,
]


def player_box_scores(raw, season, season_type):
    df = _result_set(raw)
    df["season"] = season
    df["season_type"] = season_type
    df = df[PLAYER_BOX_SCORE_COLUMNS]

    for column in ["season", "season_type", "game_id", "player_name",
                   "team_abbreviation", "team_name", "wl"]:
        df[column] = df[column].astype("string")
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    for column in ["player_id", "team_id", *STAT_COLUMNS]:
        df[column] = df[column].astype("Int64")
    return df


def _result_set(raw):
    result = raw["resultSets"][0]
    df = pd.DataFrame(result["rowSet"], columns=result["headers"])
    df.columns = df.columns.str.lower()
    return df
