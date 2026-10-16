"""Test frog maths, layout, parts, presets and export without Blender.

Run: python tests/test_core.py   (needs the Model Rail Generator next to this repo; see _paths.py)
"""

import math
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402

rail = _paths.publish_rail_api()
from switch_frog import api  # noqa: E402
from switch_frog.frog import FrogSpec, compute_layout  # noqa: E402
from switch_frog.geometry import (extrude_polygon, offset_polyline, polygon_area,  # noqa: E402
                                  triangulate_polygon)


def check(md, label):
    """Assert ``md`` is a closed solid with outward-facing normals."""
    assert md.is_manifold(), label + " not manifold"
    assert md.volume() > 0, label + " inverted"


# ------------------------------------------------------------- frog numbers
assert abs(api.frog_angle_deg(6) - 9.527283) < 1e-5, api.frog_angle_deg(6)
for n in (1.5, 4, 6, 7.5, 10, 20):
    assert abs(api.frog_number_from_angle(api.frog_angle_deg(n)) - n) < 1e-9

# ---------------------------------------------------------- geometry helpers
sq = offset_polyline([(0, 0), (0, 10), (10, 20)], 1.0)
assert abs(sq[0][0] - 1.0) < 1e-12 and abs(sq[0][1]) < 1e-12           # right of +Y travel
box = extrude_polygon([(0, 0), (4, 0), (4, 3), (2, 1), (0, 3)], 0, 2)   # non-convex
check(box, "extrude")
assert abs(box.volume() - 2 * polygon_area([(0, 0), (4, 0), (4, 3), (2, 1), (0, 3)])) < 1e-9
poly = [(0, 0), (4, 0), (4, 3), (2, 1), (0, 3)]
tri_area = sum(abs(polygon_area([poly[a], poly[b], poly[c]])) for a, b, c in triangulate_polygon(poly))
assert abs(tri_area - polygon_area(poly)) < 1e-9

# ------------------------------------------------- every built-in preset builds
for name in api.list_builtin_presets():
    spec = api.get_preset(name)
    assert spec.is_valid(), (name, spec.validate())
    assert spec.rail_preset in rail.list_builtin_presets(), (name, spec.rail_preset)
    prof = rail.get_preset(spec.rail_preset)
    lay = api.frog_layout(spec)
    assert not lay.errors, (name, lay.errors)
    assert not lay.warnings, (name, lay.warnings)
    parts = api.generate_frog_parts(spec)
    for pn, md in parts.items():
        check(md, f"{name} {pn}")
    md = api.generate_frog_mesh(spec)
    (x0, y0, z0), (x1, y1, z1) = md.bounds()
    assert abs(z1 - prof.height) < 1e-9 and abs(z0) < 1e-9, (name, z0, z1)
    assert y0 < lay.y_toe + 0.5 and y1 > lay.y_heel - 0.5
    # throat = flangeway; the wing rail runs one flangeway outside the point
    assert abs(lay.throat_width - spec.flangeway_width) < 1e-9
    xw, yw = lay.left_wing[2]
    assert abs((-yw * lay.t) - xw - spec.flangeway_width) < 1e-9
    print(f"{name:16s} {spec.angle_deg:6.3f} deg  toe {lay.toe_length:6.2f}  heel {lay.heel_length:6.2f}"
          f"  length {lay.length:6.2f} mm  parts {len(parts)}")

# fill modes and plate change the parts and bottom
spec = api.get_preset("HO #6 Code 83")
assert "Fill" not in api.generate_frog_parts(spec.copy(fill="NONE", base_plate=True))
lay = api.frog_layout(spec.copy(fill="NONE"))
assert any("separate pieces" in w for w in lay.warnings)
md = api.generate_frog_mesh(spec.copy(base_plate=True, plate_thickness=0.5))
assert abs(md.bounds()[0][2] + 0.5) < 1e-9
lay = api.frog_layout(spec)
assert abs(lay.fill_top - (rail.get_preset("Code 83").height - spec.flangeway_depth)) < 1e-9
assert abs(api.frog_layout(spec.copy(fill="BASE")).fill_top
           - rail.get_preset("Code 83").base_thickness) < 1e-9

# point drop lowers only the tip of the V
v = api.generate_frog_parts(spec.copy(point_drop=0.2, point_ramp=3.0))["V Point"]
tip_top = max(z for x, y, z in v.vertices if abs(y - lay.y_point) < 1e-9)
assert abs(tip_top - (rail.get_preset("Code 83").height - 0.2)) < 1e-9

# larger frog numbers make longer, narrower frogs
l6, l10 = api.frog_layout(spec), api.frog_layout(spec.copy(frog_number=10))
assert l10.length > l6.length and l10.angle_deg < l6.angle_deg

# manual lengths
lay = api.frog_layout(spec.copy(length_mode="MANUAL", toe_length=20, heel_length=40))
assert lay.toe_length == 20 and lay.heel_length == 40

