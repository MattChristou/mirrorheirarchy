# -*- coding: utf-8 -*-
"""MirrorHierarchy pure helpers: rotations, the mirror rule, side names.

No lwsdk import - the tests run this outside LightWave. Not a plug-in
container (no LightWave version marker). Keep it Python 2.7-parseable.

Conventions (LightWave, Y up, left-handed):
    R = Ry(H) . Rx(P) . Rz(B)    column vectors
    forward = R.z = (sH cP, -sP, cH cP)
    B = atan2(right.y, up.y)

Mirroring across X: M = diag(-1, 1, 1). If every item's world transform W
becomes M.W.M, every LOCAL transform L also becomes M.L.M - which in
channels is: negate Position.X, Rotation.H, Rotation.B (and the same for
pivot position/rotation and bone rest position/rotation). M.W.M is a plain
rotation (det +1), so no item ever gets a negative scale. The geometry is
mirrored in the object file instead (lwo_mirror), where the polygon winding
can be reversed as well.
"""

import math
import re

TWO_PI = 2.0 * math.pi

# Channels whose values change sign under the mirror rule.
MIRROR_CHANNELS = ("Position.X", "Rotation.H", "Rotation.B")

# LWKEY_SHAPE values (anenvel.html) -> which LWKEY_PARAM_n hold VALUE
# offsets/slopes and so change sign with the key value.
#   1 Hermite, 2 1D Bezier: params 0, 1 = incoming / outgoing slope
#   5 2D Bezier: params 0/1 = in (time, value), 2/3 = out (time, value)
#   0 TCB, 3 linear, 4 stepped: no value params
SHAPE_VALUE_PARAMS = {1: (0, 1), 2: (0, 1), 5: (1, 3)}


def value_params(shape):
    return SHAPE_VALUE_PARAMS.get(int(shape), ())


# --------------------------------------------------
# 3x3 / rigid transforms (lists of rows)
# --------------------------------------------------

IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
MIRROR_X = [[-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def mat_vec(a, v):
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def transpose(a):
    return [[a[j][i] for j in range(3)] for i in range(3)]


def det(a):
    return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
            - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
            + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))


def from_columns(c0, c1, c2):
    return [[c0[i], c1[i], c2[i]] for i in range(3)]


def column(a, j):
    return [a[0][j], a[1][j], a[2][j]]


def _norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0.0 else list(v)


def orthonormal_from_axes(right, up, forward):
    """Rotation whose columns are the item's world axes, cleaned of scale
    and small skew (Gram-Schmidt on forward, then up)."""
    f = _norm(forward)
    u = [up[i] - sum(up[k] * f[k] for k in range(3)) * f[i] for i in range(3)]
    u = _norm(u)
    # Left-handed frame: right = up x forward.
    r = [u[1] * f[2] - u[2] * f[1], u[2] * f[0] - u[0] * f[2],
         u[0] * f[1] - u[1] * f[0]]
    if sum(r[i] * right[i] for i in range(3)) < 0.0:
        r = [-x for x in r]
    return from_columns(r, u, f)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def hpb_to_matrix(h, p, b):
    return mat_mul(rot_y(h), mat_mul(rot_x(p), rot_z(b)))


def matrix_to_hpb(r):
    """(H, P, B) radians of a rotation built as Ry(H).Rx(P).Rz(B)."""
    fwd = column(r, 2)
    sp = max(-1.0, min(1.0, -fwd[1]))
    p = math.asin(sp)
    if abs(math.cos(p)) > 1.0e-7:
        h = math.atan2(fwd[0], fwd[2])
        b = math.atan2(r[1][0], r[1][1])          # right.y, up.y
    else:
        # Gimbal lock: put it all in heading, bank 0.
        b = 0.0
        right = column(r, 0)
        h = math.atan2(-right[2], right[0])
    return h, p, b


def unwrap(angle, ref):
    """`angle` plus whole turns, as close as possible to `ref`."""
    return angle + TWO_PI * round((ref - angle) / TWO_PI)


def unwrap_hpb(hpb, ref):
    """Euler triple closest to `ref`: also tries the equivalent
    (H+pi, pi-P, B+pi) form, which stays continuous through P = 90."""
    a = [unwrap(hpb[i], ref[i]) for i in range(3)]
    alt = (hpb[0] + math.pi, math.pi - hpb[1], hpb[2] + math.pi)
    b = [unwrap(alt[i], ref[i]) for i in range(3)]
    da = sum(abs(a[i] - ref[i]) for i in range(3))
    db = sum(abs(b[i] - ref[i]) for i in range(3))
    return a if da <= db else b


