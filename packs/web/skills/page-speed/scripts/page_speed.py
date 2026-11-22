#!/usr/bin/env python3
"""Measure how one page transfers: time to first byte, transfer time and bytes for the document and
the assets its HTML lists, the request count, uncompressed text and missing cache headers.

  page_speed.py URL                         measure the document three times and each listed asset once
  page_speed.py URL --runs 5                more runs of the document; the median is reported
  page_speed.py URL --budget-bytes 500000   fail when the bytes on the wire are above this
  page_speed.py URL --budget-ttfb-ms 300    fail when the median time to first byte is above this
  page_speed.py URL --budget-requests 30    fail when the page needs more requests than this
  page_speed.py URL --transfer-only         the user asked about transfer only: allow a pass without rendering metrics
  page_speed.py URL --json speed.json       also write the measurements to a new file

What it cannot do: it has no browser. Largest contentful paint, layout shift, interaction delay, first
paint and script run time are NOT measured, and the run says so and ends that part as not verified.
Each request opens a new connection and assets are fetched one after another, so the summed time is
not a load time. Assets named inside style sheets and scripts, and srcset candidates, are not fetched.

Robots rules are read for every host an asset lives on; a disallowed asset is listed as not measured.

Exit codes: 0 = transfer checks passed and --transfer-only was given
            1 = fail: a failed asset, uncompressed text, missing cache headers, or a budget exceeded
            2 = not verified or blocked: rendering not measured (the normal end without --transfer-only),
                an asset that could not be measured, no answer, bad input
"""
import argparse
import datetime
import html.parser
import json
import pathlib
import statistics
import sys
import urllib.parse

import webfetch

TOOL = "page-speed"
BUDGETS = pathlib.Path(__file__).resolve().parent.parent / "references" / "budgets.json"
ASSET_RELS = {"stylesheet", "icon", "preload", "modulepreload", "manifest", "apple-touch-icon"}
TEXT_TYPES = ("text/", "javascript", "json", "xml", "svg")
RENDERING = "largest contentful paint, layout shift, interaction delay, first paint and script run time"


