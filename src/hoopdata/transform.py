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

# Every box score column's type. game_date becomes a plain date afterwards.
BOX_SCORE_TYPES = {
    **dict.fromkeys(
        ["season", "season_type", "game_id", "player_name", "team_abbreviation", "team_name", "wl"], "string"
    ),
    "game_date": "datetime64[ns]",
    **dict.fromkeys(["player_id", "team_id", *STAT_COLUMNS], "Int64"),
}

PLAYER_COLUMNS = [
    "player_id", "first_name", "last_name", "display_name", "birthdate",
    "height_in", "weight_lb", "position", "country", "school",
    "draft_year", "draft_round", "draft_number", "from_year", "to_year",
]


def player_box_scores(raw, season, season_type):
    return _box_scores(_result_set(raw), season, season_type, PLAYER_BOX_SCORE_COLUMNS)


def team_box_scores(raw, season, season_type):
    return _box_scores(_result_set(raw), season, season_type, TEAM_BOX_SCORE_COLUMNS)


def games(raw, season, season_type):
    """One row per game from the team game log: ``vs.`` in the matchup means home, ``@`` away.

    At a neutral site both matchups read ``@``. That game is flagged ``neutral_site``, and its
    home and away only put the two teams in order: the lower team ID is home.
    """
    df = _result_set(raw).sort_values("team_id")
    df["listed_home"] = df["matchup"].str.contains(" vs. ", regex=False)
    df["neutral_site"] = ~df.groupby("game_id")["listed_home"].transform("any")
    is_home = df["listed_home"] | (df["neutral_site"] & ~df.duplicated("game_id"))
    df = df[is_home].merge(df[~is_home], on="game_id", suffixes=("_home", "_away"))
    return pd.DataFrame({
        "season": pd.Series(season, index=df.index, dtype="string"),
        "season_type": pd.Series(season_type, index=df.index, dtype="string"),
        "game_id": df["game_id"].astype("string"),
        "neutral_site": df["neutral_site_home"].astype("boolean"),
        "game_date": pd.to_datetime(df["game_date_home"]).dt.date,
        "home_team_id": df["team_id_home"].astype("Int64"),
        "away_team_id": df["team_id_away"].astype("Int64"),
        "home_pts": df["pts_home"].astype("Int64"),
        "away_pts": df["pts_away"].astype("Int64"),
    })


def _box_scores(df, season, season_type, columns):
    df["season"] = season
    df["season_type"] = season_type
    df = df[columns].astype({column: BOX_SCORE_TYPES[column] for column in columns})
    df["game_date"] = df["game_date"].dt.date
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


def teams(team_list):
    """Current team identities from nba_api's bundled static team list."""
    df = pd.DataFrame(team_list).rename(columns={"id": "team_id"})
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
