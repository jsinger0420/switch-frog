"""Blender UI: scene properties, operators and the sidebar panel (Frog tab).

Everything here goes through ``api`` so the UI and other add-ons always
behave identically.
"""

from __future__ import annotations

import os

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, PointerProperty,
                       StringProperty)
from bpy.types import Operator, Panel, PropertyGroup

from . import api
from .frog import FrogSpec, compute_layout
from .standards import SCALES

#: FrogSpec fields that map one-to-one onto panel properties.
SPEC_FIELDS = ("frog_number", "flangeway_width", "flangeway_depth", "point_width",
               "point_drop", "point_ramp", "length_mode", "toe_length", "heel_length",
               "joint_gap", "flare_length", "flare_angle", "fill", "base_plate",
               "plate_thickness", "plate_margin")

_DEF = api.get_preset(api.default_preset_name())

# Blender requires dynamic enum items to stay referenced.
_preset_items_cache: list = []
_rail_items_cache: list = []


# ============================================================ preset menus
def _preset_items(self, context):
    """Items for the frog Preset menu: built-ins, then user presets marked (user)."""
    global _preset_items_cache
    items = []
    for i, n in enumerate(api.list_presets()):
        s = api.get_preset(n)
        tag = "" if api.is_builtin_preset(n) else " (user)"
        items.append((n, n + tag, f"{s.description}  [#{s.frog_number:g}, {s.rail_preset or 'no rail'}]", i))
    _preset_items_cache = items or [("NONE", "No presets", "", 0)]
    return _preset_items_cache


def _get_preset(self):
    """Index of the current frog preset in the menu (0 if it no longer exists)."""
    names = api.list_presets()
    return names.index(self.preset_current) if self.preset_current in names else 0


def _set_preset(self, value):
    """Choose a frog preset from the menu and load its settings into the panel."""
    names = api.list_presets()
    if 0 <= value < len(names):
        self.load_spec(api.get_preset(names[value]))


def _rail_names(self) -> list[str]:
    """Rail preset names for the menu, plus the current one if it has gone missing."""
    names = api.list_rail_presets()
    if self.rail_preset and self.rail_preset not in names:
        names.append(self.rail_preset)
    return names


def _rail_items(self, context):
    """Items for the Rail menu: the Model Rail Generator's presets."""
    global _rail_items_cache
    known = set(api.list_rail_presets())
    items = []
    for i, n in enumerate(_rail_names(self)):
        label = n if n in known else f"{n} (missing)"
        items.append((n, label, "Rail preset from the Model Rail Generator", i))
    _rail_items_cache = items or [("NONE", "Rail add-on not enabled", "", 0)]
    return _rail_items_cache


def _get_rail(self):
    """Index of the chosen rail preset in the Rail menu."""
    names = _rail_names(self)
    return names.index(self.rail_preset) if self.rail_preset in names else 0


def _set_rail(self, value):
    """Store the rail preset picked in the Rail menu."""
    names = _rail_names(self)
    if 0 <= value < len(names):
        self.rail_preset = names[value]


_SCALE_ITEMS = [("CUSTOM", "Custom", "No scale: the flangeway is only checked against the rail")] + [
    (k, v.label, f"NMRA flangeway: width up to {v.max_width:.2f} mm, depth at least "
                 f"{v.min_depth:.2f} mm") for k, v in SCALES.items()]


def _mm(name, desc, default, soft_max=20.0):
    """A millimetre dimension property with a consistent tooltip."""
    return FloatProperty(name=name, description=desc + " (mm, actual model size)",
                         default=default, min=0.0, soft_max=soft_max, precision=3, step=1)


