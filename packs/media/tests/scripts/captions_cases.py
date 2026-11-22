"""Script test for captions: cue making, the validator on good and bad files, the frame check and the burn-in gate.

Burn-in itself runs only where ffmpeg has the 'subtitles' filter. Where it does not, the test expects 'blocked'.
The frame check is tested with a stand-in for burned captions: a white box drawn over the picture during each cue.
Usage: captions_cases.py <new folder>   (for example .testrun/media-captions)
"""
import argparse
import re
import subprocess

import fixtures as fx

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
root = fx.new_folder(parser.parse_args().folder)
C = fx.script("captions", "captions.py")
c = fx.Cases("captions cases")

words = (fx.spread("Welcome back to the show, today we are talking about how to check subtitles.", 1.0, 6.0)
         + fx.spread("The first rule is simple: never drop a word.", 7.5, 10.5)
         + fx.spread("Yes.", 10.7, 11.0)
         + fx.spread("And the second rule is that timing follows the speech, always.", 11.1, 15.0))
talk = fx.words_json(root / "talk.transcript.json", words, 16)

out = c.case("make: four sentences with pauses", [C, "make", talk, "--out-dir", root / "subs"], 0)
srt = (root / "subs" / "talk.srt").read_text()
c.expect("no line is longer than 42 characters and no cue has more than 2 lines",
         all(len(l) <= 42 for l in srt.splitlines()) and all(len(b.split("\n")) <= 4 for b in srt.strip().split("\n\n")))
c.expect("every transcript word is in the .srt, in order",
         [w for b in srt.strip().split("\n\n") for l in b.split("\n")[2:] for w in l.split()] == [w[0] for w in words])
c.expect("the short 'Yes.' was joined to its neighbour instead of flashing for 0.3 s", "\nYes.\n\n" not in srt)
c.case("check: the .srt against the transcript", [C, "check", root / "subs" / "talk.srt", "--transcript", talk], 0)
c.case("check: the .vtt against the transcript", [C, "check", root / "subs" / "talk.vtt", "--transcript", talk], 0)
c.case("make: same output folder again", [C, "make", talk, "--out-dir", root / "subs"], 2, must_print="already exists")
out = c.case("make: narrow limit of 20 characters", [C, "make", talk, "--out-dir", root / "narrow", "--max-chars", "20"], 0)
c.expect("every line in the narrow file fits 20 characters",
         all(len(l) <= 20 for l in (root / "narrow" / "talk.srt").read_text().splitlines() if "-->" not in l))
c.case("check: the default file fails the narrow limit", [C, "check", root / "subs" / "talk.srt", "--max-chars", "20"], 1, must_print="characters (limit 20)")


def bad(name, body):
    path = root / f"{name}.srt"
    path.write_text(body, encoding="utf-8")
    return path


c.case("check: overlapping cues", [C, "check", bad("overlap", "1\n00:00:01,000 --> 00:00:04,000\nFirst line here\n\n2\n00:00:03,500 --> 00:00:06,000\nSecond line here\n")], 1, must_print="overlaps")
c.case("check: cues out of order", [C, "check", bad("order", "1\n00:00:05,000 --> 00:00:07,000\nLater line\n\n2\n00:00:01,000 --> 00:00:03,000\nEarlier line\n")], 1, must_print="out of order")
c.case("check: wrong numbering", [C, "check", bad("number", "1\n00:00:01,000 --> 00:00:03,000\nOne\n\n3\n00:00:04,000 --> 00:00:06,000\nTwo\n")], 1, must_print="numbered 3")
c.case("check: line too long", [C, "check", bad("long", "1\n00:00:01,000 --> 00:00:06,000\nThis single line runs on for far more than forty-two characters\n")], 1, must_print="characters (limit 42)")
c.case("check: three lines", [C, "check", bad("three", "1\n00:00:01,000 --> 00:00:06,000\nOne line\nTwo lines\nThree lines\n")], 1, must_print="has 3 lines")
c.case("check: too fast to read", [C, "check", bad("fast", "1\n00:00:01,000 --> 00:00:02,000\nThirty characters in one second\n")], 1, must_print="characters a second")
c.case("check: on screen too briefly", [C, "check", bad("brief", "1\n00:00:01,000 --> 00:00:01,300\nYes.\n")], 1, must_print="minimum")
c.case("check: on screen too long", [C, "check", bad("held", "1\n00:00:01,000 --> 00:00:12,000\nStill here\n")], 1, must_print="maximum")
c.case("check: end before start", [C, "check", bad("backwards", "1\n00:00:05,000 --> 00:00:03,000\nBackwards\n")], 1, must_print="before it starts")
c.case("check: file with no cues", [C, "check", bad("nothing", "just some text\n")], 1)
c.case("check: missing file", [C, "check", root / "nope.srt"], 2, must_print="blocked")
dropped = srt.replace("never drop a", "never drop")
c.case("check: one word missing from the cues", [C, "check", bad("dropped", dropped), "--transcript", talk], 1, must_print="differs from the transcript")
across = "1\n00:00:01,000 --> 00:00:06,500\n" + "check subtitles. The first\n\n"
two = fx.words_json(root / "two.json", [("check", 1.0, 1.5), ("subtitles.", 1.6, 2.4), ("The", 5.0, 5.4), ("first", 5.5, 6.2)], 8)
c.case("check: one cue across a 2.6 s pause", [C, "check", bad("across", across), "--transcript", two], 1, must_print="runs across a pause")
late = "1\n00:00:02,500 --> 00:00:04,000\ncheck subtitles.\n\n2\n00:00:05,000 --> 00:00:06,500\nThe first\n"
c.case("check: cue starts 1.5 s after its word", [C, "check", bad("late", late), "--transcript", two], 1, must_print="away from its first word")

