"""Ultima3D/Blender English rebuild for baked-art HUD Chinese text.

One-and-done localization pass for the roleheadskin baked-art labels
(decoded in websites/everenfell/docs/swf-phaser-manifest.md §7):
  bitmap 214 (52x23, 儲值 white on brown-gold) -> "TOP UP"
  bitmap 253 (26x26, 強 white on red icon)     -> "STR"
  bitmap 300 (44x18, 戦闘力 gold w/ outline)    -> "POWER"

Method: Blender 5.x headless. Original PNG on an emission plane (pixel
geometry preserved 1 unit = 1 px via ortho_scale), Chinese glyph area
covered by a style-matched backing plate sampled from the button, then
centered English text in a matching weight/color with a dark backing
copy for the outline. Outputs go to images-en/ (originals untouched).

Usage:
  blender --background --python scripts/asset_tools/localize_hud_buttons.py
"""
import os

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SRC = os.path.join(ROOT, 'websites', 'everenfell', 'assets', 'ui', 'hud-chat', 'images')
OUT = os.path.join(ROOT, 'websites', 'everenfell', 'assets', 'ui', 'hud-chat', 'images-en')
os.makedirs(OUT, exist_ok=True)

JOBS = [
    # src, out, text, size, color, backing, cover_box(x0,y0,x1,y1 px,
    # bottom-left origin), gradient stops (None = flat emission).
    # cover=None + art=False means a from-scratch text rebuild (used when
    # the original glyphs span the whole frame, e.g. combat-power label).
    {'src': '214-jpeg3.png', 'out': '214-en.png', 'text': 'TOP UP',
     'size': 10.0, 'color': (1.0, 0.96, 0.88, 1.0),
     'backing': (0.10, 0.05, 0.02, 1.0), 'cover': (4, 4, 48, 19),
     'gradient': None, 'art': True},
    {'src': '253-jpeg3.png', 'out': '253-en.png', 'text': 'STR',
     'size': 8.0, 'color': (1.0, 0.97, 0.92, 1.0),
     'backing': (0.35, 0.07, 0.04, 1.0), 'cover': (7, 6, 19, 20),
     'gradient': None, 'art': True},
    {'src': '300-jpeg3.png', 'out': '300-en.png', 'text': 'POWER',
     'size': 9.0, 'color': (1.0, 0.80, 0.28, 1.0),
     'backing': (0.12, 0.05, 0.02, 1.0), 'cover': None, 'outline': 1.15,
     'gradient': [(0.0, (0.72, 0.38, 0.08, 1.0)),
                  (0.5, (1.0, 0.85, 0.35, 1.0)),
                  (1.0, (1.0, 0.97, 0.70, 1.0))], 'art': False},
]

FONT_CANDIDATES = [
    'C:/Windows/Fonts/georgiab.ttf',
    'C:/Windows/Fonts/timesbd.ttf',
    'C:/Windows/Fonts/arialbd.ttf',
]


def pick_font():
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return bpy.data.fonts.load(path)
            except RuntimeError:
                continue
    return None


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for block in list(datablocks):
            datablocks.remove(block)