class Xform(object):
    """Rigid transform x -> rot.x + pos. `rot` may be a reflection."""

    def __init__(self, rot=None, pos=None):
        self.rot = [list(r) for r in (rot or IDENTITY)]
        self.pos = list(pos or (0.0, 0.0, 0.0))

    def __mul__(self, other):
        return Xform(mat_mul(self.rot, other.rot),
                     [a + b for a, b in zip(mat_vec(self.rot, other.pos), self.pos)])

    def inverse(self):
        rt = transpose(self.rot)        # orthogonal (rotation or reflection)
        return Xform(rt, [-x for x in mat_vec(rt, self.pos)])

    def apply(self, v):
        return [a + b for a, b in zip(mat_vec(self.rot, v), self.pos)]


MIRROR = Xform(MIRROR_X)


def mirror_about(frame):
    """Reflection across the YZ plane of `frame` (an Xform)."""
    return frame * MIRROR * frame.inverse()


def is_plain_mirror(a, tol=1.0e-5, scale=1.0):
    """True when `a` is the X mirror M itself: the clone's parent sits
    exactly where the mirror puts the original's parent, so the plain
    channel rule (negate X, H, B) is exact - for every key, with no
    sampling."""
    for i in range(3):
        for j in range(3):
            if abs(a.rot[i][j] - MIRROR_X[i][j]) > tol:
                return False
    return all(abs(x) <= tol * max(1.0, scale) for x in a.pos)


def mirror_local(a, pos, hpb):
    """New local (pos, hpb) for L' = A.L.M, with L = (R(hpb), pos).
    A must be a reflection (det -1) so the result is a proper rotation."""
    r = mat_mul(a.rot, mat_mul(hpb_to_matrix(*hpb), MIRROR_X))
    new_pos = a.apply(pos)
    return new_pos, matrix_to_hpb(r)


def mirror_channel_rule(pos, hpb):
    return [-pos[0], pos[1], pos[2]], [-hpb[0], hpb[1], -hpb[2]]


# --------------------------------------------------
# Left / right names (same rules as AnimTweaks' Mirror Pose)
# --------------------------------------------------

_SIDE_WORDS = {"left": "right", "right": "left"}
_SIDE_LETTERS = [("L", "R"), ("l", "r")]


def parse_side_names(text):
    """[(left, right)] from a Sides field: pairs split by commas or spaces,
    each written a/b or a:b. Anything else is ignored."""
    pairs = []
    for piece in re.split(r"[,\s]+", text or ""):
        parts = re.split(r"[/:]", piece)
        if len(parts) == 2 and parts[0] and parts[1] and parts[0] != parts[1]:
            pairs.append((parts[0], parts[1]))
    return pairs


def _swap_side_token(name, pairs):
    """Swap the first side token in `name`: a whole word set off by _ . -
    or a space (or the ends of the name), maybe followed by digits - L_Arm,
    Arm.l, Arm_L_Upper, arm_L0_fk0. Case-sensitive. None if none."""
    swap = {}
    for a, b in pairs:
        swap.setdefault(a, b)
        swap.setdefault(b, a)
    if not swap:
        return None
    words = "|".join(re.escape(w) for w in sorted(swap, key=len, reverse=True))
    m = re.search(r"(?:^|(?<=[_.\- ]))(%s)(?=\d*(?:[_.\- ]|$))" % words, name)
    if not m:
        return None
    return name[:m.start(1)] + swap[m.group(1)] + name[m.end(1):]


def _match_case(word, like):
    if like.isupper():
        return word.upper()
    if like[0].isupper():
        return word.capitalize()
    return word


def mirror_name(name, pairs=None):
    """The other side's name, or None when `name` has no side in it.
    Tries `pairs` first, then Left/Right anywhere in the name, then L or R
    as a word of its own (L_Arm, Arm_L, Arm.l, Arm_L_Upper)."""
    if not name:
        return None
    other = _swap_side_token(name, pairs or [])
    if other is not None:
        return other
    m = re.search(r"(?i)left|right", name)
    if m:
        word = m.group(0)
        return (name[:m.start()] + _match_case(_SIDE_WORDS[word.lower()], word)
                + name[m.end():])
    return _swap_side_token(name, _SIDE_LETTERS)


_CLONE_SUFFIX = re.compile(r"\s*\(\d+\)$")


def base_item_name(name):
    """Item name without Layout's clone counter: 'Arm (2)' -> 'Arm'."""
    return _CLONE_SUFFIX.sub("", name or "")


def mirrored_file_candidates(path, pairs=None):
    """Where a mirrored copy of object file `path` may go, best first:
    the other side's name (L_Hand.lwo -> R_Hand.lwo), then
    <name>_mirror.lwo, <name>_mirror2.lwo, ... Never `path` itself."""
    import os
    folder, leaf = os.path.split(path)
    stem, ext = os.path.splitext(leaf)
    ext = ext or ".lwo"
    other = mirror_name(stem, pairs)
    if other and other != stem:
        yield os.path.join(folder, other + ext)
    n = 1
    while True:
        yield os.path.join(folder, "%s_mirror%s%s" % (stem, "" if n == 1 else n, ext))
        n += 1