class SWITCHFROG_PG_settings(PropertyGroup):
    """Everything in the Frog panel, stored on the scene as ``scene.switch_frog``."""

    # ------------------------------------------------------------ presets
    preset: EnumProperty(name="Preset", items=_preset_items, get=_get_preset, set=_set_preset,
                         description="Frog preset; choosing one loads all its settings")
    preset_current: StringProperty(default=_DEF.name, options={'HIDDEN'})
    preset_name: StringProperty(name="Name", default=_DEF.name,
                                description="Name used when saving a preset")
    description: StringProperty(name="Notes", default=_DEF.description)

    # --------------------------------------------------------------- frog
    rail_menu: EnumProperty(name="Rail", items=_rail_items, get=_get_rail, set=_set_rail,
                            description="Rail profile, from the Model Rail Generator's presets")
    rail_preset: StringProperty(name="Rail Preset", default=_DEF.rail_preset)
    frog_number: FloatProperty(name="Frog Number", default=_DEF.frog_number, min=1.0, max=40.0,
                               precision=2, step=50,
                               description="Frog number N: the routes spread 1 unit every N units "
                                           "(angle = 2 atan(1/2N))")
    scale: EnumProperty(name="Scale", items=_SCALE_ITEMS, default=_DEF.scale or "CUSTOM",
                        description="Model scale; sets the NMRA flangeway limits the frog is "
                                    "checked against (Set Flangeway fills them in)")
    flangeway_width: _mm("Flangeway Width", "Gap between the wing rails and the point",
                         _DEF.flangeway_width, 6.0)
    flangeway_depth: _mm("Flangeway Depth", "Depth of the flangeway floor below the railhead "
                         "(used by Fill: Flangeway Floor)", _DEF.flangeway_depth, 6.0)
    point_width: _mm("Point Width", "Width of the blunt end of the V point", _DEF.point_width, 3.0)
    point_drop: _mm("Point Drop", "Lower the top of the point at its tip by this much "
                    "(0 = level)", _DEF.point_drop, 1.0)
    point_ramp: _mm("Drop Length", "Distance over which the point rises back to full height",
                    _DEF.point_ramp, 20.0)

    # ------------------------------------------------------------ lengths
    length_mode: EnumProperty(name="Lengths", default=_DEF.length_mode, items=[
        ("AUTO", "Auto", "Make the frog just long enough for rail joiners at both ends"),
        ("MANUAL", "Manual", "Enter the toe and heel lengths"),
    ])
    toe_length: _mm("Toe Length", "From the theoretical point back to the toe", _DEF.toe_length, 200.0)
    heel_length: _mm("Heel Length", "From the theoretical point forward to the heel",
                     _DEF.heel_length, 300.0)
    joint_gap: _mm("Joint Gap", "Auto lengths: clear space between rail bases at the toe "
                   "and heel, for rail joiners", _DEF.joint_gap, 10.0)
    flare_length: _mm("Flare Length", "Length of the outward bend at the heel end of each "
                      "wing rail (0 = none)", _DEF.flare_length, 30.0)
    flare_angle: FloatProperty(name="Flare Angle", default=_DEF.flare_angle, min=0.0, max=45.0,
                               precision=1, description="Angle of the wing rail flares in degrees")

    # ----------------------------------------------------------- printing
    fill: EnumProperty(name="Fill", default=_DEF.fill, items=[
        ("NONE", "None", "Rails only: the point and wing rails are separate pieces"),
        ("BASE", "Base", "Join the rails at the top of the rail base"),
        ("FLOOR", "Flangeway Floor", "Solid between the wing rails up to the flangeway floor "
                                     "(a cast frog)"),
    ])
    base_plate: BoolProperty(name="Base Plate", default=_DEF.base_plate,
                             description="Add a plate under the whole frog (raises the rail "
                                         "top by its thickness)")
    plate_thickness: _mm("Thickness", "Base plate thickness", _DEF.plate_thickness, 5.0)
    plate_margin: _mm("Margin", "How far the base plate reaches past the outer rail bases",
                      _DEF.plate_margin, 10.0)
    alignment: EnumProperty(name="Alignment", default="CENTERED", items=[
        ("CENTERED", "Centred", "Frog centreline along Y"),
        ("LEFT_HAND", "Left Hand", "Straight route along Y, other route diverging left"),
        ("RIGHT_HAND", "Right Hand", "Straight route along Y, other route diverging right"),
    ])
    merged: BoolProperty(name="Merge Into One Solid", default=True,
                         description="Union all parts into one clean solid (best for printing); "
                                     "off is faster but leaves overlapping parts")

    # ----------------------------------------------------- status, export
    last_report: StringProperty(name="Last Result", default="",
                                description="Result of the last Generate / Update / Export")
    export_format: EnumProperty(name="Format", items=[
        ("STL", "STL (binary)", "Best for 3D printing"),
        ("STL_ASCII", "STL (ASCII)", "Text STL"),
        ("OBJ", "OBJ", "Wavefront OBJ"),
    ])

    # ------------------------------------------------------------ helpers
    def load_spec(self, spec: FrogSpec):
        """Fill the panel from ``spec``; its rail preset is used only if it names one."""
        for f in SPEC_FIELDS:
            setattr(self, f, getattr(spec, f))
        if spec.rail_preset:
            self.rail_preset = spec.rail_preset
        self.scale = spec.scale or "CUSTOM"
        self.description = spec.description
        self.preset_name = spec.name
        self.preset_current = spec.name

    def to_spec(self) -> FrogSpec:
        """The panel's current settings as a FrogSpec (including the chosen rail preset)."""
        kw = {f: getattr(self, f) for f in SPEC_FIELDS}
        return FrogSpec(name=self.preset_name.strip() or "Custom frog",
                        rail_preset=self.rail_preset, description=self.description,
                        scale="" if self.scale == "CUSTOM" else self.scale, **kw)

    def check(self):
        """(layout, rail profile, error text) for the current settings; error is "" when OK."""
        try:
            spec = self.to_spec()
            profile = api.resolve_rail_profile(None, spec)
            lay = compute_layout(spec, profile)
        except (api.FrogError, ValueError, TypeError) as ex:
            return None, None, str(ex)
        return lay, profile, "; ".join(lay.errors)


