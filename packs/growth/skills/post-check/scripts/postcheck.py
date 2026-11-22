#!/usr/bin/env python3
"""Check one draft post against one platform's limits and rules.

  postcheck.py <draft-file> --platform <name> [--need-link] [--root <folder>] [--out report.json]
  postcheck.py --list                      show the platforms in the data file

Checks:
  length       counted the way references/platforms.json describes for that platform (links may count as a fixed
               number of characters; some platforms count by weight or by grapheme)
  links        how many, and with --need-link that there is at least one
  hashtags     how many, against the platform's entry
  front matter for the "blog" platform: the required keys are present and the date reads as a date
  images       every local image the draft refers to exists (paths relative to the draft, or to --root for /paths)
  open claims  no marker such as [unverified], [citation needed], TODO, TK or {{placeholder}} is left in the text

A draft may start with front matter between two --- lines; for a social platform it is not counted.
The limits file is dated and unverified: the script says so, and they have to be checked against the platform
before posting. The script reads the draft and never changes or publishes it. No network is used.

Exit codes: 0 = pass, 1 = fail, 2 = not verified (remote images not opened) or blocked (no draft, unknown platform).
"""
import argparse
import datetime
import json
import pathlib
import re
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
LINK = re.compile(r"https?://[^\s<>\"')\]]+")
HASHTAG = re.compile(r"(?<![\w&/])#[^\W\d_]\w*")
MARKERS = [
    (re.compile(r"\[(?:unverified|unconfirmed|citation needed|source needed|needs source|source\?|check|verify|todo|tk)[^\]]*\]", re.I), "open-claim marker"),
    (re.compile(r"\((?:unverified|unconfirmed|citation needed|source needed)\)", re.I), "open-claim marker"),
    (re.compile(r"\b(?:TODO|FIXME|TKTK|TK)\b"), "unfinished marker"),
    (re.compile(r"\{\{[^}]*\}\}|\[(?:link|url|name|date|number)\](?!\()|\bXX+%", re.I), "unfilled placeholder"),
]
IMAGE_KEYS = ("image", "cover", "cover_image", "og_image", "thumbnail", "hero")


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

    def finish(self, out=None):
        if self.failures:
            code, line = 1, f"RESULT fail: {self.failures[0]}" + (f" (and {len(self.failures) - 1} more)" if len(self.failures) > 1 else "")
        elif self.open:
            code, line = 2, f"RESULT not verified: {self.open[0]}" + (f" (and {len(self.open) - 1} more)" if len(self.open) > 1 else "")
        else:
            code, line = 0, "RESULT pass"
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


