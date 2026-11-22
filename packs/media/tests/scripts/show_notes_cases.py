"""Script test for show-notes: good notes pass and are written; each kind of bad chapter or quote is caught.

Needs no media tools. The transcript is written by hand.
Usage: show_notes_cases.py <new folder>   (for example .testrun/media-show-notes)
"""
import argparse
import json

import fixtures as fx

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
root = fx.new_folder(parser.parse_args().folder)
S = fx.script("show-notes", "show_notes.py")
c = fx.Cases("show-notes cases")

words = (fx.spread("Welcome to the workshop podcast. I'm Asha, and today we talk about small tools.", 0.5, 8)
         + fx.spread("First, why do people keep a notebook? Because memory is a leaky bucket, and paper never crashes.", 30, 42)
         + fx.spread("Now the second topic: pricing. We charged nine dollars a month and nobody complained.", 60, 72)
         + fx.spread("To close, here's the one thing to remember: write it down before you forget.", 100, 110))
talk = fx.words_json(root / "talk.transcript.json", words, 120)
good = {"title": "Small tools", "summary": "Asha on notebooks and pricing.",
        "chapters": [{"start": 0, "title": "Welcome"}, {"start": "00:30", "title": "Why keep a notebook"},
                     {"start": 60, "title": "Pricing"}, {"start": "1:40", "title": "One thing to remember"}],
        "quotes": [{"text": "Memory is a leaky bucket, and paper never crashes.", "speaker": "Asha"},
                   {"text": "we charged nine dollars a month and nobody complained"}]}


def notes(name, **changes):
    data = json.loads(json.dumps(good))
    data.update(changes)
    path = root / f"{name}.json"
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return path


def chapters(*pairs):
    return [{"start": s, "title": t} for s, t in pairs]


out = c.case("check: good notes", [S, "check", notes("good"), "--transcript", talk], 0)
c.expect("each chapter shows what is spoken there, and each quote its time", "spoken there: \"First, why do people" in out and "00:36  \"Memory is a leaky" in out)
c.case("render: good notes", [S, "render", notes("good"), "--transcript", talk, "--out-dir", root / "out"], 0)
c.expect("chapters.txt holds four lines starting at 00:00", (root / "out" / "chapters.txt").read_text().splitlines() ==
         ["00:00 Welcome", "00:30 Why keep a notebook", "01:00 Pricing", "01:40 One thing to remember"])
c.expect("the notes file quotes Asha with a time", "(Asha, 00:36)" in (root / "out" / "show-notes.md").read_text())
c.expect("the ffmetadata file ends the last chapter at the end of the recording", "END=120000" in (root / "out" / "chapters.ffmetadata").read_text())
c.case("render: same folder again", [S, "render", notes("good"), "--transcript", talk, "--out-dir", root / "out"], 2, must_print="already holds")

c.case("check: first chapter not at zero", [S, "check", notes("late", chapters=chapters((5, "Welcome"), (30, "Notebook"), (60, "Pricing"))), "--transcript", talk], 1, must_print="has to start at zero")
c.case("check: chapters out of order", [S, "check", notes("order", chapters=chapters((0, "Welcome"), (60, "Pricing"), (30, "Notebook"))), "--transcript", talk], 1, must_print="not after chapter")
c.case("check: chapter after the end", [S, "check", notes("beyond", chapters=chapters((0, "Welcome"), (30, "Notebook"), ("2:30", "Outro"))), "--transcript", talk], 1, must_print="after the recording ends")
c.case("check: chapter of 4 seconds", [S, "check", notes("short", chapters=chapters((0, "Welcome"), (30, "Notebook"), (34, "Aside"), (60, "Pricing"))), "--transcript", talk], 1, must_print="4 s long")
c.case("check: last chapter 5 s before the end", [S, "check", notes("tail", chapters=chapters((0, "Welcome"), (30, "Notebook"), (115, "Bye"))), "--transcript", talk], 1, must_print="5 s long")
c.case("check: only two chapters", [S, "check", notes("two", chapters=chapters((0, "Welcome"), (60, "Pricing"))), "--transcript", talk], 1, must_print="at least 3")
c.case("check: two chapters, limit lowered", [S, "check", notes("two-ok", chapters=chapters((0, "Welcome"), (60, "Pricing"))), "--transcript", talk, "--min-chapters", "2"], 0)
c.case("check: same title twice", [S, "check", notes("twice", chapters=chapters((0, "Welcome"), (30, "Pricing"), (60, "pricing"))), "--transcript", talk], 1, must_print="used twice")
c.case("check: chapter with no title", [S, "check", notes("untitled", chapters=chapters((0, "Welcome"), (30, ""), (60, "Pricing"))), "--transcript", talk], 1, must_print="no title")
c.case("check: start that is not a time", [S, "check", notes("nottime", chapters=chapters((0, "Welcome"), ("half past", "Notebook"), (60, "Pricing"))), "--transcript", talk], 1, must_print="is not a time")
c.case("check: no chapters at all", [S, "check", notes("none", chapters=[]), "--transcript", talk], 1, must_print="no chapters")
out = c.case("check: quote with one word changed", [S, "check", notes("reworded", quotes=[{"text": "Memory is a leaky bucket, but paper never crashes."}]), "--transcript", talk], 1, must_print="not in the transcript word for word")
c.expect("the failure shows what was really said", "closest passage, at 00:3" in out and "and paper never crashes" in out)
c.case("check: quote that joins two separate passages", [S, "check", notes("spliced", quotes=[{"text": "memory is a leaky bucket and nobody complained"}]), "--transcript", talk], 1)
c.case("check: quote never said", [S, "check", notes("invented", quotes=[{"text": "Our revenue tripled in a single quarter."}]), "--transcript", talk], 1, must_print="nothing similar was said")
c.case("check: quote that only differs in case and punctuation", [S, "check", notes("case", quotes=[{"text": "WRITE IT DOWN — before you forget!"}]), "--transcript", talk], 0)
c.case("check: no quotes is fine", [S, "check", notes("noquotes", quotes=[]), "--transcript", talk], 0)
c.case("render: bad notes write nothing", [S, "render", root / "invented.json", "--transcript", talk, "--out-dir", root / "out-bad"], 1, must_print="nothing was written")
c.expect("no folder was made for the bad notes", not (root / "out-bad").exists())
c.case("check: notes file missing", [S, "check", root / "nope.json", "--transcript", talk], 2, must_print="blocked")
c.case("check: transcript is not a transcript", [S, "check", notes("good"), "--transcript", notes("good")], 2, must_print="blocked")
long = fx.words_json(root / "long.transcript.json", fx.spread("hello and welcome to a very long recording", 0, 5) + fx.spread("we are now in the second hour", 3700, 3705), 4000)
out = c.case("check: recording over an hour uses h:mm:ss", [S, "check", notes("hour", chapters=chapters((0, "Start"), ("1:01:40", "Second hour"), ("1:05:00", "End")), quotes=[]), "--transcript", long], 0, must_print="1:01:40  Second hour")
raise SystemExit(c.finish())