class Assets(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.base, self.srcsets = [], None, 0

    def handle_starttag(self, tag, attrs):
        attrs = {key: (value or "").strip() for key, value in attrs}
        if tag == "base" and attrs.get("href") and self.base is None:
            self.base = attrs["href"]
        if attrs.get("srcset"):
            self.srcsets += 1
        if tag == "link" and set(attrs.get("rel", "").lower().split()) & ASSET_RELS:
            self.found.append(attrs.get("href"))
        elif tag in ("script", "img", "source", "audio", "video", "iframe", "embed", "track"):
            self.found.append(attrs.get("src"))
            self.found.append(attrs.get("poster"))
        elif tag == "object":
            self.found.append(attrs.get("data"))


def size(count):
    return f"{count / 1024:.1f} kB" if count >= 1024 else f"{count} B"


def ms(seconds):
    return f"{seconds * 1000:.0f} ms"


def cache_state(response):
    control = response.header("cache-control").lower()
    if any(word in control for word in ("no-store", "no-cache", "max-age=0")):
        return "off", f"Cache-Control: {control}"
    if control or response.header("expires"):
        return "ok", control or f"Expires: {response.header('expires')}"
    if response.header("etag") or response.header("last-modified"):
        return "validator", "ETag or Last-Modified only"
    return "missing", "no Cache-Control, Expires, ETag or Last-Modified"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="the page to measure")
    parser.add_argument("--runs", type=int, default=3, help="times the document is fetched; the median is reported (default 3)")
    parser.add_argument("--max-assets", type=int, default=40, help="assets fetched; the rest are listed as not measured (default 40)")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests to one host; never below 1 for a public host (default 0.5)")
    parser.add_argument("--budget-bytes", type=int, help="fail above this many bytes on the wire for document plus assets")
    parser.add_argument("--budget-ttfb-ms", type=float, help="fail above this median time to first byte of the document")
    parser.add_argument("--budget-requests", type=int, help="fail above this many requests")
    parser.add_argument("--transfer-only", action="store_true", help="scope the claim to transfer, so a pass is possible without rendering metrics")
    parser.add_argument("--budgets-file", type=pathlib.Path, default=BUDGETS, help="dated default limits (default: references/budgets.json)")
    parser.add_argument("--json", type=pathlib.Path, metavar="FILE", help="write the measurements to this new file")
    parser.add_argument("--timeout", type=float, default=15.0, help="seconds to wait per request (default 15)")
    args = parser.parse_args()

    try:
        url = webfetch.check_url(args.url)
        budgets = json.loads(args.budgets_file.read_text(encoding="utf-8"))
        default_ttfb, min_compress = budgets["ttfb_ms"], budgets["min_compress_bytes"]
    except webfetch.BadURL as exc:
        print(f"blocked: {exc}")
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(f"blocked: the budgets file could not be used ({exc})")
        return 2
    if args.json and args.json.exists():
        print(f"blocked: {args.json} already exists; name a new file")
        return 2
    if not 1 <= args.runs <= 10:
        print("blocked: --runs takes a number from 1 to 10")
        return 2

    print(f"page-speed {url}\nuser agent: {webfetch.user_agent(TOOL)}")
    throttle = webfetch.Throttle(args.delay)
    options = {"timeout": args.timeout, "max_bytes": 10_000_000, "throttle": throttle}
    hops, problem = webfetch.follow(url, TOOL, **options)
    document, requests = hops[-1], len(hops)
    for hop in hops[:-1]:
        print(f"  redirect: {hop.status} {hop.url} -> {hop.location} ({ms(hop.total)})")
    if problem or document.error:
        why = problem or f"{document.error_kind}: {document.error}"
        print(f"RESULT not verified: no usable answer from {document.url} ({why})")
        return 2
    if document.status != 200:
        print(f"RESULT fail: the page answered {document.status}; there is no page to measure")
        return 1
    samples = [document]
    for _ in range(args.runs - 1):
        throttle.wait(document.url)
        again = webfetch.fetch(document.url, TOOL, timeout=args.timeout, max_bytes=10_000_000)
        throttle.observe(again)
        if again.error or again.status != 200 or throttle.stop_reason(document.url):
            print(f"  note: a repeat run did not answer 200 ({again.status or again.error}); the median uses {len(samples)} run(s)")
            break
        samples.append(again)
    ttfb = statistics.median(sample.ttfb for sample in samples)
    total_time = statistics.median(sample.total for sample in samples)

    fails, warns, unmeasured, rows = [], [], [], []
    rows.append({"url": document.url, "kind": "document", "status": 200, "wire": len(document.wire), "decoded": len(document.body),
                 "encoding": document.header("content-encoding") or "none", "cache": cache_state(document)[1],
                 "ttfb": ttfb, "total": total_time, "type": document.content_type})
    parser_ = Assets()
    if "html" in document.content_type:
        parser_.feed(document.text())
    base = urllib.parse.urljoin(document.url, parser_.base) if parser_.base else document.url
    wanted = []
    for value in parser_.found:
        if value and not value.lower().startswith(("data:", "blob:", "javascript:", "about:", "#")):
            target = urllib.parse.urldefrag(urllib.parse.urljoin(base, value))[0]
            if target.lower().startswith(("http:", "https:")) and target not in wanted and target != document.url:
                wanted.append(target)
    robots = {}
    page_is_local = webfetch.is_local(urllib.parse.urlsplit(document.url).hostname)
    for number, target in enumerate(wanted):
        if number >= args.max_assets:
            unmeasured.append((target, f"above the limit of {args.max_assets} assets"))
            continue
        try:
            webfetch.check_url(target)
        except webfetch.BadURL as exc:
            unmeasured.append((target, str(exc)))
            continue
        if webfetch.is_local(urllib.parse.urlsplit(target).hostname) and not page_is_local:
            unmeasured.append((target, "points at a local or private address"))
            continue
        origin = webfetch.origin_of(target)
        if origin not in robots:
            robots[origin] = webfetch.load_robots(origin, TOOL, args.timeout, throttle)
            throttle.raise_delay(target, robots[origin].rules.delay)
        verdict = robots[origin].verdict(target)
        if verdict != "allowed":
            unmeasured.append((target, "disallowed by robots.txt" if verdict == "disallowed" else f"robots.txt of {origin} could not be read"))
            continue
        if throttle.stop_reason(target):
            unmeasured.append((target, throttle.stop_reason(target)))
            continue
        asset_hops, asset_problem = webfetch.follow(target, TOOL, max_hops=3, **options)
        requests += len(asset_hops)
        asset = asset_hops[-1]
        if asset_problem or asset.error:
            unmeasured.append((target, asset_problem or f"no answer ({asset.error_kind}: {asset.error})"))
            continue
        if throttle.stop_reason(asset.url):
            unmeasured.append((target, throttle.stop_reason(asset.url)))
            continue
        if asset.status != 200:
            fails.append(f"asset answered {asset.status}: {target}")
            continue
        state, detail = cache_state(asset)
        rows.append({"url": target, "kind": "asset", "status": 200, "wire": len(asset.wire), "decoded": len(asset.body),
                     "encoding": asset.header("content-encoding") or "none", "cache": detail, "type": asset.content_type,
                     "ttfb": sum(hop.ttfb or 0 for hop in asset_hops), "total": sum(hop.total or 0 for hop in asset_hops)})
        if state == "missing":
            fails.append(f"no cache headers: {target}")
        elif state in ("validator", "off"):
            warns.append(f"asset is checked or downloaded again on every visit ({detail}): {target}")
        if asset.truncated:
            warns.append(f"larger than 10 MB, measured only in part: {target}")

    for row in rows:
        textual = any(mark in row["type"] for mark in TEXT_TYPES)
        if textual and row["encoding"] == "none" and row["wire"] >= min_compress["value"]:
            fails.append(f"uncompressed {row['type']} of {size(row['wire'])}: {row['url']}")
    wire_total = sum(row["wire"] for row in rows)
    time_total = sum(row["total"] for row in rows)
    if args.budget_bytes is not None and wire_total > args.budget_bytes:
        fails.append(f"{wire_total} bytes on the wire, budget {args.budget_bytes}")
    if args.budget_requests is not None and requests > args.budget_requests:
        fails.append(f"{requests} requests, budget {args.budget_requests}")
    if args.budget_ttfb_ms is not None and ttfb * 1000 > args.budget_ttfb_ms:
        fails.append(f"median time to first byte {ms(ttfb)}, budget {args.budget_ttfb_ms:g} ms")
    elif args.budget_ttfb_ms is None and ttfb * 1000 > default_ttfb["value"]:
        warns.append(f"median time to first byte {ms(ttfb)} is above the default of {default_ttfb['value']} ms "
                     f"(a warning only: that limit is {'verified' if default_ttfb.get('verified') else 'unverified, written from memory'}; pass --budget-ttfb-ms to make it a check)")

    spread = f"{ms(min(s.ttfb for s in samples))} to {ms(max(s.ttfb for s in samples))}"
    print(f"document: {document.url}")
    print(f"  time to first byte: median {ms(ttfb)} of {len(samples)} run(s) ({spread}); includes DNS, connect and TLS, new connection each run")
    print(f"  transfer complete: median {ms(total_time)}; {size(len(document.wire))} on the wire, {size(len(document.body))} decoded, encoding {rows[0]['encoding']}")
    print(f"assets listed in the HTML: {len(wanted)}, measured {len(rows) - 1}")
    for row in sorted(rows[1:], key=lambda r: -r["wire"])[:12]:
        print(f"  {size(row['wire']):>10}  {ms(row['total']):>7}  {row['encoding']:5}  {row['url']}")
    if len(rows) > 13:
        print(f"  ... {len(rows) - 13} smaller asset(s) not shown")
    print(f"totals: {requests} request(s) to {len({webfetch.host_of(row['url']) for row in rows})} host(s), {size(wire_total)} on the wire, "
          f"{ms(time_total)} of transfer time added up (fetched one after another; not a load time)")
    unverified = [name for name in ("ttfb_ms", "min_compress_bytes") if not budgets[name].get("verified")]
    if unverified:
        print(f"note: default limits marked unverified in {args.budgets_file.name}: {', '.join(unverified)} (checked {budgets[unverified[0]]['checked']}, written from memory)")
    for label, items in (("FAIL", fails), ("warn", warns)):
        for item in items:
            print(f"  {label}  {item}")
    for target, why in unmeasured:
        print(f"  not measured  {target}: {why}")
    if parser_.srcsets:
        print(f"  not measured  srcset candidates on {parser_.srcsets} element(s): only src was fetched")
    print(f"  not measured  assets named inside style sheets and scripts")
    print(f"rendering: not verified. This script has no browser, so {RENDERING} were not measured. Use the host's browser performance tool for those.")

    if fails:
        result, code = f"RESULT fail: {len(fails)} finding(s): " + "; ".join(fails[:3])[:260], 1
    elif unmeasured:
        result, code = f"RESULT not verified: {len(unmeasured)} asset(s) could not be measured; rendering metrics were not measured", 2
    elif args.transfer_only:
        result, code = "RESULT pass: transfer checks only; rendering metrics were not measured", 0
    else:
        result, code = "RESULT not verified: the transfer checks passed, but rendering metrics were not measured (a browser is needed)", 2
    if args.json:
        args.json.write_text(json.dumps({"url": url, "measured": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                                         "runs": len(samples), "ttfb_ms": [round(s.ttfb * 1000, 1) for s in samples], "requests": requests,
                                         "wire_bytes": wire_total, "rows": rows, "failed": fails, "warnings": warns,
                                         "not_measured": [{"url": target, "why": why} for target, why in unmeasured] ,
                                         "rendering": "not measured: no browser", "result": result}, indent=2) + "\n", encoding="utf-8")
        print(f"measurements written to {args.json}")
    print(result)
    return code


if __name__ == "__main__":
    sys.exit(main())
