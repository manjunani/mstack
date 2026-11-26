---
name: claim-check
description: Finds every number, superlative ("fastest", "best", "only", "first"), comparison and testimonial in marketing text and fails each one that has no entry with evidence in a sources file. Use when landing page copy, an announcement, a pitch or an email makes claims, or someone asks "can we say this" or "is every stat backed". Not for checking quotes against saved web sources in articles (use cite-check).
license: MIT
metadata:
  pack: growth
  version: 0.3.0
  needs: python3; network only with --fetch, to the evidence addresses given
---

# Claim check

Produces a list of every claim in a text with a verdict: observed, reported, not a claim, unopened or unsupported.

## Done when

- `scripts/claims.py check` ran on the final text with a sources file and ended with a `RESULT` line.
- Every unsupported claim is either given a source or removed from the text, and the check was run again.
- Each "observed" verdict was read beside its quote by a person or the model: the script finds the words, it does not judge meaning.

End in exactly one state: **pass** (every claim sourced, or no claims), **fail** (unsupported claims, listed), **not verified** (evidence named but not opened), or **blocked** (no text or no readable sources file).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The text as a file | the path exists | save it to a new file under `.mstack/growth/` |
| Evidence for each claim | the user has it | ask; a claim with none is removed, never invented |

## Steps

The script is `scripts/claims.py` in this skill's folder; in Claude Code `"${CLAUDE_SKILL_DIR}/scripts/claims.py"`.

1. **Find the claims.**
   ```
   python3 scripts/claims.py find copy.md --template .mstack/growth/sources.json
   ```
2. **Fill the sources file with the user.** Per entry: `evidence` (a file or address), and `quote` (words in it) or `attested_by` (who vouches for a screenshot or dashboard). Testimonials also need `permission`: who agreed to be quoted, and when. A sentence flagged by mistake gets `"status": "not a claim"` with a reason. Ask the user for each source; do not search for one that might fit.
3. **Check.**
   ```
   python3 scripts/claims.py check copy.md --sources .mstack/growth/sources.json
   python3 scripts/claims.py check copy.md --sources .mstack/growth/sources.json --fetch   # opens web evidence
   ```
   Ask before `--fetch`: it requests each evidence address once.
4. **Read each observed quote beside its claim.** "3x faster" backed by a quote that says 3.2 to 1 is fine; backed by a quote about something else is not.
5. **Fix the text** in a new file: remove or soften unsupported claims, then run step 3 again.
6. **Report.** End state first, then unsupported claims with line numbers, then supported ones with their evidence, then not checked.

## Rules

- No invented numbers, fake reviews or testimonials, or quotes from people who did not agree. Removing the claim is always a valid fix.
- Rounding up is a new claim. "Over 10,000" needs evidence of over 10,000.
- Comparisons with a named competitor need evidence about that competitor, dated.
- The script never edits the text.

## Not for

- Quotes and facts in articles against their saved sources → use `cite-check`.
- Length and platform rules of a post → use `post-check`.
- Grammar and style → use `copyedit`.

## Level

- beginner: explain the verdicts and why a testimonial needs permission.
- standard: as written.
- expert: unsupported list and end state only. Every claim is still checked.
