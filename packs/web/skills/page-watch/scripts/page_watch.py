#!/usr/bin/env python3
"""Tell what changed on one page since the last look, as added and removed lines of visible text.

  page_watch.py check URL                      fetch the page once, compare with the saved snapshot, report the difference
  page_watch.py check URL --ignore-line "^Updated \\d+ minutes ago"
                                               drop lines that match this pattern before comparing (repeat for more)
  page_watch.py check URL --ignore-id clock --ignore-class ad
                                               drop whole elements by id or class before comparing
  page_watch.py check URL --clear-ignores      forget the saved ignore rules for this page
  page_watch.py list                           the pages watched in this project, with the last look and last change
  page_watch.py --root DIR ...                 project folder that holds .mstack/ (default: current folder)

Snapshots live in .mstack/page-watch/<page>/: the page as received, its text, and one diff per change.
Ignore rules are saved with the page and reused on the next look; when the rules change, the earlier
page is read again with the new rules, so a rule change never shows up as a page change.
The folder is listed in .mstack/.gitignore: saved pages are not for commits.

One request per look, and no second look at the same page within --min-interval seconds (default 60).
The script has no scheduler: something else decides when to look again.

Exit codes: 0 = no change since the last snapshot
            1 = the page changed (this is the "fail" state here: it means changed, not broken); the diff is saved
            2 = not verified or blocked: first snapshot (nothing to compare), no answer, a refusal, too soon, bad input
"""
import argparse
import datetime
import difflib
import hashlib
import html.parser
import json
import pathlib
import re
import sys
import urllib.parse

import webfetch

TOOL = "page-watch"
DROP = {"script", "style", "noscript", "template", "svg"}
VOID = {"br", "hr", "img", "input", "meta", "link", "source", "track", "wbr", "area", "base", "col", "embed"}
BLOCK = {"p", "div", "section", "article", "main", "li", "ul", "ol", "tr", "table", "blockquote", "pre", "dl", "dt", "dd", "figure",
         "figcaption", "hr", "br", "address", "h1", "h2", "h3", "h4", "h5", "h6", "header", "footer", "nav", "aside", "form", "title", "option"}


class Visible(html.parser.HTMLParser):
    """Visible text as lines, without scripts and styles and without elements the user marked as noisy."""

    def __init__(self, ids, classes):
        super().__init__(convert_charrefs=True)
        self.ids, self.classes = set(ids), set(classes)
        self.stack, self.pieces, self.dropped_elements = [], [], 0

    def handle_starttag(self, tag, attrs):
        attrs = {key: (value or "") for key, value in attrs}
        noisy = attrs.get("id") in self.ids or bool(set(attrs.get("class", "").split()) & self.classes)
        if noisy:
            self.dropped_elements += 1
        if tag in VOID:
            if tag in BLOCK and not self.stack:
                self.pieces.append("\n")
            return
        if tag in DROP or noisy:
            self.stack.append([tag, 0])
        else:
            for entry in reversed(self.stack):
                if entry[0] == tag:
                    entry[1] += 1
                    break
        if tag in BLOCK and not self.stack:
            self.pieces.append("\n")

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                if self.stack[index][1]:
                    self.stack[index][1] -= 1
                else:
                    del self.stack[index:]
                break
        if tag in BLOCK and not self.stack:
            self.pieces.append("\n")

    def handle_data(self, data):
        if not self.stack:
            self.pieces.append(data)


def normalise(body, content_type, rules):
    """Return (lines, counts of what the rules removed)."""
    if "html" in content_type or not content_type:
        parser = Visible(rules["ignore_ids"], rules["ignore_classes"])
        parser.feed(body.decode("utf-8", "replace"))
        parser.close()
        raw, elements = "".join(parser.pieces).split("\n"), parser.dropped_elements
    elif content_type.startswith("text/") or any(mark in content_type for mark in ("json", "xml", "javascript")):
        raw, elements = body.decode("utf-8", "replace").split("\n"), 0
    else:
        raw, elements = [f"binary content: {len(body)} bytes, sha256 {hashlib.sha256(body).hexdigest()}"], 0
    lines = [line for line in (re.sub(r"\s+", " ", line).strip() for line in raw) if line]
    patterns = [re.compile(pattern) for pattern in rules["ignore_lines"]]
    kept = [line for line in lines if not any(pattern.search(line) for pattern in patterns)]
    return kept, {"lines": len(lines) - len(kept), "elements": elements}


