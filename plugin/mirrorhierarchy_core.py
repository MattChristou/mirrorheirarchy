# -*- coding: utf-8 -*-
"""MirrorHierarchy core: clone a hierarchy and mirror it across X without
any negative scale.

How (see mirror_math for the maths):
  1. Clone every item of each selected hierarchy, rebuild the parenting
     with Parent In Place OFF, so every clone keeps its local values.
  2. Mesh objects: write a mirrored copy of the object file (points negated
     in X, polygon winding reversed - lwo_mirror) and ReplaceWithObject.
  3. Every clone: negate Position.X, Rotation.H, Rotation.B on every key
     (tangents too), pivot position X, pivot rotation H/B, bone rest
     position X and rest rotation H/B. That is the local form of the world
     mirror M.W.M - a plain rotation, so no negative scale anywhere.
  4. The top item of each hierarchy: if its new parent is not simply the
     mirror image of its old parent, solve its keys in world space.
  5. Re-point IK goals / targets / poles / Same-As-Item links at the clones
     (or at the other side's item by name), rename L <-> R, swap bone
     weight map names, then check every clone's world position and axes
     against the expected mirror image.

NOT a plug-in container: no LightWave version marker, no server record.
Keep it Python 2.7-parseable.
"""

import json
import math
import os

import lwsdk

import lwo_mirror
import mirror_math as mm

__author__ = "Matthew Christou"
__version__ = "0.1.0"

PLUGIN = "MirrorHierarchy"

PLANE_WORLD, PLANE_TOP, PLANE_PARENT = 0, 1, 2
PLANE_LABELS = ["World (X = 0)", "Top of hierarchy", "Parent of selection"]

PARENT_OTHER_SIDE, PARENT_SAME, PARENT_NONE = 0, 1, 2
PARENT_LABELS = ["Other side of the original's parent", "The original's parent",
                 "Nothing"]

MESH_MIRRORED, MESH_KEEP = 0, 1
MESH_LABELS = ["Write a mirrored copy", "Keep the original mesh"]

SETTINGS = {
    "plane": PLANE_WORLD,
    "parent": PARENT_OTHER_SIDE,
    "rename": 1,
    "sides": "",
    "mesh": MESH_MIRRORED,
    "reuse_symmetric": 1,
}

POSITION_CHANNELS = ("Position.X", "Position.Y", "Position.Z")
ROTATION_CHANNELS = ("Rotation.H", "Rotation.P", "Rotation.B")

# World-check tolerances: position relative to the hierarchy's size,
# axes as a dot-product shortfall (1e-4 ~ 0.8 degrees).
POS_TOL = 1.0e-4
AXIS_TOL = 1.0e-4


# --------------------------------------------------
# Logging / preferences
# --------------------------------------------------


def log_exception(where):
    try:
        import time
        import traceback
        text = traceback.format_exc()
        print("%s: %s failed\n%s" % (PLUGIN, where, text))
        path = os.path.join(os.environ.get("TEMP", "."), PLUGIN + "_error.log")
        with open(path, "a") as fh:
            fh.write("%s  %s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), where, text))
    except Exception:
        pass


def _prefs_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, PLUGIN, "prefs.json")


def load_prefs():
    try:
        with open(_prefs_path(), "r") as fh:
            saved = json.load(fh)
        for k in SETTINGS:
            if k in saved and type(saved[k]) is type(SETTINGS[k]):
                SETTINGS[k] = saved[k]
    except Exception:
        pass


def save_prefs():
    try:
        path = _prefs_path()
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            json.dump(SETTINGS, fh, indent=1, sort_keys=True)
    except Exception:
        log_exception("save_prefs")


# --------------------------------------------------
# Small Layout helpers
# --------------------------------------------------


def cmd(text):
    return lwsdk.command(text)


def key(item):
    return lwsdk.itemid_to_str(item) if item else None


def select(item):
    cmd("SelectItem " + key(item))


def _f(v):
    return "%.9g" % v


def vec3(value):
    """param()/restParam() results as 3 floats, whatever the wrapper hands
    back: a vector, or (ok, vector) on some builds."""
    if value is None:
        return None
    nums = list(value) if not isinstance(value, (int, float)) else [value]
    if len(nums) == 2 and not isinstance(nums[0], float):
        nums = list(nums[1])
    if len(nums) < 3:
        return None
    return [float(v) for v in nums[:3]]


