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

PLAYER_COLUMNS = [
    "player_id", "first_name", "last_name", "display_name", "birthdate",
    "height_in", "weight_lb", "position", "country", "school",
    "draft_year", "draft_round", "draft_number", "from_year", "to_year",
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


def players(all_players, player_infos):
    """Join new players' rows from the all-players list with their player info."""
    listed = _result_set(all_players)[["person_id", "display_first_last", "from_year", "to_year"]]
    info = pd.concat([_result_set(raw) for raw in player_infos], ignore_index=True)
    info = info.drop(columns=["display_first_last", "from_year", "to_year"])
    df = info.merge(listed, on="person_id")
    df = df.rename(columns={
        "person_id": "player_id", "display_first_last": "display_name",
        "height": "height_in", "weight": "weight_lb",
    })
    df = df[PLAYER_COLUMNS].replace({"": None, "Undrafted": None})

    for column in ["first_name", "last_name", "display_name", "position", "country", "school"]:
        df[column] = df[column].astype("string")
    df["birthdate"] = pd.to_datetime(df["birthdate"]).dt.date
    df["height_in"] = df["height_in"].map(_feet_inches_to_inches, na_action="ignore")
    for column in ["player_id", "height_in", "weight_lb", "draft_year", "draft_round",
                   "draft_number", "from_year", "to_year"]:
        df[column] = pd.to_numeric(df[column]).astype("Int64")
    return df


def teams(static_teams):
    """Current team identities from nba_api's bundled static team list."""
    df = pd.DataFrame(static_teams).rename(columns={"id": "team_id"})
    df = df[["team_id", "abbreviation", "city", "nickname", "full_name", "year_founded"]]
    for column in ["abbreviation", "city", "nickname", "full_name"]:
        df[column] = df[column].astype("string")
    for column in ["team_id", "year_founded"]:
        df[column] = df[column].astype("Int64")
    return df


def _feet_inches_to_inches(height):
    feet, inches = height.split("-")
    return int(feet) * 12 + int(inches)


def _result_set(raw):
    result = raw["resultSets"][0]
    df = pd.DataFrame(result["rowSet"], columns=result["headers"])
    df.columns = df.columns.str.lower()
    return df
