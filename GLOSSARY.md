# hoopdata

A local pipeline that keeps NBA stats fetched, cleaned and current, published as one store any project can query.

## Language

### Seasons and games

**Season**:
One NBA year, named by its two calendar years, like `2024-25`.
_Avoid_: year

**Season type**:
The part of a season a game belongs to: `Regular Season`, `PlayIn` or `Playoffs`.
_Avoid_: game type, phase

**Play-In**:
The short tournament between the regular season and the playoffs that decides the last playoff seeds. It is its own season type, and its games count toward neither the regular season nor the playoffs. It began in 2019-20 with the one bubble game, which NBA labels Play-In.
_Avoid_: play-in round, pre-playoffs

### Data sources

**Box score**:
The official counting stats for one player or one team in one game.
_Avoid_: stat line, game log row

**Advanced box score**:
NBA's official advanced stats for one player or one team in one game.
_Avoid_: advanced game log, advanced stat line

**Official advanced stats**:
NBA's own rate and estimate stats for a game, like possessions, pace and offensive, defensive and net rating. They are the only source of these numbers; hoopdata never recomputes them.
_Avoid_: derived ratings, calculated advanced stats

**Shot**:
One field-goal attempt, with where and how it was taken. Free throws aren't shots.
_Avoid_: shot chart row, attempt

**Play-by-play**:
NBA's ordered record of every event in one game: shots, rebounds, fouls, substitutions and so on.
_Avoid_: PBP (in docs), event log

**Roster**:
The players who appeared in a game for a team in one season and season type. A player traded mid-season is on both teams' rosters.
_Avoid_: squad, lineup

**Official roster**:
NBA's own list of a team's players for one season, as NBA last reported it: usually the end-of-season roster for past seasons, and as of the latest update for the current one. It includes players who never appeared, but leaves out anyone who left the team before that report.
_Avoid_: roster (on its own), team list

**Coach**:
A head or assistant coach on a team's staff for one season, as NBA last reported it. Trainers and other support staff aren't coaches.
_Avoid_: staff, coaching staff

**Reconciliation**:
The check that summing a game's play-by-play reproduces each team's box score in that game. A mismatch is reported, never blocks an update, and shows the play-by-play quality for each era.
_Avoid_: validation, audit

**Action**:
One event in a game's play-by-play, like a shot, rebound, foul or substitution.
_Avoid_: event, play, row

### Pipeline

**Dataset**:
A group of tables and views that come from one source and are loaded or left out together.
_Avoid_: module, feature, source (the code seam), package

**Selection**:
The datasets a data root has been asked to hold, and the seasons they all hold: every season (including future ones) or a fixed list. Every dataset in a data root holds the same seasons. Only an explicit request changes it, and an update with no request keeps exactly the selection current.
_Avoid_: config, subscription, profile, saved choice

**Core**:
The dataset every data root always holds: box scores, games, players and teams, covering every season type. Every other dataset joins to it.
_Avoid_: base, v1 data

**Item**:
One unit of fetching with its own recorded outcome: a table for one season and season type, a table for one season when its source doesn't split by season type, or the players bios as a whole. A play-by-play item is a season and season type that fills in only its missing games: a game already fetched is never fetched again.
_Avoid_: job, task, partition
