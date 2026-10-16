"""Frog specification, layout and solid parts.  Pure Python (no bpy).

Coordinates (model millimetres)::

    y : along the frog centreline, toe at -y, heel at +y
    x : across the frog, +x to the right looking toward the heel
    z : up; the rail base sits on z = 0 (a base plate goes below 0)

The origin is the *theoretical point* (TP), where the two gauge lines
cross.  The gauge lines are ``x = +y*t`` (the right-hand route) and
``x = -y*t`` (the left-hand route), with ``t = tan(angle / 2)``.

Frog number N follows the usual (AREA) definition N = 1 / (2 tan(angle/2)),
so t = 1 / (2N): a #6 frog spreads 1 mm for every 6 mm along its centreline.

Parts of the frog::

    toe                 knuckle  TP  actual point            heel
     |                     |      |    |                       |
     \\_____ left wing rail __/----------------------------- flare
                               flangeway
                    throat    <==  V point  ==> point rails split
     /‾‾‾‾‾ right wing rail ‾‾\\----------------------------- flare

* The **V point** is one solid from the actual (blunt) point to where the
  two point rails' heads separate; beyond that each **point rail** is a
  normal rail sweep to the heel.
* Each **wing rail** runs along a gauge line from the toe to the knuckle,
  then bends to run parallel to the opposite point rail one flangeway
  away, with an optional outward flare at the heel end.
* An optional **fill** joins the pieces between the wing rails, either at
  the rail base or up to the flangeway floor, and an optional **base
  plate** sits under everything.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields, replace

from .geometry import MeshData, extrude_polygon, loft_sections, offset_polyline
from .standards import MIN_DEPTH_RATIO, MIN_WIDTH_RATIO, SCALES

FILL_MODES = ("NONE", "BASE", "FLOOR")
LENGTH_MODES = ("AUTO", "MANUAL")
ALIGNMENTS = ("CENTERED", "LEFT_HAND", "RIGHT_HAND")

#: Rail profile dimensions the frog needs (attributes of the Rail API's RailProfile).
PROFILE_KEYS = ("height", "head_width", "head_depth", "web_thickness", "base_width",
                "base_thickness", "base_edge_thickness", "head_corner_radius",
                "corner_segments")


def frog_angle_deg(number: float) -> float:
    """Frog angle in degrees for a frog number: 2 * atan(1 / (2N))."""
    if number <= 0:
        raise ValueError("frog number must be greater than 0")
    return math.degrees(2.0 * math.atan(1.0 / (2.0 * number)))


def frog_number_from_angle(angle_deg: float) -> float:
    """Frog number for a frog angle in degrees (inverse of ``frog_angle_deg``)."""
    if not 0 < angle_deg < 180:
        raise ValueError("angle must be between 0 and 180 degrees")
    return 1.0 / (2.0 * math.tan(math.radians(angle_deg) / 2.0))


@dataclass
class FrogSpec:
    """Everything that defines a frog except the rail profile (lengths in model mm).

    ``rail_preset`` names the Rail Generator preset the frog is normally
    built with; it may be empty, and a profile passed to the builder
    always wins.  ``scale`` is a key of ``standards.SCALES`` (e.g. "HO") or
    "" for none; it is used to check the flangeway against the NMRA standard.
    """

    name: str = "Custom frog"
    frog_number: float = 6.0
    rail_preset: str = ""
    flangeway_width: float = 1.27
    flangeway_depth: float = 0.80
    point_width: float = 0.30
    point_drop: float = 0.0
    point_ramp: float = 3.0
    length_mode: str = "AUTO"
    toe_length: float = 12.0
    heel_length: float = 24.0
    joint_gap: float = 1.0
    flare_length: float = 2.0
    flare_angle: float = 10.0
    fill: str = "FLOOR"
    base_plate: bool = False
    plate_thickness: float = 0.5
    plate_margin: float = 0.5
    scale: str = ""
    description: str = ""

    # ------------------------------------------------------------- info
    @property
    def angle_deg(self) -> float:
        """Frog angle in degrees."""
        return frog_angle_deg(self.frog_number)

    def validate(self) -> list[str]:
        """Problems that don't depend on the rail profile (empty list = valid)."""
        e: list[str] = []
        if not 1.0 <= self.frog_number <= 40.0:
            e.append("frog number must be between 1 and 40")
        if self.flangeway_width <= 0:
            e.append("flangeway width must be greater than 0")
        if self.flangeway_depth <= 0:
            e.append("flangeway depth must be greater than 0")
        if self.point_width <= 0:
            e.append("point width must be greater than 0")
        if self.point_drop < 0 or self.point_ramp < 0:
            e.append("point drop and ramp cannot be negative")
        if self.length_mode not in LENGTH_MODES:
            e.append(f"length mode must be one of {LENGTH_MODES}")
        elif self.length_mode == "MANUAL" and (self.toe_length <= 0 or self.heel_length <= 0):
            e.append("toe and heel lengths must be greater than 0")
        if self.joint_gap < 0:
            e.append("joint gap cannot be negative")
        if self.flare_length < 0:
            e.append("flare length cannot be negative")
        if not 0 <= self.flare_angle <= 45:
            e.append("flare angle must be between 0 and 45 degrees")
        if self.fill not in FILL_MODES:
            e.append(f"fill must be one of {FILL_MODES}")
        if self.base_plate and self.plate_thickness <= 0:
            e.append("base plate thickness must be greater than 0")
        if self.plate_margin < 0:
            e.append("base plate margin cannot be negative")
        if self.scale and self.scale not in SCALES:
            e.append(f"scale must be one of {list(SCALES)} or empty")
        return e

    def is_valid(self) -> bool:
        """True if ``validate`` finds no problems."""
        return not self.validate()

    # ---------------------------------------------------- serialisation
    def to_dict(self) -> dict:
        """Spec as a JSON-safe dict, with the derived ``angle_deg`` included for readers."""
        d = asdict(self)
        d["angle_deg"] = round(self.angle_deg, 6) if self.frog_number > 0 else 0.0
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FrogSpec":
        """Build a spec from a dict, ignoring unknown keys such as ``angle_deg``."""
        kinds = {f.name: f.type for f in fields(cls)}
        kw = {}
        for k, v in d.items():
            if k not in kinds:
                continue
            t = str(kinds[k])
            if t == "float":
                v = float(v)
            elif t == "bool":
                v = bool(v)
            elif t == "str":
                v = str(v)
            kw[k] = v
        return cls(**kw)

    def copy(self, **changes) -> "FrogSpec":
        """Copy of this spec with any fields in ``changes`` replaced."""
        return replace(self, **changes)


