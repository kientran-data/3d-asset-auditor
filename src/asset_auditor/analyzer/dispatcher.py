"""Batch analysis dispatcher.

Queries the database for pending GLB/GLTF assets and runs them through
Blender analysis one at a time. Each asset runs in its own subprocess.
"""
import logging
import sqlite3
from datetime import datetime, UTC
from typing import Dict, Any, Optional, List

from .runner import run_blender_analysis
from .result_parser import persist_analysis_result
from ..config import ANALYSIS_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# Extensions supported in Phase 2A
PHASE_2A_EXTENSIONS = {".glb", ".gltf"}


def get_pending_assets(
    conn: sqlite3.Connection,
    source_root: Optional[str] = None,
    asset_id: Optional[str] = None,
    include_failed: bool = False,
    deep: bool = False,
) -> List[dict]:
    """Query assets eligible for analysis."""
    conditions = [
        "is_present = 1",
        "LOWER(extension) IN ('.glb', '.gltf')",
    ]
    params = []

    if asset_id:
        conditions.append("asset_id = ?")
        params.append(asset_id)
    elif source_root:
        conditions.append("source_root = ?")
        params.append(source_root)

    if deep:
        conditions.append("analysis_status = 'SUCCESS'")
        if include_failed:
            conditions.append(
                "deep_analysis_status IN ('PENDING', 'FAILED_IMPORT', 'FAILED_ANALYSIS', 'TIMEOUT')"
            )
        else:
            conditions.append("deep_analysis_status = 'PENDING'")
    else:
        if include_failed:
            conditions.append(
                "analysis_status IN ('PENDING', 'FAILED_IMPORT', 'FAILED_ANALYSIS', 'TIMEOUT')"
            )
        else:
            conditions.append("analysis_status = 'PENDING'")

    sql = f"SELECT asset_id, absolute_path, filename FROM assets WHERE {' AND '.join(conditions)}"
    cursor = conn.cursor()
    cursor.execute(sql, params)
    return [
        {"asset_id": row[0], "absolute_path": row[1], "filename": row[2]}
        for row in cursor.fetchall()
    ]


def run_batch_analysis(
    conn: sqlite3.Connection,
    source_root: Optional[str] = None,
    asset_id: Optional[str] = None,
    include_failed: bool = False,
    timeout: int = ANALYSIS_TIMEOUT_SECONDS,
    deep: bool = False,
) -> Dict[str, Any]:
    """Run analysis on eligible GLB/GLTF assets.

    Returns batch statistics.
    """
    pending = get_pending_assets(conn, source_root, asset_id, include_failed, deep)
    total = len(pending)

    stats = {
        "total": total,
        "success": 0,
        "failed_import": 0,
        "failed_analysis": 0,
        "timeout": 0,
    }

    if total == 0:
        logger.info("No pending GLB/GLTF assets to analyze")
        return stats

    profile = "DEEP" if deep else "BASIC"
    logger.info("Starting %s analysis of %d asset(s)", profile, total)

    for i, asset in enumerate(pending, 1):
        aid = asset["asset_id"]
        filename = asset["filename"]
        path = asset["absolute_path"]

        print(f"[{i}/{total}] {profile} Analyzing {filename}...")

        # Mark as ANALYZING
        status_col = "deep_analysis_status" if deep else "analysis_status"
        conn.execute(
            f"UPDATE assets SET {status_col} = 'ANALYZING' WHERE asset_id = ?",
            (aid,),
        )
        conn.commit()

        result = run_blender_analysis(aid, path, timeout=timeout, analysis_profile=profile)

        # Persist result
        persist_analysis_result(conn, result)

        # Print status
        duration_sec = result.duration_ms / 1000
        if result.status == "SUCCESS":
            stats["success"] += 1
            print(f"  SUCCESS — {duration_sec:.1f} sec")
        elif result.status == "FAILED_IMPORT":
            stats["failed_import"] += 1
            print(f"  FAILED_IMPORT — {result.error_message}")
        elif result.status == "TIMEOUT":
            stats["timeout"] += 1
            print(f"  TIMEOUT — exceeded {timeout}s")
        else:
            stats["failed_analysis"] += 1
            print(f"  {result.status} — {result.error_message}")

    return stats
