#!/usr/bin/env python3
"""Before fetching many pages: read each site's robots.txt, sort the addresses into allowed, disallowed
and unknown, and write a plan with a count, a rate and an estimated duration.

  fetch_plan.py URL [URL ...]               plan for the addresses given
  fetch_plan.py --urls list.txt             one address per line; blank lines and # comments are skipped
  fetch_plan.py --urls list.txt --delay 5   seconds between two requests to one host (default 2; never below
                                            the site's Crawl-delay, never below 1 for a public host)
  fetch_plan.py ... --terms-reviewed "Dana read example.org/terms on 2026-11-22: automated reading allowed"
                                            the user's own statement, copied into the plan; without it the plan is a draft
  fetch_plan.py ... --drop-disallowed       plan only the allowed addresses and list the ones left out
  fetch_plan.py ... --robots-file robots.txt  judge the addresses against a saved robots.txt (no network)

It requests robots.txt once per site and, unless --no-terms-lookup is given, the site's front page once
to find a link to its terms. It fetches none of the listed addresses.

The plan is refused when an address is disallowed. Nothing in this script can be told to ignore robots.txt.

Exit codes: 0 = plan written and ready: every planned address is allowed and the terms were reviewed
            1 = fail: at least one address is disallowed by robots.txt (no plan written)
            2 = not verified or blocked: robots.txt unreadable, terms not reviewed (draft written), bad input
"""
import argparse
import datetime
import html.parser
import json
import pathlib
import re
import sys
import urllib.parse

import webfetch

TOOL = "fetch-plan"
TERMS = re.compile(r"terms|conditions|\btos\b|legal|acceptable[- ]use|usage[- ]policy|copyright|licen[cs]e", re.I)
RULES = [
    "identify as the user agent recorded in this plan, on every request",
    "one request at a time per host, with the pause recorded for that host",
    "stop sending to a host that answers 429, or 503 with Retry-After; do not retry around it",
    "no sign-in, no saved cookies, no pages behind a login",
    "a 401 or 403 is an answer, not an obstacle",
    "do not collect personal data about people",
]


