# -*- coding: utf-8 -*-
"""Mirror a LightWave object file across its own X axis.

    python lwo_mirror.py in.lwo out.lwo [--sides "Lf/Rt,lft/rgt"] [--keep-names]

Works on the IFF chunks directly, so everything the mirror does not need to
touch (surfaces and their node graphs, image clips, envelopes, unknown
chunks) is copied byte for byte. LWO3 and LWO2 share the chunks changed here.

What changes:
    PNTS          negate X
    POLS          FACE / PTCH / SUBD: reverse the winding (keep vertex 0
                  first). CURV, BONE (skelegons), MBAL, PTCL: untouched -
                  they have no winding, and reversing a skelegon flips it.
    VMAP / VMAD   MORF, SPOT, NORM: negate X. WGHT, MORF, SPOT, PICK:
                  swap left/right in the map name (L_Arm -> R_Arm) unless
                  names are kept.
    BBOX          negate and swap the X bounds
    LAYR          negate the pivot's X
    FORM (SURF..) LWO3 node graphs: a leaf chunk holding exactly one of the
                  renamed map names (e.g. a Weight Map node's NDTA/NAME) is
                  renamed to match; node identity chunks (NNME, IINN, ...)
                  never are. Any renamed name still found elsewhere is
                  listed in stats['unresolved'] (e.g. LWO2 surfaces).

Point and polygon order never change, so every PTAG / VMAP / VMAD index
stays valid.

No lwsdk import. Not a plug-in container (no LightWave version marker).
Keep it Python 2.7-parseable.
"""

from __future__ import print_function

import os
import struct
import sys

try:
    import mirror_math
except ImportError:                                   # run as a script
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mirror_math

REVERSE_POLY_TYPES = (b"FACE", b"PTCH", b"SUBD")
NEGATE_X_VMAPS = (b"MORF", b"SPOT", b"NORM")
RENAME_VMAPS = (b"WGHT", b"MORF", b"SPOT", b"PICK")

# Node-graph chunks that name NODES (or surfaces), not maps: never renamed,
# or connections (IINN refers to NNME) would break.
NODE_ID_CHUNKS = (b"NSRV", b"NRNM", b"NNME", b"IINN", b"IONM", b"INME", b"OINN",
                  b"ONME", b"NPRW", b"    ")


class LwoError(Exception):
    pass


# --------------------------------------------------
# IFF primitives (bytearray in, ints out - same in Python 2 and 3)
# --------------------------------------------------


def _u2(buf, off):
    return struct.unpack(">H", bytes(buf[off:off + 2]))[0]


def _u4(buf, off):
    return struct.unpack(">I", bytes(buf[off:off + 4]))[0]


def read_vx(buf, off):
    """(index, next offset). 2 bytes, or 4 when the first byte is 0xFF."""
    if buf[off] == 0xFF:
        return _u4(buf, off) & 0x00FFFFFF, off + 4
    return _u2(buf, off), off + 2


def read_s0(buf, off):
    """(raw name bytes, next offset) - NUL-terminated, padded to even."""
    end = off
    while end < len(buf) and buf[end] != 0:
        end += 1
    if end >= len(buf):
        raise LwoError("unterminated string at %d" % off)
    raw = bytes(buf[off:end])
    size = end - off + 1
    return raw, off + size + (size & 1)


def write_s0(raw):
    out = bytearray(raw) + bytearray(b"\0")
    if len(out) & 1:
        out += bytearray(b"\0")
    return out


def _flip_sign(buf, off):
    """Negate the big-endian float at `off` by flipping its sign bit -
    exact, and leaves +0.0 alone so symmetric data stays byte-identical."""
    if buf[off] & 0x7F or buf[off + 1] or buf[off + 2] or buf[off + 3]:
        buf[off] ^= 0x80