def _settings(context) -> SWITCHFROG_PG_settings:
    """The scene's Frog panel settings."""
    return context.scene.switch_frog


def _first_error(op, s):
    """Report and return the first problem with the settings, or "" when they are fine."""
    lay, profile, err = s.check()
    if err:
        op.report({'ERROR'}, err)
        s.last_report = err.split(";")[0]
    return err


# ================================================================ operators
_busy = False


def is_busy() -> bool:
    """True while a frog is being generated (the panel shows a wait message)."""
    return _busy


def _redraw(context):
    """Ask every area of the screen to redraw so the wait message shows."""
    screen = context.screen
    if screen:
        for area in screen.areas:
            area.tag_redraw()


class SWITCHFROG_OT_generate(Operator):
    """Create a frog at the 3D cursor from the current settings"""

    bl_idname = "switch_frog.generate"
    bl_label = "Generate Frog"
    bl_options = {'REGISTER', 'UNDO'}

    _timer = None

    def _run(self, context):
        """Build the frog and select it; reports and records the result or error."""
        s = _settings(context)
        if _first_error(self, s):
            return {'CANCELLED'}
        try:
            obj = api.create_frog_object(s.to_spec(), s.rail_preset,
                                         location=context.scene.cursor.location.copy(),
                                         alignment=s.alignment, merged=s.merged)
        except (api.FrogError, ValueError, TypeError) as ex:
            self.report({'ERROR'}, str(ex))
            s.last_report = str(ex).splitlines()[0]
            return {'CANCELLED'}
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        s.last_report = f"Created '{obj.name}' ({len(obj.data.polygons)} faces)"
        self.report({'INFO'}, s.last_report)
        return {'FINISHED'}

    def execute(self, context):
        """Build straight away (used by scripts and the redo panel)."""
        return self._run(context)

    def invoke(self, context, event):
        """Show the wait message and busy cursor first, then build on the next timer tick.

        Blender doesn't redraw while an operator runs, so the build waits one
        tick to let the panel show "please wait".
        """
        global _busy
        if _busy:
            return {'CANCELLED'}
        _busy = True
        wm = context.window_manager
        context.window.cursor_modal_set('WAIT')
        if context.workspace:
            context.workspace.status_text_set("Generating frog, please wait...")
        _redraw(context)
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        """Ignore input until the timer fires, then build and restore the cursor."""
        global _busy
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}  # ignore clicks and keys until the build is done
        context.window_manager.event_timer_remove(self._timer)
        try:
            return self._run(context)
        finally:
            context.window.cursor_modal_restore()
            if context.workspace:
                context.workspace.status_text_set(None)
            _busy = False
            _redraw(context)


