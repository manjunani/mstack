---
name: notebook-check
description: Checks a Jupyter .ipynb file for cells run out of order or never run, error outputs, names used before they are defined, machine-only paths, credentials; re-runs a copy when Jupyter is there. Use when a notebook is shared or its results quoted, or someone asks "will this notebook run for me" or "is this notebook reproducible". Not for numbers in a written report (use number-trace) or the project's test suite (use verify).
license: MIT
metadata:
  pack: data
  version: 0.1.0
  needs: python3, jupyter (optional, for the re-run)
---

# Notebook check

Produces file checks on a notebook and, when possible, a clean re-run of a copy; without the re-run the result is "not verified".

## Done when

- `scripts/nbcheck.py` ran on the notebook and its RESULT line is in the reply.
- Either the copy re-ran top to bottom in a fresh kernel, or the reply says the notebook was not re-run and why.
- No credential value appears in the reply.

End in exactly one state: **pass** (file checks clean and the re-run succeeded), **fail** (out of order, error outputs, a name used before it is defined, a machine path, a credential, or a cell that fails on re-run), **not verified** (not re-run, or a cell that does not parse), or **blocked** (not a notebook file).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Jupyter, for the re-run | `jupyter nbconvert --version` | file checks still run; the re-run is not verified; tell the user how to install it in their project environment, and do not install it |

## Steps

The script is `scripts/nbcheck.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/nbcheck.py"`.

1. **Check needs.**
2. **Check the file.** Nothing is executed.
   ```
   python3 scripts/nbcheck.py <notebook.ipynb>
   ```
3. **Ask before re-running.** Re-running executes the notebook's code: it may read files, call services or take long. Say so, and run only after a yes.
   ```
   python3 scripts/nbcheck.py <notebook.ipynb> --run [--out-dir .mstack/notebook-check]
   ```
   The executed copy goes to the out folder; the notebook itself is never changed.
4. **Report.** End state first. Then findings with cell numbers, then what was not checked (the re-run, cells that did not parse, a star import).

## Rules

- The name scan is simple: it reads top-level code only, not function bodies or names set by magics. A clean scan is not proof of a clean run; only the re-run is.
- A credential found in a notebook is in its history too. Tell the user to change it, not only delete it.
- Never print a credential's value, even when asked to confirm it.

## Not for

- Numbers quoted in a written report → use `number-trace`.
- Running the project's tests → use `verify`.
- Checking a dataset the notebook reads → use `data-profile`.

## Level

- beginner: explain why run order and hidden state make results impossible to repeat.
- standard: as written.
- expert: findings by cell and the RESULT line. The question before a re-run is never skipped.
