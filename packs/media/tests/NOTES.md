# mstack-media: what was tested

Date: 2026-11-22. Machine: macOS, ffmpeg 9.0.2 (no libass, so no `subtitles` filter), ffprobe, sox, sips. Pillow was found on this machine's Python, though the build brief said it was absent; the scripts detect it at run time. No ImageMagick, no speech recogniser.

Script tests live in `tests/scripts/`. Each takes a NEW folder and builds its own media with ffmpeg (sine tones with silent gaps, ffmpeg's test picture with a tone, small JPEG and PNG files). Run from the repository root, for example:

```
python3 packs/media/tests/scripts/transcribe_cases.py .testrun/media-transcribe
```

Every case states its expected exit code; the test prints `ok` or `BAD` per case and exits 1 on any `BAD`.

| Skill | Script test | Last run | Result |
|---|---|---|---|
| transcribe | transcribe_cases.py | 2026-11-22 | 30 run, 0 wrong |
| captions | captions_cases.py | 2026-11-22 | 37 run, 0 wrong |
| export-check | export_check_cases.py | 2026-11-22 | 32 run, 0 wrong |
| podcast-edit | podcast_edit_cases.py | 2026-11-22 | 35 run, 0 wrong |
| show-notes | show_notes_cases.py | 2026-11-22 | 29 run, 0 wrong |
| video-edit | video_edit_cases.py | 2026-11-22 | 37 run, 0 wrong |
| image-batch | image_batch_cases.py | 2026-11-22 | 24 run, 0 wrong |

Trigger, silence and benefit tests (`tests/<skill>.json`) are written but were NOT run: `claude plugin eval` was out of scope for this build. No `results.json` exists.

## Faults the script tests caught during the build

- captions: with a 20-character limit, the cue maker left a 0.85 s cue below the 1 s minimum. Fixed by moving words from the cue above when it can spare them.
- export-check: the "too loud" test file was not loud enough (ffmpeg's sine source peaks near -18 dBFS), so the true-peak failure was not exercised. Test fixture fixed.
- video-edit: join frames were read one frame late (seeking after `-i` returns the first frame at or after the time), and the match limit of 12 grey levels let a cut shifted by 0.8 s pass. Fixed the seek and lowered the limit to 4; the shifted cut now fails.
- transcribe: with an API named and no key set, audio was extracted before the key was checked. Now the key is checked first.
- Several test expectations were wrong (cut lengths with crossfades, a substring count); those were fixes to the tests, not the scripts.

## Per skill: tested and not tested

**transcribe.** Tested: audio extraction to mono 16 kHz with a length check; the coverage validator on good, half-covered, invented (words in silence), out-of-order, empty and unscored transcripts; low-confidence listing; import of openai-whisper and whisper.cpp JSON shapes (samples written by hand in those shapes, not produced by the real tools); `find`; blocked paths (no recogniser, no ffmpeg, API without the yes, API with an empty key); the API request against a stand-in server on 127.0.0.1. Not tested: any real recogniser (none installed), so the command lines built for whisper.cpp and openai-whisper have never run; any real API.

**captions.** Tested: cue making with default and narrow limits; validator on overlap, order, numbering, line length, line count, reading speed, too short, too long, end before start, empty file, lost word, cue across a pause, cue far from its words; refusing to overwrite; frame check against a stand-in for burned captions (a white box drawn per cue). Not tested: real burn-in (this ffmpeg has no `subtitles` filter; the blocked path was tested). Non-Latin scripts and right-to-left text were not tested; line length counts characters, not graphemes.

**export-check.** Tested: real encodes to all five presets' kinds (landscape, vertical with bars, frame-rate cap, podcast MP3); failing files for resolution, pixel format, sample rate, loudness, true peak, duration and size; plan-only; refusals. Not tested: rotated phone video, variable frame rate, HDR sources. Every preset number is unverified (written from memory, no network); the script prints this on every report.

**podcast-edit.** Tested: measure, plan, apply to .wav and .mp3, three targets, filler cuts with and without approval, normalise-only, near-full-scale input, silent input, changed source, refusals, length equal to original minus cuts and crossfades. Not tested: real speech (tones only), so how cuts sound was not judged; stereo with different channels; very long files.

**show-notes.** Tested: chapter rules (zero start, order, end, minimum length, count, titles), exact quotes, reworded and spliced and invented quotes, case and punctuation tolerance, h:mm:ss for long recordings, render refuses to write bad notes. Not tested: whether chapter titles or summaries are apt (no script can).

**video-edit.** Tested: snapping cut points out of words (both directions), `--cut` and `--keep` giving the same list, the approval gate, real cuts with one and two ranges, a cut of the right length at the wrong place (caught by join frames), sound shorter than picture, footage with no sound, refusals. Not tested: variable frame rate footage, long files, cuts judged by eye on real footage.

**image-batch.** Tested with sips and Pillow: preview, cover and within modes, JPEG and PNG, GPS removal from hand-built EXIF, size limit failure, missing output, wrong dimensions, planted file with GPS, refusals. Not tested: ImageMagick (not installed); HEIC input; EXIF orientation (stripping EXIF also drops the orientation tag, which matters if a tool did not apply it first); colour profile conversion (the study note's sRGB check is not implemented). Background removal is out of scope for this version.

## Names

No skill name was changed. `export-check` is fine as named.
