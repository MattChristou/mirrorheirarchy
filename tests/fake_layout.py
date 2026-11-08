# -*- coding: utf-8 -*-
"""A small fake of the Layout API surface mirrorhierarchy_core uses.

Installs `lwsdk` into sys.modules. The scene model:
  local L = T(pos) . R(hpb)   (pivot / pivot rotation stored, not applied)
  world   = parent world . L
These are assumptions about Layout, NOT facts - the tests check the core's
bookkeeping and maths against this model; Layout itself is checked by hand
(TESTING.md).

Deliberate traps, so the core has to cope:
  - firstChild() leaves bones out (core must find them via first(LWI_BONE)).
  - PivotRotation takes DEGREES, BoneRestRotation RADIANS (core must verify).
  - ReplaceWithObject sets the item pivot from the file's layer pivot.
  - Clone of an object also clones its bones (same names); a clone stays
    under the original's parent; non-objects get " (n)" names.
"""

import math
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "plugin"))

import lwo_mirror  # noqa: E402
import mirror_math as mm  # noqa: E402

lwsdk = types.ModuleType("lwsdk")
sys.modules["lwsdk"] = lwsdk

for i, n in enumerate(["LWKEY_VALUE", "LWKEY_TIME", "LWKEY_SHAPE", "LWKEY_TENSION",
                       "LWKEY_CONTINUITY", "LWKEY_BIAS", "LWKEY_PARAM_0", "LWKEY_PARAM_1",
                       "LWKEY_PARAM_2", "LWKEY_PARAM_3"]):
    setattr(lwsdk, n, i)
lwsdk.LWI_OBJECT, lwsdk.LWI_LIGHT, lwsdk.LWI_CAMERA, lwsdk.LWI_BONE = 0, 1, 2, 3
lwsdk.LWIP_POSITION, lwsdk.LWIP_RIGHT, lwsdk.LWIP_UP, lwsdk.LWIP_FORWARD = 1, 2, 3, 4
lwsdk.LWIP_ROTATION, lwsdk.LWIP_SCALING, lwsdk.LWIP_PIVOT, lwsdk.LWIP_W_POSITION = 5, 6, 7, 8
lwsdk.LWIP_PIVOT_ROT = 12
lwsdk.LWGENF_PARENTINPLACE = 1 << 6
lwsdk.AFUNC_OK = 0
lwsdk.IGeneric = object
lwsdk.LWENVTAG_PREBEHAVE, lwsdk.LWENVTAG_POSTBEHAVE = 1, 2

CHANNELS = ["Position.X", "Position.Y", "Position.Z",
            "Rotation.H", "Rotation.P", "Rotation.B",
            "Scale.X", "Scale.Y", "Scale.Z"]


class Key(object):
    def __init__(self, time, value, shape=0, params=(0.0, 0.0, 0.0, 0.0)):
        self.time, self.value, self.shape = float(time), float(value), shape
        self.params = list(params)


class Env(object):
    def __init__(self, keys):
        self.keys = sorted(keys, key=lambda k: k.time)
        self.behave = {1: 1, 2: 1}               # pre / post: constant
        self.modifiers = []                      # channel modifier servers

    def copy(self):
        e = Env([Key(k.time, k.value, k.shape, k.params) for k in self.keys])
        e.behave = dict(self.behave)
        e.modifiers = list(self.modifiers)
        return e

    def evaluate(self, t):
        ks = self.keys
        if not ks:
            return 0.0
        if t <= ks[0].time:
            return ks[0].value
        for a, b in zip(ks, ks[1:]):
            if t <= b.time:
                f = (t - a.time) / (b.time - a.time)
                return a.value + f * (b.value - a.value)
        return ks[-1].value


class Item(object):
    def __init__(self, scene, itype, name, parent=None, pos=(0, 0, 0), hpb=(0, 0, 0)):
        self.scene = scene
        scene.counter += 1
        self.id = "%x" % (0x10000000 * (itype + 1) + scene.counter)
        self.type, self.name, self.parent = itype, name, parent
        self.envs = {}
        for c in CHANNELS:
            self.envs[c] = Env([Key(0, 1.0 if c.startswith("Scale") else 0.0)])
        self.set_local(0.0, pos, hpb)
        self.pivot = [0.0, 0.0, 0.0]
        self.pivot_rot = [0.0, 0.0, 0.0]
        self.rest_pos = [0.0, 0.0, 0.0]
        self.rest_rot = [0.0, 0.0, 0.0]
        self.weight_map = ""
        self.links = {}
        self.filename = ""
        self.points = 0
        self.layer = 1
        self.owner = None
        scene.items.append(self)

    def set_local(self, t, pos, hpb):
        for c, v in zip(CHANNELS[:6], list(pos) + list(hpb)):
            env = self.envs[c]
            env.keys = [k for k in env.keys if abs(k.time - t) > 1e-9]
            env.keys.append(Key(t, v))
            env.keys.sort(key=lambda k: k.time)

    def local(self, t):
        v = [self.envs[c].evaluate(t) for c in CHANNELS[:6]]
        return mm.Xform(mm.hpb_to_matrix(*v[3:]), v[:3])

    def world(self, t):
        w = self.local(t)
        return self.parent.world(t) * w if self.parent else w