def _unwrap(value):
    return value[-1] if isinstance(value, tuple) else value


def all_items(ii):
    """Every object, light, camera and bone in the scene."""
    out = []
    for item_type in (lwsdk.LWI_OBJECT, lwsdk.LWI_LIGHT, lwsdk.LWI_CAMERA):
        item = ii.first(item_type, None)
        while item:
            out.append(item)
            item = ii.next(item)
    obj = ii.first(lwsdk.LWI_OBJECT, None)
    while obj:
        bone = ii.first(lwsdk.LWI_BONE, obj)
        while bone:
            out.append(bone)
            bone = ii.next(bone)
        obj = ii.next(obj)
    return out


def children(ii, item):
    """Child items, plus (for an object) its bones parented straight to it,
    in case the child list leaves bones out."""
    out = []
    seen = set()
    child = ii.firstChild(item)
    while child:
        out.append(child)
        seen.add(key(child))
        child = ii.nextChild(item, child)
    if ii.type(item) in (lwsdk.LWI_OBJECT, lwsdk.LWI_BONE):
        obj = item if ii.type(item) == lwsdk.LWI_OBJECT else owner_object(ii, item)
        bone = ii.first(lwsdk.LWI_BONE, obj) if obj else None
        while bone:
            if key(ii.parent(bone)) == key(item) and key(bone) not in seen:
                out.append(bone)
                seen.add(key(bone))
            bone = ii.next(bone)
    return out


def owner_object(ii, item):
    """The object a bone belongs to (walk up past parent bones)."""
    cur = ii.parent(item)
    while cur and ii.type(cur) == lwsdk.LWI_BONE:
        cur = ii.parent(cur)
    return cur


def item_envelopes(item):
    ii = lwsdk.LWItemInfo()
    ci = lwsdk.LWChannelInfo()
    group = ii.chanGroup(item)
    found = {}
    if not group:
        return found
    chan = ci.nextChannel(group, None)
    while chan:
        env = ci.channelEnvelope(chan)
        if env:
            found[ci.channelName(chan)] = env
        chan = ci.nextChannel(group, chan)
    return found


def key_get(ef, env, k, tag):
    return _unwrap(ef.keyGet(env, k, tag))


def env_keys(ef, env):
    out = []
    k = ef.nextKey(env, None)
    while k:
        out.append(k)
        k = ef.nextKey(env, k)
    return out


def negate_envelope(ef, env):
    """Every key's value and its value-tangents change sign: the curve
    becomes its exact negative, shape for shape."""
    for k in env_keys(ef, env):
        ef.keySet(env, k, lwsdk.LWKEY_VALUE, -float(key_get(ef, env, k, lwsdk.LWKEY_VALUE)))
        try:
            shape = int(key_get(ef, env, k, lwsdk.LWKEY_SHAPE))
        except Exception:
            shape = 0
        for n in mm.value_params(shape):
            tag = getattr(lwsdk, "LWKEY_PARAM_%d" % n)
            ef.keySet(env, k, tag, -float(key_get(ef, env, k, tag)))


def set_value_at(ef, env, when, value, tol):
    for k in env_keys(ef, env):
        if abs(float(key_get(ef, env, k, lwsdk.LWKEY_TIME)) - when) <= tol:
            ef.keySet(env, k, lwsdk.LWKEY_VALUE, float(value))
            return
    ef.createKey(env, when, float(value))


def world_frame(ii, item, when):
    """Item's world frame as an Xform (rotation cleaned of scale)."""
    if not item:
        return mm.Xform()
    r = vec3(ii.param(item, lwsdk.LWIP_RIGHT, when))
    u = vec3(ii.param(item, lwsdk.LWIP_UP, when))
    f = vec3(ii.param(item, lwsdk.LWIP_FORWARD, when))
    p = vec3(ii.param(item, lwsdk.LWIP_W_POSITION, when))
    return mm.Xform(mm.orthonormal_from_axes(r, u, f), p)


def world_axes(ii, item, when):
    return (vec3(ii.param(item, lwsdk.LWIP_W_POSITION, when)),
            [vec3(ii.param(item, tag, when))
             for tag in (lwsdk.LWIP_RIGHT, lwsdk.LWIP_UP, lwsdk.LWIP_FORWARD)])


