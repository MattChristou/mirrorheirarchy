# -*- coding: utf-8 -*-
"""MirrorHierarchy core: mirror a hierarchy across X without any negative
scale - either as new clones, or onto the existing other side.

How (see mirror_math for the maths):
  Create mode
    1. Clone every item of each selected hierarchy, rebuild the parenting
       with Parent In Place OFF, so every clone keeps its local values.
    2. Mesh objects: write a mirrored copy of the object file (points
       negated in X, polygon winding reversed, node-graph map names
       swapped - lwo_mirror) and ReplaceWithObject.
  Update mode
    1. Find the existing other side by name (R_Arm for L_Arm), then its
       children by name under it.
    2. Copy the original's motion keys onto it; refresh its mesh file only
       if this plug-in wrote that file and nobody has edited it since.
  Both
    3. Negate Position.X, Rotation.H, Rotation.B on every key (tangents
       too); pivot position X, pivot rotation H/B, bone rest position X and
       rest rotation H/B from the original. That is the local form of the
       world mirror M.W.M - a plain rotation, so no negative scale.
    4. The top item: if its parent is not simply the mirror image of the
       original's parent, solve its keys in world space.
    5. Re-point IK goals / targets / poles / Same-As-Item links, swap bone
       weight map names, then check every result's world position and axes
       against the expected mirror image.

NOT a plug-in container: no LightWave version marker, no server record.
Keep it Python 2.7-parseable.
"""

import hashlib
import json
import math
import os

import lwsdk

import lwo_mirror
import mirror_math as mm

__author__ = "Matthew Christou"
__version__ = "0.2.0"

PLUGIN = "MirrorHierarchy"

MODE_CREATE, MODE_UPDATE = 0, 1
MODE_LABELS = ["Create mirrored clones", "Update the existing other side"]

PLANE_WORLD, PLANE_TOP, PLANE_PARENT = 0, 1, 2
PLANE_LABELS = ["World (YZ plane)", "Top of hierarchy", "Parent of selection"]

PARENT_OTHER_SIDE, PARENT_SAME, PARENT_NONE = 0, 1, 2
PARENT_LABELS = ["Other side of the original's parent", "The original's parent",
                 "Nothing"]

MESH_MIRRORED, MESH_KEEP = 0, 1
MESH_LABELS = ["Write a mirrored copy", "Keep the original mesh"]

SETTINGS = {
    "mode": MODE_CREATE,
    "plane": PLANE_WORLD,
    "parent": PARENT_OTHER_SIDE,
    "rename": 1,
    "sides": "",
    "mesh": MESH_MIRRORED,
    "reuse_symmetric": 1,
}

POSITION_CHANNELS = ("Position.X", "Position.Y", "Position.Z")
ROTATION_CHANNELS = ("Rotation.H", "Rotation.P", "Rotation.B")
SCALE_CHANNELS = ("Scale.X", "Scale.Y", "Scale.Z")
MOTION_CHANNELS = POSITION_CHANNELS + ROTATION_CHANNELS + SCALE_CHANNELS

# World-check tolerances: position relative to the hierarchy's size,
# axes as a dot-product shortfall (1e-4 ~ 0.8 degrees).
POS_TOL = 1.0e-4
AXIS_TOL = 1.0e-4


# --------------------------------------------------
# Logging / preferences / written-files manifest
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


def _app_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, PLUGIN)


def _write_json(name, data):
    try:
        folder = _app_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, name), "w") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
    except Exception:
        log_exception("write " + name)


def _read_json(name):
    try:
        with open(os.path.join(_app_dir(), name), "r") as fh:
            return json.load(fh)
    except Exception:
        return {}


def load_prefs():
    saved = _read_json("prefs.json")
    for k in SETTINGS:
        if k in saved and type(saved[k]) is type(SETTINGS[k]):
            SETTINGS[k] = saved[k]


def save_prefs():
    _write_json("prefs.json", SETTINGS)


# Every object file this plug-in writes is recorded with a hash of what it
# wrote. Update mode only ever overwrites a file that is in this list AND
# still has those exact bytes - never someone's hand-made right side, and
# never a file that was edited after it was mirrored.
MANIFEST = "written.json"


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _digest(data):
    return hashlib.sha1(data).hexdigest()


