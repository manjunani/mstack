"""Script test for video-edit: cut list with snapped points, the approval gate, real cuts, and results that must fail.

The footage is ffmpeg's moving test picture with a tone; the transcript is written by hand.
Usage: video_edit_cases.py <new folder>   (for example .testrun/media-video-edit)
"""
import argparse
import hashlib
import json
import shutil

import fixtures as fx

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
root = fx.new_folder(parser.parse_args().folder)
V = fx.script("video-edit", "video_edit.py")
c = fx.Cases("video-edit cases")

film = fx.video(root / "talk.mp4", 20, quiet=[(5, 7), (11, 13)])
mute = fx.video(root / "mute.mp4", 10, audio=False)
before = hashlib.sha256(film.read_bytes()).hexdigest()
words = (fx.spread("Hello and welcome to the channel everyone.", 1.0, 5.0) + fx.spread("Sorry, let me start that bit again, hold on.", 7.0, 11.0)
         + fx.spread("Today we are building a small shelf from scrap wood.", 13.0, 18.0))
said = fx.words_json(root / "talk.transcript.json", words, 20)

out = c.case("plan: one range in the gaps", [V, "plan", film, "--transcript", said, "--cut", "6-12.4", "--out-dir", root / "a"], 2, must_print="blocked: the user has not approved")
plan = json.loads((root / "a" / "cutlist.json").read_text())
c.expect("the list removes the whole second sentence and nothing else", plan["cuts"][0]["words_removed"] == "Sorry, let me start that bit again, hold on.", plan["cuts"][0]["words_removed"])
c.expect("kept time is 20 minus 6.4 seconds", abs(plan["kept_seconds"] - 13.6) < 0.001, str(plan["kept_seconds"]))
out = c.case("plan: both cut points fall inside words", [V, "plan", film, "--transcript", said, "--cut", "7.1-10.8", "--out-dir", root / "snap"], 2)
snapped = json.loads((root / "snap" / "cutlist.json").read_text())["cuts"][0]
c.expect("the start moved back before 'Sorry,' and the end moved past 'on.'", snapped["start"] < 7.0 and snapped["end"] > 10.92 and out.count("\nmoved: ") == 2, f"{snapped['start']} to {snapped['end']}")
c.expect("no word is split: the removed words are the whole sentence", snapped["words_removed"] == "Sorry, let me start that bit again, hold on.", snapped["words_removed"])
c.case("plan: a start nearer the end of a word keeps that word", [V, "plan", film, "--transcript", said, "--cut", "7.3-12", "--out-dir", root / "snap2"], 2)
c.expect("'Sorry,' stays and the cut starts in the gap after it", json.loads((root / "snap2" / "cutlist.json").read_text())["cuts"][0]["words_removed"].startswith("let me"))

c.case("cut: without the user's yes", [V, "cut", root / "a" / "cutlist.json", "--out", root / "out" / "a.mp4"], 2, must_print="needs the user's yes")
c.expect("nothing was written without the yes", not (root / "out").exists())
out = c.case("cut: approved", [V, "cut", root / "a" / "cutlist.json", "--out", root / "out" / "a.mp4", "--approved"], 0)
c.expect("both join frames match the source", out.count("matches the source") == 2 and "DOES NOT" not in out)
c.expect("two pictures were saved for the join", len(list((root / "out" / "a.joins").glob("*.png"))) == 2)
c.case("check: the cut file again", [V, "check", root / "out" / "a.mp4", "--cutlist", root / "a" / "cutlist.json"], 0)
c.case("cut: output already exists", [V, "cut", root / "a" / "cutlist.json", "--out", root / "out" / "a.mp4", "--approved"], 2, must_print="already exists")
c.case("cut: output is the source", [V, "cut", root / "a" / "cutlist.json", "--out", film, "--approved"], 2, must_print="blocked")

