# Mirror Hierarchy (Clean)

A Layout Python plug-in that clones item hierarchies and mirrors them across X **without negative scale**.

## Why not the stock Mirror Hierarchy?

LightWave's `mirrorhierarchy.ls` mirrors by scaling a temporary parent to -1 in X and unparenting the clone with Parent In Place on. This has three problems:

- The clone keeps a negative scale. LightWave doesn't reverse polygon winding for a mirrored transform, so a negative-scaled mesh renders inside out. Its children inherit the flip, and bones and IK misbehave.
- Only the current frame is mirrored. Other keys stay unmirrored.
- If the selected top item isn't a null, the script inserts a "Hierarchy" null above your original.

This plug-in does the mirror in two halves that cancel out:

| Part | What changes |
|---|---|
| The mesh | A copy of the object file: every point's X negated **and** every polygon's winding reversed (`lwo_mirror.py`) |
| Every item | Position.X, Heading and Bank negated on every key, tangents too. The same rule applies to pivot position/rotation and bone rest position/rotation. |

**Why they cancel.** Write `M` for the X mirror, `W` for an item's world transform and `G` for its mesh points. The mesh copy holds `M·G`. The rule on the channels makes the world transform `M·W·M`, which is still a plain rotation. So the clone's points sit at `M·W·M·M·G = M·W·G`, the exact mirror image, with no negative scale anywhere.

Special cases:

- **Top item of each hierarchy.** If its new parent is the mirror image of its old one (a centred parent, or `L_Clavicle` → `R_Clavicle`), the channel rule is exact. Otherwise its keys are solved in world space at each key time.
- **World check.** After a run, every clone's world position and axes are compared with the mirror image of the original's, and the result is printed.

## Install

In Layout, use Utilities › Add Plugins and add `plugin/MirrorHierarchy.py`. Keep the other three files in `plugin/` beside it. They're helper modules that LightWave skips because they have no version marker. For another language, also copy the matching `l10n` file (see Languages).

Two commands appear under Utilities › Python:

- **Mirror Hierarchy (Clean)**: opens the panel, then mirrors.
- **Mirror Hierarchy Again** (`MC_MirrorHierarchyAgain`): mirrors with the last settings. Bind it to a key if you like.

Save the scene first. The operation is many Layout commands and can't be undone in one step.

## Panel

| Setting | |
|---|---|
| Mode | **Create mirrored clones**, or **Update the existing other side** (see below). |
| Mirror across | World (the YZ plane at X = 0); the top item of the hierarchy (its YZ plane); or the selection's parent. |
| Parent clone to | The other side of the original's parent, found by name (falls back to the original's parent); the original's parent; or nothing (a bone goes to its object). |
| Meshes | Write a mirrored copy, or keep the original mesh. |
| Keep file if symmetric | A mesh symmetric about its own X = 0, with no left/right map names, keeps its file. |
| Swap Left/Right in names | Item names, bone weight-map names, and WGHT/MORF/SPOT/PICK map names in the mirrored file. |
| Extra side pairs | Your own pairs on top of Left/Right and L/R, e.g. `Lf/Rt, lft/rgt`. |

Mirrored files go next to the original:

- The name tries the other side first (`L_Hand.lwo` → `R_Hand.lwo`), then `<name>_mirror.lwo`, `_mirror2`, and so on.
- An existing file is never overwritten unless it's byte-identical to the new copy.
- Mesh objects are named after their file. Nulls, lights, cameras and bones are renamed.

## Update mode

Build the left side, mirror it once with **Create**, then keep working on the left. Select the left top item again and run with **Update the existing other side**:

- **Finding the other side.** The top item's partner is found by name (`L_Arm` → `R_Arm`). Each child is matched under its parent's partner, by its other-side name, or by the same name when the name has no side (`Finger1`).
- **Animation.** The partner's motion channels become a copy of the original's keys, with curve shapes, tangents and pre/post behaviour, and then get the mirror rule. Keys the right side had are replaced.
- **Pivots, bone rests, bone weight-map names and IK / Same-As-Item links** are set from the left side.
- **Meshes.** The right side's object file is rewritten **only** if this plug-in wrote it and it hasn't changed since. A hand-made or edited right-side mesh is left alone, and the console says so. Files the plug-in has written are recorded with a hash in `%APPDATA%\MirrorHierarchy\written.json`.
- **Nothing is created or renamed.** Items with no match on the other side are skipped and listed.

