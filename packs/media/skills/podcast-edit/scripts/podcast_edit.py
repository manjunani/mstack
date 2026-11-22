#!/usr/bin/env python3
"""Clean a spoken recording: shorten long silences, bring loudness to a named target, optionally remove filler words.

  measure  print loudness, true peak and every silence longer than the limit; changes nothing
  plan     write the cut list (cuts.json and cuts.txt): every cut with its time, length and reason; changes nothing
  apply    make the cuts with short crossfades, normalise loudness in two passes, write a NEW file, then check it
  check    measure an edited file against its cut list: loudness, true peak, remaining silences, length, untouched original

Filler removal is off unless plan gets --fillers with a word-timed transcript. It cuts speech, so apply
refuses a list with filler cuts until the user has heard or read them and --fillers-approved is given.

Targets and settings live in references/targets.json, each with its source and date.
Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked.
The recording is only read: its SHA-256 is taken at plan time and compared again after the edit.
"""
import argparse
import hashlib
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
TARGETS = HERE.parent / "references" / "targets.json"
LOSSY = {".mp3", ".m4a", ".aac", ".ogg", ".opus"}
MIN_KEEP = 0.1  # a kept piece shorter than this between two cuts cannot carry two crossfades


def end(code, line):
    print(line)
    return code


def need_ffmpeg():
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        print(f"blocked: {' and '.join(missing)} not found on the path. Install ffmpeg (it includes ffprobe) "
              "with the system's package manager, then run this again.")
        sys.exit(2)


def settings(args):
    data = json.loads(TARGETS.read_text(encoding="utf-8"))
    name = getattr(args, "target", None) or "podcast"
    if name not in data["targets"]:
        print(f"blocked: no target named '{name}'. Known targets: {', '.join(sorted(data['targets']))}")
        sys.exit(2)
    values = {k: v["value"] for k, v in data.items() if isinstance(v, dict) and "value" in v}
    values.update(target=name, loudness=data["targets"][name]["loudness"]["value"], max_true_peak=data["targets"][name]["max_true_peak"]["value"])
    for key in ("max_silence", "keep_silence", "silence_noise_db"):
        if getattr(args, key, None) is not None:
            values[key] = getattr(args, key)
    entries = [v for v in data.values() if isinstance(v, dict) and "value" in v] + list(data["targets"][name].values())
    loose = sum(1 for v in entries if isinstance(v, dict) and "verified" in v and not v["verified"])
    if loose:
        print(f"note: target '{name}' and the edit settings hold {loose} UNVERIFIED numbers (references/targets.json, written 2026-11-22 from memory "
              "or as defaults). If the user's host or broadcaster names a level, use that.")
    return values


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def audio_info(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate,channels,codec_name:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
        stream = data["streams"][0]
        return {"duration": float(data["format"]["duration"]), "rate": int(stream["sample_rate"]), "channels": int(stream["channels"]),
                "codec": stream.get("codec_name")}
    except (ValueError, KeyError, IndexError):
        return None


def loudness(path):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True)
    return read_loudnorm(out.stderr) if out.returncode == 0 else None


def read_loudnorm(text):
    blocks = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", text, re.S)
    if not blocks:
        return None
    raw = json.loads(blocks[-1])
    result = {}
    for key, name in (("input_i", "i"), ("input_tp", "tp"), ("input_lra", "lra"), ("input_thresh", "thresh")):
        try:
            v = float(raw[key])
            result[name] = None if math.isinf(v) or math.isnan(v) else v
        except (KeyError, ValueError):
            result[name] = None
    return result


def silences(path, noise_db, min_len, duration):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_len}",
                          "-f", "null", "-"], capture_output=True, text=True)
    if out.returncode != 0:
        return None
    spans, start = [], None
    for line in out.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: (-?[\d.]+)", line)
        if m and start is not None:
            spans.append((start, min(duration, float(m.group(1)))))
            start = None
    if start is not None:
        spans.append((start, duration))
    return spans