# alignment: LEFT_HAND turns the right-hand route's gauge line onto +Y
p = api.generate_frog_parts(spec, alignment="LEFT_HAND")["Point Rail R"]
c = api.generate_frog_parts(spec)["Point Rail R"]
rot = spec.angle_deg / 2
a = math.radians(rot)
x, y, z = c.vertices[0]
assert all(abs(u - w) < 1e-9 for u, w in zip(p.vertices[0],
                                             (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a), z)))
gx = [x * math.cos(a) - y * math.sin(a) for x, y in [(lay_y * l6.t, lay_y) for lay_y in (5.0, 30.0)]]
assert abs(gx[0]) < 1e-9 and abs(gx[1]) < 1e-9

# ------------------------------------------------- flangeway vs scale and rail
# An HO flangeway (0.80 mm deep) left on code 250 rail is flagged...
ho = api.get_preset("HO #4 Code 83")
warn = api.frog_layout(ho, rail="Code 250").warnings
assert any("shallow" in w for w in warn) and any("narrow" in w for w in warn), warn
# ...and the NMRA values for the scale clear the warnings and deepen the floor
fixed = api.with_standard_flangeway(ho, "Fn3")
lay = api.frog_layout(fixed, rail="Code 250")
assert not lay.warnings, lay.warnings
assert rail.get_preset("Code 250").height - lay.fill_top >= api.flangeway_standard("Fn3").min_depth
assert api.frog_layout(ho.copy(flangeway_depth=0.6)).warnings          # under the HO minimum
assert api.list_scales()[0] == "Z" and "Fn3" in api.list_scales()
assert api.get_preset("Fn3 #6 Code 250").flangeway_depth == api.flangeway_standard("Fn3").depth
assert FrogSpec(scale="XX").validate()
print("flangeway checks ok:", warn[0])

# ---------------------------------------------------------------- validation
prof83 = rail.get_preset("Code 83")
assert compute_layout(spec.copy(point_width=5.0), prof83).errors
assert compute_layout(spec.copy(length_mode="MANUAL", toe_length=2.0), prof83).errors
assert compute_layout(spec.copy(point_drop=1.0), prof83).errors
assert FrogSpec(fill="SOLID").validate() and FrogSpec(frog_number=0.5).validate()
try:
    api.generate_frog_parts(spec.copy(point_width=5.0))
    raise SystemExit("bad spec accepted")
except api.FrogError as ex:
    print("validation ok:", ex)

# ------------------------------------------------------------ spec resolution
assert api.resolve_spec(8).frog_number == 8
assert api.resolve_spec(spec.to_dict()) == spec
assert api.resolve_spec("N #10 Code 55").rail_preset == "Code 55"
assert api.generate_frog_parts(7, rail=70)          # any rail code works
assert api.frog_layout(spec, rail=prof83.copy(head_width=1.2)).y_split > l6.y_split
try:
    api.frog_layout(spec.copy(rail_preset=""))
    raise SystemExit("no rail accepted")
except api.FrogError:
    pass

# -------------------------------------------------------------------- presets
tmp = tempfile.mkdtemp()
api.set_preset_file(os.path.join(tmp, "p.json"))
mine = spec.copy(name="HO #7 Code 70 measured", frog_number=7, rail_preset="Code 70")
api.save_preset(mine)
api.set_preset_file(os.path.join(tmp, "p.json"))           # force reload from disk
assert api.get_preset("HO #7 Code 70 measured") == mine
assert api.list_presets()[-1] == "HO #7 Code 70 measured"
for bad in (lambda: api.save_preset(spec), lambda: api.delete_preset("HO #6 Code 83"),
            lambda: api.save_preset(spec.copy(name="x", flangeway_width=0))):
    try:
        bad()
        raise SystemExit("preset rule not enforced")
    except api.PresetError:
        pass
api.export_presets(os.path.join(tmp, "share.json"))
api.delete_preset("HO #7 Code 70 measured")
assert api.import_presets(os.path.join(tmp, "share.json")) == ["HO #7 Code 70 measured"]

# --------------------------------------------------------------------- export
md = api.generate_frog_mesh("HO #6 Code 83")
f = api.export_frog(md, os.path.join(tmp, "f.stl"))
data = open(f, "rb").read()
n = struct.unpack("<I", data[80:84])[0]
assert len(data) == 84 + 50 * n == 84 + 50 * len(md.triangles())
assert data.startswith(b"Switch Frog Generator")
api.export_frog(md, os.path.join(tmp, "f.obj"))
api.export_frog(md, os.path.join(tmp, "a.stl"), "STL_ASCII")

# ------------------------------------------------------ without the rail add-on
saved = sys.modules.pop("model_rail_api")
assert api.rail_api_status() and api.list_rail_presets() == []
try:
    api.frog_layout(spec)
    raise SystemExit("worked without the rail API")
except api.FrogError:
    pass
sys.modules["model_rail_api"] = saved

print("STL tris", n, "OK - all core tests passed")
