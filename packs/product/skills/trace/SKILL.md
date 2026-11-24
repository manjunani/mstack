---
name: trace
description: Builds a matrix from each requirement id in the spec (R-001) to the tests, code and commits that mention it, and flags what is missing in either direction. Use when the user asks which requirements have no test, whether everything in the spec got built, which requirement a test or commit belongs to, or wants spec coverage before a release. Not for writing the spec or its ids (use spec), for writing the missing tests (use test-cases) or for finding untested code where no spec exists (use test-gaps).
license: MIT
metadata:
  pack: product
  version: 0.2.1
  needs: python3, git, a spec with ids
---

# Trace

Produces `.mstack/trace/matrix.md`: one row per requirement with its tests, code and commits, and a list of flags.

## Done when

- `scripts/trace.py matrix` ran on the current files and its matrix is saved.
- It exits 0: every requirement has a test reference and a code reference, or a waiver whose reason came from the user, and no test or source file points at an id the spec does not define.
- If it exits 1, the remaining flags are reported as they were printed.

End in exactly one state: **pass**, **fail** (the flags are shown), **not verified** (say which search did not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A spec with ids | a file in `docs/specs/`, or `SPEC.md`, has bullets that start `R-001:` | use `spec` if installed (its second mode writes a spec from existing code); otherwise ask the user where the requirements are; end as blocked |
| git | `git rev-parse --is-inside-work-tree` | the matrix is built from files only and ends as not verified; `--no-commits` accepts that |

## Steps

The script is `scripts/trace.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/trace.py"`.

1. **Check needs.** Run the checks above.
2. **Build the matrix.**
   ```
   python3 scripts/trace.py matrix
   python3 scripts/trace.py --spec docs/requirements.md matrix    # a spec kept elsewhere
   ```
3. **Work through the flags.** Read the file or commit named in each one before deciding.

   | Flag | Meaning | What to do |
   |---|---|---|
   | `no-test` | no test mentions the requirement | Look for a test that covers it without carrying the id. If one exists, propose adding the id to it. If none exists, it is a gap: report it. |
   | `no-code` | no source file and no commit mentions it | Search for the behaviour. If it is built, propose an id comment where it lives. If it is not built, say "not built". |
   | `orphan-test` | a test points at an id the spec lacks | The flag says whether the id was once in the spec. Removed: ask whether the test is still wanted. Never there: correct the id. |
   | `gone` | source code points at an id the spec lacks | Same question for the code. |

   Where an id is written: in a test name (`test_r_001_file_name`) or a comment beside the test (`# R-001`); in a comment beside the code; at the start of a commit message.
4. **Waive only on the user's word.** A requirement that will have no test or no code reference needs a reason from the user.
   ```
   python3 scripts/trace.py waive R-004 --flag no-test --reason "<the user's reason>"
   ```
5. **Run the matrix again** after any edit, so the saved file matches the project.
6. **Report.** End state first, then the counts, each remaining flag, each waiver with its reason, and the path of the matrix.

## Rules

- A mention is a pointer, not proof. The matrix shows that a test claims a requirement, not that the test passes or would catch a defect. Say this when the user reads "ok" as "works".
- Add an id only to a test or a function you opened and read. Ask before editing files; adding ids is the only edit this skill makes.
- Never write a waiver reason yourself, and never waive to reach a pass.
- This skill writes no tests and no product code. Gaps are reported, not filled.
- A requirement whose check in the spec is `command`, `measure`, `inspect` or `demo` is not expected to have a test; the script notes it and raises no flag.

## Not for

- Writing requirements or giving them ids → use `spec`.
- Writing the tests a `no-test` flag asks for → use `test-cases`.
- Finding risky code that has no test, in a project with no spec → use `test-gaps`.
- Proving the tests pass on the current code → use `verify`.

## Level

- beginner: explain the four flags with one example each from this project, and what a waiver means.
- standard: as written.
- expert: the matrix, the flags and the end state only. The matrix is rebuilt after every edit at every level.