def split_front_matter(text):
    """Return (fields, body, number of lines the front matter takes)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text, 0
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            fields = {}
            for line in lines[1:index]:
                key, sep, value = line.partition(":")
                if sep and key.strip() and not line.startswith((" ", "\t", "#", "-")):
                    fields[key.strip().lower()] = value.strip().strip("\"'")
            return fields, "\n".join(lines[index + 1:]), index + 1
    return None, text, 0


def graphemes(text):
    count, joined, flags = 0, False, 0
    for char in text:
        code = ord(char)
        if code == 0x200D:
            joined = True
            continue
        if unicodedata.combining(char) or unicodedata.category(char) in ("Mn", "Me", "Cf") or 0xFE00 <= code <= 0xFE0F \
                or 0x1F3FB <= code <= 0x1F3FF:
            continue
        if joined:
            joined = False
            continue
        if 0x1F1E6 <= code <= 0x1F1FF:
            flags += 1
            if flags % 2 == 0:
                continue
        else:
            flags = 0
        count += 1
    return count


def measure(text, rules):
    """Return (length, how it was counted)."""
    method = rules.get("count", {}).get("value", "codepoints")
    text = unicodedata.normalize("NFC", text.strip())
    links = LINK.findall(text)
    fixed = rules.get("url_chars", {}).get("value")
    extra, how = 0, method
    if fixed is not None and links:
        text = LINK.sub("", text)
        extra = fixed * len(links)
        how += f", each of {len(links)} links counted as {fixed}"
    if method == "weighted":
        light = rules.get("light_ranges", {}).get("value", [])
        units = sum(1 if any(low <= ord(c) <= high for low, high in light) else 2 for c in text)
        return units + extra, how
    if method == "graphemes":
        return graphemes(text) + extra, how + " (approximate count)"
    if method == "utf16":
        return len(text.encode("utf-16-le")) // 2 + extra, how
    return len(text) + extra, how


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("draft", nargs="?", help="the draft: a text or Markdown file")
    parser.add_argument("--platform", help="a platform name from the data file, for example x, linkedin, blog")
    parser.add_argument("--list", action="store_true", help="show the platforms and their limits, then stop")
    parser.add_argument("--need-link", action="store_true", help="fail when the post holds no link")
    parser.add_argument("--root", type=pathlib.Path, help="folder that image paths starting with / are relative to")
    parser.add_argument("--limits", type=pathlib.Path, default=HERE.parent / "references" / "platforms.json",
                        help="dated platform limits (default: references/platforms.json)")
    parser.add_argument("--out", help="also write the three lists as JSON to this new file")
    args = parser.parse_args()

    try:
        platforms = json.loads(args.limits.read_text(encoding="utf-8"))["platforms"]
    except (OSError, ValueError, KeyError) as exc:
        return blocked(f"limits file {args.limits} cannot be read: {exc}")
    if args.list:
        for key, rules in platforms.items():
            parts = [f"{name}={entry['value']}" for name, entry in rules.items() if name not in ("name", "light_ranges")]
            print(f"{key:10} {rules['name']['value']}: {'; '.join(parts)}")
        print("every value is dated and unverified; check it against the platform before posting")
        return 0
    if not args.draft or not args.platform:
        return blocked("give a draft file and --platform; --list shows the platforms")
    rules = platforms.get(args.platform.lower())
    if rules is None:
        return blocked(f"no platform '{args.platform}' in {args.limits.name}; known: {', '.join(platforms)}")
    if args.out and pathlib.Path(args.out).exists():
        return blocked(f"{args.out} exists; reports are never overwritten, name a new file")
    draft = pathlib.Path(args.draft)
    if not draft.is_file():
        return blocked(f"{args.draft} is not a file")
    raw = draft.read_text(encoding="utf-8", errors="replace")
    fields, body, offset = split_front_matter(raw)
    if not body.strip():
        return blocked(f"{args.draft} has no text to check")

    report = Report(f"post-check {args.draft} for {rules['name']['value']}")
    loose = [entry for key, entry in rules.items() if key != "name" and not entry.get("verified")]
    dates = sorted({entry.get("checked", "?") for entry in loose})
    if loose:
        report.note(f"all {len(loose)} limits used for this platform are unverified (written from memory, dated "
                    f"{', '.join(dates)}): check them against the platform before posting")
    is_blog = "front_matter" in rules

    def judge(entry, text_fail):
        (report.warn if entry.get("kind") == "guidance" else report.fail)(text_fail)

    # length
    if "max_chars" in rules:
        length, how = measure(body, rules)
        limit = rules["max_chars"]["value"]
        if length > limit:
            judge(rules["max_chars"], f"length {length} is over the limit of {limit} {rules['max_chars']['unit']} by {length - limit} ({how})")
        else:
            report.ok(f"length {length} of {limit} {rules['max_chars']['unit']} ({how})")
        if fields is not None:
            report.note("the front matter block was left out of the count")
    if "fold_chars" in rules:
        fold = rules["fold_chars"]["value"]
        report.note(f"first {fold} characters, roughly what shows before the cut: \"{' '.join(body.split())[:fold]}\"")

    # links and hashtags
    links = [link.rstrip(".,;:!?") for link in LINK.findall(body)]
    if args.need_link and not links:
        report.fail("the post holds no link, and --need-link was given")
    elif links:
        report.ok(f"{len(links)} links in the post: {', '.join(links[:3])}" + (" ..." if len(links) > 3 else ""))
        report.skip("whether the links answer (use link-check)")
    if "max_links" in rules and len(links) > rules["max_links"]["value"]:
        judge(rules["max_links"], f"{len(links)} links, more than {rules['max_links']['value']}")
    if not is_blog:
        tags = HASHTAG.findall(body)
        if "max_hashtags" in rules:
            most = rules["max_hashtags"]["value"]
            if len(tags) > most:
                judge(rules["max_hashtags"], f"{len(tags)} hashtags, more than {most}: {' '.join(tags)}")
            else:
                report.ok(f"{len(tags)} hashtags, within {most}")
        elif tags:
            report.note(f"{len(tags)} hashtags; the data file holds no hashtag entry for this platform")
        repeated = sorted({t.lower() for t in tags if [x.lower() for x in tags].count(t.lower()) > 1})
        if repeated:
            report.warn(f"hashtags used more than once: {' '.join(repeated)}")

    # front matter
    if is_blog:
        wanted = rules["front_matter"]["value"]
        if fields is None:
            report.fail(f"no front matter block; this platform entry asks for {', '.join(wanted)}")
        else:
            absent = [key for key in wanted if not fields.get(key)]
            if absent:
                report.fail(f"front matter keys missing or empty: {', '.join(absent)}")
            else:
                report.ok(f"front matter has {', '.join(wanted)}")
            if fields.get("date"):
                try:
                    datetime.date.fromisoformat(fields["date"][:10])
                    report.ok(f"date reads as a date: {fields['date'][:10]}")
                except ValueError:
                    report.fail(f"front matter date '{fields['date']}' is not in the form YYYY-MM-DD")
            for key in ("title", "description"):
                entry = rules.get(f"{key}_max_chars")
                if entry and fields.get(key) and len(fields[key]) > entry["value"]:
                    judge(entry, f"front matter {key} is {len(fields[key])} characters, over {entry['value']}")
            if fields.get("draft", "").lower() == "true":
                report.warn("front matter says draft: true")

    # images
    refs = re.findall(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)", body) + re.findall(r"<img[^>]+src=[\"']([^\"']+)", body, re.I)
    refs += [fields[key] for key in IMAGE_KEYS if fields and fields.get(key)]
    present = 0
    for ref in dict.fromkeys(refs):
        if re.match(r"^(https?:)?//", ref, re.I):
            report.skip(f"remote image not opened: {ref}", blocks=True)
        elif ref.startswith("data:"):
            present += 1
        elif ref.startswith("/") and args.root is None:
            report.skip(f"image path {ref} starts with /; give --root to say which folder that is", blocks=True)
        else:
            path = (args.root / ref.lstrip("/")) if ref.startswith("/") else (draft.parent / ref.split("#")[0].split("?")[0])
            if path.is_file() and path.stat().st_size > 0:
                present += 1
            else:
                report.fail(f"image not found or empty: {ref} (looked at {path})")
    if present:
        report.ok(f"{present} local images exist")
    if not refs:
        report.note("the draft refers to no image")

    # open claims and unfinished text
    found = 0
    for number, line in enumerate(raw.splitlines(), 1):
        for pattern, label in MARKERS:
            for match in pattern.finditer(line):
                found += 1
                report.fail(f"line {number}: {label} '{match.group(0)}' is still in the text: \"{line.strip()[:90]}\"")
    if not found:
        report.ok("no open-claim marker, unfinished marker or placeholder in the text")

    report.skip("whether the claims in the post are true (use claim-check)")
    report.skip("how the platform will lay the post out, and its rules on content")
    return report.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
