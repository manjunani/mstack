---
name: skill-name
description: <Result the user gets>. Use when <situations in the user's words>. Not for <nearest other job> (use <that skill>).
license: MIT
metadata:
  pack: <pack>
  version: 0.1.0
  needs: <comma-separated tools, or none>
---

# Skill name

One sentence: what this skill produces.

## Done when

- <A check a script or a person can run.>
- <Another.>

End in exactly one state: **pass**, **fail**, **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| <tool> | `<command that proves it is there>` | <what to tell the user>; end as blocked |

## Steps

1. **Check needs.** Run the checks above.
2. **<Verb> ...** <What to do, and which script to run.>
   ```
   python3 scripts/<name>.py <arguments>
   ```
3. **<Verb> ...**
4. **Report.** State the end state first, then what was checked, what failed, and what was not verified.

## Rules

- <A judgement rule that is specific to this job.>
- <What must never happen here.>

## Not for

- <A nearby request> → use `<other-skill>`.

## Level

- beginner: <what is explained or asked in addition>.
- standard: as written.
- expert: <what is shortened>. No check is skipped at any level.

<!--
Folder layout:

skill-name/
  SKILL.md          this file, body under 150 lines
  scripts/          checks; Python standard library; --help; exit 0 pass, 1 fail, 2 not verified or blocked
  references/       detail loaded only when a step says so; dated data files
  assets/           templates the skill copies

Before submitting: read ../../standard/RULES.md and DESCRIPTIONS.md, add tests (TESTS.md), run tools/validate and tools/build-map.
Remove this comment.
-->
