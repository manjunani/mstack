#!/usr/bin/env python3
"""Before a launch: ask a site for every page a first visitor needs and report each one.

  launch.py <base-url> [--path pricing=/plans/] [--skip pricing] [--action-text "join the beta"] [--out report.json]

Checks, each reported on its own line:
  home        answers 200, has a title, is not marked noindex, holds no "lorem ipsum"
  not-found   a made-up address answers 404 or 410 (not 200, not a redirect to the home page)
  pricing, privacy, terms, contact
              found from a link on the home page, or at a usual path, and answers 200 with text
  favicon     the icon named in the HTML, or /favicon.ico, answers with an image
  preview     og:title, og:description and og:image are set and the image answers
  action      the first sign-up or download link on the home page leads somewhere that answers
  robots      robots.txt does not close the whole site

--path NAME=/path   say where a page lives (NAME is pricing, privacy, terms or contact)
--skip NAME         leave a page out, for a product that has none; it is listed under not checked
Only the site named is asked, with GET requests. Forms are never submitted.

Exit codes: 0 = pass, 1 = fail, 2 = not verified (something on another host, or unreadable) or blocked.
"""
import argparse
import hashlib
import re
import secrets
import sys
import time
import urllib.parse
import urllib.robotparser

import pagefacts as pf

PAGES = {
    "pricing": (("/pricing", "/plans", "/prices"), re.compile(r"\b(pricing|plans|prices?)\b", re.I)),
    "privacy": (("/privacy", "/privacy-policy", "/legal/privacy"), re.compile(r"\bprivacy\b", re.I)),
    "terms": (("/terms", "/terms-of-service", "/tos", "/legal/terms"), re.compile(r"\b(terms|conditions|tos)\b", re.I)),
    "contact": (("/contact", "/contact-us", "/support", "/help"), re.compile(r"\b(contact|support|help|get in touch)\b", re.I)),
}
ACTION = re.compile(r"\b(sign ?up|get started|start|try|download|install|join|register|create (an |your )?account|"
                    r"subscribe|buy|get the app|book a demo|request access)\b", re.I)