def split_chunks(data):
    """(form type, [(id, payload bytearray)]) for a whole file."""
    data = bytearray(data)
    if len(data) < 12 or bytes(data[0:4]) != b"FORM":
        raise LwoError("not an IFF FORM file")
    form = bytes(data[8:12])
    if form not in (b"LWO3", b"LWO2"):
        raise LwoError("not an LWO2 / LWO3 object (%r)" % form)
    end = min(len(data), 8 + _u4(data, 4))
    chunks = []
    off = 12
    while off + 8 <= end:
        cid = bytes(data[off:off + 4])
        size = _u4(data, off + 4)
        if off + 8 + size > end:
            raise LwoError("chunk %r at %d runs past the end of the file" % (cid, off))
        chunks.append((cid, data[off + 8:off + 8 + size]))
        off += 8 + size + (size & 1)
    return form, chunks


def join_chunks(form, chunks):
    body = bytearray(form)
    for cid, payload in chunks:
        body += bytearray(cid) + bytearray(struct.pack(">I", len(payload))) + payload
        if len(payload) & 1:
            body += bytearray(b"\0")
    return bytes(bytearray(b"FORM") + bytearray(struct.pack(">I", len(body))) + body)


# --------------------------------------------------
# Chunk mirrors (each edits a copy and returns it)
# --------------------------------------------------


def mirror_pnts(payload):
    out = bytearray(payload)
    if len(out) % 12:
        raise LwoError("PNTS size %d is not a multiple of 12" % len(out))
    for off in range(0, len(out), 12):
        _flip_sign(out, off)
    return out


def mirror_bbox(payload):
    out = bytearray(payload)
    if len(out) != 24:
        return out
    lo = bytes(out[0:4])
    hi = bytes(out[12:16])
    out[0:4] = hi
    out[12:16] = lo
    _flip_sign(out, 0)
    _flip_sign(out, 12)
    return out


def mirror_layr(payload):
    out = bytearray(payload)
    if len(out) >= 16:
        _flip_sign(out, 4)          # U2 number, U2 flags, VEC12 pivot
    return out


def mirror_pols(payload, stats):
    out = bytearray(payload)
    ptype = bytes(out[0:4])
    if ptype not in REVERSE_POLY_TYPES:
        return out
    off = 4
    while off < len(out):
        count = _u2(out, off) & 0x03FF
        off += 2
        spans = []
        for _ in range(count):
            start = off
            _, off = read_vx(out, off)
            spans.append(bytes(out[start:off]))
        if off > len(out):
            raise LwoError("POLS runs past its chunk")
        if count > 2:
            ordered = [spans[0]] + spans[:0:-1]      # v0, vn-1, ..., v1
            out[off - sum(len(s) for s in spans):off] = b"".join(ordered)
            stats["polygons"] += 1
    return out


def _rename(raw, pairs, stats):
    try:
        name = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    other = mirror_math.mirror_name(name, pairs)
    if not other or other == name:
        return raw
    stats["renamed"].append((name, other))
    return other.encode("utf-8")


def mirror_vmap(payload, discontinuous, rename, pairs, stats):
    """VMAP { type, dim, name, (vx point, [vx poly], f4 * dim)* }."""
    buf = bytearray(payload)
    vtype = bytes(buf[0:4])
    dim = _u2(buf, 4)
    raw, data_off = read_s0(buf, 6)
    if vtype in NEGATE_X_VMAPS and dim >= 1:
        off = data_off
        while off < len(buf):
            _, off = read_vx(buf, off)
            if discontinuous:
                _, off = read_vx(buf, off)
            _flip_sign(buf, off)
            off += 4 * dim
        if off != len(buf):
            raise LwoError("%s %r does not divide into records" % (vtype, raw))
        stats["vmaps_negated"] += 1
    if rename and vtype in RENAME_VMAPS:
        new_raw = _rename(raw, pairs, stats)
        if new_raw != raw:
            buf = buf[0:6] + write_s0(new_raw) + buf[data_off:]
    return buf


