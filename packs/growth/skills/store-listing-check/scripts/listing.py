#!/usr/bin/env python3
"""Check an app store listing, kept as a file, against the store's field limits.

  listing.py <listing.json> [--sources sources.json] [--out report.json]

The listing file is JSON:
  { "store": "apple" or "google",
    "name": "...", "subtitle": "...", "promotional_text": "...", "short_description": "...", "description": "...",
    "keywords": "one,two,three" (or a list), "screenshots": ["shots/1.png", "shots/2.png"] }

Checks:
  required   every field the store entry in references/store-limits.json lists as required is filled
  lengths    each text field against its limit in that file
  keywords   total length; the same keyword twice; keywords already in the name or subtitle; spaces after commas
  screenshots  how many, against the store's range; every local file exists (paths relative to the listing file)
  claims     every number, superlative, comparison or testimonial in the text fields, found with the same rules
             as claim-check; each needs an entry in --sources (same file format as claim-check) or it fails
  leftovers  placeholder text such as "lorem ipsum" or TODO

The limits are dated and unverified; the script says so. This reads the file, not the live store page, and it
states nothing about how often a keyword is searched. No network is used.

Exit codes: 0 = pass, 1 = fail, 2 = not verified (remote screenshots, unopened evidence) or blocked.
"""
import argparse
import json
import pathlib
import re
import sys

import claims as cl

