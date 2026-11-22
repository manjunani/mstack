#!/usr/bin/env python3
"""Report what a page puts first: its first heading, first paragraph, first call to action, and what has to load.

  firstscreen.py <file-or-url> [--promise "words the visitor was promised"] [--root <folder>] [--out report.json]

It reads the HTML in document order and reports:
  heading     the first heading and its level
  paragraph   the first paragraph of three words or more
  action      the first button or action link, its words and where it leads
  headline    whether the first heading shares a word with the <title> or the meta description
              (a headline that shares none is flagged: it may not say what the product is)
  promise     with --promise, whether those words appear in the heading, first paragraph or action
  load        bytes of the HTML, every stylesheet, every render-blocking script in <head> and the first image
              that is not lazy-loaded, compared with the dated guidance in references/budget.json

For a file, resources are looked up beside the file (or under --root for paths starting with /).
For a URL, resources on the same site are fetched once each; other hosts are not contacted.
Document order is not the screen: what truly shows before scrolling depends on layout, fonts and screen size,
and that needs a browser. The report says so every time.

Exit codes: 0 = pass, 1 = fail, 2 = not verified (page built by script, target set by script) or blocked.
"""
import argparse
import pathlib
import re
import sys
import urllib.parse

import pagefacts as pf

HERE = pathlib.Path(__file__).resolve().parent
DEAD = re.compile(r"^\s*(#|javascript:|$)", re.I)