def record_written(path, data):
    manifest = _read_json(MANIFEST)
    manifest[_norm(path)] = _digest(data)
    _write_json(MANIFEST, manifest)


def written_and_unchanged(path):
    want = _read_json(MANIFEST).get(_norm(path))
    if not want or not os.path.isfile(path):
        return False
    with open(path, "rb") as fh:
        return _digest(fh.read()) == want


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


def owner_object(ii, item):
    """The object a bone belongs to (walk up past parent bones)."""
    cur = ii.parent(item)
    while cur and ii.type(cur) == lwsdk.LWI_BONE:
        cur = ii.parent(cur)
    return cur


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


def item_channels(item):
    """{channel name: (channel, envelope)} for an item's own channels."""
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
            found[ci.channelName(chan)] = (chan, env)
        chan = ci.nextChannel(group, chan)
    return found


def item_envelopes(item):
    return dict((n, ce[1]) for n, ce in item_channels(item).items())


def channel_modifiers(item, names):
    """[(channel name, modifier server)] - expressions and other channel
    modifiers on the given channels. Their output is not mirrored."""
    ci = lwsdk.LWChannelInfo()
    found = []
    for name, (chan, _) in sorted(item_channels(item).items()):
        if name not in names:
            continue
        for idx in range(1, 9):
            try:
                server = ci.server(chan, "ChannelHandler", idx)
            except Exception:
                server = None
            if not server:
                break
            found.append((name, server))
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


KEY_ATTRS = ("LWKEY_SHAPE", "LWKEY_TENSION", "LWKEY_CONTINUITY", "LWKEY_BIAS",
             "LWKEY_PARAM_0", "LWKEY_PARAM_1", "LWKEY_PARAM_2", "LWKEY_PARAM_3")
BEHAVIOURS = ("LWENVTAG_PREBEHAVE", "LWENVTAG_POSTBEHAVE")


def copy_envelope(ef, src, dst, group=None):
    """Make `dst` an exact copy of `src`: keys with shape, TCB and tangent
    parameters, and (when the binding allows) pre/post behaviour."""
    keys = []
    for k in env_keys(ef, src):
        attrs = []
        for name in KEY_ATTRS:
            tag = getattr(lwsdk, name, None)
            if tag is None:
                continue
            try:
                attrs.append((tag, key_get(ef, src, k, tag)))
            except Exception:
                pass
        keys.append((float(key_get(ef, src, k, lwsdk.LWKEY_TIME)),
                     float(key_get(ef, src, k, lwsdk.LWKEY_VALUE)), attrs))
    for k in env_keys(ef, dst):
        ef.destroyKey(dst, k)
    for when, value, attrs in keys:
        k = ef.createKey(dst, when, value)
        for tag, v in attrs:
            if v is not None:
                ef.keySet(dst, k, tag, v)
    for name in BEHAVIOURS:
        tag = getattr(lwsdk, name, None)
        if tag is None:
            continue
        try:
            ef.egSet(dst, group, tag, int(_unwrap(ef.egGet(src, group, tag))))
        except Exception:
            pass


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


def _differs(a, b, tol=1.0e-7):
    return a is None or b is None or any(abs(x - y) > tol for x, y in zip(a, b))


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

    def __init__(self, mode=MODE_CREATE):
        self.mode = mode
        self.lines = []
        self.warnings = []
        self.created = []      # top items made (create) or updated (update)
        self.items = 0         # every item made or updated

    def note(self, text):
        self.lines.append(text)
        print("%s: %s" % (PLUGIN, text))

    def warn(self, text):
        self.warnings.append(text)
        print("%s: WARNING %s" % (PLUGIN, text))

    def summary(self):
        head = "%s %d item(s)." % ("Updated" if self.mode == MODE_UPDATE else "Mirrored",
                                   self.items)
        if self.warnings:
            head += " %d warning(s) - see the Python console." % len(self.warnings)
        return head


# --------------------------------------------------
# Finding things
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
    """[(item, parent item)] preorder, read before anything changes."""
    out = []
    stack = [(root, None)]
    while stack:
        item, parent = stack.pop()
        out.append((item, parent))
        kids = children(ii, item)
        for kid in reversed(kids):
            stack.append((kid, item))
    return out


