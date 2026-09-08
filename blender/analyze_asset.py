"""Blender-side analysis script for 3D assets.

This script runs INSIDE a Blender subprocess. It is invoked as:

    blender --background --factory-startup --disable-autoexec \
        --python blender/analyze_asset.py \
        -- --input <asset_path> --output <result_json> --asset-id <uuid>

It imports the asset, collects geometry/scene/material metrics,
computes a world-space bounding box, and writes a structured JSON result.

Geometry semantics:
    - vertices/edges/faces/triangles are summed across UNIQUE mesh datablocks
    - Shared mesh datablocks (instances) are counted once to avoid double-counting
    - Triangles are computed via mesh.calc_loop_triangles() without modifying source
    - All metrics represent raw mesh data, not evaluated modifier geometry

Bounding box semantics:
    - Computed in WORLD SPACE using object transforms (obj.matrix_world)
    - Considers all mesh object vertices after transformation
    - Blender coordinate system: X=right, Y=forward, Z=up
"""
import sys
import os
sys.path.append(os.path.expanduser("~/.local/lib/python3.12/site-packages"))

import json
import argparse
import traceback
from mathutils import Vector

import bpy

ANALYSIS_SCHEMA_VERSION = "1"


def parse_args():
    """Parse arguments passed after -- separator."""
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to asset file")
    parser.add_argument("--output", required=True, help="Path to write result JSON")
    parser.add_argument("--asset-id", required=True, help="Asset UUID")
    return parser.parse_args(argv)


def clean_scene():
    """Remove all objects from the default factory scene."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    # Also remove orphan data
    for mesh in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)
    for mat in bpy.data.materials:
        bpy.data.materials.remove(mat)
    for img in bpy.data.images:
        bpy.data.images.remove(img)


def import_glb(filepath: str):
    """Import a GLB/GLTF file using the appropriate Blender operator."""
    bpy.ops.import_scene.gltf(filepath=filepath)


def collect_scene_info() -> dict:
    """Collect object type counts from the current scene."""
    counts = {
        "objects": 0,
        "mesh_objects": 0,
        "empties": 0,
        "cameras": 0,
        "lights": 0,
        "armatures": 0,
    }
    for obj in bpy.data.objects:
        counts["objects"] += 1
        if obj.type == "MESH":
            counts["mesh_objects"] += 1
        elif obj.type == "EMPTY":
            counts["empties"] += 1
        elif obj.type == "CAMERA":
            counts["cameras"] += 1
        elif obj.type == "LIGHT":
            counts["lights"] += 1
        elif obj.type == "ARMATURE":
            counts["armatures"] += 1
    return counts


def collect_geometry() -> dict:
    """Collect geometry metrics from unique mesh datablocks.

    Uses unique mesh datablocks to avoid double-counting instanced meshes.
    """
    total_verts = 0
    total_edges = 0
    total_faces = 0
    total_tris = 0

    # Collect unique mesh datablocks (avoid double-counting shared meshes)
    seen_meshes = set()
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.data and obj.data.name not in seen_meshes:
            seen_meshes.add(obj.data.name)
            mesh = obj.data
            total_verts += len(mesh.vertices)
            total_edges += len(mesh.edges)
            total_faces += len(mesh.polygons)
            mesh.calc_loop_triangles()
            total_tris += len(mesh.loop_triangles)

    return {
        "vertices": total_verts,
        "edges": total_edges,
        "faces": total_faces,
        "triangles": total_tris,
    }


def collect_bounding_box() -> dict:
    """Compute overall world-space bounding box across all mesh objects.

    Takes object transforms (matrix_world) into account.
    Blender axes: X=right, Y=forward, Z=up.
    """
    all_coords = []
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.data:
            for v in obj.data.vertices:
                world_co = obj.matrix_world @ v.co
                all_coords.append(world_co)

    if not all_coords:
        return {
            "min_x": 0.0, "min_y": 0.0, "min_z": 0.0,
            "max_x": 0.0, "max_y": 0.0, "max_z": 0.0,
            "width": 0.0, "depth": 0.0, "height": 0.0,
        }

    min_x = min(c.x for c in all_coords)
    max_x = max(c.x for c in all_coords)
    min_y = min(c.y for c in all_coords)
    max_y = max(c.y for c in all_coords)
    min_z = min(c.z for c in all_coords)
    max_z = max(c.z for c in all_coords)

    return {
        "min_x": round(min_x, 6),
        "min_y": round(min_y, 6),
        "min_z": round(min_z, 6),
        "max_x": round(max_x, 6),
        "max_y": round(max_y, 6),
        "max_z": round(max_z, 6),
        "width": round(max_x - min_x, 6),
        "depth": round(max_y - min_y, 6),
        "height": round(max_z - min_z, 6),
    }


def collect_units() -> dict:
    """Record Blender scene unit settings."""
    scene = bpy.context.scene
    return {
        "system": scene.unit_settings.system,
        "scale_length": scene.unit_settings.scale_length,
    }


def main():
    args = parse_args()
    blender_version = ".".join(str(x) for x in bpy.app.version)

    result = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "asset_id": args.asset_id,
        "source_path": args.input,
        "status": "SUCCESS",
        "blender_version": blender_version,
        "error": None,
        "scene": None,
        "geometry": None,
        "materials": None,
        "images": None,
        "bounding_box": None,
        "units": None,
    }

    try:
        clean_scene()
        import_glb(args.input)
    except Exception as e:
        result["status"] = "FAILED_IMPORT"
        result["error"] = {
            "type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        sys.exit(1)

    try:
        result["scene"] = collect_scene_info()
        result["geometry"] = collect_geometry()
        result["bounding_box"] = collect_bounding_box()
        result["units"] = collect_units()
        result["materials"] = {"count": len(bpy.data.materials)}
        result["images"] = {"count": len(bpy.data.images)}
    except Exception as e:
        result["status"] = "FAILED_ANALYSIS"
        result["error"] = {
            "type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        sys.exit(2)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    sys.exit(0)


if __name__ == "__main__":
    main()