def _leaf_string(payload):
    """The raw string when `payload` is exactly one S0 (padded to even, or
    not), else None."""
    p = bytes(payload)
    end = p.find(b"\0")
    if end <= 0:
        return None
    if len(p) not in (end + 1, end + 2) or p[end:].strip(b"\0"):
        return None
    return p[:end]


def rename_in_tree(payload, renames, stats):
    """Rename map references inside a FORM's contents (after its type ID).
    Returns the new contents, or None when nothing changed or the contents
    do not walk as IFF (then they are left exactly as they were)."""
    buf = bytearray(payload)
    parts = []
    changed = False
    off = 0
    while off < len(buf):
        if off + 8 > len(buf):
            return None
        cid = bytes(buf[off:off + 4])
        size = _u4(buf, off + 4)
        end = off + 8 + size
        if end > len(buf):
            return None
        body = buf[off + 8:end]
        new_body = None
        if cid == b"FORM" and size >= 4:
            inner = rename_in_tree(body[4:], renames, stats)
            if inner is not None:
                new_body = body[0:4] + inner
        elif cid not in NODE_ID_CHUNKS:
            name = _leaf_string(body)
            if name is not None and name in renames:
                new_body = write_s0(renames[name])
                stats["node_refs"] += 1
        if new_body is not None:
            changed = True
            parts.append((cid, new_body))
        else:
            parts.append((cid, body))
        off = end + (size & 1)
    if not changed:
        return None
    out = bytearray()
    for cid, body in parts:
        out += bytearray(cid) + bytearray(struct.pack(">I", len(body))) + body
        if len(body) & 1:
            out += bytearray(b"\0")
    return out


def _mentions(payload, name):
    """`name` as a whole NUL-terminated string somewhere in `payload`."""
    p = bytes(payload)
    needle = name + b"\0"
    start = 0
    while True:
        i = p.find(needle, start)
        if i < 0:
            return False
        if i == 0 or not (p[i - 1:i].isalnum() or p[i - 1:i] in (b"_", b".", b"-")):
            return True
        start = i + 1


def mirror_bytes(data, rename=True, pairs=None):
    """(mirrored file bytes, stats). stats: points, polygons (reversed),
    vmaps_negated, renamed [(old, new)], node_refs (node-graph references
    renamed), unresolved [names still mentioned outside the maps], layers,
    form."""
    form, chunks = split_chunks(data)
    stats = {"points": 0, "polygons": 0, "vmaps_negated": 0, "renamed": [],
             "node_refs": 0, "unresolved": [], "layers": 0,
             "form": form.decode("ascii")}
    out = []
    for cid, payload in chunks:
        if cid == b"PNTS":
            stats["points"] += len(payload) // 12
            payload = mirror_pnts(payload)
        elif cid == b"POLS":
            payload = mirror_pols(payload, stats)
        elif cid == b"VMAP":
            payload = mirror_vmap(payload, False, rename, pairs, stats)
        elif cid == b"VMAD":
            payload = mirror_vmap(payload, True, rename, pairs, stats)
        elif cid == b"BBOX":
            payload = mirror_bbox(payload)
        elif cid == b"LAYR":
            stats["layers"] += 1
            payload = mirror_layr(payload)
        out.append((cid, payload))
    if stats["renamed"]:
        renames = dict((old.encode("utf-8"), new.encode("utf-8"))
                       for old, new in stats["renamed"])
        for i, (cid, payload) in enumerate(out):
            if cid == b"FORM" and len(payload) >= 4:
                inner = rename_in_tree(payload[4:], renames, stats)
                if inner is not None:
                    out[i] = (cid, payload[0:4] + inner)
        # A name that is also some other map's NEW name (L <-> R swaps) can't
        # be told apart, so only check the rest.
        targets = set(renames.values())
        for old in sorted(renames):
            if old in targets:
                continue
            if any(cid not in (b"VMAP", b"VMAD") and _mentions(payload, old)
                   for cid, payload in out):
                stats["unresolved"].append(old.decode("utf-8", "replace"))
    return join_chunks(form, out), stats


