# -*- Mode: Python -*-
# -*- coding: utf-8 -*-
"""Mirror Hierarchy (Clean) - clone and mirror item hierarchies across X
with no negative scale, or update the existing other side from this one.
Meshes get a mirrored copy of their object file (points negated in X AND
polygon winding reversed), items get mirrored channels (Position.X,
Heading, Bank negated on every key).

Generic: MC_MirrorHierarchy        panel, then mirror
         MC_MirrorHierarchyAgain   mirror with the last settings (hotkey)

Text shown in Layout goes through LightWave's l10n resource tags (context
"MirrorHierarchy"); translations live in l10n/<locale>/MirrorHierarchy.resource.
Console output stays plain English - the console would print the raw tags.

Keep this file Python 2.7-parseable: LightWave scans plug-ins with both
interpreters. All real work is in mirrorhierarchy_core, imported inside
process() so a broken import gives a traceback instead of LightWave's
silent "not a valid plug-in container".
"""

import lwsdk

__author__ = "Matthew Christou"
__version__ = "0.2.0"
__lwver__ = "2025"

L10N_CONTEXT = "MirrorHierarchy"


def tr(key):
    """Resource-tagged text: LightWave shows the translation for the
    user's language, or `key` itself when there is none. Keys must not
    contain '=' or a double quote (resource file syntax)."""
    return '\04(k:"%s" c:%s)' % (key, L10N_CONTEXT)


def _load_core():
    import os
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import mirrorhierarchy_core as core
    if getattr(core, "__version__", None) != __version__:
        raise ImportError("MirrorHierarchy %s installed, but Layout still has core %s "
                          "loaded - restart Layout." % (__version__, core.__version__))
    return core


def _info(first, second=""):
    try:
        lwsdk.LWMessageFuncs().info(first, second)
    except Exception:
        print("Mirror Hierarchy: %s %s" % (first, second))


def _error(first, second=""):
    try:
        lwsdk.LWMessageFuncs().error(first, second)
    except Exception:
        print("Mirror Hierarchy: %s %s" % (first, second))


def _show_report(report):
    """Dialog: fixed phrases are translated, numbers appended. The details
    (item names, files) are on the console in English."""
    if report.warnings and not report.created:
        _error(tr("Nothing was mirrored."), tr("See the Python console for details."))
        return
    head = tr("Updated items:" if report.mode == 1 else "Mirrored items:") + " %d" % report.items
    if report.warnings:
        _info(head, tr("Warnings:") + " %d - " % len(report.warnings)
              + tr("See the Python console for details."))
    else:
        _info(head, tr("World check passed."))


PANEL_NOTES = [
    "No negative scale: meshes get a mirrored copy of their",
    "object file (X negated, polygons flipped), items get",
    "Position X, Heading and Bank negated on every key.",
    "Update mode rewrites the R side's keys from the L side.",
    "Extra side pairs, for example:  Lf/Rt, lft/rgt",
    "Save the scene first - this can't be undone in one step.",
]


def _panel(core):
    """Settings panel. True on OK."""
    s = core.SETTINGS
    ui = lwsdk.LWPanels()
    panel = ui.create(tr("Mirror Hierarchy (Clean)") + " " + __version__)
    try:
        mode = panel.popup_ctl(tr("Mode"), [tr(t) for t in core.MODE_LABELS])
        plane = panel.popup_ctl(tr("Mirror across"), [tr(t) for t in core.PLANE_LABELS])
        parent = panel.popup_ctl(tr("Parent clone to"), [tr(t) for t in core.PARENT_LABELS])
        mesh = panel.popup_ctl(tr("Meshes"), [tr(t) for t in core.MESH_LABELS])
        reuse = panel.bool_ctl(tr("Keep file if symmetric"))
        rename = panel.bool_ctl(tr("Swap Left/Right in names"))
        sides = panel.str_ctl(tr("Extra side pairs"), 30)
        info = panel.text_ctl("", [tr(t) for t in PANEL_NOTES])
        controls = [mode, plane, parent, mesh, reuse, rename, sides, info]
        mode.set_int(s["mode"])
        plane.set_int(s["plane"])
        parent.set_int(s["parent"])
        mesh.set_int(s["mesh"])
        reuse.set_int(s["reuse_symmetric"])
        rename.set_int(s["rename"])
        sides.set_str(s["sides"])
        panel.align_controls_vertical(controls)
        panel.size_to_layout(5, 5)
        if not panel.open(lwsdk.PANF_BLOCKING | lwsdk.PANF_CANCEL):
            return False
        s["mode"] = int(mode.get_int())
        s["plane"] = int(plane.get_int())
        s["parent"] = int(parent.get_int())
        s["mesh"] = int(mesh.get_int())
        s["reuse_symmetric"] = int(reuse.get_int())
        s["rename"] = int(rename.get_int())
        s["sides"] = str(sides.get_str() or "")
        return True
    finally:
        ui.destroy(panel)


class MirrorHierarchyGeneric(lwsdk.IGeneric):

    ask = True

    def __init__(self, context):
        lwsdk.IGeneric.__init__(self)

    def process(self, ga):
        try:
            core = _load_core()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            _error(tr("Could not load the plug-in core."), str(exc))
            return lwsdk.AFUNC_OK
        try:
            if not lwsdk.LWInterfaceInfo().selected_items():
                _error(tr("Select the top item of each hierarchy to mirror."))
                return lwsdk.AFUNC_OK
            core.load_prefs()
            if self.ask:
                if not _panel(core):
                    return lwsdk.AFUNC_OK
                core.save_prefs()
            _show_report(core.run(core.SETTINGS))
        except Exception as exc:
            core.log_exception("process")
            _error(tr("Failed - see the Python console."), str(exc))
        return lwsdk.AFUNC_OK


class MirrorHierarchyAgain(MirrorHierarchyGeneric):
    ask = False


ServerTagInfo = [
    ("Mirror Hierarchy (Clean)", lwsdk.SRVTAG_USERNAME | lwsdk.LANGID_USENGLISH),
    ("Mirror Hierarchy (Clean)", lwsdk.SRVTAG_BUTTONNAME | lwsdk.LANGID_USENGLISH),
    ("Utilities/Python", lwsdk.SRVTAG_MENU | lwsdk.LANGID_USENGLISH),
]

ServerTagInfoAgain = [
    ("Mirror Hierarchy (Clean) Again", lwsdk.SRVTAG_USERNAME | lwsdk.LANGID_USENGLISH),
    ("Mirror Hierarchy Again", lwsdk.SRVTAG_BUTTONNAME | lwsdk.LANGID_USENGLISH),
]

ServerRecord = {
    lwsdk.GenericFactory("MC_MirrorHierarchy", MirrorHierarchyGeneric): ServerTagInfo,
    lwsdk.GenericFactory("MC_MirrorHierarchyAgain", MirrorHierarchyAgain): ServerTagInfoAgain,
}
