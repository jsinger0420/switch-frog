"""Public API of the Switch Frog Generator add-on.

Other add-ons should use only what is listed in ``__all__``; everything else
is internal and may change.  The API follows semantic versioning through
``API_VERSION``: a change in the major number means a breaking change.

Getting hold of the API from another add-on::

    import sys
    def get_frog_api(min_version=(1, 0, 0)):
        api = sys.modules.get("switch_frog_api")      # alias set on register
        if api is None:
            raise RuntimeError("Enable the 'Switch Frog Generator' add-on")
        if api.API_VERSION[0] != min_version[0] or api.API_VERSION < min_version:
            raise RuntimeError(f"Need Switch Frog API {min_version}, found {api.API_VERSION}")
        return api

    frog = get_frog_api()
    obj = frog.create_frog_object("HO #6 Code 83")            # a preset name
    obj = frog.create_frog_object(frog.get_preset("HO #6 Code 83").copy(frog_number=7),
                                  rail="Code 70", alignment="LEFT_HAND")

Rail profiles come from the Model Rail Generator add-on, found through its
``model_rail_api`` alias, so that add-on must be enabled.  Outside Blender,
import ``model_rail_generator.api`` and put it in ``sys.modules`` under
that name first.

Units: every length in this API is millimetres at actual model size.
Conversion to Blender scene units happens only when objects are created or
read (see ``mm_to_blender_units``).  The origin is the frog's theoretical
point, the centreline runs along +Y toward the heel and the rail base sits
on Z = 0 (see ``frog.py`` for the full layout).
"""

from __future__ import annotations

import json
import math
import os
import sys

from .exporters import FORMATS, export_mesh
from .frog import (ALIGNMENTS, FILL_MODES, LENGTH_MODES, FrogLayout, FrogSpec,
                   alignment_rotation, build_parts, compute_layout, frog_angle_deg,
                   frog_number_from_angle)
from .geometry import MeshData, merge
from .presets import BUILTIN_PRESETS, DEFAULT_PRESET, PresetError, PresetLibrary
from .standards import SCALES, ScaleStandard, get_standard

API_VERSION = (1, 1, 0)

#: Custom property key under which frog parameters are stored on objects.
FROG_PROP_KEY = "switch_frog"
#: Module alias the Model Rail Generator publishes its API under.
RAIL_API_ALIAS = "model_rail_api"
#: Oldest Rail API this add-on works with.
RAIL_API_MIN = (1, 0, 0)

__all__ = [
    "API_VERSION", "FROG_PROP_KEY", "FORMATS", "ALIGNMENTS", "FILL_MODES", "LENGTH_MODES",
    # data types and errors
    "FrogSpec", "FrogLayout", "MeshData", "FrogError", "PresetError",
    # frog numbers and scale standards
    "frog_angle_deg", "frog_number_from_angle", "ScaleStandard", "list_scales",
    "flangeway_standard", "with_standard_flangeway",
    # presets
    "list_presets", "list_builtin_presets", "list_user_presets", "get_preset",
    "save_preset", "delete_preset", "is_builtin_preset", "default_preset_name",
    "get_preset_file", "set_preset_file", "import_presets", "export_presets",
    "resolve_spec",
    # rail profiles (Model Rail Generator)
    "get_rail_api", "rail_api_status", "list_rail_presets", "resolve_rail_profile",
    # geometry (no bpy needed)
    "frog_layout", "generate_frog_parts", "generate_frog_mesh",
    # blender objects
    "mm_to_blender_units", "create_frog_object", "rebuild_frog_object",
    "is_frog_object", "get_frog_params", "object_to_mesh_data",
    # export
    "export_frog",
]


class FrogError(ValueError):
    """Raised when a frog can't be built: bad settings or no rail profile (the message says why)."""


# ======================================================= scale standards
def list_scales() -> list[str]:
    """Scale keys with NMRA flangeway standards, smallest first (Z, N, TT, HO, ... LS)."""
    return list(SCALES)


def flangeway_standard(scale: str) -> ScaleStandard:
    """NMRA flangeway limits for a scale: ``.max_width``, ``.min_depth`` and suggested ``.depth``."""
    return get_standard(scale)


def with_standard_flangeway(spec, scale: str | None = None) -> FrogSpec:
    """Copy of ``spec`` with the flangeway width and depth suggested for ``scale`` (default: its own)."""
    spec = resolve_spec(spec)
    std = get_standard(scale or spec.scale)
    return spec.copy(scale=std.key, flangeway_width=std.width, flangeway_depth=std.depth)


# ================================================================ presets
_library: PresetLibrary | None = None
_preset_file_override: str | None = None


