#!/usr/bin/env python3
"""Crawl one site politely and report what stops its pages being found and understood by search engines.

  audit.py <start-url> [--max-pages 25] [--delay 0.5] [--out report.json]

What it does, in order:
  1. reads /robots.txt and obeys it (a page closed to this checker is not fetched);
  2. reads the sitemaps named in robots.txt, or /sitemap.xml, and asks each listed URL whether it answers;
  3. follows links that stay on the start URL's site, up to --max-pages pages, one request at a time;
  4. checks each page: title and its length, meta description, h1 count, heading order, canonical link,
     language attribute, image alt text, internal link count, noindex;
  5. prints three lists: findings, checked and fine, not checked.

Length guidance comes from references/limits.json, a dated file whose values are unverified guidance.
The script only reads. It sends GET and HEAD requests to the one site named and to no other host.

Exit codes: 0 = pass, 1 = fail (a finding blocks), 2 = not verified (crawl cut short, pages unreadable) or blocked.
"""
import argparse
import collections
import gzip
import pathlib
import statistics
import sys
import time
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ElementTree

import pagefacts as pf

HERE = pathlib.Path(__file__).resolve().parent
NOT_PAGES = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js", ".zip", ".gz", ".mp4",
             ".mp3", ".woff", ".woff2", ".xml", ".json", ".txt", ".dmg", ".exe")
HARD_PAGE_CAP = 500

# key, blocks, what the finding says, what the fine line says
CHECKS = [
    ("title_missing", True, "no <title>", "a <title> is present"),
    ("title_many", False, "more than one <title>", "one <title> per page"),
    ("title_short", False, "title shorter than the guidance", None),
    ("title_long", False, "title longer than the guidance", "title length within the guidance"),
    ("desc_missing", False, "no meta description", "a meta description is present"),
    ("desc_many", False, "more than one meta description", None),
    ("desc_short", False, "meta description shorter than the guidance", None),
    ("desc_long", False, "meta description longer than the guidance", "meta description length within the guidance"),
    ("h1_missing", True, "no <h1>", "an <h1> is present"),
    ("h1_many", False, "more than one <h1>", "exactly one <h1>"),
    ("heading_order", False, "heading levels out of order", "heading levels in order"),
    ("canonical_missing", False, "no canonical link", "a canonical link is present"),
    ("canonical_many", True, "more than one canonical link", None),
    ("canonical_offsite", True, "canonical link points to another site", "canonical links stay on this site"),
    ("lang_missing", False, "no lang attribute on <html>", "lang attribute present"),
    ("alt_missing", False, "images with no alt attribute", "every image has an alt attribute"),
    ("no_internal_links", False, "no link to another page of the site", "every page links onward inside the site"),
]


def normal(url):
    url = urllib.parse.urldefrag(url)[0]
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    default = {"http": 80, "https": 443}.get(parts.scheme)
    netloc = host if parts.port in (None, default) else f"{host}:{parts.port}"
    return urllib.parse.urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def short(url):
    parts = urllib.parse.urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def some(urls, limit=5):
    urls = sorted(urls)
    shown = ", ".join(short(u) for u in urls[:limit])
    return shown + (f" and {len(urls) - limit} more" if len(urls) > limit else "")


def read_sitemap(body):
    """Return (kind, [loc]) where kind is 'index', 'urls' or None when the XML cannot be read."""
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except (OSError, EOFError):
            return None, []
    if b"<!ENTITY" in body or b"<!DOCTYPE" in body:
        return None, []
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return None, []
    name = root.tag.rsplit("}", 1)[-1].lower()
    locs = [el.text.strip() for el in root.iter() if el.tag.rsplit("}", 1)[-1].lower() == "loc" and el.text and el.text.strip()]
    if name == "sitemapindex":
        return "index", locs
    if name == "urlset":
        return "urls", locs
    return None, []


