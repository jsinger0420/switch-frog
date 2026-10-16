"""Built-in frog presets and the user preset library.  Pure Python (no bpy).

Flangeway widths are the NMRA S-3.2 maximums for each scale; depths are a
little deeper than the NMRA minimum flangeway depth (see ``standards``).  Each built-in names
a built-in Rail Generator preset.  Save your own presets for other rail,
scales or measured values.
"""

from __future__ import annotations

import json
import os
import tempfile

from .frog import FrogSpec
from .standards import SCALES

PRESET_FILE_VERSION = 1

#: Per-scale defaults besides the flangeway (which comes from ``standards.SCALES``):
#: point width, joint gap, flare length, base plate thickness and margin (model mm).
SCALE_DEFAULTS = {
    "N": dict(point_width=0.20, joint_gap=0.6, flare_length=1.2, plate_thickness=0.4,
              plate_margin=0.3),
    "HO": dict(point_width=0.30, joint_gap=1.0, flare_length=2.0, plate_thickness=0.5,
               plate_margin=0.5),
    "S": dict(point_width=0.40, joint_gap=1.2, flare_length=2.6, plate_thickness=0.6,
              plate_margin=0.6),
    "O": dict(point_width=0.50, joint_gap=1.6, flare_length=3.5, plate_thickness=0.8,
              plate_margin=0.8),
    "Fn3": dict(point_width=0.80, joint_gap=2.5, flare_length=6.0, plate_thickness=1.2,
                plate_margin=1.2),
    "LS": dict(point_width=1.20, joint_gap=3.0, flare_length=8.0, plate_thickness=1.5,
               plate_margin=1.5),
}


def _builtin() -> dict[str, FrogSpec]:
    """Build the built-in presets, smallest scale first."""
    specs = [
        ("N", 6, 55, "N scale #6 on code 55 rail"),
        ("N", 10, 55, "N scale #10 on code 55 rail"),
        ("HO", 4, 83, "HO #4 (yard / industrial) on code 83 rail"),
        ("HO", 6, 83, "HO #6 (common mainline turnout) on code 83 rail"),
        ("HO", 8, 83, "HO #8 (mainline) on code 83 rail"),
        ("HO", 6, 70, "HO #6 branchline on code 70 rail"),
        ("HO", 6, 100, "HO #6 on code 100 rail"),
        ("S", 6, 100, "S scale fine #6 on code 100 rail"),
        ("O", 6, 148, "O scale #6 on code 148 rail"),
        ("Fn3", 6, 250, "Fn3 (1:20.3 narrow gauge) #6 on code 250 rail"),
        ("LS", 6, 332, "G / large scale (45 mm gauge) #6 on code 332 rail"),
    ]
    out = {}
    for scale, number, code, desc in specs:
        std = SCALES[scale]
        name = f"{'G' if scale == 'LS' else scale} #{number} Code {code}"
        out[name] = FrogSpec(name=name, frog_number=float(number), rail_preset=f"Code {code}",
                             scale=scale, flangeway_width=std.width, flangeway_depth=std.depth,
                             description=desc, **SCALE_DEFAULTS[scale])
    return out


BUILTIN_PRESETS: dict[str, FrogSpec] = _builtin()
DEFAULT_PRESET = "HO #6 Code 83"


class PresetError(Exception):
    """Raised when a preset can't be saved, deleted or loaded (the message says why)."""


class PresetLibrary:
    """Built-in frog presets plus user presets stored in one JSON file.

    Built-ins are read-only; user presets may not reuse a built-in name.
    """

    def __init__(self, user_file: str | None = None):
        """Load built-ins plus user presets from ``user_file`` (None keeps them in memory only)."""
        self.user_file = user_file
        self._user: dict[str, FrogSpec] = {}
        self.reload()

    # ----------------------------------------------------------- queries
    def names(self) -> list[str]:
        """All preset names: built-ins first, then user presets alphabetically."""
        return list(BUILTIN_PRESETS) + self.user_names()

    def builtin_names(self) -> list[str]:
        """Names of the built-in presets."""
        return list(BUILTIN_PRESETS)

    def user_names(self) -> list[str]:
        """Names of the user presets, sorted ignoring case."""
        return sorted(self._user, key=str.casefold)

    def is_builtin(self, name: str) -> bool:
        """True if ``name`` is a built-in preset."""
        return name in BUILTIN_PRESETS

    def get(self, name: str) -> FrogSpec:
        """Return a *copy* of the preset (safe to modify)."""
        if name in BUILTIN_PRESETS:
            return BUILTIN_PRESETS[name].copy()
        if name in self._user:
            return self._user[name].copy()
        raise KeyError(f"No frog preset named '{name}'")

    # ---------------------------------------------------------- mutation
    def save(self, spec: FrogSpec, overwrite: bool = True) -> None:
        """Validate ``spec`` and save it as a user preset under its name."""
        name = (spec.name or "").strip()
        if not name:
            raise PresetError("Preset name cannot be empty")
        if name in BUILTIN_PRESETS:
            raise PresetError(f"'{name}' is a built-in preset; choose another name")
        if name in self._user and not overwrite:
            raise PresetError(f"Preset '{name}' already exists")
        errs = spec.validate()
        if errs:
            raise PresetError("; ".join(errs))
        self._user[name] = spec.copy(name=name)
        self._write()

    def delete(self, name: str) -> None:
        """Delete the user preset ``name`` (built-ins can't be deleted)."""
        if name in BUILTIN_PRESETS:
            raise PresetError("Built-in presets cannot be deleted")
        if name not in self._user:
            raise KeyError(f"No user preset named '{name}'")
        del self._user[name]
        self._write()

    # ------------------------------------------------------------- file io
    def reload(self) -> None:
        """Re-read user presets from disk, skipping any bad entries."""
        self._user = {}
        if not self.user_file or not os.path.isfile(self.user_file):
            return
        try:
            with open(self.user_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as ex:
            print(f"[Switch Frog] Could not read presets file {self.user_file}: {ex}")
            return
        for d in data.get("presets", []):
            try:
                s = FrogSpec.from_dict(d)
                if s.name and s.name not in BUILTIN_PRESETS:
                    self._user[s.name] = s
            except (TypeError, ValueError) as ex:
                print(f"[Switch Frog] Skipping bad preset {d!r}: {ex}")

    def export_json(self, path: str, names: list[str] | None = None) -> None:
        """Write the given presets (default: all user presets) to a file for sharing."""
        names = names or self.user_names()
        data = {"version": PRESET_FILE_VERSION, "presets": [self.get(n).to_dict() for n in names]}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    def import_json(self, path: str, overwrite: bool = True) -> list[str]:
        """Merge presets from a file; returns the names imported."""
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        done = []
        for d in data.get("presets", []):
            s = FrogSpec.from_dict(d)
            if not s.name or s.name in BUILTIN_PRESETS or (s.name in self._user and not overwrite):
                continue
            if s.is_valid():
                self._user[s.name] = s
                done.append(s.name)
        self._write()
        return done

    def _write(self) -> None:
        """Save user presets to the JSON file atomically, so a crash can't corrupt it."""
        if not self.user_file:
            return
        folder = os.path.dirname(self.user_file) or "."
        os.makedirs(folder, exist_ok=True)
        data = {"version": PRESET_FILE_VERSION,
                "presets": [self._user[n].to_dict() for n in self.user_names()]}
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, self.user_file)
