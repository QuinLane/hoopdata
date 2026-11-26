import argparse
import os
import sys

from hoopdata.ingest import ingest
from hoopdata.source import NbaApiSource
from hoopdata.store import Store

DEFAULT_DATA_ROOT = "data"


def main(argv=None, source=None):
    parser = argparse.ArgumentParser(prog="hoopdata")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_parser = commands.add_parser("ingest", help="fetch NBA stats and publish hoopdata.duckdb")
    ingest_parser.add_argument("--season", required=True, help="season to fetch, like 2023-24")
    ingest_parser.add_argument(
        "--data-root",
        help=f"where data is written (default: $NBA_DATA_ROOT, then ./{DEFAULT_DATA_ROOT})",
    )
    args = parser.parse_args(argv)

    data_root = args.data_root or os.environ.get("NBA_DATA_ROOT") or DEFAULT_DATA_ROOT
    report = ingest(source or NbaApiSource(), Store(data_root), seasons=[args.season])
    for item in report.items:
        outcome = f"FAILED ({item.error})" if item.error else f"{item.rows} rows"
        print(f"{item.table} {item.season} {item.season_type}: {outcome}")
    print(f"{len(report.failed)} of {len(report.items)} items failed. Log: {report.log_path}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