giant = fx.words_json(root / "giant.json", [("Pneumonoultramicroscopicsilicovolcanoconiosisandmore", 1.0, 4.0), ("is", 4.1, 4.3), ("long.", 4.4, 5.0)], 6)
c.case("make: one word longer than a line is reported, not cut", [C, "make", giant, "--out-dir", root / "giant"], 1, must_print="characters (limit 42)")
c.expect("the long word is whole in the file", "Pneumonoultramicroscopicsilicovolcanoconiosisandmore" in (root / "giant" / "giant.srt").read_text())
rapid = fx.words_json(root / "rapid.json", fx.spread("this sentence is spoken far too quickly for anyone to read it comfortably at all", 1.0, 2.6)
                      + fx.spread("and the next one follows at once with no room", 2.65, 4.0), 5)
c.case("make: speech too fast for the reading ceiling", [C, "make", rapid, "--out-dir", root / "rapid"], 1, must_print="characters a second")
empty = fx.words_json(root / "empty.json", [], 5)
c.case("make: transcript with no words", [C, "make", empty, "--out-dir", root / "empty"], 0, must_print="nothing to caption")
c.case("make: not a transcript", [C, "make", root / "subs" / "talk.srt", "--out-dir", root / "x"], 2, must_print="blocked")

# Frame check. Cues at 1-3 s and 5-7 s on an 8 second video.
clean = fx.video(root / "clean.mp4", 8)
cues = bad("two-cues", "1\n00:00:01,000 --> 00:00:03,000\nFirst caption\n\n2\n00:00:05,000 --> 00:00:07,000\nSecond caption\n")
box = "drawbox=x=100:y=280:w=440:h=50:color=white:t=fill:enable='{}'"
fx.ffmpeg("-i", clean, "-vf", box.format("between(t,1,3)+between(t,5,7)"), "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", root / "both.mp4")
fx.ffmpeg("-i", clean, "-vf", box.format("between(t,1,3)"), "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", root / "first-only.mp4")
fx.ffmpeg("-i", clean, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-c:a", "copy", root / "reencoded.mp4")
c.case("frames: stand-in captions present at both cues", [C, "frames", root / "both.mp4", cues, "--out-dir", root / "f-both", "--against", clean], 0)
c.expect("two pictures were saved for inspection", len(list((root / "f-both").glob("*.png"))) == 2)
c.case("frames: caption missing at the second cue", [C, "frames", root / "first-only.mp4", cues, "--out-dir", root / "f-first", "--against", clean], 1, must_print="is not in the picture")
c.case("frames: video only encoded again, no captions", [C, "frames", root / "reencoded.mp4", cues, "--out-dir", root / "f-re", "--against", clean], 1, must_print="is not in the picture")
c.case("frames: no source to compare with", [C, "frames", root / "both.mp4", cues, "--out-dir", root / "f-alone"], 2, must_print="not verified")

# Burn-in gate.
filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
can_burn = re.search(r"^\s*\S+\s+subtitles\s", filters, re.M) is not None
print(f"this ffmpeg {'has' if can_burn else 'does NOT have'} the subtitles filter")
if can_burn:
    c.case("burn: plan only", [C, "burn", clean, cues, "--out", root / "burn" / "out.mp4"], 2, must_print="plan only")
    c.case("burn: run and check", [C, "burn", clean, cues, "--out", root / "burn" / "out.mp4", "--run"], 0)
else:
    c.case("burn: ffmpeg cannot burn in, so the script stops", [C, "burn", clean, cues, "--out", root / "burn" / "out.mp4", "--run"], 2, must_print="blocked: this ffmpeg")
    c.expect("nothing was written", not (root / "burn").exists())
c.case("burn: output name is the input", [C, "burn", clean, cues, "--out", clean, "--run"], 2, must_print="blocked")
raise SystemExit(c.finish())