class SWITCHFROG_OT_rebuild(Operator):
    """Regenerate the selected frogs with the current settings"""

    bl_idname = "switch_frog.rebuild"
    bl_label = "Update Selected Frogs"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """Available only when at least one selected object is a frog."""
        return any(api.is_frog_object(o) for o in context.selected_objects)

    def execute(self, context):
        """Rebuild each selected frog in place (transform and materials are kept)."""
        s = _settings(context)
        if _first_error(self, s):
            return {'CANCELLED'}
        n = 0
        try:
            for o in context.selected_objects:
                if api.is_frog_object(o):
                    api.rebuild_frog_object(o, s.to_spec(), s.rail_preset,
                                            alignment=s.alignment, merged=s.merged)
                    n += 1
        except (api.FrogError, ValueError) as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        s.last_report = f"Updated {n} frog(s)"
        self.report({'INFO'}, s.last_report)
        return {'FINISHED'}


class SWITCHFROG_OT_set_flangeway(Operator):
    """Set the flangeway width and depth to the NMRA values for the chosen scale"""

    bl_idname = "switch_frog.set_flangeway"
    bl_label = "Set Flangeway"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """Available once a scale is chosen."""
        return _settings(context).scale in SCALES

    def execute(self, context):
        """Fill in the NMRA maximum width and the suggested depth."""
        s = _settings(context)
        std = SCALES[s.scale]
        s.flangeway_width = std.width
        s.flangeway_depth = std.depth
        self.report({'INFO'}, f"{std.key} flangeway: {std.width:.2f} mm wide, "
                              f"{std.depth:.2f} mm deep")
        return {'FINISHED'}


class SWITCHFROG_OT_save_preset(Operator):
    """Save the current settings as a frog preset of your own, under the name above"""

    bl_idname = "switch_frog.save_preset"
    bl_label = "Save Preset"

    def invoke(self, context, event):
        """Ask before overwriting an existing user preset of the same name."""
        name = _settings(context).preset_name.strip()
        if name in api.list_user_presets():
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        """Save the preset and select it in the Preset menu."""
        s = _settings(context)
        spec = s.to_spec()
        if api.is_builtin_preset(spec.name):
            self.report({'ERROR'}, f"'{spec.name}' is built in; enter a new name to save")
            return {'CANCELLED'}
        try:
            api.save_preset(spec, overwrite=True)
        except api.PresetError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        s.preset_current = spec.name
        self.report({'INFO'}, f"Saved preset '{spec.name}'")
        return {'FINISHED'}


class SWITCHFROG_OT_delete_preset(Operator):
    """Delete the selected frog preset (only your own presets can be deleted)"""

    bl_idname = "switch_frog.delete_preset"
    bl_label = "Delete Preset"

    @classmethod
    def poll(cls, context):
        """Available only for user presets."""
        return _settings(context).preset_current in api.list_user_presets()

    def invoke(self, context, event):
        """Ask for confirmation before deleting."""
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        """Delete the preset and switch to the default built-in."""
        s = _settings(context)
        name = s.preset_current
        try:
            api.delete_preset(name)
        except (api.PresetError, KeyError) as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        s.load_spec(api.get_preset(api.default_preset_name()))
        self.report({'INFO'}, f"Deleted preset '{name}'")
        return {'FINISHED'}