# ================================================================= layout
@dataclass
class Dims:
    """The rail profile dimensions the frog uses, read from any profile-like object."""

    height: float
    head_width: float
    head_depth: float
    web_thickness: float
    base_width: float
    base_thickness: float
    base_edge_thickness: float
    head_corner_radius: float = 0.0
    corner_segments: int = 3

    @classmethod
    def of(cls, profile) -> "Dims":
        """Read the dimensions from a RailProfile-like object or a dict."""
        get = profile.get if isinstance(profile, dict) else lambda k, d=None: getattr(profile, k, d)
        kw = {}
        for k in PROFILE_KEYS:
            v = get(k, None)
            if v is None:
                if k in ("head_corner_radius", "corner_segments"):
                    continue
                raise ValueError(f"rail profile is missing '{k}'")
            kw[k] = int(v) if k == "corner_segments" else float(v)
        return cls(**kw)


@dataclass
class FrogLayout:
    """Where everything goes, in model mm, worked out from a spec and a rail profile.

    y values are measured along the centreline from the theoretical point
    (negative toward the toe).  Gauge-line polylines are lists of (x, y).
    """

    number: float
    angle_deg: float
    t: float                       # tan(angle / 2): gauge lines are x = +/- y * t
    k: float                       # 1 / cos(angle / 2): widths measured across the frog
    y_toe: float
    y_knuckle: float
    y_point: float                 # actual (blunt) point
    y_split: float                 # point rail heads separate here
    y_heel: float
    y_flare: float                 # wing rails start to flare here (= y_heel if no flare)
    fill_top: float                # z of the fill top, 0 when there is no fill
    left_wing: list = field(default_factory=list)
    right_wing: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def toe_length(self) -> float:
        """Distance from the theoretical point back to the toe (mm)."""
        return -self.y_toe

    @property
    def heel_length(self) -> float:
        """Distance from the theoretical point to the heel (mm)."""
        return self.y_heel

    @property
    def length(self) -> float:
        """Overall frog length, toe to heel (mm)."""
        return self.y_heel - self.y_toe

    @property
    def throat_width(self) -> float:
        """Gap between the wing rails' gauge faces at the knuckle (mm)."""
        return 2.0 * abs(self.y_knuckle) * self.t

    @property
    def heel_spread(self) -> float:
        """Distance between the point rails' gauge faces at the heel (mm)."""
        return 2.0 * self.y_heel * self.t

    @property
    def toe_spread(self) -> float:
        """Distance between the wing rails' gauge faces at the toe (mm)."""
        return 2.0 * abs(self.y_toe) * self.t

    def summary(self) -> dict:
        """Key numbers as a plain dict (handy for other add-ons and the UI)."""
        return {k: round(v, 4) for k, v in {
            "frog_number": self.number, "angle_deg": self.angle_deg,
            "toe_length": self.toe_length, "heel_length": self.heel_length,
            "length": self.length, "knuckle_y": self.y_knuckle, "point_y": self.y_point,
            "split_y": self.y_split, "throat_width": self.throat_width,
            "toe_spread": self.toe_spread, "heel_spread": self.heel_spread,
            "fill_top": self.fill_top}.items()}


