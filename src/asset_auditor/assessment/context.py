"""Frozen assessment context — loads all upstream data scoped to exact lineage IDs."""
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from .models import Lineage


@dataclass
class AssessmentContext:
    """Immutable context for rule evaluation, scoped to frozen lineage IDs.

    All data is loaded once at construction time.  Evaluators must never
    query the database directly; they use this context exclusively.
    """
    lineage: Lineage

    # Geometry (from BASIC run)
    geometry: Optional[Dict[str, Any]] = None

    # Deep analysis data (from DEEP run)
    materials: List[Dict[str, Any]] = field(default_factory=list)
    images: List[Dict[str, Any]] = field(default_factory=list)
    material_textures: List[Dict[str, Any]] = field(default_factory=list)
    uv_summaries: List[Dict[str, Any]] = field(default_factory=list)
    mesh_materials: List[Dict[str, Any]] = field(default_factory=list)


def load_assessment_context(conn: sqlite3.Connection, lineage: Lineage) -> AssessmentContext:
    """Build a frozen AssessmentContext from the database using exact lineage IDs."""
    conn.row_factory = sqlite3.Row

    # --- Geometry (BASIC run) ---
    geo_row = conn.execute(
        "SELECT * FROM asset_geometry WHERE asset_id = ? AND analysis_run_id = ?",
        (lineage.asset_id, lineage.basic_analysis_run_id),
    ).fetchone()
    geometry = dict(geo_row) if geo_row else None

    # --- Materials (DEEP run) ---
    materials = [
        dict(r) for r in conn.execute(
            "SELECT * FROM asset_materials WHERE asset_id = ? AND analysis_run_id = ?",
            (lineage.asset_id, lineage.deep_analysis_run_id),
        ).fetchall()
    ]

    # --- Images (DEEP run) ---
    images = [
        dict(r) for r in conn.execute(
            "SELECT * FROM asset_images WHERE asset_id = ? AND analysis_run_id = ?",
            (lineage.asset_id, lineage.deep_analysis_run_id),
        ).fetchall()
    ]

    # --- Material textures (DEEP run) ---
    material_textures = [
        dict(r) for r in conn.execute(
            "SELECT * FROM asset_material_textures WHERE asset_id = ? AND analysis_run_id = ?",
            (lineage.asset_id, lineage.deep_analysis_run_id),
        ).fetchall()
    ]

    # --- UV summaries (DEEP run) ---
    uv_summaries = [
        dict(r) for r in conn.execute(
            "SELECT * FROM asset_uv_summary WHERE asset_id = ? AND analysis_run_id = ?",
            (lineage.asset_id, lineage.deep_analysis_run_id),
        ).fetchall()
    ]

    # --- Mesh-material assignments (DEEP run) ---
    mesh_materials = [
        dict(r) for r in conn.execute(
            "SELECT * FROM asset_mesh_materials WHERE asset_id = ? AND analysis_run_id = ?",
            (lineage.asset_id, lineage.deep_analysis_run_id),
        ).fetchall()
    ]

    return AssessmentContext(
        lineage=lineage,
        geometry=geometry,
        materials=materials,
        images=images,
        material_textures=material_textures,
        uv_summaries=uv_summaries,
        mesh_materials=mesh_materials,
    )
