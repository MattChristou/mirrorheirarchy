# Changelog

## Unreleased

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
