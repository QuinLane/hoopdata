import argparse
import os
import sys

from hoopdata.ingest import EmptySelectionError, ingest
from hoopdata.source import NbaApiSource
from hoopdata.store import ALL_SEASONS, Store

DEFAULT_DATA_ROOT = "data"


def main(argv=None, source=None):
    parser = argparse.ArgumentParser(prog="hoopdata")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_parser = commands.add_parser("ingest", help="fetch NBA stats and publish hoopdata.duckdb")
    seasons = ingest_parser.add_mutually_exclusive_group()
    seasons.add_argument("--season", help="add one season, like 2023-24, to the data root's selection")
    seasons.add_argument(
        "--all-seasons",
        action="store_true",
        help="widen the data root's selection to every season from 1996-97 on, including future ones",
    )
    ingest_parser.add_argument(
        "--data-root",
        help=f"where data is written (default: $NBA_DATA_ROOT, then ./{DEFAULT_DATA_ROOT})",
    )
    args = parser.parse_args(argv)

    data_root = args.data_root or os.environ.get("NBA_DATA_ROOT") or DEFAULT_DATA_ROOT
    seasons = [args.season] if args.season else ALL_SEASONS if args.all_seasons else None
    try:
        report = ingest(source or NbaApiSource(), Store(data_root), seasons=seasons)
    except EmptySelectionError as e:
        print(e, file=sys.stderr)
        return 2
    for item in report.items:
        outcome = f"FAILED ({item.error})" if item.error else f"{item.rows} rows"
        print(f"{item.name}: {outcome}")
    print(f"{len(report.failed)} of {len(report.items)} items failed. Log: {report.log_path}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
