---
name: copyedit
description: Proofreads and copy-edits a document to a style guide, house style by default, listing corrections, suggestions and queries apart and proving code, quotes, links and numbers survived. Use when the user asks to proofread, copy-edit, line edit, fix grammar, spelling or typos, or polish the wording of a doc, report, article, README or essay before sending it. Not for interface wording (use ui-copy), translation (use translate-check) or social posts (use post-check).
license: MIT
metadata:
  pack: writing
  version: 0.2.2
  needs: python3
---

# Copyedit

Produces an edited copy of the text, a list of changes (`changes.json`) and a check report with counts by category.

## Done when

- `editcheck.py check` passes: protected spans unchanged, every number and name still present, the listed changes applied to the original give exactly the edited text, every correction cites a rule in the guide.
- Corrections, suggestions and queries are given to the user as three separate lists with counts.

End in exactly one state: **pass**, **fail**, **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A style guide | the user names one, or `references/house-style.md` | use the house style and say so |

## Steps

The script is `scripts/editcheck.py` (`"${CLAUDE_SKILL_DIR}/scripts/editcheck.py"`).

1. **Pick the guide.** A user's guide needs `## <id> <title>` headings for its rules so corrections can cite them. List the ids:
   ```
   python3 scripts/editcheck.py rules [--guide <their guide>]
   ```
2. **Edit in one pass.** Write the edited text to a new file. Build `changes.json` as you go (format in `--help`):
   - correction: breaks a rule; cites the rule id; applied.
   - suggestion: a choice the author may decline; applied only if they accept.
   - query: a possible factual problem; never changed in the text.
   Keep one name per thing (rule H5): use the form the text uses most.
3. **Check.**
   ```
   python3 scripts/editcheck.py check <original> <edited> --changes changes.json
   ```
   A fail names the unlisted change or the lost item. Fix the edit or the list; never weaken the check.
4. **Optional second pass** over the edited text into `second.json`, checked with `--second second.json`: it holds no corrections when the first pass was complete.
5. **Report.** End state first, then the three lists with counts by category and rule.

## Rules

- Fix language, not facts. A doubtful figure, date or name is a query.
- Quoted text, code, links, file names and people's names are never edited.
- Do not add opinions, examples or claims the author did not write.
- This skill does not rewrite text to hide that it was machine-written, and does not score "AI likelihood".

## Not for

- Interface strings, buttons and error messages → use `ui-copy`.
- Translating → use `translate-check`.
- Checking a social post before publishing → use `post-check`.

## Level

- beginner: explain the difference between a correction, a suggestion and a query.
- standard: as written.
- expert: deliver the three lists and the end state only. The check still runs.
