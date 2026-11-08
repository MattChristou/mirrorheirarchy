# Changelog

## Unreleased

### 0.2.0 (2026-11-08): Update mode, node-graph map names, languages. Not yet tested in Layout

- **Update the existing other side** (new Mode setting).
  - **Problem:** every run made new clones, so after editing the left side the only way to sync was to delete the right side and mirror again, losing anything that pointed at it.
  - **Change:** the mode finds the other side by name. It copies and mirrors the keys (curve shape, tangents, pre/post behaviour), pivots, bone rests, weight-map names and links. It rewrites the other side's mesh file only when this plug-in wrote it and nobody has edited it since (`%APPDATA%\MirrorHierarchy\written.json`).
- **Map names inside surfaces.**
  - **Problem:** a renamed weight map left LWO3 node graphs (such as a Weight Map node) still asking for the old name.
  - **Change:** leaf chunks holding exactly a renamed map name now follow the rename, and every enclosing chunk size is rewritten. Node names and connections are never touched. References the plug-in can't edit (LWO2 surfaces, non-IFF node data) are reported instead.
- **Channel modifiers / expressions** on mirrored channels are reported, because their output isn't mirrored.
- **Pivots and bone rests** are now set whenever they differ from the mirrored value, not only when the original's value is non-zero. Update mode needs this.
- **Languages:** the panel, popups and dialogs use LightWave l10n resource tags (context `MirrorHierarchy`). Ships an English key list and a Japanese translation in `l10n/jp/`.
- The "World (X = 0)" label became "World (YZ plane)", because resource keys can't contain `=`.

### 0.1.0 (2026-11-08): first version, not yet tested in Layout

- New Layout Python plug-in that replaces the stock LScript `mirrorhierarchy.ls` for mirroring across X.
- **What was wrong with the stock script:**
  - It mirrors through a parent scaled to -1. Clones keep that negative scale, and LightWave doesn't reverse the polygon winding to match, so meshes render inside out and bones and IK misbehave.
  - It keys frame 0 only.
  - It inserts a "Hierarchy" null above your original.
- **What this version does instead:**
  - Writes a mirrored copy of each mesh object, with X negated and the winding reversed, and loads it with `ReplaceWithObject`.
  - Negates Position.X, Heading and Bank on every key of every clone, value tangents included. Pivots and bone rests get the same rule.
  - Solves the top item in world space when its new parent isn't a mirror image of its old one.
  - Re-points IK goals, targets, poles and Same-As-Item links.
  - Swaps Left/Right in names and weight maps.
  - Checks every clone's world transform after the run.
- `mirrorhierarchy_x.ls`, an earlier attempt at a fix sitting in `scripts/LScript/utility/generic`, doesn't run. It calls LScript functions that don't exist and has the wrong rotation maths. This plug-in supersedes it.
