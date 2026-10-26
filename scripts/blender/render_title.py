"""Render hero text in headless Blender (transparent PNG).

Usage (repo root):
  blender.exe --background --python scripts/blender/render_title.py -- \\
      "CREATE" out.png [size]

Proves the Blender leg of the graphics pipeline: real font shaping,
beveled metallic materials, studio lighting, transparent film. Used for
NEW English text art only — authentic 2D recovery stays in PIL.
"""

import sys

import bpy


def main():
    args = sys.argv[sys.argv.index('--') + 1:]
    text, outpath = args[0], args[1]
    fontpath = args[2] if len(args) > 2 else \
        'C:/Windows/Fonts/georgiab.ttf'

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    try:
        scene.render.engine = 'BLENDER_EEVEE'
    except TypeError:  # older Blender naming
        scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.render.film_transparent = True
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 400
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    curve = bpy.data.curves.new('TitleCurve', type='FONT')
    curve.body = text
    curve.font = bpy.data.fonts.load(fontpath)
    curve.size = 1.0
    curve.align_x = 'CENTER'
    curve.align_y = 'CENTER'
    curve.extrude = 0.06
    curve.bevel_depth = 0.018
    curve.bevel_resolution = 3
    obj = bpy.data.objects.new('Title', curve)
    scene.collection.objects.link(obj)

    mat = bpy.data.materials.new('TitleGold')
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (1.0, 0.78, 0.42, 1.0)
    bsdf.inputs['Metallic'].default_value = 0.85
    bsdf.inputs['Roughness'].default_value = 0.32
    obj.data.materials.append(mat)

    for name, energy, rot in (('Key', 3.0, (0.6, 0.0, 0.5)),
                              ('Fill', 1.2, (0.6, 0.0, -0.6)),
                              ('Rim', 2.0, (-0.4, 0.0, 3.14))):
        lamp = bpy.data.lights.new(name, type='SUN')
        lamp.energy = energy
        lamp_obj = bpy.data.objects.new(name, lamp)
        scene.collection.objects.link(lamp_obj)
        lamp_obj.rotation_euler = rot

    bpy.context.view_layer.update()
    w = max(obj.dimensions.x, 0.001)
    cam_data = bpy.data.cameras.new('TitleCam')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = w * 1.12
    cam = bpy.data.objects.new('TitleCam', cam_data)
    scene.collection.objects.link(cam)
    cam.location = (obj.dimensions.x / 2 - w / 2 + 0.0, 0.0, 10.0)
    # Center on the text bounds.
    cam.location = ((obj.bound_box[0][0] + obj.bound_box[4][0]) / 2,
                    0.0, 10.0)
    scene.camera = cam

    scene.render.filepath = outpath
    bpy.ops.render.render(write_still=True)
    print('blender title rendered: %s' % outpath)


main()
