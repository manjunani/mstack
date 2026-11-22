#!/usr/bin/env python3
"""Check how one deployed address answers: redirects, status, security headers, cache headers,
certificate expiry and mixed content.

  site_check.py URL                     run every check on URL
  site_check.py URL --expect-status 401 the status the final page is expected to give (default 200)
  site_check.py URL --require content-security-policy
                                        treat an advised header as required (repeat for more)
  site_check.py URL --require-https     fail when the final address is plain http (automatic for public hosts)
  site_check.py URL --ca-file ca.pem    trust a private certificate authority (staging, internal sites)
  site_check.py URL --json report.json  also write the findings to a new file

It sends GET requests to the address the user named and to the redirects that address gives, and
opens one TLS connection to read the certificate. It guesses no paths and sends nothing else.

Exit codes: 0 = every check passed (warnings may be listed)
            1 = at least one check failed
            2 = not verified or blocked: no answer, bad address, or a file could not be used
"""
import argparse
import datetime
import html.parser
import json
import pathlib
import re
import socket
import ssl
import sys
import urllib.parse

import webfetch

TOOL = "site-check"
CHECKS = pathlib.Path(__file__).resolve().parent.parent / "references" / "checks.json"
ACTIVE = {"script": ("src",), "iframe": ("src",), "frame": ("src",), "object": ("data",), "embed": ("src",),
          "link": ("href",), "form": ("action",)}
PASSIVE = {"img": ("src", "srcset"), "source": ("src", "srcset"), "video": ("src", "poster"), "audio": ("src",),
           "track": ("src",), "input": ("src",)}
LINK_RELS = {"stylesheet", "preload", "modulepreload", "icon", "manifest", "prefetch"}


