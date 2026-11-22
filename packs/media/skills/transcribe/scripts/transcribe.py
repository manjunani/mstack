#!/usr/bin/env python3
"""Make and check a word-timed transcript of an audio or video file.

  find    look for a transcript that already exists for this file
  audio   extract mono 16 kHz audio into a new file and check the result
  run     transcribe with a local recogniser found on the path, or with an API the user named
  import  convert a recogniser's JSON output into the mstack transcript format
  check   compare the transcript with the voiced time found by silence detection

The transcript format is one JSON file:
  {"format": "mstack-transcript-1", "source": ..., "duration": seconds, "engine": ...,
   "words": [{"word": "hello", "start": 0.52, "end": 0.81, "confidence": 0.93}, ...]}
A plain text file with the same words is written beside it.

Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked (tool missing, bad input, no recogniser).
The source file is only read. Output goes to .mstack/transcribe/ or to --out-dir.
The last line printed is RESULT pass, RESULT fail: ..., RESULT not verified: ... or blocked: ...
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

FORMAT = "mstack-transcript-1"
HERE = pathlib.Path(__file__).resolve().parent
THRESHOLDS = HERE.parent / "references" / "thresholds.json"
# Command names looked for on the path, with the engine each belongs to.
RECOGNISERS = [("whisper-cli", "whisper.cpp"), ("whisper-cpp", "whisper.cpp"), ("whisper", "openai-whisper"),
               ("mlx_whisper", "mlx-whisper"), ("whisperx", "whisperx"), ("faster-whisper", "faster-whisper"),
               ("vosk-transcriber", "vosk")]
DRIVEN = ("whisper.cpp", "openai-whisper")  # engines this script can start itself


def end(code, line):
    print(line)
    return code


def need_ffmpeg():
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        print(f"blocked: {' and '.join(missing)} not found on the path. Install ffmpeg (it includes ffprobe) "
              "with the system's package manager, then run this again.")
        sys.exit(2)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except ValueError:
        return None


def audio_info(path):
    """Return (duration, audio stream) or (None, None) when the file has no readable audio."""
    info = probe(path)
    if not info:
        return None, None
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    try:
        duration = float(info.get("format", {}).get("duration", 0))
    except ValueError:
        duration = 0.0
    if not streams or duration <= 0:
        return None, None
    return duration, streams[0]


def numbers():
    data = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    loose = [k for k, v in data.items() if not v.get("verified")]
    if loose:
        print(f"note: {len(loose)} of {len(data)} thresholds in references/thresholds.json are unverified defaults "
              f"(checked {data[loose[0]]['checked']}); change them there if they do not suit the recording.")
    return {k: v["value"] for k, v in data.items()}


def out_dir(args):
    folder = args.out_dir or pathlib.Path.cwd() / ".mstack" / "transcribe"
    folder.mkdir(parents=True, exist_ok=True)
    if args.out_dir is None:
        ignore = folder.parent / ".gitignore"
        lines = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
        if "transcribe/*.wav" not in lines:
            ignore.write_text("\n".join(lines + ["transcribe/*.wav"]) + "\n", encoding="utf-8")
    return folder


def load_transcript(path):
    """Return (data, problems). Problems are faults in the file itself."""
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [f"cannot read {path}: {exc}"]
    if not isinstance(data, dict) or not isinstance(data.get("words"), list):
        return None, ["no 'words' list: this is not a word-timed transcript"]
    problems, last = [], -1.0
    for i, w in enumerate(data["words"]):
        if not isinstance(w, dict) or not isinstance(w.get("word"), str) or not w["word"].strip():
            problems.append(f"word {i}: no text")
            continue
        s, e = w.get("start"), w.get("end")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (s, e)):
            problems.append(f"word {i} '{w['word']}': start and end must be numbers")
            continue
        if e < s or s < 0:
            problems.append(f"word {i} '{w['word']}': end {e} is before start {s}, or start is negative")
        if s < last - 1e-6:
            problems.append(f"word {i} '{w['word']}': starts at {s}, before the previous word at {last}")
        last = max(last, s)
        c = w.get("confidence")
        if c is not None and not (isinstance(c, (int, float)) and 0 <= c <= 1):
            problems.append(f"word {i} '{w['word']}': confidence {c!r} is not between 0 and 1")
    return data, problems[:20]


def write_transcript(folder, stem, source, duration, engine, words, language=None):
    data = {"format": FORMAT, "source": str(source), "source_bytes": pathlib.Path(source).stat().st_size if source and pathlib.Path(source).exists() else None,
            "duration": round(duration, 3) if duration else None, "language": language, "engine": engine, "words": words}
    target = folder / f"{stem}.transcript.json"
    target.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    text = " ".join(w["word"] for w in words)
    (folder / f"{stem}.transcript.txt").write_text(text + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(words)} words) and {stem}.transcript.txt")
    return target


# ---- converting recogniser output -------------------------------------------------------------

def from_openai_whisper(raw):
    """openai-whisper JSON made with word timestamps: segments[].words[] with word, start, end, probability."""
    words = []
    for segment in raw.get("segments", []):
        for w in segment.get("words", []):
            text = str(w.get("word", "")).strip()
            if text:
                words.append({"word": text, "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3),
                              "confidence": round(float(w["probability"]), 3) if "probability" in w else None})
    return words


def from_whisper_cpp(raw):
    """whisper.cpp full JSON: transcription[].tokens[] with text, offsets in milliseconds, and p.
    Tokens are pieces of words; a token that starts with a space starts a new word."""
    words = []
    for segment in raw.get("transcription", []):
        for token in segment.get("tokens", []):
            text = str(token.get("text", ""))
            if not text.strip() or re.fullmatch(r"\s*\[_[A-Z]+_?\d*\]\s*", text):
                continue
            off = token.get("offsets", {})
            start, stop, p = off.get("from", 0) / 1000.0, off.get("to", 0) / 1000.0, token.get("p")
            if text.startswith(" ") or not words:
                words.append({"word": text.strip(), "start": round(start, 3), "end": round(stop, 3), "confidence": p})
            else:
                last = words[-1]
                last["word"] += text.strip()
                last["end"] = round(stop, 3)
                if p is not None and last["confidence"] is not None:
                    last["confidence"] = min(last["confidence"], p)
    for w in words:
        if w["confidence"] is not None:
            w["confidence"] = round(float(w["confidence"]), 3)
    return words


def from_api(raw):
    """A response with a top-level words[] list of word, start, end (confidence is usually absent)."""
    words = []
    for w in raw.get("words", []):
        text = str(w.get("word", "")).strip()
        if text:
            c = w.get("confidence", w.get("probability"))
            words.append({"word": text, "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3),
                          "confidence": round(float(c), 3) if c is not None else None})
    return words


SHAPES = {"openai-whisper": from_openai_whisper, "whisper.cpp": from_whisper_cpp, "api-words": from_api}


def guess_shape(raw):
    if isinstance(raw, dict):
        if isinstance(raw.get("words"), list) and raw.get("format") != FORMAT:
            return "api-words"
        if isinstance(raw.get("transcription"), list):
            return "whisper.cpp"
        if isinstance(raw.get("segments"), list):
            return "openai-whisper"
    return None


def convert(raw, shape):
    shape = shape or guess_shape(raw)
    if shape not in SHAPES:
        return None, "cannot tell which recogniser wrote this JSON; name it with --shape"
    try:
        words = SHAPES[shape](raw)
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"the JSON does not have the {shape} shape ({exc!r})"
    if not words:
        return None, f"no timed words in the JSON (shape {shape}); was the recogniser run with word timestamps on?"
    return words, shape


# ---- commands ---------------------------------------------------------------------------------

def cmd_find(args):
    media = args.media
    if not media.exists():
        return end(2, f"blocked: {media} does not exist")
    stem = media.stem
    places = [media.with_name(media.name + ".transcript.json"), media.with_name(stem + ".transcript.json"),
              pathlib.Path.cwd() / ".mstack" / "transcribe" / f"{stem}.transcript.json"]
    size = media.stat().st_size
    for place in places:
        if not place.exists():
            continue
        data, problems = load_transcript(place)
        if data is None or problems:
            print(f"found {place}, but it is not usable: {(problems or ['unreadable'])[0]}")
            continue
        if data.get("source_bytes") not in (None, size):
            print(f"found {place}, but it was made from a file of {data['source_bytes']} bytes; this one is {size}. Treat it as stale.")
            continue
        print(f"found {place}: {len(data['words'])} words, engine {data.get('engine')}")
        return end(0, "RESULT pass: a word-timed transcript exists; run check on it before using it")
    others = [p for p in (media.with_suffix(ext) for ext in (".srt", ".vtt", ".txt", ".json")) if p.exists() and p != media]
    for other in others:
        print(f"also present: {other.name} (no word timings in the mstack format; it cannot stand in for a transcript)")
    return end(2, "RESULT not verified: no usable word-timed transcript for this file yet")


def cmd_audio(args):
    need_ffmpeg()
    media = args.media
    duration, stream = audio_info(media)
    if duration is None:
        return end(2, f"blocked: {media} has no readable audio stream")
    folder = out_dir(args)
    target = folder / f"{media.stem}.16k.wav"
    if target.resolve() == media.resolve():
        return end(2, "blocked: the output would replace the input; choose another --out-dir")
    done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(media), "-vn", "-ac", "1",
                           "-ar", "16000", "-c:a", "pcm_s16le", str(target)], capture_output=True, text=True)
    got, out_stream = audio_info(target) if target.exists() else (None, None)
    print(f"source: {media} ({duration:.2f} s, {stream.get('codec_name')}, {stream.get('sample_rate')} Hz, {stream.get('channels')} ch)")
    if done.returncode != 0 or got is None:
        return end(1, f"RESULT fail: ffmpeg did not produce readable audio ({done.stderr.strip()[-200:] or 'no error text'})")
    print(f"wrote:  {target} ({got:.2f} s, {out_stream.get('sample_rate')} Hz, {out_stream.get('channels')} ch)")
    faults = []
    if out_stream.get("sample_rate") != "16000" or out_stream.get("channels") != 1:
        faults.append("output is not mono 16 kHz")
    if abs(got - duration) > 0.1:
        faults.append(f"output is {got:.2f} s but the source is {duration:.2f} s")
    if faults:
        return end(1, "RESULT fail: " + "; ".join(faults))
    return end(0, "RESULT pass")


def find_recogniser(wanted=None):
    found = [(cmd, engine) for cmd, engine in RECOGNISERS if shutil.which(cmd)]
    if wanted:
        found = [f for f in found if wanted in f]
    return found


def call_api(args, wav):
    """Send the extracted audio to the address the user gave. Returns (raw JSON, None) or (None, why)."""
    key = os.environ.get(args.api_key_env or "", "")
    if not key:
        return None, f"the environment variable named by --api-key-env ({args.api_key_env}) is empty"
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("model", args.api_model), ("response_format", "verbose_json"), ("timestamp_granularities[]", "word")):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{wav.name}"\r\n'
                 "Content-Type: audio/wav\r\n\r\n".encode() + wav.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(args.api_url, data=b"".join(parts), method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as reply:
            return json.loads(reply.read().decode("utf-8")), None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"the request to {args.api_url} failed: {exc}. It was sent once and is not retried, because a failed call can still be billed."


def cmd_run(args):
    need_ffmpeg()
    media = args.media
    duration, _ = audio_info(media)
    if duration is None:
        return end(2, f"blocked: {media} has no readable audio stream")
    folder = out_dir(args)
    wav = folder / f"{media.stem}.16k.wav"

    if args.api_url:
        megabytes = duration * 32000 / 1e6
        print(f"upload planned: {duration / 60:.1f} minutes of audio, about {megabytes:.1f} MB, to {args.api_url}")
        print("the price is set by that service; this script does not know it")
        if not args.allow_upload:
            return end(2, "blocked: uploading needs the user's yes. Tell them the destination and the length above, "
                          "then run again with --allow-upload")
        if not os.environ.get(args.api_key_env or "", ""):
            return end(2, f"blocked: the environment variable named by --api-key-env ({args.api_key_env}) is empty; "
                          "the user sets it in their own shell, never in chat")
        if cmd_audio(args) != 0:
            return 1
        raw, why = call_api(args, wav)
        if raw is None:
            return end(2, f"RESULT not verified: {why}")
        words, shape = convert(raw, "api-words")
        engine = f"api:{args.api_url}"
    else:
        found = find_recogniser(args.engine)
        if not found:
            names = ", ".join(cmd for cmd, _ in RECOGNISERS)
            return end(2, f"blocked: no speech recogniser on the path (looked for: {names}). Ask the user to install one "
                          "they trust, or to name an API with --api-url, --api-key-env and --allow-upload. "
                          "A transcript made elsewhere can be brought in with: transcribe.py import <file>")
        usable = [f for f in found if f[1] in DRIVEN]
        if not usable:
            return end(2, f"blocked: found {found[0][0]} ({found[0][1]}), which this version cannot start itself. Run it "
                          "with word timestamps and JSON output, then use: transcribe.py import <file>")
        command, engine = usable[0]
        if not args.model:
            return end(2, f"blocked: {command} needs a model. Ask the user which one, and pass it with --model")
        if not pathlib.Path(args.model).exists() and not args.allow_model_download:
            return end(2, f"blocked: --model {args.model} is not a file on disk, so {command} may download it. "
                          "Ask the user, then run again with --allow-model-download")
        if cmd_audio(args) != 0:
            return 1
        if engine == "whisper.cpp":
            prefix = folder / f"{media.stem}.raw"
            call = [command, "-m", args.model, "-f", str(wav), "-ojf", "-of", str(prefix)]
            raw_path = pathlib.Path(str(prefix) + ".json")
        else:
            call = [command, str(wav), "--model", args.model, "--word_timestamps", "True",
                    "--output_format", "json", "--output_dir", str(folder)]
            raw_path = folder / f"{wav.stem}.json"
        if args.language:
            call += ["-l", args.language] if engine == "whisper.cpp" else ["--language", args.language]
        print("running: " + " ".join(call), flush=True)
        done = subprocess.run(call, capture_output=True, text=True)
        if done.returncode != 0 or not raw_path.exists():
            return end(1, f"RESULT fail: {command} exited {done.returncode} and wrote no JSON ({done.stderr.strip()[-300:]})")
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        words, shape = convert(raw, engine)
    if words is None:
        return end(1, f"RESULT fail: {shape}")
    target = write_transcript(folder, media.stem, media, duration, engine, words, args.language)
    args.transcript, args.media = target, media
    return cmd_check(args)


def cmd_import(args):
    try:
        raw = json.loads(args.raw.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return end(2, f"blocked: cannot read {args.raw}: {exc}")
    words, shape = convert(raw, args.shape)
    if words is None:
        return end(1, f"RESULT fail: {shape}")
    duration = None
    if args.media:
        need_ffmpeg()
        duration, _ = audio_info(args.media)
        if duration is None:
            return end(2, f"blocked: {args.media} has no readable audio stream")
    stem = args.media.stem if args.media else args.raw.stem
    write_transcript(out_dir(args), stem, args.media or "", duration, f"imported:{shape}", words)
    if not args.media:
        return end(2, "RESULT not verified: converted, but not compared with the recording (no --media given)")
    return end(0, "RESULT pass: converted; now run check against the recording")


def silences(media, noise_db, min_len, duration):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(media), "-vn", "-af",
                          f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"], capture_output=True, text=True)
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


def invert(spans, duration):
    out, at = [], 0.0
    for s, e in spans:
        if s > at:
            out.append((at, s))
        at = max(at, e)
    if at < duration:
        out.append((at, duration))
    return out


def merge(spans, bridge):
    out = []
    for s, e in sorted(spans):
        if out and s - out[-1][1] <= bridge:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def subtract(spans, holes):
    out = []
    for s, e in spans:
        at = s
        for hs, he in holes:
            if he <= at or hs >= e:
                continue
            if hs > at:
                out.append((at, hs))
            at = max(at, he)
        if at < e:
            out.append((at, e))
    return out


def clock(t):
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def cmd_check(args):
    need_ffmpeg()
    data, problems = load_transcript(args.transcript)
    if data is None:
        return end(2, f"blocked: {problems[0]}")
    duration, _ = audio_info(args.media)
    if duration is None:
        return end(2, f"blocked: {args.media} has no readable audio stream")
    n = numbers()
    words = [w for w in data["words"] if isinstance(w, dict) and isinstance(w.get("start"), (int, float)) and isinstance(w.get("end"), (int, float))]
    late = [w for w in words if w["end"] > duration + 0.5]
    if late:
        problems.append(f"{len(late)} words end after the recording does ({duration:.2f} s); first: '{late[0]['word']}' at {late[0]['end']}")
    quiet = silences(args.media, n["silence_noise_db"], n["silence_min_seconds"], duration)
    if quiet is None:
        return end(2, "RESULT not verified: silence detection did not run on this file")
    voiced = invert(quiet, duration)
    voiced_total = sum(e - s for s, e in voiced)
    pad = n["word_pad_seconds"]
    spoken = merge([(max(0.0, w["start"] - pad), min(duration, w["end"] + pad)) for w in words], n["bridge_gap_seconds"])
    missed = subtract(voiced, spoken)
    missed_total = sum(e - s for s, e in missed)
    coverage = 1.0 if voiced_total == 0 else 1 - missed_total / voiced_total
    in_silence = [w for w in words if any(s + pad <= (w["start"] + w["end"]) / 2 <= e - pad for s, e in quiet)]
    scored = [w for w in words if w.get("confidence") is not None]
    low = [w for w in scored if w["confidence"] < n["low_confidence"]]

    print(f"recording:   {args.media} ({duration:.2f} s)")
    print(f"transcript:  {args.transcript} ({len(words)} words, engine {data.get('engine')})")
    print(f"voiced time: {voiced_total:.2f} s in {len(voiced)} stretches (silence = below {n['silence_noise_db']} dB for {n['silence_min_seconds']} s)")
    print(f"coverage:    {coverage:.1%} of voiced time has words (needs {n['min_coverage']:.0%})")
    long_gaps = [(s, e) for s, e in missed if e - s > n["max_voiced_gap_seconds"]]
    for s, e in sorted(missed, key=lambda x: x[0] - x[1])[:8]:
        if e - s >= 0.5:
            print(f"  voiced, no words: {clock(s)} to {clock(e)} ({e - s:.1f} s)")
    if in_silence:
        print(f"words placed in silence: {len(in_silence)} (possible invented text); first: " +
              ", ".join(f"'{w['word']}' at {clock(w['start'])}" for w in in_silence[:5]))
    if scored:
        print(f"low confidence (< {n['low_confidence']}): {len(low)} of {len(scored)} scored words")
        for w in low[:40]:
            print(f"  {clock(w['start'])}  {w['word']}  ({w['confidence']})")
        if len(low) > 40:
            print(f"  ... and {len(low) - 40} more")
    for p in problems:
        print(f"file fault: {p}")

    faults = list(problems[:3])
    if voiced_total >= 0.5 and not words:
        faults.append("the recording has voiced audio but the transcript has no words")
    if coverage < n["min_coverage"]:
        faults.append(f"coverage {coverage:.1%} is below {n['min_coverage']:.0%}")
    if long_gaps:
        faults.append(f"{len(long_gaps)} voiced stretch(es) longer than {n['max_voiced_gap_seconds']} s have no words, first at {clock(long_gaps[0][0])}")
    if words and len(in_silence) > len(words) / 2:
        faults.append(f"{len(in_silence)} of {len(words)} words sit in silence")
    if faults:
        return end(1, "RESULT fail: " + "; ".join(faults))
    if not words:
        return end(0, "RESULT pass: nothing spoken was found, and the transcript is empty")
    if not scored:
        return end(2, "RESULT not verified: coverage passed, but the engine reported no word confidence, so doubtful words cannot be listed")
    return end(0, f"RESULT pass: coverage {coverage:.1%}, {len(low)} low-confidence words listed")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)

    def common(p, media=True):
        if media:
            p.add_argument("media", type=pathlib.Path, help="the audio or video file (only read)")
        p.add_argument("--out-dir", type=pathlib.Path, help="folder for output (default: .mstack/transcribe in the current folder)")

    p = sub.add_parser("find", help="look for an existing transcript")
    p.add_argument("media", type=pathlib.Path)
    p = sub.add_parser("audio", help="extract mono 16 kHz audio and check it")
    common(p)
    p = sub.add_parser("run", help="transcribe with a recogniser on the path, or with a named API")
    common(p)
    p.add_argument("--engine", help="command name or engine to use when several are installed")
    p.add_argument("--model", help="model name or file for the local recogniser")
    p.add_argument("--allow-model-download", action="store_true", help="the user agreed that the recogniser may download its model")
    p.add_argument("--language", help="language code, when the user knows it")
    p.add_argument("--api-url", help="transcription address the user gave; the audio is sent there")
    p.add_argument("--api-key-env", help="NAME of the environment variable that holds the key (the key itself is never an argument)")
    p.add_argument("--api-model", default="whisper-1", help="model name sent to the API (default whisper-1)")
    p.add_argument("--allow-upload", action="store_true", help="the user said yes to sending the audio to --api-url")
    p.add_argument("--timeout", type=int, default=600, help="seconds allowed for the API call (default 600)")
    p = sub.add_parser("import", help="convert recogniser JSON into the mstack format")
    p.add_argument("raw", type=pathlib.Path, help="JSON written by a recogniser")
    p.add_argument("--shape", choices=sorted(SHAPES), help="which recogniser wrote it (default: guessed)")
    p.add_argument("--media", type=pathlib.Path, help="the recording, to record its length")
    common(p, media=False)
    p = sub.add_parser("check", help="compare a transcript with the recording")
    p.add_argument("transcript", type=pathlib.Path)
    p.add_argument("--media", type=pathlib.Path, required=True, help="the recording the transcript belongs to")
    args = parser.parse_args()
    return {"find": cmd_find, "audio": cmd_audio, "run": cmd_run, "import": cmd_import, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
