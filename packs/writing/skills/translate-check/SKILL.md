---
name: translate-check
description: Translates a text or a JSON strings file and proves nothing countable was lost. Use when the user wants something translated or localised, or asks whether a translation dropped anything. Checks numbers, glossary names, links, placeholders and markup match in count and form, every key is translated and length limits hold; quality is not checked. Not for one-language proofreading (use copyedit).
license: MIT
metadata:
  pack: writing
  version: 0.3.0
  needs: python3
---

# Translate check

Produces the translation in a new file and a parity report against the source.

## Done when

- `parity.py` passes on the source and the translation: protected items match in count and form, glossary terms used as many times as in the source, every source key has a non-empty translation, limits kept.
- The reply says that accuracy and tone were not checked by any script, and offers a back-translation of a few lines for the user to judge.

End in exactly one state: **pass**, **fail**, **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Target language | the user names it | ask; end as blocked until named |
| Glossary (optional) | a JSON file `{"source term": "required translation"}` | carry on; terms are then not checked |

## Steps

The script is `scripts/parity.py` (`"${CLAUDE_SKILL_DIR}/scripts/parity.py"`).

1. **Collect the fixed points.** Product and people's names that stay as they are, required term translations, interface length limits. Put them in a glossary and a limits file.
2. **Translate** into a new file. Placeholders (`{name}`, `%d`, `%(n)s`), tags and link addresses are copied as they are; only the words around them change.
3. **Check.**
   ```
   python3 scripts/parity.py text <source> <translation> --glossary glossary.json
   python3 scripts/parity.py strings <en.json> <de.json> --glossary glossary.json --limits limits.json
   ```
   If the target language writes numbers differently (1.250,00), ask the user; with their agreement add `--loose-numbers`.
4. **Fix and re-check** until it passes. Shorten an over-long interface string by rewording, never by cutting a placeholder.
5. **Report.** End state first, then counts checked, any warning (keys left identical, extra keys), and the line that quality was not checked.

## Rules

- A pass means nothing countable was lost. It does not mean the translation is correct.
- Never translate a placeholder, a tag, a link address or a name in the glossary mapped to itself.
- Keys missing from the translation are faults, not "to do later".

## Not for

- Proofreading or style in one language → use `copyedit`.
- Interface wording in the source language → use `ui-copy`.
- Subtitles in another language from speech → use `captions` after translating the transcript.

## Level

- beginner: explain what a placeholder is and why it is copied unchanged.
- standard: as written.
- expert: report faults and the end state only. Every check still runs.
