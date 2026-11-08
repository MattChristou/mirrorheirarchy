# -*- coding: utf-8 -*-
"""mirrorhierarchy_core end to end against fake_layout."""

import math
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fake_layout as fl  # noqa: E402  (installs lwsdk first)
import lwo_build  # noqa: E402
import lwo_mirror  # noqa: E402
import mirror_math as mm  # noqa: E402
import mirrorhierarchy_core as core  # noqa: E402

lwsdk = fl.lwsdk


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class RigTest(unittest.TestCase):
    """Chest (centre) > L_Arm (mesh object with bones) > L_Hand (null, pivot).
    L_Goal / R_Goal sit under Chest; L_Lower's IK goal is L_Goal."""

    chest_pos = (0.0, 5.0, 0.0)
    chest_hpb = (0.0, 0.3, 0.0)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        os.environ["APPDATA"] = self.tmp            # prefs + written-files manifest
        self.arm_file = os.path.join(self.tmp, "L_Arm.lwo")
        with open(self.arm_file, "wb") as fh:
            fh.write(lwo_build.build([lwo_build.hand_layer()]))
        s = self.s = fl.reset()
        O, B = lwsdk.LWI_OBJECT, lwsdk.LWI_BONE
        self.chest = s.add(O, "Chest", pos=self.chest_pos, hpb=self.chest_hpb)
        self.arm = s.add(O, "L_Arm", self.chest, pos=(1.0, 0.5, 0.2), hpb=(0.4, 0.2, 0.1))
        self.arm.filename, self.arm.points = self.arm_file, 8
        self.arm.pivot = [1.5, 0.5, 0.0]
        self.arm.set_local(1.0, (2.0, 0.5, 0.2), (0.9, -0.2, 0.5))
        for c in ("Position.X", "Rotation.H"):              # Hermite / 2D Bezier keys
            k = self.arm.envs[c].keys[0]
            k.shape, k.params = (1, [0.25, -0.5, 0.0, 0.0]) if c == "Position.X" else \
                (5, [-0.1, 0.3, 0.1, 0.7])
        self.hand = s.add(O, "L_Hand", self.arm, pos=(0.0, 0.0, 1.0), hpb=(0.0, 0.0, 0.6))
        self.hand.pivot, self.hand.pivot_rot = [0.2, 0.0, 0.0], [0.3, 0.1, 0.2]
        self.upper = s.add_bone(self.arm, "L_Upper", pos=(0.1, 0.0, 0.0), hpb=(0.5, 0.0, 0.0))
        self.lower = s.add_bone(self.arm, "L_Lower", self.upper, pos=(0.0, 0.0, 1.0),
                                hpb=(0.2, 0.1, 0.0))
        self.upper.rest_pos, self.upper.rest_rot = [0.1, 0.0, 0.0], [0.5, 0.0, 0.25]
        self.upper.weight_map = "L_Hand"
        self.goal = s.add(O, "L_Goal", self.chest, pos=(1.0, -2.0, 0.0))
        self.rgoal = s.add(O, "R_Goal", self.chest, pos=(-1.0, -2.0, 0.0))
        self.lower.links["GoalItem"] = self.goal
        self.hand.links["RotationItem"] = self.arm          # inside: goes to the clone
        self.settings = dict(core.SETTINGS, plane=core.PLANE_WORLD,
                             parent=core.PARENT_OTHER_SIDE, rename=1, sides="",
                             mesh=core.MESH_MIRRORED, reuse_symmetric=1)
        core.ANGLE_SCALE.clear()

    def run_core(self, select=None, **kw):
        self.s.selected = select or [self.arm]
        settings = dict(self.settings, **kw)
        return core.run(settings)

    def assert_world_mirror(self, orig, clone, t, mw=mm.MIRROR):
        want = mw * orig.world(t) * mm.MIRROR
        got = clone.world(t)
        self.assertTrue(close(got.pos, want.pos), (clone.name, t, got.pos, want.pos))
        for i in range(3):
            self.assertTrue(close(got.rot[i], want.rot[i]), (clone.name, t))
        self.assertAlmostEqual(mm.det(got.rot), 1.0)

    def test_full_rig(self):
        report = self.run_core()
        self.assertEqual(report.warnings, [])
        s = self.s
        r_arm = s.named("R_Arm")
        r_hand = s.named("R_Hand")
        r_upper = [b for b in s.items if b.name == "R_Upper"][0]
        r_lower = [b for b in s.items if b.name == "R_Lower"][0]
        # Structure
        self.assertIs(r_arm.parent, self.chest)
        self.assertIs(r_hand.parent, r_arm)
        self.assertIs(r_upper.owner, r_arm)
        self.assertIs(r_lower.parent, r_upper)
        # World mirror at both key times, every item
        for t in (0.0, 0.5, 1.0):
            for o, c in ((self.arm, r_arm), (self.hand, r_hand),
                         (self.upper, r_upper), (self.lower, r_lower)):
                self.assert_world_mirror(o, c, t)
        # Mesh: mirrored file, pivot from the ORIGINAL (not doubly negated)
        self.assertEqual(os.path.basename(r_arm.filename), "R_Arm.lwo")
        with open(r_arm.filename, "rb") as fh:
            with open(self.arm_file, "rb") as src:
                self.assertEqual(fh.read(), lwo_mirror.mirror_bytes(src.read())[0])
        self.assertEqual(r_arm.pivot, [-1.5, 0.5, 0.0])
        # Pivot rotation took on the second (degrees) try
        self.assertTrue(close(r_hand.pivot_rot, (-0.3, 0.1, -0.2)))
        self.assertEqual(r_hand.pivot, [-0.2, 0.0, 0.0])
        self.assertEqual(core.ANGLE_SCALE["PivotRotation"], 180.0 / math.pi)
        # Bones
        self.assertEqual(r_upper.rest_pos, [-0.1, 0.0, 0.0])
        self.assertTrue(close(r_upper.rest_rot, (-0.5, 0.0, -0.25)))
        self.assertEqual(r_upper.weight_map, "R_Hand")
        # Tangents negated with the values
        kx = r_arm.envs["Position.X"].keys[0]
        self.assertEqual(kx.params[:2], [-0.25, 0.5])
        kh = r_arm.envs["Rotation.H"].keys[0]
        self.assertEqual(kh.params, [-0.1, -0.3, 0.1, -0.7])
        # Links
        self.assertIs(r_lower.links["GoalItem"], self.rgoal)
        self.assertIs(r_hand.links["RotationItem"], r_arm)
        # Originals untouched, PIP restored, clone selected
        self.assertEqual(self.arm.name, "L_Arm")
        self.assertEqual(self.arm.envs["Position.X"].keys[0].value, 1.0)
        self.assertTrue(self.s.flags & lwsdk.LWGENF_PARENTINPLACE)
        self.assertEqual(self.s.selected, [r_arm])
        self.assertTrue(any("World check passed" in l for l in report.lines))

    def test_offset_parent_is_solved_in_world(self):
        """Chest off-centre and turned: the top clone needs the world solve."""
        self.chest.set_local(0.0, (0.7, 5.0, -0.3), (0.5, 0.2, 0.1))
        report = self.run_core()
        r_arm = self.s.named("R_Arm")
        self.assertIs(r_arm.parent, self.chest)
        self.assertTrue(any("solved in world space" in l for l in report.lines))
        for t in (0.0, 1.0):
            self.assert_world_mirror(self.arm, r_arm, t)
            self.assert_world_mirror(self.hand, self.s.named("R_Hand"), t)
        self.assertEqual(report.warnings, [])

    def test_other_side_parent(self):
        """L_Arm under L_Clavicle: the clone goes under R_Clavicle."""
        lc = self.s.add(lwsdk.LWI_OBJECT, "L_Clavicle", self.chest, pos=(0.5, 0, 0),
                        hpb=(0.2, 0, 0.1))
        rc = self.s.add(lwsdk.LWI_OBJECT, "R_Clavicle", self.chest, pos=(-0.5, 0, 0),
                        hpb=(-0.2, 0, -0.1))
        self.arm.parent = lc
        report = self.run_core()
        r_arm = self.s.named("R_Arm")
        self.assertIs(r_arm.parent, rc)
        self.assertFalse(any("solved" in l for l in report.lines))   # plain rule exact
        self.assert_world_mirror(self.arm, r_arm, 1.0)

    def test_parent_nothing_and_plane_item(self):
        report = self.run_core(parent=core.PARENT_NONE, plane=core.PLANE_PARENT)
        r_arm = self.s.named("R_Arm")
        self.assertIsNone(r_arm.parent)
        mw = mm.mirror_about(self.chest.world(0.0))
        self.assert_world_mirror(self.arm, r_arm, 0.0, mw)
        self.assertEqual(report.warnings, [])

    def test_symmetric_mesh_keeps_file(self):
        sym = {"points": [(-1.0, 0, 0), (1.0, 0, 0), (0, 1.0, 0)], "polys": [[0, 1, 2]]}
        with open(self.arm_file, "wb") as fh:
            fh.write(lwo_build.build([sym]))
        self.arm.points = 3
        self.run_core()
        clone = [i for i in self.s.items if i.type == lwsdk.LWI_OBJECT
                 and i is not self.arm and i.filename == self.arm_file]
        self.assertEqual(len(clone), 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "R_Arm.lwo")))

    def test_never_overwrites_someone_elses_file(self):
        theirs = os.path.join(self.tmp, "R_Arm.lwo")
        with open(theirs, "wb") as fh:
            fh.write(b"hand made right arm")
        self.run_core()
        with open(theirs, "rb") as fh:
            self.assertEqual(fh.read(), b"hand made right arm")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "L_Arm_mirror.lwo")))
        # Run again: the identical mirrored copy is reused, not duplicated.
        self.run_core()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "L_Arm_mirror2.lwo")))

    def test_bone_chain_inside_one_object(self):
        """Mirror just the L_Upper bone chain within its own object."""
        self.arm.envs["Position.X"].keys[0].value = 0.0
        report = self.run_core(select=[self.upper])
        r_upper = [b for b in self.s.items if b.name == "R_Upper"]
        self.assertEqual(len(r_upper), 1)
        r_upper = r_upper[0]
        self.assertIs(r_upper.owner, self.arm)
        self.assertIs(r_upper.parent, self.arm)
        r_lower = [b for b in self.s.items if b.name == "R_Lower"][0]
        self.assertIs(r_lower.parent, r_upper)
        self.assertEqual(r_upper.weight_map, "R_Hand")
        # Object is not symmetric about its own centre -> world solve
        self.assertTrue(any("solved" in l for l in report.lines), report.lines)
        self.assert_world_mirror(self.upper, r_upper, 0.0)

    def test_no_rename(self):
        self.run_core(rename=0)
        names = [i.name for i in self.s.items]
        self.assertIn("L_Hand (1)", names)
        self.assertNotIn("R_Hand", names)

    def test_two_roots(self):
        other = self.s.add(lwsdk.LWI_LIGHT, "Left_Lamp", self.chest, pos=(2, 0, 0))
        self.run_core(select=[self.arm, self.hand, other])   # hand is under arm
        self.assertEqual(len([i for i in self.s.items if i.name == "R_Hand"]), 1)
        lamp = self.s.named("Right_Lamp")
        self.assertEqual(len(self.s.selected), 2)
        self.assert_world_mirror(other, lamp, 0.0)

    # ---------- Update mode ----------

    def update(self, select=None, **kw):
        return self.run_core(select=select, mode=core.MODE_UPDATE, **kw)

    def test_update_follows_new_animation(self):
        self.run_core()
        count = len(self.s.items)
        r_arm, r_hand = self.s.named("R_Arm"), self.s.named("R_Hand")
        # Animate the left side further, then update.
        self.arm.set_local(2.0, (1.5, 1.0, -0.4), (-0.3, 0.6, 0.2))
        self.hand.set_local(2.0, (0.0, 0.5, 1.0), (0.4, 0.0, -0.6))
        report = self.update()
        self.assertEqual(report.warnings, [])
        self.assertEqual(len(self.s.items), count)          # nothing new
        self.assertIs(self.s.named("R_Arm"), r_arm)
        self.assertEqual(report.items, 4)                    # arm, hand, 2 bones
        for t in (0.0, 1.0, 1.5, 2.0):
            self.assert_world_mirror(self.arm, r_arm, t)
            self.assert_world_mirror(self.hand, r_hand, t)
        self.assertEqual(self.s.selected, [r_arm])

    def test_update_is_repeatable(self):
        self.run_core()
        self.update()
        r_arm = self.s.named("R_Arm")
        snap = [(k.time, k.value) for k in r_arm.envs["Rotation.H"].keys]
        self.update()
        self.assertEqual([(k.time, k.value) for k in r_arm.envs["Rotation.H"].keys], snap)

    def test_update_copies_curve_shape_and_behaviour(self):
        self.run_core()
        env = self.arm.envs["Position.X"]
        env.keys[1].shape, env.keys[1].params = 1, [0.3, 0.4, 0.0, 0.0]
        env.behave[2] = 3                                     # post: repeat
        self.update()
        r = self.s.named("R_Arm").envs["Position.X"]
        self.assertEqual(r.keys[1].shape, 1)
        self.assertEqual(r.keys[1].params[:2], [-0.3, -0.4])
        self.assertEqual(r.behave[2], 3)

    def test_update_bone_rest_and_pivot(self):
        self.run_core()
        self.upper.rest_pos, self.upper.rest_rot = [0.3, 0.1, 0.0], [0.2, 0.1, 0.05]
        self.hand.pivot = [0.5, 0.1, 0.0]
        self.update()
        r_upper = [b for b in self.s.items if b.name == "R_Upper"][0]
        self.assertEqual(r_upper.rest_pos, [-0.3, 0.1, 0.0])
        self.assertTrue(close(r_upper.rest_rot, (-0.2, 0.1, -0.05)))
        self.assertEqual(self.s.named("R_Hand").pivot, [-0.5, 0.1, 0.0])

    def _edit_left_mesh(self):
        layer = lwo_build.hand_layer()
        layer["points"] = [(p[0] + 0.25, p[1], p[2]) for p in layer["points"]]
        with open(self.arm_file, "wb") as fh:
            fh.write(lwo_build.build([layer]))

    def test_update_rewrites_our_mesh_file(self):
        self.run_core()
        r_file = os.path.join(self.tmp, "R_Arm.lwo")
        self._edit_left_mesh()
        report = self.update()
        with open(r_file, "rb") as fh, open(self.arm_file, "rb") as src:
            self.assertEqual(fh.read(), lwo_mirror.mirror_bytes(src.read())[0])
        self.assertTrue(any("rewritten" in l for l in report.lines))
        self.assertEqual(self.s.commands.count("ReplaceWithObject " + r_file), 2)

    def test_update_never_touches_an_edited_mesh_file(self):
        self.run_core()
        r_file = os.path.join(self.tmp, "R_Arm.lwo")
        layer = lwo_build.hand_layer()                       # someone edits it
        layer["points"][0] = (5.0, 5.0, 5.0)
        mine = lwo_build.build([layer])
        with open(r_file, "wb") as fh:
            fh.write(mine)
        self._edit_left_mesh()
        report = self.update()
        with open(r_file, "rb") as fh:
            self.assertEqual(fh.read(), mine)
        self.assertTrue(any("left alone" in l for l in report.lines))

    def test_update_needs_the_other_side(self):
        report = self.update()
        self.assertTrue(any("no other-side item" in w for w in report.warnings))
        self.assertEqual(report.created, [])
        self.assertFalse(any(i.name.startswith("R_") and i.name != "R_Goal"
                             for i in self.s.items))

    def test_update_skips_unmatched_child(self):
        self.run_core()
        extra = self.s.add(lwsdk.LWI_OBJECT, "L_Finger", self.hand, pos=(0, 0, 0.5))
        report = self.update()
        self.assertTrue(any("L_Finger" in w and "skipped" in w for w in report.warnings))
        self.assert_world_mirror(self.hand, self.s.named("R_Hand"), 0.0)

    def test_update_centre_named_child(self):
        """Children without a side in the name match by the same name."""
        self.s.add(lwsdk.LWI_OBJECT, "Tip", self.hand, pos=(0.0, 0.2, 0.5))
        self.run_core()
        tips = [i for i in self.s.items if mm.base_item_name(i.name) == "Tip"]
        self.assertEqual(len(tips), 2)
        orig = tips[0]
        orig.set_local(0.0, (0.1, 0.3, 0.6), (0.2, 0.0, 0.0))
        self.update()
        self.assert_world_mirror(orig, tips[1], 0.0)

    def test_modifier_warning(self):
        self.arm.envs["Rotation.H"].modifiers = ["LW_Expression"]
        report = self.run_core()
        self.assertTrue(any("LW_Expression" in w for w in report.warnings))

    def test_nothing_selected(self):
        self.s.selected = []
        report = core.run(self.settings)
        self.assertTrue(report.warnings)
        self.assertEqual(report.created, [])


if __name__ == "__main__":
    unittest.main()
