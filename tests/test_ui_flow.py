"""Simulate clicking Generate and drawing the panels, without a Blender window.

Checks the wait cursor, status message, ignored input, button order, the
error box and the missing-rail-add-on message using stand-ins for the
window, workspace and layout.
Run: python tests/test_ui_flow.py  (needs pip install bpy).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402,F401

import bpy  # noqa: E402
import model_rail_generator as rail_addon  # noqa: E402
import switch_frog as addon  # noqa: E402

rail_addon.register()
addon.register()
from switch_frog import ui  # noqa: E402

log = []  # every recorded call, in order


class Rec:
    """Stand-in for a Blender UI layout that records every call made on it."""

    def __init__(self, name="layout"):
        """Name the recorder after the call that created it."""
        self.__dict__["_n"] = name

    def __getattr__(self, a):
        """Return a function that logs the call and returns a child recorder."""
        def f(*args, **kw):
            """Log one layout call (row, label, operator, prop...)."""
            log.append((a, args, kw))
            return Rec(a)
        return f

    def __setattr__(self, a, v):
        """Log attribute settings such as ``row.enabled = False``."""
        log.append(("set", a, v))


class Win:
    """Stand-in for the window, recording cursor changes."""

    def cursor_modal_set(self, c):
        """Record the cursor being set (e.g. WAIT)."""
        log.append(("cursor", c))

    def cursor_modal_restore(self):
        """Record the cursor being restored."""
        log.append(("cursor", "restore"))


class WS:
    """Stand-in for the workspace, recording status-bar text."""

    def status_text_set(self, t):
        """Record the status-bar message (None clears it)."""
        log.append(("status", t))


class WM:
    """Stand-in for the window manager, recording timers and modal handlers."""

    def event_timer_add(self, t, window=None):
        """Record a timer being added and return a dummy handle."""
        log.append(("timer_add",))
        return "T"

    def event_timer_remove(self, t):
        """Record the timer being removed."""
        log.append(("timer_remove",))

    def modal_handler_add(self, op):
        """Record the operator becoming modal."""
        log.append(("modal_add",))


class Ctx:
    """Context with fake window parts; everything else comes from bpy.context."""

    window, workspace, window_manager, screen = Win(), WS(), WM(), None

    def __getattr__(self, a):
        """Fall back to the real context for scene, objects, view layer, etc."""
        return getattr(bpy.context, a)


class Ev:
    """Minimal event with just a type, e.g. TIMER or LEFTMOUSE."""

    def __init__(self, t):
        """Store the event type."""
        self.type = t


class FakeOp:
    """Stand-in for the Generate operator instance, borrowing its real _run."""

    _timer = None
    _run = ui.SWITCHFROG_OT_generate._run

    def report(self, lvl, msg):
        """Record messages the operator would show in Blender's info bar."""
        log.append(("report", msg))


def draw(panel):
    """Draw ``panel`` into a recorder and return its operator, label and prop calls."""
    log.clear()
    obj = type("P", (), {"layout": Rec()})()
    panel.draw(obj, bpy.context)
    return [(a, args, kw) for a, args, kw in log if a in ("operator", "label", "prop")]


ctx, op = Ctx(), FakeOp()
n_before = len(bpy.data.objects)

# click Generate
log.clear()
assert ui.SWITCHFROG_OT_generate.invoke(op, ctx, None) == {'RUNNING_MODAL'}
assert ("cursor", "WAIT") in log and ("status", "Generating frog, please wait...") in log
assert ui.is_busy()
assert ui.SWITCHFROG_OT_generate.invoke(op, ctx, None) == {'CANCELLED'}   # second click refused
calls = draw(ui.SWITCHFROG_PT_main)
first = calls[0]
assert first[0] == "label" and "please wait" in first[2]["text"], first
assert not any(a == "operator" and args[0] == "switch_frog.generate" for a, args, kw in calls)
for t in ("LEFTMOUSE", "A", "MOUSEMOVE"):                                  # input swallowed
    assert ui.SWITCHFROG_OT_generate.modal(op, ctx, Ev(t)) == {'RUNNING_MODAL'}
assert len(bpy.data.objects) == n_before
log.clear()
assert ui.SWITCHFROG_OT_generate.modal(op, ctx, Ev("TIMER")) == {'FINISHED'}
assert ("cursor", "restore") in log and ("status", None) in log and not ui.is_busy()
assert len(bpy.data.objects) == n_before + 1
print("modal flow ok:", bpy.context.scene.switch_frog.last_report)

# idle panel: Generate, Update, Export, then the summary
calls = draw(ui.SWITCHFROG_PT_main)
ops = [args[0] for a, args, kw in calls if a == "operator"]
assert ops[:3] == ["switch_frog.generate", "switch_frog.rebuild", "switch_frog.export"], ops
labels = [kw.get("text") for a, args, kw in calls if a == "label"]
assert any(t and t.startswith("#6 frog") for t in labels), labels
print("main panel:", ops, "|", labels)
for p in (ui.SWITCHFROG_PT_preset, ui.SWITCHFROG_PT_frog, ui.SWITCHFROG_PT_lengths,
          ui.SWITCHFROG_PT_print):
    draw(p)

# invalid settings: Generate disabled and the problem shown
s = bpy.context.scene.switch_frog
s.point_width = 5.0
calls = draw(ui.SWITCHFROG_PT_main)
assert any(a == "label" and "Fix the settings" in kw.get("text", "") for a, args, kw in calls)
assert ("set", "enabled", False) in log
s.point_width = 0.3

# rail add-on disabled: the Frog panel says so
rail_addon.unregister()
calls = draw(ui.SWITCHFROG_PT_frog)
assert any(a == "label" and "Model Rail Generator" in kw.get("text", "") for a, args, kw in calls)
calls = draw(ui.SWITCHFROG_PT_main)
assert ("set", "enabled", False) in log
rail_addon.register()

addon.unregister()
rail_addon.unregister()
print("ALL UI FLOW TESTS PASSED")
