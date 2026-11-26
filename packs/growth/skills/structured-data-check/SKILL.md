---
name: structured-data-check
description: Validates the JSON-LD on real pages: each block parses, has @context and @type, and Article, Product, Organization, BreadcrumbList, FAQPage and SoftwareApplication items carry the properties in a dated list. Use when schema markup, rich results or a JSON-LD snippet was added or changed, or someone asks if the structured data is valid. Not for titles, headings or the sitemap (use site-audit).
license: MIT
metadata:
  pack: growth
  version: 0.3.0
  needs: python3, network only for a URL
---

# Structured data check

Produces one line per JSON-LD item on each page: valid, invalid with the property named, or not checked.

## Done when

- `scripts/jsonld.py` ran on every page the user named (file or address) and ended with a `RESULT` line.
- Every block is reported as parsed, failed (with the property or the JSON error) or not checked (type with no list).
- The reply says the search engine's own testing tool is the authority on rich results, and that the property lists are unverified.

End in exactly one state: **pass** (no failure; a page with no JSON-LD is a pass with that reason), **fail** (a block does not parse or lacks a required property), **not verified** (microdata, RDFa or a page built by script), or **blocked** (the page cannot be read).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The pages | a file path or an address the user gave | ask which pages; end as blocked |

## Steps

The script is `scripts/jsonld.py` in this skill's folder; in Claude Code `"${CLAUDE_SKILL_DIR}/scripts/jsonld.py"`.

1. **Pick the pages**: one per template (home, product, article, pricing), not every page.
2. **Run.**
   ```
   python3 scripts/jsonld.py page.html https://their-site.tld/pricing/ --out .mstack/growth/jsonld-<date>.json
   ```
3. **Read the output.** Failures name the block number and property. Warnings are recommended properties or values (ratings, FAQ questions) that the visitor cannot see on the page.
4. **Check the data file's age.** `references/types.json` is dated and unverified; if the user relies on a rich result, open the source named there before calling it right.
5. **Report.** End state first, then failures by page and block, then what parsed, then not checked, ending with the line about the testing tool.

## Rules

- Valid markup is not the same as a rich result appearing. Never promise one.
- Markup has to describe what the page shows. A rating, review or FAQ that is not visible on the page is a warning to fix, never something to add.
- Never write invented ratings, review counts, prices or authors into markup to make it pass.
- When fixing, change the page's source, then run the script again on the changed page.

## Not for

- Titles, descriptions, headings, robots.txt and the sitemap → use `site-audit`.
- Social preview tags and launch pages → use `launch-site-check`.
- Whether the facts in the markup are true → use `claim-check`.

## Level

- beginner: explain what JSON-LD is and why a search engine reads it, in two sentences.
- standard: as written.
- expert: failures and the end state only. Every block is still checked.
