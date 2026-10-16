"""Exercise the add-on inside Blender: operators, presets, merging, rebuild, export and alignment.

Run: python tests/test_blender.py (with pip install bpy) or
blender -b --factory-startup --python tests/test_blender.py.
"""

import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402,F401  (sys.path and temporary preset files)

import bpy  # noqa: E402  (import before bmesh)
import bmesh  # noqa: E402
import model_rail_generator as rail_addon  # noqa: E402
import switch_frog as addon  # noqa: E402

rail_addon.register()
addon.register()
import switch_frog_api as frog  # noqa: E402

print("API", frog.API_VERSION)
sc = bpy.context.scene
s = sc.switch_frog


def manifold_stats(obj):
    """(is manifold, volume mm^3, shells) of a mesh object's own data."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    ok = all(e.is_manifold for e in bm.edges) and all(len(e.link_faces) == 2 for e in bm.edges)
    f = 1.0 / frog.mm_to_blender_units()
    vol = bm.calc_volume() * f ** 3
    seen, shells = set(), 0
    for v in bm.verts:
        if v.index in seen:
            continue
        shells += 1
        stack = [v]
        while stack:
            x = stack.pop()
            if x.index in seen:
                continue
            seen.add(x.index)
            stack.extend(e.other_vert(x) for e in x.link_edges)
    bm.free()
    return ok, vol, shells


# defaults come from the HO #6 Code 83 preset
assert s.preset == "HO #6 Code 83", s.preset
assert s.rail_preset == "Code 83" and s.frog_number == 6.0
print("rail menu:", s.rail_menu, "| presets:", len(frog.list_presets()))

# generate with the operator, every fill mode
for fill in ("FLOOR", "BASE", "NONE"):
    s.fill = fill
    s.base_plate = fill == "NONE"
    assert bpy.ops.switch_frog.generate() == {'FINISHED'}, s.last_report
    o = bpy.context.active_object
    ok, vol, shells = manifold_stats(o)
    print(f"{fill:5s} plate={s.base_plate}: {o.name}, {len(o.data.polygons)} faces, "
          f"manifold={ok}, shells={shells}, volume={vol:.2f} mm3")
    assert ok and shells == 1 and vol > 0
    assert frog.is_frog_object(o) and frog.get_frog_params(o)["spec"]["fill"] == fill

# choosing a preset loads its rail and number
s.preset = "N #10 Code 55"
assert s.frog_number == 10 and s.rail_preset == "Code 55" and abs(s.flangeway_width - 0.76) < 1e-6
s.preset = "HO #6 Code 83"

# rail menu follows rail presets, including user rail presets
my_rail = rail_addon.api.get_preset("Code 83").copy(name="My Code 83", head_width=1.0)
rail_addon.api.save_preset(my_rail)
s.rail_menu = "My Code 83"
assert s.rail_preset == "My Code 83"

# Set Flangeway fills the NMRA values for the chosen scale
s.scale = "Fn3"
assert bpy.ops.switch_frog.set_flangeway() == {'FINISHED'}
assert abs(s.flangeway_width - 2.97) < 1e-6 and abs(s.flangeway_depth - 1.85) < 1e-6
assert s.to_spec().scale == "Fn3"
s.preset = "HO #6 Code 83"
assert s.scale == "HO" and abs(s.flangeway_depth - 0.80) < 1e-6
s.rail_menu = "My Code 83"

# save / reload / delete a frog preset
s.frog_number = 7
s.preset_name = "HO #7 my rail"
assert bpy.ops.switch_frog.save_preset('EXEC_DEFAULT') == {'FINISHED'}
assert "HO #7 my rail" in frog.list_user_presets() and s.preset == "HO #7 my rail"
saved = frog.get_preset("HO #7 my rail")
assert saved.rail_preset == "My Code 83" and saved.frog_number == 7
s.preset = "HO #4 Code 83"
assert s.frog_number == 4
s.preset = "HO #7 my rail"
assert s.frog_number == 7 and s.rail_preset == "My Code 83"
assert bpy.ops.switch_frog.delete_preset('EXEC_DEFAULT') == {'FINISHED'}
assert "HO #7 my rail" not in frog.list_user_presets()

# update selected frog in place: keeps object, changes number
s.preset = "HO #6 Code 83"
assert bpy.ops.switch_frog.generate() == {'FINISHED'}
o = bpy.context.active_object
o.location.x = 0.05
len6 = frog.object_to_mesh_data(o).bounds()
s.frog_number = 8
assert bpy.ops.switch_frog.rebuild() == {'FINISHED'}
assert frog.get_frog_params(o)["spec"]["frog_number"] == 8 and abs(o.location.x - 0.05) < 1e-9
len8 = frog.object_to_mesh_data(o).bounds()
print("length #6 vs #8 (mm):", round(len6[1][1] - len6[0][1], 2), round(len8[1][1] - len8[0][1], 2))
assert len8[1][1] - len8[0][1] > len6[1][1] - len6[0][1]

# export: selected, then from settings
tmp = tempfile.mkdtemp()
out = os.path.join(tmp, "frog.stl")
assert bpy.ops.switch_frog.export('EXEC_DEFAULT', filepath=out, format="STL") == {'FINISHED'}
n_obj = len(bpy.data.objects)
for o2 in bpy.context.selected_objects:
    o2.select_set(False)
out2 = os.path.join(tmp, "frog_settings.obj")
assert bpy.ops.switch_frog.export('EXEC_DEFAULT', filepath=out2, format="OBJ") == {'FINISHED'}
assert len(bpy.data.objects) == n_obj, "temporary export object left behind"
print("exported", os.path.getsize(out), "and", os.path.getsize(out2), "bytes")

# API: alignment puts a gauge line along +Y; frog number from a plain number
spec = frog.get_preset("HO #6 Code 83")
lay = frog.frog_layout(spec)
o = frog.create_frog_object(spec, alignment="LEFT_HAND", merged=False)
md = frog.object_to_mesh_data(o)
rot = frog.get_frog_params(o)["alignment"]
assert rot == "LEFT_HAND"
o = frog.create_frog_object(8, rail=83)
assert frog.get_frog_params(o)["spec"]["frog_number"] == 8
# rebuild after the rail preset is gone uses the stored profile
o = frog.create_frog_object(spec, rail="My Code 83")
rail_addon.api.delete_preset("My Code 83")
frog.rebuild_frog_object(o, spec=spec.copy(frog_number=5))
assert abs(frog.get_frog_params(o)["profile"]["head_width"] - 1.0) < 1e-9

# mm-unit scene
sc.unit_settings.scale_length = 0.001
o = frog.create_frog_object(spec)
top = max(v.co.z for v in o.data.vertices)
print("mm scene: rail top", round(top, 4), "BU (expect", round(rail_addon.api.get_preset("Code 83").height, 4), ")")
assert abs(top - rail_addon.api.get_preset("Code 83").height) < 1e-3
sc.unit_settings.scale_length = 1.0

# without the rail add-on, the panel reports it and the API raises FrogError
rail_addon.unregister()
assert frog.rail_api_status() and frog.list_rail_presets() == []
try:
    frog.frog_layout(spec)
    raise SystemExit("should need the rail add-on")
except frog.FrogError as ex:
    print("no rail add-on:", ex)
try:  # in background mode an operator's ERROR report is raised as RuntimeError
    assert bpy.ops.switch_frog.generate() == {'CANCELLED'}
except RuntimeError as ex:
    assert "Model Rail Generator" in str(ex)
rail_addon.register()

addon.unregister()
rail_addon.unregister()
assert "switch_frog_api" not in sys.modules
print("ALL BLENDER TESTS PASSED")