## Map names inside surfaces

When the mirrored file renames a weight map (`L_Hand` → `R_Hand`), LWO3 surface node graphs that use it follow the rename. That covers, for example, a Weight Map node's map name (`NDTA/NAME`). Node names and connections are never touched, even when a node happens to share a map's name.

If a renamed name still turns up somewhere the plug-in can't edit safely (an LWO2 surface, or a third-party node that doesn't store its data as IFF), the console names it so you can check it. Expressions and other channel modifiers on mirrored channels are reported the same way, because their output isn't mirrored.

## Languages

Everything shown in Layout (panel, popups, dialogs) uses LightWave's l10n resource tags, context `MirrorHierarchy`. Console messages stay in English, because the console would print the raw tags.

- To translate: copy `l10n/<locale>/MirrorHierarchy.resource` into `<LightWave>/support/l10n/<locale>/`.
- Japanese is in `l10n/jp/`. It's a machine draft; a native speaker should review it.
- `l10n/MirrorHierarchy.resource` is the English key list to start other languages from. LightWave's locale codes are `de`, `en_GB`, `sp`, `fr`, `it`, `jp`, `ko`, `ru`, `sw` and `zh_Hans`.
- Without a resource file, the English key text is shown.

A test checks that every tagged string has an entry in every language file.

## What the mirrored object file gets

| Chunk | Change |
|---|---|
| PNTS | X negated |
| POLS FACE / PTCH / SUBD | Winding reversed; vertex 0 stays first |
| POLS BONE, CURV, MBAL, PTCL | Untouched. Reversing a skelegon would flip it. |
| VMAP / VMAD MORF, SPOT, NORM | X negated |
| WGHT, MORF, SPOT, PICK names | Left ↔ right |
| BBOX | X bounds negated and swapped |
| LAYR pivot | X negated |
| Surface node graphs (LWO3) | References to renamed maps follow the rename |

Everything else is copied byte for byte: surfaces and node graphs, image clips, envelopes, and unknown chunks. Point and polygon order never change. LWO2 and LWO3 are both handled.

`lwo_mirror.py` also works on its own from the command line:

```
python plugin/lwo_mirror.py in.lwo out.lwo [--sides "Lf/Rt"] [--keep-names]
```

## Limits

- Channel modifiers and expressions on the mirrored channels aren't mirrored. The world check names any item they move.
- The world solve for a top item assumes rigid parents (no non-uniform scale) and reads parents' keyed motion at key times.
- Procedural textures in object space are sampled at mirrored coordinates, so an asymmetric procedural won't look mirrored. Image maps follow the UVs, so text in a texture reads backwards, as a mirror should.

## Tests

```
python -B tests/run_all.py
"<LW>/support/modules/MSWIN/x86_64/Python-2.7.18/python.exe" -B tests/run_all.py
```

Always pass `-B`: a stray `.pyc` in `plugin/` would be scanned by LightWave, and a test checks for that.

| File | Covers |
|---|---|
| `tests/test_math.py` | Rotation convention, mirror rule, world solve, names |
| `tests/test_lwo_mirror.py` | Geometry, winding (mirrored normals), vmaps, renames, 4-byte indices, multi-layer files. It also mirrors every real object in `../LWOFix/tests/seeds` twice and expects the file back byte for byte. |
| `tests/test_core.py` | End to end against `tests/fake_layout.py`, a model of Layout built on stated assumptions. Layout itself is checked by hand with [TESTING.md](TESTING.md). |
| `tests/test_plugin_files.py` | Plug-in container rules: version marker only in the entry file, parses under LightWave's Python 2.7. |
| `tests/test_l10n.py` | Every tagged string is in every resource file; keys are legal; file header and encoding |

`tools/make_test_objects.py` writes the Layout test objects to `C:/tmp/MirrorHierarchy`.