class Refs(html.parser.HTMLParser):
    """Collect plain-http references that a secure page would load or post to."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active, self.passive = [], []

    def handle_starttag(self, tag, attrs):
        attrs = {key: (value or "") for key, value in attrs}
        if tag == "link" and not (set(attrs.get("rel", "").lower().split()) & LINK_RELS):
            return
        for table, bucket in ((ACTIVE, self.active), (PASSIVE, self.passive)):
            for name in table.get(tag, ()):
                for value in re.split(r"\s*,\s*", attrs.get(name, "")) if name == "srcset" else [attrs.get(name, "")]:
                    value = value.strip().split(" ")[0]
                    if value.lower().startswith("http://"):
                        bucket.append(f"<{tag} {name}> {value}")


class Report:
    def __init__(self):
        self.lines = []

    def add(self, level, name, detail):
        self.lines.append({"level": level, "check": name, "detail": detail})
        print(f"  {level:5} {name}: {detail}")

    def count(self, level):
        return sum(1 for line in self.lines if line["level"] == level)


def load_checks(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = [value for key, value in data.items() if isinstance(value, dict)] + data.get("headers", [])
    unverified = [entry for entry in entries if not entry.get("verified")]
    return data, len(unverified), len(entries)


def certificate(host, port, context, timeout):
    """Return (days left, expiry date, subject) or raise OSError / ssl.SSLError."""
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as secure:
            cert = secure.getpeercert()
    expires = datetime.datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), datetime.timezone.utc)
    left = (expires - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 86400
    subject = ", ".join(value for part in cert.get("subject", ()) for key, value in part if key == "commonName")
    return left, expires, subject


def check_headers(report, final, secure, checks, required_extra):
    csp = final.header("content-security-policy")
    for entry in checks["headers"]:
        name = entry["name"]
        level = "FAIL" if entry["value"] == "required" or name in required_extra else "warn"
        if entry.get("applies") == "https" and not secure:
            report.add("skip", name, "applies to https only; the final address is plain http")
            continue
        value = final.header(name)
        if name == "x-frame-options" and not value and "frame-ancestors" in csp.lower():
            report.add("ok", name, "covered by frame-ancestors in the content security policy")
        elif not value:
            report.add(level, name, f"missing ({entry['why']})")
        elif name == "x-content-type-options" and value.strip().lower() != "nosniff":
            report.add(level, name, f"value is '{value}', expected 'nosniff'")
        elif name == "strict-transport-security":
            age = re.search(r"max-age\s*=\s*\"?(\d+)", value, re.I)
            wanted = checks["hsts_min_max_age"]["value"]
            if not age:
                report.add(level, name, f"no max-age in '{value}'")
            elif int(age.group(1)) < wanted:
                report.add("warn", name, f"max-age {age.group(1)} is below {wanted} seconds")
            else:
                report.add("ok", name, value)
        else:
            report.add("ok", name, value if len(value) <= 90 else value[:87] + "...")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="the deployed address to check")
    parser.add_argument("--expect-status", type=int, default=200, help="status the final page should give (default 200)")
    parser.add_argument("--require", action="append", default=[], metavar="HEADER", help="treat this header as required")
    parser.add_argument("--require-https", action="store_true", help="fail when the final address is plain http")
    parser.add_argument("--ca-file", type=pathlib.Path, help="PEM file of a private certificate authority to trust")
    parser.add_argument("--checks-file", type=pathlib.Path, default=CHECKS, help="dated limits and header list (default: references/checks.json)")
    parser.add_argument("--max-hops", type=int, default=10, help="redirects to follow before giving up (default 10)")
    parser.add_argument("--timeout", type=float, default=15.0, help="seconds to wait per request (default 15)")
    parser.add_argument("--json", type=pathlib.Path, metavar="FILE", help="write the findings to this new file")
    args = parser.parse_args()

    try:
        url = webfetch.check_url(args.url)
        checks, unverified, total = load_checks(args.checks_file)
        context = ssl.create_default_context(cafile=str(args.ca_file)) if args.ca_file else ssl.create_default_context()
    except webfetch.BadURL as exc:
        print(f"blocked: {exc}")
        return 2
    except (OSError, ValueError, KeyError, ssl.SSLError) as exc:
        print(f"blocked: a file this check needs could not be used ({exc})")
        return 2
    if args.json and args.json.exists():
        print(f"blocked: {args.json} already exists; name a new file")
        return 2

    print(f"site-check {url}\nuser agent: {webfetch.user_agent(TOOL)}")
    if unverified:
        print(f"note: {unverified} of {total} limits in {args.checks_file.name} are marked unverified: written from memory, not read in their source")
    report = Report()
    hops, problem = webfetch.follow(url, TOOL, max_hops=args.max_hops, timeout=args.timeout, context=context)
    print("redirects:")
    for number, hop in enumerate(hops, 1):
        answer = hop.status if hop.status else f"no answer ({hop.error_kind})"
        arrow = f" -> {hop.location}" if hop.location else ""
        print(f"  hop {number}: {answer} {hop.url}{arrow}  ({(hop.total or 0) * 1000:.0f} ms)")
    final = hops[-1]
    print("checks:")
    if problem:
        report.add("FAIL", "redirects", problem)
    for earlier, later in zip(hops, hops[1:]):
        if earlier.url.startswith("https:") and later.url.startswith("http:"):
            report.add("FAIL", "redirects", f"{earlier.url} sends visitors from https back to plain http")
    if not problem and len(hops) - 1 > checks["redirect_hops_warn"]["value"]:
        report.add("warn", "redirects", f"{len(hops) - 1} redirects before the page")
    elif not problem:
        report.add("ok", "redirects", f"{len(hops) - 1} redirect(s), no loop")

    unanswered = None
    if final.error:
        if final.error_kind == "certificate":
            report.add("FAIL", "certificate", f"{final.url}: {final.error}")
        elif final.error_kind == "refused":
            report.add("FAIL", "status", f"{final.url} refused the connection ({final.error})")
        else:
            unanswered = f"no answer from {final.url} ({final.error_kind}: {final.error})"
            report.add("skip", "status", unanswered)
    elif not problem:
        secure = final.url.startswith("https:")
        host = urllib.parse.urlsplit(final.url)
        if final.status == args.expect_status:
            report.add("ok", "status", f"{final.status} at {final.url}")
        else:
            report.add("FAIL", "status", f"{final.status} at {final.url}, expected {args.expect_status}")
        if secure:
            report.add("ok", "https", "the final address is https")
        elif args.require_https or not webfetch.is_local(host.hostname):
            report.add("FAIL", "https", "the final address is plain http")
        else:
            report.add("skip", "https", "plain http on a local host; pass --require-https to make this a failure")
        check_headers(report, final, secure, checks, {name.lower() for name in args.require})
        cache = {name: final.header(name) for name in ("cache-control", "etag", "last-modified", "expires", "age", "vary") if final.header(name)}
        if cache:
            report.add("ok", "cache headers", "; ".join(f"{key}: {value}" for key, value in cache.items()))
        else:
            report.add("warn", "cache headers", "none sent (no Cache-Control, ETag, Last-Modified or Expires)")
        if secure:
            try:
                left, expires, subject = certificate(host.hostname, host.port or 443, context, args.timeout)
                detail = f"expires {expires:%Y-%m-%d} ({left:.0f} days left), issued to {subject or 'unknown'}"
                if left < checks["certificate_fail_days"]["value"]:
                    report.add("FAIL", "certificate", detail)
                elif left < checks["certificate_warn_days"]["value"]:
                    report.add("warn", "certificate", detail)
                else:
                    report.add("ok", "certificate", detail)
            except (OSError, ssl.SSLError, KeyError, ValueError) as exc:
                report.add("skip", "certificate", f"could not be read ({exc})")
                unanswered = unanswered or "the certificate could not be read"
        else:
            report.add("skip", "certificate", "plain http has no certificate")
        if "html" in final.content_type:
            refs = Refs()
            refs.feed(final.text())
            if not secure:
                found = len(refs.active) + len(refs.passive)
                report.add("skip", "mixed content", f"the page is plain http; it holds {found} http:// reference(s) that would be mixed content under https")
            elif refs.active:
                report.add("FAIL", "mixed content", f"{len(refs.active)} blocked-by-browsers reference(s): " + "; ".join(refs.active[:5]))
            else:
                report.add("ok", "mixed content", "no script, style, frame or form points at plain http")
            if secure and refs.passive:
                report.add("warn", "mixed content", f"{len(refs.passive)} image or media reference(s) over plain http: " + "; ".join(refs.passive[:5]))
            if final.truncated:
                report.add("warn", "mixed content", "the page was larger than the read limit; only the first part was scanned")
            print("  not checked: addresses inside style sheets and scripts")
        else:
            report.add("skip", "mixed content", f"content type is '{final.content_type or 'not stated'}', not HTML")

    failed = [line for line in report.lines if line["level"] == "FAIL"]
    if failed:
        result, code = "RESULT fail: " + "; ".join(f"{line['check']}: {line['detail']}" for line in failed[:3])[:300], 1
    elif unanswered:
        result, code = f"RESULT not verified: {unanswered}", 2
    else:
        result, code = "RESULT pass", 0
    if args.json:
        args.json.write_text(json.dumps({"url": url, "checked": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                                         "hops": [{"url": hop.url, "status": hop.status, "error": hop.error, "location": hop.location} for hop in hops],
                                         "checks": report.lines, "result": result}, indent=2) + "\n", encoding="utf-8")
        print(f"findings written to {args.json}")
    print(f"{report.count('ok')} ok, {report.count('FAIL')} failed, {report.count('warn')} warnings, {report.count('skip')} not checked or not applicable")
    print(result)
    return code


if __name__ == "__main__":
    sys.exit(main())
