# Play-by-play keeps the games it has fetched

Every other dataset refetches the latest season on every run, which keeps it current when NBA corrects a recent game. Play-by-play doesn't: once a game's play-by-play is stored, no run fetches it again, and the nightly job only fetches the latest season's games that core holds and play-by-play doesn't yet. Refetching the whole latest season would cost ~1,230 requests (~20 min) by the end of a season, every night, to catch corrections that are rare. The cost is that a later NBA correction to a game's play-by-play is missed. Reconciliation shows those games as mismatches, and they're redone the documented way: delete the folder and run `ingest`.

## Consequences

- A play-by-play item is a season × season type that fills in its missing games. A failed item keeps the games it fetched, and the next run fetches only the rest.
- Each game is stored in its own file, so "already held" means the file exists.
- The nightly cost in season is the day's new games, ~5–15 requests.
