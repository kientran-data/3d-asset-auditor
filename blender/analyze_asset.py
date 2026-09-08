"""Blender-side analysis script for 3D assets.

This script runs INSIDE a Blender subprocess. It is invoked as:

    blender --background --factory-startup --disable-autoexec \
        --python blender/analyze_asset.py \
        -- --input <asset_path> --output <result_json> --asset-id <uuid> [--deep]

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

ANALYSIS_SCHEMA_VERSION = "2"


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
    parser.add_argument("--deep", action="store_true", help="Run Deep Analysis")
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
    """Compute overall world-space bounding box across all mesh objects."""
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


def collect_materials() -> list:
    results = []
    for idx, mat in enumerate(bpy.data.materials):
        use_nodes = getattr(mat, "use_nodes", False)
        node_count = 0
        img_node_count = 0
        principled_count = 0
        if use_nodes and mat.node_tree:
            node_count = len(mat.node_tree.nodes)
            img_node_count = sum(1 for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE')
            principled_count = sum(1 for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        
        results.append({
            "index": idx,
            "name": mat.name,
            "use_nodes": use_nodes,
            "node_count": node_count,
            "image_texture_node_count": img_node_count,
            "principled_bsdf_count": principled_count,
        })
    return results


def collect_images() -> list:
    results = []
    for idx, img in enumerate(bpy.data.images):
        packed = img.packed_file is not None
        source_type = img.source
        
        # Resource precedence
        if source_type == 'GENERATED':
            resource_status = 'GENERATED'
        elif packed:
            resource_status = 'PACKED'
        elif img.filepath and img.filepath != "":
            resolved = bpy.path.abspath(img.filepath)
            exists = os.path.exists(resolved)
            resource_status = 'EXTERNAL_PRESENT' if exists else 'EXTERNAL_MISSING'
        else:
            resource_status = 'UNKNOWN'
        
        exists_on_disk = None
        if resource_status == 'EXTERNAL_PRESENT':
            exists_on_disk = 1
        elif resource_status == 'EXTERNAL_MISSING':
            exists_on_disk = 0

        results.append({
            "index": idx,
            "name": img.name,
            "width": img.size[0],
            "height": img.size[1],
            "channels": img.channels,
            "file_format": img.file_format,
            "source_type": source_type,
            "colorspace_name": img.colorspace_settings.name,
            "packed": packed,
            "original_filepath": img.filepath,
            "resolved_filepath": bpy.path.abspath(img.filepath) if img.filepath else None,
            "exists_on_disk": exists_on_disk,
            "resource_status": resource_status,
        })
    return results


def trace_texture_roles() -> list:
    results = []
    image_idx_map = {img.name: i for i, img in enumerate(bpy.data.images)}
    
    for mat_idx, mat in enumerate(bpy.data.materials):
        if not mat.use_nodes or not mat.node_tree:
            continue
            
        mat_output = next((n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        principled = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        
        # Keep track of already emitted roles for an image in a material to prevent dupes
        emitted_links = set()

        def trace_socket(socket) -> list:
            found_images = []
            if not socket.is_linked:
                return found_images
            for link in socket.links:
                from_node = link.from_node
                if from_node.type == 'TEX_IMAGE' and from_node.image:
                    found_images.append(from_node)
                elif from_node.type == 'NORMAL_MAP':
                    if 'Color' in from_node.inputs:
                        found_images.extend(trace_socket(from_node.inputs['Color']))
                else:
                    for in_sock in from_node.inputs:
                        found_images.extend(trace_socket(in_sock))
            return found_images

        def process_socket(socket, role_name):
            if socket:
                img_nodes = trace_socket(socket)
                for node in img_nodes:
                    if node.image and node.image.name in image_idx_map:
                        img_idx = image_idx_map[node.image.name]
                        # Avoid emitting exact duplicates for same role/node
                        link_key = (img_idx, role_name, node.name)
                        if link_key in emitted_links:
                            continue
                        emitted_links.add(link_key)
                        
                        uv_map_name = None
                        uv_mapping_source = "DEFAULT"
                        
                        if 'Vector' in node.inputs and node.inputs['Vector'].is_linked:
                            for l in node.inputs['Vector'].links:
                                if l.from_node.type == 'UVMAP':
                                    uv_mapping_source = "EXPLICIT_UV_MAP"
                                    uv_map_name = l.from_node.uv_map
                                    break
                                elif l.from_node.type == 'TEX_COORD':
                                    uv_mapping_source = "OTHER"
                                    
                        results.append({
                            "material_index": mat_idx,
                            "image_index": img_idx,
                            "node_name": node.name,
                            "texture_role": role_name,
                            "uv_mapping_source": uv_mapping_source,
                            "uv_map_name": uv_map_name
                        })

        roles = {
            'BASE_COLOR': 'Base Color',
            'ROUGHNESS': 'Roughness',
            'METALLIC': 'Metallic',
            'NORMAL': 'Normal',
            'ALPHA': 'Alpha',
            'EMISSION': 'Emission Color', 
        }
        
        if principled:
            for role_name, socket_name in roles.items():
                socket = principled.inputs.get(socket_name)
                if not socket and role_name == 'EMISSION':
                    socket = principled.inputs.get('Emission')
                process_socket(socket, role_name)
                            
        if mat_output:
            disp_socket = mat_output.inputs.get('Displacement')
            process_socket(disp_socket, 'DISPLACEMENT')

    return results


def collect_uv_summary() -> list:
    results = []
    for mesh_idx, mesh in enumerate(bpy.data.meshes):
        uv_layers = mesh.uv_layers
        layer_names = [layer.name for layer in uv_layers]
        active_layer = uv_layers.active.name if uv_layers.active else None
        
        results.append({
            "mesh_index": mesh_idx,
            "mesh_name": mesh.name,
            "uv_layer_count": len(layer_names),
            "uv_layer_names": layer_names,
            "active_uv_layer": active_layer,
            "has_uv": len(layer_names) > 0,
        })
    return results


def collect_mesh_materials() -> list:
    results = []
    mesh_idx_map = {mesh.name: i for i, mesh in enumerate(bpy.data.meshes)}
    mat_idx_map = {mat.name: i for i, mat in enumerate(bpy.data.materials)}
    
    for obj_idx, obj in enumerate(bpy.data.objects):
        if obj.type == 'MESH' and obj.data:
            mesh_idx = mesh_idx_map.get(obj.data.name)
            if mesh_idx is None:
                continue
                
            for slot_idx, slot in enumerate(obj.material_slots):
                if slot.material:
                    mat_idx = mat_idx_map.get(slot.material.name)
                    if mat_idx is not None:
                        results.append({
                            "object_index": obj_idx,
                            "object_name": obj.name,
                            "mesh_index": mesh_idx,
                            "mesh_name": obj.data.name,
                            "material_index": mat_idx,
                            "material_slot_index": slot_idx,
                            "material_link_mode": slot.link,
                        })
    return results


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
        "analysis_profile": "DEEP" if args.deep else "BASIC",
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
        # Always run basic
        result["scene"] = collect_scene_info()
        result["geometry"] = collect_geometry()
        result["bounding_box"] = collect_bounding_box()
        result["units"] = collect_units()
        
        # Collect materials/images count for BASIC geometry compatibility
        mats_list = collect_materials()
        imgs_list = collect_images()
        
        result["materials"] = {"count": len(mats_list)}
        result["images"] = {"count": len(imgs_list)}

        if args.deep:
            # Override with full data
            result["materials"] = mats_list
            result["images"] = imgs_list
            result["material_textures"] = trace_texture_roles()
            result["uv_summary"] = collect_uv_summary()
            result["mesh_materials"] = collect_mesh_materials()

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
