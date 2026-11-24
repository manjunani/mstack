---
name: ui-copy
description: Checks the words in an interface and flags one action with several names, vague buttons like "OK" or "Submit", errors with no way forward, raw error codes and leftover placeholders. Use when the user asks to check or review error messages, button labels, microcopy or UX writing, or says the wording in the app is confusing or useless. Not for editing long prose or docs (use copyedit) or for a visual page check (use design-review).
license: MIT
metadata:
  pack: design
  version: 0.2.1
  needs: python3; a browser for the best evidence
---

# UI copy

Produces an inventory of the interface's strings with their roles and places, the strings that block, and a proposed rewrite for each.

## Done when

- `scripts/copy_check.py check` exits 0: each action has one name across the flow, no button or link label is vague, every error says what to do next, no internal error text or placeholder is shown; or each remaining item is answered with a reason.
- The report says which evidence was used: a rendered snapshot (best), a source scan, or a strings file.

End in exactly one state: **pass**, **fail** (strings listed), **not verified** (no strings found, or only part of the flow was covered; say which), or **blocked** (no page and no source to read).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Strings | a snapshot from design-review's `collect.js`, or markup files | ask where the screens are; end as blocked |

## Steps

The script is `scripts/copy_check.py` in this skill's folder.

1. **Get the strings.** Best: capture a snapshot of each screen and state in the flow with design-review's collector (if that skill is not installed, use a strings file you write from the rendered page). Otherwise scan the source and say that text built at run time is not seen.
2. **Check.**
   ```
   python3 scripts/copy_check.py check --snapshot .mstack/design-review/snapshot.json --inventory .mstack/ui-copy/inventory.json
   python3 scripts/copy_check.py check --source src/components
   ```
3. **Rewrite each blocking string.** Buttons: verb plus object ("Delete project", "Print 14 labels"). Errors: what happened, then what to do ("That file is over 10 MB. Choose a smaller file."). One name per action across every screen.
4. **Answer what stays.** Where a flagged string is right in context, add `{"text", "rule", "reason"}` to an answers file and pass `--answers`.
5. **Propose, then change.** Show the before and after table. Edit only after the user agrees, then run the check again.
6. **Report.** End state, the evidence used, the before/after table, answered items with reasons.

## Rules

- Blocking items are measurable: two names for one action, a vague label, a dead-end error, internal error text, placeholder text. Case style, shouting and weak labels are warnings.
- Keep the product's own vocabulary. If the product says "parcel", do not change it to "package".
- The word lists in `references/copy-rules.json` are dated and English only. For another language, say the lists do not apply.
- Never answer a finding just to pass; the reason has to hold for a reader.

## Not for

- Editing long text, docs or articles to a style guide → use `copyedit`.
- Layout, contrast and overflow → use `design-review`.
- Accessible names for screen readers in depth → use `a11y-audit`.

## Level

- beginner: explain why each flagged label confuses people, with the rewrite.
- standard: as written.
- expert: the before/after table and the end state. The check still runs.
