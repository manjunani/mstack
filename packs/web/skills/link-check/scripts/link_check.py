#!/usr/bin/env python3
"""Crawl one site within stated limits and sort every link and asset into three lists:
broken, fine, could not check.

  link_check.py URL                      crawl from URL: pages to depth 2, at most 50 pages
  link_check.py URL --depth 1 --max-pages 20
  link_check.py URL --no-external        check the site's own links and assets only
  link_check.py URL --delay 2            seconds between two requests to one host (default 1)
  link_check.py URL --out report.json    where to write the full lists (default: .mstack/link-check/)

How it behaves on the network:
  - reads robots.txt first and never requests a path it disallows; a Crawl-delay raises the pause
  - pages of the site are fetched with GET and read for links; other targets on the site get one HEAD
  - each external link gets one HEAD after that host's robots.txt was read; redirects are not followed
  - a host that answers 429, or 503 with Retry-After, gets no further requests
  - asks for one made-up address, to learn whether the site answers 200 for missing pages

Only a target that answered 2xx is called fine. Everything that could not be decided is listed with its reason.

Exit codes: 0 = nothing broken and nothing left unchecked
            1 = at least one broken link or missing asset
            2 = not verified or blocked: something could not be checked, or the crawl could not start
"""
import argparse
import collections
import datetime
import html.parser
import json
import pathlib
import secrets
import sys
import time
import urllib.parse

import webfetch

TOOL = "link-check"
NOT_PAGES = (".pdf", ".zip", ".gz", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".mp4", ".mp3", ".webm",
             ".css", ".js", ".json", ".xml", ".txt", ".woff", ".woff2", ".csv", ".dmg", ".exe")
ASSET_RELS = {"stylesheet", "icon", "preload", "modulepreload", "manifest", "apple-touch-icon"}
LINK_RELS = {"canonical", "alternate", "next", "prev"}