# Which number scale a Layout angle command takes (radians or degrees) is
# not documented per command, so the first use is checked by reading the
# value back. Remembered for the session.
ANGLE_SCALE = {}


def set_vector_verified(command, values, readback, angles=False):
    """Send `command x y z` (values in radians for angles) and confirm with
    readback(). Returns True (confirmed), False (did not take), or None
    (no readback available)."""
    scales = [1.0]
    if angles:
        known = ANGLE_SCALE.get(command)
        scales = [known] if known else [1.0, 180.0 / math.pi]
    for scale in scales:
        cmd("%s %s" % (command, " ".join(_f(v * scale) for v in values)))
        try:
            got = vec3(readback())
        except Exception:
            got = None
        if got is None:
            return None
        if all(abs(g - w) <= 1.0e-4 * max(1.0, abs(w)) for g, w in zip(got, values)):
            if angles and command not in ANGLE_SCALE:
                ANGLE_SCALE[command] = scale
                print("%s: %s takes %s" % (PLUGIN, command,
                                           "radians" if scale == 1.0 else "degrees"))
            return True
    return False


# --------------------------------------------------
# Result report
# --------------------------------------------------


class Report(object):

    def __init__(self):
        self.lines = []
        self.warnings = []
        self.created = []

    def note(self, text):
        self.lines.append(text)
        print("%s: %s" % (PLUGIN, text))

    def warn(self, text):
        self.warnings.append(text)
        print("%s: WARNING %s" % (PLUGIN, text))

    def summary(self):
        head = "Mirrored %d item(s)." % len(self.created)
        if self.warnings:
            head += " %d warning(s) - see the Python console." % len(self.warnings)
        return head


# --------------------------------------------------
# The run
# --------------------------------------------------


def gather_roots(ii, selected):
    """Selected items with no selected ancestor."""
    picked = set(key(i) for i in selected)
    roots = []
    for item in selected:
        cur = ii.parent(item)
        while cur and key(cur) not in picked:
            cur = ii.parent(cur)
        if not cur:
            roots.append(item)
    return roots


def subtree(ii, root):
    """[(item, parent item)] preorder, read before anything is cloned."""
    out = []
    stack = [(root, None)]
    while stack:
        item, parent = stack.pop()
        out.append((item, parent))
        kids = children(ii, item)
        for kid in reversed(kids):
            stack.append((kid, item))
    return out


def find_by_name(ii, name, like):
    """An existing item named `name`, of the same type as `like` (and the
    same object, for bones)."""
    if not name:
        return None
    want_type = ii.type(like)
    want_owner = key(owner_object(ii, like)) if want_type == lwsdk.LWI_BONE else None
    for item in all_items(ii):
        if ii.type(item) != want_type or ii.name(item) != name:
            continue
        if want_type == lwsdk.LWI_BONE and key(owner_object(ii, item)) != want_owner:
            continue
        return item
    return None


def clone_one(ii, item):
    """Clone `item`. Returns (clone, other new items) - Layout clones an
    object's bones with it."""
    before = set(key(i) for i in all_items(ii))
    select(item)
    cmd("Clone 1")
    ii = lwsdk.LWItemInfo()
    new_items = [i for i in all_items(ii) if key(i) not in before]
    chosen = None
    for sel in lwsdk.LWInterfaceInfo().selected_items():
        if key(sel) in set(key(i) for i in new_items):
            chosen = sel
            break
    if chosen is None:
        same = [i for i in new_items if ii.type(i) == ii.type(item)
                and mm.base_item_name(ii.name(i)) == mm.base_item_name(ii.name(item))]
        chosen = same[0] if same else None
    if chosen is None:
        raise RuntimeError("Clone made no copy of %s" % ii.name(item))
    return chosen, [i for i in new_items if key(i) != key(chosen)]


def _path_below(ii, item, top):
    """Base names from just below `top` down to `item`, plus the type."""
    names = []
    cur = item
    while cur and key(cur) != key(top):
        names.append(mm.base_item_name(ii.name(cur)))
        cur = ii.parent(cur)
    if not cur:
        return None
    return (ii.type(item), tuple(reversed(names)))