class SWITCHFROG_OT_export(Operator):
    """Export the selected objects (or, with none selected, a frog from these settings) as STL/OBJ in mm"""

    bl_idname = "switch_frog.export"
    bl_label = "Export Frog"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.stl;*.obj", options={'HIDDEN'})
    format: EnumProperty(name="Format", items=[
        ("STL", "STL (binary)", ""), ("STL_ASCII", "STL (ASCII)", ""), ("OBJ", "OBJ", "")])
    selected_only: BoolProperty(name="Selected Objects", default=True,
                                description="Export selected meshes; otherwise build from settings")

    def invoke(self, context, event):
        """Open the file browser with a file name based on the frog."""
        s = _settings(context)
        self.format = s.export_format
        base = bpy.path.clean_name(f"frog_{s.frog_number:g}_{s.rail_preset or 'rail'}")
        self.filepath = bpy.path.ensure_ext(base, ".obj" if self.format == "OBJ" else ".stl")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        """Write the file and show where it went."""
        s = _settings(context)
        ext = ".obj" if self.format == "OBJ" else ".stl"
        path = bpy.path.ensure_ext(bpy.path.abspath(self.filepath), ext)
        objs = [o for o in context.selected_objects if o.type == 'MESH'] if self.selected_only else []
        try:
            if objs:
                api.export_frog(objs, path, self.format)
                what = f"{len(objs)} object(s)"
            else:
                if _first_error(self, s):
                    return {'CANCELLED'}
                obj = api.create_frog_object(s.to_spec(), s.rail_preset,
                                             alignment=s.alignment, merged=s.merged)
                try:
                    api.export_frog(obj, path, self.format)
                finally:
                    me = obj.data
                    bpy.data.objects.remove(obj)
                    bpy.data.meshes.remove(me)
                what = "frog from current settings"
        except (OSError, ValueError) as ex:
            self.report({'ERROR'}, f"Export failed: {ex}")
            return {'CANCELLED'}
        s.export_format = self.format
        s.last_report = f"Exported {what} to {os.path.basename(path)}"
        self.report({'INFO'}, f"Exported {what} to {path}")
        return {'FINISHED'}


# =================================================================== panels
class _Panel:
    """Settings shared by all Frog panels: 3D Viewport sidebar, Frog tab."""

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Frog"


class SWITCHFROG_PT_main(_Panel, Panel):
    """Top of the Frog tab: Generate, Update, Export, the last result and a summary."""

    bl_label = "Switch Frog"
    bl_idname = "SWITCHFROG_PT_main"

    def draw(self, context):
        """Draw Generate (or the wait message), Update, Export, problems and a summary."""
        s = _settings(context)
        col = self.layout.column()
        lay, profile, err = s.check()

        row = col.row(align=True)
        row.scale_y = 1.4
        if is_busy():
            row.alert = True
            row.label(text="Generating frog, please wait...", icon='SORTTIME')
        else:
            row.enabled = not err
            row.operator(SWITCHFROG_OT_generate.bl_idname, icon='ADD')
        col.operator(SWITCHFROG_OT_rebuild.bl_idname, icon='FILE_REFRESH')

        row = col.row(align=True)
        row.operator(SWITCHFROG_OT_export.bl_idname, icon='EXPORT')
        row.prop(s, "export_format", text="")

        if err:
            box = col.box()
            box.alert = True
            box.label(text="Fix the settings to generate:", icon='ERROR')
            for e in err.split("; ")[:3]:
                box.label(text=e)
            return
        if s.last_report:
            col.label(text=s.last_report, icon='INFO')
        for w in lay.warnings:
            col.label(text=w, icon='ERROR')

        box = col.box()
        box.label(text=f"#{lay.number:g} frog, {lay.angle_deg:.3f}°, {profile.name}",
                  icon='MOD_SOLIDIFY')
        box.label(text=f"Length {lay.length:.1f} mm (toe {lay.toe_length:.1f}, "
                       f"heel {lay.heel_length:.1f})")
        box.label(text=f"Throat {lay.throat_width:.2f} mm, heel spread {lay.heel_spread:.2f} mm")


class SWITCHFROG_PT_preset(_Panel, Panel):
    """Sub-panel for choosing, saving and deleting frog presets."""

    bl_label = "Frog Preset"
    bl_parent_id = "SWITCHFROG_PT_main"

    def draw(self, context):
        """Draw the preset menu with delete, then the name, notes and Save Preset."""
        s = _settings(context)
        col = self.layout.column()
        row = col.row(align=True)
        row.prop(s, "preset", text="")
        row.operator(SWITCHFROG_OT_delete_preset.bl_idname, text="", icon='TRASH')
        sub = col.column(align=True)
        sub.prop(s, "preset_name")
        sub.prop(s, "description")
        sub.operator(SWITCHFROG_OT_save_preset.bl_idname, icon='FILE_TICK')


