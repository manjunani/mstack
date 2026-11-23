---
name: video-edit
description: Cuts supplied video by its transcript or by time ranges into a new file, with a cut list the user approves first. Use when the user wants retakes, false starts, "sorry let me start again", a coughing fit or dead air removed, asks to keep only 0:30 to 2:00, splice out a section at a time, or make a tighter cut of a talk. Cuts at gaps between words, frame-accurately, then checks length and sync at every join. Not for audio-only recordings (use podcast-edit) or adding captions (use captions).
license: MIT
metadata:
  pack: media
  version: 0.2.0
  needs: python3, ffmpeg, ffprobe, a word-timed transcript
---

# Video edit

Produces a cut list (`cutlist.json`, `cutlist.txt` with the words each cut removes), a new video, and pictures of every join.

## Done when

- The user approved `cutlist.txt`.
- `video_edit.py check` passes: picture length equals the sum of kept ranges within one frame per cut, sound length matches picture length, each join frame matches the source frame it should be, and the source is unchanged.
- The join pictures were looked at.

End in exactly one state: **pass**, **fail**, **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| ffmpeg and ffprobe | `ffmpeg -version` | tell the user to install ffmpeg; end as blocked |
| A word-timed transcript | a `*.transcript.json` for this video | use `transcribe` first; end as blocked |

## Steps

The script is `scripts/video_edit.py` (`"${CLAUDE_SKILL_DIR}/scripts/video_edit.py"`).

1. **Find the ranges** with the user from the transcript: retakes, false starts, long silences. Proposing ranges is fine; the choice is theirs.
2. **Plan.** Edits nothing.
   ```
   python3 scripts/video_edit.py plan <video> --transcript <name>.transcript.json --cut 12.5-18 --cut 1:02-1:10
   ```
   or `--keep` ranges instead. Points inside a word are moved to the nearest gap and listed.
3. **Show `cutlist.txt`** to the user: each cut with the words it removes. Wait for a yes to this list.
4. **Cut.**
   ```
   python3 scripts/video_edit.py cut <cutlist.json> --out <new video> --approved
   ```
5. **Look at the join pictures** in `<new video>.joins/` for a cut mid-gesture or mid-blink.
6. **Report.** End state first, then cuts made, seconds removed, length and sync results, and what the join pictures showed.

## Rules

- No cut without the user's yes to the list as printed. A changed list needs a new yes.
- Picture and sound are encoded again so cuts land on the exact frame; tell the user the file is re-encoded.
- Reframing to vertical, music and colour are out of scope for this version; say so if asked.

## Not for

- Audio-only recordings → use `podcast-edit`.
- Encoding for a platform → use `export-check`.
- Subtitles → use `captions`.

## Level

- beginner: explain why cut points move to gaps between words.
- standard: as written.
- expert: show the cut list and the end state only. The approval and every check remain.