class Scene(object):
    def __init__(self):
        self.items = []
        self.counter = 0
        self.selected = []
        self.time = 0.0
        self.flags = lwsdk.LWGENF_PARENTINPLACE          # PIP on, must come back on
        self.commands = []
        self.pip_states = []

    def add(self, itype, name, parent=None, **kw):
        return Item(self, itype, name, parent, **kw)

    def add_bone(self, obj, name, parent=None, **kw):
        b = Item(self, lwsdk.LWI_BONE, name, parent or obj, **kw)
        b.owner = obj
        return b

    def by_id(self, text):
        for it in self.items:
            if it.id == text:
                return it
        raise KeyError(text)

    def named(self, name):
        hits = [i for i in self.items if i.name == name]
        assert len(hits) == 1, (name, len(hits))
        return hits[0]

    def children(self, item):
        return [i for i in self.items if i.parent is item and i.type != lwsdk.LWI_BONE]

    # ---------- commands ----------

    def run(self, text):
        self.commands.append(text)
        verb, _, rest = text.partition(" ")
        args = rest.split()
        sel = self.selected[-1] if self.selected else None
        if verb == "SelectItem":
            self.selected = [self.by_id(args[0])]
        elif verb == "AddToSelection":
            self.selected.append(self.by_id(args[0]))
        elif verb == "Clone":
            self.selected = [self.clone(sel)]
        elif verb == "ParentItem":
            for it in self.selected:
                it.parent = self.by_id(args[0]) if args else None
        elif verb == "ParentInPlace":
            self.pip_states.append(int(args[0]))
            if int(args[0]):
                self.flags |= lwsdk.LWGENF_PARENTINPLACE
            else:
                self.flags &= ~lwsdk.LWGENF_PARENTINPLACE
        elif verb == "Rename":
            sel.name = rest
        elif verb in ("ReplaceWithObject", "ReplaceObjectLayer"):
            path = rest if verb == "ReplaceWithObject" else rest.partition(" ")[2]
            with open(path, "rb") as fh:
                layers = lwo_mirror.read_layers(fh.read())
            layer = layers[0] if verb == "ReplaceWithObject" else layers[int(args[0]) - 1]
            sel.filename = path
            sel.points = len(layer["points"])
            sel.name = os.path.splitext(os.path.basename(path))[0]
            sel.pivot = list(layer["pivot"])                  # trap
        elif verb == "PivotPosition":
            sel.pivot = [float(a) for a in args]
        elif verb == "PivotRotation":                         # trap: degrees
            sel.pivot_rot = [math.radians(float(a)) for a in args]
        elif verb == "BoneRestPosition":
            sel.rest_pos = [float(a) for a in args]
        elif verb == "BoneRestRotation":
            sel.rest_rot = [float(a) for a in args]
        elif verb == "BoneWeightMapName":
            sel.weight_map = rest
        elif verb in ("GoalItem", "TargetItem", "PoleItem", "PositionItem",
                      "RotationItem", "ScaleItem"):
            sel.links[verb] = self.by_id(args[0])
        elif verb == "RefreshNow":
            pass
        else:
            raise ValueError("unexpected command " + text)
        return 1

    def clone(self, src, parent="same", rename=True):
        name = src.name
        if rename and src.type != lwsdk.LWI_BONE and not src.filename:
            n = 1 + sum(1 for i in self.items if mm.base_item_name(i.name) == src.name)
            name = "%s (%d)" % (src.name, n - 1)
        new = Item(self, src.type, name, src.parent if parent == "same" else parent)
        new.envs = dict((c, e.copy()) for c, e in src.envs.items())
        for attr in ("pivot", "pivot_rot", "rest_pos", "rest_rot"):
            setattr(new, attr, list(getattr(src, attr)))
        new.weight_map, new.links = src.weight_map, dict(src.links)
        new.filename, new.points, new.layer, new.owner = (src.filename, src.points,
                                                          src.layer, src.owner)
        if src.type == lwsdk.LWI_OBJECT:
            # Bones come along, same names, same structure.
            made = {}
            for b in [i for i in self.items if i.type == lwsdk.LWI_BONE and i.owner is src]:
                made[b.id] = None
            order = [i for i in self.items if i.type == lwsdk.LWI_BONE and i.owner is src]
            for b in order:
                parent = new if b.parent is src else made[b.parent.id]
                nb = self.clone(b, parent=parent, rename=False)
                nb.owner = new
                made[b.id] = nb
        return new


SCENE = [Scene()]


def scene():
    return SCENE[0]


def reset():
    SCENE[0] = Scene()
    return SCENE[0]


def _find(text):
    return scene().by_id(text)