class SWITCHFROG_PT_frog(_Panel, Panel):
    """Sub-panel for the frog number, rail profile, flangeways and point."""

    bl_label = "Frog"
    bl_parent_id = "SWITCHFROG_PT_main"

    def draw(self, context):
        """Draw frog number and angle, rail preset, flangeway and point settings."""
        s = _settings(context)
        col = self.layout.column()
        row = col.row(align=True)
        row.prop(s, "frog_number", text="Frog #")
        try:
            row.label(text=f"{api.frog_angle_deg(s.frog_number):.3f}°")
        except ValueError:
            pass

        status = api.rail_api_status()
        if status:
            box = col.box()
            box.alert = True
            box.label(text="Rail profiles unavailable:", icon='ERROR')
            box.label(text="Enable Model Rail Generator 1.0+")
        else:
            col.prop(s, "rail_menu")
            try:
                p = api.resolve_rail_profile(s.rail_preset)
                col.label(text=f"Code {p.code:g}: {p.height:.3f} mm high, "
                               f"head {p.head_width:.3f} mm")
            except api.FrogError as ex:
                col.label(text=str(ex), icon='ERROR')

        row = col.row(align=True)
        row.prop(s, "scale", text="")
        row.operator(SWITCHFROG_OT_set_flangeway.bl_idname)
        sub = col.column(align=True)
        sub.prop(s, "flangeway_width")
        sub.prop(s, "flangeway_depth")
        std = SCALES.get(s.scale)
        if std is not None:
            sub.label(text=f"NMRA {std.key}: width ≤ {std.max_width:.2f}, depth ≥ "
                           f"{std.min_depth:.2f} mm")
        sub = col.column(align=True)
        sub.prop(s, "point_width")
        sub.prop(s, "point_drop")
        if s.point_drop > 0:
            sub.prop(s, "point_ramp")


class SWITCHFROG_PT_lengths(_Panel, Panel):
    """Sub-panel for the toe and heel lengths and the wing rail flares."""

    bl_label = "Lengths"
    bl_parent_id = "SWITCHFROG_PT_main"

    def draw(self, context):
        """Draw Auto/Manual lengths, the joint gap or the lengths, and the flare."""
        s = _settings(context)
        col = self.layout.column()
        col.row().prop(s, "length_mode", expand=True)
        sub = col.column(align=True)
        if s.length_mode == "AUTO":
            sub.prop(s, "joint_gap")
            lay, _p, err = s.check()
            if not err:
                sub.label(text=f"Toe {lay.toe_length:.2f} mm, heel {lay.heel_length:.2f} mm")
        else:
            sub.prop(s, "toe_length")
            sub.prop(s, "heel_length")
        sub = col.column(align=True)
        sub.prop(s, "flare_length")
        sub.prop(s, "flare_angle", text="Flare Angle (°)")


class SWITCHFROG_PT_print(_Panel, Panel):
    """Sub-panel for printing: fill, base plate, alignment and merging."""

    bl_label = "Printing"
    bl_parent_id = "SWITCHFROG_PT_main"

    def draw(self, context):
        """Draw the fill choice, base plate, alignment and the merge option."""
        s = _settings(context)
        col = self.layout.column()
        col.label(text="Fill:")
        col.row().prop(s, "fill", expand=True)
        col.prop(s, "base_plate")
        if s.base_plate:
            sub = col.column(align=True)
            sub.prop(s, "plate_thickness")
            sub.prop(s, "plate_margin")
        col.prop(s, "alignment")
        col.prop(s, "merged")


classes = (
    SWITCHFROG_PG_settings,
    SWITCHFROG_OT_generate,
    SWITCHFROG_OT_rebuild,
    SWITCHFROG_OT_set_flangeway,
    SWITCHFROG_OT_save_preset,
    SWITCHFROG_OT_delete_preset,
    SWITCHFROG_OT_export,
    SWITCHFROG_PT_main,
    SWITCHFROG_PT_preset,
    SWITCHFROG_PT_frog,
    SWITCHFROG_PT_lengths,
    SWITCHFROG_PT_print,
)


def register():
    """Register the panel classes and add ``scene.switch_frog``."""
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.switch_frog = PointerProperty(type=SWITCHFROG_PG_settings)


def unregister():
    """Remove ``scene.switch_frog`` and unregister the panel classes."""
    del bpy.types.Scene.switch_frog
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