HERE = pathlib.Path(__file__).resolve().parent
TEXT_FIELDS = ("name", "subtitle", "promotional_text", "short_description", "description")
LEFTOVER = re.compile(r"lorem ipsum|\bTODO\b|\bTBD\b|\bTK\b|\{\{[^}]*\}\}|\[(?:app name|name|placeholder)\]", re.I)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("listing", help="the listing file (JSON)")
    parser.add_argument("--sources", help="sources for the claims in the listing, in claim-check's format")
    parser.add_argument("--limits", type=pathlib.Path, default=HERE.parent / "references" / "store-limits.json",
                        help="dated store limits (default: references/store-limits.json)")
    parser.add_argument("--out", help="also write the three lists as JSON to this new file")
    args = parser.parse_args()

    if args.out and pathlib.Path(args.out).exists():
        return cl.blocked(f"{args.out} exists; reports are never overwritten, name a new file")
    try:
        stores = json.loads(args.limits.read_text(encoding="utf-8"))["stores"]
    except (OSError, ValueError, KeyError) as exc:
        return cl.blocked(f"limits file {args.limits} cannot be read: {exc}")
    path = pathlib.Path(args.listing)
    try:
        listing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(listing, dict):
            raise ValueError("the top level has to be an object")
    except (OSError, ValueError) as exc:
        return cl.blocked(f"listing file {args.listing} cannot be read: {exc}")
    store = str(listing.get("store", "")).lower()
    if store not in stores:
        return cl.blocked(f"the listing's \"store\" has to be one of {', '.join(stores)}; got '{listing.get('store', '')}'")
    entries = None
    if args.sources:
        try:
            entries = cl.load_sources(args.sources)
        except (OSError, ValueError) as exc:
            return cl.blocked(f"sources file {args.sources} cannot be read: {exc}")
    rules = stores[store]

    report = cl.Report(f"store-listing-check {args.listing} ({store})")
    loose = [entry for entry in rules.values() if not entry.get("verified")]
    if loose:
        dates = ", ".join(sorted({entry.get("checked", "?") for entry in loose}))
        report.note(f"all {len(loose)} limits used for this store are unverified (written from memory, dated {dates}): "
                    f"check them against the store's own documentation before submitting")

    def text_of(field):
        value = listing.get(field)
        return value.strip() if isinstance(value, str) else ""

    keywords_raw = listing.get("keywords", "")
    keywords_text = ",".join(keywords_raw) if isinstance(keywords_raw, list) else str(keywords_raw or "")
    shots = listing.get("screenshots") if isinstance(listing.get("screenshots"), list) else []

    # required
    filled = {"keywords": bool(keywords_text.strip()), "screenshots": bool(shots)}
    absent = [f for f in rules["required_fields"]["value"] if not filled.get(f, bool(text_of(f)))]
    if absent:
        report.fail(f"required fields empty or missing: {', '.join(absent)}")
    else:
        report.ok(f"required fields filled: {', '.join(rules['required_fields']['value'])}")

    # lengths
    for key, entry in rules.items():
        if not key.endswith("_max_chars"):
            continue
        field = key[:-len("_max_chars")]
        value = keywords_text if field == "keywords" else text_of(field)
        if not value:
            continue
        if len(value) > entry["value"]:
            report.fail(f"{field} is {len(value)} characters, over the limit of {entry['value']} by {len(value) - entry['value']}")
        else:
            report.ok(f"{field}: {len(value)} of {entry['value']} characters")
    unknown = [f for f in listing if f not in TEXT_FIELDS + ("store", "keywords", "screenshots") and not f.startswith("_")]
    if unknown:
        report.skip(f"fields this script has no rule for: {', '.join(unknown)}")

    # keywords
    if keywords_text.strip():
        words = [k for k in keywords_text.split(",")]
        clean = [k.strip().lower() for k in words if k.strip()]
        twice = sorted({k for k in clean if clean.count(k) > 1})
        if twice:
            report.fail(f"keywords repeated in the keyword field: {', '.join(twice)}")
        else:
            report.ok(f"{len(clean)} keywords, none repeated")
        padded = sum(1 for k in words if k != k.strip())
        if padded:
            report.warn(f"{padded} keywords have a space beside the comma; each space uses up a character of the limit")
        headline = set(re.findall(r"[^\W_]+", (text_of("name") + " " + text_of("subtitle")).lower()))
        echoed = sorted(k for k in set(clean) if k in headline)
        if echoed:
            report.warn(f"keywords that already appear in the name or subtitle: {', '.join(echoed)}")
        pairs = sorted(k for k in set(clean) if k + "s" in clean)
        if pairs:
            report.warn(f"singular and plural of the same keyword: {', '.join(f'{k}/{k}s' for k in pairs)}")
    elif "keywords_max_chars" not in rules and listing.get("keywords"):
        report.skip("keywords: this store entry has no keyword field")

    # screenshots
    if shots:
        low, high = rules["screenshots_min"]["value"], rules["screenshots_max"]["value"]
        if not low <= len(shots) <= high:
            report.fail(f"{len(shots)} screenshots; the store entry allows {low} to {high}")
        else:
            report.ok(f"{len(shots)} screenshots, within {low} to {high}")
        present = 0
        for shot in shots:
            if re.match(r"^https?://", str(shot), re.I):
                report.skip(f"remote screenshot not opened: {shot}", blocks=True)
            elif (path.parent / str(shot)).is_file() and (path.parent / str(shot)).stat().st_size > 0:
                present += 1
            else:
                report.fail(f"screenshot file not found or empty: {shot}")
        if present:
            report.ok(f"{present} screenshot files exist")
        report.skip("screenshot pixel sizes and what the screenshots show (use ios-submit-check for App Store sizes)")

    # claims and leftovers
    found = []
    for field in TEXT_FIELDS:
        value = text_of(field)
        if LEFTOVER.search(value):
            report.fail(f"{field} holds placeholder text: '{LEFTOVER.search(value).group(0)}'")
        for claim in cl.find_claims(value):
            claim["field"], claim["where"] = field, f"{field} "
            found.append(claim)
    if not found:
        report.ok("no number, superlative, comparison or testimonial in the text fields")
    elif entries is None:
        for claim in found:
            report.fail(f"claim with no source: {claim['field']} line {claim['line']} [{', '.join(claim['kinds'])}] "
                        f"\"{claim['text'][:110]}\" (give --sources, or remove it)")
    else:
        cl.check_claims(found, entries, pathlib.Path(args.sources).resolve().parent, False, report)

    report.skip("the live store page: this read the file only")
    report.skip("how often any keyword is searched: no figure is stated without a measured source")
    report.skip("the store's review rules on content, privacy answers and age rating")
    return report.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
