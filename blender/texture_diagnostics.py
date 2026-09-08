"""Read-only texture diagnostic: extract pixel statistics from packed images
used by the 13 TEXTURED_MESH_WITHOUT_UV issues.

Output JSON with per-image variance/min/max/mean to determine whether
the texture is spatially varying or effectively constant.
"""
import bpy
import json
import sys
import os
import numpy as np

def get_pixel_stats(image):
    """Get basic pixel statistics from a Blender image."""
    w, h = image.size
    if w == 0 or h == 0:
        return {"error": "zero_size"}
    
    pixels = np.array(image.pixels[:])
    # pixels is flat RGBA: [r,g,b,a, r,g,b,a, ...]
    pixels = pixels.reshape((w * h, 4))
    
    rgb = pixels[:, :3]
    
    stats = {
        "width": w,
        "height": h,
        "channels": 4,
        "pixel_count": w * h,
        "rgb_mean": [round(float(x), 4) for x in rgb.mean(axis=0)],
        "rgb_std": [round(float(x), 4) for x in rgb.std(axis=0)],
        "rgb_min": [round(float(x), 4) for x in rgb.min(axis=0)],
        "rgb_max": [round(float(x), 4) for x in rgb.max(axis=0)],
        "overall_std": round(float(rgb.std()), 4),
        "overall_range": round(float(rgb.max() - rgb.min()), 4),
    }
    
    # Classify
    if stats["overall_std"] < 0.02:
        stats["classification"] = "EFFECTIVELY_CONSTANT"
    elif stats["overall_std"] < 0.10:
        stats["classification"] = "LOW_VARIATION"
    else:
        stats["classification"] = "SPATIALLY_VARYING"
    
    return stats

def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    input_glb = args[0]
    output_json = args[1]
    image_names_json = args[2]  # JSON list of image names to inspect
    
    image_names = json.loads(image_names_json)
    
    # Import GLB
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=input_glb)
    
    results = {}
    for img in bpy.data.images:
        if img.name in image_names:
            try:
                stats = get_pixel_stats(img)
                results[img.name] = stats
            except Exception as e:
                results[img.name] = {"error": str(e)}
    
    with open(output_json, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"TEXTURE_STATS_DONE: {len(results)} images analyzed")

main()
