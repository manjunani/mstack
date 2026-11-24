---
name: text-to-3d
description: Gets one 3D model from a text-to-3D provider the user picked, with the cost agreed first, then accepts or rejects the downloaded file by running real-file, structure and budget checks and recording the spend. Use when the user asks to generate a 3D model or asset from a prompt or image with an AI service. Not for checking a model you already have (use gltf-gate).
license: MIT
metadata:
  pack: 3d
  version: 0.2.2
  needs: python3, the provider's own tool or account
---

# Text to 3D

Produces an approval record with the stated cost, one generated model, and an accept or reject verdict on that exact file.

## Done when

- The user said yes to the provider, the stated cost and the prompt, and `accept.py approve` recorded it.
- Exactly one generation ran with the provider's own tool.
- `accept.py accept` judged the downloaded file and `gltf-gate check` passed on it, or the reason it did not is reported.

End in exactly one state: **pass**, **fail** (quote the failing line), **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| a provider the user chose, with its own CLI, MCP server or skill | the user names it; its tool answers `--help` or lists its tools | end as blocked; this skill ships no provider details |
| `gltf-gate` for the full check | the skill is installed | carry on; the result is at best not verified |

## Steps

The script is `scripts/accept.py` in this skill's folder (`"${CLAUDE_SKILL_DIR}/scripts/accept.py"` in Claude Code).

1. **Ask.** Tell the user the provider, the cost per model as the provider states it today, that the prompt goes to that provider, and that this is one generation. Wait for a yes.
2. **Record the yes.**
   ```
   python3 scripts/accept.py approve --provider "<name>" --cost "<stated cost>" --prompt "<prompt>" --user-approved
   ```
   Pass `--user-approved` only after the yes. Without it the script refuses.
3. **Generate once** with the provider's own tool. Ask for glTF or GLB output. Take the model file from the response by its named key, not by position, and save it to disk.
4. **Accept or reject.**
   ```
   python3 scripts/accept.py accept <file> --id <approval id> --profile phone-ar
   ```
   A web page or API error saved as a model is rejected and does not use up the approval; download again.
5. **Gate.** Run `gltf-gate check` with renders on the same file, then `accept` again; it finds the passing manifest by hash.
6. **Rigged?** If the model has a skeleton, run `rig-motion-check` before anyone animates it.
7. **Report.** End state first, then cost recorded, the verdict, and `python3 scripts/accept.py list` for the ledger.

## Rules

- No paid call without a recorded yes. One approval covers one generated file; a retry is a new question to the user.
- The provider cannot show you the model. Judge it from local checks and local renders only.
- Prices and endpoints change; never write them into files. Ask the provider's tool or page each time.

## Not for

- Checking a model you already have → use `gltf-gate`.
- Making or fixing a model by hand in Blender → use `blender-task`.

## Level

- beginner: explain the cost question, why one approval is one file, and what the gate checks.
- standard: as written.
- expert: ask once with cost and provider, then show verdicts only. The approval step is never skipped.
