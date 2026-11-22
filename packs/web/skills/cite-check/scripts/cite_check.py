#!/usr/bin/env python3
"""Check that every quote in a document appears in the saved copy of the source it cites.

  cite_check.py draft.md --sources sources/                 check every quoted passage in the draft
  cite_check.py draft.md --sources sources/ --claims claims.json
                                                            also check a list of claims, each with its supporting quote
  cite_check.py draft.md --sources sources/ --min-words 5   ignore quoted phrases shorter than this (default 3 words)
  cite_check.py draft.md --sources sources/ --json out.json also write the three lists to a new file

The document: Markdown or plain text. A quote is text inside "double quotes" (straight or curly) or a
block of lines starting with ">". Its source is the reference nearest after it in the same paragraph:
a key such as [S1] or [^3], a Markdown link, or a bare address.

The sources folder: saved copies as .txt, .md, .html, or the .json written by page-extract. A key finds
the file with the same name (S1 -> S1.txt). An optional index.json maps keys and addresses to files:
  {"S1": {"file": "harbour-report.txt", "url": "https://example.org/report"}}

The claims file (optional): a JSON list. Each entry has "claim", "source", "verdict" and, for the first
three verdicts, the exact "quote" that decides it:
  supported, partly, contradicted   need a quote that is in the saved source
  absent                            the source does not speak to the claim (reported as not found)
  unreachable                       no copy of the source could be saved (reported as source missing)

Matching ignores differences in spacing, line breaks, curly or straight quote marks and dash style.
An ellipsis in a quote splits it into parts that must appear in that order. Nothing is fetched.

What this proves: the quoted words are in the saved copy. It does not prove the source is right, or
that the quote supports the sentence around it.

Exit codes: 0 = every quote and claim was found in its source
            1 = fail: at least one quote is not in its source, or a claim entry is unsupported or malformed
            2 = not verified or blocked: a saved source is missing, nothing to check was found, bad input
"""
import argparse
import difflib
import html.parser
import json
import pathlib
import re
import sys
import unicodedata

REF = re.compile(r"\[[^\]\n]*\]\((https?://[^)\s]+)\)|\[\^?([A-Za-z0-9][\w.-]{0,40})\](?!\()|(https?://[^\s)>\]]+)")
INLINE = re.compile(r"\"([^\"\n]{8,1500})\"|“([^”]{8,1500})”")
ELLIPSIS = re.compile(r"\s*(?:\[\s*(?:\.\.\.|…)\s*\]|\.\.\.+|…)\s*")
NEED_QUOTE = ("supported", "partly", "contradicted")
VERDICTS = NEED_QUOTE + ("absent", "unreachable")
SWAPS = str.maketrans({"‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
                       "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-", " ": " ", "­": None, "*": None, "`": None})


QUOTE_MARKS = str.maketrans({'"': None})


def norm(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).translate(SWAPS)).strip()


def bare(text):
    """For matching only: quote marks inside a quote or a source do not decide whether the words are there."""
    return re.sub(r"\s+", " ", norm(text).translate(QUOTE_MARKS)).strip()


