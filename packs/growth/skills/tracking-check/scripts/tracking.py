#!/usr/bin/env python3
"""Check captured network requests for the analytics events a page was expected to send.

  tracking.py <evidence-file> --expect <expected.json> [--out report.json]

Evidence is something the user captured while using the page:
  - a HAR file saved from the browser's network panel, or
  - a JSON list of requests: [{"url": "...", "method": "POST", "body": "...", "status": 204}, ...], or
  - a text file with one request address per line.

The expected file is JSON:
  { "endpoint": "analytics.your-site.tld/collect",        part of the address every event request contains
    "name_keys": ["en", "event", "event_name", "name"],  optional: where the event name sits
    "events": [ { "name": "sign_up", "properties": {"plan": "pro", "method": "*"}, "count": 1 } ] }
A property value of "*" means any non-empty value. "count" is how many times the event should be sent (default 1).

For every expected event it confirms a request went to the endpoint with that name and those properties,
fails an event sent more often than expected, fails an answer with an error status, and fails personal data
(an email address, or a parameter named like email, phone or password) carried in the address.
Email addresses are masked in the output. Sent is not arrived: whether the event shows up in the analytics
account is listed as not checked every time. The script reads files only and uses no network.

Exit codes: 0 = pass, 1 = fail, 2 = blocked (evidence or expected file unreadable or empty).
"""
import argparse
import datetime
import json
import pathlib
import re
import sys
import urllib.parse

NAME_KEYS = ["en", "event", "event_name", "eventName", "name", "e", "ea", "action"]
PROP_HOLDERS = ("properties", "params", "props", "event_params", "data", "payload")
BATCH_KEYS = ("events", "batch", "data")
EMAIL = re.compile(r"[A-Za-z0-9._+-]+(?:@|%40)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", re.I)
PERSONAL_KEYS = re.compile(r"^(e-?mail|email_address|phone|phone_number|tel|mobile|password|passwd|pwd|ssn|first_?name|"
                           r"last_?name|full_?name|surname|address|street|dob|birth_?date|card_?number)$", re.I)


class Report:
    """Three lists and one end state. Findings are either failures (block) or warnings (do not)."""

    def __init__(self, title):
        self.title, self.failures, self.warnings, self.fine, self.skipped, self.open, self.notes = title, [], [], [], [], [], []

    def fail(self, text):
        self.failures.append(text)

    def warn(self, text):
        self.warnings.append(text)

    def ok(self, text):
        self.fine.append(text)

    def skip(self, text, blocks=False):
        self.skipped.append(text)
        if blocks:
            self.open.append(text)

    def note(self, text):
        self.notes.append(text)

    def finish(self, out=None):
        if self.failures:
            code, line = 1, f"RESULT fail: {self.failures[0]}" + (f" (and {len(self.failures) - 1} more)" if len(self.failures) > 1 else "")
        elif self.open:
            code, line = 2, f"RESULT not verified: {self.open[0]}" + (f" (and {len(self.open) - 1} more)" if len(self.open) > 1 else "")
        else:
            code, line = 0, "RESULT pass"
        print(f"== {self.title}")
        for text in self.notes:
            print(f"note  {text}")
        print(f"FINDINGS ({len(self.failures)} fail, {len(self.warnings)} warn)")
        for text in self.failures:
            print(f"  FAIL  {text}")
        for text in self.warnings:
            print(f"  warn  {text}")
        print(f"CHECKED AND FINE ({len(self.fine)})")
        for text in self.fine:
            print(f"  ok    {text}")
        print(f"NOT CHECKED ({len(self.skipped)})")
        for text in self.skipped:
            print(f"  --    {text}")
        if out:
            data = {"check": self.title, "made": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                    "result": line, "failures": self.failures, "warnings": self.warnings, "fine": self.fine,
                    "not_checked": self.skipped, "notes": self.notes}
            pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
            with open(out, "x", encoding="utf-8") as handle:
                handle.write(json.dumps(data, indent=2) + "\n")
            print(f"report written to {out}")
        print(line)
        return code


def blocked(text):
    print(f"blocked: {text}")
    return 2


def mask(text):
    """Hide the personal part of any email address in a line that is about to be printed."""
    def hide(match):
        local, sep, domain = re.split(r"(@|%40)", match.group(0), maxsplit=1, flags=re.I)
        return f"{local[:1]}***{sep}{domain}"
    return EMAIL.sub(hide, text)