def size_of(ref, info, root):
    """Return (bytes or None, why not)."""
    if ref.startswith("data:"):
        return len(ref), None
    if info["kind"] == "url":
        target = urllib.parse.urljoin(info["final"], ref)
        if urllib.parse.urlsplit(target).scheme not in ("http", "https") or not pf.same_site(target, info["final"]):
            return None, "on another host, not fetched"
        got = pf.fetch(target, limit=20_000_000)
        if got["status"] == 200 and not got["offsite"]:
            return len(got["body"]), None
        return None, got["error"] or f"status {got['status']}"
    if re.match(r"^(https?:)?//", ref, re.I):
        return None, "a web address, not fetched for a saved file"
    clean = urllib.parse.unquote(ref.split("#")[0].split("?")[0])
    if clean.startswith("/"):
        if root is None:
            return None, "path starts with /; give --root"
        path = root / clean.lstrip("/")
    else:
        path = pathlib.Path(info["source"]).parent / clean
    return (path.stat().st_size, None) if path.is_file() else (None, "file not found beside the page")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="an HTML file, or an http(s) address")
    parser.add_argument("--promise", help="the words the visitor was promised before the click (an ad, a listing, a post)")
    parser.add_argument("--root", type=pathlib.Path, help="for a saved file: the folder that paths starting with / are relative to")
    parser.add_argument("--budget", type=pathlib.Path, default=HERE.parent / "references" / "budget.json",
                        help="dated load guidance (default: references/budget.json)")
    parser.add_argument("--timeout", type=int, default=15, help="seconds allowed per fetch (default 15)")
    parser.add_argument("--out", help="also write the three lists as JSON to this new file")
    args = parser.parse_args()

    if pf.out_refused(args.out):
        return pf.blocked(f"{args.out} exists; reports are never overwritten, name a new file")
    try:
        budget, lines = pf.load_data(args.budget)
    except (OSError, ValueError, KeyError) as exc:
        return pf.blocked(f"budget file {args.budget} cannot be read: {exc}")
    try:
        text, info = pf.read_source(args.source, args.timeout)
    except pf.SourceError as exc:
        return pf.blocked(str(exc))
    page = pf.parse(text)
    report = pf.Report(f"first-screen {args.source} (read from {'a fetched page' if info['kind'] == 'url' else 'a saved file'}, HTML only)")
    for line in lines:
        report.note(line)
    browser = "what really shows before scrolling: that depends on layout and screen size and needs a browser; this read the HTML in document order"

    if not page.title:
        report.fail("the page has no <title>")
    if page.built_by_script():
        report.skip(f"heading, paragraph and action: the HTML holds {len(pf.words(page.text))} words and the page is built by script; "
                    f"open it in a browser", blocks=True)
        report.skip(browser)
        return report.finish(args.out)

    # heading
    heading = next((h for h in page.headings if h["text"]), None)
    if heading is None:
        report.fail("no heading (h1 to h6) with text in the HTML")
    else:
        report.ok(f"first heading (h{heading['level']}): \"{heading['text'][:120]}\"")
        if heading["level"] != 1:
            report.warn(f"the first heading is an h{heading['level']}, not an h1")

    # paragraph
    paragraph = next((p for p in page.paragraphs if len(pf.words(p["text"])) >= 3), None)
    if paragraph is None:
        report.warn("no paragraph of three words or more in the HTML")
    else:
        report.ok(f"first paragraph: \"{paragraph['text'][:160]}\"")
        if heading and paragraph["order"] < heading["order"]:
            report.note("the first paragraph comes before the first heading in the HTML")

    # call to action
    action = next((a for a in page.actions() if a["text"]), None)
    if action is None:
        report.fail("no call to action in the HTML: no button, and no link styled as a button or starting with an action verb")
    else:
        target = action["target"]
        label = f"first call to action ({action['kind']}): \"{action['text'][:60]}\""
        if action["kind"] == "link" and (target is None or DEAD.match(target)) and not re.match(r"^\s*#[\w-]+", target or ""):
            report.fail(f"{label} leads nowhere (href '{target or ''}')")
        elif action["kind"] == "button" and not target:
            report.ok(f"{label}")
            report.skip("where the first call to action leads: it is a button with no form or address in the HTML, so a script decides",
                        blocks=True)
        else:
            report.ok(f"{label} -> {target}")
        if heading and action["order"] < heading["order"]:
            report.note("the first call to action comes before the first heading in the HTML (often a navigation button)")

    # headline against title and description
    described = " ".join(filter(None, [page.title, page.meta_one("description"), page.meta_one("og:title"), page.meta_one("og:description")]))
    if heading and described:
        shared = pf.content_words(heading["text"]) & pf.content_words(described)
        if shared:
            report.ok(f"the headline shares words with the title or description: {', '.join(sorted(shared)[:8])}")
        else:
            report.warn(f"the headline shares no word with the title or description, so it may not say what the product is "
                        f"(headline: {', '.join(sorted(pf.content_words(heading['text']))[:8]) or 'no content words'})")
    elif heading:
        report.skip("headline against title and description: the page has neither")

    # promise
    if args.promise:
        wanted = pf.content_words(args.promise)
        first = " ".join(filter(None, [heading and heading["text"], paragraph and paragraph["text"], action and action["text"]]))
        have = pf.content_words(first)
        absent = sorted(wanted - have)
        if not wanted:
            report.skip("promise: the words given hold nothing to look for")
        elif len(absent) == len(wanted):
            report.fail(f"none of the promised words appear in the first heading, paragraph or action: {', '.join(absent)}")
        elif absent:
            report.warn(f"promised words missing from the first heading, paragraph and action: {', '.join(absent)}")
        else:
            report.ok(f"every promised word appears in the first heading, paragraph or action: {', '.join(sorted(wanted))}")

    # what has to load first
    needed = [("stylesheet", link["href"]) for link in page.rel("stylesheet") if link["href"] and "print" not in link["media"].lower()]
    needed += [("blocking script", s["src"]) for s in page.scripts
               if s["src"] and s["in_head"] and not (s["async"] or s["defer"] or s["module"])]
    hero = next((i for i in page.images if i["src"] and i["loading"] != "lazy"), None)
    if hero:
        needed.append(("first image", hero["src"]))
    total, unknown = info["bytes"], []
    for kind, ref in needed:
        size, why = size_of(ref, info, args.root)
        if size is None:
            unknown.append(f"{kind} {ref[:70]} ({why})")
        else:
            total += size
    limit = budget["first_load_kb"]["value"] * 1000
    blocking = sum(1 for kind, _ in needed if kind != "first image")
    summary = (f"HTML {info['bytes']} bytes; with {len(needed) - len(unknown)} of {len(needed)} first-load resources measured "
               f"the total is {'at least ' if unknown else ''}{total} bytes ({blocking} render-blocking files)")
    if total > limit:
        report.warn(f"first load is over the guidance of {limit} bytes: {summary}")
    else:
        report.ok(f"first load: {summary}; guidance {limit} bytes")
    for item in unknown:
        report.skip(f"size of {item}")

    report.skip(browser)
    report.skip("whether the words persuade: that is taste, and no script judges it")
    report.skip("load time on a real connection (use page-speed)")
    return report.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
