# The data root remembers its selection

Each data root saves its selection: which datasets it holds and which seasons (all, including future ones, or a fixed list). Every dataset holds the same seasons, so tables always line up: adding a season adds it to every dataset, and adding a dataset fills in every season already held. `ingest` with `--datasets` or a season flag adds to the selection. Plain `ingest`, which the nightly job runs, keeps exactly the selection current and never fetches anything outside it. We rejected passing the choice as flags on every run, because the nightly job and the user's first command would drift apart. Data would quietly stop updating, or an 11-hour play-by-play backfill would start without being asked for. A dataset outside the selection is missing from `hoopdata.duckdb`, not empty, so a query against it fails loudly instead of returning wrong numbers. `hoopdata_datasets` lists what is loaded.

## Consequences

- The nightly job runs plain `hoopdata ingest`, not `--all-seasons`.
- A fixed season list never grows on its own: someone who chose only `2024-25` gets no new seasons.
- There is no remove command. Deleting a dataset's folder and running `ingest` again updates the selection from what's on disk.
