# -*- coding: utf-8 -*-
"""LightWave plug-in container rules for the files in plugin/.

- Only MirrorHierarchy.py declares the version marker; helpers must not
  even contain the token, or LightWave scans them as plug-ins.
- Every file parses under LightWave's own Python 2.7 (it scans with both).
- File names are importable module names.
- Entry file and core agree on __version__.
"""

import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", "plugin"))
MARKER = "__lw" + "ver__"
LW27 = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "modules", "MSWIN",
                                     "x86_64", "Python-2.7.18", "python.exe"))

FILES = sorted(f for f in os.listdir(PLUGIN) if f.endswith(".py"))


def read(name):
    with open(os.path.join(PLUGIN, name), "rb") as fh:
        return fh.read().decode("utf-8")


class ContainerTests(unittest.TestCase):

    def test_marker_only_in_entry_file(self):
        for name in FILES:
            has = MARKER in read(name)
            self.assertEqual(has, name == "MirrorHierarchy.py", name)

    def test_module_names(self):
        for name in FILES:
            self.assertTrue(re.match(r"^[A-Za-z_][A-Za-z0-9_]*\.py$", name), name)

    def test_versions_agree(self):
        versions = set(re.search(r'__version__ = "([^"]+)"', read(n)).group(1)
                       for n in ("MirrorHierarchy.py", "mirrorhierarchy_core.py"))
        self.assertEqual(len(versions), 1, versions)

    def test_compiles_here(self):
        tmp = tempfile.mkdtemp()
        try:
            for name in FILES:
                py_compile.compile(os.path.join(PLUGIN, name),
                                   cfile=os.path.join(tmp, name + "c"), doraise=True)
        finally:
            shutil.rmtree(tmp)

    @unittest.skipUnless(os.path.isfile(LW27), "LightWave's Python 2.7 not found")
    def test_parses_under_lightwave_27(self):
        # Compile to a temp dir: a stray 2.7 .pyc in plugin/ would itself be
        # scanned by LightWave.
        tmp = tempfile.mkdtemp()
        try:
            for name in FILES:
                code = ("import py_compile; py_compile.compile(%r, cfile=%r, doraise=True)"
                        % (os.path.join(PLUGIN, name), os.path.join(tmp, name + "c")))
                proc = subprocess.Popen([LW27, "-c", code], stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT)
                out = proc.communicate()[0]
                self.assertEqual(proc.returncode, 0, "%s: %s" % (name, out))
        finally:
            shutil.rmtree(tmp)
        self.assertFalse([f for f in os.listdir(PLUGIN) if f.endswith(".pyc")])


if __name__ == "__main__":
    unittest.main()
