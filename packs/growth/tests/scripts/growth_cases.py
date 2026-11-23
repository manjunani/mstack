#!/usr/bin/env python3
"""Run every mstack-growth script on throwaway files and on local servers, and compare each exit code.

  python3 packs/growth/tests/scripts/growth_cases.py [--only <skill>] [--show]

It writes the pages from fixtures.py into a new folder under .testrun/ in the repository root, starts
http.server instances on 127.0.0.1 (random free ports) that serve those folders, runs each case and checks:
the exit code, words that have to appear in the output, words that must not, and that the last line is a
RESULT or blocked line. Nothing outside 127.0.0.1 is contacted. The folder is left in place for inspection.

Exit codes: 0 = every case behaved as expected, 1 = at least one did not, 2 = the test folder could not be made.
"""
import argparse
import functools
import http.server
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

import fixtures

PACK = pathlib.Path(__file__).resolve().parents[2]
REPO = PACK.parents[1]
SKILLS = PACK / "skills"


class Quiet(http.server.SimpleHTTPRequestHandler):
    soft = False

    def log_message(self, *args):
        pass

    def _record(self):
        self.server.seen.append((self.command, self.path, self.headers.get("User-Agent", "")))
        if self.soft and not pathlib.Path(self.translate_path(self.path)).exists():
            self.path = "/index.html"

    def do_GET(self):
        self._record()
        super().do_GET()

    def do_HEAD(self):
        self._record()
        super().do_HEAD()


class Soft(Quiet):
    soft = True


