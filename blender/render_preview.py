"""Blender script to render a 3D asset thumbnail."""
import argparse
import json
import math
import os
import sys
import time
from mathutils import Vector, Matrix, Euler

import bpy

def fail(message: str, error_type: str = "RendererError", exit_code: int = 1):
    result = {
        "status": "FAILED_RENDER",
        "error_message": message,
        "error_type": error_type
    }
    print(f"\n---RESULT_JSON_START---\n{json.dumps(result)}\n---RESULT_JSON_END---\n")
    sys.exit(exit_code)

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input GLB/GLTF path")
    parser.add_argument("--output", required=True, help="Output PNG path")
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--preview-id", required=True)
    if "--" not in sys.argv:
        return parser.parse_args(sys.argv[1:])
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])

def clean_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for mesh in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)
    for mat in bpy.data.materials:
        bpy.data.materials.remove(mat)
    for img in bpy.data.images:
        bpy.data.images.remove(img)
    for cam in bpy.data.cameras:
        bpy.data.cameras.remove(cam)
    for light in bpy.data.lights:
        bpy.data.lights.remove(light)

def get_scene_bounding_box():
    min_x, min_y, min_z = float('inf'), float('inf'), float('inf')
    max_x, max_y, max_z = float('-inf'), float('-inf'), float('-inf')
    has_geometry = False
    
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            # Need to evaluate the evaluated object if there are modifiers,
            # but for GLB basic bounds usually suffice.
            # Using bound_box which is in object space, then transform to world space.
            bbox = obj.bound_box
            for corner in bbox:
                world_corner = obj.matrix_world @ Vector(corner)
                min_x = min(min_x, world_corner.x)
                min_y = min(min_y, world_corner.y)
                min_z = min(min_z, world_corner.z)
                max_x = max(max_x, world_corner.x)
                max_y = max(max_y, world_corner.y)
                max_z = max(max_z, world_corner.z)
            has_geometry = True
            
    if not has_geometry:
        return None
        
    return {
        "min_x": min_x, "min_y": min_y, "min_z": min_z,
        "max_x": max_x, "max_y": max_y, "max_z": max_z,
        "width": max_x - min_x,
        "depth": max_y - min_y,
        "height": max_z - min_z,
        "center_x": (min_x + max_x) / 2.0,
        "center_y": (min_y + max_y) / 2.0,
        "center_z": (min_z + max_z) / 2.0,
    }

def setup_lighting(radius: float, center: Vector):
    # Neutral Studio V1: Scale-aware, neutral white lights
    light_distance = radius * 4.0
    light_size = radius * 2.0
    base_energy = (radius ** 2) * 2000.0 * 0.82 # Energy scales with radius squared
    
    # Key light
    bpy.ops.object.light_add(type='AREA')
    key_light = bpy.context.active_object
    key_light.name = "KeyLight"
    key_light.data.color = (1.0, 1.0, 1.0)
    key_light.data.energy = base_energy * 1.5
    key_light.data.size = light_size
    key_light.location = center + Vector((-light_distance, -light_distance, light_distance))
    
    # Fill light
    bpy.ops.object.light_add(type='AREA')
    fill_light = bpy.context.active_object
    fill_light.name = "FillLight"
    fill_light.data.color = (1.0, 1.0, 1.0)
    fill_light.data.energy = base_energy * 0.5
    fill_light.data.size = light_size
    fill_light.location = center + Vector((light_distance, -light_distance * 0.5, 0))
    
    # Rim light
    bpy.ops.object.light_add(type='AREA')
    rim_light = bpy.context.active_object
    rim_light.name = "RimLight"
    rim_light.data.color = (1.0, 1.0, 1.0)
    rim_light.data.energy = base_energy * 2.0
    rim_light.data.size = light_size
    rim_light.location = center + Vector((0, light_distance, light_distance))

    # Point all lights to center
    for light_obj in [key_light, fill_light, rim_light]:
        direction = center - light_obj.location
        rot_quat = direction.to_track_quat('-Z', 'Y')
        light_obj.rotation_euler = rot_quat.to_euler()

