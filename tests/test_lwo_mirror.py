# -*- coding: utf-8 -*-
"""lwo_mirror: geometry, winding, vmaps, names, pass-through, real files."""

import glob
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "plugin"))
sys.path.insert(0, HERE)

import lwo_build  # noqa: E402
import lwo_mirror  # noqa: E402

# Real LW-saved objects (LWO2 and LWO3), if the LWOFix checkout is beside us.
SEEDS = sorted(glob.glob(os.path.join(HERE, "..", "..", "LWOFix", "tests", "seeds", "*.lwo")))


def face_normal(points, idx):
    """Newell normal. LightWave is left-handed with clockwise front faces,
    but only the RELATION between the two normals matters here."""
    n = [0.0, 0.0, 0.0]
    for i in range(len(idx)):
        a = points[idx[i]]
        b = points[idx[(i + 1) % len(idx)]]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return n


class SyntheticTests(unittest.TestCase):

    def setUp(self):
        self.src = lwo_build.build([lwo_build.hand_layer()])
        self.out, self.stats = lwo_mirror.mirror_bytes(self.src)
        self.a = lwo_mirror.read_layers(self.src)[0]
        self.b = lwo_mirror.read_layers(self.out)[0]

    def test_points_negate_x_only(self):
        for p, q in zip(self.a["points"], self.b["points"]):
            self.assertEqual((-p[0], p[1], p[2]), tuple(q))

    def test_faces_reversed_so_normals_mirror(self):
        """The whole point: with the winding reversed, each face normal is
        the MIRROR of the original (M.n), not its opposite. Negative scale
        alone gives -M.n - an inside-out mesh."""
        for (ta, ia), (tb, ib) in zip(self.a["polys"], self.b["polys"]):
            self.assertEqual(ta, tb)
            if ta not in lwo_mirror.REVERSE_POLY_TYPES:
                self.assertEqual(ia, ib, ta)
                continue
            self.assertEqual(ib[0], ia[0])
            self.assertEqual(ib[1:], ia[:0:-1])
            na = face_normal(self.a["points"], ia)
            nb = face_normal(self.b["points"], ib)
            for got, want in zip(nb, (-na[0], na[1], na[2])):
                self.assertAlmostEqual(got, want, places=5)

    def test_skelegon_and_curve_untouched(self):
        types = [t for t, _ in self.b["polys"]]
        self.assertIn(b"BONE", types)
        self.assertIn(b"CURV", types)

    def test_reversed_counts(self):
        self.assertEqual(self.stats["polygons"], 7)      # 6 FACE + 1 SUBD
        self.assertEqual(self.stats["points"], 8)

    def test_bbox_and_pivot(self):
        self.assertAlmostEqual(self.b["pivot"][0], -1.5)
        bb = self.b["bbox"]
        self.assertEqual((bb[0], bb[3]), (-2.0, -1.0))
        self.assertEqual(bb[1:3] + bb[4:6], self.a["bbox"][1:3] + self.a["bbox"][4:6])

    def test_vmaps(self):
        maps = dict(((t, n), recs) for t, n, _, recs in self.b["vmaps"])
        self.assertIn((b"WGHT", "R_Hand"), maps)
        self.assertIn((b"WGHT", "Thumb.L"), maps)
        self.assertIn((b"MORF", "Fist_Right"), maps)
        # UV names are not sides of the body - left alone.
        self.assertIn((b"TXUV", "L_UV"), maps)
        morph = maps[(b"MORF", "Fist_Right")][0][2]
        self.assertEqual(tuple(morph), struct.unpack(">3f", struct.pack(">3f", -0.25, -0.5, 0.1)))
        norm = maps[(b"NORM", "vnormals")][0][2]
        self.assertAlmostEqual(norm[0], -0.6, places=6)
        uv = [v for t, n, d, r in self.b["vmaps"] if d for v in r][0]
        self.assertEqual(uv[:2], (0, 0))
        self.assertAlmostEqual(uv[2][0], 0.9, places=6)

    def test_keep_names(self):
        out, stats = lwo_mirror.mirror_bytes(self.src, rename=False)
        names = [n for _, n, _, _ in lwo_mirror.read_layers(out)[0]["vmaps"]]
        self.assertIn("L_Hand", names)
        self.assertEqual(stats["renamed"], [])

    def test_extra_side_pairs(self):
        layer = lwo_build.hand_layer()
        layer["vmaps"] = [(b"WGHT", "Arm_Lf", 1, {0: (1.0,)})]
        out, _ = lwo_mirror.mirror_bytes(lwo_build.build([layer]),
                                         pairs=[("Lf", "Rt")])
        self.assertEqual(lwo_mirror.read_layers(out)[0]["vmaps"][0][1], "Arm_Rt")

    def test_mirror_twice_is_identity(self):
        again, _ = lwo_mirror.mirror_bytes(self.out)
        self.assertEqual(again, self.src)

    def test_surface_form_passes_through(self):
        _, chunks_a = lwo_mirror.split_chunks(self.src)
        _, chunks_b = lwo_mirror.split_chunks(self.out)
        surf_a = [p for c, p in chunks_a if c == b"FORM"]
        surf_b = [p for c, p in chunks_b if c == b"FORM"]
        self.assertEqual(surf_a, surf_b)
        self.assertEqual([c for c, _ in chunks_a], [c for c, _ in chunks_b])

    def test_rename_changes_chunk_size_cleanly(self):
        layer = lwo_build.hand_layer()
        layer["vmaps"] = [(b"WGHT", "Left_Arm", 1, {0: (1.0,)})]   # 8 -> 9 chars
        out, _ = lwo_mirror.mirror_bytes(lwo_build.build([layer]))
        self.assertEqual(lwo_mirror.read_layers(out)[0]["vmaps"][0][1], "Right_Arm")
        self.assertEqual(struct.unpack(">I", out[4:8])[0], len(out) - 8)

    def test_big_vx_indices(self):
        """Points past 65279 use 4-byte VX indices."""
        n = 0xFF10
        pts = [(1.0 + i * 1e-4, 0.0, float(i % 7)) for i in range(n)]
        layer = {"points": pts, "polys": [[0, n - 1, n - 2], [n - 3, 1, 2, 3]],
                 "vmaps": [(b"MORF", "m", 3, {n - 1: (1.0, 0.0, 0.0)})]}
        out, stats = lwo_mirror.mirror_bytes(lwo_build.build([layer]))
        b = lwo_mirror.read_layers(out)[0]
        self.assertEqual(b["polys"][0][1], [0, n - 2, n - 1])
        self.assertEqual(b["polys"][1][1], [n - 3, 3, 2, 1])
        self.assertEqual(b["vmaps"][0][3][0][0], n - 1)
        self.assertEqual(b["vmaps"][0][3][0][2][0], -1.0)

    def test_multi_layer(self):
        l1 = lwo_build.hand_layer()
        l2 = {"points": [(3.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0)],
              "polys": [[0, 1, 2]], "pivot": (-2.0, 0.0, 0.0)}
        out, stats = lwo_mirror.mirror_bytes(lwo_build.build([l1, l2]))
        layers = lwo_mirror.read_layers(out)
        self.assertEqual(stats["layers"], 2)
        self.assertEqual(layers[1]["points"][0][0], -3.0)
        self.assertEqual(layers[1]["pivot"][0], 2.0)

    def test_symmetry(self):
        self.assertFalse(lwo_mirror.is_point_symmetric(self.src))
        sym = {"points": [(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                          (0.0, 0.0, 2.0)],
               "polys": [[0, 1, 2]]}
        self.assertTrue(lwo_mirror.is_point_symmetric(lwo_build.build([sym])))
        sym["points"][1] = (1.0 + 1e-9, 0.0, 0.0)     # within tolerance
        self.assertTrue(lwo_mirror.is_point_symmetric(lwo_build.build([sym])))

    def test_rejects_garbage(self):
        self.assertRaises(lwo_mirror.LwoError, lwo_mirror.mirror_bytes, b"FORM\0\0\0\4ILBM")
        bad = bytearray(self.src)
        bad[4:8] = struct.pack(">I", len(bad))        # FORM claims 8 more bytes
        bad += b"PNTS\0\0\0\x30"                        # chunk past the end
        self.assertRaises(lwo_mirror.LwoError, lwo_mirror.mirror_bytes, bytes(bad))

    def test_cli(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "L_Hand.lwo")
        dst = os.path.join(tmp, "R_Hand.lwo")
        with open(src, "wb") as fh:
            fh.write(self.src)
        self.assertEqual(lwo_mirror.main([src, dst]), 0)
        with open(dst, "rb") as fh:
            self.assertEqual(fh.read(), self.out)


@unittest.skipUnless(SEEDS, "LWOFix seeds not found")
class RealFileTests(unittest.TestCase):

    def test_every_seed(self):
        for path in SEEDS:
            with open(path, "rb") as fh:
                data = fh.read()
            try:
                out, stats = lwo_mirror.mirror_bytes(data)
            except lwo_mirror.LwoError as exc:
                self.fail("%s: %s" % (os.path.basename(path), exc))
            # Involution: mirroring twice gives the file back exactly.
            again, _ = lwo_mirror.mirror_bytes(out)
            self.assertEqual(again, data[:8 + struct.unpack(">I", data[4:8])[0]],
                             os.path.basename(path))
            a = lwo_mirror.read_layers(data)
            b = lwo_mirror.read_layers(out)
            self.assertEqual(len(a), len(b))
            for la, lb in zip(a, b):
                self.assertEqual(len(la["points"]), len(lb["points"]))
                for p, q in zip(la["points"], lb["points"]):
                    self.assertEqual((-p[0], p[1], p[2]), tuple(q))


if __name__ == "__main__":
    unittest.main()