def clock(t):
    return f"{int(t // 3600):02d}:{int(t // 60 % 60):02d}:{t % 60:06.3f}"


def kept_ranges(cuts, duration):
    out, at = [], 0.0
    for cut in cuts:
        if cut["start"] > at:
            out.append((at, cut["start"]))
        at = max(at, cut["end"])
    if at < duration:
        out.append((at, duration))
    return out


def cmd_measure(args):
    need_ffmpeg()
    info = audio_info(args.audio)
    if info is None:
        return end(2, f"blocked: {args.audio} has no readable audio stream")
    s = settings(args)
    loud = loudness(args.audio)
    quiet = silences(args.audio, s["silence_noise_db"], s["max_silence"], info["duration"])
    if loud is None or quiet is None:
        return end(2, "RESULT not verified: ffmpeg could not measure this file")
    print(f"file: {args.audio} ({info['duration']:.2f} s, {info['codec']}, {info['rate']} Hz, {info['channels']} ch)")
    print(f"integrated loudness: {loud['i']} LUFS (target '{s['target']}': {s['loudness']} +/- {s['loudness_tolerance']})")
    print(f"true peak: {loud['tp']} dBTP (ceiling {s['max_true_peak']})")
    print(f"silences longer than {s['max_silence']} s: {len(quiet)}")
    for a, b in quiet:
        print(f"  {clock(a)} to {clock(b)}  ({b - a:.2f} s)")
    faults = []
    if loud["i"] is None:
        faults.append("the file is silent or too short for a loudness reading")
    elif abs(loud["i"] - s["loudness"]) > s["loudness_tolerance"]:
        faults.append(f"loudness {loud['i']} LUFS is outside {s['loudness']} +/- {s['loudness_tolerance']}")
    if loud["tp"] is not None and loud["tp"] > s["max_true_peak"]:
        faults.append(f"true peak {loud['tp']} dBTP is over {s['max_true_peak']}")
    if quiet:
        faults.append(f"{len(quiet)} silence(s) longer than {s['max_silence']} s")
    if faults:
        return end(1, "RESULT fail: " + "; ".join(faults))
    return end(0, "RESULT pass: the file already meets the target; nothing to do")


