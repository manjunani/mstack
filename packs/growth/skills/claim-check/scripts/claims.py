#!/usr/bin/env python3
"""Find the claims in marketing text and require a source for each one.

  claims.py find  <text-file> [--template new-sources.json]
        list every claim with its line number; with --template, write a sources file to fill in
  claims.py check <text-file> --sources <sources.json> [--fetch] [--out report.json]
        every claim has to map to a sources entry whose evidence exists and holds the quoted words

A claim is a sentence that holds a number, a superlative ("fastest", "best", "the only", "the first"),
a comparison ("faster than", "unlike", "3x") or a testimonial (quoted words, a blockquote, "trusted by").

The sources file is JSON: {"sources": [entry, ...]}. An entry has:
  match        words copied from the claim (six characters or more); the entry covers every claim holding them
  evidence     a file path (relative to the sources file) or an http(s) address
  quote        words that appear in the evidence; the script looks for them           -> verdict "observed"
  attested_by  who vouches for evidence the script cannot search (a screenshot, a dashboard) -> "reported"
  permission   for a testimonial: who agreed to be quoted, and when (required)
  status       "not a claim" with a "reason", for a sentence flagged by mistake

Verdicts: observed, reported, not a claim, unopened (evidence named but not searched), unsupported.
Any unsupported claim fails. Web evidence is opened only with --fetch, and only at the address in the entry.
The script never edits the text. Whether a quote truly supports its claim is for a person to read.

Exit codes: 0 = pass, 1 = fail (unsupported claims), 2 = not verified (unopened evidence) or blocked.
"""
import argparse
import datetime
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

AGENT = "mstack-growth-check/0.1 (run by the site owner; python-urllib)"

NUMBER = re.compile(r"(?<![A-Za-z\d.#/-])[$€£₹]?\d[\d,]*(?:\.\d+)?(?:\s?%|\+|[kKmMxX×]\b)?")
NOT_A_FIGURE = re.compile(r"(?:\b(?:step|chapter|figure|part|section|page|phase|version|ios|android|windows|macos|python|"
                          r"node|http|utf|iso|rfc|wcag|es)[ -]?|©\s?|copyright\s)$", re.I)
NUMBER_WORDS = re.compile(r"\b(dozens|hundreds|thousands|millions|billions)\b", re.I)
SUPERLATIVE = re.compile(
    r"\b(best|fastest|quickest|easiest|simplest|cheapest|smallest|largest|biggest|safest|strongest|lightest|smartest|"
    r"greatest|highest|lowest|leading|unmatched|unrivall?ed|unbeatable|unparalleled|guaranteed|world[- ]class|"
    r"award[- ]winning|top[- ]rated|best[- ]in[- ]class|industry[- ]leading|number one|no\. ?1|revolutionary|ultimate|"
    r"(?:the|our|world's) most [\w-]+|the only|only (?:one|app|tool|product|platform|service|company|solution|way)|"
    r"(?:the|world's|industry's|market's) first|first[- ]ever|first [\w-]+ (?:to|that))\b|#1\b", re.I)
COMPARISON = re.compile(
    r"\b((?!rather|other|another|later|either|neither|whether|together|ever|never)\w+er than|(?:more|less|fewer)\b[\w\s,-]{0,40}?\bthan|"
    r"compared (?:to|with)|vs\.?|versus|unlike|outperforms?|beats|twice (?:as|the)|half (?:as|the)|alternative to|"
    r"\d+(?:\.\d+)?\s?(?:x|×|times)\b)", re.I)
QUOTED = re.compile(r"[\"“]([^\"“”]{12,})[\"”]")
SOCIAL = re.compile(r"\b((?:trusted|used|loved|chosen|recommended|backed) by|(?:customers?|users?|clients?|reviewers?) "
                    r"(?:say|said|love|rate|report)|\d(?:\.\d)? ?(?:stars?|out of 5)|rated|testimonials?)\b", re.I)
MARKER = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|#{1,6}\s+)")
SENTENCE_END = re.compile(r"(?<=[.!?])[\"”’)]*\s+(?=[\"“(]?[A-Z0-9])")


