import bpy

# Clear default scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# Add a cube (2m x 2m x 2m)
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
cube = bpy.context.active_object

# Add a simple material
mat = bpy.data.materials.new(name="SimpleMaterial")
mat.use_nodes = True
if cube.data.materials:
    cube.data.materials[0] = mat
else:
    cube.data.materials.append(mat)

# Export as GLB
bpy.ops.export_scene.gltf(filepath="/tmp/tiny_fixture.glb", export_format='GLB')