c.case("plan: two ranges", [V, "plan", film, "--transcript", said, "--cut", "0-0.8", "--cut", "5.5-12.5", "--out-dir", root / "b"], 2)
out = c.case("cut: two ranges", [V, "cut", root / "b" / "cutlist.json", "--out", root / "out" / "b.mp4", "--approved"], 0)
c.case("plan: the same edit as --keep ranges", [V, "plan", film, "--transcript", said, "--keep", "0.8-5.5", "--keep", "12.5-20", "--out-dir", root / "k"], 2)
c.expect("--keep gives the same cuts as --cut", [(x["start"], x["end"]) for x in json.loads((root / "k" / "cutlist.json").read_text())["cuts"]]
         == [(x["start"], x["end"]) for x in json.loads((root / "b" / "cutlist.json").read_text())["cuts"]])

# Same length, wrong content: a file cut at 5.2-11.6 checked against the list that says 6-12.4.
c.case("plan: a shifted range of the same length", [V, "plan", film, "--transcript", said, "--cut", "5.2-11.6", "--out-dir", root / "shift"], 2)
c.case("cut: the shifted range", [V, "cut", root / "shift" / "cutlist.json", "--out", root / "out" / "shift.mp4", "--approved"], 0)
c.case("check: right length, wrong frames at the join", [V, "check", root / "out" / "shift.mp4", "--cutlist", root / "a" / "cutlist.json"], 1, must_print="is not the source frame")
c.case("check: uncut source against the list", [V, "check", film, "--cutlist", root / "a" / "cutlist.json"], 1, must_print="kept ranges add up to")
# Sound shorter than picture.
fx.ffmpeg("-i", root / "out" / "a.mp4", "-c:v", "copy", "-af", "atrim=0:9", "-c:a", "aac", root / "out" / "short-sound.mp4")
c.case("check: sound 4.6 s shorter than picture", [V, "check", root / "out" / "short-sound.mp4", "--cutlist", root / "a" / "cutlist.json"], 1, must_print="sound is")

still = fx.words_json(root / "mute.transcript.json", [], 10)
c.case("plan: footage with no sound track", [V, "plan", mute, "--transcript", still, "--cut", "2-4", "--out-dir", root / "m"], 2)
c.case("cut: footage with no sound track", [V, "cut", root / "m" / "cutlist.json", "--out", root / "out" / "m.mp4", "--approved"], 0, must_print="no sound track")

c.case("plan: --cut and --keep together", [V, "plan", film, "--transcript", said, "--cut", "1-2", "--keep", "3-4"], 2, must_print="one of the two")
c.case("plan: no ranges", [V, "plan", film, "--transcript", said], 2, must_print="blocked")
c.case("plan: range after the end", [V, "plan", film, "--transcript", said, "--cut", "25-30"], 2, must_print="after the video ends")
c.case("plan: range that is not a range", [V, "plan", film, "--transcript", said, "--cut", "soon"], 2)
c.case("plan: everything cut", [V, "plan", film, "--transcript", said, "--cut", "0-20", "--out-dir", root / "all"], 1, must_print="whole video")
c.case("plan: transcript missing", [V, "plan", film, "--transcript", root / "none.json", "--cut", "1-2"], 2, must_print="blocked")
c.case("plan: file is not a video", [V, "plan", said, "--transcript", said, "--cut", "1-2"], 2, must_print="blocked")

changing = root / "changing.mp4"
shutil.copy(film, changing)
c.case("plan: a copy that will change", [V, "plan", changing, "--transcript", said, "--cut", "6-12", "--out-dir", root / "c"], 2)
with open(changing, "ab") as handle:
    handle.write(b"\0" * 64)
c.case("cut: the footage changed after the plan", [V, "cut", root / "c" / "cutlist.json", "--out", root / "out" / "c.mp4", "--approved"], 2, must_print="changed since the plan")
c.expect("the source footage is byte-for-byte unchanged", hashlib.sha256(film.read_bytes()).hexdigest() == before)
raise SystemExit(c.finish())