DEAD = re.compile(r"^\s*(#|javascript:|$)", re.I)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base", help="the site's address, for example https://your-site.tld")
    parser.add_argument("--path", action="append", default=[], metavar="NAME=/path", help="where a required page lives")
    parser.add_argument("--skip", action="append", default=[], metavar="NAME", help="leave out pricing, privacy, terms or contact")
    parser.add_argument("--action-text", help="words of the sign-up or download link, if the usual ones do not fit")
    parser.add_argument("--delay", type=float, default=0.2, help="seconds between requests (default 0.2)")
    parser.add_argument("--timeout", type=int, default=15, help="seconds allowed per request (default 15)")
    parser.add_argument("--out", help="also write the three lists as JSON to this new file")
    args = parser.parse_args()

    if pf.out_refused(args.out):
        return pf.blocked(f"{args.out} exists; reports are never overwritten, name a new file")
    problem = pf.url_problem(args.base)
    if problem:
        return pf.blocked(problem)
    placed = {}
    for item in args.path:
        name, _, where = item.partition("=")
        if name not in PAGES or not where.startswith("/"):
            return pf.blocked(f"--path wants NAME=/path with NAME one of {', '.join(PAGES)}; got '{item}'")
        placed[name] = where
    unknown = [name for name in args.skip if name not in PAGES]
    if unknown:
        return pf.blocked(f"--skip accepts {', '.join(PAGES)}; got {', '.join(unknown)}")
    try:
        action = re.compile(args.action_text, re.I) if args.action_text else ACTION
    except re.error as exc:
        return pf.blocked(f"--action-text is not a usable pattern: {exc}")

    parts = urllib.parse.urlsplit(args.base)
    root = f"{parts.scheme}://{parts.netloc}"
    base = root + (parts.path or "/")
    report = pf.Report(f"launch-site-check {base}")
    count = [0]

    def get(url):
        if count[0] and args.delay > 0:
            time.sleep(args.delay)
        count[0] += 1
        return pf.fetch(url, timeout=args.timeout)

    def describe(got):
        if got["error"]:
            return got["error"]
        if got["offsite"]:
            return f"redirects to another site, {got['offsite']}"
        return f"status {got['status']}"

    # home
    home = get(base)
    if home["error"]:
        return pf.blocked(f"{base} could not be reached: {home['error']}")
    if home["offsite"] or home["status"] != 200:
        report.fail(f"home: {base} gives {describe(home)}")
        report.skip("every other check: they start from the home page", blocks=True)
        return report.finish(args.out)
    html = pf.decode(home["body"], home["headers"])
    page = pf.parse(html)
    here = home["final"]
    if page.title:
        report.ok(f"home: answers 200, title '{page.title[:70]}'")
    else:
        report.fail("home: answers 200 but has no <title>")
    marks = " ".join(page.meta_all("robots") + page.meta_all("googlebot") + [home["headers"].get("x-robots-tag", "")]).lower()
    if "noindex" in marks:
        report.fail("home: marked noindex, so search engines are told to leave it out")
    if "lorem ipsum" in page.text.lower():
        report.fail("home: holds placeholder text ('lorem ipsum')")
    if parts.scheme == "http" and parts.hostname not in ("127.0.0.1", "localhost", "::1"):
        report.warn("the address given is http, not https")
    scripted = page.built_by_script()
    if scripted:
        report.skip("links and tags a browser adds: the home page holds almost no text in its HTML", blocks=True)

    # not-found behaviour
    made_up = urllib.parse.urljoin(root, f"/mstack-check-{secrets.token_hex(4)}")
    probe = get(made_up)
    soft = False
    if probe["status"] in (404, 410):
        report.ok(f"not-found: a made-up address answers {probe['status']}")
    elif probe["status"] == 200 or probe["offsite"]:
        soft = True
        how = "after a redirect " if len(probe["chain"]) > 1 else ""
        report.fail(f"not-found: a made-up address ({urllib.parse.urlsplit(made_up).path}) {how}gives {describe(probe)}; "
                    f"missing pages have to answer 404")
    else:
        report.warn(f"not-found: a made-up address gives {describe(probe)}")
    probe_mark = hashlib.sha256(probe["body"]).hexdigest() if probe["status"] == 200 else None

    def on_site(href):
        target = urllib.parse.urljoin(here, href)
        return target if pf.same_site(target, here) and urllib.parse.urlsplit(target).scheme in ("http", "https") else None

    # required pages
    for name, (usual, pattern) in PAGES.items():
        if name in args.skip:
            report.skip(f"{name}: left out at the user's request")
            continue
        candidates, how = [], ""
        if name in placed:
            candidates, how = [urllib.parse.urljoin(root, placed[name])], "path given"
        else:
            for anchor in page.anchors:
                href = anchor["href"] or ""
                if pattern.search(anchor["text"] or anchor["alt"]) or pattern.search(urllib.parse.urlsplit(href).path):
                    if name == "contact" and href.lower().startswith("mailto:") and "@" in href:
                        candidates, how = ["mailto"], "mail link on the home page"
                        break
                    target = on_site(href) if not DEAD.match(href) else None
                    if target:
                        candidates, how = [target], f"linked from the home page as '{(anchor['text'] or anchor['alt'])[:40]}'"
                        break
            if not candidates and not soft:
                candidates, how = [urllib.parse.urljoin(root, path) for path in usual], "usual path, not linked from the home page"
        if candidates == ["mailto"]:
            report.ok(f"{name}: {how} (mail delivery not tested)")
            continue
        if not candidates:
            report.fail(f"{name}: no link on the home page, and usual paths prove nothing because made-up addresses answer 200")
            continue
        last = None
        for target in candidates:
            got = get(target)
            last = got
            if got["status"] == 200 and not got["offsite"]:
                break
        short = urllib.parse.urlsplit(last["final"]).path
        if last["status"] != 200 or last["offsite"]:
            tried = ", ".join(urllib.parse.urlsplit(t).path for t in candidates)
            report.fail(f"{name}: {how}: {tried} gives {describe(last)}")
            continue
        body = pf.parse(pf.decode(last["body"], last["headers"]))
        if probe_mark and hashlib.sha256(last["body"]).hexdigest() == probe_mark:
            report.fail(f"{name}: {short} returns the same page as a made-up address")
        elif not pf.words(body.text) and not body.built_by_script():
            report.fail(f"{name}: {short} answers 200 but holds no text")
        elif body.built_by_script():
            report.skip(f"{name}: {short} answers 200 but is built by script; its content was not read", blocks=True)
        else:
            report.ok(f"{name}: {short} answers 200 with {len(pf.words(body.text))} words ({how})")

    # favicon
    icons = [link["href"] for link in page.rel("icon") if link["href"]] or ["/favicon.ico"]
    icon = urllib.parse.urljoin(here, icons[0])
    if not pf.same_site(icon, here):
        report.skip(f"favicon: on another host ({icon}); not fetched", blocks=True)
    else:
        got = get(icon)
        kind = got["headers"].get("content-type", "").lower()
        is_image = kind.startswith("image/") or urllib.parse.urlsplit(icon).path.lower().endswith((".ico", ".png", ".svg"))
        if got["status"] == 200 and got["body"] and is_image and not pf.looks_like_html(pf.decode(got["body"][:2000])):
            report.ok(f"favicon: {urllib.parse.urlsplit(icon).path} answers with {len(got['body'])} bytes")
        else:
            report.fail(f"favicon: {urllib.parse.urlsplit(icon).path} gives {describe(got)}"
                        + (" but not an image" if got["status"] == 200 else ""))

    # social preview
    absent = [tag for tag in ("og:title", "og:description", "og:image") if not page.meta_one(tag)]
    if absent:
        report.fail(f"preview: tags missing on the home page: {', '.join(absent)}")
    else:
        report.ok("preview: og:title, og:description and og:image are set")
    image = page.meta_one("og:image")
    if image:
        if not re.match(r"^https?://", image, re.I):
            report.fail(f"preview: og:image is not a full address ('{image[:60]}'); sharing sites do not resolve relative ones")
        elif not pf.same_site(image, here):
            report.skip(f"preview: og:image is on another host ({image[:80]}); not fetched", blocks=True)
        else:
            got = get(image)
            if got["status"] == 200 and got["body"] and got["headers"].get("content-type", "").lower().startswith("image/"):
                report.ok(f"preview: og:image answers with {len(got['body'])} bytes of {got['headers']['content-type']}")
            else:
                report.fail(f"preview: og:image gives {describe(got)}"
                            + (f" with type '{got['headers'].get('content-type', '')}'" if got["status"] == 200 else ""))
    if not page.meta_one("twitter:card"):
        report.warn("preview: no twitter:card tag; some sharing sites fall back to a small card")

    # sign-up or download
    chosen = next((a for a in page.anchors if action.search(a["text"] or a["alt"])), None)
    if chosen:
        label, href = (chosen["text"] or chosen["alt"])[:40], chosen["href"] or ""
        if DEAD.match(href) and not re.match(r"^\s*#[\w-]+", href):
            report.fail(f"action: '{label}' leads nowhere (href '{href}')")
        elif href.strip().startswith("#"):
            name = href.strip()[1:]
            if re.search(rf"\bid\s*=\s*[\"']?{re.escape(name)}\b", html):
                report.ok(f"action: '{label}' jumps to #{name}, which is on the page")
            else:
                report.fail(f"action: '{label}' jumps to #{name}, which is not on the page")
        elif href.lower().startswith("mailto:"):
            report.ok(f"action: '{label}' is a mail link (delivery not tested)")
        elif on_site(href) is None:
            report.skip(f"action: '{label}' points to another host ({href[:80]}); not fetched", blocks=True)
        else:
            got = get(on_site(href))
            if got["status"] == 200 and not got["offsite"]:
                report.ok(f"action: '{label}' leads to {urllib.parse.urlsplit(got['final']).path}, which answers 200")
            else:
                report.fail(f"action: '{label}' leads to {href}, which gives {describe(got)}")
    elif any(b["type"] in ("submit", "image") and b["form"] is not None for b in page.buttons):
        report.ok("action: a form with a submit button is on the home page")
        report.skip("action: the form was not submitted; whether it delivers is not known", blocks=True)
    elif scripted:
        report.skip("action: no sign-up or download link in the HTML of a script-built page", blocks=True)
    else:
        report.fail("action: no sign-up or download link found on the home page (use --action-text if it is worded differently)")

    # robots
    robots = get(root + "/robots.txt")
    text = pf.decode(robots["body"], robots["headers"])
    if robots["status"] == 200 and not pf.looks_like_html(text):
        rules = urllib.robotparser.RobotFileParser()
        rules.parse(text.splitlines())
        if rules.can_fetch("Googlebot", base):
            report.ok("robots: robots.txt leaves the home page open to search crawlers")
        else:
            report.fail("robots: robots.txt closes the home page to search crawlers")
    elif robots["status"] in (404, 410):
        report.ok("robots: no robots.txt, so nothing is closed")
    else:
        report.warn(f"robots: /robots.txt gives {describe(robots)}" + (" with an HTML page" if robots["status"] == 200 else ""))

    report.skip("forms were not submitted and no account was created")
    report.skip("how the pages look (use design-review), every other link (use link-check), certificate and headers (use site-check)")
    report.note(f"{count[0]} GET requests sent to {parts.netloc}")
    return report.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