class Links(html.parser.HTMLParser):
    """Collect (kind, address) pairs from one page: kind is 'link' or 'asset'."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.base, self.scripts, self.anchors, self.skipped = [], None, 0, 0, 0

    def handle_starttag(self, tag, attrs):
        attrs = {key: (value or "").strip() for key, value in attrs}
        if tag == "base" and attrs.get("href") and self.base is None:
            self.base = attrs["href"]
        elif tag in ("a", "area"):
            self.anchors += 1
            self.add("link", attrs.get("href"))
        elif tag == "link":
            rels = set(attrs.get("rel", "").lower().split())
            if rels & ASSET_RELS:
                self.add("asset", attrs.get("href"))
            elif rels & LINK_RELS:
                self.add("link", attrs.get("href"))
        elif tag == "script":
            self.scripts += 1
            self.add("asset", attrs.get("src"))
        elif tag in ("img", "source", "video", "audio", "iframe", "embed", "track", "input"):
            self.add("asset", attrs.get("src"))
            self.add("asset", attrs.get("poster"))
            for candidate in attrs.get("srcset", "").split(","):
                self.add("asset", candidate.strip().split(" ")[0])
        elif tag == "object":
            self.add("asset", attrs.get("data"))

    def add(self, kind, value):
        if not value or value.startswith("#"):
            return
        if ":" in value.split("/")[0] and not value.lower().startswith(("http:", "https:")):
            self.skipped += 1  # mailto:, tel:, javascript:, data: and the like
            return
        self.found.append((kind, value))


class Crawl:
    def __init__(self, args, start):
        self.args, self.start = args, start
        self.throttle = webfetch.Throttle(args.delay)
        self.robots, self.targets, self.requests = {}, {}, 0
        self.began = time.monotonic()
        self.site = webfetch.origin_of(start)
        self.parsed, self.thin_pages, self.skipped_schemes, self.externals = [], [], 0, 0

    def budget(self):
        if self.requests >= self.args.max_requests:
            return f"the request limit of {self.args.max_requests} was reached"
        if time.monotonic() - self.began > self.args.max_minutes * 60:
            return f"the time limit of {self.args.max_minutes} minutes was reached"
        return None

    def request(self, url, method, read=True):
        self.requests += 1
        self.throttle.wait(url)
        response = webfetch.fetch(url, TOOL, method=method, timeout=self.args.timeout, max_bytes=2_000_000, read=read)
        self.throttle.observe(response)
        return response

    def robots_for(self, url):
        origin = webfetch.origin_of(url)
        if origin not in self.robots:
            self.requests += 1
            state = webfetch.load_robots(origin, TOOL, self.args.timeout, self.throttle)
            self.throttle.raise_delay(url, state.rules.delay)
            self.robots[origin] = state
        return self.robots[origin]

    def note(self, url, kind, source):
        entry = self.targets.setdefault(url, {"kind": kind, "internal": webfetch.origin_of(url) == self.site,
                                               "from": [], "state": None, "detail": "", "status": None})
        if kind == "link" and entry["kind"] == "asset" and entry["state"] is None:
            entry["kind"] = "link"
        if source and source not in entry["from"]:
            entry["from"].append(source)
        return entry

    def settle(self, url, state, detail, status=None):
        self.targets[url].update(state=state, detail=detail, status=status)

    def internal(self, url, method):
        """One site-internal target, redirects followed inside the site. Returns the last response or None when settled."""
        first, seen = url, set()
        for _ in range(6):
            reason = self.budget() or self.throttle.stop_reason(url)
            if reason:
                return self.settle(first, "unchecked", reason)
            verdict = self.robots_for(url).verdict(url)
            if verdict != "allowed":
                return self.settle(first, "unchecked", "disallowed by robots.txt" if verdict == "disallowed" else "robots.txt could not be read")
            response = self.request(url, method)
            if response.status in (405, 501) and method == "HEAD":
                response = self.request(url, "GET", read=False)
            if response.error:
                return self.settle(first, "unchecked", f"no answer ({response.error_kind}: {response.error})")
            target = response.location
            if not target:
                break
            seen.add(url)
            if target in seen:
                return self.settle(first, "broken", f"redirect loop through {target}", response.status)
            if webfetch.origin_of(target) != self.site:
                for source in self.targets[first]["from"] or [first]:
                    self.note(target, "link", source)
                return self.settle(first, "fine", f"redirects off the site to {target}, which is checked as an external link", response.status)
            url = target
        else:
            return self.settle(first, "broken", "more than 5 redirects")
        status = response.status
        if 200 <= status < 300:
            self.settle(first, "fine", "" if url == first else f"after redirect to {url}", status)
            return response
        if status in (401, 403):
            return self.settle(first, "unchecked", f"answered {status}: needs a login or refuses this client", status)
        if self.throttle.stop_reason(url):
            return self.settle(first, "unchecked", self.throttle.stop_reason(url), status)
        return self.settle(first, "broken", f"answered {status}", status)

    def external(self, url):
        self.externals += 1
        if self.externals > self.args.max_external:
            return self.settle(url, "unchecked", f"the limit of {self.args.max_external} external links was reached")
        reason = self.budget() or self.throttle.stop_reason(url)
        if reason:
            return self.settle(url, "unchecked", reason)
        try:
            webfetch.check_url(url)
        except webfetch.BadURL as exc:
            return self.settle(url, "unchecked", str(exc))
        if webfetch.is_local(urllib.parse.urlsplit(url).hostname) and not webfetch.is_local(urllib.parse.urlsplit(self.site).hostname):
            return self.settle(url, "unchecked", "points at a local or private address; a public site's links are not followed there")
        robots = self.robots_for(url)
        verdict = robots.verdict(url)
        if verdict == "disallowed":
            return self.settle(url, "unchecked", "disallowed by that site's robots.txt")
        if verdict == "unknown":
            return self.settle(url, "unchecked", f"that site's robots.txt could not be read ({robots.detail})")
        if self.throttle.stop_reason(url):
            return self.settle(url, "unchecked", self.throttle.stop_reason(url))
        response = self.request(url, "HEAD")
        if response.error:
            return self.settle(url, "unchecked", f"no answer ({response.error_kind}: {response.error})")
        status = response.status
        if 200 <= status < 300:
            return self.settle(url, "fine", "", status)
        if status in (404, 410):
            return self.settle(url, "broken", f"answered {status}", status)
        if response.location:
            return self.settle(url, "unchecked", f"redirects to {response.location}; not followed (one request per external link)", status)
        return self.settle(url, "unchecked", self.throttle.stop_reason(url) or f"answered {status} to a HEAD request", status)

    def read_page(self, url, response, depth, queue):
        parser = Links()
        parser.feed(response.text())
        base = urllib.parse.urljoin(url, parser.base) if parser.base else url
        self.parsed.append(url)
        self.skipped_schemes += parser.skipped
        if parser.scripts >= 3 and parser.anchors <= 2:
            self.thin_pages.append(url)
        for kind, value in parser.found:
            target = urllib.parse.urldefrag(urllib.parse.urljoin(base, value))[0]
            if not target.lower().startswith(("http:", "https:")):
                continue
            known = target in self.targets
            entry = self.note(target, kind, url)
            page_like = kind == "link" and not urllib.parse.urlsplit(target).path.lower().endswith(NOT_PAGES)
            if not known and entry["internal"] and page_like and depth < self.args.depth:
                queue.append((target, depth + 1))

    def run(self, first):
        """Breadth first from the start page, whose answer `first` is already in hand."""
        queue = collections.deque()
        self.read_page(first.url, first, 0, queue)
        while queue:
            url, depth = queue.popleft()
            if self.targets[url]["state"] is not None or len(self.parsed) >= self.args.max_pages:
                continue  # past the page limit a target still gets one request below, but is not read for links
            response = self.internal(url, "GET")
            if response is not None and "html" in response.content_type:
                self.read_page(response.url, response, depth, queue)
        for url, entry in list(self.targets.items()):
            if entry["state"] is None and entry["internal"]:
                self.internal(url, "HEAD")
        for url, entry in list(self.targets.items()):
            if entry["state"] is None and self.args.no_external:
                self.settle(url, "unchecked", "external links were not requested (--no-external)")
            elif entry["state"] is None:
                self.external(url)


def soft_404(crawl):
    """Ask for an address that cannot exist. Returns a sentence when the site answers 200 for it."""
    probe = f"{crawl.site}/mstack-link-check-{secrets.token_hex(6)}.html"
    if crawl.robots_for(probe).verdict(probe) != "allowed" or crawl.budget():
        return None, "the made-up address was not requested (robots.txt or the request limit)"
    crawl.note(probe, "link", None)
    response = crawl.internal(probe, "GET")
    entry = crawl.targets.pop(probe)
    for url in [url for url, other in crawl.targets.items() if other["from"] == [probe]]:
        del crawl.targets[url]
    if response is not None:
        return f"the site answers {response.status} for a made-up address ({probe}), so a missing page can look fine", None
    return None, None if entry["state"] == "broken" else f"the made-up address gave no clear answer ({entry['detail']})"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="the page to start from; the crawl stays on this site")
    parser.add_argument("--depth", type=int, default=2, help="how many links away from the start page are read for more links (default 2)")
    parser.add_argument("--max-pages", type=int, default=50, help="pages read for links (default 50)")
    parser.add_argument("--max-requests", type=int, default=400, help="requests in total, all hosts (default 400)")
    parser.add_argument("--max-external", type=int, default=50, help="external links checked (default 50)")
    parser.add_argument("--max-minutes", type=float, default=10.0, help="stop sending requests after this long (default 10)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests to one host; never below 1 for a public host (default 1)")
    parser.add_argument("--no-external", action="store_true", help="do not request links that leave the site")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds to wait per request (default 10)")
    parser.add_argument("--out", type=pathlib.Path, help="new file for the full lists (default: .mstack/link-check/report-<time>.json)")
    args = parser.parse_args()

    try:
        start = webfetch.check_url(args.url)
    except webfetch.BadURL as exc:
        print(f"blocked: {exc}")
        return 2
    if args.out and args.out.exists():
        print(f"blocked: {args.out} already exists; name a new file")
        return 2
    print(f"link-check {start}\nuser agent: {webfetch.user_agent(TOOL)}")
    crawl = Crawl(args, start)
    for attempt in (1, 2):  # the second pass is for a start address that redirects to another host
        robots = crawl.robots_for(start)
        print(f"robots.txt of {crawl.site}: {robots.state} ({robots.detail})" + (f"; crawl delay {robots.rules.delay:g} s" if robots.rules.delay else ""))
        verdict = robots.verdict(start)
        if verdict != "allowed":
            why = "robots.txt could not be read, so nothing is assumed" if verdict == "unknown" else f"robots.txt does not allow fetching {start}"
            print(f"blocked: {why}; nothing was crawled. The site owner can allow the token '{webfetch.ROBOTS_TOKEN}'.")
            return 2
        if attempt == 1:
            hops, problem = webfetch.follow(start, TOOL, throttle=crawl.throttle, timeout=args.timeout, max_bytes=2_000_000)
            crawl.requests += len(hops)
            first = hops[-1]
            if problem or first.error or first.status != 200:
                why = problem or (f"{first.error_kind}: {first.error}" if first.error else f"it answered {first.status}")
                print(f"RESULT not verified: the start page could not be read ({why}); nothing was crawled")
                return 2
            if webfetch.origin_of(first.url) == crawl.site:
                break
            print(f"the start address redirects to {first.url}; the crawl stays on that site")
            start, crawl.site = first.url, webfetch.origin_of(first.url)
    crawl.note(first.url, "link", None)
    crawl.settle(first.url, "fine", "start page", first.status)
    soft, probe_note = soft_404(crawl)
    crawl.run(first)

    lists = {state: sorted((url, entry) for url, entry in crawl.targets.items() if entry["state"] == state)
             for state in ("broken", "fine", "unchecked")}
    pages_found = sum(1 for entry in crawl.targets.values() if entry["internal"] and entry["kind"] == "link")
    scope = (f"site {crawl.site}, depth {args.depth}: {len(crawl.parsed)} page(s) read for links of {pages_found} internal link target(s) found "
             f"(limit {args.max_pages}); {crawl.requests} request(s) of at most {args.max_requests}; "
             f"pause per host {crawl.throttle.delay_for(first.url):g} s; {crawl.skipped_schemes} mailto/tel/script link(s) skipped")
    print(f"scope: {scope}")
    print(f"\nbroken ({len(lists['broken'])}):")
    for url, entry in lists["broken"]:
        where = ", ".join(entry["from"][:3]) + (f" and {len(entry['from']) - 3} more" if len(entry["from"]) > 3 else "")
        print(f"  {entry['kind']:5} {url}\n        {entry['detail']}; linked from: {where or '(start)'}")
    print(f"\nfine ({len(lists['fine'])}): each answered 2xx; the list is in the report file")
    print(f"\ncould not check ({len(lists['unchecked'])}):")
    reasons = collections.Counter()
    for url, entry in lists["unchecked"][:40]:
        print(f"  {entry['kind']:5} {url}\n        {entry['detail']}")
    for url, entry in lists["unchecked"]:
        reasons[entry["detail"].split(" (")[0].split(";")[0][:70]] += 1
    if len(lists["unchecked"]) > 40:
        print(f"  ... and {len(lists['unchecked']) - 40} more, in the report file")
    notes = [note for note in (soft, probe_note) if note]
    if crawl.thin_pages:
        notes.append(f"{len(crawl.thin_pages)} page(s) hold several scripts and almost no links ({crawl.thin_pages[0]}); links built by JavaScript are not seen here")
    notes.append("not checked: #fragment targets inside pages, links inside style sheets and scripts, pages behind a login")
    for note in notes:
        print(f"note: {note}")

    out = args.out or webfetch.state_dir("link-check") / f"report-{datetime.datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "start": start, "checked": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "scope": scope,
        "notes": notes, "pages_read": crawl.parsed,
        **{name: [{"url": url, **entry} for url, entry in items] for name, items in lists.items()},
    }, indent=2) + "\n", encoding="utf-8")
    print(f"report: {out}")
    if lists["broken"]:
        assets = sum(1 for _, entry in lists["broken"] if entry["kind"] == "asset")
        print(f"RESULT fail: {len(lists['broken'])} broken ({len(lists['broken']) - assets} link(s), {assets} asset(s))")
        return 1
    if lists["unchecked"] or soft:
        why = [f"{len(lists['unchecked'])} target(s) could not be checked"] if lists["unchecked"] else []
        print("RESULT not verified: " + "; ".join(why + ([soft] if soft else [])))
        return 2
    print(f"RESULT pass: {len(lists['fine'])} target(s) answered 2xx, none broken, none unchecked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
