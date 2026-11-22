#!/usr/bin/env python3
"""Encode a finished video or audio file for a named platform, then measure the result against that platform's preset.

  presets  list the presets, with the date each number was checked and whether it was verified
  plan     measure the source, print the exact ffmpeg command for a preset; encode only with --run, then check
  check    measure any file against a preset: codec, pixel format, resolution, aspect, frame rate, duration,
           file size, sample rate, integrated loudness and true peak

Presets are data in references/presets.json (or a file given with --presets). Each number carries its
source and date. A number not read in a primary source is marked unverified and the script says so.

The picture is fitted inside the preset's frame and padded, never cropped or stretched.
Loudness is normalised in two passes: measured first, then corrected with the measured values.

Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked.
The source is only read. Output goes to the new file named with --out.
"""
import argparse
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PRESETS = HERE.parent / "references" / "presets.json"


def end(code, line):
    print(line)
    return code


def need_ffmpeg():
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        print(f"blocked: {' and '.join(missing)} not found on the path. Install ffmpeg (it includes ffprobe) "
              "with the system's package manager, then run this again.")
        sys.exit(2)


def load_presets(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        assert isinstance(data["presets"], dict) and data["presets"]
    except (OSError, ValueError, KeyError, AssertionError) as exc:
        print(f"blocked: cannot read presets from {path}: {exc!r}")
        sys.exit(2)
    return data


def pick(data, name):
    preset = data["presets"].get(name)
    if preset is None:
        print(f"blocked: no preset named '{name}'. Known presets: {', '.join(sorted(data['presets']))}. "
              "If the platform is not listed, ask the user for its upload spec and add it to a presets file.")
        sys.exit(2)
    return preset


def value(preset, key, default=None):
    entry = preset["limits"].get(key)
    return entry["value"] if entry else default


def unverified_line(name, preset):
    entries = preset["limits"]
    loose = [k for k, v in entries.items() if not v.get("verified")]
    if loose:
        dates = sorted({entries[k].get("checked", "?") for k in loose})
        return (f"note: {len(loose)} of {len(entries)} limits in preset '{name}' are UNVERIFIED (written {', '.join(dates)}, not read in the "
                "platform's own documentation). A pass means the file meets these numbers, not that the platform will accept it.")
    return f"preset '{name}': every limit was verified against its source"


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
    except ValueError:
        return None
    return data if out.returncode == 0 and data.get("streams") else None


def rate(text):
    try:
        a, b = text.split("/")
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError, AttributeError):
        return None


