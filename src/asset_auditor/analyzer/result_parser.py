"""Analysis result persistence — stores analysis_runs and asset_geometry in SQLite."""
import sqlite3
from typing import Optional

from .runner import AnalysisResult
from ..config import ANALYZER_VERSION, ANALYSIS_SCHEMA_VERSION

import logging

logger = logging.getLogger(__name__)


def persist_analysis_result(conn: sqlite3.Connection, result: AnalysisResult):
    """Persist an AnalysisResult to analysis_runs and asset_geometry tables.

    Also updates the assets.analysis_status field.
    """
    # Insert analysis run
    conn.execute(
        """INSERT INTO analysis_runs
           (analysis_run_id, asset_id, status, blender_version, analyzer_version,
            analysis_schema_version, started_at, finished_at, duration_ms,
            blender_exit_code, error_type, error_message, stdout_tail, stderr_tail)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            result.analysis_run_id,
            result.asset_id,
            result.status,
            result.blender_version,
            result.analyzer_version,
            result.analysis_schema_version,
            result.started_at,
            result.finished_at,
            result.duration_ms,
            result.blender_exit_code,
            result.error_type,
            result.error_message,
            result.stdout_tail,
            result.stderr_tail,
        ),
    )

    # Insert geometry if analysis succeeded
    if result.status == "SUCCESS" and result.result_data:
        data = result.result_data
        scene = data.get("scene", {})
        geo = data.get("geometry", {})
        bbox = data.get("bounding_box", {})
        units = data.get("units", {})
        mats = data.get("materials", {})
        imgs = data.get("images", {})

        conn.execute(
            """INSERT INTO asset_geometry
               (analysis_run_id, asset_id,
                objects_count, mesh_objects_count, empty_count,
                camera_count, light_count, armature_count,
                vertices, edges, faces, triangles,
                materials_count, images_count,
                bbox_min_x, bbox_min_y, bbox_min_z,
                bbox_max_x, bbox_max_y, bbox_max_z,
                width, depth, height,
                unit_system, unit_scale_length)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result.analysis_run_id,
                result.asset_id,
                scene.get("objects"),
                scene.get("mesh_objects"),
                scene.get("empties"),
                scene.get("cameras"),
                scene.get("lights"),
                scene.get("armatures"),
                geo.get("vertices"),
                geo.get("edges"),
                geo.get("faces"),
                geo.get("triangles"),
                mats.get("count"),
                imgs.get("count"),
                bbox.get("min_x"),
                bbox.get("min_y"),
                bbox.get("min_z"),
                bbox.get("max_x"),
                bbox.get("max_y"),
                bbox.get("max_z"),
                bbox.get("width"),
                bbox.get("depth"),
                bbox.get("height"),
                units.get("system"),
                units.get("scale_length"),
            ),
        )

    # Update asset analysis_status
    conn.execute(
        "UPDATE assets SET analysis_status = ? WHERE asset_id = ?",
        (result.status, result.asset_id),
    )

    conn.commit()
    logger.debug("Persisted analysis run %s for asset %s: %s",
                 result.analysis_run_id, result.asset_id, result.status)
