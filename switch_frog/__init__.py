"""Switch Frog Generator — Blender add-on.

Generates 3D-printable model railroad turnout frogs from a frog number and
a rail profile chosen from the Model Rail Generator's presets, with
built-in and user frog presets, and exports them to STL/OBJ in millimetres.

Other add-ons: use the public API in ``api`` (also importable as
``switch_frog_api`` while this add-on is enabled).  See README.md in the repository.
"""

bl_info = {
    "name": "Switch Frog Generator",
    "author": "John (singerlinks.com)",
    "version": (1, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Frog",
    "description": "Generate and export 3D-printable model railroad turnout frogs",
    "category": "Add Mesh",
}

import sys

if "bpy" in locals():                      # support "Reload Scripts"
    import importlib
    from . import standards, geometry, frog, presets, exporters, api, ui
    for _m in (standards, geometry, frog, presets, exporters, api, ui):
        importlib.reload(_m)
else:
    from . import geometry, frog, presets, exporters, api   # noqa: F401
    try:
        import bpy                          # noqa: F401
        from . import ui
    except ImportError:                     # imported outside Blender (tests / tools)
        ui = None

API_ALIAS = "switch_frog_api"


def register():
    """Register the panel, operators and settings, and publish the API as ``switch_frog_api``."""
    ui.register()
    sys.modules[API_ALIAS] = api


def unregister():
    """Remove the ``switch_frog_api`` alias and unregister everything ``register`` added."""
    if sys.modules.get(API_ALIAS) is api:
        del sys.modules[API_ALIAS]
    ui.unregister()