def facts(path):
    """Read what ffprobe reports. Returns None when the file cannot be read."""
    info = probe(path)
    if info is None:
        return None
    video = next((s for s in info["streams"] if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    audio = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    f = {"duration": float(info["format"].get("duration", 0) or 0), "size_mb": pathlib.Path(path).stat().st_size / 1e6,
         "has_video": video is not None, "has_audio": audio is not None}
    if video:
        w, h = int(video.get("width", 0)), int(video.get("height", 0))
        sar = rate(str(video.get("sample_aspect_ratio", "1:1")).replace(":", "/")) or 1.0
        turn = 0
        for side in video.get("side_data_list", []):
            turn = int(abs(float(side.get("rotation", 0)))) if "rotation" in side else turn
        shown_w, shown_h = (h, w * sar) if turn in (90, 270) else (w * sar, h)
        f.update(video_codec=video.get("codec_name"), pixel_format=video.get("pix_fmt"), width=w, height=h,
                 shown_w=round(shown_w), shown_h=round(shown_h), fps=rate(video.get("avg_frame_rate")) or rate(video.get("r_frame_rate")),
                 video_seconds=float(video["duration"]) if "duration" in video else None)
    if audio:
        f.update(audio_codec=audio.get("codec_name"), sample_rate=int(audio.get("sample_rate", 0)),
                 audio_seconds=float(audio["duration"]) if "duration" in audio else None)
    return f


def loudness(path, extra=""):
    """Integrated loudness and true peak, measured by ffmpeg's loudnorm filter. Returns a dict or None."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", f"loudnorm=print_format=json{extra}",
                          "-f", "null", "-"], capture_output=True, text=True)
    blocks = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", out.stderr, re.S)
    if out.returncode != 0 or not blocks:
        return None
    raw = json.loads(blocks[-1])

    def number(key):
        try:
            v = float(raw[key])
        except (KeyError, ValueError):
            return None
        return None if math.isinf(v) or math.isnan(v) else v

    return {"i": number("input_i"), "tp": number("input_tp"), "lra": number("input_lra"), "thresh": number("input_thresh"),
            "offset": number("target_offset")}


def measure(path, preset, data, source_seconds=None):
    """Compare a file with a preset. Returns (rows, failed, unmeasured). Each row: label, measured, limit, verdict."""
    f = facts(path)
    if f is None:
        return None, 0, 0
    rows = []

    def row(label, got, limit, ok):
        rows.append((label, got, limit, "ok" if ok else ("NOT MEASURED" if ok is None else "FAIL")))

    kind = preset.get("kind", "video")
    if kind == "video":
        if not f["has_video"]:
            row("video stream", "none", "one video stream", False)
        else:
            want_w, want_h = value(preset, "width"), value(preset, "height")
            if value(preset, "video_codec"):
                row("video codec", f["video_codec"], value(preset, "video_codec"), f["video_codec"] == value(preset, "video_codec"))
            if value(preset, "pixel_format"):
                row("pixel format", f["pixel_format"], value(preset, "pixel_format"), f["pixel_format"] == value(preset, "pixel_format"))
            if want_w and want_h:
                row("resolution", f"{f['shown_w']}x{f['shown_h']}", f"{want_w}x{want_h}", (f["shown_w"], f["shown_h"]) == (want_w, want_h))
                tol = data.get("aspect_tolerance", {}).get("value", 0.01)
                ratio = f["shown_w"] / f["shown_h"] if f["shown_h"] else 0
                row("aspect (width / height)", f"{ratio:.3f}", f"{want_w / want_h:.3f} +/- {tol}", abs(ratio - want_w / want_h) <= tol)
            if value(preset, "max_fps"):
                fps = f["fps"]
                row("frame rate", f"{fps:.2f}" if fps else "unknown", f"at most {value(preset, 'max_fps')}",
                    None if not fps else fps <= value(preset, "max_fps") + 0.01)
    elif f["has_video"]:
        row("video stream", "present", "none (audio preset)", False)

    lo, hi = value(preset, "min_duration"), value(preset, "max_duration")
    if lo is not None or hi is not None:
        limit = " and ".join(x for x in (f"at least {lo} s" if lo is not None else "", f"at most {hi} s" if hi is not None else "") if x)
        row("duration", f"{f['duration']:.2f} s", limit, (lo is None or f["duration"] >= lo) and (hi is None or f["duration"] <= hi))
    if source_seconds is not None:
        tol = data.get("duration_tolerance", {}).get("value", 0.1)
        row("duration against the source", f"{f['duration']:.3f} s", f"{source_seconds:.3f} s +/- {tol}", abs(f["duration"] - source_seconds) <= tol)
    if value(preset, "max_size_mb") is not None:
        row("file size", f"{f['size_mb']:.2f} MB", f"at most {value(preset, 'max_size_mb')} MB", f["size_mb"] <= value(preset, "max_size_mb"))

    if not f["has_audio"]:
        row("audio stream", "none", "one audio stream", None if kind == "video" else False)
        rows.append(("loudness and true peak", "no audio to measure", "-", "NOT MEASURED" if kind == "video" else "FAIL"))
    else:
        if value(preset, "audio_codec"):
            row("audio codec", f["audio_codec"], value(preset, "audio_codec"), f["audio_codec"] == value(preset, "audio_codec"))
        if value(preset, "sample_rate"):
            row("sample rate", f"{f['sample_rate']} Hz", f"{value(preset, 'sample_rate')} Hz", f["sample_rate"] == value(preset, "sample_rate"))
        if f.get("video_seconds") and f.get("audio_seconds"):
            row("audio length against picture", f"{f['audio_seconds']:.3f} s", f"{f['video_seconds']:.3f} s +/- 0.1",
                abs(f["audio_seconds"] - f["video_seconds"]) <= 0.1)
        loud = loudness(path)
        target, tol, peak = value(preset, "loudness"), value(preset, "loudness_tolerance", 1.0), value(preset, "max_true_peak")
        if loud is None:
            row("integrated loudness", "measurement did not run", f"{target} LUFS", None)
        else:
            if target is not None:
                got = loud["i"]
                row("integrated loudness", "silent or too short to measure" if got is None else f"{got:.1f} LUFS", f"{target} LUFS +/- {tol} LU",
                    False if got is None else abs(got - target) <= tol + 0.05)
            if peak is not None:
                got = loud["tp"]
                row("true peak", "silent" if got is None else f"{got:.1f} dBTP", f"at most {peak} dBTP", True if got is None else got <= peak + 0.05)
    failed = sum(1 for r in rows if r[3] == "FAIL")
    unmeasured = sum(1 for r in rows if r[3] == "NOT MEASURED")
    return rows, failed, unmeasured


def show(path, name, preset, rows, failed, unmeasured):
    print(f"file:   {path}")
    print(f"preset: {name} ({preset.get('about', '')})")
    width = max(len(r[0]) for r in rows)
    for label, got, limit, verdict in rows:
        print(f"  {label:{width}}  {str(got):32} {str(limit):34} {verdict}")
    print(unverified_line(name, preset))
    bad = [r for r in rows if r[3] == "FAIL"]
    if failed:
        return end(1, "RESULT fail: " + "; ".join(f"{r[0]} is {r[1]}, needs {r[2]}" for r in bad[:4]))
    if unmeasured:
        return end(2, "RESULT not verified: " + "; ".join(f"{r[0]} ({r[1]})" for r in rows if r[3] == "NOT MEASURED"))
    return end(0, f"RESULT pass: {len(rows)} measured values are inside preset '{name}'")


def build(source, out, preset, f, loud):
    """The ffmpeg command for this source and preset, using the loudness measured in the first pass."""
    kind = preset.get("kind", "video")
    call = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source)]
    if kind == "video":
        w, h = value(preset, "width"), value(preset, "height")
        chain = [f"scale={w}:{h}:force_original_aspect_ratio=decrease", f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2", "setsar=1"]
        if value(preset, "max_fps") and f.get("fps") and f["fps"] > value(preset, "max_fps") + 0.01:
            chain.append(f"fps={value(preset, 'max_fps')}")
        chain.append(f"format={value(preset, 'pixel_format', 'yuv420p')}")
        call += ["-vf", ",".join(chain), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-movflags", "+faststart"]
    else:
        call += ["-vn"]
    if f["has_audio"]:
        target, peak = value(preset, "loudness"), value(preset, "max_true_peak", -1.0)
        if target is not None and loud and loud["i"] is not None:
            # Aim one dB under the ceiling: a lossy encoder can lift peaks a little after the filter has run.
            lra = min(50, max(11, math.ceil(loud["lra"] or 0) + 1))
            call += ["-af", f"loudnorm=I={target}:TP={peak - 1.0}:LRA={lra}:measured_I={loud['i']}:measured_TP={loud['tp']}:"
                            f"measured_LRA={loud['lra']}:measured_thresh={loud['thresh']}:linear=true"]
        codec = {"aac": ["-c:a", "aac", "-b:a", "192k"], "mp3": ["-c:a", "libmp3lame", "-b:a", "128k"]}.get(value(preset, "audio_codec"), [])
        call += codec + (["-ar", str(value(preset, "sample_rate"))] if value(preset, "sample_rate") else [])
    else:
        call += ["-an"]
    return call + [str(out)]


def cmd_presets(args):
    data = load_presets(args.presets)
    print(data.get("about", ""))
    for name, preset in sorted(data["presets"].items()):
        entries = preset["limits"]
        sure = sum(1 for v in entries.values() if v.get("verified"))
        print(f"\n{name}: {preset.get('about', '')}  [{sure} of {len(entries)} limits verified]")
        for key, v in entries.items():
            print(f"  {key:20} {str(v['value']):>8} {v.get('unit', ''):18} checked {v.get('checked', '?')}  {'verified' if v.get('verified') else 'UNVERIFIED'}")
    return end(0, "RESULT pass: presets listed; nothing was measured")


def cmd_check(args):
    need_ffmpeg()
    data = load_presets(args.presets)
    preset = pick(data, args.preset)
    if not args.file.exists():
        return end(2, f"blocked: {args.file} does not exist")
    source_seconds = None
    if args.source:
        src = facts(args.source)
        if src is None:
            return end(2, f"blocked: {args.source} cannot be read as media")
        source_seconds = src["duration"]
    rows, failed, unmeasured = measure(args.file, preset, data, source_seconds)
    if rows is None:
        return end(1, f"RESULT fail: {args.file} cannot be read as media (empty or damaged)")
    return show(args.file, args.preset, preset, rows, failed, unmeasured)


def cmd_plan(args):
    need_ffmpeg()
    data = load_presets(args.presets)
    preset = pick(data, args.preset)
    f = facts(args.source) if args.source.exists() else None
    if f is None:
        return end(2, f"blocked: {args.source} does not exist or cannot be read as media")
    if preset.get("kind", "video") == "video" and not f["has_video"]:
        return end(2, f"blocked: preset '{args.preset}' is a video preset and {args.source} has no picture")
    if args.out.exists() or args.out.resolve() == args.source.resolve():
        return end(2, f"blocked: {args.out} already exists or is the source; give a new file name so nothing is overwritten")
    if args.out.suffix.lower().lstrip(".") != preset.get("container", "mp4"):
        return end(2, f"blocked: preset '{args.preset}' writes .{preset.get('container', 'mp4')} files; change the --out name")
    loud = loudness(args.source) if f["has_audio"] else None
    print(f"source: {args.source} ({f['duration']:.2f} s, {f['size_mb']:.2f} MB"
          + (f", {f['shown_w']}x{f['shown_h']} {f['video_codec']} at {f['fps']:.2f} fps" if f["has_video"] else "")
          + (f", loudness {loud['i']} LUFS, true peak {loud['tp']} dBTP" if loud else ", no audio") + ")")
    if f["has_video"] and preset.get("kind", "video") == "video":
        want = value(preset, "width") / value(preset, "height")
        have = f["shown_w"] / f["shown_h"]
        if abs(want - have) > 0.01:
            print(f"warning: the source is {f['shown_w']}x{f['shown_h']} and the preset is {value(preset, 'width')}x{value(preset, 'height')}; "
                  "bars will be added to fill the frame. Reframing is a creative choice this script does not make.")
    call = build(args.source, args.out, preset, f, loud)
    print("command:")
    print("  " + " ".join(f"'{a}'" if any(ch in a for ch in " ()[],;=:") and not a.startswith("-") else a for a in call))
    print(unverified_line(args.preset, preset))
    if not args.run:
        return end(2, "RESULT not verified: plan only. Nothing was encoded. Show the command to the user, then run again with --run.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(call, capture_output=True, text=True)
    if done.returncode != 0 or not args.out.exists() or args.out.stat().st_size == 0:
        return end(1, f"RESULT fail: ffmpeg exited {done.returncode} and left no usable file ({done.stderr.strip()[-300:]})")
    rows, failed, unmeasured = measure(args.out, preset, data, f["duration"])
    if rows is None:
        return end(1, f"RESULT fail: {args.out} was written but cannot be read back as media")
    return show(args.out, args.preset, preset, rows, failed, unmeasured)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--presets", type=pathlib.Path, default=PRESETS, help="presets file (default: the one shipped with the skill)")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("presets", help="list presets and how sure each number is")
    p = sub.add_parser("plan", help="print the encode command; run it with --run and check the result")
    p.add_argument("source", type=pathlib.Path, help="the finished file to export (only read)")
    p.add_argument("--preset", required=True)
    p.add_argument("--out", type=pathlib.Path, required=True, help="new file to write")
    p.add_argument("--run", action="store_true", help="encode; without this only the plan is printed")
    p = sub.add_parser("check", help="measure a file against a preset")
    p.add_argument("file", type=pathlib.Path)
    p.add_argument("--preset", required=True)
    p.add_argument("--source", type=pathlib.Path, help="the file it was exported from, to compare length")
    args = parser.parse_args()
    return {"presets": cmd_presets, "plan": cmd_plan, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
