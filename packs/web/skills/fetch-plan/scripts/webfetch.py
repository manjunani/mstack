#!/usr/bin/env python3
"""Shared fetch helper of the mstack-web scripts. The same file sits beside every script that fetches.

What it guarantees, for every request made through it:
  - one plain user agent that names the pack and the script, never a browser's
  - http and https only, and no address that carries a user name or password
  - redirects are never followed silently: the caller sees every hop
  - robots.txt is read with the pack's own token ("mstack-web"), longest rule wins
  - a pause between two requests to the same host, and a full stop when a host answers 429
    or 503 with Retry-After. Nothing here retries, rotates or disguises a request.

Run it directly to look at one address:

  webfetch.py URL            one GET, no redirects followed: status, timing and headers
  webfetch.py URL --robots   read the site's robots.txt and say whether URL may be fetched

Exit codes: 0 = answered (or allowed), 1 = not allowed by robots, 2 = no answer or bad address.
"""
import argparse
import http.client
import ipaddress
import pathlib
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

VERSION = "0.1"
PROJECT = "https://github.com/manjunani/mstack"
ROBOTS_TOKEN = "mstack-web"
REDIRECTS = (301, 302, 303, 307, 308)
PUBLIC_FLOOR = 1.0  # seconds between two requests to one host that is not on this machine or network


class BadURL(ValueError):
    """The address is one this pack does not fetch."""


def user_agent(tool):
    return f"mstack-web/{VERSION} ({tool}; +{PROJECT})"


def check_url(url):
    """Return the address without its fragment, or raise BadURL."""
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise BadURL(f"only http and https addresses are fetched, got: {url.strip() or '(empty)'}")
    if not parts.hostname:
        raise BadURL(f"no host in address: {url.strip()}")
    if parts.username or parts.password:
        raise BadURL("the address carries a user name or password; this pack does not log in to anything")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def host_of(url):
    return urllib.parse.urlsplit(url).netloc.lower()


def origin_of(url):
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def is_local(hostname):
    """True for this machine and private networks: the places a developer's own server runs."""
    name = (hostname or "").lower().strip("[]")
    if name == "localhost" or name.endswith((".localhost", ".test", ".local")):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


