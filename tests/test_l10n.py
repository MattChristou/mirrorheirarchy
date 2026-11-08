# -*- coding: utf-8 -*-
"""Every resource-tagged string has an entry in the English base file and
in each translation; keys are legal; files are in LightWave's format."""

import ast
import io
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
PLUGIN = os.path.join(ROOT, "plugin")
L10N = os.path.join(ROOT, "l10n")


def _strings(node):
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) if hasattr(ast, "Constant") else False:
            if isinstance(sub.value, str):
                out.append(sub.value)
        elif type(sub).__name__ == "Str":                 # Python 2.7
            out.append(sub.s)
    return out


def _tree(name):
    with open(os.path.join(PLUGIN, name), "rb") as fh:   # bytes: 2.7 rejects a
        return ast.parse(fh.read())                        # coding line in unicode


def used_keys():
    """tr("...") literals in the entry file, plus the label lists it
    passes through tr() (core *_LABELS and PANEL_NOTES)."""
    keys = set()
    entry = _tree("MirrorHierarchy.py")
    for node in ast.walk(entry):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr"
                and node.args and not isinstance(node.args[0], ast.Name)):
            keys.update(_strings(node.args[0]))
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PANEL_NOTES":
            keys.update(_strings(node.value))
    for node in ast.walk(_tree("mirrorhierarchy_core.py")):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "").endswith("_LABELS"):
            keys.update(_strings(node.value))
    return keys


def read_resource(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8")
    entries = {}
    for line in text.splitlines()[1:]:
        if not line.strip() or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        entries[k] = v
    return raw, text, entries


def resource_files():
    out = [os.path.join(L10N, "MirrorHierarchy.resource")]
    for name in sorted(os.listdir(L10N)):
        sub = os.path.join(L10N, name, "MirrorHierarchy.resource")
        if os.path.isfile(sub):
            out.append(sub)
    return out


class L10nTests(unittest.TestCase):

    def test_keys_found(self):
        keys = used_keys()
        self.assertIn("Mode", keys)
        self.assertIn("Updated items:", keys)          # inside a conditional
        self.assertIn("Create mirrored clones", keys)  # core label list
        self.assertGreater(len(keys), 25)

    def test_keys_legal(self):
        for k in used_keys():
            self.assertNotIn("=", k)
            self.assertNotIn('"', k)
            self.assertEqual(k, k.strip())

    def test_every_file_has_every_key(self):
        keys = used_keys()
        files = resource_files()
        self.assertIn(os.path.join(L10N, "jp", "MirrorHierarchy.resource"), files)
        for path in files:
            raw, text, entries = read_resource(path)
            self.assertTrue(raw.startswith(b"LWRS 1"), path)       # no BOM, header first
            self.assertEqual(sorted(keys - set(entries)), [], path)
            self.assertEqual(sorted(set(entries) - keys), [], path)  # no stale keys

    def test_translations_filled(self):
        _, _, entries = read_resource(os.path.join(L10N, "jp", "MirrorHierarchy.resource"))
        empty = [k for k, v in entries.items() if not v.strip()]
        self.assertEqual(empty, [])
        self.assertTrue(any(ord(c) > 0x3000 for v in entries.values() for c in v))


if __name__ == "__main__":
    unittest.main()
