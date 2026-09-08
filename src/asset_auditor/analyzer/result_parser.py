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
            analysis_schema_version, analysis_profile, started_at, finished_at, duration_ms,
            blender_exit_code, error_type, error_message, stdout_tail, stderr_tail)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            result.analysis_run_id,
            result.asset_id,
            result.status,
            result.blender_version,
            result.analyzer_version,
            result.analysis_schema_version,
            result.analysis_profile,
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

    if result.status == "SUCCESS" and result.result_data:
        data = result.result_data

        if result.analysis_profile == "BASIC":
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
        
        elif result.analysis_profile == "DEEP":
            import json
            # Maps from blender index to SQLite DB id
            material_id_map = {}
            image_id_map = {}

            # 1. Insert materials
            materials = data.get("materials", [])
            for m in materials:
                c = conn.execute(
                    """INSERT INTO asset_materials 
                       (analysis_run_id, asset_id, material_index, material_name, 
                        use_nodes, node_count, image_texture_node_count, principled_bsdf_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        result.analysis_run_id,
                        result.asset_id,
                        m["index"],
                        m.get("name"),
                        1 if m.get("use_nodes") else 0,
                        m.get("node_count"),
                        m.get("image_texture_node_count"),
                        m.get("principled_bsdf_count"),
                    )
                )
                material_id_map[m["index"]] = c.lastrowid

            # 2. Insert images
            images = data.get("images", [])
            for i in images:
                c = conn.execute(
                    """INSERT INTO asset_images
                       (analysis_run_id, asset_id, image_index, image_name, width, height, 
                        channels, file_format, source_type, colorspace_name, packed, 
                        original_filepath, resolved_filepath, exists_on_disk, resource_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        result.analysis_run_id,
                        result.asset_id,
                        i["index"],
                        i.get("name"),
                        i.get("width"),
                        i.get("height"),
                        i.get("channels"),
                        i.get("file_format"),
                        i.get("source_type"),
                        i.get("colorspace_name"),
                        1 if i.get("packed") else 0,
                        i.get("original_filepath"),
                        i.get("resolved_filepath"),
                        i.get("exists_on_disk"),
                        i.get("resource_status"),
                    )
                )
                image_id_map[i["index"]] = c.lastrowid

            # 3. Insert material textures
            textures = data.get("material_textures", [])
            for t in textures:
                mat_id = material_id_map.get(t["material_index"])
                img_id = image_id_map.get(t["image_index"])
                if mat_id is not None and img_id is not None:
                    conn.execute(
                        """INSERT INTO asset_material_textures
                           (analysis_run_id, asset_id, material_id, image_id, 
                            node_name, texture_role, uv_mapping_source, uv_map_name)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            result.analysis_run_id,
                            result.asset_id,
                            mat_id,
                            img_id,
                            t.get("node_name"),
                            t.get("texture_role"),
                            t.get("uv_mapping_source"),
                            t.get("uv_map_name"),
                        )
                    )

            # 4. Insert UV summary
            uv_summary = data.get("uv_summary", [])
            for u in uv_summary:
                conn.execute(
                    """INSERT INTO asset_uv_summary
                       (analysis_run_id, asset_id, mesh_index, mesh_name, 
                        uv_layer_count, uv_layer_names_json, active_uv_layer, has_uv)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        result.analysis_run_id,
                        result.asset_id,
                        u["mesh_index"],
                        u.get("mesh_name"),
                        u.get("uv_layer_count"),
                        json.dumps(u.get("uv_layer_names", [])),
                        u.get("active_uv_layer"),
                        1 if u.get("has_uv") else 0,
                    )
                )

            # 5. Insert mesh material assignments
            mesh_materials = data.get("mesh_materials", [])
            for mm in mesh_materials:
                mat_id = material_id_map.get(mm["material_index"])
                if mat_id is not None:
                    conn.execute(
                        """INSERT INTO asset_mesh_materials
                           (analysis_run_id, asset_id, object_index, object_name, 
                            mesh_index, mesh_name, material_id, material_slot_index, material_link_mode)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            result.analysis_run_id,
                            result.asset_id,
                            mm["object_index"],
                            mm.get("object_name"),
                            mm["mesh_index"],
                            mm.get("mesh_name"),
                            mat_id,
                            mm.get("material_slot_index"),
                            mm.get("material_link_mode"),
                        )
                    )


    # Update status depending on profile
    if result.analysis_profile == "BASIC":
        conn.execute(
            "UPDATE assets SET analysis_status = ? WHERE asset_id = ?",
            (result.status, result.asset_id),
        )
    elif result.analysis_profile == "DEEP":
        conn.execute(
            "UPDATE assets SET deep_analysis_status = ? WHERE asset_id = ?",
            (result.status, result.asset_id),
        )

    conn.commit()
    logger.debug("Persisted %s analysis run %s for asset %s: %s",
                 result.analysis_profile, result.analysis_run_id, result.asset_id, result.status)
