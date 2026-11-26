---
name: tauri-preflight
description: Flags release blockers in a Tauri desktop app's tauri.conf.json and capabilities. Use when the user asks if the CSP in the desktop app is too permissive, whether the version in Cargo.toml, package.json and the tauri config match, if the identifier is still com.tauri.dev, or "is my Tauri config ok to ship". Also checks broad fs, shell or http permissions, an updater without a pubkey or on plain http, and missing icons. Not for the built, signed .app or dmg (use mac-release-verify).
license: MIT
metadata:
  pack: apps
  version: 0.3.1
  needs: python3
---

# Tauri preflight

Produces a list of failures and warnings for the configuration fields a release depends on, read without building.

## Done when

- `scripts/tauricheck.py --project <dir>` exits 0, or every failure it printed is in the reply.
- The reply names which fields were read and that the permission lists are unverified.

End in exactly one state: **pass** (no failure in the fields read), **fail**, **not verified** (a platform override or a capability file could not be read), or **blocked** (no tauri.conf.json).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The app folder | `src-tauri/tauri.conf.json` exists | ask for the path; a Tauri.toml or JSON5 config is not read: end as blocked and say so |

## Steps

The script is `scripts/tauricheck.py` (`"${CLAUDE_SKILL_DIR}/scripts/tauricheck.py"` in Claude Code).

1. **Run.**
   ```
   python3 scripts/tauricheck.py --project <app folder>
   ```
   It reads version 1 and version 2 configuration shapes; its `--help` lists every field.
2. **Read failures first.** Each names the field. Fix only what the user agrees to; a permission the app needs stays, narrowed to the paths or hosts it uses.
3. **Warnings** are decisions for the user (inline styles, shell execution, an identifier ending in `.app`). List them; do not change them unasked.
4. **Then build.** The project's own checks still need to run (front-end build, `cargo check`, `cargo clippy`, tests); use `verify` if installed, otherwise run them and show the exit codes.
5. **Report.** End state, failures, warnings, files that were not read, and that `references/tauri-rules.json` was written from memory. Tauri's documentation is the source for what each field means.

## Rules

- Do not run a release build, sign or publish from this skill.
- Do not loosen the content security policy or widen a permission to make an error go away; find the narrow rule.
- A clean result is about the fields read, not a security review of the app.

## Not for

- The signed, notarised .app or .dmg → use `mac-release-verify`.
- Running the test and build commands → use `verify`.
- Cutting the release itself → use `release`.

## Level

- beginner: explain what the content security policy and capabilities protect.
- standard: as written.
- expert: failures and the RESULT line. No check is skipped.
