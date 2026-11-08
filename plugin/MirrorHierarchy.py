# -*- Mode: Python -*-
# -*- coding: utf-8 -*-
"""Mirror Hierarchy (Clean) - clone and mirror item hierarchies across X
with no negative scale. Meshes get a mirrored copy of their object file
(points negated in X AND polygon winding reversed), items get mirrored
channels (Position.X, Heading, Bank negated on every key).

Generic: MC_MirrorHierarchy        panel, then mirror
         MC_MirrorHierarchyAgain   mirror with the last settings (hotkey)

Keep this file Python 2.7-parseable: LightWave scans plug-ins with both
interpreters. All real work is in mirrorhierarchy_core, imported inside
process() so a broken import gives a traceback instead of LightWave's
silent "not a valid plug-in container".
"""

import lwsdk

__author__ = "Matthew Christou"
__version__ = "0.1.0"
__lwver__ = "2025"


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


def _message(first, second=""):
    try:
        if second:
            lwsdk.LWMessageFuncs().info(first, second)
        else:
            lwsdk.LWMessageFuncs().info(first, "")
    except Exception:
        print(first, second)


def _error(text):
    try:
        lwsdk.LWMessageFuncs().error("Mirror Hierarchy", text)
    except Exception:
        print("Mirror Hierarchy: " + text)


def _show_report(report):
    if report.warnings and not report.created:
        _error(report.warnings[0])
        return
    detail = report.warnings[0] if report.warnings else (report.lines[-1] if report.lines else "")
    _message(report.summary(), detail[:200])


def _panel(core):
    """Settings panel. True on OK."""
    s = core.SETTINGS
    ui = lwsdk.LWPanels()
    panel = ui.create("Mirror Hierarchy (Clean) %s" % __version__)
    try:
        plane = panel.popup_ctl("Mirror across", core.PLANE_LABELS)
        parent = panel.popup_ctl("Parent clone to", core.PARENT_LABELS)
        mesh = panel.popup_ctl("Meshes", core.MESH_LABELS)
        reuse = panel.bool_ctl("Keep file if symmetric")
        rename = panel.bool_ctl("Swap Left/Right in names")
        sides = panel.str_ctl("Extra side pairs", 30)
        info = panel.text_ctl("", [
            "No negative scale: meshes get a mirrored copy of their",
            "object file (X negated, polygons flipped), items get",
            "Position X / Heading / Bank negated on every key.",
            "Extra side pairs: e.g.  Lf/Rt, lft/rgt",
            "Save the scene first - this can't be undone in one step.",
        ])
        controls = [plane, parent, mesh, reuse, rename, sides, info]
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
            _error("Could not load the plug-in core: %s" % exc)
            return lwsdk.AFUNC_OK
        try:
            if not lwsdk.LWInterfaceInfo().selected_items():
                _error("Select the top item of each hierarchy to mirror.")
                return lwsdk.AFUNC_OK
            core.load_prefs()
            if self.ask:
                if not _panel(core):
                    return lwsdk.AFUNC_OK
                core.save_prefs()
            _show_report(core.run(core.SETTINGS))
        except Exception as exc:
            core.log_exception("process")
            _error("Failed: %s (see the Python console)" % exc)
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
