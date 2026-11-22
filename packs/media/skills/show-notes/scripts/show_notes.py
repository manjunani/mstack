#!/usr/bin/env python3
"""Check chapters and quotes in show notes against the word-timed transcript, then write the notes out.

  check   chapters start at zero, ascend, are long enough and stay inside the recording;
          every quoted line is in the transcript word for word; prints what is spoken at each chapter start
  render  run the same checks, and only if they pass write show-notes.md, chapters.txt and chapters.ffmetadata

The notes are a JSON file the writer fills in:
  {"title": "...", "summary": "...",
   "chapters": [{"start": 0, "title": "Welcome"}, {"start": "12:40", "title": "Pricing"}],
   "quotes": [{"text": "words exactly as spoken", "speaker": "optional name"}]}
A start is seconds, or a clock time such as 12:40 or 1:02:03.

A quote matches when its words appear in the transcript in the same order with nothing added, dropped or
changed. Letter case and punctuation are ignored, because the recogniser guessed those.
The script does not judge whether the summary is good or the chapter titles are apt.

Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked.
"""
import argparse
import difflib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
LIMITS = HERE.parent / "references" / "limits.json"


def end(code, line):
    print(line)
    return code


def seconds(value):
    if isinstance(value, bool):
        raise ValueError("not a time")
    if isinstance(value, (int, float)):
        return float(value)
    parts = [float(p) for p in str(value).strip().split(":")]
    if not 1 <= len(parts) <= 3 or any(p < 0 for p in parts):
        raise ValueError("not a time")
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def clock(t, hours):
    t = int(round(t))
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if hours else f"{t // 60:02d}:{t % 60:02d}"


def plain(token):
    return re.sub(r"^\W+|\W+$", "", token.replace("’", "'").casefold())


def load(args):
    """Return (notes, words, duration, limits) or exit with blocked."""
    try:
        notes = json.loads(args.notes.read_text(encoding="utf-8"))
        assert isinstance(notes, dict)
    except (OSError, ValueError, AssertionError) as exc:
        print(f"blocked: cannot read the notes file {args.notes}: {exc!r}")
        sys.exit(2)
    try:
        data = json.loads(args.transcript.read_text(encoding="utf-8"))
        words = data["words"]
        assert isinstance(words, list) and all(isinstance(w["word"], str) and w["end"] >= w["start"] >= 0 for w in words)
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        print(f"blocked: {args.transcript} is not a word-timed transcript ({exc!r}). Make one with the transcribe skill.")
        sys.exit(2)
    if not words:
        print("blocked: the transcript has no words, so there is nothing to check notes against")
        sys.exit(2)
    duration = args.duration or data.get("duration")
    if not duration:
        duration = words[-1]["end"]
        print(f"note: the transcript does not record the length of the recording; using the end of the last word ({duration:.1f} s)")
    raw = json.loads(LIMITS.read_text(encoding="utf-8"))
    lim = {k: v["value"] for k, v in raw.items()}
    loose = [k for k, v in raw.items() if not v.get("verified")]
    for key in ("min_chapter_seconds", "min_chapters"):
        if getattr(args, key, None) is not None:
            lim[key] = getattr(args, key)
    if loose:
        print(f"note: {len(loose)} of {len(raw)} limits in references/limits.json are unverified (written {raw[loose[0]]['checked']} from memory); "
              "check the platform's own rules, or pass --min-chapter-seconds and --min-chapters.")
    return notes, words, float(duration), lim


