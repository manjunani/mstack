---
name: captions
description: Writes .srt and .vtt subtitle files from a word-timed transcript and checks every cue for overlaps, order, line length and reading speed; burns them into the video only when asked. Use when the user wants subtitles, closed captions or an .srt or .vtt file for a video or .mp4, or an existing .srt needs checking or retiming. Not for transcribing the audio first (use transcribe) or for translating subtitles (use translate-check).
license: MIT
metadata:
  pack: media
  version: 0.1.0
  needs: python3; ffmpeg with the subtitles filter (libass) for burn-in only
---

# Captions

Produces `<name>.srt` and `<name>.vtt` that pass a validator, and on request a new video with the captions burned in.

## Done when

- `captions.py check --transcript` passes on the written files: no overlap, cues in order, at most the line and character limits, reading speed under the ceiling, no cue across a long pause, and the cue words equal the transcript words.
- For burn-in: the output length equals the source within one frame, and frames at cue midpoints differ from the source where captions should be.

End in exactly one state: **pass**, **fail**, **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| A word-timed transcript | a `*.transcript.json` file | use `transcribe` first; end as blocked |
| ffmpeg with `subtitles` (burn-in only) | `ffmpeg -filters` lists `subtitles` | the script ends as blocked; the .srt and .vtt still work as sidecar files |

## Steps

The script is `scripts/captions.py` (`"${CLAUDE_SKILL_DIR}/scripts/captions.py"`).

1. **Ask for the spec.** If the user or platform has its own limits (characters per line, reading speed), pass them; otherwise the defaults in `references/limits.json` apply, which are unverified common practice.
2. **Make and check.**
   ```
   python3 scripts/captions.py make <name>.transcript.json --out-dir <new folder> [--max-chars 37 --max-cps 15]
   ```
   A cue that cannot meet a limit is reported, never shortened: words are not dropped or reworded.
3. **Check an existing file** the user supplies.
   ```
   python3 scripts/captions.py check <file.srt> [--transcript <name>.transcript.json]
   ```
4. **Burn in, only when asked.** Plan first; encode with `--run` after the user agrees.
   ```
   python3 scripts/captions.py burn <video> <file.srt> --out <new video> [--run]
   ```
5. **Look at the frames** the script saved and judge whether the text is readable and inside the picture.
6. **Report.** End state first, then cue count, the slowest-reading cue, any faults with their times, and whether frames were looked at.

## Rules

- Sidecar files are the default. Burn-in changes the picture for good and needs the user's request.
- A fault in reading speed means the speech is fast; tell the user, and let them choose between shorter text (their wording) and a higher limit.
- Never edit a transcript word to make a cue fit.

## Not for

- Getting the words from the audio → use `transcribe`.
- Encoding for a platform and proving its spec → use `export-check`.
- Cutting the video → use `video-edit`.

## Level

- beginner: explain what a cue is and why reading speed matters.
- standard: as written.
- expert: report faults and the end state only. Every check still runs.