def serve(folder, handler=Quiet):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(handler, directory=str(folder)))
    server.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def closed_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="run the cases of one skill")
    parser.add_argument("--show", action="store_true", help="print the full output of every case")
    args = parser.parse_args()

    work = REPO / ".testrun" / f"growth-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    try:
        work.mkdir(parents=True)
    except OSError as exc:
        print(f"blocked: cannot make {work}: {exc}")
        return 2
    for name in ("site-good", "site-bad", "site-closed", "site-spa", "files"):
        (work / name).mkdir()
    good, GOOD = serve(work / "site-good")
    bad, BAD = serve(work / "site-bad")
    closed, CLOSED = serve(work / "site-closed")
    spa, SPA = serve(work / "site-spa")
    soft, SOFT = serve(work / "site-good", Soft)
    for path, text in fixtures.FILES.items():
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text.replace("{{GOOD}}", GOOD).replace("{{BAD}}", BAD), encoding="utf-8")
    for path, data in fixtures.BINARY.items():
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    DEAD = f"http://127.0.0.1:{closed_port()}"
    F = work / "files"

    def script(skill, name):
        return str(SKILLS / skill / "scripts" / name)

    audit = script("site-audit", "audit.py")
    jsonld = script("structured-data-check", "jsonld.py")
    launch = script("launch-site-check", "launch.py")
    post = script("post-check", "postcheck.py")
    claims = script("claim-check", "claims.py")
    first = script("first-screen", "firstscreen.py")
    track = script("tracking-check", "tracking.py")
    listing = script("store-listing-check", "listing.py")
    compare = script("page-compare", "compare.py")
    mail = script("mail-domain-check", "maildomain.py")
    facts = script("site-audit", "pagefacts.py")
    D = "mail.tidepool.test"

    # (skill, case name, command, expected exit, has to appear, must not appear, extra)
    cases = [
        ("site-audit", "clean site passes", [audit, GOOD + "/", "--delay", "0"], 0,
         ["RESULT pass", "7 of 7 listed URLs", "exactly one <h1>: 7 pages", "are unverified"], ["FAIL"]),
        ("site-audit", "page limit cuts the crawl", [audit, GOOD + "/", "--delay", "0", "--max-pages", "2"], 2,
         ["RESULT not verified", "page limit of 2"], []),
        ("site-audit", "planted faults are found", [audit, BAD + "/", "--delay", "0"], 1,
         ["no <h1>: 1 of 4 pages", "internal link answers with status 404: /gone/", "listed in the sitemap but marked noindex: /hidden/",
          "sitemap lists a URL that answers with status 404: /nowhere/", "URLs on another host", "title longer than the guidance",
          "no meta description", "more than one <h1>", "heading levels out of order", "images with no alt attribute",
          "no lang attribute", "same title on several pages", "no canonical link"], ["other-host.invalid/page answers"]),
        ("site-audit", "robots.txt closes the site", [audit, CLOSED + "/", "--delay", "0"], 1,
         ["closes the start page to Googlebot", "no page was fetched"], []),
        ("site-audit", "page built by script", [audit, SPA + "/", "--delay", "0"], 2,
         ["RESULT not verified", "built by script", "no /robots.txt", "no sitemap"], []),
        ("site-audit", "placeholder host refused", [audit, "https://www.example.com/"], 2, ["blocked:", "placeholder"], []),
        ("site-audit", "site not reachable", [audit, DEAD + "/"], 2, ["blocked:", "could not be reached"], []),
        ("site-audit", "report file is not overwritten", [audit, GOOD + "/", "--out", str(F / "copy.md")], 2, ["blocked:", "exists"], []),
        ("site-audit", "pagefacts prints facts", [facts, GOOD + "/pricing/"], 0, ['"title": "Tidepool pricing for harbours and marinas"'], [], "raw"),
        ("site-audit", "pagefacts refuses a missing file", [facts, str(F / "nope.html")], 2, ["blocked:"], []),

        ("structured-data-check", "valid blocks pass", [jsonld, str(F / "jsonld-good.html")], 0,
         ["Product: parses", "BreadcrumbList: parses", "FAQPage: parses", "testing tool is the authority", "are unverified"], ["FAIL"]),
        ("structured-data-check", "valid block from a URL", [jsonld, GOOD + "/"], 0, ["Organization: parses"], ["FAIL"]),
        ("structured-data-check", "planted faults are found", [jsonld, str(F / "jsonld-bad.html")], 1,
         ["block 1: does not parse as JSON", "required property 'name' is missing", "needs at least one of offers, review, aggregateRating",
          "block 3: no @context", "has no 'acceptedAnswer'", "aggregateRating values 4.9, 1200 are not in the page's visible text",
          "FAQ question not found in the visible text"], []),
        ("structured-data-check", "no markup is a pass with a reason", [jsonld, str(F / "jsonld-none.html")], 0,
         ["RESULT pass: no JSON-LD in the HTML, nothing to validate"], []),
        ("structured-data-check", "unknown type is not checked", [jsonld, str(F / "jsonld-unknown.html")], 0,
         ["Recipe: no property list", "RESULT pass"], []),
        ("structured-data-check", "microdata cannot be read", [jsonld, str(F / "jsonld-microdata.html")], 2, ["RESULT not verified", "microdata"], []),
        ("structured-data-check", "script-built page", [jsonld, str(work / "site-spa" / "index.html")], 2, ["RESULT not verified", "built by script"], []),
        ("structured-data-check", "missing file", [jsonld, str(F / "nope.html")], 2, ["RESULT not verified", "not read"], []),

        ("launch-site-check", "ready site passes", [launch, GOOD, "--delay", "0"], 0,
         ["RESULT pass", "not-found: a made-up address answers 404", "pricing: /pricing/ answers 200", "privacy: /privacy/",
          "terms: /terms/", "contact: /contact/", "favicon: /favicon.ico answers", "og:image answers", "action: 'Start a harbour table'"], ["FAIL"]),
        ("launch-site-check", "unready site fails", [launch, BAD, "--delay", "0"], 1,
         ["lorem ipsum", "pricing:", "privacy:", "terms:", "contact:", "favicon: /favicon.ico gives status 404",
          "tags missing on the home page: og:title, og:description, og:image", "action: 'Sign up' leads nowhere"], []),
        ("launch-site-check", "soft 404 is caught", [launch, SOFT, "--delay", "0"], 1,
         ["not-found: a made-up address", "gives status 200", "pricing: /pricing/ answers 200"], ["pricing: no link"]),
        ("launch-site-check", "a wrong path given fails", [launch, GOOD, "--delay", "0", "--path", "pricing=/plans/"], 1,
         ["pricing: path given: /plans/ gives status 404"], []),
        ("launch-site-check", "a skipped page is listed", [launch, GOOD, "--delay", "0", "--skip", "pricing"], 0,
         ["pricing: left out at the user's request", "RESULT pass"], []),
        ("launch-site-check", "script-built home", [launch, SPA, "--delay", "0"], 1, ["home page holds almost no text", "pricing:"], []),
        ("launch-site-check", "unknown page name", [launch, GOOD, "--skip", "blog"], 2, ["blocked:"], []),
        ("launch-site-check", "placeholder host refused", [launch, "https://example.org"], 2, ["blocked:", "placeholder"], []),
        ("launch-site-check", "site not reachable", [launch, DEAD], 2, ["blocked:", "could not be reached"], []),

        ("post-check", "short post fits", [post, str(F / "post-x-ok.md"), "--platform", "x", "--need-link"], 0,
         ["RESULT pass", "each of 1 links counted as 23", "check them against the platform before posting", "1 hashtags, within 2"], ["FAIL"]),
        ("post-check", "long post is over", [post, str(F / "post-x-long.md"), "--platform", "x"], 1, ["is over the limit of 280"], []),
        ("post-check", "same long post fits a longer platform", [post, str(F / "post-x-long.md"), "--platform", "mastodon"], 0, ["RESULT pass"], []),
        ("post-check", "open claim marker fails", [post, str(F / "post-x-marker.md"), "--platform", "x"], 1,
         ["line 1: open-claim marker '[unverified]'"], []),
        ("post-check", "too many hashtags is a warning", [post, str(F / "post-linkedin-tags.md"), "--platform", "linkedin"], 0,
         ["warn  7 hashtags, more than 5", "RESULT pass"], ["FAIL"]),
        ("post-check", "link required but absent", [post, str(F / "post-linkedin-tags.md"), "--platform", "linkedin", "--need-link"], 1,
         ["holds no link"], []),
        ("post-check", "blog post with front matter passes", [post, str(F / "post-blog-ok.md"), "--platform", "blog"], 0,
         ["front matter has title, description, date", "1 local images exist", "RESULT pass"], ["FAIL"]),
        ("post-check", "blog post with gaps fails", [post, str(F / "post-blog-bad.md"), "--platform", "blog"], 1,
         ["front matter keys missing or empty: description", "is not in the form YYYY-MM-DD", "image not found or empty: missing-shot.png",
          "unfinished marker 'TODO'"], []),
        ("post-check", "remote image is not verified", [post, str(F / "post-remote-image.md"), "--platform", "x"], 2,
         ["RESULT not verified: remote image not opened"], []),
        ("post-check", "empty draft", [post, str(F / "post-empty.md"), "--platform", "x"], 2, ["blocked:", "no text"], []),
        ("post-check", "unknown platform", [post, str(F / "post-x-ok.md"), "--platform", "myspace"], 2, ["blocked:", "known: x, linkedin"], []),
        ("post-check", "missing draft", [post, str(F / "nope.md"), "--platform", "x"], 2, ["blocked:"], []),
        ("post-check", "list platforms", [post, "--list"], 0, ["unverified"], [], "raw"),

        ("claim-check", "find lists four claims", [claims, "find", str(F / "copy.md")], 2,
         ["c4 ", "the only", "3x", "Trusted by", "testimonial", "RESULT not verified: 4 claims found"], ["c5 "]),
        ("claim-check", "find on plain text", [claims, "find", str(F / "copy-plain.md")], 0, ["RESULT pass: no claims found"], []),
        ("claim-check", "every claim sourced", [claims, "check", str(F / "copy.md"), "--sources", str(F / "sources-ok.json")], 0,
         ["observed:", "reported:", "RESULT pass", "quote: \"Ratio 3.2 to 1\""], ["FAIL"]),
        ("claim-check", "gaps in the sources fail", [claims, "check", str(F / "copy.md"), "--sources", str(F / "sources-gaps.json")], 1,
         ["no sources entry covers it", "the quote is not in evidence/timing.md", "evidence file not found: evidence/no-such-file.png",
          "a testimonial needs 'permission'", "FINDINGS (4 fail"], []),
        ("claim-check", "web evidence is not opened without --fetch", [claims, "check", str(F / "copy.md"), "--sources", str(F / "sources-web.json")], 2,
         ["RESULT not verified", "run with --fetch"], []),
        ("claim-check", "web evidence opened with --fetch", [claims, "check", str(F / "copy.md"), "--sources", str(F / "sources-web.json"), "--fetch"], 0,
         ["observed:", "quote found at " + GOOD + "/about/", "not a claim:", "RESULT pass"], []),
        ("claim-check", "plain text passes with a reason", [claims, "check", str(F / "copy-plain.md"), "--sources", str(F / "sources-ok.json")], 0,
         ["RESULT pass: no claims found in the text"], []),
        ("claim-check", "template is written", [claims, "find", str(F / "copy.md"), "--template", str(F / "new-sources.json")], 2,
         ["sources template with 4 entries"], []),
        ("claim-check", "empty template supports nothing", [claims, "check", str(F / "copy.md"), "--sources", str(F / "new-sources.json")], 1,
         ["names no evidence"], []),
        ("claim-check", "missing sources file", [claims, "check", str(F / "copy.md"), "--sources", str(F / "nope.json")], 2, ["blocked:"], []),
        ("claim-check", "missing text", [claims, "find", str(F / "nope.md")], 2, ["blocked:"], []),

        ("first-screen", "saved page passes", [first, str(work / "site-good" / "index.html"), "--root", str(work / "site-good")], 0,
         ["first heading (h1): \"Tide tables your whole harbour can share\"", "first call to action (link): \"Start a harbour table\" -> /signup/",
          "shares words with the title", "needs a browser", "2 of 2 first-load resources measured", "RESULT pass"], ["FAIL"]),
        ("first-screen", "fetched page passes", [first, GOOD + "/", "--promise", "tide table for the harbour"], 0,
         ["every promised word appears", "2 of 2 first-load resources measured", "RESULT pass"], ["FAIL"]),
        ("first-screen", "promise not kept", [first, GOOD + "/", "--promise", "free invoicing software"], 1,
         ["none of the promised words appear"], []),
        ("first-screen", "vague headline and dead action", [first, str(F / "landing-vague.html")], 1,
         ["warn  the headline shares no word with the title or description", "\"Get started\" leads nowhere"], []),
        ("first-screen", "button with no target", [first, str(F / "landing-button.html")], 2,
         ["RESULT not verified", "a script decides"], []),
        ("first-screen", "script-built page", [first, SPA + "/"], 2, ["RESULT not verified", "built by script"], []),
        ("first-screen", "missing file", [first, str(F / "nope.html")], 2, ["blocked:"], []),

        ("tracking-check", "events sent once with properties", [track, str(F / "capture-good.har"), "--expect", str(F / "expect.json")], 0,
         ["event 'sign_up': sent 1 time", "properties as expected (plan, method)", "sent is not arrived", "RESULT pass"], ["FAIL"]),
        ("tracking-check", "event fired twice", [track, str(F / "capture-double.har"), "--expect", str(F / "expect.json")], 1,
         ["event 'sign_up': sent 2 times, expected 1"], []),
        ("tracking-check", "email in the address and wrong property", [track, str(F / "capture-leak.har"), "--expect", str(F / "expect.json")], 1,
         ["personal data in a request address: an email address (m***%40northquay.test)", "'plan' is 'free', expected 'harbour'"], ["mina.okafor"]),
        ("tracking-check", "no request to the endpoint", [track, str(F / "capture-other.har"), "--expect", str(F / "expect.json")], 1,
         ["no captured request goes to 'stats.tidepool.test/collect'"], []),
        ("tracking-check", "request never completed", [track, str(F / "capture-blocked.har"), "--expect", str(F / "expect.json")], 1,
         ["answered with status 0"], []),
        ("tracking-check", "JSON body with a batch of events", [track, str(F / "capture-list.json"), "--expect", str(F / "expect.json")], 0,
         ["request list, 1 requests", "event 'sign_up': sent 1 time", "RESULT pass"], ["FAIL"]),
        ("tracking-check", "plain list of addresses", [track, str(F / "capture-urls.txt"), "--expect", str(F / "expect.json")], 0,
         ["address list", "status is not in the evidence", "RESULT pass"], ["FAIL"]),
        ("tracking-check", "empty capture", [track, str(F / "capture-empty.har"), "--expect", str(F / "expect.json")], 2, ["blocked:", "holds no requests"], []),
        ("tracking-check", "missing expected file", [track, str(F / "capture-good.har"), "--expect", str(F / "nope.json")], 2, ["blocked:"], []),

        ("store-listing-check", "clean listing passes", [listing, str(F / "listing-ok.json")], 0,
         ["name: 23 of 30 characters", "2 screenshot files exist", "RESULT pass"], ["FAIL", "check them against the store's own documentation"]),
        ("store-listing-check", "planted faults are found", [listing, str(F / "listing-bad.json")], 1,
         ["name is 41 characters, over the limit of 30", "keywords repeated in the keyword field: tide", "keywords is ",
          "screenshot file not found or empty: shots/not-there.png", "claim with no source: name", "claim with no source: subtitle",
          "claim with no source: description", "description holds placeholder text: 'TODO'", "space beside the comma"], []),
        ("store-listing-check", "google listing with one screenshot", [listing, str(F / "listing-google.json")], 1,
         ["1 screenshots; the store entry allows 2 to 8"], []),
        ("store-listing-check", "claim with no sources file fails", [listing, str(F / "listing-claims.json")], 1,
         ["claim with no source: description"], []),
        ("store-listing-check", "claim covered by a source passes", [listing, str(F / "listing-claims.json"), "--sources", str(F / "sources-ok.json")], 0,
         ["observed: description line 1", "RESULT pass"], ["FAIL"]),
        ("store-listing-check", "unknown store", [listing, str(F / "listing-nostore.json")], 2, ["blocked:", "apple, google"], []),
        ("store-listing-check", "missing listing", [listing, str(F / "nope.json")], 2, ["blocked:"], []),

        ("page-compare", "two different pages", [compare, str(work / "site-good" / "index.html"), str(F / "theirs.html")], 0,
         ["h1 count", "calls to action", "JSON-LD types", "1 of 2 (50%)", "makes no such claim", "RESULT pass"], ["FAIL", "better than"]),
        ("page-compare", "copied sentences fail", [compare, str(F / "copied.html"), str(F / "theirs.html")], 1,
         ["2 sentences of 8 words or more are word for word the same"], []),
        ("page-compare", "script-built page", [compare, str(work / "site-spa" / "index.html"), str(F / "theirs.html")], 2,
         ["RESULT not verified", "built by script"], []),
        ("page-compare", "same file twice", [compare, str(F / "theirs.html"), str(F / "theirs.html")], 2, ["blocked:", "same bytes"], []),
        ("page-compare", "an address is refused", [compare, GOOD + "/", str(F / "theirs.html")], 2, ["blocked:", "save the page"], []),
        ("page-compare", "missing file", [compare, str(F / "nope.html"), str(F / "theirs.html")], 2, ["blocked:"], []),

        ("mail-domain-check", "sound records pass", [mail, D, "--records", str(F / "records-good.txt"), "--selector", "s1"], 0,
         ["SPF: one record", "DMARC: one record", "p=reject", "(2048 bit rsa)", "RESULT pass"], ["FAIL"]),
        ("mail-domain-check", "permissive records fail", [mail, D, "--records", str(F / "records-open.txt")], 1,
         ["'+all'", "covers 268435456 addresses", "p=none", "is 512 bits, under the minimum of 1024"], []),
        ("mail-domain-check", "policy none fails", [mail, D, "--records", str(F / "records-monitor.txt"), "--selector", "s1"], 1,
         ["DMARC: p=none", "DKIM: no key record at s1._domainkey.mail.tidepool.test"], []),
        ("mail-domain-check", "no selector means not verified", [mail, D, "--records", str(F / "records-monitor.txt"), "--monitoring-ok"], 2,
         ["warn  DMARC: p=none", "RESULT not verified: DKIM: no selector"], []),
        ("mail-domain-check", "missing DMARC record", [mail, D, "--records", str(F / "records-nodmarc.txt"), "--selector", "s1"], 1,
         ["DMARC: no TXT record starting with v=DMARC1 at _dmarc.mail.tidepool.test"], []),
        ("mail-domain-check", "broken syntax", [mail, D, "--records", str(F / "records-broken.txt")], 1,
         ["SPF: 2 records", "p=rejected is not one of", "pct=150", "is not in the form mailto:", "p= is empty"], []),
        ("mail-domain-check", "file with no records", [mail, D, "--records", str(F / "records-junk.txt")], 2, ["blocked:"], []),
        ("mail-domain-check", "neither records nor lookup", [mail, D], 2, ["blocked:", "exactly one of"], []),
        ("mail-domain-check", "not a domain", [mail, "send from us", "--records", str(F / "records-good.txt")], 2, ["blocked:", "never guessed"], []),
        ("mail-domain-check", "lookup refuses a reserved name", [mail, D, "--lookup"], 2, ["blocked:", "placeholder or reserved"], []),
        ("mail-domain-check", "lookup with no resolver command", [mail, "mail.tidepool-fixture.dev", "--lookup"], 2,
         ["blocked:", "neither dig nor nslookup"], [], "nopath"),
    ]

    failed = ran = 0
    for case in cases:
        skill, name, command, want, has, lacks = case[:6]
        extra = case[6] if len(case) > 6 else ""
        if args.only and skill != args.only:
            continue
        ran += 1
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        if extra == "nopath":
            env["PATH"] = str(work / "no-such-bin")
        done = subprocess.run([sys.executable, "-B", *command], capture_output=True, text=True, timeout=180, cwd=work, env=env)
        output = done.stdout + done.stderr
        lines = [line for line in done.stdout.strip().splitlines() if line.strip()]
        problems = []
        if done.returncode != want:
            problems.append(f"exit {done.returncode}, expected {want}")
        problems += [f"missing: {text!r}" for text in has if text not in output]
        problems += [f"must not appear: {text!r}" for text in lacks if text in output]
        if extra != "raw" and not (lines and lines[-1].startswith(("RESULT pass", "RESULT fail: ", "RESULT not verified: ", "blocked: "))):
            problems.append(f"last line is not a result line: {lines[-1] if lines else '(no output)'}")
        if "Traceback" in output:
            problems.append("the script crashed")
        print(f"{'FAIL' if problems else 'ok  '} {skill}: {name} (exit {done.returncode}, expect {want})")
        for problem in problems:
            print(f"       {problem}")
        if args.show or problems:
            print("       | " + "\n       | ".join(output.strip().splitlines()))
        failed += bool(problems)

    # checks on what the servers saw, and on the shared files
    extras = []
    if not args.only or args.only == "site-audit":
        paths = sorted({path for _, path, _ in closed.seen})
        extras.append(("site-audit: a site closed by robots.txt was asked for robots.txt only", paths == ["/robots.txt"], str(paths)))
    agents = {agent for server in (good, bad, closed, spa, soft) for _, _, agent in server.seen}
    extras.append(("every request carried the checker's own user agent", bool(agents) and all("mstack-growth-check" in a for a in agents), str(agents)))
    for name, holders in (("pagefacts.py", ["site-audit", "structured-data-check", "launch-site-check", "first-screen", "page-compare"]),
                          ("claims.py", ["claim-check", "store-listing-check"])):
        copies = {(SKILLS / skill / "scripts" / name).read_bytes() for skill in holders}
        extras.append((f"the {len(holders)} copies of {name} are identical", len(copies) == 1, ""))
    extras.append(("the draft, listing and page files were not changed by any script",
                   all((work / path).read_text(encoding="utf-8") == text.replace("{{GOOD}}", GOOD).replace("{{BAD}}", BAD)
                       for path, text in fixtures.FILES.items()), ""))
    for label, fine, detail in extras:
        ran += 1
        failed += not fine
        print(f"{'ok  ' if fine else 'FAIL'} {label}" + (f" ({detail})" if detail and not fine else ""))

    total = sum(len(server.seen) for server in (good, bad, closed, spa, soft))
    print(f"\n{ran} cases, {failed} failed; {total} requests, all to 127.0.0.1; files in {work}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
