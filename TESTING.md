# Layout tests: Mirror Hierarchy (Clean)

Run these in Layout 2025.

1. Make the test objects: `python -B tools/make_test_objects.py`. This writes `C:/tmp/MirrorHierarchy/L_Hand.lwo` and `Sym_Head.lwo`.
2. Add `plugin/MirrorHierarchy.py` with Utilities › Add Plugins.
3. Open the Python console (Utilities › Python › Console) before running anything. The plug-in reports to it, and any errors also go to `%TEMP%\MirrorHierarchy_error.log`.

Record results under each test: pass/fail, and what the console printed.

## Facts the code assumes about Layout

The tests below check these. The code guards each one, but say what you saw.

| # | Assumption | How the code copes if it's wrong |
|---|---|---|
| A1 | `Clone 1` on a mesh object also clones its bones, keeping their names. | The console warns "also made …" for anything it can't match. |
| A2 | A cloned item stays under the original's parent. | It's re-parented anyway. |
| A3 | `ReplaceWithObject <path>` with an unquoted path containing spaces works, and keeps the item's bones. | A warning if the file didn't change. |
| A4 | `PivotRotation` and `BoneRestRotation` take radians or degrees. | Checked by reading back; the console prints "… takes radians/degrees". |
| A5 | `ParentItem` with no argument unparents the single selected item. | |
| A6 | `Rename` works on nulls. | |
| A7 | `LWObjectInfo.layerLoaded()` gives the layer number for `ReplaceObjectLayer`. | Tried n and n+1; checked by point count. |

## T1: mesh winding (the main point)

1. Load `C:/tmp/MirrorHierarchy/L_Hand.lwo`. It's a slab at X 1..2 with a thumb sticking out toward +Z and a bump on top.
2. Select it and run **Mirror Hierarchy (Clean)** with the defaults.

Expect:
- `C:/tmp/MirrorHierarchy/R_Hand.lwo` is written.
- A new item **R_Hand** is the mirror image of L_Hand across world X = 0. If L_Hand shows at X 1..2, R_Hand shows at X -2..-1.
- Shading looks right (not inside out). Compare it with the original in a Textured Shaded viewport, and with backface culling on if your viewport has it.
- The clone's Scale channels are 1, 1, 1 (no negative scale), and its pivot is at (-1, 0.25, 0.5).
- The console reports "World check passed".

For contrast (optional): run the stock Setup › Mirror Hierarchy on the same object. Its clone should look inside out.

## T2: hierarchy and animation

1. Add a null **Chest** at (0, 5, 0).
2. Add a null **L_Arm** under Chest at (1, 0, 0). Key frame 0 with H 30°, then frame 30 at a different position, H -20° and B 15°.
3. Parent L_Hand under L_Arm.
4. Select L_Arm and run.

Expect:
- New nulls **R_Arm** under Chest, and R_Hand under R_Arm.
- Scrubbing frames 0 to 30, the right side mirrors the left on every frame, not just frame 0.
- Parent In Place is in the same state as before the run.

## T3: offset parent (world solve)

Same as T2, but first move Chest to X = 0.5 and give it H 20°. Delete the T2 clones before running.

Expect:
- The console prints "top item solved in world space at N key time(s)" and "World check passed".
- R_Arm is the mirror image of L_Arm across world X = 0.

## T4: bones in a cloned object

1. Give L_Hand one bone **L_Wrist**. Set its weight map to `L_Hand`, turn on Weight Map Only, and make it active.
2. Rotate it to check that it bends the hand.
3. Mirror L_Hand.

Expect:
- R_Hand has a bone **R_Wrist** with weight map `R_Hand`. That map exists in `R_Hand.lwo`.
- Rotating R_Wrist's heading the opposite way to L_Wrist bends R_Hand as the mirror image.
- The console says whether BoneRestRotation takes radians or degrees (A4).

## T5: bones inside one object

In one object, make a left bone chain **L_Upper › L_Lower** with a weight map, plus the matching right-side weight map in the mesh. Select L_Upper and run.

Expect:
- **R_Upper › R_Lower** appear in the same object, mirrored.
- Their weight maps are swapped to the R names.

## T6: IK links

1. Add nulls **L_Goal** and **R_Goal**.
2. Set L_Lower's IK goal to L_Goal.
3. Mirror the chain.

Expect: R_Lower's goal is R_Goal.

## T7: symmetric mesh, and re-runs

- Mirror `Sym_Head.lwo` on its own, placed at X = 1. Expect: the clone keeps `Sym_Head.lwo` (the console says it's symmetric) and sits at X = -1.
- Run T1 again. Expect: no `L_Hand_mirror.lwo`, because the identical `R_Hand.lwo` is reused.
- Put any other file named `R_Hand.lwo` in place and run T1. Expect: that file is left alone, and the copy goes to `L_Hand_mirror.lwo`.

## T8: your own rig

Mirror a real left limb from one of your rigs and report anything the world check flags.
