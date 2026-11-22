"""Script test for podcast-edit: measure, cut list, real edits to .wav and .mp3, filler approval, and files that must fail.

"Speech" is a tone with silent gaps; the transcript for the filler case is written by hand.
Usage: podcast_edit_cases.py <new folder>   (for example .testrun/media-podcast-edit)
"""
import argparse
import hashlib
import json
import re
import shutil

import fixtures as fx

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
root = fx.new_folder(parser.parse_args().folder)
P = fx.script("podcast-edit", "podcast_edit.py")
c = fx.Cases("podcast-edit cases")

# 30 s. Pauses: 3.0 s at 4-7, 1.0 s at 12-13 (under the limit), 4.5 s at 18-22.5.
raw = fx.tone(root / "episode.wav", 30, quiet=[(4, 7), (12, 13), (18, 22.5)])
before = hashlib.sha256(raw.read_bytes()).hexdigest()
steady = fx.tone(root / "steady.wav", 12, quiet=[(5, 5.8)])
loud = fx.tone(root / "loud.wav", 12, quiet=[(5, 5.8)], volume_db=17)       # peaks near -1 dBFS
hush = fx.tone(root / "hush.wav", 5, quiet=[(0, 5)])
film = fx.video(root / "film.mp4", 2, audio=False)

out = c.case("measure: raw recording", [P, "measure", raw], 1, must_print="2 silence(s) longer than")
out = c.case("plan: silences only", [P, "plan", raw, "--out-dir", root / "plan"], 0)
cuts = json.loads((root / "plan" / "cuts.json").read_text())["cuts"]
c.expect("two cuts, at 4.3-6.7 and 18.3-22.2; the 1 s pause is left alone",
         [(round(x["start"], 1), round(x["end"], 1)) for x in cuts] == [(4.3, 6.7), (18.3, 22.2)], str([(x["start"], x["end"]) for x in cuts]))
c.expect("cuts.txt lists each cut with its time", (root / "plan" / "cuts.txt").read_text().count("silence ") == 2)
out = c.case("apply: to .wav", [P, "apply", root / "plan" / "cuts.json", "--out", root / "out" / "episode.clean.wav"], 0)
want = 30 - sum(x["end"] - x["start"] for x in cuts) - 2 * 0.02        # two joins, 0.02 s crossfade each
got = float(re.search(r"length:\s+([\d.]+) s", out).group(1))
c.expect(f"measured length {got:.3f} s equals 30 s minus the listed cuts and two crossfades ({want:.3f} s)", abs(got - want) < 0.01)
c.case("check: the edited .wav again", [P, "check", root / "out" / "episode.clean.wav", "--cuts", root / "plan" / "cuts.json"], 0)
c.case("measure: the edited .wav meets the target", [P, "measure", root / "out" / "episode.clean.wav"], 0, must_print="nothing to do")
c.case("apply: to .mp3 (lossy encoder)", [P, "apply", root / "plan" / "cuts.json", "--out", root / "out" / "episode.clean.mp3"], 0)
c.case("apply: output already exists", [P, "apply", root / "plan" / "cuts.json", "--out", root / "out" / "episode.clean.wav"], 2, must_print="already exists")
c.case("apply: output is the original", [P, "apply", root / "plan" / "cuts.json", "--out", raw], 2, must_print="blocked")
out = c.case("check: the untouched original against the cut list", [P, "check", raw, "--cuts", root / "plan" / "cuts.json"], 1)
c.expect("length, loudness and silences are all named", all(x in out for x in ("length is", "loudness is", "silence(s) longer")))

c.case("plan: broadcast target", [P, "plan", raw, "--out-dir", root / "plan-b", "--target", "broadcast"], 0)
out = c.case("apply: broadcast target", [P, "apply", root / "plan-b" / "cuts.json", "--out", root / "out" / "episode.broadcast.wav"], 0, must_print="-23.0")
c.case("check: podcast-level file against the broadcast list", [P, "check", root / "out" / "episode.clean.wav", "--cuts", root / "plan-b" / "cuts.json"], 1, must_print="loudness is")
c.case("plan: unknown target", [P, "plan", raw, "--target", "cinema"], 2, must_print="no target named")

# Filler words: off unless a transcript is given, and then the user has to agree.
said = fx.words_json(root / "episode.transcript.json", [("so", 8.0, 8.4), ("um", 9.0, 9.4), ("we", 9.5, 9.8), ("start", 9.9, 10.6),
                                                        ("Uh,", 15.0, 15.3), ("right", 15.4, 16.0), ("umbrella", 24.0, 24.8)], 30)
out = c.case("plan: with filler words", [P, "plan", raw, "--out-dir", root / "plan-f", "--fillers", said], 2, must_print="blocked: 2 cut(s) remove filler")
c.expect("'um' and 'Uh,' are listed; 'umbrella' is not", "filler word 'um'" in out and "filler word 'Uh,'" in out and "umbrella" not in out)
c.case("apply: filler cuts without the user's yes", [P, "apply", root / "plan-f" / "cuts.json", "--out", root / "out" / "episode.nofill.wav"], 2, must_print="need the user's yes")
c.expect("nothing was written without the yes", not (root / "out" / "episode.nofill.wav").exists())
c.case("apply: filler cuts with the yes", [P, "apply", root / "plan-f" / "cuts.json", "--out", root / "out" / "episode.nofill.wav", "--fillers-approved"], 0)
c.case("plan: fillers file is not a transcript", [P, "plan", raw, "--out-dir", root / "plan-x", "--fillers", raw], 2, must_print="blocked")

c.case("plan: nothing to cut", [P, "plan", steady, "--out-dir", root / "plan-s"], 0, must_print="only normalise")
c.case("apply: normalise only", [P, "apply", root / "plan-s" / "cuts.json", "--out", root / "out" / "steady.clean.wav"], 0)
c.case("plan: recording near full scale", [P, "plan", loud, "--out-dir", root / "plan-l"], 0)
c.case("apply: turned down to the target", [P, "apply", root / "plan-l" / "cuts.json", "--out", root / "out" / "loud.clean.wav"], 0)
c.case("plan: silent recording", [P, "plan", hush, "--out-dir", root / "plan-h"], 0)
c.case("apply: silent recording cannot be normalised", [P, "apply", root / "plan-h" / "cuts.json", "--out", root / "out" / "hush.clean.wav"], 1, must_print="silent")
c.case("plan: file with no audio", [P, "plan", film], 2, must_print="blocked")
c.case("plan: keep longer than the limit", [P, "plan", raw, "--out-dir", root / "plan-k", "--keep-silence", "2", "--max-silence", "1.5"], 2, must_print="blocked")

changing = root / "changing.wav"
shutil.copy(raw, changing)
c.case("plan: a copy that will change", [P, "plan", changing, "--out-dir", root / "plan-c"], 0)
with open(changing, "ab") as handle:
    handle.write(b"\0" * 64)
c.case("apply: the recording changed after the plan", [P, "apply", root / "plan-c" / "cuts.json", "--out", root / "out" / "changing.wav"], 2, must_print="changed since the plan")
c.case("apply: not a cut list", [P, "apply", said, "--out", root / "out" / "x.wav"], 2, must_print="blocked")
c.expect("the original recording is byte-for-byte unchanged", hashlib.sha256(raw.read_bytes()).hexdigest() == before)
raise SystemExit(c.finish())
