---
name: rig-motion-check
description: Checks a rigged or animated .glb by numbers: lists bones and clips, then follows a foot or hand bone through each clip and reports height above the floor, sliding while planted, sinking and scale drift, with a per-sample table. Use when a character's feet slide or sink, an animation looks wrong, or a rigged model came from a generator or export. Not for file structure or budget checks (use gltf-gate).
license: MIT
metadata:
  pack: 3d
  version: 0.3.1
  needs: python3
---

# Rig motion check

Produces a per-clip table of one bone's world position at every key and sample time, with a pass or fail for contact, sliding, sinking and scale.

## Done when

- `motion.py list` showed the bones and clips, and the bone to follow was named from that list.
- `motion.py check` ran on every clip that matters, with the floor height stated.
- Each failing clip is named with the time and the number that failed.
- The reply repeats what the script says it cannot compute.

End in exactly one state: **pass**, **fail** (quote the failing line), **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| a .glb or .gltf with skins or animations | `python3 scripts/motion.py list <file>` | not verified: nothing to check |

## Steps

The script is `scripts/motion.py` in this skill's folder (`"${CLAUDE_SKILL_DIR}/scripts/motion.py"` in Claude Code).

1. **List.**
   ```
   python3 scripts/motion.py list <file>
   ```
   Bones that look like feet or hands are marked. Ask the user which one plants on the floor if it is not clear.
2. **Decide the floor.** By default the floor is the bone's rest-pose height, which assumes the rest pose stands on the floor. If that is not true, pass `--floor <metres>`. A walk cycle made to stay on the spot needs `--in-place`.
3. **Check.**
   ```
   python3 scripts/motion.py check <file> --joint <bone> [--clip <name>] [--floor 0] [--json-out <new file>]
   ```
4. **Read the table.** Look at the rows around each change of state (air to contact), and the worst slide.
5. **Report.** End state first, then one line per clip, then the not-computed list.

## Rules

- This follows bone origins by forward kinematics. It does not deform the mesh. A sole can still cut the floor when the bone does not: say so.
- Limits in `references/motion_thresholds.json` are unverified working values; scale them to the character's size.
- A clip that never touches the floor is not verified, not a pass. Check `--floor` first.
- Do not change the animation to make a check pass. Report, then fix in the source tool.

## Not for

- File structure, budgets and renders → use `gltf-gate`.
- Doing the fix in Blender → use `blender-task`.

## Level

- beginner: explain rest pose, contact and why sliding shows as "moonwalking".
- standard: as written.
- expert: the per-clip verdict lines only. Every check still runs.