def check_chapters(notes, words, duration, lim):
    faults, warnings, rows = [], [], []
    chapters = notes.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return ["the notes have no chapters"], warnings, rows
    hours = duration >= 3600
    starts = []
    for i, ch in enumerate(chapters, 1):
        title = str(ch.get("title", "")).strip() if isinstance(ch, dict) else ""
        try:
            start = seconds(ch["start"])
        except (KeyError, TypeError, ValueError):
            faults.append(f"chapter {i}: start {ch.get('start') if isinstance(ch, dict) else ch!r} is not a time")
            continue
        if not title:
            faults.append(f"chapter {i} at {clock(start, hours)}: no title")
        elif len(title) > lim["max_title_chars"]:
            warnings.append(f"chapter {i} title is {len(title)} characters (over {lim['max_title_chars']}); players may cut it off")
        starts.append((i, start, title))
    if faults:
        return faults, warnings, rows
    if starts[0][1] != 0:
        faults.append(f"the first chapter starts at {clock(starts[0][1], hours)} ({starts[0][1]} s); it has to start at zero")
    if len(starts) < lim["min_chapters"]:
        faults.append(f"{len(starts)} chapter(s); at least {lim['min_chapters']} are needed")
    titles = [t.casefold() for _, _, t in starts]
    for i, _, t in starts:
        if titles.count(t.casefold()) > 1 and titles.index(t.casefold()) != i - 1:
            faults.append(f"chapter {i}: the title '{t}' is used twice")
    for n, (i, start, title) in enumerate(starts):
        nxt = starts[n + 1][1] if n + 1 < len(starts) else duration
        if start >= duration:
            faults.append(f"chapter {i} '{title}' starts at {clock(start, hours)}, after the recording ends ({clock(duration, hours)})")
            continue
        if n + 1 < len(starts) and nxt <= start:
            faults.append(f"chapter {i + 1} starts at {clock(nxt, hours)}, not after chapter {i} at {clock(start, hours)}")
            continue
        if min(nxt, duration) - start < lim["min_chapter_seconds"]:
            faults.append(f"chapter {i} '{title}' is {min(nxt, duration) - start:.0f} s long; the minimum is {lim['min_chapter_seconds']} s")
        heard = " ".join(w["word"] for w in words if start - 0.5 <= w["start"] < start + 8)[:70]
        rows.append((start, title, heard or "(no speech in the 8 s after this point)"))
    return faults, warnings, rows


def find_quote(tokens, said):
    """Return the index in said where tokens start, or -1."""
    n = len(tokens)
    for i in range(len(said) - n + 1):
        if said[i] == tokens[0] and said[i:i + n] == tokens:
            return i
    return -1