def compute_layout(spec: FrogSpec, profile) -> FrogLayout:
    """Work out the frog's layout; problems go in ``errors`` and ``warnings``."""
    P = Dims.of(profile)
    errs = list(spec.validate())
    n = spec.frog_number if spec.frog_number > 0 else 6.0
    half = math.atan(1.0 / (2.0 * n))
    t, k = math.tan(half), 1.0 / math.cos(half)
    hw, bw = P.head_width, P.base_width
    fw = spec.flangeway_width

    y_knuckle = -fw / (2.0 * t)
    y_point = spec.point_width / (2.0 * t)
    y_split = k * hw / t
    flare = spec.flare_length if spec.flare_angle > 0 else 0.0

    if spec.length_mode == "AUTO":
        toe = max((spec.joint_gap + k * (bw - hw)) / (2.0 * t), 1.5 * abs(y_knuckle))
        heel = max((spec.joint_gap / 2.0 + k * (hw + bw) / 2.0) / t,
                   y_split + flare + k * hw / t * 0.25,
                   y_point + flare + 1.0)
    else:
        toe, heel = spec.toe_length, spec.heel_length

    lay = FrogLayout(number=n, angle_deg=math.degrees(2 * half), t=t, k=k,
                     y_toe=-toe, y_knuckle=y_knuckle, y_point=y_point, y_split=y_split,
                     y_heel=heel, y_flare=heel - flare, fill_top=0.0)

    if y_point >= y_split:
        errs.append(f"point width must be less than {2 * k * hw:.3f} mm "
                    "(two rail heads) for this rail")
    if toe <= abs(y_knuckle) + 1e-6:
        errs.append(f"toe length must be more than {abs(y_knuckle):.2f} mm "
                    "(the knuckle) for this flangeway and frog number")
    if heel <= y_point + flare + 1e-6:
        errs.append(f"heel length must be more than {y_point + flare:.2f} mm "
                    "(actual point plus flare)")
    if spec.point_drop >= 0.8 * P.head_depth:
        errs.append(f"point drop must be less than {0.8 * P.head_depth:.3f} mm "
                    "(80% of the head depth)")
    lay.errors = errs
    if errs:
        return lay

    # Wing rail gauge lines: along a gauge line to the knuckle, then one
    # flangeway outside the opposite point rail, flaring out at the heel.
    flare_out = flare * math.tan(math.radians(spec.flare_angle))
    left = [(lay.y_toe * t, lay.y_toe), (-fw / 2.0, y_knuckle)]
    if flare > 0:
        left.append((-lay.y_flare * t - fw, lay.y_flare))
    left.append((-heel * t - fw - flare_out, heel))
    lay.left_wing = left
    lay.right_wing = [(-x, y) for x, y in left]

    if spec.fill == "FLOOR":
        lay.fill_top = P.height - spec.flangeway_depth
        if lay.fill_top <= 0:
            lay.fill_top = 0.0
            lay.warnings.append("Flangeway is deeper than the rail, so there is no floor fill.")
    elif spec.fill == "BASE":
        lay.fill_top = P.base_thickness

    if lay.fill_top <= 0 and not spec.base_plate:
        lay.warnings.append("The point and the two wing rails are separate pieces; "
                            "choose a Fill or a Base Plate to print the frog as one piece.")
    lay.warnings.extend(flangeway_warnings(spec, P))
    if spec.point_width < 0.2:
        lay.warnings.append(f"The point is {spec.point_width:.2f} mm wide; resin printers "
                            "need about 0.2 mm and FDM about 0.4 mm.")
    if spec.length_mode == "MANUAL" and heel < y_split:
        lay.warnings.append("The heel is before the point rails separate, so the frog "
                            "ends in a solid V.")
    return lay