def check_page(page, url, limits):
    """Return {check key: detail} for one parsed page."""
    issues = {}
    title = page.title
    if not title:
        issues["title_missing"] = ""
    else:
        if len(title) < limits["title_min_chars"]["value"]:
            issues["title_short"] = f"{len(title)} characters"
        if len(title) > limits["title_max_chars"]["value"]:
            issues["title_long"] = f"{len(title)} characters"
    if len(page.titles) > 1:
        issues["title_many"] = str(len(page.titles))
    descriptions = page.meta_all("description")
    if not descriptions or not descriptions[0]:
        issues["desc_missing"] = ""
    else:
        if len(descriptions[0]) < limits["description_min_chars"]["value"]:
            issues["desc_short"] = f"{len(descriptions[0])} characters"
        if len(descriptions[0]) > limits["description_max_chars"]["value"]:
            issues["desc_long"] = f"{len(descriptions[0])} characters"
    if len(descriptions) > 1:
        issues["desc_many"] = str(len(descriptions))
    canonicals = [link["href"] for link in page.rel("canonical") if link["href"]]
    if not canonicals:
        issues["canonical_missing"] = ""
    elif len(set(canonicals)) > 1:
        issues["canonical_many"] = str(len(canonicals))
    elif not pf.same_site(urllib.parse.urljoin(url, canonicals[0]), url):
        issues["canonical_offsite"] = canonicals[0]
    if not (page.lang or "").strip():
        issues["lang_missing"] = ""
    if page.built_by_script():
        return issues, True
    levels = [h["level"] for h in page.headings]
    if levels.count(1) == 0:
        issues["h1_missing"] = ""
    elif levels.count(1) > 1:
        issues["h1_many"] = str(levels.count(1))
    if levels and levels[0] != 1:
        issues["heading_order"] = f"first heading is h{levels[0]}"
    else:
        for before, after in zip(levels, levels[1:]):
            if after > before + 1:
                issues["heading_order"] = f"h{before} followed by h{after}"
                break
    bare = sum(1 for image in page.images if image["alt"] is None)
    if bare:
        issues["alt_missing"] = f"{bare} of {len(page.images)}"
    return issues, False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="where the crawl starts, for example https://your-site.tld/")
    parser.add_argument("--max-pages", type=int, default=25, help="pages to fetch at most (default 25, never more than 500)")
    parser.add_argument("--max-sitemap-urls", type=int, default=50, help="sitemap URLs to ask at most (default 50)")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests (default 0.5)")
    parser.add_argument("--max-seconds", type=int, default=300, help="stop the crawl after this long (default 300)")
    parser.add_argument("--timeout", type=int, default=15, help="seconds allowed per request (default 15)")
    parser.add_argument("--limits", type=pathlib.Path, default=HERE.parent / "references" / "limits.json",
                        help="dated length guidance (default: references/limits.json)")
    parser.add_argument("--out", help="also write the three lists as JSON to this new file")
    args = parser.parse_args()

    if pf.out_refused(args.out):
        return pf.blocked(f"{args.out} exists; reports are never overwritten, name a new file")
    problem = pf.url_problem(args.url)
    if problem:
        return pf.blocked(problem)
    if args.max_pages < 1:
        return pf.blocked("--max-pages has to be 1 or more")
    max_pages = min(args.max_pages, HARD_PAGE_CAP)
    try:
        limits, lines = pf.load_data(args.limits)
    except (OSError, ValueError, KeyError) as exc:
        return pf.blocked(f"limits file {args.limits} cannot be read: {exc}")

    start = normal(args.url)
    parts = urllib.parse.urlsplit(start)
    root = f"{parts.scheme}://{parts.netloc}"
    report = pf.Report(f"site-audit {start} (page limit {max_pages})")
    for line in lines:
        report.note(line)
    began = time.monotonic()
    requests = [0]

    def get(url, method="GET"):
        if requests[0] and args.delay > 0:
            time.sleep(args.delay)
        requests[0] += 1
        return pf.fetch(url, timeout=args.timeout, method=method)

    # 1. robots.txt
    rules = urllib.robotparser.RobotFileParser()
    rules.parse([])
    named_sitemaps = []
    robots = get(root + "/robots.txt")
    if robots["error"]:
        return pf.blocked(f"{root} could not be reached: {robots['error']}")
    robots_text = pf.decode(robots["body"], robots["headers"])
    if robots["status"] == 200 and pf.looks_like_html(robots_text):
        report.fail("/robots.txt answers with an HTML page (status 200), so crawlers read no rules there")
    elif robots["status"] == 200:
        rules.parse(robots_text.splitlines())
        named_sitemaps = list(rules.site_maps() or [])
        report.ok("/robots.txt answers with status 200 and was read")
    elif robots["status"] in (404, 410):
        report.warn(f"no /robots.txt (status {robots['status']}); crawlers assume everything is open")
    elif robots["status"] and robots["status"] >= 500:
        report.fail(f"/robots.txt answers with status {robots['status']}; a crawler may treat the whole site as closed")
    else:
        report.warn(f"/robots.txt answers with status {robots['status']}")

    closed_to = [name for name in ("Googlebot", "Bingbot") if not rules.can_fetch(name, start)]
    if closed_to:
        report.fail(f"robots.txt closes the start page to {' and '.join(closed_to)}")
    elif robots["status"] == 200:
        report.ok("robots.txt leaves the start page open to Googlebot and Bingbot")
    wait = rules.crawl_delay(pf.AGENT_NAME)
    if wait and float(wait) > args.delay:
        args.delay = min(float(wait), 10.0)
        report.note(f"robots.txt asks for {wait} seconds between requests; using {args.delay}")

    standing = ["whether any page is in a search index: only the search engine's own console shows that",
                "content a browser adds by script: the HTML was read as sent",
                "page speed (use page-speed), structured data (use structured-data-check), links to other sites (use link-check)"]
    if not rules.can_fetch(pf.AGENT_NAME, start):
        report.skip("the crawl: robots.txt closes the start page to this checker, so no page was fetched", blocks=True)
        for text in standing:
            report.skip(text)
        return report.finish(args.out)

    # 2. crawl
    pages, order = {}, []
    queue, seen = collections.deque([start]), {start}
    inbound = collections.defaultdict(set)
    closed, out_of_time = set(), False
    while queue and len(order) < max_pages:
        if time.monotonic() - began > args.max_seconds:
            out_of_time = True
            break
        url = queue.popleft()
        if not rules.can_fetch(pf.AGENT_NAME, url):
            closed.add(url)
            continue
        got = get(url)
        record = {"status": got["status"], "error": got["error"], "offsite": got["offsite"], "hops": len(got["chain"]) - 1,
                  "final": normal(got["final"]), "page": None, "issues": {}, "script": False, "internal": set(), "noindex": False}
        pages[url] = record
        order.append(url)
        if got["error"] or got["offsite"] or got["status"] != 200:
            continue
        if record["final"] != url:
            if record["final"] in pages:
                continue
            seen.add(record["final"])
        if "html" not in got["headers"].get("content-type", "text/html").lower():
            continue
        page = pf.parse(pf.decode(got["body"], got["headers"]))
        record["page"] = page
        record["issues"], record["script"] = check_page(page, record["final"], limits)
        robots_meta = " ".join(page.meta_all("robots") + page.meta_all("googlebot")).lower()
        record["noindex"] = "noindex" in robots_meta or "noindex" in got["headers"].get("x-robots-tag", "").lower()
        base = urllib.parse.urljoin(record["final"], page.base) if page.base else record["final"]
        for anchor in page.anchors:
            href = (anchor["href"] or "").strip()
            if not href or href.startswith("#"):
                continue
            target = urllib.parse.urljoin(base, href)
            if urllib.parse.urlsplit(target).scheme not in ("http", "https") or not pf.same_site(target, start):
                continue
            target = normal(target)
            if target in (url, record["final"]):
                continue
            record["internal"].add(target)
            inbound[target].add(url)
            if target not in seen and not urllib.parse.urlsplit(target).path.lower().endswith(NOT_PAGES):
                seen.add(target)
                queue.append(target)
        if not record["internal"] and not record["script"]:
            record["issues"]["no_internal_links"] = ""

    html_pages = [u for u in order if pages[u]["page"] is not None]
    judged = [u for u in html_pages if not pages[u]["script"]]
    if not html_pages:
        first = pages.get(start, {})
        why = first.get("error") or (f"redirects to another site: {first.get('offsite')}" if first.get("offsite")
                                     else f"status {first.get('status')}")
        report.skip(f"every page check: the start page gave no HTML ({why})", blocks=True)

    # 3. per-page findings, merged by cause
    script_only = {"h1_missing", "h1_many", "heading_order", "alt_missing", "no_internal_links"}
    for key, blocks, bad, good in CHECKS:
        pool = judged if key in script_only else html_pages
        hit = [u for u in pool if key in pages[u]["issues"]]
        if hit:
            detail = pages[hit[0]]["issues"][key]
            text = f"{bad}: {len(hit)} of {len(pool)} pages: {some(hit)}" + (f" (first: {detail})" if detail else "")
            (report.fail if blocks else report.warn)(text)
        elif good and pool:
            report.ok(f"{good}: {len(pool)} pages")
    for label, pick in (("title", lambda p: p.title), ("meta description", lambda p: p.meta_one("description"))):
        groups = collections.defaultdict(list)
        for u in html_pages:
            value = pick(pages[u]["page"])
            if value:
                groups[value.casefold()].append(u)
        repeats = [g for g in groups.values() if len(g) > 1]
        if repeats:
            report.warn(f"same {label} on several pages: {len(repeats)} groups, for example {some(repeats[0])}")
        elif groups:
            report.ok(f"every {label} is used on one page only: {len(groups)} pages")
    scripted = [u for u in html_pages if pages[u]["script"]]
    if scripted:
        report.skip(f"headings, images and links on {len(scripted)} pages that hold almost no text in their HTML and are "
                    f"probably built by script: {some(scripted)}", blocks=True)
    if judged:
        counts = sorted(len(pages[u]["internal"]) for u in judged)
        report.note(f"internal links per page: least {counts[0]}, median {statistics.median(counts):g}, most {counts[-1]}")

    # 4. status of what was crawled
    broken = [u for u in order if pages[u]["status"] and pages[u]["status"] >= 400]
    for u in broken[:10]:
        source = some(inbound[u], 2) if inbound[u] else "the start URL"
        report.fail(f"internal link answers with status {pages[u]['status']}: {short(u)} (linked from {source})")
    if len(broken) > 10:
        report.fail(f"{len(broken) - 10} more internal links answer with an error status")
    errors = [u for u in order if pages[u]["error"]]
    if errors:
        report.skip(f"{len(errors)} URLs gave no answer ({pages[errors[0]]['error']}): {some(errors)}", blocks=True)
    if order and not broken and not errors:
        report.ok(f"all {len(order)} crawled URLs answered without an error status")
    chains = [u for u in order if pages[u]["hops"] >= 2]
    if chains:
        report.warn(f"redirect chains of two or more hops: {some(chains)}")
    hops = [u for u in order if pages[u]["hops"] == 1 and inbound[u]]
    if hops:
        report.warn(f"internal links that point at a redirect, {len(hops)} targets: {some(hops)}")
    away = [u for u in order if pages[u]["offsite"]]
    if away:
        report.warn(f"internal URLs that redirect to another site (not followed): {some(away)}")
    if closed:
        report.skip(f"{len(closed)} URLs that robots.txt closes to this checker: {some(closed)}")
    left = len(queue)
    if left:
        why = f"the {args.max_seconds} second limit" if out_of_time else f"the page limit of {max_pages}"
        report.skip(f"{left} known URLs were not crawled because of {why}; raise the limit to cover them", blocks=True)

    # 5. sitemaps
    todo = named_sitemaps[:3] or [root + "/sitemap.xml"]
    listed, found_any, tried = [], False, 0
    while todo and tried < 8:
        address = todo.pop(0)
        tried += 1
        if not pf.same_site(address, start):
            report.skip(f"sitemap on another host, not fetched: {address}")
            continue
        got = get(address)
        if got["status"] != 200:
            if named_sitemaps:
                report.fail(f"sitemap named in robots.txt does not answer: {short(address)} "
                            f"({got['error'] or 'status ' + str(got['status'])})")
            continue
        kind, locs = read_sitemap(got["body"])
        if kind is None:
            report.fail(f"sitemap is not readable XML with <urlset> or <sitemapindex>: {short(address)}")
            continue
        found_any = True
        if kind == "index":
            todo.extend(locs[:5])
            if len(locs) > 5:
                report.skip(f"{len(locs) - 5} child sitemaps of {short(address)}", blocks=True)
        else:
            listed.extend(locs)
    if not found_any and not named_sitemaps:
        report.warn("no sitemap: none named in robots.txt and /sitemap.xml does not answer")
    if found_any:
        listed = list(dict.fromkeys(listed))
        foreign = [u for u in listed if not pf.same_site(u, start)]
        if foreign:
            report.fail(f"sitemap lists {len(foreign)} URLs on another host, for example {foreign[0]}")
        own = [normal(u) for u in listed if pf.same_site(u, start)]
        bad, moved, fine_count, silent = [], [], 0, []
        for u in own[:args.max_sitemap_urls]:
            if u in pages:
                status, hop = pages[u]["status"], pages[u]["hops"]
            elif not rules.can_fetch(pf.AGENT_NAME, u):
                closed.add(u)
                silent.append(u)
                continue
            else:
                got = get(u, "HEAD")
                if got["status"] in (405, 501):
                    got = get(u)
                status, hop = got["status"], len(got["chain"]) - 1
            if status is None:
                silent.append(u)
            elif status >= 400:
                bad.append((u, status))
            elif hop or status != 200:
                moved.append(u)
            else:
                fine_count += 1
        for u, status in bad[:10]:
            report.fail(f"sitemap lists a URL that answers with status {status}: {short(u)}")
        if len(bad) > 10:
            report.fail(f"{len(bad) - 10} more sitemap URLs answer with an error status")
        if moved:
            report.warn(f"sitemap lists URLs that redirect, {len(moved)}: {some(moved)}")
        if silent:
            report.skip(f"{len(silent)} sitemap URLs gave no answer or are closed by robots.txt: {some(silent)}", blocks=True)
        if fine_count:
            report.ok(f"sitemap found; {fine_count} of {len(own)} listed URLs were asked and answer with status 200")
        elif not own:
            report.fail("sitemap found but it lists no URL on this site")
        if len(own) > args.max_sitemap_urls:
            report.skip(f"{len(own) - args.max_sitemap_urls} sitemap URLs beyond the limit of {args.max_sitemap_urls}", blocks=True)
        in_map = set(own)
        hidden = [u for u in html_pages if pages[u]["noindex"] and (u in in_map or pages[u]["final"] in in_map)]
        if hidden:
            report.fail(f"listed in the sitemap but marked noindex: {some(hidden)}")
        if not left and not out_of_time:
            lonely = [u for u in own[:args.max_sitemap_urls] if u not in pages and not inbound[u]]
            if lonely:
                report.warn(f"in the sitemap but no crawled page links to them, {len(lonely)}: {some(lonely)}")
            absent = [u for u in html_pages if u not in in_map and pages[u]["final"] not in in_map and not pages[u]["noindex"]]
            if absent:
                report.warn(f"crawled pages missing from the sitemap, {len(absent)}: {some(absent)}")

    # 6. noindex
    noindex = [u for u in html_pages if pages[u]["noindex"]]
    if start in noindex:
        report.fail("the start page is marked noindex")
    others = [u for u in noindex if u != start]
    if others:
        report.warn(f"pages marked noindex, {len(others)}; confirm each is meant to stay out of search: {some(others)}")
    if html_pages and not noindex:
        report.ok(f"no page is marked noindex: {len(html_pages)} pages")

    for text in standing:
        report.skip(text)
    report.note(f"{requests[0]} requests sent to {parts.netloc}; {len(html_pages)} HTML pages read")
    return report.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
