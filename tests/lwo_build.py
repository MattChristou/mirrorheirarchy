# -*- coding: utf-8 -*-
"""Tiny LWO3 writer for the tests: one or more layers of points, polygons
and vmaps, plus a dummy surface FORM that must come through untouched."""

import struct


def _s0(text):
    raw = text.encode("utf-8") + b"\0"
    if len(raw) & 1:
        raw += b"\0"
    return raw


def _vx(i):
    return struct.pack(">H", i) if i < 0xFF00 else struct.pack(">I", 0xFF000000 | i)


def _chunk(cid, payload):
    out = cid + struct.pack(">I", len(payload)) + payload
    if len(payload) & 1:
        out += b"\0"
    return out


def build(layers, surfaces=("Default",), form=b"LWO3", tail=b"", surface_form=True):
    """layers: [{'points': [(x,y,z)], 'polys': [[i..]] or [(type, [i..])],
    'pivot': (x,y,z), 'vmaps': [(type, name, dim, {pnt: values})],
    'vmads': [(type, name, dim, {(pnt, pol): values})]}]"""
    body = form
    body += _chunk(b"TAGS", b"".join(_s0(s) for s in surfaces))
    for n, layer in enumerate(layers):
        pivot = layer.get("pivot", (0.0, 0.0, 0.0))
        body += _chunk(b"LAYR", struct.pack(">HH3f", n, 0, *pivot) + _s0("L%d" % n))
        pts = layer["points"]
        body += _chunk(b"PNTS", b"".join(struct.pack(">3f", *p) for p in pts))
        xs = [p[0] for p in pts] or [0.0]
        ys = [p[1] for p in pts] or [0.0]
        zs = [p[2] for p in pts] or [0.0]
        body += _chunk(b"BBOX", struct.pack(">6f", min(xs), min(ys), min(zs),
                                            max(xs), max(ys), max(zs)))
        for vtype, name, dim, values in layer.get("vmaps", []):
            recs = b"".join(_vx(p) + struct.pack(">%df" % dim, *v)
                            for p, v in sorted(values.items()))
            body += _chunk(b"VMAP", vtype + struct.pack(">H", dim) + _s0(name) + recs)
        groups = {}
        for poly in layer["polys"]:
            ptype, idx = poly if isinstance(poly, tuple) else (b"FACE", poly)
            groups.setdefault(ptype, []).append(idx)
        for ptype in sorted(groups):
            recs = b"".join(struct.pack(">H", len(idx)) + b"".join(_vx(i) for i in idx)
                            for idx in groups[ptype])
            body += _chunk(b"POLS", ptype + recs)
        npol = len(layer["polys"])
        body += _chunk(b"PTAG", b"SURF" + b"".join(_vx(i) + struct.pack(">H", 0)
                                                    for i in range(npol)))
        for vtype, name, dim, values in layer.get("vmads", []):
            recs = b"".join(_vx(p) + _vx(q) + struct.pack(">%df" % dim, *v)
                            for (p, q), v in sorted(values.items()))
            body += _chunk(b"VMAD", vtype + struct.pack(">H", dim) + _s0(name) + recs)
    if surface_form:
        # Surface FORM with an odd-sized inner chunk, to prove pass-through.
        # (Off for files LightWave will load: LWO3 makes surfaces from TAGS.)
        surf = b"SURF" + _chunk(b"    ", _s0(surfaces[0]) + _s0("")) + _chunk(b"ODDX", b"abc")
        body += _chunk(b"FORM", surf)
    body += tail
    return b"FORM" + struct.pack(">I", len(body)) + body


# An asymmetric "hand": a box offset in +X, with a weight map, a morph,
# a normal map, a discontinuous UV, a skelegon and a curve.
BOX_POINTS = [(1, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0),
              (1, 0, 1), (2, 0, 1), (2, 1, 1), (1, 1, 1.5)]
BOX_FACES = [[0, 1, 2, 3], [5, 4, 7, 6], [4, 0, 3, 7], [1, 5, 6, 2],
             [3, 2, 6, 7], [4, 5, 1, 0]]


def hand_layer():
    pts = [tuple(float(c) for c in p) for p in BOX_POINTS]
    polys = list(BOX_FACES) + [(b"BONE", [0, 6]), (b"CURV", [0, 1, 2]),
                               (b"SUBD", [0, 3, 2, 1])]
    return {
        "points": pts,
        "polys": polys,
        "pivot": (1.5, 0.5, 0.0),
        "vmaps": [
            (b"WGHT", "L_Hand", 1, dict((i, (1.0,)) for i in range(8))),
            (b"WGHT", "Thumb.R", 1, {0: (0.5,)}),
            (b"MORF", "Fist_Left", 3, {2: (0.25, -0.5, 0.1)}),
            (b"NORM", "vnormals", 3, {0: (0.6, 0.0, 0.8)}),
            (b"TXUV", "L_UV", 2, dict((i, (i * 0.1, 0.5)) for i in range(8))),
        ],
        "vmads": [(b"TXUV", "L_UV", 2, {(0, 0): (0.9, 0.9)})],
    }