def flangeway_warnings(spec: FrogSpec, profile) -> list[str]:
    """Warnings when the flangeway is too shallow or narrow for the scale or the rail.

    Checks against the NMRA standard when ``spec.scale`` is set, and always
    against the rail height, which catches an HO flangeway left on G rail.
    """
    P = profile if isinstance(profile, Dims) else Dims.of(profile)
    fw, fd, h = spec.flangeway_width, spec.flangeway_depth, P.height
    out = []
    std = SCALES.get(spec.scale)
    floor = spec.fill == "FLOOR"
    if std is not None:
        if floor and fd < std.min_depth - 1e-9:
            out.append(f"Flangeway depth {fd:.2f} mm is under the NMRA {std.key} minimum of "
                       f"{std.min_depth:.2f} mm; wheel flanges may hit the floor.")
        if fw > std.max_width + 1e-9:
            out.append(f"Flangeway width {fw:.2f} mm is over the NMRA {std.key} maximum of "
                       f"{std.max_width:.2f} mm; wheels may drop into the gap.")
    if floor and fd < MIN_DEPTH_RATIO * h:
        out.append(f"Flangeway is only {fd:.2f} mm deep on {h:.2f} mm rail, probably too "
                   "shallow for its wheels: pick the Scale and click Set Flangeway.")
    if fw < MIN_WIDTH_RATIO * h:
        out.append(f"Flangeway is only {fw:.2f} mm wide on {h:.2f} mm rail, probably too "
                   "narrow for its wheels: pick the Scale and click Set Flangeway.")
    return out


# ================================================================== parts
def _v_section(g: float, top: float, P: Dims, k: float) -> list[tuple[float, float]]:
    """Cross-section (x, z) of the V point where its head is ``2 * g`` wide.

    The head reaches the gauge lines (x = +/- g); the webs of the two point
    rails and the space between them are solid; the bases are the outer
    halves of the two rail bases.  Same number of points for every ``g``.
    """
    zh = P.height - P.head_depth
    W = max(g - k * (P.head_width - P.web_thickness) / 2.0, k * P.web_thickness / 2.0)
    W = min(W, 0.85 * g)
    B = max(g + k * (P.base_width - P.head_width) / 2.0, W + 0.05 * P.base_width)
    right = [(B, 0.0), (B, P.base_edge_thickness), (W, P.base_thickness), (W, zh), (g, zh)]
    if P.head_corner_radius > 0:
        r = min(P.head_corner_radius, 0.45 * g, 0.9 * (top - zh))
        segs = max(1, int(P.corner_segments))
        cx, cz = g - r, top - r
        for i in range(segs + 1):
            a = (math.pi / 2.0) * i / segs
            right.append((cx + r * math.cos(a), cz + r * math.sin(a)))
    else:
        right.append((g, top))
    left = [(-x, z) for x, z in reversed(right)]
    return right + left