def _default_preset_file() -> str:
    """Path of the user preset file: $SWITCH_FROG_PRESETS, Blender's config folder, or ~/.switch_frog."""
    env = os.environ.get("SWITCH_FROG_PRESETS")
    if env:
        return env
    try:
        import bpy
        d = bpy.utils.user_resource('CONFIG', path="switch_frog", create=True)
    except Exception:
        d = os.path.join(os.path.expanduser("~"), ".switch_frog")
    return os.path.join(d, "frog_presets.json")


def _lib() -> PresetLibrary:
    """The shared PresetLibrary, created on first use."""
    global _library
    if _library is None:
        _library = PresetLibrary(_preset_file_override or _default_preset_file())
    return _library


def get_preset_file() -> str:
    """Path of the JSON file that stores user frog presets."""
    return _lib().user_file


def set_preset_file(path: str | None) -> None:
    """Use a different user preset file (``None`` restores the default)."""
    global _library, _preset_file_override
    _preset_file_override = path
    _library = None


def list_presets() -> list[str]:
    """All frog preset names: built-ins (smallest scale first) then user presets."""
    return _lib().names()


def list_builtin_presets() -> list[str]:
    """Names of the built-in frog presets."""
    return _lib().builtin_names()


def list_user_presets() -> list[str]:
    """Names of the user's saved frog presets, sorted alphabetically."""
    return _lib().user_names()


def is_builtin_preset(name: str) -> bool:
    """True if ``name`` is a built-in (read-only) frog preset."""
    return name in BUILTIN_PRESETS


def default_preset_name() -> str:
    """Name of the preset the panel starts with (HO #6 Code 83)."""
    return DEFAULT_PRESET


def get_preset(name: str) -> FrogSpec:
    """Return a copy of the named frog preset. Raises ``KeyError`` if missing."""
    return _lib().get(name)


def save_preset(spec: FrogSpec, overwrite: bool = True) -> None:
    """Save a user preset under ``spec.name``. Raises ``PresetError``."""
    _lib().save(spec, overwrite)


def delete_preset(name: str) -> None:
    """Delete a user preset. Built-ins cannot be deleted (``PresetError``)."""
    _lib().delete(name)


def import_presets(path: str, overwrite: bool = True) -> list[str]:
    """Merge presets from a JSON file into the user presets; returns the names imported."""
    return _lib().import_json(path, overwrite)


def export_presets(path: str, names: list[str] | None = None) -> None:
    """Write user presets (or just ``names``) to a JSON file for sharing."""
    _lib().export_json(path, names)


def resolve_spec(spec) -> FrogSpec:
    """Accept a ``FrogSpec``, a preset name, a dict, or a frog number (default preset, that number)."""
    if isinstance(spec, FrogSpec):
        return spec
    if isinstance(spec, str):
        return get_preset(spec)
    if isinstance(spec, dict):
        return FrogSpec.from_dict(spec)
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return get_preset(DEFAULT_PRESET).copy(frog_number=float(spec),
                                               name=f"#{spec:g} frog")
    raise TypeError(f"Cannot interpret {spec!r} as a frog spec")


# ============================================================ rail bridge
def get_rail_api():
    """The Model Rail Generator's API module. Raises ``FrogError`` if it isn't enabled or is too old."""
    api = sys.modules.get(RAIL_API_ALIAS)
    if api is None:
        raise FrogError("Enable the Model Rail Generator add-on (1.0 or later); "
                        "it supplies the rail profiles")
    version = tuple(getattr(api, "API_VERSION", (0, 0, 0)))
    if version[0] != RAIL_API_MIN[0] or version < RAIL_API_MIN:
        raise FrogError(f"Model Rail Generator API {version} isn't supported; "
                        f"need {RAIL_API_MIN[0]}.x, {RAIL_API_MIN} or later")
    return api


def rail_api_status() -> str:
    """An empty string if rail profiles are available, otherwise the reason they aren't."""
    try:
        get_rail_api()
    except FrogError as ex:
        return str(ex)
    return ""


def list_rail_presets() -> list[str]:
    """Rail preset names from the Model Rail Generator, or [] if it isn't enabled."""
    try:
        return list(get_rail_api().list_presets())
    except FrogError:
        return []


def resolve_rail_profile(rail=None, spec: FrogSpec | None = None):
    """The rail profile to build with, as the Rail API's ``RailProfile``.

    ``rail`` may be a RailProfile, a rail preset name, a rail code number or
    a dict; when it is None the spec's ``rail_preset`` is used.
    """
    api = get_rail_api()
    if rail is None or rail == "":
        rail = spec.rail_preset if spec is not None else ""
        if not rail:
            raise FrogError("No rail profile: choose a rail preset")
    try:
        return api.resolve_profile(rail)
    except KeyError:
        raise FrogError(f"No rail preset named '{rail}' in the Model Rail Generator") from None


