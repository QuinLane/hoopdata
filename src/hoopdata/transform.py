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


TEAM_BOX_SCORE_COLUMNS = [
    column for column in PLAYER_BOX_SCORE_COLUMNS if column not in ("player_id", "player_name")
]


def player_box_scores(raw, season, season_type):
    return _box_scores(_result_set(raw), season, season_type, PLAYER_BOX_SCORE_COLUMNS)


def team_box_scores(raw, season, season_type):
    return _box_scores(_result_set(raw), season, season_type, TEAM_BOX_SCORE_COLUMNS)


def games(raw, season, season_type):
    """One row per game from the team game log: ``vs.`` in the matchup means home, ``@`` away."""
    df = _result_set(raw)
    home = df[df["matchup"].str.contains(" vs. ", regex=False)]
    away = df[df["matchup"].str.contains(" @ ", regex=False)]
    df = home.merge(away, on="game_id", suffixes=("_home", "_away"))
    return pd.DataFrame({
        "season": pd.Series(season, index=df.index, dtype="string"),
        "season_type": pd.Series(season_type, index=df.index, dtype="string"),
        "game_id": df["game_id"].astype("string"),
        "game_date": pd.to_datetime(df["game_date_home"]).dt.date,
        "home_team_id": df["team_id_home"].astype("Int64"),
        "away_team_id": df["team_id_away"].astype("Int64"),
        "home_pts": df["pts_home"].astype("Int64"),
        "away_pts": df["pts_away"].astype("Int64"),
    })


def _box_scores(df, season, season_type, columns):
    df["season"] = season
    df["season_type"] = season_type
    df = df[columns]

    for column in ["season", "season_type", "game_id", "player_name",
                   "team_abbreviation", "team_name", "wl"]:
        if column in columns:
            df[column] = df[column].astype("string")
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    for column in ["player_id", "team_id", *STAT_COLUMNS]:
        if column in columns:
            df[column] = df[column].astype("Int64")
    return df


def _result_set(raw):
    result = raw["resultSets"][0]
    df = pd.DataFrame(result["rowSet"], columns=result["headers"])
    df.columns = df.columns.str.lower()
    return df
