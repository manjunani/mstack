---
name: transcribe
description: Makes a word-timed transcript of an audio or video file (JSON with start, end and confidence per word, plus plain text) and checks that it covers all the speech. Use when the user wants a transcript, wants to know what is said in a recording, or another media job needs word timings first (subtitles, cutting by words, show notes). Not for turning a finished transcript into subtitles (use captions).
license: MIT
metadata:
  pack: media
  version: 0.1.0
  needs: python3, ffmpeg, ffprobe, a local speech recogniser or an API the user names
---

# Transcribe

Produces `<name>.transcript.json` (words with start, end, confidence) and `<name>.transcript.txt`, and a coverage report against the recording.

## Done when

- `transcribe.py check` reports that words cover at least the share of voiced time set in `references/thresholds.json` (silence found by ffmpeg), with no long voiced stretch left without words.
- Low-confidence words are listed for the user, or the report says the engine gave no confidence.
- The recording is unchanged; all output is in `.mstack/transcribe/` or the folder the user named.

End in exactly one state: **pass**, **fail**, **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| ffmpeg and ffprobe | `ffmpeg -version` | tell the user to install ffmpeg; end as blocked |
| A recogniser | `transcribe.py run` looks for whisper-cli, whisper-cpp, whisper, mlx_whisper, whisperx, faster-whisper, vosk-transcriber | end as blocked; offer an API (step 4) or importing a transcript made elsewhere |

## Steps

The script is `scripts/transcribe.py` in this skill's folder (`"${CLAUDE_SKILL_DIR}/scripts/transcribe.py"`).

1. **Look for an existing transcript.**
   ```
   python3 scripts/transcribe.py find <recording>
   ```
   If one exists, go to step 5.
2. **Run a local recogniser.** Ask the user which model to use; pass a model file on disk.
   ```
   python3 scripts/transcribe.py run <recording> --model <model file> [--language en]
   ```
   whisper.cpp and openai-whisper are started by the script. Others found on the path end as blocked with the command to run by hand; bring their JSON in with `import`.
3. **Import a transcript made elsewhere** (a recogniser's JSON with word timestamps).
   ```
   python3 scripts/transcribe.py import <raw.json> --media <recording>
   ```
4. **Use an API only after a yes.** First run without `--allow-upload`: the script prints the destination, minutes and megabytes, and stops. Tell the user that the audio leaves the machine and that the price is set by the service. The key stays in an environment variable the user sets; never ask for it in chat.
   ```
   python3 scripts/transcribe.py run <recording> --api-url <address the user gave> --api-key-env <VAR NAME> --allow-upload
   ```
   A failed call is not retried: it may still have been billed.
5. **Check.**
   ```
   python3 scripts/transcribe.py check <name>.transcript.json --media <recording>
   ```
6. **Report.** End state first, then coverage, the voiced stretches with no words, words found in silence (possible invented text) and the low-confidence words with times.

## Rules

- Never correct the transcript for fluency or style. A wrong word is fixed only when the user confirms what was said; otherwise it stays and is listed.
- Words found in silence are a warning sign of invented text, not a detail.
- Do not cut the recording into pieces at speaker changes before recognition; recognise it whole.
- The thresholds are unverified defaults. Say so if the user asks how strict the check is.

## Not for

- Subtitles from a transcript → use `captions`.
- Removing filler words or pauses → use `podcast-edit`.
- Chapters and quotes → use `show-notes`.

## Level

- beginner: explain what coverage and confidence mean and why a word in silence is suspect.
- standard: as written.
- expert: report the numbers and the listed words only. Every check still runs.
