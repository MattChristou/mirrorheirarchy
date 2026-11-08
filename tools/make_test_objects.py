# -*- coding: utf-8 -*-
"""Write the Layout test objects (LWO3) for TESTING.md.

    python -B tools/make_test_objects.py [out_dir]     (default C:/tmp/MirrorHierarchy)

L_Hand.lwo   asymmetric: a slab at X 1..2 with a "thumb" wedge on its +Z
             side and a "knuckle" bump on top, so a mirrored copy is easy
             to tell apart. Faces wound so every normal points OUTWARD
             (LightWave: clockwise seen from the front). Weight map L_Hand
             on every point, morph Fist_Left, a UV map. Layer pivot at the
             wrist (1, 0.25, 0.5).
Sym_Head.lwo symmetric about X = 0 (a box centred on the origin); the
             plug-in should keep this file for its clone.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))

import lwo_build  # noqa: E402


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def outward(points, faces):
    """Reorder each face so cross(v1 - v0, v2 - v0) points away from the
    solid's centre - LightWave's front side."""
    centre = [sum(p[i] for p in points) / len(points) for i in range(3)]
    out = []
    for f in faces:
        n = _cross(_sub(points[f[1]], points[f[0]]), _sub(points[f[2]], points[f[0]]))
        fc = [sum(points[i][k] for i in f) / len(f) for k in range(3)]
        if sum(n[k] * (fc[k] - centre[k]) for k in range(3)) < 0.0:
            f = [f[0]] + f[:0:-1]
        out.append(f)
    return out


def box(x0, x1, y0, y1, z0, z1, base=0):
    pts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
           (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [[0, 1, 2, 3], [4, 5, 6, 7], [0, 4, 7, 3], [1, 5, 6, 2],
             [3, 2, 6, 7], [0, 1, 5, 4]]
    return pts, outward(pts, faces), base


def hand():
    pts, faces = [], []
    for spec in ((1.0, 2.0, 0.0, 0.5, 0.0, 1.0),        # palm slab
                 (1.6, 2.4, 0.1, 0.4, 1.0, 1.5),        # thumb, sticks out +Z and +X
                 (1.1, 1.5, 0.5, 0.8, 0.2, 0.6)):       # knuckle on top
        p, f, _ = box(*spec)
        base = len(pts)
        pts.extend(p)
        faces.extend([[i + base for i in face] for face in f])
    n = len(pts)
    return {
        "points": [tuple(float(c) for c in p) for p in pts],
        "polys": faces,
        "pivot": (1.0, 0.25, 0.5),
        "vmaps": [
            (b"WGHT", "L_Hand", 1, dict((i, (1.0,)) for i in range(n))),
            (b"MORF", "Fist_Left", 3, dict((i, (0.0, -0.2, 0.0)) for i in range(16, n))),
            (b"TXUV", "UVMap", 2, dict((i, (pts[i][0] - 1.0, pts[i][2])) for i in range(n))),
        ],
    }


def head():
    p, f, _ = box(-0.5, 0.5, 0.0, 1.0, -0.5, 0.5)
    return {"points": [tuple(float(c) for c in q) for q in p], "polys": f}


def main(argv):
    out_dir = argv[0] if argv else "C:/tmp/MirrorHierarchy"
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    for name, layer in (("L_Hand.lwo", hand()), ("Sym_Head.lwo", head())):
        path = os.path.join(out_dir, name)
        with open(path, "wb") as fh:
            fh.write(lwo_build.build([layer], surfaces=(name[:-4],), surface_form=False))
        print("wrote " + path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