def emission_material(name, color, image=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.blend_method = 'BLEND'
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new('ShaderNodeOutputMaterial')
    if image is not None:
        tex = nodes.new('ShaderNodeTexImage')
        tex.image = image
        tex.interpolation = 'Closest'  # keep pixel-art edges crisp
        emit = nodes.new('ShaderNodeEmission')
        links.new(tex.outputs['Color'], emit.inputs['Color'])
        transp = nodes.new('ShaderNodeBsdfTransparent')
        mix = nodes.new('ShaderNodeMixShader')
        links.new(tex.outputs['Alpha'], mix.inputs['Fac'])
        links.new(transp.outputs['BSDF'], mix.inputs[1])
        links.new(emit.outputs['Emission'], mix.inputs[2])
        links.new(mix.outputs['Shader'], out.inputs['Surface'])
    else:
        emit = nodes.new('ShaderNodeEmission')
        emit.inputs['Color'].default_value = color
        links.new(emit.outputs['Emission'], out.inputs['Surface'])
    return mat


def gradient_material(name, stops):
    """Vertical gold-gradient emission driven by stroke UVs."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.blend_method = 'BLEND'
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new('ShaderNodeOutputMaterial')
    texco = nodes.new('ShaderNodeTexCoord')
    sep = nodes.new('ShaderNodeSeparateXYZ')
    ramp = nodes.new('ShaderNodeValToRGB')
    for i, (pos, color) in enumerate(stops):
        elem = ramp.color_ramp.elements[i] if i < 2 else \
            ramp.color_ramp.elements.new(pos)
        elem.position = pos
        elem.color = color
    emit = nodes.new('ShaderNodeEmission')
    links.new(texco.outputs['UV'], sep.inputs['Vector'])
    links.new(sep.outputs['Y'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], emit.inputs['Color'])
    links.new(emit.outputs['Emission'], out.inputs['Surface'])
    return mat


def build_job(job, font):
    src, out_name = job['src'], job['out']
    text, size = job['text'], job['size']
    color, backing = job['color'], job['backing']
    cover, gradient, use_art = job['cover'], job['gradient'], job['art']
    outline = job.get('outline', 1.22)
    clear_scene()
    if use_art:
        img = bpy.data.images.load(os.path.join(SRC, src))
        img.alpha_mode = 'STRAIGHT'
        w, h = img.size
        if w == 0 or h == 0:
            raise RuntimeError('could not read size of %s' % src)
    else:
        # Same frame size as the source text art (300: 44x18).
        ref = bpy.data.images.load(os.path.join(SRC, src))
        w, h = ref.size
        bpy.data.images.remove(ref)

    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.filepath = os.path.join(OUT, out_name)

    cam_data = bpy.data.cameras.new('Cam')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = float(w)
    cam = bpy.data.objects.new('Cam', cam_data)
    scene.collection.objects.link(cam)
    cam.location = (w / 2.0, h / 2.0, 10.0)
    scene.camera = cam

    if use_art:
        # Original art plane (1 unit = 1 px).
        bpy.ops.mesh.primitive_plane_add(size=1.0)
        plane = bpy.context.active_object
        plane.scale = (w, h, 1.0)
        plane.location = (w / 2.0, h / 2.0, 0.0)
        plane.data.materials.append(
            emission_material('Art', (1, 1, 1, 1), image=img))

    if cover is not None:
        # Backing plate over the Chinese glyphs, sampled from button tones.
        x0, y0, x1, y1 = cover
        bpy.ops.mesh.primitive_plane_add(size=1.0)
        plate = bpy.context.active_object
        plate.scale = (x1 - x0, y1 - y0, 1.0)
        plate.location = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, 0.05)
        plate.data.materials.append(emission_material('Plate', backing))

    # Dark backing copy for the outline, then the face text.
    face_mat = gradient_material('FaceGrad', gradient) if gradient \
        else emission_material('Face', color)
    for label, scale, z, mat in (('Back', outline, 0.08,
                                 emission_material('Back', backing)),
                                ('Face', 1.0, 0.1, face_mat)):
        bpy.ops.object.text_add(location=(w / 2.0, h / 2.0 - 0.5, z))
        tob = bpy.context.active_object
        tob.data.body = text
        tob.data.align_x = 'CENTER'
        tob.data.align_y = 'CENTER'
        tob.data.size = size * scale
        if font is not None:
            tob.data.font = font
        tob.data.materials.append(mat)

    bpy.ops.render.render(write_still=True)
    print('wrote %s (%dx%d)' % (out_name, w, h))


def main():
    font = pick_font()
    print('font: %s' % (font.filepath if font else 'Bfont (built-in)'))
    for job in JOBS:
        build_job(job, font)


main()
