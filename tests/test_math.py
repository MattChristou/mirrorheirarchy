# -*- coding: utf-8 -*-
"""mirror_math: rotation convention, the mirror rule, names."""

import math
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "plugin"))

import mirror_math as mm  # noqa: E402


def close(a, b, tol=1e-9):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def mat_close(a, b, tol=1e-9):
    return all(close(a[i], b[i], tol) for i in range(3))


def xform(pos, hpb):
    return mm.Xform(mm.hpb_to_matrix(*hpb), pos)


class RotationTests(unittest.TestCase):

    def test_forward_matches_lw(self):
        h, p, b = 0.3, -0.4, 0.7
        f = mm.column(mm.hpb_to_matrix(h, p, b), 2)
        self.assertTrue(close(f, (math.sin(h) * math.cos(p), -math.sin(p),
                                  math.cos(h) * math.cos(p))))

    def test_bank_from_right_and_up(self):
        r = mm.hpb_to_matrix(0.3, -0.4, 0.7)
        self.assertAlmostEqual(math.atan2(r[1][0], r[1][1]), 0.7)

    def test_round_trip(self):
        rnd = random.Random(4)
        for _ in range(200):
            hpb = (rnd.uniform(-3, 3), rnd.uniform(-1.5, 1.5), rnd.uniform(-3, 3))
            back = mm.matrix_to_hpb(mm.hpb_to_matrix(*hpb))
            self.assertTrue(mat_close(mm.hpb_to_matrix(*back), mm.hpb_to_matrix(*hpb)))
            self.assertTrue(close(back, hpb, 1e-7))

    def test_gimbal(self):
        r = mm.hpb_to_matrix(0.5, math.pi / 2, 0.2)
        self.assertTrue(mat_close(mm.hpb_to_matrix(*mm.matrix_to_hpb(r)), r, 1e-6))

    def test_mirror_rule_is_conjugation(self):
        """M.R(h,p,b).M == R(-h, p, -b): the channel rule."""
        rnd = random.Random(1)
        for _ in range(100):
            h, p, b = rnd.uniform(-3, 3), rnd.uniform(-1.5, 1.5), rnd.uniform(-3, 3)
            lhs = mm.mat_mul(mm.MIRROR_X, mm.mat_mul(mm.hpb_to_matrix(h, p, b), mm.MIRROR_X))
            self.assertTrue(mat_close(lhs, mm.hpb_to_matrix(-h, p, -b)))
            self.assertAlmostEqual(mm.det(lhs), 1.0)

    def test_chain_mirrors_in_world(self):
        """Channel rule on every link of a chain == world mirror M.W.M."""
        rnd = random.Random(2)
        links = [((rnd.uniform(-2, 2), rnd.uniform(-2, 2), rnd.uniform(-2, 2)),
                  (rnd.uniform(-3, 3), rnd.uniform(-1.5, 1.5), rnd.uniform(-3, 3)))
                 for _ in range(5)]
        world = mm.Xform()
        mirrored = mm.Xform()
        for pos, hpb in links:
            world = world * xform(pos, hpb)
            mpos, mhpb = mm.mirror_channel_rule(pos, hpb)
            mirrored = mirrored * xform(mpos, mhpb)
        want = mm.MIRROR * world * mm.MIRROR
        self.assertTrue(mat_close(mirrored.rot, want.rot))
        self.assertTrue(close(mirrored.pos, want.pos))

    def test_mirror_local_general(self):
        """Root under an asymmetric parent, mirrored about an arbitrary
        item, parented to a third item: world result is Mw.W.M."""
        rnd = random.Random(3)

        def rand_frame():
            return xform((rnd.uniform(-5, 5), rnd.uniform(-5, 5), rnd.uniform(-5, 5)),
                         (rnd.uniform(-3, 3), rnd.uniform(-1.5, 1.5), rnd.uniform(-3, 3)))
        for _ in range(50):
            parent, new_parent, plane = rand_frame(), rand_frame(), rand_frame()
            pos, hpb = (1.0, -2.0, 0.5), (0.4, 0.3, -1.1)
            mw = mm.mirror_about(plane)
            a = new_parent.inverse() * mw * parent
            npos, nhpb = mm.mirror_local(a, pos, hpb)
            got = new_parent * xform(npos, nhpb)
            want = mw * parent * xform(pos, hpb) * mm.MIRROR
            self.assertTrue(mat_close(got.rot, want.rot, 1e-8))
            self.assertTrue(close(got.pos, want.pos, 1e-8))
            self.assertAlmostEqual(mm.det(got.rot), 1.0)

    def test_plain_mirror_detection(self):
        self.assertTrue(mm.is_plain_mirror(mm.MIRROR))
        # Centred, unrotated (symmetric) parent: still the plain rule.
        p = xform((0.0, 3.0, 1.0), (0.0, 0.6, 0.0))
        self.assertTrue(mm.is_plain_mirror(p.inverse() * mm.MIRROR * p))
        q = xform((0.5, 3.0, 1.0), (0.0, 0.0, 0.0))
        self.assertFalse(mm.is_plain_mirror(q.inverse() * mm.MIRROR * q))
        r = xform((0.0, 0.0, 0.0), (0.3, 0.0, 0.0))
        self.assertFalse(mm.is_plain_mirror(r.inverse() * mm.MIRROR * r))

    def test_orthonormal_from_axes(self):
        r = mm.hpb_to_matrix(0.2, 0.5, -0.3)
        cols = [[2.0 * c for c in mm.column(r, j)] for j in range(3)]   # scaled
        self.assertTrue(mat_close(mm.orthonormal_from_axes(*cols), r, 1e-9))

    def test_unwrap(self):
        self.assertAlmostEqual(mm.unwrap(-3.0, 3.1), -3.0 + 2 * math.pi)
        ref = (3.0, 0.2, -3.0)
        got = mm.unwrap_hpb((-3.1, 0.2, 3.1), ref)
        self.assertTrue(mat_close(mm.hpb_to_matrix(*got), mm.hpb_to_matrix(-3.1, 0.2, 3.1)))
        self.assertTrue(all(abs(g - r) < 0.5 for g, r in zip(got, ref)))

    def test_value_params(self):
        self.assertEqual(mm.value_params(1), (0, 1))
        self.assertEqual(mm.value_params(5), (1, 3))
        self.assertEqual(mm.value_params(0), ())