# =============================================================== geometry
def frog_layout(spec, rail=None) -> FrogLayout:
    """Where everything goes (toe, knuckle, point, heel, wing rails...) for a spec and rail.

    Check ``layout.errors`` before building; ``layout.summary()`` gives the
    key numbers as a dict.  Works without Blender.
    """
    spec = resolve_spec(spec)
    return compute_layout(spec, resolve_rail_profile(rail, spec))


def generate_frog_parts(spec, rail=None, alignment: str = "CENTERED") -> dict[str, MeshData]:
    """Every solid of the frog by name (V Point, Point Rail L/R, Wing Rail L/R, Fill, Base Plate).

    Each part is a closed, outward-facing mesh in mm; parts overlap where
    they join.  Raises ``FrogError`` for invalid settings.  Works without Blender.
    """
    spec = resolve_spec(spec)
    profile = resolve_rail_profile(rail, spec)
    lay = compute_layout(spec, profile)
    if lay.errors:
        raise FrogError("; ".join(lay.errors))
    rot = alignment_rotation(spec, alignment)
    return {n: md.rotated_z(rot) for n, md in build_parts(spec, profile, get_rail_api(), lay).items()}


def generate_frog_mesh(spec, rail=None, alignment: str = "CENTERED") -> MeshData:
    """All parts in one MeshData (mm). The shells overlap; slicers merge them when printing.

    For a single merged, manifold solid use ``create_frog_object`` in Blender.
    """
    return merge(generate_frog_parts(spec, rail, alignment).values())


# ========================================================= blender helpers
def mm_to_blender_units(scene=None) -> float:
    """Factor that converts millimetres to Blender units for ``scene`` (0.001 at Unit Scale 1.0)."""
    import bpy
    scene = scene or bpy.context.scene
    scale = scene.unit_settings.scale_length if scene else 1.0
    return 0.001 / (scale or 1.0)


def _mesh_from_data(name: str, md: MeshData, factor: float):
    """Create a Blender mesh named ``name`` from mm MeshData, scaled by ``factor``."""
    import bpy
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x * factor, y * factor, z * factor) for x, y, z in md.vertices],
                   [], md.faces)
    me.validate(clean_customdata=False)
    me.update()
    return me


def _boolean_solver() -> str:
    """Best boolean solver this Blender has: Manifold (4.5+) or Exact."""
    import bpy
    items = bpy.types.BooleanModifier.bl_rna.properties["solver"].enum_items.keys()
    return "MANIFOLD" if "MANIFOLD" in items else "EXACT"


def _union_mesh(name: str, parts: dict[str, MeshData], factor: float, scene):
    """One Blender mesh that is the boolean union of ``parts``.

    Builds temporary objects, unions them with a Boolean modifier and keeps
    the evaluated result.  Falls back to the plain joined shells if the
    boolean produces nothing.
    """
    import bpy
    items = list(parts.values())
    if len(items) == 1:
        return _mesh_from_data(name, items[0], factor)
    tmp = bpy.data.collections.new("_switch_frog_tmp")
    ops = bpy.data.collections.new("_switch_frog_ops")
    scene.collection.children.link(tmp)
    tmp.children.link(ops)
    made = []
    try:
        for i, md in enumerate(items):
            me = _mesh_from_data(f"_frog_part_{i}", md, factor)
            ob = bpy.data.objects.new(me.name, me)
            (tmp if i == 0 else ops).objects.link(ob)
            made.append((ob, me))
        base = made[0][0]
        mod = base.modifiers.new("Union", "BOOLEAN")
        mod.operation = "UNION"
        mod.operand_type = "COLLECTION"
        mod.collection = ops
        mod.solver = _boolean_solver()
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        result = bpy.data.meshes.new_from_object(base.evaluated_get(dg))
    finally:
        for ob, me in made:
            bpy.data.objects.remove(ob)
            bpy.data.meshes.remove(me)
        bpy.data.collections.remove(ops)
        bpy.data.collections.remove(tmp)
    if not result.polygons:
        bpy.data.meshes.remove(result)
        print("[Switch Frog] Boolean union failed; using overlapping parts")
        return _mesh_from_data(name, merge(items), factor)
    result.name = name
    return result


def _build_mesh(spec: FrogSpec, profile, alignment: str, merged: bool, name: str, scene):
    """Blender mesh for a frog: one merged solid, or the parts as overlapping shells."""
    parts = generate_frog_parts(spec, profile, alignment)
    f = mm_to_blender_units(scene)
    if merged:
        return _union_mesh(name, parts, f, scene)
    return _mesh_from_data(name, merge(parts.values()), f)


