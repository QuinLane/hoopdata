# Ingest test 001

Then check:
- every item says "rows" and the exit code is 0
- `examples/python` works with `PYTHONIOENCODING=utf-8` set
- running it again doesn't refetch bios
- the log file is clean

After that, run `--season 2026-27` to check the empty-playoffs case against real data. Then do the full `--all-seasons` backfill (about 45 minutes, mostly bios) and register the nightly job.

## The plan right now

There's no open issue, so nothing is officially next. Suggested order:

1. Do the 2024-25 smoke run.
2. Fix empty-playoffs if it breaks, test-first with an empty fixture.
3. Add backfill steps to the README.
4. Run the full backfill and register the nightly job.
