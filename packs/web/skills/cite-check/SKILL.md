---
name: cite-check
description: Confirms that every quote and quoted claim in a document appears word for word in the saved copy of the source it cites, and lists not found, found and source missing. Use when a draft, report or article quotes sources, before publishing, or when the user asks "are these quotes accurate?", "check my citations", "did the source really say that". Not for gathering new sources (use web-research) or summarising interviews (use research-synthesis).
license: MIT
metadata:
  pack: web
  version: 0.2.2
  needs: python3
---

# Cite check

Produces three lists for one document: quotes not found in their source, quotes found, and quotes whose source has no saved copy.

## Done when

- Every cited source the document uses has a saved copy in one folder, or is listed as source missing.
- `scripts/cite_check.py` ran on the document and that folder and printed its `RESULT` line.
- Every not-found item is in the reply with the closest matching words the script printed.

End in exactly one state: **pass** (every quote found), **fail** (a quote not in its source, or a malformed claim entry), **not verified** (a source has no saved copy, or nothing to check), or **blocked** (the files cannot be read).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Saved copies of the sources | a folder of .txt, .md, .html or page-extract .json files | save them first (step 2); a source that cannot be saved is "source missing" |

## Steps

The script is `scripts/cite_check.py` in this skill's folder.

1. **Find the references.** Keys like `[S1]` or `[^3]`, Markdown links, or bare addresses. The quote's source is the reference nearest after it in the same paragraph.
2. **Save each source once** into a folder: `page-extract` writes JSON the checker reads; a PDF or a book passage the user provides can be pasted as .txt. Name files after the key (`S1.txt`) or map them in `index.json`. Do not edit a saved copy to make a quote match.
3. **Run the check.**
   ```
   python3 scripts/cite_check.py draft.md --sources sources/
   python3 scripts/cite_check.py draft.md --sources sources/ --claims claims.json --json cite-report.json
   ```
   The claims file is for claims that are not quoted in the text: each entry has the claim, its source, a verdict (supported, partly, contradicted, absent, unreachable) and the exact quote that decides it.
4. **Read not found first.** Often the draft paraphrased inside quote marks; the fix is to quote exactly or drop the marks. The user decides; the skill reports and does not edit the draft.
5. **Report.** End state, then not found with the closest match, then source missing, then the found count. State the limit: found means the words are in the copy, not that they support the sentence.

## Rules

- Matching ignores spacing, quote-mark and dash style and splits on an ellipsis; nothing looser. Do not argue a near match into a found.
- "Absent" (the source does not speak to the claim) is not "contradicted". Keep them apart.
- A quote from a page behind a login or paywall the user cannot share is source missing, not found.

## Not for

- Finding sources and building an answer → use `web-research`.
- Turning interview notes into findings → use `research-synthesis`.
- Proving that code or tests pass → use `verify`.

## Level

- beginner: explain the three lists and why a paraphrase in quote marks fails.
- standard: as written.
- expert: the lists and the end state. Every quote is still checked.