def _v_point(spec: FrogSpec, lay: FrogLayout, P: Dims) -> MeshData:
    """The solid V from the actual point to where the point rails separate (or the heel)."""
    t, k = lay.t, lay.k
    y0, y1 = lay.y_point, min(lay.y_split, lay.y_heel)
    ramp_end = y0 + spec.point_ramp if spec.point_drop > 0 and spec.point_ramp > 0 else y0

    def top(y):
        """Height of the head top at ``y`` (lowered near the point by the drop)."""
        if ramp_end <= y0:
            return P.height
        return P.height - spec.point_drop * max(0.0, 1.0 - (y - y0) / (ramp_end - y0))

    hw, wt = P.head_width, P.web_thickness
    marks = [k * hw / 2.0, k * (hw - wt) / 2.0 / 0.15, k * wt / 1.7]
    if P.head_corner_radius > 0:
        marks.append(P.head_corner_radius / 0.45)
    ys = {y0, y1, ramp_end}
    ys.update(g / t for g in marks)
    ys.update(y0 + (y1 - y0) * i / 12.0 for i in range(13))
    ys = sorted(y for y in ys if y0 - 1e-9 <= y <= y1 + 1e-9)
    clean = [ys[0]]
    for y in ys[1:]:
        if y - clean[-1] > 1e-6:
            clean.append(y)
    clean[-1] = y1
    return loft_sections([(y, _v_section(y * t, top(y), P, k)) for y in clean])


def _sweep(rail_api, profile, pts, lateral) -> MeshData:
    """A rail swept along plan points (x, y) with the Rail API, as frog MeshData."""
    spec = {"kind": "POLYLINE", "points": [(x, y, 0.0) for x, y in pts], "closed": False}
    return MeshData.from_any(rail_api.generate_rail_mesh(profile, spec, lateral_offset=lateral))


def build_parts(spec: FrogSpec, profile, rail_api, layout: FrogLayout | None = None
                ) -> dict[str, MeshData]:
    """Every solid of the frog by name, in mm, centred as described in this module.

    ``rail_api`` is the Rail Generator's API module (it sweeps the rails).
    The solids overlap where they join; ``api.create_frog_object`` merges
    them into one manifold solid.  Raises ValueError if the layout has errors.
    """
    lay = layout or compute_layout(spec, profile)
    if lay.errors:
        raise ValueError("Invalid frog: " + "; ".join(lay.errors))
    P = Dims.of(profile)
    t, k, hw = lay.t, lay.k, P.head_width
    parts: dict[str, MeshData] = {"V Point": _v_point(spec, lay, P)}

    if lay.y_heel > lay.y_split + 1e-6:
        y0 = max(lay.y_point, lay.y_split - P.base_width * math.sin(math.atan(t)) - 0.02)
        parts["Point Rail R"] = _sweep(rail_api, profile,
                                       [(y0 * t, y0), (lay.y_heel * t, lay.y_heel)], -hw / 2.0)
        parts["Point Rail L"] = _sweep(rail_api, profile,
                                       [(-y0 * t, y0), (-lay.y_heel * t, lay.y_heel)], hw / 2.0)

    parts["Wing Rail L"] = _sweep(rail_api, profile, lay.left_wing, -hw / 2.0)
    parts["Wing Rail R"] = _sweep(rail_api, profile, lay.right_wing, hw / 2.0)

    if lay.fill_top > 0:
        left_c = offset_polyline(lay.left_wing, -hw / 2.0)
        right_c = offset_polyline(lay.right_wing, hw / 2.0)
        parts["Fill"] = extrude_polygon(left_c + list(reversed(right_c)), 0.0, lay.fill_top)

    if spec.base_plate:
        d = hw / 2.0 + P.base_width / 2.0 + spec.plate_margin
        left_o = offset_polyline(lay.left_wing, -d)
        right_o = offset_polyline(lay.right_wing, d)
        parts["Base Plate"] = extrude_polygon(left_o + list(reversed(right_o)),
                                              -spec.plate_thickness, 0.0)
    return parts


def alignment_rotation(spec: FrogSpec, alignment: str) -> float:
    """Degrees to turn the frog (about the TP) for an alignment.

    ``CENTERED``: centreline along +Y.  ``LEFT_HAND``: the right-hand route's
    gauge line along +Y, so the other route diverges to the left (as in a
    left-hand turnout).  ``RIGHT_HAND``: the mirror image.
    """
    alignment = (alignment or "CENTERED").upper()
    if alignment not in ALIGNMENTS:
        raise ValueError(f"alignment must be one of {ALIGNMENTS}")
    half = spec.angle_deg / 2.0
    return {"CENTERED": 0.0, "LEFT_HAND": half, "RIGHT_HAND": -half}[alignment]