class LWItemInfo(object):
    def first(self, itype, owner):
        for it in scene().items:
            if it.type == itype and (itype != lwsdk.LWI_BONE or (owner and it.owner is owner)):
                return it
        return None

    def next(self, item):
        items = scene().items
        for it in items[items.index(item) + 1:]:
            if it.type == item.type and (it.type != lwsdk.LWI_BONE or it.owner is item.owner):
                return it
        return None

    def firstChild(self, item):
        kids = scene().children(item)
        return kids[0] if kids else None

    def nextChild(self, item, prev):
        kids = scene().children(item)
        i = kids.index(prev) + 1
        return kids[i] if i < len(kids) else None

    def parent(self, item):
        return item.parent

    def type(self, item):
        return item.type

    def name(self, item):
        return item.name

    def chanGroup(self, item):
        return item

    def goal(self, item):
        return item.links.get("GoalItem")

    def target(self, item):
        return item.links.get("TargetItem")

    def pole(self, item):
        return item.links.get("PoleItem")

    def sameItem(self, item, which):
        return item.links.get({lwsdk.LWIP_POSITION: "PositionItem",
                               lwsdk.LWIP_ROTATION: "RotationItem",
                               lwsdk.LWIP_SCALING: "ScaleItem"}[which])

    def param(self, item, which, t):
        if which == lwsdk.LWIP_PIVOT:
            return tuple(item.pivot)
        if which == lwsdk.LWIP_PIVOT_ROT:
            return tuple(item.pivot_rot)
        w = item.world(t)
        if which == lwsdk.LWIP_W_POSITION:
            return tuple(w.pos)
        col = {lwsdk.LWIP_RIGHT: 0, lwsdk.LWIP_UP: 1, lwsdk.LWIP_FORWARD: 2}[which]
        return tuple(mm.column(w.rot, col))


class LWChannelInfo(object):
    def nextChannel(self, group, prev):
        names = CHANNELS
        i = 0 if prev is None else names.index(prev[1]) + 1
        return (group, names[i]) if i < len(names) else None

    def channelName(self, chan):
        return chan[1]

    def channelEnvelope(self, chan):
        return chan[0].envs[chan[1]]

    def server(self, chan, cls, idx):
        mods = chan[0].envs[chan[1]].modifiers
        return mods[idx - 1] if cls == "ChannelHandler" and 0 < idx <= len(mods) else None


class LWEnvelopeFuncs(object):
    def nextKey(self, env, prev):
        if not env.keys:
            return None
        if prev is None:
            return env.keys[0]
        i = env.keys.index(prev) + 1
        return env.keys[i] if i < len(env.keys) else None

    def keyGet(self, env, k, tag):
        if tag == lwsdk.LWKEY_VALUE:
            return (1, k.value)
        if tag == lwsdk.LWKEY_TIME:
            return (1, k.time)
        if tag == lwsdk.LWKEY_SHAPE:
            return (1, k.shape)
        return (1, k.params[tag - lwsdk.LWKEY_PARAM_0])

    def keySet(self, env, k, tag, value):
        if tag == lwsdk.LWKEY_VALUE:
            k.value = value
        elif tag == lwsdk.LWKEY_SHAPE:
            k.shape = value
        else:
            k.params[tag - lwsdk.LWKEY_PARAM_0] = value

    def destroyKey(self, env, k):
        env.keys.remove(k)

    def egGet(self, env, group, tag):
        return (1, env.behave[tag])

    def egSet(self, env, group, tag, value):
        env.behave[tag] = value

    def createKey(self, env, t, value):
        k = Key(t, value)
        env.keys.append(k)
        env.keys.sort(key=lambda x: x.time)
        return k

    def evaluate(self, env, t):
        return env.evaluate(t)


class LWInterfaceInfo(object):
    def selected_items(self):
        return list(scene().selected)

    @property
    def curTime(self):
        return scene().time

    @property
    def generalFlags(self):
        return scene().flags


class LWSceneInfo(object):
    framesPerSecond = 30.0


class LWObjectInfo(object):
    def numPoints(self, item):
        return item.points

    def filename(self, item):
        return item.filename

    def layerLoaded(self, item):
        return item.layer


class LWBoneInfo(object):
    def restParam(self, bone, which):
        return tuple(bone.rest_pos if which == lwsdk.LWIP_POSITION else bone.rest_rot)

    def weightMap(self, bone):
        return bone.weight_map


class LWMessageFuncs(object):
    def info(self, *a):
        pass

    def error(self, *a):
        pass


lwsdk.LWItemInfo = LWItemInfo
lwsdk.LWChannelInfo = LWChannelInfo
lwsdk.LWEnvelopeFuncs = LWEnvelopeFuncs
lwsdk.LWInterfaceInfo = LWInterfaceInfo
lwsdk.LWSceneInfo = LWSceneInfo
lwsdk.LWObjectInfo = LWObjectInfo
lwsdk.LWBoneInfo = LWBoneInfo
lwsdk.LWMessageFuncs = LWMessageFuncs
lwsdk.itemid_to_str = lambda item: item.id
lwsdk.command = lambda text: scene().run(text)
