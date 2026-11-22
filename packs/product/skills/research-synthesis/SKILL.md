---
name: research-synthesis
description: Turns interview transcripts or research notes into themes backed by exact quotes. A script checks every quote word for word against its cited line, counts distinct people per theme, labels thin findings as anecdotes and lists what no finding used. Use when the user has interview notes, call transcripts or survey answers and asks for themes, insights, "what did people say" or a research summary. Not for planning interviews (use clarify), for producing solutions (use ideate) or for reviewing a screen (use design-review).
license: MIT
metadata:
  pack: product
  version: 0.1.0
  needs: python3, text sources
---

# Research synthesis

Produces a findings file in which every claim rests on verified quotes, each theme shows how many people back it, and the parts of each source that nobody cited are listed.

## Done when

- `scripts/evidence.py check` exits 0: zero unverified quotes, and no finding is called a theme with fewer people than the threshold.
- The report gives the participant count beside every theme, labels anecdotes as such, and states the coverage of each source.

End in exactly one state: **pass**, **fail** (the failing quotes or labels are shown), **not verified** (say which source could not be read), or **blocked** (no sources, or a decision only the user can make).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Sources as text | `.md` or `.txt` files with one participant each | audio needs a transcript first (`transcribe` if installed); a PDF or document must be saved as text by the user; end as blocked until then |

## Steps

The script is `scripts/evidence.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/evidence.py"`. Findings live in `.mstack/research/<study>.json`.

1. **Number the sources.** Read every source in full, with line numbers, before writing any finding.
   ```
   python3 scripts/evidence.py number notes/*.md
   ```
2. **Start the findings file.** List each source with its participant. Set the threshold with the user; 3 is the default.
   ```
   python3 scripts/evidence.py template .mstack/research/<study>.json
   ```
3. **Write findings from the text, not toward a conclusion.** Each finding has a one-sentence claim and its evidence: source, line (or range `14-15`), and the exact words. Copy quotes from the numbered output; do not tidy grammar or join separate sentences. Label each finding `theme` or `anecdote`.
4. **Check.**
   ```
   python3 scripts/evidence.py check .mstack/research/<study>.json
   ```
   A quote at the wrong line: correct the line. A quote not found: copy it again or drop it. A theme under the threshold: relabel it `anecdote`, or find more people who said it.
5. **Read the uncited stretches.** They are where a finding may be missing, or where a participant disagreed. Add a finding, or say in the report why the stretch holds nothing relevant.
6. **Report.** End state first. Then the themes with their participant counts and one quote each, then the anecdotes, then contradictions between participants, then the coverage per source.

## Rules

- Never write a quote the script has not verified, in the file or in the reply. Paraphrase is marked as paraphrase and carries no quote marks.
- Counts are of distinct people, not of quotes. Five quotes from one person are one person.
- A finding that only the researcher believes is not a finding. Opposite evidence goes in, as its own finding.
- Participant ids stay ids. Names, emails and company names from the sources are left out of the report unless the user asks.
- Sources stay as they are. Never edit a transcript to make a quote match.

## Not for

- Deciding what to ask, or what the user wants → use `clarify`.
- Turning the findings into solution ideas → use `ideate`.
- Checking a rendered page → use `design-review`.
- Saving a decision that came from the research → use `remember`.

## Level

- beginner: explain theme, anecdote and coverage with one finding from these sources before the report.
- standard: as written.
- expert: the table of findings and counts, and the coverage line. The quote check runs at every level.