def load_requests(path):
    """Return a list of {url, method, body, status} from a HAR file, a JSON list or a text file of addresses."""
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise ValueError("the file is empty")
    try:
        data = json.loads(text)
    except ValueError:
        found = [{"url": line.strip().split()[-1], "method": "GET", "body": "", "status": None}
                 for line in text.splitlines() if re.search(r"https?://", line)]
        if not found:
            raise ValueError("neither JSON nor a list of addresses")
        return found, "address list"
    if isinstance(data, dict) and isinstance(data.get("log"), dict):
        found = []
        for entry in data["log"].get("entries", []):
            request, answer = entry.get("request", {}), entry.get("response", {})
            post = request.get("postData") or {}
            body = post.get("text") or "&".join(f"{p.get('name', '')}={p.get('value', '')}" for p in post.get("params", []) or [])
            found.append({"url": request.get("url", ""), "method": request.get("method", "GET"), "body": body,
                          "status": answer.get("status")})
        return found, "HAR file"
    if isinstance(data, dict) and isinstance(data.get("requests"), list):
        data = data["requests"]
    if isinstance(data, list):
        found = []
        for item in data:
            if isinstance(item, str):
                item = {"url": item}
            if isinstance(item, dict) and item.get("url"):
                body = item.get("body", item.get("postData", ""))
                found.append({"url": item["url"], "method": item.get("method", "GET"),
                              "body": body if isinstance(body, str) else json.dumps(body), "status": item.get("status")})
        return found, "request list"
    raise ValueError("JSON, but neither a HAR file nor a list of requests")


def flatten(value, prefix=""):
    """Turn nested JSON into {dotted key: text}."""
    flat = {}
    if isinstance(value, dict):
        for key, inner in value.items():
            flat.update(flatten(inner, f"{prefix}{key}."))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            flat.update(flatten(inner, f"{prefix}{index}."))
    elif value is not None:
        flat[prefix[:-1]] = str(value).lower() if isinstance(value, bool) else str(value)
    return flat


def from_pairs(pairs, name_keys):
    """One event from key=value pairs: (name or None, properties)."""
    name, props = None, {}
    for key, value in pairs:
        if name is None and key in name_keys:
            name = value
        else:
            props[re.sub(r"^(epn?|up|upn)\.", "", key)] = value
    return name, props


def from_json(item, name_keys):
    """One event from a JSON object."""
    name = next((str(item[k]) for k in name_keys if isinstance(item.get(k), (str, int))), None)
    props = {}
    for key, value in item.items():
        if key in PROP_HOLDERS and isinstance(value, dict):
            props.update(flatten(value))
        elif not isinstance(value, (dict, list)) and value is not None:
            props[key] = str(value).lower() if isinstance(value, bool) else str(value)
    return name, props


def events_in(request, name_keys):
    """Every event one request carries, as (name, properties)."""
    query = urllib.parse.parse_qsl(urllib.parse.urlsplit(request["url"]).query, keep_blank_values=True)
    body = (request.get("body") or "").strip()
    found = []
    if body[:1] in ("{", "["):
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        items = data if isinstance(data, list) else None
        if isinstance(data, dict):
            items = next((data[k] for k in BATCH_KEYS if isinstance(data.get(k), list)), [data])
        for item in items or []:
            if isinstance(item, dict):
                name, props = from_json(item, name_keys)
                if name:
                    shared = dict(from_pairs(query, name_keys)[1])
                    shared.update(props)
                    found.append((name, shared))
    elif body:
        for line in body.splitlines():
            pairs = urllib.parse.parse_qsl(line.strip(), keep_blank_values=True)
            name, props = from_pairs(query + pairs, name_keys)
            if name:
                found.append((name, props))
    if not found:
        name, props = from_pairs(query, name_keys)
        if name:
            found.append((name, props))
    return found


