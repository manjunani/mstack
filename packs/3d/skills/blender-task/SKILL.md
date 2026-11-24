---
name: blender-task
description: Runs a Blender job in background mode with a script and proves the result from a state file of objects, sizes, polygon counts, modifiers and applied scale, checked against facts from the request. Use when the user wants something modelled, cleaned up, decimated or exported in Blender, or asks to apply scale or modifiers in a .blend. Not for checking an exported model alone (use gltf-gate).
license: MIT
metadata:
  pack: 3d
  version: 0.2.2
  needs: python3, Blender
---

# Blender task

Produces a state file written by Blender itself and a fact-by-fact check of it against what the user asked for; exports then go through `gltf-gate`.

## Done when

- A facts file written from the request (not from the result) exists.
- `blender_job.py run` exited 0 and wrote a state file; the opened .blend was not changed.
- `blender_job.py check` reports every fact ok.
- Any export passed `gltf-gate check`, or is listed as not verified.

End in exactly one state: **pass**, **fail** (quote the failing line), **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Blender | `python3 scripts/blender_job.py detect` | end as blocked; tell the user to install Blender or pass `--blender <path>`; install nothing |

## Steps

The script is `scripts/blender_job.py` in this skill's folder (`"${CLAUDE_SKILL_DIR}/scripts/blender_job.py"` in Claude Code).

1. **Check needs.** `python3 scripts/blender_job.py detect`.
2. **Write the facts** from the request into `facts.json`: names, sizes in metres, polygon limits, "scale applied", "no modifiers left", objects that should be gone. Format: `references/facts-format.md`. Show them to the user if anything was a guess.
3. **Write the job script** (Blender Python). It saves or exports to NEW files only.
4. **Run.**
   ```
   python3 scripts/blender_job.py run --job job.py --state .mstack/blender/state-1.json --blend scene.blend -- --out model.glb
   ```
   The wrapper adds `assets/state_dump.py`, which writes the state file from inside Blender.
5. **Check.**
   ```
   python3 scripts/blender_job.py check --state .mstack/blender/state-1.json --facts facts.json
   ```
   On a fail, change the job script and run again with a new state file name.
6. **Gate the export** with `gltf-gate` if it is installed; otherwise say the export was not checked.
7. **Report.** End state first, then the fact table, the files written, and what was not verified.

## Rules

- The state file is the evidence. Never write or edit one by hand for a real job.
- A job that exits 0 without a state file has proved nothing.
- Never save over the user's .blend; the wrapper fails if it changed.
- Renders from Blender are optional extra proof; if made, pixel-check them with `gltf-gate`'s `pngstats.py`.

## Not for

- Checking an exported model's structure and budget → use `gltf-gate`.
- Checking bones and animation by numbers → use `rig-motion-check`.

## Level

- beginner: explain background mode, applied scale and why facts come before the job.
- standard: as written.
- expert: the fact table and end state only. Every check still runs.