def folder_for(root, url):
    parts = urllib.parse.urlsplit(url)
    name = re.sub(r"[^a-z0-9]+", "-", (parts.netloc + parts.path).lower()).strip("-")[:50]
    return webfetch.state_dir("page-watch", root) / f"{name}-{hashlib.sha256(url.encode()).hexdigest()[:8]}"


def cmd_list(args):
    base = pathlib.Path(args.root) / ".mstack" / "page-watch"
    watches = sorted(base.glob("*/watch.json")) if base.is_dir() else []
    for path in watches:
        watch = json.loads(path.read_text(encoding="utf-8"))
        rules = sum(len(watch["rules"][key]) for key in ("ignore_lines", "ignore_ids", "ignore_classes"))
        print(f"{watch['url']}\n  last look {watch['last_checked']}, last change {watch.get('last_changed') or 'none seen'}, {watch['looks']} look(s), {rules} ignore rule(s)\n  {path.parent}")
    print(f"RESULT pass: {len(watches)} page(s) watched in {base}")
    return 0


def cmd_check(args):
    try:
        url = webfetch.check_url(args.url)
        for pattern in args.ignore_line:
            re.compile(pattern)
    except webfetch.BadURL as exc:
        print(f"blocked: {exc}")
        return 2
    except re.error as exc:
        print(f"blocked: an --ignore-line pattern is not a valid regular expression ({exc})")
        return 2
    folder = folder_for(args.root, url)
    watch_file = folder / "watch.json"
    now = datetime.datetime.now(datetime.timezone.utc)
    watch = json.loads(watch_file.read_text(encoding="utf-8")) if watch_file.exists() else {
        "url": url, "rules": {"ignore_lines": [], "ignore_ids": [], "ignore_classes": []}, "latest": None, "last_checked": None, "last_changed": None, "looks": 0}
    print(f"page-watch {url}\nuser agent: {webfetch.user_agent(TOOL)}")
    if watch["last_checked"]:
        since = (now - datetime.datetime.fromisoformat(watch["last_checked"])).total_seconds()
        if since < args.min_interval:
            print(f"blocked: this page was fetched {since:.0f} s ago; the pause between two looks is {args.min_interval:g} s (--min-interval). Nothing was requested")
            return 2
    rules = {key: list(value) for key, value in watch["rules"].items()}
    if args.clear_ignores:
        rules = {"ignore_lines": [], "ignore_ids": [], "ignore_classes": []}
    for key, extra in (("ignore_lines", args.ignore_line), ("ignore_ids", args.ignore_id), ("ignore_classes", args.ignore_class)):
        rules[key] = rules[key] + [item for item in extra if item not in rules[key]]
    rules_changed = rules != watch["rules"]
    listed = [f"line /{item}/" for item in rules["ignore_lines"]] + [f"id {item}" for item in rules["ignore_ids"]] + [f"class {item}" for item in rules["ignore_classes"]]
    print(f"ignore rules: {'; '.join(listed) or 'none'}")

    hops, problem = webfetch.follow(url, TOOL, timeout=args.timeout, max_bytes=5_000_000)
    page = hops[-1]
    kept = "the earlier snapshot was kept" if watch["latest"] else "no snapshot was saved"
    if problem or page.error:
        print(f"RESULT not verified: no usable answer from {page.url} ({problem or f'{page.error_kind}: {page.error}'}); {kept}")
        return 2
    if page.status != 200:
        refusal = " This skill does not sign in or work around a refusal." if page.status in (401, 403, 429) else ""
        print(f"RESULT not verified: the page answered {page.status}, so nothing was compared; {kept}.{refusal}")
        return 2
    textual = "html" in page.content_type or not page.content_type or page.content_type.startswith("text/") or any(
        mark in page.content_type for mark in ("json", "xml", "javascript"))
    stored = page.text().encode("utf-8") if textual else page.body  # kept as UTF-8 so a later look reads it the same way
    lines, removed_by_rules = normalise(stored, page.content_type, rules)
    if not lines:
        print(f"RESULT not verified: no text came out of the page (it may be built by JavaScript, or the rules remove everything); {kept}")
        return 2
    print(f"fetched {len(page.body)} bytes, {len(lines)} line(s) of text; the rules removed {removed_by_rules['lines']} line(s) and {removed_by_rules['elements']} element(s)")

    def save(stamp):
        snapshots = folder / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        (snapshots / f"{stamp}.page").write_bytes(stored)
        (snapshots / f"{stamp}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        watch.update(latest=stamp, latest_type=page.content_type, latest_sha256=hashlib.sha256(stored).hexdigest())

    stamp, extra = now.strftime("%Y%m%dT%H%M%SZ"), 1
    while (folder / "snapshots" / f"{stamp}.page").exists() or stamp == watch["latest"]:
        extra += 1
        stamp = f"{now:%Y%m%dT%H%M%SZ}-{extra}"
    watch.update(url=url, rules=rules, last_checked=now.isoformat(timespec="seconds"), looks=watch["looks"] + 1)
    earlier = watch["latest"]
    if earlier is None:
        save(stamp)
        watch_file.write_text(json.dumps(watch, indent=2) + "\n", encoding="utf-8")
        print(f"saved: {folder / 'snapshots' / (stamp + '.txt')}")
        print(f"RESULT not verified: first snapshot saved ({len(lines)} lines); there is no earlier one to compare with")
        return 2
    old_body = (folder / "snapshots" / f"{earlier}.page").read_bytes()
    old_lines, _ = normalise(old_body, watch.get("latest_type", "text/html"), rules)
    if rules_changed:
        print("the ignore rules changed, so the earlier page was read again with the current rules")
    added, removed = [], []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, old_lines, lines, autojunk=False).get_opcodes():
        if op in ("delete", "replace"):
            removed += old_lines[a1:a2]
        if op in ("insert", "replace"):
            added += lines[b1:b2]
    if not added and not removed:
        watch_file.write_text(json.dumps(watch, indent=2) + "\n", encoding="utf-8")
        print(f"RESULT pass: no change since the snapshot of {earlier} ({len(lines)} lines compared)")
        return 0
    diff = list(difflib.unified_diff(old_lines, lines, f"snapshot {earlier}", f"snapshot {stamp}", lineterm="", n=1))
    save(stamp)
    (folder / "diffs").mkdir(exist_ok=True)
    diff_file = folder / "diffs" / f"{earlier}-to-{stamp}.diff"
    diff_file.write_text("\n".join(diff) + "\n", encoding="utf-8")
    watch["last_changed"] = now.isoformat(timespec="seconds")
    watch_file.write_text(json.dumps(watch, indent=2) + "\n", encoding="utf-8")
    for label, sign, items in (("added", "+", added), ("removed", "-", removed)):
        print(f"{label} ({len(items)}):")
        for line in items[:25]:
            print(f"  {sign} {line[:200]}")
        if len(items) > 25:
            print(f"  ... {len(items) - 25} more in the diff file")
    print(f"diff: {diff_file}")
    print(f"RESULT fail: the page changed since the snapshot of {earlier}: {len(added)} line(s) added, {len(removed)} removed")
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder that holds .mstack/ (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    check = sub.add_parser("check", help="fetch one page and compare it with its last snapshot")
    check.add_argument("url", help="the page to watch")
    check.add_argument("--ignore-line", action="append", default=[], metavar="REGEX", help="drop text lines that match (saved for next time)")
    check.add_argument("--ignore-id", action="append", default=[], metavar="ID", help="drop the element with this id (saved for next time)")
    check.add_argument("--ignore-class", action="append", default=[], metavar="CLASS", help="drop elements with this class (saved for next time)")
    check.add_argument("--clear-ignores", action="store_true", help="forget the saved ignore rules before applying the ones given now")
    check.add_argument("--min-interval", type=float, default=60.0, help="seconds that must pass between two looks at one page (default 60)")
    check.add_argument("--timeout", type=float, default=15.0, help="seconds to wait (default 15)")
    sub.add_parser("list", help="show the pages watched in this project")
    args = parser.parse_args()
    return cmd_list(args) if args.action == "list" else cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