def cmd_plan(args):
    need_ffmpeg()
    info = audio_info(args.audio)
    if info is None:
        return end(2, f"blocked: {args.audio} has no readable audio stream")
    s = settings(args)
    if s["keep_silence"] >= s["max_silence"]:
        return end(2, "blocked: --keep-silence must be shorter than --max-silence")
    quiet = silences(args.audio, s["silence_noise_db"], s["max_silence"], info["duration"])
    if quiet is None:
        return end(2, "RESULT not verified: silence detection did not run on this file")
    half = s["keep_silence"] / 2
    cuts = [{"start": round(a + half, 3), "end": round(b - half, 3), "kind": "silence", "note": f"pause of {b - a:.2f} s shortened to {s['keep_silence']} s"}
            for a, b in quiet if (b - half) - (a + half) > 0.01]
    fillers = 0
    if args.fillers:
        try:
            words = json.loads(args.fillers.read_text(encoding="utf-8"))["words"]
            assert all(isinstance(w["word"], str) and w["end"] >= w["start"] for w in words)
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
            return end(2, f"blocked: {args.fillers} is not a word-timed transcript ({exc!r}). Make one with the transcribe skill.")
        wanted = {w.strip().lower() for w in args.filler_words.split(",") if w.strip()}
        pad = s["filler_pad"]
        for i, w in enumerate(words):
            if re.sub(r"[^\w']", "", w["word"].lower()) not in wanted:
                continue
            lo = max(w["start"] - pad, words[i - 1]["end"] if i else 0.0)
            hi = min(w["end"] + pad, words[i + 1]["start"] if i + 1 < len(words) else info["duration"])
            if hi - lo > 0.02:
                cuts.append({"start": round(lo, 3), "end": round(hi, 3), "kind": "filler", "note": f"filler word '{w['word']}'"})
                fillers += 1
    cuts.sort(key=lambda x: x["start"])
    merged, skipped = [], []
    for cut in cuts:
        if merged and cut["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], cut["end"])
            merged[-1]["note"] += " + " + cut["note"]
            merged[-1]["kind"] = "filler" if "filler" in (merged[-1]["kind"], cut["kind"]) else "silence"
        elif merged and cut["start"] - merged[-1]["end"] < MIN_KEEP:
            skipped.append(cut)
        else:
            merged.append(cut)
    for n, cut in enumerate(merged, 1):
        cut["n"], cut["seconds"] = n, round(cut["end"] - cut["start"], 3)
    removed = sum(c["seconds"] for c in merged)
    folder = args.out_dir or pathlib.Path.cwd() / ".mstack" / "podcast-edit" / args.audio.stem
    folder.mkdir(parents=True, exist_ok=True)
    plan = {"format": "mstack-cuts-1", "source": str(args.audio.resolve()), "source_sha256": sha256(args.audio), "duration": info["duration"],
            "sample_rate": info["rate"], "target": s["target"], "loudness": s["loudness"], "max_true_peak": s["max_true_peak"],
            "loudness_tolerance": s["loudness_tolerance"], "max_silence": s["max_silence"], "keep_silence": s["keep_silence"],
            "silence_noise_db": s["silence_noise_db"], "crossfade": s["crossfade"], "duration_tolerance": s["duration_tolerance"],
            "filler_cuts": sum(1 for c in merged if c["kind"] == "filler"), "cuts": merged}
    (folder / "cuts.json").write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    lines = [f"Cut list for {args.audio.name}: {len(merged)} cuts, {removed:.2f} s removed of {info['duration']:.2f} s", ""]
    lines += [f"{c['n']:>3}  {clock(c['start'])} to {clock(c['end'])}  {c['seconds']:>7.3f} s  {c['kind']:8} {c['note']}" for c in merged]
    lines += [f"skipped (too close to the cut before it): {clock(c['start'])} {c['note']}" for c in skipped]
    (folder / "cuts.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:42]) + (f"\n... {len(lines) - 42} more lines in cuts.txt" if len(lines) > 42 else ""))
    print(f"wrote {folder / 'cuts.json'} and cuts.txt. Nothing was edited.")
    if plan["filler_cuts"]:
        return end(2, f"blocked: {plan['filler_cuts']} cut(s) remove filler words, which changes speech. Show the list to the user (or let them "
                      "listen at those times); after their yes, run apply with --fillers-approved")
    if not merged:
        return end(0, "RESULT pass: no silence is longer than the limit; apply will only normalise loudness")
    return end(0, f"RESULT pass: cut list written with {len(merged)} silence cut(s); run apply to make the new file")


def load_plan(path):
    try:
        plan = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        assert plan.get("format") == "mstack-cuts-1" and isinstance(plan["cuts"], list)
        return plan
    except (OSError, ValueError, KeyError, AssertionError) as exc:
        print(f"blocked: {path} is not a cut list written by plan ({exc!r})")
        sys.exit(2)


def verify(out, plan):
    """Measure the edited file. Returns (faults, unmeasured)."""
    faults, unmeasured = [], []
    info = audio_info(out) if pathlib.Path(out).exists() else None
    if info is None:
        return [f"{out} is missing or has no readable audio"], []
    kept = kept_ranges(plan["cuts"], plan["duration"])
    expected = sum(b - a for a, b in kept) - plan["crossfade"] * max(0, len(kept) - 1)
    print(f"length:      {info['duration']:.3f} s; expected {expected:.3f} s ({plan['duration']:.3f} s minus {len(plan['cuts'])} cuts and {max(0, len(kept) - 1)} crossfades)")
    if abs(info["duration"] - expected) > plan["duration_tolerance"]:
        faults.append(f"length is {info['duration']:.3f} s, expected {expected:.3f} s +/- {plan['duration_tolerance']}")
    loud = loudness(out)
    if loud is None or loud["i"] is None:
        unmeasured.append("loudness (ffmpeg gave no reading; the file may be silent or very short)")
    else:
        print(f"loudness:    {loud['i']:.1f} LUFS; target '{plan['target']}' is {plan['loudness']} +/- {plan['loudness_tolerance']}")
        print(f"true peak:   {loud['tp']:.1f} dBTP; ceiling {plan['max_true_peak']}")
        if abs(loud["i"] - plan["loudness"]) > plan["loudness_tolerance"] + 0.05:
            faults.append(f"loudness is {loud['i']:.1f} LUFS, target {plan['loudness']} +/- {plan['loudness_tolerance']}")
        if loud["tp"] is not None and loud["tp"] > plan["max_true_peak"] + 0.05:
            faults.append(f"true peak is {loud['tp']:.1f} dBTP, ceiling {plan['max_true_peak']}")
    quiet = silences(out, plan["silence_noise_db"], plan["max_silence"] + 0.1, info["duration"])
    if quiet is None:
        unmeasured.append("remaining silences")
    else:
        print(f"silences longer than {plan['max_silence']} s left: {len(quiet)}")
        if quiet:
            faults.append(f"{len(quiet)} silence(s) longer than {plan['max_silence']} s remain, first at {clock(quiet[0][0])} ({quiet[0][1] - quiet[0][0]:.2f} s)")
    source = pathlib.Path(plan["source"])
    if not source.exists():
        faults.append(f"the original {source} is gone")
    elif sha256(source) != plan["source_sha256"]:
        faults.append(f"the original {source} has changed since the plan was made")
    else:
        print("original:    unchanged (same SHA-256 as at plan time)")
    return faults, unmeasured


def cmd_apply(args):
    need_ffmpeg()
    plan = load_plan(args.cuts)
    source = pathlib.Path(plan["source"])
    if not source.exists() or sha256(source) != plan["source_sha256"]:
        return end(2, f"blocked: {source} is missing or has changed since the plan was made; run plan again")
    if args.out.exists() or args.out.resolve() == source.resolve():
        return end(2, f"blocked: {args.out} already exists or is the original; give a new file name so nothing is overwritten")
    if plan.get("filler_cuts") and not args.fillers_approved:
        return end(2, f"blocked: the list has {plan['filler_cuts']} filler cut(s). They need the user's yes; then add --fillers-approved")
    kept = kept_ranges(plan["cuts"], plan["duration"])
    if not kept:
        return end(1, "RESULT fail: the cut list removes the whole recording")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if len(kept) == 1 and kept[0] == (0.0, plan["duration"]):
        graph = "[0:a]anull[cut]"
    else:
        parts = [f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[s{i}]" for i, (a, b) in enumerate(kept)]
        last = "s0"
        for i in range(1, len(kept)):
            parts.append(f"[{last}][s{i}]acrossfade=d={plan['crossfade']}:c1=tri:c2=tri[x{i}]")
            last = f"x{i}"
        graph = ";".join(parts) + f";[{last}]anull[cut]"
    # Pass 1: make the cuts in memory and measure them. No file is written.
    done = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(source), "-filter_complex", graph + ";[cut]loudnorm=print_format=json[m]",
                           "-map", "[m]", "-f", "null", "-"], capture_output=True, text=True)
    first = read_loudnorm(done.stderr) if done.returncode == 0 else None
    if first is None:
        return end(1, f"RESULT fail: cutting failed in the measuring pass ({done.stderr.strip()[-300:]})")
    if first["i"] is None:
        return end(1, "RESULT fail: the cut audio is silent or too short for a loudness reading, so it cannot be normalised")
    # A lossy encoder can lift peaks slightly after the filter has run, so aim lower for those formats.
    peak = plan["max_true_peak"] - (1.0 if args.out.suffix.lower() in LOSSY else 0.2)
    lra = min(50, max(11, math.ceil(first["lra"] or 0) + 1))
    chain = (f"loudnorm=I={plan['loudness']}:TP={peak}:LRA={lra}:measured_I={first['i']}:measured_TP={first['tp']}:"
             f"measured_LRA={first['lra']}:measured_thresh={first['thresh']}:linear=true")
    print(f"pass 1: after cutting, loudness is {first['i']} LUFS and true peak {first['tp']} dBTP")
    # Pass 2: the same cuts again, corrected with the measured values, written to the new file.
    done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source), "-filter_complex", f"{graph};[cut]{chain}[final]",
                           "-map", "[final]", "-ar", str(plan["sample_rate"]), str(args.out)], capture_output=True, text=True)
    if done.returncode != 0 or not args.out.exists():
        return end(1, f"RESULT fail: the edit failed ({done.stderr.strip()[-300:]})")
    print(f"wrote {args.out}")
    faults, unmeasured = verify(args.out, plan)
    return finish(faults, unmeasured, args.cuts)


