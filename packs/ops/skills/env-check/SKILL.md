---
name: env-check
description: Lists environment variable names the code reads that are not set or not documented, and names that nothing reads, without showing any value. Use when an app crashes on a missing env var, a new variable was added in code, .env.example may be out of date, or the user asks "are all the env vars set in production?". Not for finding secrets committed to a repository (use secure) or for checking that a deployed service answers (use deploy-check).
license: MIT
metadata:
  pack: ops
  version: 0.1.0
  needs: python3
---

# Env check

Produces three lists of variable names: missing in the target, undocumented, unused. No value is read out, printed or stored.

## Done when

- The script scanned the source folder and printed how many names the code reads.
- Every name the code reads is in the example env file and in the list of names set in the target, or is listed as missing or undocumented.
- The reply contains names and file places only. No value appears in it.

End in exactly one state: **pass**, **fail** (names listed), **not verified** (the target's names were not supplied, so only code and example were compared), or **blocked** (no source files, or a file that was named does not exist).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Source code | the folder holds `.js`, `.ts`, `.py`, `.rs`, `.go` or `.rb` files | end as blocked |
| An example env file | `.env.example`, `.env.sample` or `.env.template` exists | carry on; the result is not verified for "documented" |
| The names set in the target | a file the user made (see step 2) | carry on; the result is not verified for the target |

## Steps

The script is `scripts/envnames.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/envnames.py"`.

1. **Check needs.** Find the source folder and the example file. Do not open `.env`, `.env.local` or any file that holds real values; the script does not need them and neither do you.
2. **Ask for the target's names.** The script cannot read a hosting platform. Ask the user to save the list of variable names set in the environment they care about (production, staging, preview) to a file, from the platform's dashboard or its own command-line tool. Names alone are enough. A `NAME=value` listing or a JSON export also works: the script keeps only the names. Tell the user not to paste the listing into the chat. If the user wants you to run a platform command to produce the file, show the command and wait for a yes; write its output straight to the file and do not print it.
3. **Compare.**
   ```
   python3 scripts/envnames.py --root . --set-names names-production.txt
   ```
   Use `--example path` when the example file has another name, and `--ignore NAME ...` for names a platform injects by itself.
4. **Read the lists.**
   - *MISSING*: the code reads it and the target does not have it. This is what crashes at start.
   - *UNDOCUMENTED*: the code reads it and the example file does not mention it.
   - *UNUSED*: documented or set, and no source file reads it. A warning: a framework, a build tool or the platform may read it. Do not remove it on this evidence alone.
   - *DYNAMIC*: places where the name is built at run time. Open each place and name the variables by hand.
5. **Fix only what the user asks for.** Adding a name to the example file (with an empty or placeholder value) is a normal edit. Setting a variable on a live service changes that service: say which name and where, and let the user do it or say yes.
6. **Run the script again** after any fix, and report. End state first, then the three lists and what was not verified.

## Rules

- Never print, quote or summarise a value, not even its first characters or its length. If a value reaches you by accident, do not repeat it.
- The script's exit code decides: missing and undocumented fail, unused warns.
- One environment per run. Production and staging get separate set-names files and separate results.
- A name being set says nothing about whether the value is right. Say so if the user asks whether the configuration is correct.

## Not for

- Finding secrets committed to the repository or its history → use `secure`.
- Checking that the deployed service runs → use `deploy-check`.
- Proving local work is finished → use `verify`.

## Level

- beginner: explain what an example env file is for, and why names are compared and values are not.
- standard: as written.
- expert: the three lists and the `RESULT` line. The rule about values holds at every level.