# --------------------------------------------------
# Reading back (tests, symmetry check)
# --------------------------------------------------


def read_layers(data):
    """[{'points': [(x,y,z)], 'polys': [(type, [idx])], 'vmaps':
    [(type, name, discontinuous, [(pnt, poly, values)])], 'pivot', 'bbox'}]"""
    _, chunks = split_chunks(data)
    layers = []
    cur = None
    for cid, buf in chunks:
        if cid == b"LAYR":
            cur = {"points": [], "polys": [], "vmaps": [], "bbox": None,
                   "pivot": struct.unpack(">3f", bytes(buf[4:16]))}
            layers.append(cur)
            continue
        if cur is None:
            continue
        if cid == b"PNTS":
            n = len(buf) // 12
            vals = struct.unpack(">%df" % (3 * n), bytes(buf[:12 * n]))
            cur["points"] = [vals[i:i + 3] for i in range(0, 3 * n, 3)]
        elif cid == b"BBOX":
            cur["bbox"] = struct.unpack(">6f", bytes(buf[:24]))
        elif cid == b"POLS":
            ptype = bytes(buf[0:4])
            off = 4
            while off < len(buf):
                count = _u2(buf, off) & 0x03FF
                off += 2
                idx = []
                for _ in range(count):
                    v, off = read_vx(buf, off)
                    idx.append(v)
                cur["polys"].append((ptype, idx))
        elif cid in (b"VMAP", b"VMAD"):
            vtype = bytes(buf[0:4])
            dim = _u2(buf, 4)
            raw, off = read_s0(buf, 6)
            recs = []
            while off < len(buf):
                pnt, off = read_vx(buf, off)
                pol = None
                if cid == b"VMAD":
                    pol, off = read_vx(buf, off)
                vals = struct.unpack(">%df" % dim, bytes(buf[off:off + 4 * dim]))
                off += 4 * dim
                recs.append((pnt, pol, vals))
            cur["vmaps"].append((vtype, raw.decode("utf-8", "replace"),
                                 cid == b"VMAD", recs))
    return layers


def is_point_symmetric(data, rel_tol=1.0e-5):
    """True when every layer's points are symmetric about its X = 0 plane
    (each point has a partner at (-x, y, z)). Such a mesh looks the same
    mirrored, so its clone can keep the original file."""
    for layer in read_layers(data):
        pts = layer["points"]
        if not pts:
            continue
        extent = max(max(abs(c) for c in p) for p in pts) or 1.0
        q = extent * rel_tol
        cells = set(tuple(int(round(c / q)) for c in p) for p in pts)
        for p in pts:
            key = (int(round(-p[0] / q)), int(round(p[1] / q)), int(round(p[2] / q)))
            if key in cells:
                continue
            hit = False
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        if (key[0] + dx, key[1] + dy, key[2] + dz) in cells:
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    break
            if not hit:
                return False
    return True


def mirror_file(src, dst, rename=True, pairs=None):
    with open(src, "rb") as fh:
        data = fh.read()
    out, stats = mirror_bytes(data, rename, pairs)
    with open(dst, "wb") as fh:
        fh.write(out)
    return stats


def main(argv):
    args = list(argv)
    rename = True
    pairs = None
    if "--keep-names" in args:
        args.remove("--keep-names")
        rename = False
    if "--sides" in args:
        i = args.index("--sides")
        pairs = mirror_math.parse_side_names(args[i + 1])
        del args[i:i + 2]
    if len(args) != 2:
        print(__doc__)
        return 2
    stats = mirror_file(args[0], args[1], rename, pairs)
    print("%s: %d points, %d polygons reversed, %d vmaps mirrored, %d renamed"
          % (stats["form"], stats["points"], stats["polygons"],
             stats["vmaps_negated"], len(stats["renamed"])))
    for old, new in stats["renamed"]:
        print("  %s -> %s" % (old, new))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
