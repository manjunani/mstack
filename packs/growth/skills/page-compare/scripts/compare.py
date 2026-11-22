#!/usr/bin/env python3
"""Put the measurable facts of two saved HTML pages side by side. It never says which page is better.

  compare.py <our-page.html> <their-page.html> [--out report.json]

Both arguments are HTML files saved to disk (save the pages first; this script fetches nothing).
The table shows, for each page:
  title and its length, meta description length, number of h1, headings per level, visible word count,
  calls to action (buttons, plus links styled as a button or starting with an action verb),
  structured data types found in JSON-LD, images and how many carry alt text,
  HTML size as stored and as it would travel compressed (gzip, HTML only).

One thing fails the run: sentences of eight words or more that are word for word the same on both pages.
Copying a competitor's text is not something this pack helps with, so shared sentences are listed.

Exit codes: 0 = pass (table complete), 1 = fail (shared sentences), 2 = not verified (a page built by script)
or blocked (a file missing, empty, not HTML, or the same file twice).
"""
import argparse
import gzip
import json
import pathlib
import re
import sys

import pagefacts as pf

SENTENCE = re.compile(r"(?<=[.!?])\s+")
SHARED_WORDS = 8


def measure(page, info):
    levels = [h["level"] for h in page.headings]
    types, broken = [], 0
    for raw in page.jsonld:
        try:
            data = json.loads(raw)
        except ValueError:
            broken += 1
            continue
        for top in data if isinstance(data, list) else [data]:
            if isinstance(top, dict):
                for item in (top.get("@graph") if isinstance(top.get("@graph"), list) else [top]):
                    if isinstance(item, dict):
                        kinds = item.get("@type")
                        types += [str(k) for k in (kinds if isinstance(kinds, list) else [kinds]) if k]
    with_alt = sum(1 for image in page.images if image["alt"])
    empty_alt = sum(1 for image in page.images if image["alt"] == "")
    images = len(page.images)
    description = page.meta_one("description")
    return [
        ("title", f"\"{page.title}\"" if page.title else "none"),
        ("title length", len(page.title) if page.title else 0),
        ("meta description length", len(description) if description else 0),
        ("h1 count", levels.count(1)),
        ("first h1", next((f"\"{h['text'][:60]}\"" for h in page.headings if h["level"] == 1), "none")),
        ("headings per level", " ".join(f"h{n}:{levels.count(n)}" for n in range(1, 7) if levels.count(n)) or "none"),
        ("visible words", len(pf.words(page.text))),
        ("calls to action", len(page.actions())),
        ("JSON-LD types", ", ".join(sorted(set(types))) or "none"),
        ("JSON-LD blocks that do not parse", broken),
        ("images", images),
        ("images with alt text", f"{with_alt} of {images}" + (f" ({round(100 * with_alt / images)}%)" if images else "")),
        ("images with empty alt", empty_alt),
        ("HTML bytes as stored", info["bytes"]),
        ("HTML bytes compressed (gzip)", len(gzip.compress(info["body"], compresslevel=6, mtime=0))),
    ]


def sentences(page):
    found = set()
    pieces = [p["text"] for p in page.paragraphs] + [h["text"] for h in page.headings] + [page.text]
    for piece in pieces:
        for sentence in SENTENCE.split(piece):
            plain = " ".join(pf.words(sentence.casefold()))
            if len(plain.split()) >= SHARED_WORDS:
                found.add(plain)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ours", help="our page, saved as an HTML file")
    parser.add_argument("theirs", help="the other page, saved as an HTML file")
    parser.add_argument("--out", help="also write the table and the three lists as JSON to this new file")
    args = parser.parse_args()

    if pf.out_refused(args.out):
        return pf.blocked(f"{args.out} exists; reports are never overwritten, name a new file")
    loaded = []
    for source in (args.ours, args.theirs):
        if re.match(r"^https?://", source, re.I):
            return pf.blocked(f"{source} is an address; save the page to a file first, this script compares saved files")
        try:
            text, info = pf.read_source(source)
        except pf.SourceError as exc:
            return pf.blocked(str(exc))
        loaded.append((pf.parse(text), info))
    (ours, our_info), (theirs, their_info) = loaded
    if our_info["body"] == their_info["body"]:
        return pf.blocked("the two files hold the same bytes; give two different pages")

    left, right = measure(ours, our_info), measure(theirs, their_info)
    report = pf.Report(f"page-compare A={args.ours} B={args.theirs}")
    width = max(len(name) for name, _ in left)
    col = max(12, min(48, max(len(str(value)) for _, value in left)))
    print(f"{'measure':{width}}  {'A':{col}}  B")
    for (name, a), (_, b) in zip(left, right):
        print(f"{name:{width}}  {str(a):{col}}  {b}")
    print()
    report.ok(f"both files read as HTML; {len(left)} measures set side by side")
    for label, page in (("A", ours), ("B", theirs)):
        if page.built_by_script():
            report.skip(f"page {label} holds almost no text in its HTML and is built by script; its counts describe the shell, "
                        f"not what a visitor sees. Save the rendered page instead", blocks=True)
    shared = sorted(sentences(ours) & sentences(theirs), key=len, reverse=True)
    if shared:
        report.fail(f"{len(shared)} sentences of {SHARED_WORDS} words or more are word for word the same on both pages; "
                    f"the longest: \"{shared[0][:140]}\"")
        for sentence in shared[1:5]:
            report.fail(f"shared sentence: \"{sentence[:140]}\"")
    else:
        report.ok(f"no sentence of {SHARED_WORDS} words or more is shared between the two pages")
    report.skip("which page is better: this script counts and makes no such claim")
    report.skip("images, stylesheets and scripts in the transfer size: only the HTML was measured")
    report.skip("how either page looks, ranks or converts")
    if args.out:
        report.note("table: " + json.dumps({name: {"A": a, "B": b} for (name, a), (_, b) in zip(left, right)}, ensure_ascii=False))
    return report.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
