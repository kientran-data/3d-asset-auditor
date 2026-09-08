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
        description="3D Asset Auditor — Local inventory scanner and analyzer for 3D asset libraries.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- scan command ---
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

    # --- analyze command ---
    analyze_parser = subparsers.add_parser(
        "analyze", help="Run Blender headless analysis on pending GLB/GLTF assets"
    )
    analyze_parser.add_argument(
        "path", nargs="?", default=None,
        help="Path to the asset library (source_root). If omitted, analyzes all pending assets in the DB."
    )
    analyze_parser.add_argument(
        "--db", default="reports/catalog.db", help="Path to SQLite database"
    )
    analyze_parser.add_argument(
        "--asset-id", default=None, help="Analyze a specific asset by UUID"
    )
    analyze_parser.add_argument(
        "--retry-failed", action="store_true",
        help="Include previously failed/timed-out assets"
    )
    analyze_parser.add_argument(
        "--timeout", type=int, default=None,
        help="Per-asset timeout in seconds (default: 120)"
    )
    analyze_parser.add_argument(
        "--deep", action="store_true", help="Run Phase 3A Deep Material/Texture analysis"
    )
    analyze_parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose/debug logging"
    )

    # --- render command ---
    render_parser = subparsers.add_parser(
        "render", help="Run Phase 3B Thumbnail Rendering on eligible assets"
    )
    render_parser.add_argument(
        "path", nargs="?", default=None,
        help="Path to the asset library (source_root). If omitted, uses DB."
    )
    render_parser.add_argument(
        "--db", default="reports/catalog.db", help="Path to SQLite database"
    )
    render_parser.add_argument(
        "--asset-id", default=None, help="Render a specific asset by UUID"
    )
    render_parser.add_argument(
        "--timeout", type=int, default=None,
        help="Per-asset timeout in seconds (default: 120)"
    )
    render_parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose/debug logging"
    )

    # --- assess command ---
    assess_parser = subparsers.add_parser(
        "assess", help="Run Phase 4A Dry-Plumbing Sell-readiness Assessment"
    )
    assess_parser.add_argument(
        "path", nargs="?", default=None,
        help="Path to the asset library (source_root). If omitted, uses DB."
    )
    assess_parser.add_argument(
        "--db", default="reports/catalog.db", help="Path to SQLite database"
    )
    assess_parser.add_argument(
        "--asset-id", default=None, help="Assess a specific asset by UUID"
    )
    assess_parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose/debug logging"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    setup_logging(args.verbose)

    if args.command == "scan":
        _run_scan(args)
    elif args.command == "analyze":
        _run_analyze(args)
    elif args.command == "render":
        _run_render(args)
    elif args.command == "assess":
        _run_assess(args)


