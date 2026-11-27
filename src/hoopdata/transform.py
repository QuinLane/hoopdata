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

# NBA's official advanced rates, stored as given (ADR 0001). poss is a count, the rest are rates.
ADVANCED_STAT_COLUMNS = [
    "off_rating", "def_rating", "net_rating", "ast_pct", "ast_to", "ast_ratio", "oreb_pct", "dreb_pct",
    "reb_pct", "tm_tov_pct", "efg_pct", "ts_pct", "usg_pct", "pace", "pace_per40", "poss", "pie",
]

PLAYER_ADVANCED_BOX_SCORE_COLUMNS = ["season", "season_type", "game_id", "player_id", "team_id", *ADVANCED_STAT_COLUMNS]

# NBA gives no usg_pct for teams.
TEAM_ADVANCED_BOX_SCORE_COLUMNS = [
    "season", "season_type", "game_id", "team_id", *[column for column in ADVANCED_STAT_COLUMNS if column != "usg_pct"],
]

ADVANCED_BOX_SCORE_TYPES = {
    **dict.fromkeys(["season", "season_type", "game_id"], "string"),
    **dict.fromkeys(["player_id", "team_id", "poss"], "Int64"),
    **dict.fromkeys([column for column in ADVANCED_STAT_COLUMNS if column != "poss"], "Float64"),
}

# One row per field-goal attempt: the keys, then the kept columns as given.
SHOT_COLUMNS = [
    "season", "season_type", "game_id", "game_event_id", "player_id", "team_id",
    "period", "minutes_remaining", "seconds_remaining", "action_type", "shot_type",
    "shot_zone_basic", "shot_zone_area", "shot_zone_range", "shot_distance", "loc_x", "loc_y", "shot_made_flag",
]

SHOT_TYPES = {
    **dict.fromkeys(
        ["season", "season_type", "game_id", "action_type", "shot_type", "shot_zone_basic", "shot_zone_area",
         "shot_zone_range"],
        "string",
    ),
    **dict.fromkeys(
        ["game_event_id", "player_id", "team_id", "period", "minutes_remaining", "seconds_remaining",
         "shot_distance", "loc_x", "loc_y", "shot_made_flag"],
        "Int64",
    ),
}

# The official roster's source columns stored under another name. The rest keep theirs.
OFFICIAL_ROSTER_COLUMNS = {
    "teamid": "team_id",
    "player": "player_name",
    "num": "jersey_number",
    "exp": "experience",
}

OFFICIAL_ROSTER_TYPES = {
    "season": "string",
    "team_id": "Int64",
    "player_id": "Int64",
    **dict.fromkeys(["player_name", "jersey_number", "position", "experience", "how_acquired"], "string"),
}

# One row per play-by-play action, with each kept column's type. The source's camelCase names become snake_case.
PLAY_BY_PLAY_TYPES = {
    "game_id": "string",
    **dict.fromkeys(["action_id", "action_number", "period"], "Int64"),
    "clock": "string",
    **dict.fromkeys(["team_id", "person_id"], "Int64"),
    **dict.fromkeys(["action_type", "sub_type", "description"], "string"),
    **dict.fromkeys(["is_field_goal", "shot_value"], "Int64"),
    "shot_result": "string",
    **dict.fromkeys(["shot_distance", "x_legacy", "y_legacy"], "Int64"),
    "location": "string",
    **dict.fromkeys(["score_home", "score_away"], "Int32"),
    "points_total": "Int64",
}

# Team IDs all start with these digits, like 1610612743. No player ID does.
TEAM_ID_PREFIX = 1610612

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


def player_advanced_box_scores(raw, season, season_type):
    """The keys and official rates of an advanced player game log, values as given."""
    return _advanced_box_scores(_result_set(raw), season, season_type, PLAYER_ADVANCED_BOX_SCORE_COLUMNS)


def team_advanced_box_scores(raw, season, season_type):
    """The keys and official rates of an advanced team game log, values as given."""
    return _advanced_box_scores(_result_set(raw), season, season_type, TEAM_ADVANCED_BOX_SCORE_COLUMNS)


def _advanced_box_scores(df, season, season_type, columns):
    df["season"] = season
    df["season_type"] = season_type
    return df[columns].astype({column: ADVANCED_BOX_SCORE_TYPES[column] for column in columns})


def shots(raws, season, season_type):
    """Every field-goal attempt in the teams' shot charts ``raws``, keys plus the kept columns, values as given."""
    df = pd.concat([_result_set(raw) for raw in raws], ignore_index=True)
    df["season"] = season
    df["season_type"] = season_type
    return df[SHOT_COLUMNS].astype(SHOT_TYPES)


def official_rosters(raws, season, season_type):
    """Every player on the teams' rosters ``raws``, the kept columns as given. ``season_type`` is always ``None``."""
    df = pd.concat([_result_set(raw) for raw in raws], ignore_index=True).rename(columns=OFFICIAL_ROSTER_COLUMNS)
    df["season"] = season
    return df[list(OFFICIAL_ROSTER_TYPES)].astype(OFFICIAL_ROSTER_TYPES)


def play_by_play(raw):
    """One game's actions, the kept columns as given and ordered by ``action_id``. Blank scores are NULL.

    Team-level actions (team rebounds, timeouts, team turnovers) come with the team ID in
    ``personId`` and 0 in ``teamId``. They're stored with it in ``team_id`` and ``person_id`` NULL.
    """
    df = pd.DataFrame(raw["game"]["actions"])
    df.columns = df.columns.str.replace(r"([A-Z])", r"_\1", regex=True).str.lower()
    df["game_id"] = raw["game"]["gameId"]
    team_level = df["person_id"] // 10**3 == TEAM_ID_PREFIX
    df.loc[team_level, "team_id"] = df.loc[team_level, "person_id"]
    df.loc[team_level, "person_id"] = None
    df[["score_home", "score_away"]] = df[["score_home", "score_away"]].replace("", None)
    return df[list(PLAY_BY_PLAY_TYPES)].astype(PLAY_BY_PLAY_TYPES).sort_values("action_id", ignore_index=True)


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
    df = df[PLAYER_COLUMNS].replace({"": None, " ": None, "Undrafted": None})

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
