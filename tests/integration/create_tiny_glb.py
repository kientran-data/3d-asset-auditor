import bpy
import os
import tempfile
import numpy as np

# Clear default scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# Add a cube (2m x 2m x 2m)
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
cube = bpy.context.active_object

# Create a UV Map named "ExplicitUV"
if not cube.data.uv_layers:
    cube.data.uv_layers.new(name="ExplicitUV")
else:
    cube.data.uv_layers[0].name = "ExplicitUV"

# Add a simple material
mat = bpy.data.materials.new(name="SimpleMaterial")
mat.use_nodes = True
if cube.data.materials:
    cube.data.materials[0] = mat
else:
    cube.data.materials.append(mat)

nodes = mat.node_tree.nodes
links = mat.node_tree.links

principled = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
mat_output = next(n for n in nodes if n.type == 'OUTPUT_MATERIAL')

def create_image(name, color=(1.0, 1.0, 1.0, 1.0)):
    img = bpy.data.images.new(name, width=16, height=16, alpha=True)
    pixels = np.array(color * 16 * 16, dtype=np.float32)
    img.pixels = pixels.tolist()
    img.pack()
    return img

img_base_color = create_image("BaseColorTex", (1.0, 0.0, 0.0, 1.0))
img_roughness = create_image("RoughnessTex", (0.5, 0.5, 0.5, 1.0))
img_normal = create_image("NormalTex", (0.5, 0.5, 1.0, 1.0))
img_disp = create_image("DispTex", (0.0, 0.0, 0.0, 1.0))

# UV Map node
uv_node = nodes.new('ShaderNodeUVMap')
uv_node.uv_map = "ExplicitUV"

def setup_texture_node(img, location):
    tex_node = nodes.new('ShaderNodeTexImage')
    tex_node.image = img
    tex_node.location = location
    links.new(uv_node.outputs[0], tex_node.inputs['Vector'])
    return tex_node

# Base Color
tex_bc = setup_texture_node(img_base_color, (-600, 300))
links.new(tex_bc.outputs['Color'], principled.inputs['Base Color'])

# Roughness
tex_rough = setup_texture_node(img_roughness, (-600, 0))
links.new(tex_rough.outputs['Color'], principled.inputs['Roughness'])

# Normal
tex_norm = setup_texture_node(img_normal, (-900, -300))
normal_map_node = nodes.new('ShaderNodeNormalMap')
normal_map_node.location = (-600, -300)
links.new(tex_norm.outputs['Color'], normal_map_node.inputs['Color'])
links.new(normal_map_node.outputs['Normal'], principled.inputs['Normal'])

# Displacement
tex_disp = setup_texture_node(img_disp, (-600, -600))
links.new(tex_disp.outputs['Color'], mat_output.inputs['Displacement'])

# Export as GLB
import sys
output_path = "/tmp/tiny_fixture.glb"
if "--" in sys.argv:
    idx = sys.argv.index("--")
    if idx + 1 < len(sys.argv):
        output_path = sys.argv[idx + 1]
elif len(sys.argv) > 1 and not sys.argv[-1].endswith('.py'):
    output_path = sys.argv[-1]
    
bpy.ops.export_scene.gltf(filepath=output_path, export_format='GLB')