def _run_scan(args):
    source_root = os.path.abspath(args.path)

    if not os.path.isdir(source_root):
        print(f"Error: '{source_root}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

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

        present_assets = list(repo.get_all_assets(source_root, present_only=True))
        export_to_csv(present_assets, args.csv)
        export_to_json(present_assets, source_root, stats, args.json)

    _print_scan_summary(source_root, stats, args)


def _run_analyze(args):
    from .analyzer.dispatcher import run_batch_analysis
    from .config import ANALYSIS_TIMEOUT_SECONDS

    if not os.path.isfile(args.db):
        print(f"Error: Database not found at '{args.db}'. Run 'scan' first.", file=sys.stderr)
        sys.exit(1)

    source_root = os.path.abspath(args.path) if args.path else None
    timeout = args.timeout if args.timeout else ANALYSIS_TIMEOUT_SECONDS

    db = Database(args.db)
    with db.get_connection() as conn:
        stats = run_batch_analysis(
            conn,
            source_root=source_root,
            asset_id=args.asset_id,
            include_failed=args.retry_failed,
            timeout=timeout,
            deep=args.deep,
        )

    print("\n3D Asset Auditor — Analysis Complete\n")
    print(f"  Analysis Profile: {'DEEP' if args.deep else 'BASIC'}")
    print(f"  Total dispatched: {stats['total']}")
    print(f"  Success: {stats['success']}")
    print(f"  Failed import: {stats['failed_import']}")
    print(f"  Failed analysis: {stats['failed_analysis']}")
    print(f"  Timeout: {stats['timeout']}\n")

def _run_render(args):
    from .renderer.dispatcher import run_render, run_batch_render, recover_stale_renders
    from .config import ANALYSIS_TIMEOUT_SECONDS

    if not os.path.isfile(args.db):
        print(f"Error: Database not found at '{args.db}'. Run 'scan' first.", file=sys.stderr)
        sys.exit(1)

    timeout = args.timeout if args.timeout else ANALYSIS_TIMEOUT_SECONDS
    source_root = os.path.abspath(args.path) if args.path else None

    db = Database(args.db)
    with db.get_connection() as conn:
        # If specific asset_id provided:
        if args.asset_id:
            recover_stale_renders(conn)
            row = conn.execute("SELECT absolute_path, source_root FROM assets WHERE asset_id=?", (args.asset_id,)).fetchone()
            if not row:
                print(f"Error: Asset {args.asset_id} not found.")
                sys.exit(1)
            absolute_path, source_root = row
            print(f"Rendering asset {args.asset_id}...")
            run_render(conn, args.asset_id, absolute_path, source_root, timeout)
            print("Render complete.")
        else:
            stats = run_batch_render(
                conn,
                source_root=source_root,
                timeout=timeout
            )
            print("\n3D Asset Auditor — Render Complete\n")
            print(f"  Total dispatched: {stats['total']}")
            print(f"  Success: {stats['success']}")
            print(f"  Failed render: {stats['failed_render']}")
            print(f"  Timeout: {stats['timeout']}\n")

def _run_assess(args):
    from .assessment.dispatcher import run_batch_assessment

    if not os.path.isfile(args.db):
        print(f"Error: Database not found at '{args.db}'. Run 'scan' first.", file=sys.stderr)
        sys.exit(1)

    source_root = os.path.abspath(args.path) if args.path else None

    db = Database(args.db)
    with db.get_connection() as conn:
        print("\n3D Asset Auditor — Sell-readiness Assessment (Phase 4B.2)\n")

        batch_result = run_batch_assessment(
            conn,
            source_root=source_root,
            asset_id=args.asset_id,
        )

        print(f"  Assessment Run: {batch_result['assessment_run_id']}")
        print(f"  Ruleset: {batch_result['ruleset_version']}")
        print(f"  Ruleset Hash: {batch_result['ruleset_hash'][:16]}...")
        print(f"  Assessor: {batch_result['assessor_version']}")
        print()

        for r in batch_result["results"]:
            print("-" * 60)
            print(f"Asset: {r.get('filename', '?')}")
            print(f"Asset ID: {r.get('asset_id', '?')}")
            decision = r.get("decision", "?")
            exec_status = r.get("execution_status", "")
            print(f"Decision: {decision}")
            if exec_status:
                print(f"Execution: {exec_status}")
            if r.get("blocked_reason"):
                print(f"Blocked Reason: {r['blocked_reason']}")
            if r.get("readiness_status"):
                print(f"Technical Readiness: {r['readiness_status']}")
            if r.get("input_signature"):
                print(f"Input Signature: {r['input_signature'][:16]}...")

            issues = r.get("issues", [])
            if issues:
                print(f"Issues ({len(issues)}):")
                for issue in issues:
                    print(f"  [{issue.severity}] {issue.rule_code}: {issue.message}")

            rule_outcomes = r.get("rule_outcomes", {})
            if rule_outcomes:
                print("Rule Outcomes:")
                for code, outcome in rule_outcomes.items():
                    print(f"  {code}: {outcome}")

        # Summary
        results = batch_result["results"]
        assessed = sum(1 for r in results if r.get("execution_status") == "SUCCESS")
        skipped = sum(1 for r in results if r.get("decision") == "SKIP")
        blocked = sum(1 for r in results if r.get("decision") == "BLOCKED")
        failed = sum(1 for r in results if r.get("execution_status") in ("FAILED", "INPUT_CHANGED"))

        print("-" * 60)
        print(f"\nSummary:")
        print(f"  Total:    {len(results)}")
        print(f"  Assessed: {assessed}")
        print(f"  Skipped:  {skipped}")
        print(f"  Blocked:  {blocked}")
        print(f"  Failed:   {failed}")
        print()

def _print_scan_summary(source_root: str, stats: dict, args):
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