def finish(faults, unmeasured, cuts):
    if faults:
        return end(1, "RESULT fail: " + "; ".join(faults[:4]))
    if unmeasured:
        return end(2, "RESULT not verified: " + "; ".join(unmeasured))
    return end(0, f"RESULT pass: loudness, true peak, silences and length are inside the limits; every cut is listed in {pathlib.Path(cuts).with_name('cuts.txt')}")


def cmd_check(args):
    need_ffmpeg()
    plan = load_plan(args.cuts)
    faults, unmeasured = verify(args.out, plan)
    return finish(faults, unmeasured, args.cuts)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)

    def tuning(p):
        p.add_argument("--target", help="loudness target name from references/targets.json (default podcast)")
        p.add_argument("--max-silence", dest="max_silence", type=float, help="pauses longer than this many seconds are shortened")
        p.add_argument("--keep-silence", dest="keep_silence", type=float, help="seconds left of a shortened pause")
        p.add_argument("--noise-db", dest="silence_noise_db", type=float, help="level below which audio counts as silence, in dB")

    p = sub.add_parser("measure", help="report loudness, peak and long silences")
    p.add_argument("audio", type=pathlib.Path)
    tuning(p)
    p = sub.add_parser("plan", help="write the cut list; edit nothing")
    p.add_argument("audio", type=pathlib.Path)
    p.add_argument("--out-dir", type=pathlib.Path, help="folder for cuts.json and cuts.txt (default: .mstack/podcast-edit/<name>/)")
    p.add_argument("--fillers", type=pathlib.Path, help="word-timed transcript; turns filler removal on")
    p.add_argument("--filler-words", default="um,uh,erm,er,uhm", help="comma-separated words to treat as fillers (default: um,uh,erm,er,uhm)")
    tuning(p)
    p = sub.add_parser("apply", help="cut, normalise, write a new file and check it")
    p.add_argument("cuts", type=pathlib.Path, help="cuts.json written by plan")
    p.add_argument("--out", type=pathlib.Path, required=True, help="new audio file; the extension chooses the format")
    p.add_argument("--fillers-approved", action="store_true", help="the user agreed to the filler cuts in this list")
    p = sub.add_parser("check", help="measure an edited file against its cut list")
    p.add_argument("out", type=pathlib.Path, help="the edited file")
    p.add_argument("--cuts", type=pathlib.Path, required=True, help="cuts.json the edit was made from")
    args = parser.parse_args()
    return {"measure": cmd_measure, "plan": cmd_plan, "apply": cmd_apply, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
