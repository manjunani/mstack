---
name: xr-target
description: Finds which VR or AR platform and stack a repository targets (three.js WebXR, A-Frame, Babylon, Unity XR, Quest Android, visionOS, Unreal, Godot) and prints one target record with the evidence lines, then names the skill to use next. Use when starting XR work in an unfamiliar repo or the user asks "what does this project build for". Not for testing whether a WebXR page works (use webxr-verify).
license: MIT
metadata:
  pack: xr
  version: 0.2.2
  needs: python3
---

# XR target

Produces one target record: platforms, stacks, declared versions, and the file lines that prove each.

## Done when

- `target.py` ran on the repository root and its record is shown.
- When more than one platform shows up, the user said which one the task is about.
- The next skill is named.

End in exactly one state: **pass**, **fail** (quote the failing line), **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |

## Steps

The script is `scripts/target.py` in this skill's folder (`"${CLAUDE_SKILL_DIR}/scripts/target.py"` in Claude Code).

1. **Detect.**
   ```
   python3 scripts/target.py <repo>
   ```
2. **Read the evidence lines**, not only the labels. A string in a comment is weak evidence; say so.
3. **Hand off.**
   - Meta Quest (Unity Meta SDK, Quest manifest, IWSDK): use Meta's own skills if installed (the meta-vr plugin). If not, check claims against Meta's current developer documentation before answering.
   - Web: `webxr-verify` for the session, `xr-comfort-review` for UI sizes, `three-verify` for a page without XR.
   - visionOS, Unreal, Godot: point to the vendor's documentation; this pack has no skill for them.
4. **Report.** End state first, then the record, then the next skill.

## Rules

- No XR signal is not verified, not "this is not an XR project".
- Never pick one platform silently when several appear.
- Keep this thin: platform answers come from the vendor's own skills or docs, not from this skill.

## Not for

- Whether a WebXR page works → use `webxr-verify`.
- UI comfort numbers → use `xr-comfort-review`.

## Level

- beginner: explain each stack in one line.
- standard: as written.
- expert: the record only.
