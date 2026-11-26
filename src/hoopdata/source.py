"""The only seam to the outside world: fetching raw NBA stats.

Every call returns the raw response dict from stats.nba.com
(``{"resultSets": [{"name", "headers", "rowSet"}, ...]}``).
"""

import json
import time
from pathlib import Path

REGULAR_SEASON = "Regular Season"
PLAYOFFS = "Playoffs"
SEASON_TYPES = [REGULAR_SEASON, PLAYOFFS]

PLAYER = "player"
TEAM = "team"


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
    """Test adapter: serves responses recorded by ``record_game_log``."""

    def __init__(self, fixtures_dir):
        self.fixtures_dir = Path(fixtures_dir)

    def game_log(self, season, season_type, kind):
        path = self.fixtures_dir / _game_log_name(season, season_type, kind)
        return json.loads(path.read_text(encoding="utf-8"))


def record_game_log(source, fixtures_dir, season, season_type, kind):
    """Fetch one game log with ``source`` and save it as a replay fixture."""
    response = source.game_log(season, season_type, kind)
    path = Path(fixtures_dir) / _game_log_name(season, season_type, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response), encoding="utf-8")
    return path


def _game_log_name(season, season_type, kind):
    return f"game_log_{kind}_{season}_{season_type.replace(' ', '_').lower()}.json"
