"""Socket portraits: pre-composited circular head crops (Phaser 4 fix).

The roleheadskin portrait photo is code-attached in the SWF, and the
only authentic face art is the create-ui class stills (171x171 badges
with their own select-screen ring on transparency). Phaser 4.2 WebGL
rejects GeometryMask via setMask ("Create a Mask filter instead"), so
runtime masking is out: this script crops the face interior out of each
badge and bakes a circular alpha mask here instead. Outputs
images-en/portrait-{A,B,C,D}.png at 68x68 (socket r34), which UIScene
draws unmasked.

Per-job crop boxes are estimates of the badge's inner face circle;
verify in-client and adjust CROP below.

Usage:
  blender --background --python scripts/asset_tools/build_portraits.py
"""
import os

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      '..', '..'))
SRC = os.path.join(ROOT, 'websites', 'everenfell', 'assets', 'ui',
                   'create-ui', 'images')
OUT = os.path.join(ROOT, 'websites', 'everenfell', 'assets', 'ui',
                   'hud-chat', 'images-en')
os.makedirs(OUT, exist_ok=True)

# job -> (still id, crop x0, y0, x1, y1 in still px, bottom-left origin).
CROP = {
    'A': (32, 25, 28, 145, 148),
    'B': (16, 25, 28, 145, 148),
    'C': (24, 25, 28, 145, 148),
    'D': (1, 25, 28, 145, 148),
}

SIZE = 68  # socket diameter (r34)


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for block in list(datablocks):
            datablocks.remove(block)


def build(job, still_id, box):
    clear_scene()
    img = bpy.data.images.load(
        os.path.join(SRC, '%d-jpeg3.png' % still_id))
    img.alpha_mode = 'STRAIGHT'
    w, h = img.size
    x0, y0, x1, y1 = box

    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = SIZE
    scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    out_name = 'portrait-%s.png' % job
    scene.render.filepath = os.path.join(OUT, out_name)

    cam_data = bpy.data.cameras.new('Cam')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = 1.0
    cam = bpy.data.objects.new('Cam', cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.5, 0.5, 10.0)
    scene.camera = cam

    mat = bpy.data.materials.new('Portrait')
    mat.use_nodes = True
    mat.blend_method = 'BLEND'
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new('ShaderNodeOutputMaterial')
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = img
    tex.interpolation = 'Cubic'
    mapping = nodes.new('ShaderNodeMapping')
    mapping.vector_type = 'POINT'
    mapping.inputs['Location'].default_value = (
        x0 / w, y0 / h, 0.0)
    mapping.inputs['Scale'].default_value = (
        (x1 - x0) / w, (y1 - y0) / h, 1.0)
    texco = nodes.new('ShaderNodeTexCoord')
    links.new(texco.outputs['UV'], mapping.inputs['Vector'])
    links.new(mapping.outputs['Vector'], tex.inputs['Vector'])
    # Circular alpha in original-still UV space (square crop, square
    # pixels, so the radius is isotropic).
    cx, cy = ((x0 + x1) / 2 / w, (y0 + y1) / 2 / h)
    radius = (x1 - x0) / w / 2
    sub = nodes.new('ShaderNodeVectorMath')
    sub.operation = 'SUBTRACT'
    sub.inputs[1].default_value = (cx, cy, 0.0)
    links.new(texco.outputs['UV'], sub.inputs[0])
    dist = nodes.new('ShaderNodeVectorMath')
    dist.operation = 'LENGTH'
    links.new(sub.outputs['Vector'], dist.inputs[0])
    inside = nodes.new('ShaderNodeMath')
    inside.operation = 'LESS_THAN'
    inside.inputs[1].default_value = radius
    links.new(dist.outputs['Value'], inside.inputs[0])
    alpha = nodes.new('ShaderNodeMath')
    alpha.operation = 'MULTIPLY'
    links.new(tex.outputs['Alpha'], alpha.inputs[0])
    links.new(inside.outputs['Value'], alpha.inputs[1])
    emit = nodes.new('ShaderNodeEmission')
    links.new(tex.outputs['Color'], emit.inputs['Color'])
    transp = nodes.new('ShaderNodeBsdfTransparent')
    mix = nodes.new('ShaderNodeMixShader')
    links.new(alpha.outputs['Value'], mix.inputs['Fac'])
    links.new(transp.outputs['BSDF'], mix.inputs[1])
    links.new(emit.outputs['Emission'], mix.inputs[2])
    links.new(mix.outputs['Shader'], out.inputs['Surface'])

    bpy.ops.mesh.primitive_plane_add(size=1.0)
    plane = bpy.context.active_object
    plane.location = (0.5, 0.5, 0.0)
    plane.data.materials.append(mat)
    bpy.ops.render.render(write_still=True)
    print('wrote %s (crop %s)' % (out_name, box))


def main():
    for job, (still_id, x0, y0, x1, y1) in CROP.items():
        build(job, still_id, (x0, y0, x1, y1))


main()