class NameTests(unittest.TestCase):

    def test_names(self):
        cases = {
            "L_Arm": "R_Arm", "Arm_R": "Arm_L", "arm.l": "arm.r",
            "Arm_L_Upper": "Arm_R_Upper", "arm_L0_fk0": "arm_R0_fk0",
            "LeftHand": "RightHand", "left_foot": "right_foot",
            "RIGHT_EYE": "LEFT_EYE", "Head": None, "Lamp": None, "Clavicle": None,
        }
        for name, want in cases.items():
            self.assertEqual(mm.mirror_name(name), want, name)

    def test_pairs_first(self):
        pairs = mm.parse_side_names("Lf/Rt, lft:rgt bogus")
        self.assertEqual(pairs, [("Lf", "Rt"), ("lft", "rgt")])
        self.assertEqual(mm.mirror_name("Arm_Rt", pairs), "Arm_Lf")

    def test_base_item_name(self):
        self.assertEqual(mm.base_item_name("Arm (12)"), "Arm")
        self.assertEqual(mm.base_item_name("Arm"), "Arm")

    def test_file_candidates(self):
        it = mm.mirrored_file_candidates(os.path.join("x", "L_Hand.lwo"))
        self.assertEqual([next(it) for _ in range(3)],
                         [os.path.join("x", n) for n in
                          ("R_Hand.lwo", "L_Hand_mirror.lwo", "L_Hand_mirror2.lwo")])
        it = mm.mirrored_file_candidates("Rock.lwo")
        self.assertEqual(next(it), "Rock_mirror.lwo")


if __name__ == "__main__":
    unittest.main()
