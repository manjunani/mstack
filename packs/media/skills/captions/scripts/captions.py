#!/usr/bin/env python3
"""Turn a word-timed transcript into subtitles, check them, and optionally burn them into a video.

  make    split the transcript's words into cues by rule, write .srt and .vtt, then check what was written
  check   check any .srt or .vtt file: order, overlaps, line count, line length, reading speed, duration;
          with --transcript also that no word was lost or added and each cue sits on its words
  burn    print the ffmpeg command that burns a subtitle file into a video; run it only with --run,
          then compare length with the source and look for the captions in frames at cue midpoints
  frames  pull frames at cue midpoints from a video; with --against, prove each differs from the source

The limits (lines, characters, seconds, reading speed) come from references/limits.json and can be
overridden per run. Words are never dropped, shortened or reworded to make a cue fit: a cue that
cannot meet a limit is reported.

Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked.
Inputs are only read. Output goes to the folder or file named with --out-dir or --out, which must be new.
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
LIMITS = HERE.parent / "references" / "limits.json"
TIMING = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})|(\d\d):(\d\d)[.](\d{3})\s*-->\s*(\d\d):(\d\d)[.](\d{3})")


def end(code, line):
    print(line)
    return code


def limits(args):
    data = json.loads(LIMITS.read_text(encoding="utf-8"))
    loose = [k for k, v in data.items() if not v.get("verified")]
    values = {k: v["value"] for k, v in data.items()}
    changed = []
    for key in values:
        given = getattr(args, key, None)
        if given is not None:
            values[key] = given
            changed.append(f"{key}={given}")
    if loose:
        print(f"note: {len(loose)} of {len(data)} limits in references/limits.json are unverified (checked {data[loose[0]]['checked']}); "
              "they are common practice written from memory, not a broadcaster's rule. Use the user's own spec if they have one.")
    if changed:
        print("limits changed for this run: " + ", ".join(changed))
    return values


def load_words(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        words = data["words"]
        assert isinstance(words, list)
        for w in words:
            assert isinstance(w["word"], str) and w["word"].strip() and w["end"] >= w["start"] >= 0
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        return None, f"{path} is not a word-timed transcript ({exc!r}). Make one with the transcribe skill."
    for a, b in zip(words, words[1:]):
        if b["start"] < a["start"] - 1e-6:
            return None, f"{path}: word '{b['word']}' at {b['start']} comes before '{a['word']}' at {a['start']}; fix the transcript first"
    return [dict(w, word=" ".join(w["word"].split())) for w in words], data.get("duration")


def wrap(text, max_chars, max_lines):
    """Split text into at most max_lines lines of at most max_chars. Returns None when it cannot fit."""
    if len(text) <= max_chars:
        return [text]
    words = text.split(" ")
    if max_lines == 2:
        best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            if len(a) <= max_chars and len(b) <= max_chars:
                score = abs(len(a) - len(b)) - (6 if a[-1] in ",;:.?!" else 0)
                if best is None or score < best[0]:
                    best = (score, [a, b])
        return best[1] if best else None
    lines = []
    for word in words:
        if lines and len(lines[-1]) + 1 + len(word) <= max_chars:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines if len(lines) <= max_lines and all(len(x) <= max_chars for x in lines) else None


def joined(words):
    return " ".join(w["word"] for w in words)


def segment(words, lim, duration):
    groups, cur = [], []
    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            fits = wrap(joined(cur + [w]), lim["max_chars_per_line"], lim["max_lines"]) is not None
            long = w["end"] - cur[0]["start"] > lim["max_duration"]
            sentence = cur[-1]["word"][-1] in ".?!" and len(joined(cur)) >= lim["max_chars_per_line"] * 0.5
            if gap > lim["pause_split"] or not fits or long or sentence:
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)

    def too_short(g, nxt):
        room = (nxt[0]["start"] - lim["min_gap"]) if nxt else (duration or float("inf"))
        return room - g[0]["start"] < lim["min_duration"]

    def can_join(a, b):
        return (b[0]["start"] - a[-1]["end"] <= lim["pause_split"] and b[-1]["end"] - a[0]["start"] <= lim["max_duration"]
                and wrap(joined(a + b), lim["max_chars_per_line"], lim["max_lines"]) is not None)

    i = 0
    while i < len(groups):  # a cue with no room to stay on screen long enough joins a neighbour when the rules allow
        nxt = groups[i + 1] if i + 1 < len(groups) else None
        if too_short(groups[i], nxt):
            if nxt and can_join(groups[i], nxt):
                groups[i:i + 2] = [groups[i] + nxt]
                continue
            if i > 0 and can_join(groups[i - 1], groups[i]):
                groups[i - 1:i + 1] = [groups[i - 1] + groups[i]]
                i -= 1
                continue
            # No join fits. Take words from the end of the cue above while that cue can spare them.
            while (i > 0 and too_short(groups[i], nxt) and len(groups[i - 1]) > 1
                   and groups[i][0]["start"] - groups[i - 1][-1]["end"] <= lim["pause_split"]
                   and groups[i - 1][-1]["start"] - lim["min_gap"] - groups[i - 1][0]["start"] >= lim["min_duration"]
                   and wrap(joined([groups[i - 1][-1]] + groups[i]), lim["max_chars_per_line"], lim["max_lines"]) is not None):
                groups[i].insert(0, groups[i - 1].pop())
        i += 1

    cues = []
    for i, g in enumerate(groups):
        text = joined(g)
        lines = wrap(text, lim["max_chars_per_line"], lim["max_lines"]) or [text]
        start, stop = g[0]["start"], g[-1]["end"]
        room = (groups[i + 1][0]["start"] - lim["min_gap"]) if i + 1 < len(groups) else (duration or float("inf"))
        want = start + max(lim["min_duration"], len(text) / lim["max_chars_per_second"])
        stop = max(stop, min(want, room))
        cues.append({"start": round(start, 3), "end": round(stop, 3), "lines": lines})
    return cues


def stamp(t, sep):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def write_files(cues, folder, stem):
    srt = "".join(f"{i}\n{stamp(c['start'], ',')} --> {stamp(c['end'], ',')}\n" + "\n".join(c["lines"]) + "\n\n" for i, c in enumerate(cues, 1))
    vtt = "WEBVTT\n\n" + "".join(f"{stamp(c['start'], '.')} --> {stamp(c['end'], '.')}\n" + "\n".join(c["lines"]) + "\n\n" for c in cues)
    (folder / f"{stem}.srt").write_text(srt, encoding="utf-8")
    (folder / f"{stem}.vtt").write_text(vtt, encoding="utf-8")
    return folder / f"{stem}.srt", folder / f"{stem}.vtt"


def parse(path):
    """Return (cues, problems). Each cue: index (or None), start, end, lines."""
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [f"cannot read {path}: {exc}"]
    cues, problems = [], []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        rows = [r for r in block.split("\n") if r.strip()]
        at = next((i for i, r in enumerate(rows) if TIMING.search(r)), None)
        if at is None:
            if rows and not re.match(r"WEBVTT|NOTE|STYLE|REGION", rows[0]):
                problems.append(f"block with no timing line: '{rows[0][:40]}'")
            continue
        g = TIMING.search(rows[at]).groups()
        if g[0] is not None:
            a = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3].ljust(3, "0")) / 1000
            b = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7].ljust(3, "0")) / 1000
        else:
            a = int(g[8]) * 60 + int(g[9]) + int(g[10]) / 1000
            b = int(g[11]) * 60 + int(g[12]) + int(g[13]) / 1000
        index = int(rows[at - 1]) if at > 0 and rows[at - 1].strip().isdigit() else None
        lines = [re.sub(r"<[^>]+>|\{\\[^}]*\}", "", r).strip() for r in rows[at + 1:]]
        cues.append({"index": index, "start": a, "end": b, "lines": lines})
    return cues, problems


def validate(cues, lim, words=None, is_srt=True):
    faults = []

    def add(i, message):
        faults.append(f"cue {i + 1} at {stamp(cues[i]['start'], ',')}: {message}")

    for i, c in enumerate(cues):
        text = " ".join(c["lines"])
        length = c["end"] - c["start"]
        if not text.strip():
            add(i, "has no text")
        if length <= 0:
            add(i, f"ends at or before it starts ({c['start']} to {c['end']})")
            continue
        if i and c["start"] < cues[i - 1]["start"]:
            add(i, "starts before the cue above it (out of order)")
        if i and c["start"] < cues[i - 1]["end"] - 0.0005:
            add(i, f"overlaps the cue above it by {cues[i - 1]['end'] - c['start']:.3f} s")
        if is_srt and c["index"] is not None and c["index"] != i + 1:
            add(i, f"is numbered {c['index']}, expected {i + 1}")
        if len(c["lines"]) > lim["max_lines"]:
            add(i, f"has {len(c['lines'])} lines (limit {lim['max_lines']})")
        for line in c["lines"]:
            if len(line) > lim["max_chars_per_line"]:
                add(i, f"line of {len(line)} characters (limit {lim['max_chars_per_line']}): '{line[:50]}'")
        if length < lim["min_duration"] - 0.0005:
            add(i, f"is on screen {length:.2f} s (minimum {lim['min_duration']})")
        if length > lim["max_duration"] + 0.0005:
            add(i, f"is on screen {length:.2f} s (maximum {lim['max_duration']})")
        speed = len(text) / length
        if speed > lim["max_chars_per_second"] + 0.05:
            add(i, f"reads at {speed:.1f} characters a second (ceiling {lim['max_chars_per_second']}): '{text[:40]}'")
    if words is not None:
        shown = [w for c in cues for line in c["lines"] for w in line.split()]
        said = [p for w in words for p in w["word"].split()]
        if shown != said:
            at = next((i for i, (a, b) in enumerate(zip(shown, said)) if a != b), min(len(shown), len(said)))
            faults.append(f"the cue text differs from the transcript at word {at + 1}: cues have "
                          f"'{' '.join(shown[at:at + 4]) or '(end)'}', transcript has '{' '.join(said[at:at + 4]) or '(end)'}' "
                          f"({len(shown)} words in cues, {len(said)} in the transcript)")
        else:
            at = 0
            for i, c in enumerate(cues):
                count = sum(len(line.split()) for line in c["lines"])
                group = []
                while count > 0 and at < len(words):
                    group.append(words[at])
                    count -= len(words[at]["word"].split())
                    at += 1
                if not group:
                    continue
                if abs(c["start"] - group[0]["start"]) > 0.3:
                    add(i, f"starts {c['start'] - group[0]['start']:+.2f} s away from its first word '{group[0]['word']}'")
                if c["end"] < group[-1]["end"] - 0.3:
                    add(i, f"ends {group[-1]['end'] - c['end']:.2f} s before its last word '{group[-1]['word']}' is finished")
                for a, b in zip(group, group[1:]):
                    if b["start"] - a["end"] > lim["pause_split"] + 0.0005:
                        add(i, f"runs across a pause of {b['start'] - a['end']:.2f} s between '{a['word']}' and '{b['word']}'")
    return faults


def report(cues, faults, what):
    spans = [c["end"] - c["start"] for c in cues if c["end"] > c["start"]]
    speeds = [len(" ".join(c["lines"])) / (c["end"] - c["start"]) for c in cues if c["end"] > c["start"]]
    print(f"{what}: {len(cues)} cues" + (f", {min(spans):.2f} to {max(spans):.2f} s on screen, fastest {max(speeds):.1f} characters a second, "
                                         f"longest line {max(len(l) for c in cues for l in c['lines'])} characters" if spans else ""))
    for f in faults[:30]:
        print("  FAIL " + f)
    if len(faults) > 30:
        print(f"  ... and {len(faults) - 30} more")
    if faults:
        return end(1, f"RESULT fail: {len(faults)} fault(s); first: {faults[0]}")
    return end(0, "RESULT pass")


def cmd_make(args):
    words, duration = load_words(args.transcript)
    if words is None:
        return end(2, f"blocked: {duration}")
    lim = limits(args)
    folder = args.out_dir
    stem = args.name or pathlib.Path(args.transcript).name.replace(".transcript.json", "").replace(".json", "")
    if (folder / f"{stem}.srt").exists() or (folder / f"{stem}.vtt").exists():
        return end(2, f"blocked: {folder}/{stem}.srt or .vtt already exists; name a new --out-dir or --name so nothing is overwritten")
    if not words:
        return end(0, "RESULT pass: the transcript has no words, so there is nothing to caption and no file was written")
    folder.mkdir(parents=True, exist_ok=True)
    cues = segment(words, lim, duration)
    srt, vtt = write_files(cues, folder, stem)
    print(f"wrote {srt} and {vtt.name}")
    faults = []
    for path in (srt, vtt):  # check the files as written, not the list in memory
        parsed, problems = parse(path)
        faults += [f"{path.name}: {p}" for p in problems] + [f"{path.name}: {f}" for f in validate(parsed, lim, words, path.suffix == ".srt")]
        if len(parsed) != len(cues):
            faults.append(f"{path.name}: {len(parsed)} cues read back, {len(cues)} written")
    return report(cues, faults, "subtitles")


def cmd_check(args):
    cues, problems = parse(args.subtitles)
    if cues is None:
        return end(2, f"blocked: {problems[0]}")
    words = None
    if args.transcript:
        words, why = load_words(args.transcript)
        if words is None:
            return end(2, f"blocked: {why}")
    lim = limits(args)
    if not cues and not problems:
        if words == []:
            return end(0, "RESULT pass: no cues and no words; nothing to caption")
        return end(1, "RESULT fail: the file has no cues")
    faults = problems + validate(cues, lim, words, pathlib.Path(args.subtitles).suffix.lower() == ".srt")
    code = report(cues, faults, str(args.subtitles))
    if code == 0 and words is None:
        print("note: no --transcript given, so the words and their timing were not compared with the speech")
    return code


def has_filter(name):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return re.search(rf"^\s*\S+\s+{name}\s", out.stdout, re.M) is not None


def video_info(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate,width,height:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
        num, den = data["streams"][0]["r_frame_rate"].split("/")
        return float(data["format"]["duration"]), float(num) / float(den)
    except (ValueError, KeyError, IndexError, ZeroDivisionError):
        return None, None


def gray(path, t):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                          "-vf", "scale=160:90,format=gray", "-f", "rawvideo", "-"], capture_output=True)
    return out.stdout if out.returncode == 0 and len(out.stdout) == 160 * 90 else None


def pull_frames(video, cues, folder, against, count):
    """Save a picture at the midpoint of up to `count` cues. With `against`, measure how much each differs from the source."""
    folder.mkdir(parents=True, exist_ok=True)
    step = max(1, len(cues) // count)
    chosen = cues[::step][:count]
    faults, unknown = [], []
    for n, c in enumerate(chosen, 1):
        t = (c["start"] + c["end"]) / 2
        png = folder / f"cue-{n:02d}-at-{t:.2f}s.png"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(png)],
                       capture_output=True)
        if not png.exists() or png.stat().st_size == 0:
            faults.append(f"no frame could be read at {t:.2f} s")
            continue
        line = f"  frame {png}  '{' '.join(c['lines'])[:40]}'"
        mine = gray(video, t)
        if mine is not None and sum(mine) / len(mine) < 3:
            line += "  [picture is black]"
        if against:
            theirs = gray(against, t)
            if mine is None or theirs is None:
                unknown.append(f"{t:.2f} s")
                line += "  [could not compare with the source]"
            else:
                changed = sum(1 for a, b in zip(mine, theirs) if abs(a - b) > 24) / len(mine)
                line += f"  [{changed:.1%} of the picture differs from the source]"
                if changed < 0.003:
                    faults.append(f"at {t:.2f} s the frame is the same as the source: the caption '{' '.join(c['lines'])[:30]}' is not in the picture")
        print(line)
    return faults, unknown, len(chosen)


def cmd_frames(args):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return end(2, "blocked: ffmpeg and ffprobe are needed; install ffmpeg with the system's package manager")
    cues, problems = parse(args.subtitles)
    if not cues:
        return end(2, f"blocked: no cues in {args.subtitles}")
    if video_info(args.video)[0] is None:
        return end(2, f"blocked: {args.video} has no readable video stream")
    lim = limits(args)
    faults, unknown, n = pull_frames(args.video, cues, args.out_dir, args.against, lim["burn_frames"])
    if faults:
        return end(1, "RESULT fail: " + "; ".join(faults[:3]))
    if unknown or not args.against:
        return end(2, f"RESULT not verified: {n} frames saved in {args.out_dir}; look at each one. " +
                      ("No source was given with --against, so the script could not tell whether captions are in the picture" if not args.against
                       else "frames could not be compared at " + ", ".join(unknown)))
    return end(0, f"RESULT pass: {n} frames differ from the source at cue midpoints; look at them in {args.out_dir} to judge that the text is readable")


def cmd_burn(args):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return end(2, "blocked: ffmpeg and ffprobe are needed; install ffmpeg with the system's package manager")
    cues, problems = parse(args.subtitles)
    if not cues:
        return end(2, f"blocked: no cues in {args.subtitles}")
    length, fps = video_info(args.video)
    if length is None:
        return end(2, f"blocked: {args.video} has no readable video stream")
    if args.out.exists() or args.out.resolve() == args.video.resolve():
        return end(2, f"blocked: {args.out} already exists or is the input; give a new file name")
    if not has_filter("subtitles"):
        return end(2, "blocked: this ffmpeg was built without the 'subtitles' filter (it needs libass), so it cannot burn captions in. "
                      "The .srt and .vtt files still work as sidecar files. To burn in, the user needs an ffmpeg build with libass.")
    lim = limits(args)
    faults = validate(cues, lim, None, True)
    if faults:
        return end(1, f"RESULT fail: the subtitle file has {len(faults)} fault(s); fix those before burning in. First: {faults[0]}")
    safe = "mstack-burn.srt"
    call = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-i", str(args.video.resolve()), "-vf", f"subtitles={safe}",
            "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", str(args.out.resolve())]
    print(f"plan: copy {args.subtitles} to {args.out.parent}/{safe}, then, in that folder:")
    print("  " + " ".join(call))
    print(f"the picture is encoded again (H.264, CRF 18); the sound is copied. Source: {length:.2f} s at {fps:.2f} frames a second.")
    if not args.run:
        return end(2, "RESULT not verified: plan only. Nothing was encoded. Run again with --run to burn in.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.subtitles, args.out.parent / safe)
    done = subprocess.run(call, capture_output=True, text=True, cwd=args.out.parent)
    got, _ = video_info(args.out) if args.out.exists() else (None, None)
    if done.returncode != 0 or got is None:
        return end(1, f"RESULT fail: ffmpeg exited {done.returncode} and left no playable file ({done.stderr.strip()[-300:]})")
    print(f"wrote {args.out}: {got:.2f} s (source {length:.2f} s)")
    faults = []
    if abs(got - length) > 1.0 / fps + 0.01:
        faults.append(f"output is {got:.3f} s, source is {length:.3f} s; they differ by more than one frame")
    more, unknown, n = pull_frames(args.out, cues, args.out.with_suffix(".frames"), args.video, lim["burn_frames"])
    faults += more
    if faults:
        return end(1, "RESULT fail: " + "; ".join(faults[:3]))
    if unknown:
        return end(2, "RESULT not verified: frames could not be compared at " + ", ".join(unknown))
    return end(0, f"RESULT pass: length matches and {n} cue frames differ from the source; look at them in {args.out.with_suffix('.frames')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)

    def overrides(p):
        p.add_argument("--max-lines", dest="max_lines", type=int, help="lines per cue")
        p.add_argument("--max-chars", dest="max_chars_per_line", type=int, help="characters per line")
        p.add_argument("--min-duration", dest="min_duration", type=float, help="shortest time on screen, seconds")
        p.add_argument("--max-duration", dest="max_duration", type=float, help="longest time on screen, seconds")
        p.add_argument("--max-cps", dest="max_chars_per_second", type=float, help="reading-speed ceiling, characters a second")
        p.add_argument("--pause-split", dest="pause_split", type=float, help="a pause this long between words starts a new cue")

    p = sub.add_parser("make", help="write .srt and .vtt from a transcript and check them")
    p.add_argument("transcript", type=pathlib.Path, help="word-timed transcript JSON")
    p.add_argument("--out-dir", type=pathlib.Path, required=True, help="folder for the subtitle files")
    p.add_argument("--name", help="file name without extension (default: the transcript's name)")
    overrides(p)
    p = sub.add_parser("check", help="check an .srt or .vtt file")
    p.add_argument("subtitles", type=pathlib.Path)
    p.add_argument("--transcript", type=pathlib.Path, help="also compare words and timing with this transcript")
    overrides(p)
    p = sub.add_parser("burn", help="plan or run a burn-in")
    p.add_argument("video", type=pathlib.Path)
    p.add_argument("subtitles", type=pathlib.Path)
    p.add_argument("--out", type=pathlib.Path, required=True, help="new video file to write")
    p.add_argument("--run", action="store_true", help="encode; without this only the plan is printed")
    overrides(p)
    p = sub.add_parser("frames", help="pull frames at cue midpoints")
    p.add_argument("video", type=pathlib.Path)
    p.add_argument("subtitles", type=pathlib.Path)
    p.add_argument("--out-dir", type=pathlib.Path, required=True, help="folder for the frames")
    p.add_argument("--against", type=pathlib.Path, help="the source video without captions, to compare each frame with")
    args = parser.parse_args()
    return {"make": cmd_make, "check": cmd_check, "burn": cmd_burn, "frames": cmd_frames}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
