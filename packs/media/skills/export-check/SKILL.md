---
name: export-check
description: Encodes a finished video or audio file for a named platform and proves the result with ffprobe and a loudness reading. Use when the user asks to export for YouTube, Shorts, Reels, TikTok or a podcast, or whether a file will be accepted. Checks codec, pixel format, resolution, frame rate, duration, size, sample rate, loudness and true peak. Not for cutting footage (use video-edit).
license: MIT
metadata:
  pack: media
  version: 0.1.0
  needs: python3, ffmpeg, ffprobe
---

# Export check

Produces a new file encoded for a preset and a table of every measured value against the preset's limit.

## Done when

- `export_check.py check` (or `plan --run`) shows every row as ok against the preset, measured on the written file.
- The report says which preset numbers are unverified; a pass means "meets these numbers", not "the platform will accept it".

End in exactly one state: **pass**, **fail**, **not verified** (say which value could not be measured), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| ffmpeg and ffprobe | `ffprobe -version` | tell the user to install ffmpeg; end as blocked |
| A preset | `export_check.py presets` | if the platform is missing, ask for its upload spec and write a presets file; end as blocked until then |

## Steps

The script is `scripts/export_check.py` (`"${CLAUDE_SKILL_DIR}/scripts/export_check.py"`).

1. **Name the preset** and read its numbers. Every number in `references/presets.json` was written from memory on 2026-11-22 and is marked unverified; say so.
   ```
   python3 scripts/export_check.py presets
   ```
2. **Plan.** The script measures the source and prints the exact command. Nothing is encoded.
   ```
   python3 scripts/export_check.py plan <source> --preset <name> --out <new file>
   ```
   If it warns about bars (the source shape differs from the preset), ask the user before going on; reframing is their choice.
3. **Encode** after the user agrees to the command.
   ```
   python3 scripts/export_check.py plan <source> --preset <name> --out <new file> --run
   ```
4. **Check a file made elsewhere.**
   ```
   python3 scripts/export_check.py check <file> --preset <name> [--source <original>]
   ```
5. **Report.** End state first, then each failing value with the limit, then the unverified note.

## Rules

- Fix a failing value by changing the input or the settings and encoding again; never edit the preset to make a file pass.
- The user's own spec beats the shipped preset. Copy the presets file, change it, and pass it with `--presets`.
- A file with no sound against a video preset ends as not verified: loudness could not be measured.

## Not for

- Removing parts of the footage → use `video-edit`.
- Cleaning a spoken recording → use `podcast-edit`.
- Burning in subtitles → use `captions`.

## Level

- beginner: explain each row (codec, pixel format, LUFS, true peak) in one line.
- standard: as written.
- expert: show only failing rows and the end state. Every value is still measured.