class Report:
    """Three lists and one end state. Findings are either failures (block) or warnings (do not)."""

    def __init__(self, title):
        self.title, self.failures, self.warnings, self.fine, self.skipped, self.open, self.notes = title, [], [], [], [], [], []

    def fail(self, text):
        self.failures.append(text)

    def warn(self, text):
        self.warnings.append(text)

    def ok(self, text):
        self.fine.append(text)

    def skip(self, text, blocks=False):
        self.skipped.append(text)
        if blocks:
            self.open.append(text)

    def note(self, text):
        self.notes.append(text)

    def finish(self, out=None, nothing=None):
        if self.failures:
            code, line = 1, f"RESULT fail: {self.failures[0]}" + (f" (and {len(self.failures) - 1} more)" if len(self.failures) > 1 else "")
        elif self.open:
            code, line = 2, f"RESULT not verified: {self.open[0]}" + (f" (and {len(self.open) - 1} more)" if len(self.open) > 1 else "")
        else:
            code, line = 0, f"RESULT pass: {nothing}" if nothing else "RESULT pass"
        print(f"== {self.title}")
        for text in self.notes:
            print(f"note  {text}")
        print(f"FINDINGS ({len(self.failures)} fail, {len(self.warnings)} warn)")
        for text in self.failures:
            print(f"  FAIL  {text}")
        for text in self.warnings:
            print(f"  warn  {text}")
        print(f"CHECKED AND FINE ({len(self.fine)})")
        for text in self.fine:
            print(f"  ok    {text}")
        print(f"NOT CHECKED ({len(self.skipped)})")
        for text in self.skipped:
            print(f"  --    {text}")
        if out:
            data = {"check": self.title, "made": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                    "result": line, "failures": self.failures, "warnings": self.warnings, "fine": self.fine,
                    "not_checked": self.skipped, "notes": self.notes}
            pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
            with open(out, "x", encoding="utf-8") as handle:
                handle.write(json.dumps(data, indent=2) + "\n")
            print(f"report written to {out}")
        print(line)
        return code


def blocked(text):
    print(f"blocked: {text}")
    return 2


def squash(text):
    return " ".join(text.split())


def same_words(text):
    """Lower case, one space between words, plain quote marks: for comparing a quote with its source."""
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return squash(text).casefold()


def plain_lines(text, is_html=False):
    """The text as lines with code, front matter, comments and link targets blanked out. Line numbers are kept."""
    if is_html:
        text = re.sub(r"(?is)<(script|style)\b.*?</\1>", lambda m: "\n" * m.group(0).count("\n"), text)
        text = re.sub(r"(?s)<[^>]+>", lambda m: " " + "\n" * m.group(0).count("\n"), text)
    lines = text.splitlines()
    out, fenced, front = [], False, bool(lines) and lines[0].strip() == "---"
    for number, line in enumerate(lines):
        if front:
            out.append("")
            if number > 0 and line.strip() in ("---", "..."):
                front = False
            continue
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            out.append("")
            continue
        if fenced:
            out.append("")
            continue
        line = re.sub(r"<!--.*?-->", " ", line)
        line = re.sub(r"`[^`]*`", " ", line)
        line = re.sub(r"\]\([^)]*\)", "]", line)
        line = re.sub(r"https?://\S+", " ", line)
        out.append(line)
    return out


def units(lines):
    """Yield (line number, sentence). A list item, heading or blockquote line stands alone; other lines join into paragraphs."""
    block, start = [], 0

    def flush():
        if block:
            for sentence in SENTENCE_END.split(squash(" ".join(block))):
                if sentence.strip():
                    yield start, sentence.strip()

    for number, line in enumerate(lines, 1):
        bare = line.strip()
        alone = bool(MARKER.match(line)) or bare.startswith(">")
        if not bare or alone:
            yield from flush()
            block = []
            if alone:
                quote = bare.startswith(">")
                text = squash(MARKER.sub("", bare.lstrip("> ")))
                if text:
                    for sentence in ([text] if quote else SENTENCE_END.split(text)):
                        yield number, ("> " if quote else "") + sentence.strip()
            continue
        if not block:
            start = number
        block.append(bare)
    yield from flush()


