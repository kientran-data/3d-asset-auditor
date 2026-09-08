"""CLI entry point for 3D Asset Auditor."""
import argparse
import logging
import os
import sys

from .catalog.database import Database
from .catalog.repository import AssetRepository
from .scanner.scanner import Scanner
from .exporters.csv_exporter import export_to_csv
from .exporters.json_exporter import export_to_json

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def main():
    parser = argparse.ArgumentParser(
        prog="asset_auditor",
        description="3D Asset Auditor — Local inventory scanner for 3D asset libraries.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    scan_parser = subparsers.add_parser("scan", help="Scan a directory for 3D assets")
    scan_parser.add_argument("path", help="Path to the 3D asset library")
    scan_parser.add_argument(
        "--db", default="reports/catalog.db", help="Path to SQLite database"
    )
    scan_parser.add_argument(
        "--csv", default="reports/inventory.csv", help="Path to output CSV"
    )
    scan_parser.add_argument(
        "--json", default="reports/inventory.json", help="Path to output JSON"
    )
    scan_parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose/debug logging"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    setup_logging(args.verbose)

    if args.command == "scan":
        _run_scan(args)


def _run_scan(args):
    source_root = os.path.abspath(args.path)

    if not os.path.isdir(source_root):
        print(f"Error: '{source_root}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    # Ensure output directories exist
    for path in (args.db, args.csv, args.json):
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)

    db = Database(args.db)
    with db.get_connection() as conn:
        repo = AssetRepository(conn)
        scanner = Scanner(source_root, repo)

        conn.execute("BEGIN")
        stats = scanner.scan()
        conn.execute("COMMIT")

        # Export only present assets
        present_assets = list(repo.get_all_assets(source_root, present_only=True))
        export_to_csv(present_assets, args.csv)
        export_to_json(present_assets, source_root, stats, args.json)

    _print_summary(source_root, stats, args)


def _print_summary(source_root: str, stats: dict, args):
    print("\n3D Asset Auditor — Inventory Complete\n")
    print("Source:")
    print(f"  {source_root}\n")
    print("Filesystem:")
    print(f"  Directories visited: {stats['dirs_visited']}")
    print(f"  Files encountered: {stats['files_encountered']}")
    print(f"  Non-3D files: {stats['non_3d_files']}")
    print(f"  Filesystem errors: {stats['errors']}\n")
    print("3D assets:")
    print(f"  Total: {stats['total_3d_assets']}")
    print(f"  Total size: {stats['total_size_bytes'] / (1024 * 1024):.1f} MB\n")
    print("Formats:")
    for fmt, count in sorted(stats["formats"].items()):
        print(f"  {fmt}: {count}")
    print("\nAnalysis capability:")
    for cap, count in stats["capabilities"].items():
        print(f"  {cap}: {count}")
    print("\nChanges:")
    print(f"  New: {stats['new']}")
    print(f"  Changed: {stats['changed']}")
    print(f"  Unchanged: {stats['unchanged']}")
    print(f"  Missing: {stats['missing']}\n")
    print("Outputs:")
    print(f"  SQLite: {args.db}")
    print(f"  CSV: {args.csv}")
    print(f"  JSON: {args.json}\n")