def personal_in(url):
    """Reasons this address carries personal data, already masked."""
    reasons = []
    parts = urllib.parse.urlsplit(url)
    for match in EMAIL.finditer(parts.path + "?" + parts.query):
        reasons.append(f"an email address ({mask(match.group(0))})")
    for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=False):
        bare = re.sub(r"^(epn?|up|upn)\.", "", key)
        if PERSONAL_KEYS.match(bare) and not EMAIL.search(value):
            reasons.append(f"a parameter named '{key}'")
    return list(dict.fromkeys(reasons))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("evidence", help="a HAR file, a JSON list of requests, or a text file of request addresses")
    parser.add_argument("--expect", required=True, help="the expected events (JSON)")
    parser.add_argument("--out", help="also write the three lists as JSON to this new file")
    args = parser.parse_args()

    if args.out and pathlib.Path(args.out).exists():
        return blocked(f"{args.out} exists; reports are never overwritten, name a new file")
    try:
        expected = json.loads(pathlib.Path(args.expect).read_text(encoding="utf-8"))
        endpoint, wanted = expected["endpoint"], expected["events"]
        if not isinstance(endpoint, str) or len(endpoint) < 4 or not isinstance(wanted, list) or not wanted:
            raise ValueError("'endpoint' has to be part of an address and 'events' a list with at least one event")
        if not all(isinstance(e, dict) and e.get("name") for e in wanted):
            raise ValueError("every expected event needs a 'name'")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return blocked(f"expected file {args.expect} cannot be used: {exc}")
    try:
        requests, kind = load_requests(args.evidence)
    except (OSError, ValueError) as exc:
        return blocked(f"evidence file {args.evidence} cannot be used: {exc}")
    if not requests:
        return blocked(f"evidence file {args.evidence} holds no requests; capture the page again with the network panel recording")
    name_keys = expected.get("name_keys") or NAME_KEYS

    report = Report(f"tracking-check {args.evidence} ({kind}, {len(requests)} requests) against {args.expect}")
    hits = [r for r in requests if endpoint.lower() in r["url"].lower()]
    report.note(f"{len(hits)} of {len(requests)} captured requests go to '{endpoint}'")
    if not hits:
        report.fail(f"no captured request goes to '{endpoint}': the tag did not load, was blocked, or the capture started too late")
    sent = []
    for request in hits:
        for name, props in events_in(request, name_keys):
            sent.append((name, props, request))
    counts = {}
    for name, _, _ in sent:
        counts[name] = counts.get(name, 0) + 1

    for event in wanted:
        name, props = str(event["name"]), event.get("properties") or {}
        times = event.get("count", 1)
        matches = [(p, r) for n, p, r in sent if n == name]
        if not matches:
            if hits:
                seen = ", ".join(f"{n} x{c}" for n, c in sorted(counts.items())) or "no event name could be read from them"
                report.fail(f"event '{name}': no request carries it (events seen: {seen})")
            continue
        if times != "any" and len(matches) != times:
            word = "more" if len(matches) > times else "fewer"
            report.fail(f"event '{name}': sent {len(matches)} times, expected {times} ({word} than expected; a doubled event "
                        f"usually means the tag is installed twice or fires on click and again on success)")
        else:
            report.ok(f"event '{name}': sent {len(matches)} time{'s' if len(matches) != 1 else ''}")
        got, _ = matches[0]
        wrong = []
        for key, value in props.items():
            actual = got.get(key)
            if actual is None or actual == "":
                wrong.append(f"'{key}' is absent")
            elif str(value) != "*" and str(actual) != (str(value).lower() if isinstance(value, bool) else str(value)):
                wrong.append(f"'{key}' is '{mask(str(actual))[:40]}', expected '{value}'")
        if wrong:
            report.fail(f"event '{name}': properties differ: {'; '.join(wrong)}")
        elif props:
            report.ok(f"event '{name}': properties as expected ({', '.join(props)})")
        statuses = {r.get("status") for _, r in matches}
        refused = sorted(s for s in statuses if isinstance(s, int) and (s == 0 or s >= 400))
        if refused:
            report.fail(f"event '{name}': the request was answered with status {', '.join(str(s) for s in refused)} "
                        f"(0 means it never completed, often a blocker)")
        elif None in statuses:
            report.skip(f"event '{name}': the answer's status is not in the evidence")
        else:
            report.ok(f"event '{name}': the endpoint answered {', '.join(str(s) for s in sorted(statuses))}")

    extra = sorted(set(counts) - {str(e["name"]) for e in wanted})
    if extra:
        report.note(f"other events sent to the endpoint and not in the expected file: {', '.join(f'{n} x{counts[n]}' for n in extra)}")

    leaks = 0
    for request in hits:
        reasons = personal_in(request["url"])
        if reasons:
            leaks += 1
            report.fail(f"personal data in a request address: {' and '.join(reasons)} in {mask(request['url'])[:140]}")
        elif EMAIL.search(request.get("body") or ""):
            report.warn(f"an email address is in the body of a request to the endpoint: {mask(request['url'])[:100]}")
    if hits and not leaks:
        report.ok(f"no email address or personally named parameter in the {len(hits)} request addresses")

    report.skip("whether the events arrived in the analytics account: sent is not arrived; look in the tool's own live or debug view")
    report.skip("requests the capture did not record (other pages, other browsers, visitors with a blocker)")
    report.skip("whether consent was asked before these requests were sent")
    return report.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