def _store_params(obj, spec: FrogSpec, profile, alignment: str, merged: bool):
    """Save the generation parameters on ``obj`` so it can be rebuilt or inspected later."""
    lay = compute_layout(spec, profile)
    obj[FROG_PROP_KEY] = json.dumps({
        "api_version": list(API_VERSION),
        "spec": spec.to_dict(),
        "profile": profile.to_dict(),
        "alignment": alignment,
        "merged": merged,
        "layout": lay.summary(),
    })
    obj["frog_number"] = spec.frog_number
    obj["rail_code"] = getattr(profile, "code", 0.0)


def create_frog_object(spec, rail=None, name: str | None = None, collection=None,
                       location=(0.0, 0.0, 0.0), rotation_z_deg: float = 0.0,
                       alignment: str = "CENTERED", merged: bool = True, scene=None):
    """Create a frog mesh object and return it.

    ``spec``: FrogSpec | frog preset name | dict | frog number.
    ``rail``: RailProfile | rail preset name | code | dict; default is the
    spec's ``rail_preset``.  ``alignment``: CENTERED, LEFT_HAND or
    RIGHT_HAND (see ``frog.alignment_rotation``).  ``merged`` unions the
    parts into one manifold solid (slower); False keeps overlapping shells.
    The object goes in ``collection`` (default: the active collection);
    ``location`` is in Blender units.  Parameters are stored on the object.
    """
    import bpy
    spec = resolve_spec(spec)
    profile = resolve_rail_profile(rail, spec)
    scene = scene or bpy.context.scene
    name = name or f"Frog #{spec.frog_number:g} {profile.name}"
    me = _build_mesh(spec, profile, alignment, merged, name, scene)
    obj = bpy.data.objects.new(name, me)
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, math.radians(rotation_z_deg))
    (collection or bpy.context.collection).objects.link(obj)
    _store_params(obj, spec, profile, alignment, merged)
    return obj


def is_frog_object(obj) -> bool:
    """True if ``obj`` was made by this add-on (it carries frog parameters)."""
    return obj is not None and FROG_PROP_KEY in obj.keys()


def get_frog_params(obj) -> dict:
    """Parameters the frog was generated with (``spec`` and ``profile`` are dicts)."""
    if not is_frog_object(obj):
        raise ValueError(f"'{getattr(obj, 'name', obj)}' is not a frog object")
    return json.loads(obj[FROG_PROP_KEY])


def rebuild_frog_object(obj, spec=None, rail=None, alignment: str | None = None,
                        merged: bool | None = None, scene=None):
    """Regenerate a frog object's mesh, changing only the parameters given.

    Keeps the object, its transform, modifiers and materials.  With no
    ``rail`` the profile stored on the object is reused, so a frog still
    rebuilds after its rail preset is deleted.
    """
    import bpy
    p = get_frog_params(obj)
    spec = resolve_spec(spec if spec is not None else p["spec"])
    profile = resolve_rail_profile(rail if rail is not None else p["profile"], spec)
    alignment = alignment or p.get("alignment", "CENTERED")
    merged = p.get("merged", True) if merged is None else merged
    old = obj.data
    new = _build_mesh(spec, profile, alignment, merged, old.name, scene or bpy.context.scene)
    for mat in old.materials:
        new.materials.append(mat)
    obj.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    _store_params(obj, spec, profile, alignment, merged)
    return obj


def object_to_mesh_data(obj, apply_transform: bool = True, scene=None) -> MeshData:
    """Evaluated (modifiers applied) mesh of ``obj`` as triangles in mm."""
    import bpy
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        f = 1.0 / mm_to_blender_units(scene)
        mw = obj.matrix_world if apply_transform else None
        verts = []
        for v in me.vertices:
            co = mw @ v.co if mw is not None else v.co
            verts.append((co.x * f, co.y * f, co.z * f))
        faces = [tuple(t.vertices) for t in me.loop_triangles]
        if mw is not None and mw.determinant() < 0:
            faces = [tuple(reversed(t)) for t in faces]
        return MeshData(verts, faces)
    finally:
        ev.to_mesh_clear()


def export_frog(target, filepath: str, fmt: str | None = None, name: str | None = None) -> str:
    """Export to STL/OBJ in millimetres and return the path written.

    ``target``: MeshData, a Blender object, or a list of objects (merged into
    one file, world transforms applied). ``fmt``: "STL" (binary),
    "STL_ASCII" or "OBJ"; inferred from the extension when omitted.
    """
    if isinstance(target, MeshData) or (hasattr(target, "vertices") and hasattr(target, "faces")
                                        and not hasattr(target, "data")):
        md, label = target, name or "frog"
    else:
        objs = list(target) if isinstance(target, (list, tuple)) else [target]
        if not objs:
            raise ValueError("Nothing to export")
        md = merge(object_to_mesh_data(o) for o in objs)
        label = name or objs[0].name
    if filepath.startswith("//"):
        import bpy
        filepath = bpy.path.abspath(filepath)
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    return export_mesh(filepath, md, fmt, label)
