---
name: podcast-edit
description: Cleans a spoken recording into a new file: shortens long pauses, brings loudness to a named target in two passes, and only on request removes filler words with short crossfades, writing a list of every cut with its time. Use when the user wants a podcast episode, voice note or interview tidied, levelled or made less silent. Not for cutting video by its transcript (use video-edit).
license: MIT
metadata:
  pack: media
  version: 0.3.1
  needs: python3, ffmpeg, ffprobe; a word-timed transcript for filler removal
---

# Podcast edit

Produces a new audio file, a cut list (`cuts.json`, `cuts.txt`) and a measurement of the result.

## Done when

- `podcast_edit.py check` shows: integrated loudness within the tolerance of the target, true peak under the ceiling, no silence longer than the limit, and length equal to the original minus the listed cuts.
- The cut list names every cut with its time and reason, and the original's SHA-256 is unchanged.
- Filler cuts, if any, were shown to the user and approved.

End in exactly one state: **pass**, **fail**, **not verified** (say which value could not be measured), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| ffmpeg and ffprobe | `ffmpeg -version` | tell the user to install ffmpeg; end as blocked |
| Transcript (fillers only) | a `*.transcript.json` | use `transcribe`, or skip filler removal |

## Steps

The script is `scripts/podcast_edit.py` (`"${CLAUDE_SKILL_DIR}/scripts/podcast_edit.py"`).

1. **Measure.** Shows loudness, peak and long pauses; changes nothing.
   ```
   python3 scripts/podcast_edit.py measure <recording> [--target podcast]
   ```
   Targets are in `references/targets.json` (podcast, podcast-mono, broadcast); all numbers there are unverified. Use the level the user's host names, if any.
2. **Plan the cuts.**
   ```
   python3 scripts/podcast_edit.py plan <recording> [--max-silence 1.5 --keep-silence 0.6]
   ```
   Filler removal is off. Turn it on only when the user asks: add `--fillers <name>.transcript.json`. The plan then stops as blocked until the user has read the filler list or listened at those times.
3. **Apply** into a new file.
   ```
   python3 scripts/podcast_edit.py apply <cuts.json> --out <new file.wav|.mp3> [--fillers-approved]
   ```
4. **Report.** End state first, then loudness and peak before and after, the number of cuts and seconds removed, and where `cuts.txt` is so the user can audition the cuts.

## Rules

- Originals are never overwritten; the script refuses an output path that exists or equals the source.
- Filler removal changes what was said. Never add `--fillers-approved` without the user's yes to that list.
- If a silent recording cannot be normalised, report it; do not raise the gain by hand to get a reading.
- In a noisy room, pauses may not read as silence; raise `--noise-db` with the user rather than cutting by guess.

## Not for

- Cutting video footage → use `video-edit`.
- Making a transcript → use `transcribe`.
- Encoding for a platform spec → use `export-check`.

## Level

- beginner: explain LUFS, true peak and why two passes are used.
- standard: as written.
- expert: report numbers and the end state only. Every check still runs.
