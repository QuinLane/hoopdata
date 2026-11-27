"""The only seam to the outside world: fetching raw NBA stats.

Every call returns the raw response dict from stats.nba.com
(``{"resultSets": [{"name", "headers", "rowSet"}, ...]}``).
"""

import json
import time
from pathlib import Path

REGULAR_SEASON = "Regular Season"
PLAY_IN = "PlayIn"
PLAYOFFS = "Playoffs"
SEASON_TYPES = [REGULAR_SEASON, PLAY_IN, PLAYOFFS]

PLAYER = "player"
TEAM = "team"

ALL_PLAYERS_FILE = "all_players.json"
PLAYER_INFO_FILE = "player_info.json"


class NbaApiSource:
    """Real adapter: calls stats.nba.com via nba_api, paced and retried."""

    def __init__(self, pace_seconds=1.0, retries=3, backoff_seconds=2.0, timeout=30):
        self.pace_seconds = pace_seconds
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.timeout = timeout
        self._last_request = 0.0

    def game_log(self, season, season_type, kind):
        from nba_api.stats.endpoints import leaguegamelog

        return self._request(
            lambda: leaguegamelog.LeagueGameLog(
                season=season,
                season_type_all_star=season_type,
                player_or_team_abbreviation="P" if kind == PLAYER else "T",
                timeout=self.timeout,
            )
        )

    def player_advanced_game_log(self, season, season_type):
        from nba_api.stats.endpoints import playergamelogs

        return self._request(
            lambda: playergamelogs.PlayerGameLogs(
                season_nullable=season,
                season_type_nullable=season_type,
                measure_type_player_game_logs_nullable="Advanced",
                timeout=self.timeout,
            )
        )

    def all_players(self):
        from nba_api.stats.endpoints import commonallplayers

        return self._request(lambda: commonallplayers.CommonAllPlayers(timeout=self.timeout))

    def player_info(self, player_id):
        from nba_api.stats.endpoints import commonplayerinfo

        return self._request(
            lambda: commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=self.timeout)
        )

    def _request(self, make_endpoint):
        for attempt in range(self.retries + 1):
            wait = self.pace_seconds - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                return make_endpoint().get_dict()
            except Exception:
                if attempt == self.retries:
                    raise
                time.sleep(self.backoff_seconds * 2**attempt)


class ReplaySource:
    """Test adapter: serves responses recorded by the ``record_*`` functions."""

    def __init__(self, fixtures_dir):
        self.fixtures_dir = Path(fixtures_dir)

    def game_log(self, season, season_type, kind):
        path = self.fixtures_dir / _game_log_name(season, season_type, kind)
        return json.loads(path.read_text(encoding="utf-8"))

    def player_advanced_game_log(self, season, season_type):
        path = self.fixtures_dir / _player_advanced_game_log_name(season, season_type)
        return json.loads(path.read_text(encoding="utf-8"))

    def all_players(self):
        return json.loads((self.fixtures_dir / ALL_PLAYERS_FILE).read_text(encoding="utf-8"))

    def player_info(self, player_id):
        """All recorded player infos live in one file, keyed by player ID."""
        infos = json.loads((self.fixtures_dir / PLAYER_INFO_FILE).read_text(encoding="utf-8"))
        return infos[str(player_id)]


def record_game_log(source, fixtures_dir, season, season_type, kind):
    """Fetch one game log with ``source`` and save it as a replay fixture."""
    response = source.game_log(season, season_type, kind)
    return _save(response, Path(fixtures_dir) / _game_log_name(season, season_type, kind))


def record_player_advanced_game_log(source, fixtures_dir, season, season_type):
    """Fetch one advanced player game log with ``source`` and save it as a replay fixture."""
    response = source.player_advanced_game_log(season, season_type)
    return _save(response, Path(fixtures_dir) / _player_advanced_game_log_name(season, season_type))


def record_all_players(source, fixtures_dir, player_ids):
    """Fetch the all-players list, keep only ``player_ids``, and save it as a replay fixture."""
    response = source.all_players()
    result = response["resultSets"][0]
    person_id = result["headers"].index("PERSON_ID")
    wanted = set(player_ids)
    result["rowSet"] = [row for row in result["rowSet"] if row[person_id] in wanted]
    return _save(response, Path(fixtures_dir) / ALL_PLAYERS_FILE)


def record_player_info(source, fixtures_dir, player_ids):
    """Fetch each player's info and save them together as one replay fixture."""
    infos = {str(player_id): source.player_info(player_id) for player_id in player_ids}
    return _save(infos, Path(fixtures_dir) / PLAYER_INFO_FILE)


def _save(response, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response, indent=1), encoding="utf-8")
    return path


def _game_log_name(season, season_type, kind):
    return f"game_log_{kind}_{season}_{season_type.replace(' ', '_').lower()}.json"


def _player_advanced_game_log_name(season, season_type):
    return f"player_advanced_game_log_{season}_{season_type.replace(' ', '_').lower()}.json"
