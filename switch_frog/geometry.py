"""Mesh helpers for the frog: MeshData, triangulation, lofts and extrusions.  Pure Python (no bpy).

Units are millimetres.  Plan coordinates are (x, y) with y along the frog
centreline; z is up.  Every solid built here is closed, with outward-facing
(counter-clockwise) faces.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


# ==================================================================== mesh
@dataclass
class MeshData:
    """Simple indexed mesh in millimetres: tris and quads wound outward.

    Same interface as the Rail Generator's ``MeshData`` so either can be
    passed to the exporters.
    """

    vertices: list[Vec3] = field(default_factory=list)
    faces: list[tuple[int, ...]] = field(default_factory=list)

    def triangles(self) -> list[tuple[int, int, int]]:
        """Faces split into triangles (quads become two triangles)."""
        tris = []
        for f in self.faces:
            for i in range(1, len(f) - 1):
                tris.append((f[0], f[i], f[i + 1]))
        return tris

    def volume(self) -> float:
        """Signed volume in mm^3 (positive when normals face outward)."""
        v = self.vertices
        s = 0.0
        for a, b, c in self.triangles():
            ax, ay, az = v[a]; bx, by, bz = v[b]; cx, cy, cz = v[c]
            s += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
        return s / 6.0

    def bounds(self) -> tuple[Vec3, Vec3]:
        """Bounding box as ((min x, y, z), (max x, y, z)) in millimetres."""
        xs, ys, zs = zip(*self.vertices)
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def is_manifold(self) -> bool:
        """Every edge shared by exactly two faces in opposite directions."""
        edges: dict[tuple[int, int], int] = {}
        for f in self.faces:
            for i in range(len(f)):
                e = (f[i], f[(i + 1) % len(f)])
                edges[e] = edges.get(e, 0) + 1
        return all(c == 1 and edges.get((b, a)) == 1 for (a, b), c in edges.items())

    def transformed(self, scale: float = 1.0, offset: Vec3 = (0.0, 0.0, 0.0)) -> "MeshData":
        """Copy of the mesh scaled by ``scale`` and then moved by ``offset``."""
        ox, oy, oz = offset
        return MeshData([(x * scale + ox, y * scale + oy, z * scale + oz)
                         for x, y, z in self.vertices], list(self.faces))

    def rotated_z(self, degrees: float) -> "MeshData":
        """Copy of the mesh turned ``degrees`` counter-clockwise about the Z axis."""
        if not degrees:
            return MeshData(list(self.vertices), list(self.faces))
        a = math.radians(degrees)
        c, s = math.cos(a), math.sin(a)
        return MeshData([(x * c - y * s, x * s + y * c, z) for x, y, z in self.vertices],
                        list(self.faces))

    @classmethod
    def from_any(cls, md) -> "MeshData":
        """Copy any object with ``vertices`` and ``faces`` (e.g. the Rail API's MeshData)."""
        return cls([tuple(map(float, v)) for v in md.vertices], [tuple(f) for f in md.faces])


def merge(meshes) -> MeshData:
    """Combine several MeshData into one (shells may overlap), renumbering faces."""
    out = MeshData()
    for md in meshes:
        base = len(out.vertices)
        out.vertices.extend(md.vertices)
        out.faces.extend(tuple(i + base for i in f) for f in md.faces)
    return out


# ============================================================ 2D helpers
def polygon_area(pts) -> float:
    """Signed area of a 2D polygon (positive = counter-clockwise)."""
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def triangulate_polygon(pts) -> list[tuple[int, int, int]]:
    """Triangulate a simple 2D polygon by ear clipping; returns CCW index triples."""
    n = len(pts)
    idx = list(range(n))
    if polygon_area(pts) < 0:
        idx.reverse()

    def cross(o, a, b):
        """Z of the cross product of o->a and o->b (positive when a-b turns left)."""
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(p, a, b, c):
        """True if point ``p`` lies inside or on triangle a-b-c."""
        return cross(a, b, p) >= -1e-12 and cross(b, c, p) >= -1e-12 and cross(c, a, p) >= -1e-12

    tris = []
    guard = 0
    while len(idx) > 3 and guard < 10 * n * n:
        guard += 1
        L = len(idx)
        clipped = False
        for i in range(L):
            a, b, c = idx[i - 1], idx[i], idx[(i + 1) % L]
            if cross(pts[a], pts[b], pts[c]) <= 1e-12:
                continue
            if any(inside(pts[o], pts[a], pts[b], pts[c])
                   for o in idx if o not in (a, b, c)
                   and pts[o] not in (pts[a], pts[b], pts[c])):
                continue
            tris.append((a, b, c))
            idx.pop(i)
            clipped = True
            break
        if not clipped:
            for i in range(L):          # drop a collinear vertex, or give up and fan
                a, b, c = idx[i - 1], idx[i], idx[(i + 1) % L]
                if abs(cross(pts[a], pts[b], pts[c])) <= 1e-12:
                    idx.pop(i)
                    break
            else:
                break
    if len(idx) == 3:
        tris.append(tuple(idx))
    elif len(idx) > 3:
        tris.extend((idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1))
    return tris


def offset_polyline(pts: list[Vec2], d: float) -> list[Vec2]:
    """Offset an open 2D polyline sideways by ``d`` (positive = right of travel).

    Corners are mitred so the offset line stays parallel to each segment.
    """
    n = len(pts)
    if n < 2:
        raise ValueError("a polyline needs at least two points")

    def unit(a, b):
        """Unit direction from ``a`` to ``b``."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-12:
            raise ValueError("polyline has repeated points")
        return dx / L, dy / L

    out = []
    for i, p in enumerate(pts):
        dirs = []
        if i > 0:
            dirs.append(unit(pts[i - 1], p))
        if i < n - 1:
            dirs.append(unit(p, pts[i + 1]))
        tx, ty = sum(u[0] for u in dirs), sum(u[1] for u in dirs)
        L = math.hypot(tx, ty) or 1.0
        tx, ty = tx / L, ty / L
        miter = 1.0 / max(tx * dirs[0][0] + ty * dirs[0][1], 0.2)
        out.append((p[0] + ty * d * miter, p[1] - tx * d * miter))
    return out


# ================================================================ solids
def _orient(md: MeshData) -> MeshData:
    """Flip every face if the solid came out inside-out."""
    if md.volume() < 0:
        md.faces = [tuple(reversed(f)) for f in md.faces]
    return md


def loft_sections(sections: list[tuple[float, list[tuple[float, float]]]]) -> MeshData:
    """Closed solid through cross-sections taken across the frog.

    ``sections`` is a list of (y, outline) with y increasing; each outline is
    a CCW list of (x, z) points, and every outline has the same number of
    points so they can be joined point to point.
    """
    if len(sections) < 2:
        raise ValueError("a loft needs at least two sections")
    m = len(sections[0][1])
    if any(len(o) != m for _, o in sections):
        raise ValueError("every loft section needs the same number of points")
    verts: list[Vec3] = []
    for y, outline in sections:
        verts.extend((x, y, z) for x, z in outline)
    faces: list[tuple[int, ...]] = []
    for k in range(len(sections) - 1):
        a0, a1 = k * m, (k + 1) * m
        for i in range(m):
            j = (i + 1) % m
            faces.append((a0 + i, a1 + i, a1 + j, a0 + j))
    first = sections[0][1]
    last = (len(sections) - 1) * m
    for a, b, c in triangulate_polygon(first):
        faces.append((a, b, c))
        faces.append((last + c, last + b, last + a))
    return _orient(MeshData(verts, faces))


def extrude_polygon(plan: list[Vec2], z0: float, z1: float) -> MeshData:
    """Closed prism: the plan polygon (x, y) extruded from ``z0`` up to ``z1``."""
    if z1 <= z0:
        raise ValueError("extrusion top must be above its bottom")
    pts = list(plan)
    if polygon_area(pts) < 0:
        pts.reverse()
    n = len(pts)
    verts = [(x, y, z0) for x, y in pts] + [(x, y, z1) for x, y in pts]
    faces: list[tuple[int, ...]] = []
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    for a, b, c in triangulate_polygon(pts):
        faces.append((n + a, n + b, n + c))     # top faces up
        faces.append((c, b, a))                 # bottom faces down
    return _orient(MeshData(verts, faces))