def match_extras(ii, item, clone, extras, nodes, mapping):
    """Pair items Layout cloned along with `item` (an object's bones) with
    the originals, by type and name path under the object."""
    want = {}
    for node, _ in nodes:
        path = _path_below(ii, node, item)
        if path is not None and key(node) != key(item):
            want.setdefault(path, []).append(node)
    leftovers = []
    for extra in extras:
        path = _path_below(ii, extra, clone)
        group = want.get(path) if path else None
        if group:
            mapping[key(group.pop(0))] = extra
        else:
            leftovers.append(extra)
    return leftovers


class Mirror(object):

    def __init__(self, settings, report):
        self.s = settings
        self.report = report
        self.pairs = mm.parse_side_names(settings.get("sides", ""))
        self.ef = lwsdk.LWEnvelopeFuncs()
        self.when = lwsdk.LWInterfaceInfo().curTime
        fps = lwsdk.LWSceneInfo().framesPerSecond or 30.0
        self.tol = 0.5 / float(fps)
        self.mesh_cache = {}

    # ---------- planning ----------

    def plane_item(self, ii, root):
        plane = self.s["plane"]
        if plane == PLANE_PARENT:
            return ii.parent(root)
        if plane == PLANE_TOP:
            top = root
            while ii.parent(top):
                top = ii.parent(top)
            return top
        return None

    def new_parent(self, ii, root):
        parent = ii.parent(root)
        choice = self.s["parent"]
        if choice == PARENT_NONE:
            if ii.type(root) == lwsdk.LWI_BONE:
                return owner_object(ii, root)
            return None
        if choice == PARENT_OTHER_SIDE and parent:
            other = mm.mirror_name(ii.name(parent), self.pairs)
            found = find_by_name(ii, other, parent) if other else None
            if found:
                return found
        return parent

    # ---------- one hierarchy ----------

    def run_root(self, root):
        ii = lwsdk.LWItemInfo()
        nodes = subtree(ii, root)
        orig_parent = ii.parent(root)
        new_parent = self.new_parent(ii, root)
        plane_item = self.plane_item(ii, root)

        mw = mm.mirror_about(world_frame(ii, plane_item, self.when)) if plane_item else mm.MIRROR
        before = dict((key(n), world_axes(ii, n, self.when)) for n, _ in nodes)

        mapping = self.clone_all(nodes)
        ii = lwsdk.LWItemInfo()
        root_clone = mapping[key(root)]

        # Parent the top clone.
        select(root_clone)
        if new_parent:
            cmd("ParentItem " + key(new_parent))
        else:
            cmd("ParentItem")

        a = (world_frame(ii, new_parent, self.when).inverse() * mw
             * world_frame(ii, orig_parent, self.when))
        scale = max([1.0] + [abs(c) for n, _ in nodes for c in before[key(n)][0]])
        plain_root = mm.is_plain_mirror(a, scale=scale)

        for node, _ in nodes:
            clone = mapping.get(key(node))
            if clone is None:
                continue
            if ii.type(node) == lwsdk.LWI_OBJECT and self.s["mesh"] == MESH_MIRRORED:
                self.mirror_mesh(node, clone)
            if key(node) == key(root) and not plain_root:
                self.solve_root(clone, orig_parent, new_parent, plane_item)
            else:
                self.mirror_channels(clone)
            self.mirror_pivot(node, clone)
            if ii.type(node) == lwsdk.LWI_BONE:
                self.mirror_bone(node, clone)

        self.fix_references(nodes, mapping)
        self.rename(nodes, mapping)
        cmd("RefreshNow")
        self.check_world(nodes, mapping, before, mw, scale)
        self.report.created.append(root_clone)
        return root_clone

    def clone_all(self, nodes):
        ii = lwsdk.LWItemInfo()
        mapping = {}
        for node, parent in nodes:
            if key(node) in mapping:
                continue
            clone, extras = clone_one(ii, node)
            ii = lwsdk.LWItemInfo()
            mapping[key(node)] = clone
            leftovers = match_extras(ii, node, clone, extras, nodes, mapping)
            for extra in leftovers:
                self.report.warn("Clone of %s also made %s, which matched nothing - left as is."
                                 % (ii.name(node), ii.name(extra)))
            if parent is not None:
                select(clone)
                cmd("ParentItem " + key(mapping[key(parent)]))
        return mapping

    # ---------- per item ----------

    def mirror_channels(self, clone):
        envs = item_envelopes(clone)
        for name in mm.MIRROR_CHANNELS:
            env = envs.get(name)
            if env:
                negate_envelope(self.ef, env)

    def solve_root(self, clone, orig_parent, new_parent, plane_item):
        """The top clone's new parent is not the mirror image of its old one,
        so solve L' = A.L.M at each key time (union over position and
        rotation). Other times follow the keys' own interpolation."""
        ii = lwsdk.LWItemInfo()
        envs = item_envelopes(clone)
        names = POSITION_CHANNELS + ROTATION_CHANNELS
        if any(n not in envs for n in names):
            self.report.warn("%s: missing motion channels - used the plain rule."
                             % ii.name(clone))
            self.mirror_channels(clone)
            return
        times = set()
        for n in names:
            for k in env_keys(self.ef, envs[n]):
                times.add(round(float(key_get(self.ef, envs[n], k, lwsdk.LWKEY_TIME)), 6))
        times = sorted(times) or [self.when]
        writes = []
        prev = None
        for t in times:
            pos = [self.ef.evaluate(envs[n], t) for n in POSITION_CHANNELS]
            hpb = [self.ef.evaluate(envs[n], t) for n in ROTATION_CHANNELS]
            mw = (mm.mirror_about(world_frame(ii, plane_item, t)) if plane_item
                  else mm.MIRROR)
            a = world_frame(ii, new_parent, t).inverse() * mw * world_frame(ii, orig_parent, t)
            npos, nhpb = mm.mirror_local(a, pos, hpb)
            ref = prev if prev is not None else mm.mirror_channel_rule(pos, hpb)[1]
            nhpb = mm.unwrap_hpb(nhpb, ref)
            prev = nhpb
            writes.append((t, list(npos) + list(nhpb)))
        for t, values in writes:
            for n, v in zip(names, values):
                set_value_at(self.ef, envs[n], t, v, self.tol)
        self.report.note("%s: top item solved in world space at %d key time(s)."
                         % (ii.name(clone), len(writes)))

    def mirror_pivot(self, node, clone):
        """Pivot from the ORIGINAL, set on the clone: ReplaceWithObject may
        already have given the clone the mirrored file's layer pivot."""
        ii = lwsdk.LWItemInfo()
        piv = vec3(ii.param(node, lwsdk.LWIP_PIVOT, self.when))
        now = vec3(ii.param(clone, lwsdk.LWIP_PIVOT, self.when))
        if piv and now and any(abs(a - b) > 1.0e-9 for a, b in zip(now, (-piv[0], piv[1], piv[2]))):
            select(clone)
            want = [-piv[0], piv[1], piv[2]]
            ok = set_vector_verified("PivotPosition", want,
                                     lambda: lwsdk.LWItemInfo().param(clone, lwsdk.LWIP_PIVOT, self.when))
            if ok is False:
                self.report.warn("%s: pivot position did not take." % ii.name(clone))
        prot = vec3(ii.param(node, lwsdk.LWIP_PIVOT_ROT, self.when))
        if prot and (abs(prot[0]) > 0.0 or abs(prot[2]) > 0.0):
            select(clone)
            want = [-prot[0], prot[1], -prot[2]]
            ok = set_vector_verified("PivotRotation", want,
                                     lambda: lwsdk.LWItemInfo().param(clone, lwsdk.LWIP_PIVOT_ROT, self.when),
                                     angles=True)
            if ok is False:
                self.report.warn("%s: pivot rotation did not take." % ii.name(clone))

    def mirror_bone(self, node, clone):
        ii = lwsdk.LWItemInfo()
        bi = lwsdk.LWBoneInfo()
        name = ii.name(clone)
        pos = vec3(bi.restParam(node, lwsdk.LWIP_POSITION))
        rot = vec3(bi.restParam(node, lwsdk.LWIP_ROTATION))
        select(clone)
        if pos and abs(pos[0]) > 0.0:
            ok = set_vector_verified("BoneRestPosition", [-pos[0], pos[1], pos[2]],
                                     lambda: lwsdk.LWBoneInfo().restParam(clone, lwsdk.LWIP_POSITION))
            if ok is False:
                self.report.warn("%s: rest position did not take." % name)
        if rot and (abs(rot[0]) > 0.0 or abs(rot[2]) > 0.0):
            ok = set_vector_verified("BoneRestRotation", [-rot[0], rot[1], -rot[2]],
                                     lambda: lwsdk.LWBoneInfo().restParam(clone, lwsdk.LWIP_ROTATION),
                                     angles=True)
            if ok is False:
                self.report.warn("%s: rest rotation did not take." % name)
        if self.s["rename"]:
            wmap = bi.weightMap(node)
            other = mm.mirror_name(wmap, self.pairs) if wmap else None
            if other and other != wmap:
                cmd("BoneWeightMapName " + other)

    def mirror_mesh(self, node, clone):
        oi = lwsdk.LWObjectInfo()
        ii = lwsdk.LWItemInfo()
        if not oi.numPoints(node):
            return                                      # a null
        path = oi.filename(node)
        label = ii.name(node)
        if not path or not os.path.isfile(path):
            self.report.warn("%s has no saved object file - save it first. Its clone "
                             "keeps the original mesh (not mirrored)." % label)
            return
        if path not in self.mesh_cache:
            self.mesh_cache[path] = self.write_mirrored(path, label)
        new_path, layers = self.mesh_cache[path]
        if not new_path:
            return
        select(clone)
        want_points = oi.numPoints(node)
        if layers <= 1:
            cmd("ReplaceWithObject " + new_path)
        else:
            layer = int(oi.layerLoaded(node) or 1)
            for n in (layer, layer + 1):
                cmd("ReplaceObjectLayer %d %s" % (n, new_path))
                if lwsdk.LWObjectInfo().numPoints(clone) == want_points:
                    break
        oi = lwsdk.LWObjectInfo()
        got = oi.filename(clone) or ""
        if os.path.normcase(os.path.abspath(got)) != os.path.normcase(os.path.abspath(new_path)):
            self.report.warn("%s: ReplaceWithObject did not take (clone still uses %s)."
                             % (label, got or "no file"))
        elif oi.numPoints(clone) != want_points:
            self.report.warn("%s: mirrored clone has %d points, the original %d - "
                             "wrong layer?" % (label, oi.numPoints(clone), want_points))

    def write_mirrored(self, path, label):
        """(mirrored file path or None to keep the original, layer count)."""
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            out, stats = lwo_mirror.mirror_bytes(data, bool(self.s["rename"]), self.pairs)
        except lwo_mirror.LwoError as exc:
            self.report.warn("%s: cannot read %s (%s) - mesh not mirrored." % (label, path, exc))
            return None, 0
        if (self.s["reuse_symmetric"] and not stats["renamed"]
                and lwo_mirror.is_point_symmetric(data)):
            self.report.note("%s is symmetric - the clone keeps %s." % (label, os.path.basename(path)))
            return None, stats["layers"]
        for n, cand in enumerate(mm.mirrored_file_candidates(path, self.pairs)):
            if n > 200:
                break
            if os.path.exists(cand):
                with open(cand, "rb") as fh:
                    if fh.read() != out:
                        continue                     # someone else's file: keep it
            else:
                with open(cand, "wb") as fh:
                    fh.write(out)
            self.report.note("%s -> %s (%d polygons reversed%s)." % (
                os.path.basename(path), os.path.basename(cand), stats["polygons"],
                ", %d map(s) renamed" % len(stats["renamed"]) if stats["renamed"] else ""))
            return cand, stats["layers"]
        self.report.warn("%s: no free file name for the mirrored copy." % label)
        return None, stats["layers"]

    def fix_references(self, nodes, mapping):
        ii = lwsdk.LWItemInfo()
        links = [("GoalItem", lambda n: ii.goal(n)),
                 ("TargetItem", lambda n: ii.target(n)),
                 ("PoleItem", lambda n: ii.pole(n)),
                 ("PositionItem", lambda n: ii.sameItem(n, lwsdk.LWIP_POSITION)),
                 ("RotationItem", lambda n: ii.sameItem(n, lwsdk.LWIP_ROTATION)),
                 ("ScaleItem", lambda n: ii.sameItem(n, lwsdk.LWIP_SCALING))]
        for node, _ in nodes:
            clone = mapping.get(key(node))
            if clone is None:
                continue
            for command, getter in links:
                try:
                    ref = getter(node)
                except Exception:
                    ref = None
                if not ref:
                    continue
                target = mapping.get(key(ref))
                if target is None:
                    other = mm.mirror_name(ii.name(ref), self.pairs)
                    target = find_by_name(ii, other, ref) if other else None
                if target is not None:
                    select(clone)
                    cmd("%s %s" % (command, key(target)))
                elif mm.mirror_name(ii.name(ref), self.pairs):
                    self.report.warn("%s: %s still points at %s (no other-side item found)."
                                     % (ii.name(clone), command, ii.name(ref)))

    def rename(self, nodes, mapping):
        if not self.s["rename"]:
            return
        ii = lwsdk.LWItemInfo()
        oi = lwsdk.LWObjectInfo()
        for node, _ in nodes:
            clone = mapping.get(key(node))
            if clone is None:
                continue
            if ii.type(node) == lwsdk.LWI_OBJECT and oi.numPoints(clone):
                continue     # mesh objects take their name from the file; nulls rename
            other = mm.mirror_name(ii.name(node), self.pairs)
            if other:
                select(clone)
                cmd("Rename " + other)

    def check_world(self, nodes, mapping, before, mw, scale):
        """Each clone's world position and axes against the mirror image of
        the original's: pos' = Mw.pos, right' = -Mw.right, up' = Mw.up,
        forward' = Mw.forward. IK, expressions and modifiers can move an
        item away from that legitimately; the report names them."""
        ii = lwsdk.LWItemInfo()
        bad = []
        worst = 0.0
        for node, _ in nodes:
            clone = mapping.get(key(node))
            if clone is None:
                continue
            pos, axes = before[key(node)]
            gpos, gaxes = world_axes(ii, clone, self.when)
            if pos is None or gpos is None or None in axes or None in gaxes:
                continue
            want_pos = mw.apply(pos)
            want_axes = [[-c for c in mm.mat_vec(mw.rot, axes[0])],
                         mm.mat_vec(mw.rot, axes[1]), mm.mat_vec(mw.rot, axes[2])]
            perr = math.sqrt(sum((g - w) ** 2 for g, w in zip(gpos, want_pos))) / scale
            aerr = max(1.0 - sum(g * w for g, w in zip(mm._norm(ga), mm._norm(wa)))
                       for ga, wa in zip(gaxes, want_axes))
            worst = max(worst, perr, aerr)
            if perr > POS_TOL or aerr > AXIS_TOL:
                bad.append("%s (position %.2g, axes %.2g)" % (ii.name(clone), perr, aerr))
        if bad:
            self.report.warn("%d clone(s) are not the exact mirror image at this frame "
                             "(IK / expressions / modifiers can cause that): %s"
                             % (len(bad), ", ".join(bad)))
        else:
            self.report.note("World check passed for %d clone(s) (worst %.1g)."
                             % (len(mapping), worst))


def run(settings=None):
    """Mirror the selected hierarchies. Returns the Report."""
    settings = settings or SETTINGS
    report = Report()
    ii = lwsdk.LWItemInfo()
    selected = list(lwsdk.LWInterfaceInfo().selected_items())
    if not selected:
        report.warn("Select the top item(s) of the hierarchies to mirror.")
        return report
    roots = gather_roots(ii, selected)
    flags = lwsdk.LWInterfaceInfo().generalFlags
    pip_was_on = bool(flags & lwsdk.LWGENF_PARENTINPLACE)
    cmd("ParentInPlace 0")
    mirror = Mirror(settings, report)
    try:
        for root in roots:
            try:
                mirror.run_root(root)
            except Exception as exc:
                log_exception("run_root")
                report.warn("%s: stopped - %s (details in %%TEMP%%\\%s_error.log)"
                            % (lwsdk.LWItemInfo().name(root), exc, PLUGIN))
    finally:
        cmd("ParentInPlace %d" % (1 if pip_was_on else 0))
    if report.created:
        select(report.created[0])
        for item in report.created[1:]:
            cmd("AddToSelection " + key(item))
    print("%s: %s" % (PLUGIN, report.summary()))
    return report