class TermLinks(html.parser.HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.href, self.text, self.found = base, None, [], []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href, self.text = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self.href:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            label = " ".join("".join(self.text).split())
            target = urllib.parse.urljoin(self.base, self.href)
            if (TERMS.search(label) or TERMS.search(urllib.parse.urlsplit(target).path)) and target.startswith("http") and target not in self.found:
                self.found.append(target)
            self.href = None


def duration(seconds):
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{hours} h" if hours else "", f"{minutes} min" if minutes else "", f"{secs} s" if secs or not (hours or minutes) else ""]
    return " ".join(part for part in parts if part)


def read_addresses(args):
    raw = list(args.url)
    if args.urls:
        raw += [line.strip() for line in args.urls.read_text(encoding="utf-8").splitlines() if line.strip() and not line.strip().startswith("#")]
    good, bad = [], []
    for item in raw:
        try:
            address = webfetch.check_url(item)
            if address not in good:
                good.append(address)
        except webfetch.BadURL as exc:
            bad.append(str(exc))
    return good, bad


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", nargs="*", help="addresses the user wants to fetch")
    parser.add_argument("--urls", type=pathlib.Path, help="file with one address per line")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between two requests to one host (default 2)")
    parser.add_argument("--max-pages", type=int, default=200, help="refuse a longer list unless this is raised on purpose (default 200)")
    parser.add_argument("--terms-reviewed", metavar="TEXT", help="who read the terms of use, when, and what they allow")
    parser.add_argument("--drop-disallowed", action="store_true", help="leave disallowed addresses out of the plan")
    parser.add_argument("--no-terms-lookup", action="store_true", help="do not request the front page to look for a terms link")
    parser.add_argument("--robots-file", type=pathlib.Path, help="saved robots.txt to judge against; no request is made")
    parser.add_argument("--out", type=pathlib.Path, help="new file for the plan (default: .mstack/fetch-plan/plan-<time>.json)")
    parser.add_argument("--timeout", type=float, default=15.0, help="seconds to wait per request (default 15)")
    args = parser.parse_args()

    try:
        addresses, bad = read_addresses(args)
        saved = webfetch.Robots(args.robots_file.read_text(encoding="utf-8", errors="replace")) if args.robots_file else None
    except OSError as exc:
        print(f"blocked: a file could not be read ({exc})")
        return 2
    if bad:
        print("not fetched by this pack:\n  " + "\n  ".join(bad))
        print(f"blocked: {len(bad)} address(es) in the list cannot be planned; remove or correct them")
        return 2
    if not addresses:
        print("blocked: no addresses given; pass them as arguments or with --urls")
        return 2
    if len(addresses) > args.max_pages:
        print(f"blocked: {len(addresses)} addresses is above the limit of {args.max_pages}; shorten the list, or raise --max-pages on purpose")
        return 2
    if args.out and args.out.exists():
        print(f"blocked: {args.out} already exists; name a new file")
        return 2
    if args.terms_reviewed is not None and len(args.terms_reviewed.split()) < 4:
        print("blocked: --terms-reviewed needs a real statement: who read the terms, when, and what they allow")
        return 2

    print(f"fetch-plan for {len(addresses)} address(es)\nuser agent: {webfetch.user_agent(TOOL)} (robots token '{webfetch.ROBOTS_TOKEN}')")
    throttle = webfetch.Throttle(args.delay)
    hosts, order = {}, []
    for address in addresses:
        origin = webfetch.origin_of(address)
        if origin not in hosts:
            order.append(origin)
            if saved is not None:
                state = webfetch.RobotsState("ok", f"judged against the saved file {args.robots_file}", saved)
            else:
                state = webfetch.load_robots(origin, TOOL, args.timeout, throttle)
            throttle.raise_delay(address, state.rules.delay)
            hosts[origin] = {"origin": origin, "state": state, "allowed": [], "disallowed": [], "unknown": [], "terms": []}
        hosts[origin][hosts[origin]["state"].verdict(address)].append(address)

    for origin in order:
        host, state = hosts[origin], hosts[origin]["state"]
        group = f"rules for '{state.rules.group_used}'" if state.rules.group_used else "no rules that apply"
        print(f"\n{origin}\n  robots.txt: {state.state} ({state.detail}); {group}")
        print(f"  crawl delay asked: {f'{state.rules.delay:g} s' if state.rules.delay else 'none'}; sitemap: {', '.join(state.rules.sitemaps) or 'none named in robots.txt'}")
        for verdict in ("allowed", "disallowed", "unknown"):
            for address in host[verdict]:
                print(f"  {verdict:10} {address}")
        if saved is None and not args.no_terms_lookup and state.verdict(origin + "/") == "allowed" and not throttle.stop_reason(origin):
            hops, problem = webfetch.follow(origin + "/", TOOL, throttle=throttle, timeout=args.timeout, max_bytes=1_000_000)
            front = hops[-1]
            if not problem and not front.error and front.status == 200 and "html" in front.content_type:
                finder = TermLinks(front.url)
                finder.feed(front.text())
                host["terms"] = finder.found[:5]
        print(f"  terms of use: {', '.join(host['terms']) or 'no link found by this script; look for the terms by hand'}")

    unknown = [address for origin in order for address in hosts[origin]["unknown"]]
    disallowed = [address for origin in order for address in hosts[origin]["disallowed"]]
    planned = [address for origin in order for address in hosts[origin]["allowed"]]
    if unknown:
        why = "; ".join(f"{origin}: {hosts[origin]['state'].detail}" for origin in order if hosts[origin]["unknown"])
        print(f"\nno plan written\nRESULT not verified: robots.txt could not be read for {len(unknown)} address(es) ({why}); nothing is assumed allowed")
        return 2
    if disallowed and not args.drop_disallowed:
        print(f"\nno plan written\nRESULT fail: {len(disallowed)} of {len(addresses)} address(es) are disallowed by robots.txt; "
              "remove them, or pass --drop-disallowed to plan the rest")
        return 1
    if not planned:
        print("\nno plan written\nRESULT fail: every address is disallowed by robots.txt; there is nothing to plan")
        return 1

    plan_hosts, total = [], 0.0
    for origin in order:
        host = hosts[origin]
        if not host["allowed"]:
            continue
        pause = throttle.delay_for(host["allowed"][0])
        seconds = pause * max(0, len(host["allowed"]) - 1)
        total += seconds
        plan_hosts.append({"origin": origin, "robots": host["state"].state, "robots_detail": host["state"].detail,
                           "crawl_delay_asked": host["state"].rules.delay, "sitemaps": host["state"].rules.sitemaps,
                           "pause_seconds": pause, "addresses": host["allowed"], "left_out_disallowed": host["disallowed"],
                           "estimated_seconds": seconds, "terms_links": host["terms"]})
    ready = args.terms_reviewed is not None
    plan = {"created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "status": "ready" if ready else "draft: terms of use not reviewed",
            "user_agent": webfetch.user_agent("<the fetching script>"), "robots_token": webfetch.ROBOTS_TOKEN,
            "terms_reviewed": args.terms_reviewed, "addresses": len(planned), "left_out_disallowed": len(disallowed),
            "estimated_seconds": total, "rules": RULES, "hosts": plan_hosts}
    out = args.out or webfetch.state_dir("fetch-plan") / f"plan-{datetime.datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    print(f"\nplan: {len(planned)} address(es) on {len(plan_hosts)} host(s), one host after another, about {duration(total)}")
    for entry in plan_hosts:
        print(f"  {entry['origin']}: {len(entry['addresses'])} address(es), one request every {entry['pause_seconds']:g} s, about {duration(entry['estimated_seconds'])}")
    if disallowed:
        print(f"  left out because robots.txt disallows them: {len(disallowed)}")
    print("  the estimate counts the pauses only; download time comes on top")
    print(f"written: {out} ({plan['status']})")
    if not ready:
        print("blocked: the terms of use were not reviewed. A person reads them, then run again with --terms-reviewed \"<who, when, what they allow>\"")
        return 2
    print(f"RESULT pass: {len(planned)} address(es) allowed by robots.txt, terms reviewed, about {duration(total)} at the planned rate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