class Text(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pieces, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in ("script", "style")
        self.pieces.append(" ")

    def handle_endtag(self, tag):
        self.skip = max(0, self.skip - (tag in ("script", "style")))
        self.pieces.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.pieces.append(data)


def read_source(path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".html", ".htm"):
        parser = Text()
        parser.feed(raw)
        raw = "".join(parser.pieces)
    elif path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and isinstance(data.get("text"), str):
                raw = f"{data.get('title', '')}\n{data['text']}"
        except ValueError:
            pass
    return norm(raw)[:2_000_000]


class Sources:
    def __init__(self, folder):
        self.folder, self.cache = folder, {}
        self.index, index = {}, folder / "index.json"
        if index.exists():
            for key, entry in json.loads(index.read_text(encoding="utf-8")).items():
                entry = {"file": entry} if isinstance(entry, str) else entry
                self.index[key.lower()] = entry["file"]
                if entry.get("url"):
                    self.index[self.address(entry["url"])] = entry["file"]
        self.stems = {path.stem.lower(): path.name for path in sorted(folder.iterdir()) if path.is_file() and path.name != "index.json"}

    @staticmethod
    def address(url):
        return url.split("#")[0].rstrip("/").lower()

    def text(self, reference):
        """Return (text, file name) or (None, reason)."""
        key = self.address(reference) if reference.lower().startswith("http") else reference.lower()
        name = self.index.get(key) or self.stems.get(key)
        if not name:
            return None, f"no saved copy for '{reference}' in {self.folder}"
        path = self.folder / name
        if not path.is_file():
            return None, f"index.json names {name} for '{reference}', but that file does not exist"
        if name not in self.cache:
            self.cache[name] = read_source(path)
        if len(self.cache[name]) < 20:
            return None, f"the saved copy {name} is empty"
        return self.cache[name], name


def locate(quote, source):
    """Return (found, note). Parts split by an ellipsis must appear in order."""
    source = bare(source)
    parts = [part.strip(" .,;:!?") for part in ELLIPSIS.split(bare(quote))]
    parts = [part for part in parts if part]
    if not parts:
        return False, "the quote is empty"
    for haystack, needles, note in ((source, parts, ""), (source.lower(), [part.lower() for part in parts], "letter case differs from the source")):
        position = 0
        for needle in needles:
            position = haystack.find(needle, position)
            if position < 0:
                break
            position += len(needle)
        else:
            return True, note
    whole = " ".join(parts).lower()
    match = difflib.SequenceMatcher(None, source[:300_000].lower(), whole, autojunk=False).find_longest_match(0, min(len(source), 300_000), 0, len(whole))
    if match.size >= 12:
        return False, f"longest run that does match: {match.size} of {len(whole)} characters: '{whole[match.b:match.b + match.size][:80]}'"
    return False, "no run of 12 or more characters matches"


def first_ref(text):
    match = REF.search(text)
    return (match.group(1) or match.group(2) or match.group(3)).rstrip(".,;") if match else None


def quotes_in(document):
    """Yield (line number, quote, reference or None) and count short quoted phrases that were skipped."""
    text = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), document, flags=re.S)
    blocks, current, start = [], [], 1
    for number, line in enumerate(text.split("\n") + [""], 1):
        if line.strip():
            if not current:
                start = number
            current.append(line)
        elif current:
            blocks.append((start, current))
            current = []
    found = []
    for index, (start, lines) in enumerate(blocks):
        if all(line.lstrip().startswith(">") for line in lines):
            body = [line.lstrip()[1:].strip() for line in lines]
            reference = first_ref("\n".join(body))
            quote = " ".join(line for line in body if line and not re.match(r"^(—|--|-)\s", line))
            quote = REF.sub("", quote).strip()
            if reference is None and index + 1 < len(blocks):
                reference = first_ref("\n".join(blocks[index + 1][1])[:120])
            if reference is None and index > 0:
                refs = REF.findall("\n".join(blocks[index - 1][1]))
                reference = next((item for item in reversed(refs[-1]) if item), None) if refs else None
            found.append((start, quote, reference))
            continue
        paragraph = "\n".join(lines)
        for match in INLINE.finditer(paragraph):
            quote = match.group(1) or match.group(2)
            after, before = first_ref(paragraph[match.end():]), REF.findall(paragraph[:match.start()])
            reference = after or (next((item for item in reversed(before[-1]) if item), None) if before else None)
            found.append((start + paragraph[:match.start()].count("\n"), quote, reference))
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("document", type=pathlib.Path, help="the draft, report or notes that hold the quotes")
    parser.add_argument("--sources", type=pathlib.Path, required=True, help="folder of saved source copies")
    parser.add_argument("--claims", type=pathlib.Path, help="JSON list of claims with source, verdict and quote")
    parser.add_argument("--min-words", type=int, default=3, help="quoted phrases with fewer words are not treated as quotes (default 3)")
    parser.add_argument("--json", type=pathlib.Path, metavar="FILE", help="write the lists to this new file")
    args = parser.parse_args()
    try:
        document = args.document.read_text(encoding="utf-8", errors="replace")
        if not args.sources.is_dir():
            raise OSError(f"{args.sources} is not a folder")
        sources = Sources(args.sources)
        claims = json.loads(args.claims.read_text(encoding="utf-8")) if args.claims else []
        if not isinstance(claims, list) or not all(isinstance(entry, dict) for entry in claims):
            raise ValueError("the claims file is not a JSON list of entries")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"blocked: an input could not be read ({exc})")
        return 2
    if args.json and args.json.exists():
        print(f"blocked: {args.json} already exists; name a new file")
        return 2

    found, missing, absent, malformed, short = [], [], [], [], 0
    for line, quote, reference in quotes_in(document):
        if len(quote.split()) < args.min_words:
            short += 1
            continue
        item = {"where": f"{args.document.name} line {line}", "quote": norm(quote), "source": reference}
        if reference is None:
            missing.append({**item, "why": "the quote has no source reference in its paragraph"})
            continue
        text, name = sources.text(reference)
        if text is None:
            missing.append({**item, "why": name})
            continue
        ok, note = locate(quote, text)
        (found if ok else absent).append({**item, "file": name, "note": note})
    for number, entry in enumerate(claims, 1):
        claim, verdict, reference, quote = (str(entry.get(key) or "").strip() for key in ("claim", "verdict", "source", "quote"))
        item = {"where": f"{args.claims.name} entry {number}", "claim": claim, "quote": norm(quote), "source": reference or None, "verdict": verdict}
        if not claim or verdict not in VERDICTS or not reference:
            malformed.append({**item, "why": f"needs a claim, a source and a verdict from: {', '.join(VERDICTS)}"})
        elif verdict == "unreachable":
            missing.append({**item, "why": "marked unreachable: no copy of the source was saved"})
        elif verdict == "absent":
            absent.append({**item, "file": None, "note": "marked absent: the source does not speak to this claim"})
        elif not quote:
            malformed.append({**item, "why": f"verdict '{verdict}' needs the exact quote that decides it"})
        else:
            text, name = sources.text(reference)
            if text is None:
                missing.append({**item, "why": name})
            else:
                ok, note = locate(quote, text)
                (found if ok else absent).append({**item, "file": name, "note": note})

    def show(title, items, detail):
        print(f"\n{title} ({len(items)}):")
        for item in items:
            subject = f"claim: {item['claim'][:90]}" if item.get("claim") else f"\"{item['quote'][:110]}{'...' if len(item['quote']) > 110 else ''}\""
            print(f"  {item['where']}  [{item['source'] or 'no reference'}]\n      {subject}")
            if detail(item):
                print(f"      {detail(item)}")

    print(f"cite-check {args.document} against {args.sources} ({len(sources.stems)} saved file(s))")
    show("not found", absent, lambda item: item["note"])
    show("malformed claim entries", malformed, lambda item: item["why"]) if malformed else None
    show("source missing", missing, lambda item: item["why"])
    show("found", found, lambda item: f"in {item['file']}" + (f"; {item['note']}" if item["note"] else ""))
    if short:
        print(f"\nskipped: {short} quoted phrase(s) shorter than {args.min_words} words (titles, terms, scare quotes)")
    print("limit: a found quote is in the saved copy, word for word. Whether it supports the sentence around it is for a reader to judge.")
    checked = len(found) + len(absent) + len(missing) + len(malformed)
    if absent or malformed:
        result, code = f"RESULT fail: {len(absent)} not found in the cited source, {len(malformed)} malformed claim entr(ies); {len(found)} found, {len(missing)} with no saved source", 1
    elif missing:
        result, code = f"RESULT not verified: {len(missing)} quote(s) or claim(s) have no saved source to check against; {len(found)} found", 2
    elif not checked:
        result, code = "RESULT not verified: no quotes or claims were found to check; if the document has none, there is nothing here to prove", 2
    else:
        result, code = f"RESULT pass: {len(found)} quote(s) and claim(s), each found in its saved source", 0
    if args.json:
        args.json.write_text(json.dumps({"document": str(args.document), "not_found": absent, "malformed": malformed, "source_missing": missing,
                                         "found": found, "skipped_short": short, "result": result}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"lists written to {args.json}")
    print(result)
    return code


if __name__ == "__main__":
    sys.exit(main())
