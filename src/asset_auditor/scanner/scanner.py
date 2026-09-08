"""Recursive filesystem scanner for 3D asset inventory.

Architectural boundary: Scanner answers "What is on the disk?"
It collects filesystem facts only — no business inference, no model parsing.

Missing-file reconciliation semantics:
    Assets are only marked missing (is_present=0) after a scan that completes
    without encountering ANY directory-level errors.  If the scanner fails to
    read one or more directories (permission denied, I/O error), reconciliation
    is skipped entirely so that assets in inaccessible subtrees are not falsely
    marked missing.  This prevents an interrupted or partially-failed scan from
    invalidating historical records.
"""
import os
import uuid
import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, Any, Set

from .formats import get_format_status, FormatStatus, initial_analysis_status
from .fingerprint import create_fingerprint
from ..models import AssetRecord
from ..catalog.repository import AssetRepository

logger = logging.getLogger(__name__)


class Scanner:
    def __init__(self, source_root: str, repository: AssetRepository):
        self.source_root = os.path.abspath(source_root)
        self.repository = repository

    def scan(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {
            "dirs_visited": 0,
            "files_encountered": 0,
            "non_3d_files": 0,
            "errors": 0,
            "total_3d_assets": 0,
            "total_size_bytes": 0,
            "formats": {},
            "capabilities": {
                "MVP_SUPPORTED": 0,
                "SUPPORTED_LATER": 0,
                "UNSUPPORTED_FORMAT": 0,
            },
            "new": 0,
            "changed": 0,
            "unchanged": 0,
            "missing": 0,
        }

        logger.info("Starting scan of %s", self.source_root)

        # Track every absolute_path we successfully visit so we can reconcile later
        seen_paths: Set[str] = set()
        had_dir_errors = False

        try:
            for root, dirs, files in os.walk(self.source_root, followlinks=False):
                stats["dirs_visited"] += 1

                rel_dir = os.path.relpath(root, self.source_root)
                parts = () if rel_dir == "." else Path(rel_dir).parts

                directory_depth = len(parts)
                top_level_directory = parts[0] if parts else ""
                parent_directory = parts[-1] if parts else ""

                for filename in files:
                    stats["files_encountered"] += 1
                    absolute_path = os.path.join(root, filename)

                    # Skip symlinks (do not follow, do not crash on broken ones)
                    try:
                        if os.path.islink(absolute_path):
                            continue
                    except OSError as e:
                        logger.warning("Cannot inspect link status of %s: %s", absolute_path, e)
                        stats["errors"] += 1
                        continue

                    try:
                        stat = os.stat(absolute_path)
                    except OSError as e:
                        logger.error("Cannot stat %s: %s", absolute_path, e)
                        stats["errors"] += 1
                        continue

                    extension = Path(filename).suffix
                    format_status = get_format_status(extension)

                    if format_status == FormatStatus.NON_3D:
                        stats["non_3d_files"] += 1
                        continue

                    seen_paths.add(absolute_path)
                    self._process_3d_file(
                        absolute_path=absolute_path,
                        filename=filename,
                        extension=extension,
                        stat=stat,
                        top_level_directory=top_level_directory,
                        parent_directory=parent_directory,
                        directory_depth=directory_depth,
                        format_status=format_status,
                        stats=stats,
                    )

                # Prune dirs that we cannot access to record them as errors
                inaccessible = []
                for d in dirs:
                    dir_path = os.path.join(root, d)
                    if os.path.islink(dir_path):
                        inaccessible.append(d)
                        continue
                    if not os.access(dir_path, os.R_OK | os.X_OK):
                        logger.error("Permission denied for directory: %s", dir_path)
                        stats["errors"] += 1
                        had_dir_errors = True
                        inaccessible.append(d)
                for d in inaccessible:
                    dirs.remove(d)

        except Exception as e:
            logger.error("Fatal error during scan: %s", e)
            stats["errors"] += 1
            had_dir_errors = True

        # --- Safe missing-file reconciliation ---
        # Only reconcile if the scan completed without directory-level errors.
        if not had_dir_errors:
            missing_count = self.repository.reconcile_missing(self.source_root, seen_paths)
            stats["missing"] = missing_count
        else:
            logger.warning(
                "Skipping missing-file reconciliation because %d directory error(s) occurred. "
                "Assets in inaccessible subtrees will NOT be marked missing.",
                stats["errors"],
            )
            stats["missing"] = 0

        return stats

    def _process_3d_file(
        self,
        absolute_path: str,
        filename: str,
        extension: str,
        stat: os.stat_result,
        top_level_directory: str,
        parent_directory: str,
        directory_depth: int,
        format_status: FormatStatus,
        stats: Dict[str, Any],
    ):
        size_bytes = stat.st_size
        mtime_ns = stat.st_mtime_ns
        new_fingerprint = create_fingerprint(size_bytes, mtime_ns)

        relative_path = os.path.relpath(absolute_path, self.source_root)
        stem = Path(filename).stem
        now_str = datetime.now(UTC).isoformat()

        # Update format statistics
        ext_upper = extension.upper().lstrip(".")
        if ext_upper:
            stats["formats"][ext_upper] = stats["formats"].get(ext_upper, 0) + 1
        stats["capabilities"][format_status.value] += 1
        stats["total_3d_assets"] += 1
        stats["total_size_bytes"] += size_bytes

        existing_asset = self.repository.get_by_path(self.source_root, absolute_path)

        if existing_asset:
            old_fingerprint = create_fingerprint(
                existing_asset.file_size_bytes, existing_asset.modified_time_ns
            )
            if new_fingerprint == old_fingerprint:
                # File unchanged — preserve everything, just mark present
                stats["unchanged"] += 1
                self.repository.mark_present(self.source_root, absolute_path)
            else:
                # File changed — preserve asset_id, reset ALL downstream states
                stats["changed"] += 1
                analysis = initial_analysis_status(format_status)
                asset = AssetRecord(
                    asset_id=existing_asset.asset_id,
                    source_root=self.source_root,
                    absolute_path=absolute_path,
                    relative_path=relative_path,
                    filename=filename,
                    stem=stem,
                    extension=extension,
                    file_size_bytes=size_bytes,
                    file_size_mb=round(size_bytes / (1024 * 1024), 6),
                    modified_time_ns=mtime_ns,
                    modified_at=datetime.fromtimestamp(mtime_ns / 1e9).isoformat(),
                    parent_directory=parent_directory,
                    top_level_directory=top_level_directory,
                    directory_depth=directory_depth,
                    format_status=format_status.value,
                    scan_status="SUCCESS",
                    analysis_status=analysis,
                    deep_analysis_status=analysis,
                    preview_status="PENDING",
                    assessment_status="PENDING",
                    discovered_at=existing_asset.discovered_at,
                    updated_at=now_str,
                    is_present=1,
                )
                self.repository.upsert_asset(asset)
        else:
            # New file
            stats["new"] += 1
            analysis = initial_analysis_status(format_status)
            asset = AssetRecord(
                asset_id=str(uuid.uuid4()),
                source_root=self.source_root,
                absolute_path=absolute_path,
                relative_path=relative_path,
                filename=filename,
                stem=stem,
                extension=extension,
                file_size_bytes=size_bytes,
                file_size_mb=round(size_bytes / (1024 * 1024), 6),
                modified_time_ns=mtime_ns,
                modified_at=datetime.fromtimestamp(mtime_ns / 1e9).isoformat(),
                parent_directory=parent_directory,
                top_level_directory=top_level_directory,
                directory_depth=directory_depth,
                format_status=format_status.value,
                scan_status="SUCCESS",
                analysis_status=analysis,
                deep_analysis_status=analysis,
                preview_status="PENDING",
                assessment_status="PENDING",
                discovered_at=now_str,
                updated_at=now_str,
                is_present=1,
            )
            self.repository.upsert_asset(asset)
