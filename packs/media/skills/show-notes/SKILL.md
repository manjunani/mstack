---
name: show-notes
description: Writes chapters and show notes for an episode from its word-timed transcript, then checks that chapters start at zero, ascend, are long enough and end inside the recording, and that every quoted line matches the transcript word for word. Use when the user wants timestamps, chapters or episode notes for a podcast or video. Not for making the transcript (use transcribe).
license: MIT
metadata:
  pack: media
  version: 0.2.2
  needs: python3
---

# Show notes

Produces `show-notes.md`, `chapters.txt` (for a description box) and `chapters.ffmetadata` (for ffmpeg), written only after the checks pass.

## Done when

- `show_notes.py check` passes: first chapter at 0:00, chapters ascending, each at least the minimum length, all inside the recording, titles present and distinct.
- Every quote in the notes is found word for word in the transcript (case and punctuation aside).
- The user has read the "spoken there" line for each chapter; the script cannot judge whether a title fits.

End in exactly one state: **pass**, **fail**, **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| A word-timed transcript | a `*.transcript.json` | use `transcribe` first; end as blocked |

## Steps

The script is `scripts/show_notes.py` (`"${CLAUDE_SKILL_DIR}/scripts/show_notes.py"`).

1. **Read the transcript** and draft a notes file: title, summary, chapters (start and title), and quotes copied from the transcript, not from memory. Format in `--help`.
2. **Check.**
   ```
   python3 scripts/show_notes.py check <notes.json> --transcript <name>.transcript.json
   ```
   A failed quote shows the closest passage; copy the real words, or drop the quote. Never change the transcript to match a quote.
3. **Write the files.**
   ```
   python3 scripts/show_notes.py render <notes.json> --transcript <name>.transcript.json --out-dir <new folder>
   ```
4. **Report.** End state first, then the chapter list, the quote count, and that the summary's fairness was not checked.

## Rules

- Chapter limits in `references/limits.json` are remembered platform rules, unverified. If the user's platform differs, pass `--min-chapters` and `--min-chapter-seconds`.
- The summary says only what the episode says. No claim, number or name that is not in the transcript.
- A speaker name on a quote comes from the user or the recording, never a guess.

## Not for

- Getting the words from the audio → use `transcribe`.
- Turning interview notes into research themes → use `research-synthesis`.
- Subtitles → use `captions`.

## Level

- beginner: explain why chapters start at 0:00 and what "word for word" means.
- standard: as written.
- expert: report faults and the end state only. Every check still runs.
