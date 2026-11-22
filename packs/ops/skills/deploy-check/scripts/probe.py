#!/usr/bin/env python3
"""Ask a running service which version it is and whether it answers, several times, and judge the answers.

  probe.py URL --expect TEXT [--max-ms N] [--repeat N] [--interval S] [--status CODE]

For each request the script records the status code, whether TEXT (the version string or commit you
expected to be live) is in the body or in a response header, and how long the answer took.

  status    must equal --status (default 200) on every request
  version   TEXT must be found on every request; without --expect the version is not verified
  time      the median over all requests must be at most --max-ms
  body      an empty body counts as a failure unless --allow-empty is given

Only the address you give is contacted. Redirects are reported, not followed. Requests are GET and carry
no credentials. A record of the run is written to .mstack/deploy-check/last.json (skip with --no-record).

Exit codes: 0 = every check passed, 1 = a check failed, 2 = not verified or blocked (bad URL, no --expect).
"""
import argparse
import datetime
import json
import pathlib
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

LIMITS = pathlib.Path(__file__).resolve().parent.parent / "references" / "limits.json"
MAX_BODY = 1_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def default_limit():
    """Return (milliseconds, note). The shipped default is a starting point, not a measured standard."""
    try:
        entry = json.loads(LIMITS.read_text(encoding="utf-8"))["response_ms"]
        note = "" if entry.get("verified") else f"the {entry['value']} ms limit is an unverified default; give your own with --max-ms"
        return float(entry["value"]), note
    except (OSError, ValueError, KeyError):
        return 2000.0, "limits.json could not be read; using 2000 ms, an unverified default"


def request_once(url, timeout, expect, header):
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "mstack-deploy-check", "Cache-Control": "no-cache"})
    begin = time.perf_counter()
    try:
        with opener.open(req, timeout=timeout) as resp:
            status, headers, body = resp.status, resp.headers, resp.read(MAX_BODY)
    except urllib.error.HTTPError as exc:
        status, headers, body = exc.code, exc.headers, exc.read(MAX_BODY)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return {"error": str(reason), "ms": round((time.perf_counter() - begin) * 1000, 1)}
    ms = round((time.perf_counter() - begin) * 1000, 1)
    found = None
    if expect:
        if header:
            found = "header " + header if expect in (headers.get(header) or "") else None
        else:
            for name, value in headers.items():
                if expect in value:
                    found = "header " + name
                    break
            if found is None and expect in body.decode("utf-8", "replace"):
                found = "body"
    return {"status": status, "ms": ms, "bytes": len(body), "found": found,
            "location": headers.get("Location") if 300 <= status < 400 else None}


def probe(url, expect=None, header=None, status=200, max_ms=None, repeat=3, interval=1.0, timeout=10.0, allow_empty=False, out=print):
    """Run the requests and return (state, reason, record). state is pass, fail or not verified."""
    note = ""
    if max_ms is None:
        max_ms, note = default_limit()
    attempts, problems = [], []
    for number in range(1, repeat + 1):
        result = request_once(url, timeout, expect, header)
        attempts.append(result)
        if "error" in result:
            out(f"  {number}: no answer ({result['error']})")
            problems.append(f"request {number} got no answer: {result['error']}")
        else:
            seen = "" if not expect else (f"  version found in {result['found']}" if result["found"] else "  version NOT found")
            where = f"  redirects to {result['location']}" if result["location"] else ""
            out(f"  {number}: status {result['status']}  {result['ms']} ms  {result['bytes']} bytes{seen}{where}")
            if result["status"] != status:
                problems.append(f"request {number}: status {result['status']}, expected {status}")
            if expect and not result["found"]:
                place = f"header {header}" if header else "body or headers"
                problems.append(f"request {number}: expected version '{expect}' is not in the {place}")
            if result["bytes"] == 0 and not allow_empty and result["status"] == status:
                problems.append(f"request {number}: the body is empty")
        if number < repeat:
            time.sleep(interval)
    times = [a["ms"] for a in attempts if "error" not in a]
    median = round(statistics.median(times), 1) if times else None
    if median is not None:
        out(f"  median {median} ms, slowest {max(times)} ms, limit {max_ms:g} ms")
        if median > max_ms:
            problems.append(f"median response time {median} ms is over the limit of {max_ms:g} ms")
    if note:
        out("  note: " + note)
    record = {"url": url, "expect": expect, "expected_status": status, "limit_ms": max_ms, "median_ms": median,
              "attempts": attempts, "when": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    if problems:
        state, reason = "fail", problems[0] + (f" (and {len(problems) - 1} more)" if len(problems) > 1 else "")
    elif not expect:
        state, reason = "not verified", "the service answers, but no expected version was given, so which version is live is unknown"
    else:
        state, reason = "pass", f"'{expect}' is live; {repeat} of {repeat} requests returned {status}; median {median} ms"
    record.update(state=state, reason=reason, problems=problems)
    return state, reason, record


def valid_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "give a full http or https address, such as https://example.com/health"
    if parts.username or parts.password:
        return "the address holds a user name or password; give one without credentials"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="the address to request, given by the user")
    parser.add_argument("--expect", help="version string or commit that must be live (looked for in the body and headers)")
    parser.add_argument("--header", help="look for --expect only in this response header")
    parser.add_argument("--status", type=int, default=200, help="expected status code (default 200)")
    parser.add_argument("--max-ms", type=float, help="limit for the median response time in milliseconds")
    parser.add_argument("--repeat", type=int, default=3, help="number of requests (default 3)")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between requests (default 1)")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds to wait for one answer (default 10)")
    parser.add_argument("--allow-empty", action="store_true", help="accept an empty body")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder for the record (default: current folder)")
    parser.add_argument("--no-record", action="store_true", help="do not write .mstack/deploy-check/last.json")
    args = parser.parse_args()

    problem = valid_url(args.url)
    if problem:
        print(f"blocked: {problem}")
        return 2
    if not 1 <= args.repeat <= 100:
        print("blocked: --repeat must be between 1 and 100")
        return 2
    print(f"checking {args.url} ({args.repeat} requests, GET, redirects not followed)")
    state, reason, record = probe(args.url, args.expect, args.header, args.status, args.max_ms, args.repeat,
                                  args.interval, args.timeout, args.allow_empty)
    for line in record["problems"]:
        print("  FAIL " + line)
    if not args.no_record:
        folder = args.root.resolve() / ".mstack" / "deploy-check"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "last.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        with (folder / "log.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({k: record[k] for k in ("when", "url", "expect", "state", "reason", "median_ms")}) + "\n")
        print(f"  record: {folder / 'last.json'}")
    print(f"RESULT {state}: {reason}" if state != "pass" else f"RESULT pass: {reason}")
    return {"pass": 0, "fail": 1}.get(state, 2)


if __name__ == "__main__":
    sys.exit(main())