def find_claims(text, is_html=False):
    """Return a list of claims: id, line, kinds, hits, text."""
    claims = []
    for line, sentence in units(plain_lines(text, is_html)):
        kinds, hits = [], []
        body = sentence[2:] if sentence.startswith("> ") else sentence
        figures = [m.group(0).strip() for m in NUMBER.finditer(body)
                   if not NOT_A_FIGURE.search(body[:m.start()]) and not re.match(r"[dD]\b|\.\d", body[m.end():])]
        figures += [m.group(0) for m in NUMBER_WORDS.finditer(body)]
        if figures:
            kinds.append("number")
            hits += figures
        for name, pattern in (("superlative", SUPERLATIVE), ("comparison", COMPARISON), ("social proof", SOCIAL)):
            found = [m.group(0) for m in pattern.finditer(body)]
            if found:
                kinds.append(name)
                hits += found
        quoted = [q for q in QUOTED.findall(body) if len(q.split()) >= 4]
        if quoted or (sentence.startswith("> ") and len(body.split()) >= 4):
            kinds.append("testimonial")
            hits += [q[:40] for q in quoted] or ["blockquote"]
        if kinds:
            claims.append({"id": f"c{len(claims) + 1}", "line": line, "kinds": kinds, "hits": list(dict.fromkeys(hits)),
                           "text": body})
    return claims


def open_address(url, timeout=15, limit=2_000_000):
    """GET one address without leaving its host. Returns (text or None, problem or None)."""
    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(url).hostname:
                return None
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.build_opener(Stay).open(request, timeout=timeout) as answer:
            body = answer.read(limit)
    except urllib.error.HTTPError as exc:
        return None, f"status {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, str(getattr(exc, "reason", exc))
    text = body.decode("utf-8", "replace")
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    return re.sub(r"(?s)<[^>]+>", " ", text), None


def judge(entry, kinds, base, fetch):
    """Return (verdict, detail) for one claim against the entry that covers it."""
    status = str(entry.get("status", "")).strip().lower()
    if status == "not a claim":
        reason = str(entry.get("reason", "")).strip()
        return ("not a claim", reason) if len(reason) >= 10 else ("unsupported", "marked 'not a claim' with no reason of ten characters or more")
    if status == "remove":
        return "unsupported", "marked for removal in the sources file but still in the text"
    evidence = str(entry.get("evidence", "")).strip()
    if not evidence:
        return "unsupported", "the sources entry names no evidence"
    if "testimonial" in kinds and not str(entry.get("permission", "")).strip():
        return "unsupported", "a testimonial needs 'permission' in its entry: who agreed to be quoted, and when"
    quote, vouched = str(entry.get("quote", "")).strip(), str(entry.get("attested_by", "")).strip()
    if re.match(r"^https?://", evidence, re.I):
        if not fetch:
            return "unopened", f"evidence is a web address ({evidence}); run with --fetch to open it"
        if not quote:
            return "unopened", f"no 'quote' to look for at {evidence}"
        text, problem = open_address(evidence)
        if text is None:
            return "unopened", f"{evidence} could not be opened: {problem}"
        if same_words(quote) in same_words(text):
            return "observed", f"quote found at {evidence}"
        return "unsupported", f"the quote is not on the page at {evidence}"
    path = (base / evidence).resolve()
    if not path.is_file():
        return "unsupported", f"evidence file not found: {evidence}"
    if quote:
        raw = path.read_bytes()
        if b"\x00" in raw[:4096]:
            if vouched:
                return "reported", f"{evidence} is not text; vouched for by {vouched}"
            return "unopened", f"{evidence} is not text, so the quote cannot be searched; add 'attested_by'"
        if same_words(quote) in same_words(raw.decode("utf-8", "replace")):
            return "observed", f"quote found in {evidence}"
        return "unsupported", f"the quote is not in {evidence}"
    if vouched:
        return "reported", f"{evidence} exists; vouched for by {vouched}"
    return "unopened", f"{evidence} exists but the entry has neither 'quote' nor 'attested_by'"


def load_sources(path):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    entries = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise ValueError("expected {\"sources\": [ {...}, ... ]}")
    return entries