def nearest(tokens, said, raw_words):
    """The stretch of transcript most like the quote, for the failure message."""
    n, best = len(tokens), (0.0, 0)
    step = max(1, n // 4)
    for i in range(0, max(1, len(said) - n + 1), step):
        score = difflib.SequenceMatcher(None, tokens, said[i:i + n], autojunk=False).ratio()
        if score > best[0]:
            best = (score, i)
    lo = max(0, best[1] - step)
    best = max(((difflib.SequenceMatcher(None, tokens, said[i:i + n], autojunk=False).ratio(), i) for i in range(lo, min(len(said), best[1] + step + 1))),
               default=best)
    return best[0], " ".join(w["word"] for w in raw_words[best[1]:best[1] + n]), raw_words[best[1]]["start"] if raw_words else 0.0


def check_quotes(notes, words, duration):
    faults, rows = [], []
    quotes = notes.get("quotes") or []
    kept = [w for w in words if plain(w["word"])]
    said = [plain(w["word"]) for w in kept]
    hours = duration >= 3600
    for i, q in enumerate(quotes, 1):
        text = (q.get("text") if isinstance(q, dict) else q) or ""
        tokens = [t for t in (plain(x) for x in str(text).split()) if t]
        if not tokens:
            faults.append(f"quote {i}: empty")
            continue
        at = find_quote(tokens, said)
        if at >= 0:
            q_start = kept[at]["start"]
            rows.append((q_start, str(text), q.get("speaker") if isinstance(q, dict) else None))
            continue
        score, closest, when = nearest(tokens, said, kept)
        detail = f"closest passage, at {clock(when, hours)}: \"{closest}\"" if score >= 0.5 else "nothing similar was said"
        faults.append(f"quote {i} is not in the transcript word for word: \"{str(text)[:70]}\"; {detail}")
    return faults, rows


def run_checks(args):
    notes, words, duration, lim = load(args)
    hours = duration >= 3600
    c_faults, warnings, chapters = check_chapters(notes, words, duration, lim)
    q_faults, quotes = check_quotes(notes, words, duration)
    print(f"recording: {clock(duration, hours)} ({duration:.1f} s), {len(words)} words")
    print(f"chapters: {len(notes.get('chapters') or [])}")
    for start, title, heard in chapters:
        print(f"  {clock(start, hours)}  {title}\n           spoken there: \"{heard}\"")
    print(f"quotes: {len(notes.get('quotes') or [])}, found word for word: {len(quotes)}")
    for start, text, _ in quotes:
        print(f"  {clock(start, hours)}  \"{text[:70]}\"")
    for w in warnings:
        print("  warning: " + w)
    for f in c_faults + q_faults:
        print("  FAIL " + f)
    return notes, duration, chapters, quotes, c_faults + q_faults


def cmd_check(args):
    notes, duration, chapters, quotes, faults = run_checks(args)
    if faults:
        return end(1, f"RESULT fail: {len(faults)} fault(s); first: {faults[0]}")
    print("read the 'spoken there' lines: the script cannot tell whether a title fits what is said, or whether the summary is fair")
    return end(0, f"RESULT pass: {len(chapters)} chapters are in order and inside the recording; {len(quotes)} quote(s) match the transcript")


def cmd_render(args):
    targets = [args.out_dir / n for n in ("show-notes.md", "chapters.txt", "chapters.ffmetadata")]
    if any(t.exists() for t in targets):
        return end(2, f"blocked: {args.out_dir} already holds show notes; name a new --out-dir so nothing is overwritten")
    notes, duration, chapters, quotes, faults = run_checks(args)
    if faults:
        return end(1, f"RESULT fail: nothing was written. {len(faults)} fault(s); first: {faults[0]}")
    hours = duration >= 3600
    args.out_dir.mkdir(parents=True, exist_ok=True)
    md = [f"# {notes.get('title', 'Show notes')}", ""]
    if notes.get("summary"):
        md += [str(notes["summary"]).strip(), ""]
    md += ["## Chapters", ""] + [f"- {clock(s, hours)} {t}" for s, t, _ in chapters] + [""]
    if quotes:
        md += ["## Quotes", ""] + [f"- \"{text}\"" + (f" ({who}, {clock(s, hours)})" if who else f" ({clock(s, hours)})") for s, text, who in quotes] + [""]
    targets[0].write_text("\n".join(md), encoding="utf-8")
    targets[1].write_text("".join(f"{clock(s, hours)} {t}\n" for s, t, _ in chapters), encoding="utf-8")
    meta = [";FFMETADATA1"]
    for n, (s, t, _) in enumerate(chapters):
        stop = chapters[n + 1][0] if n + 1 < len(chapters) else duration
        safe = re.sub(r"([=;#\\])", r"\\\1", t)
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(s * 1000)}", f"END={int(stop * 1000)}", f"title={safe}"]
    targets[2].write_text("\n".join(meta) + "\n", encoding="utf-8")
    print(f"wrote {targets[0]}, chapters.txt and chapters.ffmetadata")
    return end(0, f"RESULT pass: {len(chapters)} chapters and {len(quotes)} quote(s) checked and written; the summary's wording was not checked")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    for name, text in (("check", "check chapters and quotes"), ("render", "check, then write the notes files")):
        p = sub.add_parser(name, help=text)
        p.add_argument("notes", type=pathlib.Path, help="the notes JSON file")
        p.add_argument("--transcript", type=pathlib.Path, required=True, help="word-timed transcript JSON")
        p.add_argument("--duration", type=float, help="length of the recording in seconds, when the transcript does not record it")
        p.add_argument("--min-chapter-seconds", dest="min_chapter_seconds", type=float, help="shortest chapter allowed")
        p.add_argument("--min-chapters", dest="min_chapters", type=int, help="fewest chapters allowed")
        if name == "render":
            p.add_argument("--out-dir", type=pathlib.Path, required=True, help="new folder for the notes files")
    args = parser.parse_args()
    return {"check": cmd_check, "render": cmd_render}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