class Response:
    """One answer, or the reason there was none. `wire` is the bytes as sent, `body` after decompression."""

    def __init__(self, url, method):
        self.url, self.method = url, method
        self.status, self.headers = None, {}
        self.wire, self.body = b"", b""
        self.ttfb = self.total = None
        self.error = self.error_kind = None
        self.truncated = False

    def header(self, name, default=""):
        return self.headers.get(name.lower(), default)

    @property
    def location(self):
        target = self.header("location")
        if self.status in REDIRECTS and target:
            return urllib.parse.urldefrag(urllib.parse.urljoin(self.url, target.strip()))[0]
        return None

    @property
    def content_type(self):
        return self.header("content-type").split(";")[0].strip().lower()

    def text(self):
        match = re.search(r"charset=([\w.:-]+)", self.header("content-type"), re.I)
        if not match:
            match = re.search(rb"<meta[^>]+charset=[\"']?([\w.:-]+)", self.body[:4096], re.I)
        name = match.group(1) if match else "utf-8"
        name = name.decode("ascii", "replace") if isinstance(name, bytes) else name
        try:
            return self.body.decode(name, "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _kind(exc):
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "certificate"
    if isinstance(reason, ssl.SSLError):
        return "tls"
    if isinstance(reason, socket.gaierror):
        return "dns"
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(reason, (ConnectionRefusedError, ConnectionResetError)):
        return "refused"
    return "network"


def _decode(wire, encoding):
    encoding = encoding.strip().lower()
    try:
        if encoding in ("gzip", "x-gzip"):
            return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(wire)
        if encoding == "deflate":
            try:
                return zlib.decompressobj().decompress(wire)
            except zlib.error:
                return zlib.decompressobj(-zlib.MAX_WBITS).decompress(wire)
    except zlib.error:
        pass
    return wire


def fetch(url, tool, method="GET", timeout=15.0, max_bytes=3_000_000, gzip_ok=True, context=None, read=True):
    """Make exactly one request. Never raises for a network problem: look at .error and .status."""
    response = Response(url, method)
    headers = {"User-Agent": user_agent(tool), "Accept": "*/*", "Accept-Encoding": "gzip" if gzip_ok else "identity"}
    handlers = [_NoRedirect()]
    if url.lower().startswith("https:"):
        handlers.append(urllib.request.HTTPSHandler(context=context or ssl.create_default_context()))
    opener = urllib.request.build_opener(*handlers)
    begin = time.perf_counter()
    try:
        try:
            reply = opener.open(urllib.request.Request(url, method=method, headers=headers), timeout=timeout)
        except urllib.error.HTTPError as exc:
            reply = exc
        response.ttfb = time.perf_counter() - begin
        response.status = getattr(reply, "status", None) or reply.code
        response.headers = {key.lower(): value for key, value in reply.headers.items()}
        if read and method != "HEAD":
            wire = reply.read(max_bytes + 1)
            response.truncated = len(wire) > max_bytes
            response.wire = wire[:max_bytes]
            response.body = _decode(response.wire, response.header("content-encoding"))
        reply.close()
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        response.error_kind = _kind(exc)
        response.error = str(getattr(exc, "reason", exc)) or exc.__class__.__name__
    response.total = time.perf_counter() - begin
    return response


def follow(url, tool, max_hops=5, throttle=None, **options):
    """Fetch url and each redirect after it. Returns (hops, problem); problem is None or a sentence."""
    hops, seen = [], set()
    while True:
        seen.add(url)
        if throttle:
            throttle.wait(url)
        response = fetch(url, tool, **options)
        if throttle:
            throttle.observe(response)
        hops.append(response)
        target = response.location
        if response.error or not target:
            return hops, None
        if target in seen:
            return hops, f"redirect loop: {target} was already visited"
        if len(hops) > max_hops:
            return hops, f"more than {max_hops} redirects"
        try:
            url = check_url(target)
        except BadURL as exc:
            return hops, f"redirect to an address that is not fetched: {exc}"


class Robots:
    """Rules of one robots.txt for this pack's token. Longest matching rule wins; Allow wins a tie."""

    def __init__(self, text=""):
        self.sitemaps, self.delay, self.rules = [], None, []
        groups, agents, body_seen = {}, [], False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key, value = key.strip().lower(), value.strip()
            if key == "sitemap":
                self.sitemaps.append(value)
            elif key == "user-agent":
                if body_seen:
                    agents, body_seen = [], False
                agents.append(value.lower())
                groups.setdefault(value.lower(), {"rules": [], "delay": None})
            elif key in ("allow", "disallow", "crawl-delay") and agents:
                body_seen = True
                for agent in agents:
                    if key == "crawl-delay":
                        try:
                            groups[agent]["delay"] = float(value)
                        except ValueError:
                            pass
                    elif value:
                        groups[agent]["rules"].append((key == "allow", value))
        self.group_used = ROBOTS_TOKEN if ROBOTS_TOKEN in groups else ("*" if "*" in groups else None)
        if self.group_used:
            self.rules, self.delay = groups[self.group_used]["rules"], groups[self.group_used]["delay"]

    @staticmethod
    def _matches(pattern, path):
        anchored = pattern.endswith("$")
        parts = [re.escape(piece) for piece in pattern.rstrip("$").split("*")]
        return re.match(".*".join(parts) + ("$" if anchored else ""), path) is not None

    def allowed(self, url):
        parts = urllib.parse.urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if path == "/robots.txt":
            return True
        best = (-1, True)
        for allow, pattern in self.rules:
            if self._matches(pattern, path):
                rank = (len(pattern), allow)
                if rank > best:
                    best = rank
        return best[1]


class RobotsState:
    """What is known about one site's robots.txt. state: ok, none, denied or unreachable."""

    def __init__(self, state, detail, rules=None):
        self.state, self.detail, self.rules = state, detail, rules or Robots()

    def verdict(self, url):
        """'allowed', 'disallowed' or 'unknown' (robots.txt could not be read, so nothing is assumed)."""
        if self.state == "unreachable":
            return "unknown"
        if self.state == "denied":
            return "disallowed"
        return "allowed" if self.rules.allowed(url) else "disallowed"


def load_robots(origin, tool, timeout=15.0, throttle=None, context=None):
    """Read origin/robots.txt once. A missing file means no rules; an error means nothing is known."""
    hops, problem = follow(origin.rstrip("/") + "/robots.txt", tool, timeout=timeout, max_bytes=500_000,
                           throttle=throttle, context=context)
    last = hops[-1]
    if problem or last.error:
        return RobotsState("unreachable", problem or f"{last.error_kind}: {last.error}")
    if last.status == 200:
        return RobotsState("ok", f"read, {len(last.body)} bytes", Robots(last.text()))
    if last.status in (401, 403):
        return RobotsState("denied", f"robots.txt answered {last.status}; treated as a refusal of all fetching")
    if 400 <= last.status < 500 and last.status != 429:
        return RobotsState("none", f"robots.txt answered {last.status}; the site states no rules")
    return RobotsState("unreachable", f"robots.txt answered {last.status}")


class Throttle:
    """Spaces requests per host and remembers hosts that asked for a stop."""

    def __init__(self, delay=1.0):
        self.delay, self.per_host, self.last, self.stopped = max(0.0, delay), {}, {}, {}

    def delay_for(self, url):
        host = host_of(url)
        wanted = max(self.delay, self.per_host.get(host, 0.0))
        return wanted if is_local(urllib.parse.urlsplit(url).hostname) else max(wanted, PUBLIC_FLOOR)

    def raise_delay(self, url, seconds):
        if seconds:
            self.per_host[host_of(url)] = max(self.per_host.get(host_of(url), 0.0), float(seconds))

    def wait(self, url):
        host = host_of(url)
        if host in self.last:
            pause = self.last[host] + self.delay_for(url) - time.monotonic()
            if pause > 0:
                time.sleep(pause)
        self.last[host] = time.monotonic()

    def observe(self, response):
        self.last[host_of(response.url)] = time.monotonic()  # the pause counts from the end of the answer, not the start of the request
        if response.status == 429 or (response.status == 503 and response.header("retry-after")):
            wait = response.header("retry-after") or "no time given"
            self.stopped[host_of(response.url)] = f"the host answered {response.status} (Retry-After: {wait}); no more requests were sent to it"

    def stop_reason(self, url):
        return self.stopped.get(host_of(url))


def state_dir(name, root=None):
    """Return .mstack/<name>/ in the project, created, and listed in .mstack/.gitignore (fetched pages are not for commits)."""
    base = pathlib.Path(root or pathlib.Path.cwd()) / ".mstack"
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    ignore = base / ".gitignore"
    listed = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    if f"{name}/" not in listed:
        ignore.write_text("\n".join(listed + [f"{name}/"]) + "\n", encoding="utf-8")
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="the address to look at")
    parser.add_argument("--robots", action="store_true", help="read robots.txt and say whether the address may be fetched")
    parser.add_argument("--timeout", type=float, default=15.0, help="seconds to wait (default 15)")
    args = parser.parse_args()
    try:
        url = check_url(args.url)
    except BadURL as exc:
        print(f"blocked: {exc}")
        return 2
    if args.robots:
        state = load_robots(origin_of(url), "webfetch", args.timeout)
        verdict = state.verdict(url)
        print(f"robots.txt: {state.state} ({state.detail}); {url} is {verdict}")
        print("RESULT pass" if verdict == "allowed" else f"RESULT fail: {verdict}" if verdict == "disallowed" else "RESULT not verified: robots.txt could not be read")
        return {"allowed": 0, "disallowed": 1}.get(verdict, 2)
    response = fetch(url, "webfetch", timeout=args.timeout, max_bytes=200_000)
    if response.error:
        print(f"RESULT not verified: no answer from {url} ({response.error_kind}: {response.error})")
        return 2
    print(f"{response.status} {url}  first byte {response.ttfb * 1000:.0f} ms, {len(response.wire)} bytes")
    for key in sorted(response.headers):
        print(f"  {key}: {response.headers[key]}")
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