def check_claims(claims, entries, base, fetch, report, label=""):
    """Judge every claim and put the outcome on the report. Returns the number of unsupported claims."""
    keyed = []
    for number, entry in enumerate(entries, 1):
        match = same_words(str(entry.get("match", "")))
        if len(match) < 6:
            report.fail(f"sources entry {number}: 'match' has to be six characters or more, copied from the claim")
            continue
        keyed.append((match, entry, number))
    keyed.sort(key=lambda item: -len(item[0]))
    used, bad = {}, 0
    for claim in claims:
        where = f"{claim.get('where', label)}line {claim['line']} [{', '.join(claim['kinds'])}] \"{claim['text'][:110]}\""
        found = next(((entry, number) for match, entry, number in keyed if match in same_words(claim["text"])), None)
        if found is None:
            report.fail(f"unsupported: {where}: no sources entry covers it")
            bad += 1
            continue
        entry, number = found
        used[number] = used.get(number, 0) + 1
        verdict, detail = judge(entry, claim["kinds"], base, fetch)
        if verdict == "unsupported":
            report.fail(f"unsupported: {where}: {detail}")
            bad += 1
        elif verdict == "unopened":
            report.skip(f"unopened: {where}: {detail}", blocks=True)
        else:
            quote = f" | quote: \"{squash(str(entry.get('quote', '')))[:90]}\"" if verdict == "observed" else ""
            report.ok(f"{verdict}: {where}: {detail}{quote}")
    for number, times in used.items():
        if times > 3:
            report.warn(f"sources entry {number} covers {times} claims; a 'match' that broad may be hiding claims with no source of their own")
    idle = [number for _, _, number in keyed if number not in used]
    if idle:
        report.note(f"sources entries that cover no claim in this text: {', '.join(str(n) for n in sorted(idle))}")
    return bad


def read_text(path):
    file = pathlib.Path(path)
    if not file.is_file():
        return None, f"{path} is not a file"
    text = file.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return None, f"{path} is empty"
    return text, None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("find", help="list the claims in a text")
    p.add_argument("text", help="a text, Markdown or HTML file")
    p.add_argument("--template", help="write a sources file to fill in, one entry per claim, to this new file")
    p = sub.add_parser("check", help="require a source for every claim")
    p.add_argument("text", help="a text, Markdown or HTML file")
    p.add_argument("--sources", required=True, help="the sources file (JSON)")
    p.add_argument("--fetch", action="store_true", help="open evidence given as http(s) addresses")
    p.add_argument("--out", help="also write the three lists as JSON to this new file")
    args = parser.parse_args()

    text, problem = read_text(args.text)
    if problem:
        return blocked(problem)
    claims = find_claims(text, is_html=str(args.text).lower().endswith((".html", ".htm")))
    limits = ["whether each quote truly supports its claim: read every claim beside its quote",
              "claims made in images, video or audio",
              "claims worded without a number, superlative, comparison or quotation"]

    if args.action == "find":
        if args.template:
            if pathlib.Path(args.template).exists():
                return blocked(f"{args.template} exists; name a new file")
            skeleton = {"sources": [{"match": c["text"], "evidence": "", "quote": ""} for c in claims]}
            pathlib.Path(args.template).write_text(json.dumps(skeleton, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"== claim-check find {args.text}")
        for claim in claims:
            print(f"  {claim['id']:4} line {claim['line']:<4} [{', '.join(claim['kinds'])}] {claim['text'][:140]}")
            print(f"       flagged: {', '.join(claim['hits'][:6])}")
        if args.template:
            print(f"sources template with {len(claims)} entries written to {args.template}")
        if not claims:
            print("RESULT pass: no claims found in the text")
            return 0
        print(f"RESULT not verified: {len(claims)} claims found and none checked; fill in a sources file and run 'check'")
        return 2

    if args.out and pathlib.Path(args.out).exists():
        return blocked(f"{args.out} exists; reports are never overwritten, name a new file")
    try:
        entries = load_sources(args.sources)
    except (OSError, ValueError) as exc:
        return blocked(f"sources file {args.sources} cannot be read: {exc}")
    report = Report(f"claim-check {args.text} against {args.sources}")
    report.note(f"{len(claims)} claims found; {len(entries)} sources entries")
    check_claims(claims, entries, pathlib.Path(args.sources).resolve().parent, args.fetch, report)
    for line in limits:
        report.skip(line)
    return report.finish(args.out, nothing=None if claims else "no claims found in the text")


if __name__ == "__main__":
    sys.exit(main())