def find_by_name(ii, name, like, exclude=()):
    """An existing item named `name` (or `name (n)`), of the same type as
    `like` (and the same object, for bones). Exact names win."""
    if not name:
        return None
    want_type = ii.type(like)
    want_owner = key(owner_object(ii, like)) if want_type == lwsdk.LWI_BONE else None
    loose = None
    for item in all_items(ii):
        if ii.type(item) != want_type or key(item) in exclude:
            continue
        if want_type == lwsdk.LWI_BONE and key(owner_object(ii, item)) != want_owner:
            continue
        if ii.name(item) == name:
            return item
        if loose is None and mm.base_item_name(ii.name(item)) == name:
            loose = item
    return loose


def clone_one(ii, item):
    """Clone `item`. Returns (clone, other new items) - Layout clones an
    object's bones with it."""
    before = set(key(i) for i in all_items(ii))
    select(item)
    cmd("Clone 1")
    ii = lwsdk.LWItemInfo()
    new_items = [i for i in all_items(ii) if key(i) not in before]
    new_keys = set(key(i) for i in new_items)
    chosen = None
    for sel in lwsdk.LWInterfaceInfo().selected_items():
        if key(sel) in new_keys:
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


def match_partners(ii, nodes, root_partner, pairs):
    """{original key: other-side item} for Update mode, walking down from
    the root's partner: each original's partner is a child of its parent's
    partner named as its other side (L_Hand -> R_Hand), or with the same
    name when the name has no side (Finger1 under R_Hand). Returns
    (mapping, [originals with no partner])."""
    mapping = {key(nodes[0][0]): root_partner}
    used = set([key(root_partner)])
    originals = set(key(n) for n, _ in nodes)
    missing = []
    for node, parent in nodes[1:]:
        host = mapping.get(key(parent))
        if host is None:
            missing.append(node)
            continue
        base = mm.base_item_name(ii.name(node))
        want = mm.mirror_name(base, pairs) or base
        found = None
        for kid in children(ii, host):
            if (key(kid) in used or key(kid) in originals
                    or ii.type(kid) != ii.type(node)):
                continue
            if mm.base_item_name(ii.name(kid)) == want:
                found = kid
                break
        if found is None:
            missing.append(node)
            continue
        mapping[key(node)] = found
        used.add(key(found))
    return mapping, missing


# --------------------------------------------------
# The mirror
# --------------------------------------------------


