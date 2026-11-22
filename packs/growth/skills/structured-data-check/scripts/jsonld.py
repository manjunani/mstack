#!/usr/bin/env python3
"""Check the JSON-LD structured data in one or more pages.

  jsonld.py <file-or-url> [<file-or-url> ...] [--out report.json]

For every <script type="application/ld+json"> block it checks that:
  - the block parses as JSON (the line and column of the error are shown);
  - it has an @context that names schema.org, and every item has an @type;
  - items of the types in references/types.json carry the properties that file lists
    (Article, Product, Organization, BreadcrumbList, FAQPage, SoftwareApplication and their listed aliases);
  - ratings and FAQ questions in the markup also appear in the page's visible text.

The property lists are a dated, unverified summary. The search engine's own testing tool is the authority on
whether a page qualifies for a search feature; this script only says whether the markup is well formed.
A page with no JSON-LD is a pass with that reason given. A URL is fetched once; nothing else is requested.

Exit codes: 0 = pass, 1 = fail, 2 = not verified (markup this script cannot read) or blocked (source unreadable).
"""
import argparse
import json
import pathlib
import sys

import pagefacts as pf

HERE = pathlib.Path(__file__).resolve().parent
EMPTY = ("", None, [], {})


def as_list(value):
    return value if isinstance(value, list) else [value]


def has_schema_context(context):
    if isinstance(context, str):
        return "schema.org" in context
    if isinstance(context, dict):
        return any(has_schema_context(v) for v in context.values())
    if isinstance(context, list):
        return any(has_schema_context(v) for v in context)
    return False


def walk(node, path):
    """Values found at a dotted path, going through lists on the way."""
    found = [node]
    for step in path.split("."):
        following = []
        for item in found:
            for one in as_list(item):
                if isinstance(one, dict) and one.get(step) not in EMPTY:
                    following.extend(as_list(one[step]))
        found = following
    return found


def rules_for(types, kind):
    for name, entry in types.items():
        if isinstance(entry, dict) and "value" in entry and (kind == name or kind in entry["value"].get("also", [])):
            return name, entry
    return None, None


def check_item(item, where, types, page, report):
    kinds = [k for k in as_list(item.get("@type")) if isinstance(k, str)]
    if not kinds:
        report.fail(f"{where}: an item has no @type")
        return
    for kind in kinds:
        name, entry = rules_for(types, kind)
        label = f"{where} {kind}"
        if entry is None:
            report.skip(f"{label}: no property list for this type in the data file; only parsing, @context and @type were checked")
            continue
        rule, problems = entry["value"], 0
        for key in rule.get("required", []):
            if item.get(key) in EMPTY:
                report.fail(f"{label}: required property '{key}' is missing or empty")
                problems += 1
        either = rule.get("one_of", [])
        if either and all(item.get(key) in EMPTY for key in either):
            report.fail(f"{label}: needs at least one of {', '.join(either)}")
            problems += 1
        for nested in rule.get("nested", []):
            for number, child in enumerate(walk(item, nested["path"]), 1):
                if not isinstance(child, dict):
                    report.fail(f"{label}: {nested['path']} entry {number} is not an object")
                    problems += 1
                    continue
                for key in nested["required"]:
                    if child.get(key) in EMPTY:
                        report.fail(f"{label}: {nested['path']} entry {number} has no '{key}'")
                        problems += 1
        absent = [key for key in rule.get("recommended", []) if item.get(key) in EMPTY]
        if absent:
            report.warn(f"{label}: recommended properties not set: {', '.join(absent)}")
        if rule.get("note"):
            report.note(f"{name}: {rule['note']} (unverified, dated {entry.get('checked')})")
        if not problems:
            report.ok(f"{label}: parses and has the listed required properties")
    if page.built_by_script():
        return
    seen = page.text.casefold()
    for rating in walk(item, "aggregateRating"):
        if isinstance(rating, dict):
            shown = [str(rating[k]) for k in ("ratingValue", "reviewCount", "ratingCount") if rating.get(k) not in EMPTY]
            hidden = [v for v in shown if v.casefold() not in seen]
            if hidden:
                report.warn(f"{where}: aggregateRating values {', '.join(hidden)} are not in the page's visible text; "
                            f"a marked-up rating has to match reviews a visitor can see")
    if "FAQPage" in kinds:
        for question in walk(item, "mainEntity"):
            if isinstance(question, dict) and isinstance(question.get("name"), str) and pf.squash(question["name"]).casefold() not in seen:
                report.warn(f"{where}: FAQ question not found in the visible text: '{pf.squash(question['name'])[:70]}'")


def check_source(source, types, report, timeout):
    try:
        text, _ = pf.read_source(source, timeout)
    except pf.SourceError as exc:
        report.skip(f"{source}: not read ({exc})", blocks=True)
        return 0
    page = pf.parse(text)
    if page.microdata or page.rdfa:
        report.skip(f"{source}: {page.microdata + page.rdfa} microdata or RDFa items; this script reads JSON-LD only", blocks=True)
    if not page.jsonld:
        if page.built_by_script():
            report.skip(f"{source}: no JSON-LD in the HTML, but the page is built by script and may add it in the browser",
                        blocks=True)
        else:
            report.note(f"{source}: no JSON-LD blocks in the HTML")
        return 0
    for number, raw in enumerate(page.jsonld, 1):
        where = f"{source} block {number}"
        try:
            data = json.loads(raw)
        except ValueError as exc:
            report.fail(f"{where}: does not parse as JSON: {exc}")
            continue
        if data in EMPTY:
            report.fail(f"{where}: the block is empty")
            continue
        for top in as_list(data):
            if not isinstance(top, dict):
                report.fail(f"{where}: the top level is not an object")
                continue
            if "@context" not in top:
                report.fail(f"{where}: no @context")
            elif not has_schema_context(top["@context"]):
                report.skip(f"{where}: @context is not schema.org ({str(top['@context'])[:60]}); its vocabulary was not checked")
                continue
            items = as_list(top["@graph"]) if "@graph" in top else [top]
            for item in items:
                if isinstance(item, dict):
                    check_item(item, where, types, page, report)
                else:
                    report.fail(f"{where}: an entry in @graph is not an object")
    return len(page.jsonld)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="+", help="HTML files or http(s) addresses")
    parser.add_argument("--types", type=pathlib.Path, default=HERE.parent / "references" / "types.json",
                        help="dated property lists (default: references/types.json)")
    parser.add_argument("--timeout", type=int, default=15, help="seconds allowed per fetch (default 15)")
    parser.add_argument("--out", help="also write the three lists as JSON to this new file")
    args = parser.parse_args()
    if pf.out_refused(args.out):
        return pf.blocked(f"{args.out} exists; reports are never overwritten, name a new file")
    try:
        types, lines = pf.load_data(args.types)
    except (OSError, ValueError, KeyError) as exc:
        return pf.blocked(f"types file {args.types} cannot be read: {exc}")
    report = pf.Report(f"structured-data-check {' '.join(args.sources)}")
    for line in lines:
        report.note(line)
    blocks = sum(check_source(source, types, report, args.timeout) for source in args.sources)
    report.skip("whether a page qualifies for a search feature: the search engine's own testing tool is the authority")
    report.skip("microdata, RDFa and markup added in the browser by script")
    return report.finish(args.out, nothing=None if blocks else "no JSON-LD in the HTML, nothing to validate")


if __name__ == "__main__":
    sys.exit(main())
