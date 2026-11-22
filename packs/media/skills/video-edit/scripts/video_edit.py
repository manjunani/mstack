#!/usr/bin/env python3
"""Cut supplied footage by its transcript: a cut list the user approves, a frame-accurate cut, and a measured result.

  plan   turn --cut or --keep time ranges into a cut list; move every cut point that falls inside a word to
         the gap beside it; write cutlist.json and cutlist.txt (with the words each cut removes). Edits nothing.
  cut    make the cuts and join the kept parts into a NEW file (picture and sound are encoded again, so cuts
         land on the exact frame); refuses without --approved; then runs check
  check  compare the new file with the cut list: total length, sound length against picture length, and a
         frame on each side of every join, saved as pictures and matched against the source

Ranges are seconds or clock times: --cut 12.5-18 --cut 1:02-1:10.5
Choosing what to cut is the user's call. This script only makes the choice exact and proves the result.
It does not reframe (no vertical crop), add music or grade colour.

Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked.
The source is only read: its SHA-256 is taken at plan time and compared again before and after the cut.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
TOLERANCES = HERE.parent / "references" / "tolerances.json"


def end(code, line):
    print(line)
    return code


def need_ffmpeg():
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        print(f"blocked: {' and '.join(missing)} not found on the path. Install ffmpeg (it includes ffprobe) "
              "with the system's package manager, then run this again.")
        sys.exit(2)


def tolerances():
    data = json.loads(TOLERANCES.read_text(encoding="utf-8"))
    loose = [k for k, v in data.items() if not v.get("verified")]
    if loose:
        print(f"note: {len(loose)} of {len(data)} tolerances in references/tolerances.json are unverified defaults (written {data[loose[0]]['checked']}).")
    return {k: v["value"] for k, v in data.items()}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def info(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
        video = next(s for s in data["streams"] if s.get("codec_type") == "video")
        audio = next((s for s in data["streams"] if s.get("codec_type") == "audio"), None)
        num, den = video["r_frame_rate"].split("/")
        total = float(data["format"]["duration"])
        return {"duration": total, "fps": float(num) / float(den), "video_seconds": float(video.get("duration", total)),
                "audio_seconds": float(audio.get("duration", total)) if audio else None, "has_audio": audio is not None,
                "size": f"{video.get('width')}x{video.get('height')}"}
    except (ValueError, KeyError, StopIteration, ZeroDivisionError):
        return None


def seconds(text):
    parts = [float(p) for p in text.strip().split(":")]
    if not 1 <= len(parts) <= 3 or any(p < 0 for p in parts):
        raise ValueError(text)
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def span(text):
    try:
        a, b = text.split("-")
        a, b = seconds(a), seconds(b)
        assert b > a
        return a, b
    except (ValueError, AssertionError):
        raise argparse.ArgumentTypeError(f"'{text}' is not a range such as 12.5-18 or 1:02-1:10") from None


def clock(t):
    return f"{int(t // 60):02d}:{t % 60:06.3f}"


def snap(t, words, pad, duration):
    """Move t out of a word into the gap beside it. Returns (new time, the word it was inside or None)."""
    for i, w in enumerate(words):
        if w["start"] < t < w["end"]:
            before = words[i - 1]["end"] if i else 0.0
            after = words[i + 1]["start"] if i + 1 < len(words) else duration
            if t - w["start"] <= w["end"] - t:      # nearer the start of the word: go to the gap before it
                return max((before + w["start"]) / 2, w["start"] - pad), w["word"]
            return min((w["end"] + after) / 2, w["end"] + pad), w["word"]
    return t, None


def cmd_plan(args):
    need_ffmpeg()
    meta = info(args.video) if args.video.exists() else None
    if meta is None:
        return end(2, f"blocked: {args.video} does not exist or has no readable picture")
    try:
        words = json.loads(args.transcript.read_text(encoding="utf-8"))["words"]
        assert all(isinstance(w["word"], str) and w["end"] >= w["start"] >= 0 for w in words)
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        return end(2, f"blocked: {args.transcript} is not a word-timed transcript ({exc!r}). Make one with the transcribe skill.")
    if bool(args.cut) == bool(args.keep):
        return end(2, "blocked: give the ranges to remove with --cut, or the ranges to keep with --keep (one of the two, not both)")
    tol = tolerances()
    duration, fps = meta["duration"], meta["fps"]
    if args.keep:
        keeps, at, asked = sorted(args.keep), 0.0, []
        for a, b in keeps:
            if a > at:
                asked.append((at, a))
            at = max(at, b)
        if at < duration:
            asked.append((at, duration))
    else:
        asked = sorted(args.cut)
    outside = [r for r in (args.keep or args.cut) if r[0] >= duration]
    if outside:
        return end(2, f"blocked: the range {outside[0][0]}-{outside[0][1]} starts after the video ends ({duration:.2f} s)")

    def grid(t):
        return round(round(t * fps) / fps, 4)

    cuts, moves = [], []
    for a, b in asked:
        b = min(b, duration)
        na, wa = (a, None) if a <= 0 else snap(a, words, tol["snap_pad"], duration)
        nb, wb = (b, None) if b >= duration else snap(b, words, tol["snap_pad"], duration)
        if wa:
            moves.append(f"cut start {clock(a)} was inside '{wa}'; moved to {clock(grid(na))}")
        if wb:
            moves.append(f"cut end {clock(b)} was inside '{wb}'; moved to {clock(grid(nb))}")
        na, nb = grid(max(0.0, na)), min(grid(nb), duration)
        if nb - na >= 1.0 / fps:
            if cuts and na <= cuts[-1]["end"]:
                cuts[-1]["end"] = max(cuts[-1]["end"], nb)
            else:
                cuts.append({"start": na, "end": nb})
    kept, at = [], 0.0
    for cut in cuts:
        if cut["start"] > at:
            kept.append({"start": at, "end": cut["start"]})
        at = cut["end"]
    if at < duration:
        kept.append({"start": at, "end": duration})
    for n, cut in enumerate(cuts, 1):
        gone = [w["word"] for w in words if cut["start"] <= (w["start"] + w["end"]) / 2 < cut["end"]]
        cut.update(n=n, seconds=round(cut["end"] - cut["start"], 3), words_removed=" ".join(gone))
    folder = args.out_dir or pathlib.Path.cwd() / ".mstack" / "video-edit" / args.video.stem
    folder.mkdir(parents=True, exist_ok=True)
    removed = sum(c["seconds"] for c in cuts)
    plan = {"format": "mstack-cutlist-1", "source": str(args.video.resolve()), "source_sha256": sha256(args.video), "duration": duration,
            "fps": fps, "has_audio": meta["has_audio"], "cuts": cuts, "kept": kept, "kept_seconds": round(sum(k["end"] - k["start"] for k in kept), 3)}
    (folder / "cutlist.json").write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    lines = [f"Cut list for {args.video.name} ({duration:.2f} s, {meta['size']}, {fps:.2f} frames a second)",
             f"{len(cuts)} cut(s) remove {removed:.2f} s; {plan['kept_seconds']:.2f} s stay.", ""]
    for cut in cuts:
        lines.append(f"CUT {cut['n']:>2}  {clock(cut['start'])} to {clock(cut['end'])}  ({cut['seconds']:.2f} s)")
        lines.append(f"        words removed: {cut['words_removed'] or '(no speech)'}")
    lines += [""] + [f"KEEP    {clock(k['start'])} to {clock(k['end'])}  ({k['end'] - k['start']:.2f} s)" for k in kept]
    lines += [""] + ["moved: " + m for m in moves]
    (folder / "cutlist.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"wrote {folder / 'cutlist.json'} and cutlist.txt. Nothing was edited.")
    if not cuts:
        return end(0, "RESULT pass: the ranges leave nothing to cut")
    if not kept:
        return end(1, "RESULT fail: the cut list removes the whole video")
    return end(2, f"blocked: the user has not approved this cut list. Show them cutlist.txt (the words each cut removes); "
                  f"after their yes, run: video_edit.py cut {folder / 'cutlist.json'} --out <new file> --approved")


def load_plan(path):
    try:
        plan = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        assert plan.get("format") == "mstack-cutlist-1" and plan["kept"]
        return plan
    except (OSError, ValueError, KeyError, AssertionError) as exc:
        print(f"blocked: {path} is not a cut list written by plan, or it keeps nothing ({exc!r})")
        sys.exit(2)


def gray(path, t):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-ss", f"{max(0.0, t):.4f}", "-frames:v", "1",
                          "-vf", "scale=160:90,format=gray", "-f", "rawvideo", "-"], capture_output=True)
    return out.stdout if out.returncode == 0 and len(out.stdout) == 160 * 90 else None


def difference(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def verify(out, plan, tol):
    faults, unmeasured = [], []
    meta = info(out) if pathlib.Path(out).exists() else None
    if meta is None:
        return [f"{out} is missing or has no readable picture"], []
    fps, frame = plan["fps"], 1.0 / plan["fps"]
    joins = len(plan["kept"]) - 1
    allowed = max(1, len(plan["cuts"])) * tol["frames_per_cut"] * frame + 0.005
    print(f"length:  {meta['video_seconds']:.3f} s of picture; the kept ranges add up to {plan['kept_seconds']:.3f} s (allowed difference {allowed:.3f} s)")
    if abs(meta["video_seconds"] - plan["kept_seconds"]) > allowed:
        faults.append(f"picture is {meta['video_seconds']:.3f} s, kept ranges add up to {plan['kept_seconds']:.3f} s")
    if plan["has_audio"]:
        if not meta["has_audio"]:
            faults.append("the source has sound and the new file has none")
        else:
            print(f"sound:   {meta['audio_seconds']:.3f} s against {meta['video_seconds']:.3f} s of picture (allowed difference {tol['sync_tolerance']} s)")
            if abs(meta["audio_seconds"] - meta["video_seconds"]) > tol["sync_tolerance"]:
                faults.append(f"sound is {meta['audio_seconds']:.3f} s but picture is {meta['video_seconds']:.3f} s")
    else:
        print("sound:   the source has no sound track, so there is nothing to compare")
    folder = pathlib.Path(out).with_suffix(".joins")
    folder.mkdir(parents=True, exist_ok=True)
    source, at = plan["source"], 0.0
    print(f"joins:   {joins}; pictures in {folder}")
    for n in range(joins):
        at += plan["kept"][n]["end"] - plan["kept"][n]["start"]
        sides = (("before", at - frame, plan["kept"][n]["end"] - frame), ("after", at, plan["kept"][n + 1]["start"]))
        for side, t_out, t_src in sides:
            png = folder / f"join-{n + 1:02d}-{side}-at-{t_out:.2f}s.png"
            # Seeking after -i returns the first frame at or after the time given, so ask for half a frame earlier.
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(out), "-ss", f"{max(0.0, t_out - frame / 2):.4f}",
                            "-frames:v", "1", str(png)], capture_output=True)
            if not png.exists() or png.stat().st_size == 0:
                faults.append(f"no frame could be read {side} join {n + 1}")
                continue
            mine = gray(out, t_out - frame / 2)
            theirs = [g for g in (gray(source, t_src - frame / 2 + k * frame) for k in (-1, 0, 1)) if g]
            if mine is None or not theirs:
                unmeasured.append(f"frame {side} join {n + 1} could not be compared with the source")
                print(f"  join {n + 1} {side}: {png.name}  [not compared]")
                continue
            diff = min(difference(mine, g) for g in theirs)
            verdict = "matches" if diff <= tol["join_match"] else "DOES NOT MATCH"
            print(f"  join {n + 1} {side}: {png.name}  {verdict} the source at {clock(t_src)} (difference {diff:.1f}, limit {tol['join_match']})")
            if diff > tol["join_match"]:
                faults.append(f"the frame {side} join {n + 1} is not the source frame at {clock(t_src)}")
    if not pathlib.Path(source).exists():
        faults.append(f"the source {source} is gone")
    elif sha256(source) != plan["source_sha256"]:
        faults.append(f"the source {source} has changed since the plan was made")
    else:
        print("source:  unchanged (same SHA-256 as at plan time)")
    return faults, unmeasured


def finish(faults, unmeasured, out):
    if faults:
        return end(1, "RESULT fail: " + "; ".join(faults[:4]))
    if unmeasured:
        return end(2, "RESULT not verified: " + "; ".join(unmeasured[:4]))
    return end(0, f"RESULT pass: length, sound and join frames agree with the cut list. Look at the pictures in {pathlib.Path(out).with_suffix('.joins')} "
                  "for a cut that lands mid-gesture or mid-blink; the script cannot judge that")


def cmd_cut(args):
    need_ffmpeg()
    plan = load_plan(args.cutlist)
    source = pathlib.Path(plan["source"])
    if not args.approved:
        return end(2, "blocked: cutting needs the user's yes to this cut list. Show them cutlist.txt, then add --approved")
    if not source.exists() or sha256(source) != plan["source_sha256"]:
        return end(2, f"blocked: {source} is missing or has changed since the plan was made; run plan again")
    if args.out.exists() or args.out.resolve() == source.resolve():
        return end(2, f"blocked: {args.out} already exists or is the source; give a new file name so nothing is overwritten")
    tol = tolerances()
    parts, labels = [], ""
    for i, k in enumerate(plan["kept"]):
        length = k["end"] - k["start"]
        parts.append(f"[0:v]trim=start={k['start']:.4f}:end={k['end']:.4f},setpts=PTS-STARTPTS[v{i}]")
        labels += f"[v{i}]"
        if plan["has_audio"]:
            fade = min(0.005, length / 4)   # a few milliseconds of fade each side stops a click at the join
            parts.append(f"[0:a]atrim=start={k['start']:.4f}:end={k['end']:.4f},asetpts=PTS-STARTPTS,"
                         f"afade=t=in:d={fade},afade=t=out:st={length - fade:.4f}:d={fade}[a{i}]")
            labels += f"[a{i}]"
    n = len(plan["kept"])
    parts.append(f"{labels}concat=n={n}:v=1:a={1 if plan['has_audio'] else 0}[v]" + ("[a]" if plan["has_audio"] else ""))
    call = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source), "-filter_complex", ";".join(parts), "-map", "[v]"]
    call += (["-map", "[a]", "-c:a", "aac", "-b:a", "192k"] if plan["has_audio"] else [])
    call += ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(args.out)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"cutting {len(plan['cuts'])} range(s) from {source.name}; picture and sound are encoded again (H.264 CRF 18, AAC)", flush=True)
    done = subprocess.run(call, capture_output=True, text=True)
    if done.returncode != 0 or not args.out.exists():
        return end(1, f"RESULT fail: ffmpeg exited {done.returncode} and left no file ({done.stderr.strip()[-300:]})")
    print(f"wrote {args.out}")
    faults, unmeasured = verify(args.out, plan, tol)
    return finish(faults, unmeasured, args.out)


def cmd_check(args):
    need_ffmpeg()
    plan = load_plan(args.cutlist)
    faults, unmeasured = verify(args.out, plan, tolerances())
    return finish(faults, unmeasured, args.out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan", help="write the cut list; edit nothing")
    p.add_argument("video", type=pathlib.Path)
    p.add_argument("--transcript", type=pathlib.Path, required=True, help="word-timed transcript of this video")
    p.add_argument("--cut", type=span, action="append", help="a range to remove, START-END; repeat for more")
    p.add_argument("--keep", type=span, action="append", help="a range to keep, START-END; everything else is removed")
    p.add_argument("--out-dir", type=pathlib.Path, help="folder for the cut list (default: .mstack/video-edit/<name>/)")
    p = sub.add_parser("cut", help="cut and join into a new file, then check it")
    p.add_argument("cutlist", type=pathlib.Path, help="cutlist.json written by plan")
    p.add_argument("--out", type=pathlib.Path, required=True, help="new video file")
    p.add_argument("--approved", action="store_true", help="the user said yes to this cut list")
    p = sub.add_parser("check", help="compare a cut video with its cut list")
    p.add_argument("out", type=pathlib.Path, help="the cut video")
    p.add_argument("--cutlist", type=pathlib.Path, required=True)
    args = parser.parse_args()
    return {"plan": cmd_plan, "cut": cmd_cut, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