class Mirror(object):

    def __init__(self, settings, report):
        self.s = settings
        self.report = report
        self.update = settings.get("mode", MODE_CREATE) == MODE_UPDATE
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
        plane_item = self.plane_item(ii, root)
        mw = mm.mirror_about(world_frame(ii, plane_item, self.when)) if plane_item else mm.MIRROR
        before = dict((key(n), world_axes(ii, n, self.when)) for n, _ in nodes)

        if self.update:
            mapping = self.partners(nodes)
            if mapping is None:
                return None
            ii = lwsdk.LWItemInfo()
            top = mapping[key(root)]
            new_parent = ii.parent(top)
            for node, _ in nodes:
                other = mapping.get(key(node))
                if other is not None:
                    self.copy_motion(node, other)
        else:
            new_parent = self.new_parent(ii, root)
            mapping = self.clone_all(nodes)
            ii = lwsdk.LWItemInfo()
            top = mapping[key(root)]
            select(top)
            if new_parent:
                cmd("ParentItem " + key(new_parent))
            else:
                cmd("ParentItem")

        a = (world_frame(ii, new_parent, self.when).inverse() * mw
             * world_frame(ii, orig_parent, self.when))
        scale = max([1.0] + [abs(c) for n, _ in nodes for c in (before[key(n)][0] or [])])
        plain_root = mm.is_plain_mirror(a, scale=scale)

        for node, _ in nodes:
            other = mapping.get(key(node))
            if other is None:
                continue
            if ii.type(node) == lwsdk.LWI_OBJECT and self.s["mesh"] == MESH_MIRRORED:
                if self.update:
                    self.update_mesh(node, other)
                else:
                    self.mirror_mesh(node, other)
            if key(node) == key(root) and not plain_root:
                self.solve_root(other, orig_parent, new_parent, plane_item)
            else:
                self.mirror_channels(other)
            self.mirror_pivot(node, other)
            if ii.type(node) == lwsdk.LWI_BONE:
                self.mirror_bone(node, other)
            for chan, server in channel_modifiers(node, mm.MIRROR_CHANNELS):
                self.report.warn("%s: %s has a %s modifier - %s, not mirrored."
                                 % (ii.name(node), chan, server,
                                    "kept on the other side" if self.update else "copied"))

        self.fix_references(nodes, mapping)
        if not self.update:
            self.rename(nodes, mapping)
        cmd("RefreshNow")
        self.check_world(nodes, mapping, before, mw, scale)
        self.report.created.append(top)
        self.report.items += len(mapping)
        return top

    def partners(self, nodes):
        ii = lwsdk.LWItemInfo()
        root = nodes[0][0]
        originals = set(key(n) for n, _ in nodes)
        other = mm.mirror_name(ii.name(root), self.pairs)
        partner = (find_by_name(ii, mm.base_item_name(other), root, exclude=originals)
                   if other else None)
        if partner is None:
            self.report.warn("%s: no other-side item%s to update - use Create mode first."
                             % (ii.name(root), " named " + other if other else
                                " (the name has no Left/Right in it)"))
            return None
        mapping, missing = match_partners(ii, nodes, partner, self.pairs)
        for node in missing:
            self.report.warn("%s: no matching item under %s on the other side - skipped "
                             "(with anything below it)." % (ii.name(node), ii.name(partner)))
        return mapping

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

    def copy_motion(self, node, other):
        """Update mode: the other side's motion channels become a copy of
        the original's, ready for the mirror rule."""
        ii = lwsdk.LWItemInfo()
        src = item_envelopes(node)
        dst = item_envelopes(other)
        group = ii.chanGroup(other)
        for name in MOTION_CHANNELS:
            if name in src and name in dst:
                copy_envelope(self.ef, src[name], dst[name], group)

    def mirror_channels(self, item):
        envs = item_envelopes(item)
        for name in mm.MIRROR_CHANNELS:
            env = envs.get(name)
            if env:
                negate_envelope(self.ef, env)

    def solve_root(self, item, orig_parent, new_parent, plane_item):
        """The top item's parent is not the mirror image of the original's
        parent, so solve L' = A.L.M at each key time (union over position and
        rotation). Other times follow the keys' own interpolation. `item`
        holds a copy of the original's keys when this runs."""
        ii = lwsdk.LWItemInfo()
        envs = item_envelopes(item)
        names = POSITION_CHANNELS + ROTATION_CHANNELS
        if any(n not in envs for n in names):
            self.report.warn("%s: missing motion channels - used the plain rule."
                             % ii.name(item))
            self.mirror_channels(item)
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
                         % (ii.name(item), len(writes)))

    def mirror_pivot(self, node, other):
        """Pivot from the ORIGINAL, set on the result when it differs:
        ReplaceWithObject may already have given it the mirrored file's
        layer pivot, and in Update mode it may hold anything."""
        ii = lwsdk.LWItemInfo()
        piv = vec3(ii.param(node, lwsdk.LWIP_PIVOT, self.when))
        if piv:
            want = [-piv[0], piv[1], piv[2]]
            if _differs(vec3(ii.param(other, lwsdk.LWIP_PIVOT, self.when)), want):
                select(other)
                ok = set_vector_verified(
                    "PivotPosition", want,
                    lambda: lwsdk.LWItemInfo().param(other, lwsdk.LWIP_PIVOT, self.when))
                if ok is False:
                    self.report.warn("%s: pivot position did not take." % ii.name(other))
        prot = vec3(ii.param(node, lwsdk.LWIP_PIVOT_ROT, self.when))
        if prot:
            want = [-prot[0], prot[1], -prot[2]]
            if _differs(vec3(ii.param(other, lwsdk.LWIP_PIVOT_ROT, self.when)), want):
                select(other)
                ok = set_vector_verified(
                    "PivotRotation", want,
                    lambda: lwsdk.LWItemInfo().param(other, lwsdk.LWIP_PIVOT_ROT, self.when),
                    angles=True)
                if ok is False:
                    self.report.warn("%s: pivot rotation did not take." % ii.name(other))

    def mirror_bone(self, node, other):
        ii = lwsdk.LWItemInfo()
        bi = lwsdk.LWBoneInfo()
        name = ii.name(other)
        pos = vec3(bi.restParam(node, lwsdk.LWIP_POSITION))
        rot = vec3(bi.restParam(node, lwsdk.LWIP_ROTATION))
        select(other)
        if pos:
            want = [-pos[0], pos[1], pos[2]]
            if _differs(vec3(bi.restParam(other, lwsdk.LWIP_POSITION)), want):
                ok = set_vector_verified(
                    "BoneRestPosition", want,
                    lambda: lwsdk.LWBoneInfo().restParam(other, lwsdk.LWIP_POSITION))
                if ok is False:
                    self.report.warn("%s: rest position did not take." % name)
        if rot:
            want = [-rot[0], rot[1], -rot[2]]
            if _differs(vec3(bi.restParam(other, lwsdk.LWIP_ROTATION)), want):
                ok = set_vector_verified(
                    "BoneRestRotation", want,
                    lambda: lwsdk.LWBoneInfo().restParam(other, lwsdk.LWIP_ROTATION),
                    angles=True)
                if ok is False:
                    self.report.warn("%s: rest rotation did not take." % name)
        if self.s["rename"]:
            wmap = bi.weightMap(node)
            target = mm.mirror_name(wmap, self.pairs) if wmap else None
            if target and target != bi.weightMap(other):
                cmd("BoneWeightMapName " + target)

    # ---------- meshes ----------

    def mirrored_bytes(self, path, label):
        """(bytes, stats) for the mirrored copy of `path`, or (None, None)."""
        if path not in self.mesh_cache:
            with open(path, "rb") as fh:
                data = fh.read()
            try:
                out, stats = lwo_mirror.mirror_bytes(data, bool(self.s["rename"]), self.pairs)
            except lwo_mirror.LwoError as exc:
                self.report.warn("%s: cannot read %s (%s) - mesh not mirrored."
                                 % (label, path, exc))
                out, stats = None, None
            if stats is not None:
                stats["symmetric"] = lwo_mirror.is_point_symmetric(data)
                if stats["unresolved"]:
                    self.report.warn("%s: %s still mentions %s outside the maps (a surface "
                                     "or node this plug-in can't edit) - check it."
                                     % (label, os.path.basename(path),
                                        ", ".join(stats["unresolved"])))
            self.mesh_cache[path] = (out, stats)
        return self.mesh_cache[path]

    def _mesh_source(self, node):
        oi = lwsdk.LWObjectInfo()
        if not oi.numPoints(node):
            return None                                 # a null
        path = oi.filename(node)
        if not path or not os.path.isfile(path):
            self.report.warn("%s has no saved object file - save it first. Its mesh is "
                             "not mirrored." % lwsdk.LWItemInfo().name(node))
            return None
        return path

    def mirror_mesh(self, node, clone):
        path = self._mesh_source(node)
        if not path:
            return
        label = lwsdk.LWItemInfo().name(node)
        out, stats = self.mirrored_bytes(path, label)
        if out is None:
            return
        if self.s["reuse_symmetric"] and not stats["renamed"] and stats["symmetric"]:
            self.report.note("%s is symmetric - the clone keeps %s."
                             % (label, os.path.basename(path)))
            return
        new_path = self.mesh_cache.get(("written", path))
        if new_path is None:
            new_path = self.write_new_file(path, out, stats, label)
            self.mesh_cache[("written", path)] = new_path
        if new_path:
            self.replace_mesh(node, clone, new_path, stats["layers"], label)

    def write_new_file(self, path, out, stats, label):
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
            record_written(cand, out)
            self.report.note("%s -> %s (%d polygons reversed%s%s)." % (
                os.path.basename(path), os.path.basename(cand), stats["polygons"],
                ", %d map(s) renamed" % len(stats["renamed"]) if stats["renamed"] else "",
                ", %d node reference(s)" % stats["node_refs"] if stats["node_refs"] else ""))
            return cand
        self.report.warn("%s: no free file name for the mirrored copy." % label)
        return None

    def update_mesh(self, node, other):
        """Rewrite the other side's mesh file - only when this plug-in wrote
        it and it is unchanged since. Never touches a hand-made file."""
        path = self._mesh_source(node)
        if not path:
            return
        oi = lwsdk.LWObjectInfo()
        label = lwsdk.LWItemInfo().name(node)
        target = oi.filename(other) or ""
        if not target:
            return
        if _norm(target) == _norm(path):
            return            # the other side reuses the (symmetric) original file
        out, stats = self.mirrored_bytes(path, label)
        if out is None:
            return
        if os.path.isfile(target):
            with open(target, "rb") as fh:
                if fh.read() == out:
                    return                                  # already current
        if not written_and_unchanged(target):
            self.report.note("%s: %s was not written by Mirror Hierarchy, or was edited "
                             "since - mesh left alone." % (label, os.path.basename(target)))
            return
        with open(target, "wb") as fh:
            fh.write(out)
        record_written(target, out)
        self.report.note("%s -> %s rewritten (%d polygons reversed)."
                         % (os.path.basename(path), os.path.basename(target), stats["polygons"]))
        self.replace_mesh(node, other, target, stats["layers"], label)

    def replace_mesh(self, node, item, new_path, layers, label):
        oi = lwsdk.LWObjectInfo()
        want_points = oi.numPoints(node)
        select(item)
        if layers <= 1:
            cmd("ReplaceWithObject " + new_path)
        else:
            layer = int(oi.layerLoaded(node) or 1)
            for n in (layer, layer + 1):
                cmd("ReplaceObjectLayer %d %s" % (n, new_path))
                if lwsdk.LWObjectInfo().numPoints(item) == want_points:
                    break
        oi = lwsdk.LWObjectInfo()
        got = oi.filename(item) or ""
        if _norm(got) != _norm(new_path):
            self.report.warn("%s: ReplaceWithObject did not take (still uses %s)."
                             % (label, got or "no file"))
        elif oi.numPoints(item) != want_points:
            self.report.warn("%s: mirrored mesh has %d points, the original %d - "
                             "wrong layer?" % (label, oi.numPoints(item), want_points))

    # ---------- links, names, check ----------

    def fix_references(self, nodes, mapping):
        ii = lwsdk.LWItemInfo()
        links = [("GoalItem", lambda n: ii.goal(n)),
                 ("TargetItem", lambda n: ii.target(n)),
                 ("PoleItem", lambda n: ii.pole(n)),
                 ("PositionItem", lambda n: ii.sameItem(n, lwsdk.LWIP_POSITION)),
                 ("RotationItem", lambda n: ii.sameItem(n, lwsdk.LWIP_ROTATION)),
                 ("ScaleItem", lambda n: ii.sameItem(n, lwsdk.LWIP_SCALING))]
        for node, _ in nodes:
            other = mapping.get(key(node))
            if other is None:
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
                    side = mm.mirror_name(ii.name(ref), self.pairs)
                    target = find_by_name(ii, side, ref) if side else None
                if target is not None:
                    try:
                        current = getter(other)
                    except Exception:
                        current = None
                    if key(current) != key(target):
                        select(other)
                        cmd("%s %s" % (command, key(target)))
                elif mm.mirror_name(ii.name(ref), self.pairs):
                    self.report.warn("%s: %s still points at %s (no other-side item found)."
                                     % (ii.name(other), command, ii.name(ref)))

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
        """Each result's world position and axes against the mirror image of
        the original's: pos' = Mw.pos, right' = -Mw.right, up' = Mw.up,
        forward' = Mw.forward. IK, expressions and modifiers can move an
        item away from that legitimately; the report names them."""
        ii = lwsdk.LWItemInfo()
        bad = []
        worst = 0.0
        for node, _ in nodes:
            other = mapping.get(key(node))
            if other is None:
                continue
            pos, axes = before[key(node)]
            gpos, gaxes = world_axes(ii, other, self.when)
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
                bad.append("%s (position %.2g, axes %.2g)" % (ii.name(other), perr, aerr))
        if bad:
            self.report.warn("%d item(s) are not the exact mirror image at this frame "
                             "(IK / expressions / modifiers can cause that): %s"
                             % (len(bad), ", ".join(bad)))
        else:
            self.report.note("World check passed for %d item(s) (worst %.1g)."
                             % (len(mapping), worst))


def run(settings=None):
    """Mirror the selected hierarchies. Returns the Report."""
    settings = settings or SETTINGS
    report = Report(settings.get("mode", MODE_CREATE))
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
