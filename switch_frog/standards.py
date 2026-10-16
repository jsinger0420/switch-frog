"""NMRA flangeway standards by scale.  Pure Python (no bpy).

Values are from NMRA Standard S-3.2 (Trackwork): ``F`` is the maximum
flangeway width and ``D`` the minimum flangeway depth, in model mm.
``depth`` is the depth the add-on suggests: a little deeper than ``D`` so
wheels with slightly deep flanges still clear the floor.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScaleStandard:
    """One scale's flangeway limits (model mm)."""

    key: str
    label: str
    ratio: float
    max_width: float      # NMRA F (max)
    min_depth: float      # NMRA D (min)
    depth: float          # suggested depth

    @property
    def width(self) -> float:
        """Suggested flangeway width: the NMRA maximum."""
        return self.max_width


_ROWS = [
    ("Z", "Z (1:220)", 220.0, 0.64, 0.51, 0.58),
    ("N", "N (1:160)", 160.0, 0.76, 0.56, 0.60),
    ("TT", "TT (1:120)", 120.0, 0.91, 0.56, 0.62),
    ("HO", "HO (1:87.1)", 87.1, 1.27, 0.71, 0.80),
    ("OO", "OO (1:76.2)", 76.2, 1.27, 0.71, 0.80),
    ("S", "S (1:64)", 64.0, 1.27, 0.76, 0.85),
    ("O", "O (1:48)", 48.0, 2.01, 0.91, 1.00),
    ("Fn3", "Fn3 (1:20.3, 3 ft gauge)", 20.3, 2.97, 1.68, 1.85),
    ("F", "F (1:20.3, standard gauge)", 20.3, 2.49, 2.29, 2.50),
    ("LS", "Large Scale (45 mm gauge)", 29.0, 4.60, 3.00, 3.20),
]

#: Every scale by key, smallest first.
SCALES: dict[str, ScaleStandard] = {r[0]: ScaleStandard(*r) for r in _ROWS}

#: Below these fractions of the rail height the flangeway is flagged as
#: probably too shallow / too narrow for wheels made for that rail.
MIN_DEPTH_RATIO = 0.2
MIN_WIDTH_RATIO = 0.3


def get_standard(scale: str) -> ScaleStandard:
    """The standard for a scale key such as "HO". Raises KeyError if unknown."""
    try:
        return SCALES[scale]
    except KeyError:
        raise KeyError(f"Unknown scale '{scale}'; expected one of {list(SCALES)}") from None