def main():
    args = get_args()
    
    try:
        clean_scene()
        
        # Disable collection instantiation warnings or similar during import
        bpy.ops.import_scene.gltf(filepath=args.input)
        
        bbox = get_scene_bounding_box()
        if not bbox:
            fail("No geometry found in asset.", "EmptyGeometry")
            
        radius = 0.5 * math.sqrt(bbox['width']**2 + bbox['depth']**2 + bbox['height']**2)
        if radius <= 1e-6 or math.isnan(radius):
            fail(f"Invalid geometry bounds: radius={radius}", "InvalidGeometry")
            
        center = Vector((bbox['center_x'], bbox['center_y'], bbox['center_z']))
        
        # Setup Camera
        bpy.ops.object.camera_add()
        cam_obj = bpy.context.active_object
        cam = cam_obj.data
        cam.type = 'PERSP'
        cam.lens = 50.0 # 50mm
        
        # Camera distance
        # FOV in radians for largest dimension (assuming 1:1 aspect ratio, FOV is uniform)
        # Using 50mm on 36mm sensor gives FOV ~ 39.6 degrees
        fov = cam.angle
        margin = 1.07
        distance = (radius * margin) / math.sin(fov / 2.0)
        
        # WORLD_3Q_V1 direction: (+1, -1, +0.7) normalized
        direction = Vector((1.0, -1.0, 0.7)).normalized()
        cam_obj.location = center + direction * distance
        
        # Point camera at center
        rot_quat = (-direction).to_track_quat('-Z', 'Y')
        cam_obj.rotation_euler = rot_quat.to_euler()
        
        # Set dynamic clip
        cam.clip_start = max(0.001, distance * 0.1)
        cam.clip_end = max(100.0, distance * 100.0)
        
        bpy.context.scene.camera = cam_obj
        
        setup_lighting(radius, center)
        
        # Renderer Settings
        scene = bpy.context.scene
        scene.render.engine = 'BLENDER_EEVEE'
        scene.render.resolution_x = 1024
        scene.render.resolution_y = 1024
        scene.render.resolution_percentage = 100
        
        # Background: NEUTRAL_GRAY_V1
        # Set world color
        if not scene.world:
            bpy.ops.world.new()
            scene.world = bpy.data.worlds[0]
        scene.world.use_nodes = True
        bg_node = scene.world.node_tree.nodes.get("Background")
        if bg_node:
            bg_node.inputs[0].default_value = (0.18, 0.18, 0.18, 1.0)
        scene.render.film_transparent = False
        
        # Color Management
        scene.view_settings.view_transform = 'AgX'
        scene.view_settings.look = 'None'
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
        
        # Output
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGB'
        scene.render.image_settings.color_depth = '8'
        scene.render.filepath = args.output
        
        # Render!
        bpy.ops.render.render(write_still=True)
        
        render_settings = {
            "camera": {
                "type": "PERSPECTIVE",
                "focal_length_mm": 50.0,
                "profile": "WORLD_3Q_V1",
                "margin_factor": margin,
                "position": list(cam_obj.location),
                "target": list(center),
                "distance": distance,
                "clip_start": cam.clip_start,
                "clip_end": cam.clip_end
            },
            "lighting_profile": "NEUTRAL_STUDIO_V1",
            "background_profile": "NEUTRAL_GRAY_V1",
            "color_management": {
                "view_transform": scene.view_settings.view_transform,
                "look": scene.view_settings.look,
                "exposure": scene.view_settings.exposure,
                "gamma": scene.view_settings.gamma
            }
        }
        
        result = {
            "status": "SUCCESS",
            "asset_id": args.asset_id,
            "preview_id": args.preview_id,
            "blender_version": bpy.app.version_string,
            "render_engine": scene.render.engine,
            "width": scene.render.resolution_x,
            "height": scene.render.resolution_y,
            "render_settings": render_settings,
            "bounding_box": bbox
        }
        print(f"\n---RESULT_JSON_START---\n{json.dumps(result)}\n---RESULT_JSON_END---\n")

    except Exception as e:
        fail(str(e), type(e).__name__)

if __name__ == "__main__":
    main()
