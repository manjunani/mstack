#!/usr/bin/env python3
"""Read one HTML page and print the facts the mstack-growth checks rest on.

  pagefacts.py <file-or-url>           title, headings, links, images, scripts and JSON-LD as JSON
  pagefacts.py <file-or-url> --text    only the visible text

Use it to look at the line that proves a finding before the finding is reported.
A URL is fetched once with a named user agent. Redirects are followed only while they stay on the same site.
The page is read as sent. Scripts are not run, so content a browser adds later is not seen.

Exit codes: 0 = page read, 2 = not read (missing file, fetch error, placeholder host, not HTML).
The same file ships inside several mstack-growth skills; the copies are identical.
"""
import argparse
import datetime
import html.parser
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

AGENT_NAME = "mstack-growth-check"
AGENT = AGENT_NAME + "/0.1 (run by the site owner; python-urllib)"
PLACEHOLDER_HOSTS = {"example.com", "example.org", "example.net", "yourdomain.com", "yoursite.com", "mysite.com", "domain.com"}
PLACEHOLDER_ENDS = (".example", ".invalid")
REDIRECTS = (301, 302, 303, 307, 308)
SKIPPED = {"style", "noscript", "template"}
BLOCKS = {"p", "div", "section", "article", "header", "footer", "main", "nav", "ul", "ol", "li", "table", "form",
          "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "figure", "aside", "pre", "hr"}
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
ACTION_CLASS = re.compile(r"(^|[\s_-])(btn|button|cta)([\s_-]|$)", re.I)
ACTION_TEXT = re.compile(r"^(sign ?up|get started|start|try|download|install|join|register|subscribe|buy|order|book|"
                         r"request|create|add to|get|upgrade|apply|donate|contact sales|talk to)\b", re.I)
STOP = set("""a an and are as at be but by can do for from get has have how in into is it its just more my no not of on
or our out so than that the their them then there these they this to up us was we what when which who why will with
you your all any new now one also about over only very""".split())


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
        """Something not checked. blocks=True means a pass cannot be claimed without it."""
        self.skipped.append(text)
        if blocks:
            self.open.append(text)

    def note(self, text):
        self.notes.append(text)

    def result(self, nothing=None):
        if self.failures:
            more = f" (and {len(self.failures) - 1} more)" if len(self.failures) > 1 else ""
            return 1, f"RESULT fail: {self.failures[0]}{more}"
        if self.open:
            more = f" (and {len(self.open) - 1} more)" if len(self.open) > 1 else ""
            return 2, f"RESULT not verified: {self.open[0]}{more}"
        return 0, f"RESULT pass: {nothing}" if nothing else "RESULT pass"

    def finish(self, out=None, nothing=None):
        code, line = self.result(nothing)
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


def out_refused(out):
    """A report file is never overwritten."""
    return bool(out) and pathlib.Path(out).exists()


def load_data(path, key=None):
    """Read a dated references file. Returns (entries, lines to print about how far to trust them)."""
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    entries = data[key] if key else data
    dated = [e for e in entries.values() if isinstance(e, dict) and "verified" in e]
    loose = sum(1 for e in dated if not e.get("verified"))
    checked = sorted({e.get("checked", "?") for e in dated})
    lines = []
    if loose:
        lines.append(f"{loose} of {len(dated)} values in {pathlib.Path(path).name} are unverified (written from memory, "
                     f"dated {', '.join(checked)}): check them against the source named in the file before relying on them")
    return entries, lines


class SourceError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def url_problem(url):
    """Why this URL will not be fetched, or None."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return f"'{url}' is not an http or https address"
    host = parts.hostname.lower()
    bare = host[4:] if host.startswith("www.") else host
    if bare in PLACEHOLDER_HOSTS or host.endswith(PLACEHOLDER_ENDS):
        return f"'{host}' is a placeholder host; give the real address"
    return None


def site_key(url):
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return (host[4:] if host.startswith("www.") else host, parts.port or (443 if parts.scheme == "https" else 80))


def same_site(a, b):
    return site_key(a) == site_key(b)


def fetch(url, timeout=15, limit=3_000_000, method="GET", hops=5):
    """One request, redirects followed by hand and only on the same site.

    Returns a dict: status (None on error), headers, body, final, chain [(status, url)], error, offsite, cut.
    """
    opener = urllib.request.build_opener(_NoRedirect)
    chain, current = [], url
    result = {"url": url, "final": url, "status": None, "headers": {}, "body": b"", "chain": chain,
              "error": None, "offsite": None, "cut": False}
    for _ in range(hops + 1):
        request = urllib.request.Request(current, method=method, headers={"User-Agent": AGENT, "Accept": "*/*"})
        try:
            with opener.open(request, timeout=timeout) as answer:
                status, headers = answer.status, {k.lower(): v for k, v in answer.headers.items()}
                body = b"" if method == "HEAD" else answer.read(limit + 1)
        except urllib.error.HTTPError as exc:
            status, headers = exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}
            try:
                body = b"" if method == "HEAD" else exc.read(limit + 1)
            except OSError:
                body = b""
        except (urllib.error.URLError, OSError, ValueError) as exc:
            result.update(final=current, error=str(getattr(exc, "reason", exc)) or exc.__class__.__name__)
            return result
        chain.append((status, current))
        if status in REDIRECTS and headers.get("location"):
            target = urllib.parse.urljoin(current, headers["location"])
            if not same_site(target, url):
                result.update(final=current, status=status, headers=headers, offsite=target)
                return result
            current = target
            continue
        result.update(final=current, status=status, headers=headers, body=body[:limit], cut=len(body) > limit)
        return result
    result.update(final=current, error=f"more than {hops} redirects")
    return result


def decode(body, headers=None):
    charset = None
    match = re.search(r"charset=([\w-]+)", (headers or {}).get("content-type", ""), re.I)
    if match:
        charset = match.group(1)
    else:
        match = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
        if match:
            charset = match.group(1).decode("ascii", "replace")
    try:
        return body.decode(charset or "utf-8", "replace")
    except LookupError:
        return body.decode("utf-8", "replace")


def looks_like_html(text):
    return bool(re.search(r"<(!doctype html|html|head|body|title|h1|p|div)\b", text[:200_000], re.I))


def squash(text):
    return " ".join(text.split())


def words(text):
    return re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", text)


def content_words(text):
    """Lower-case words that carry meaning, with a plain plural 's' removed."""
    found = set()
    for word in words(text.lower()):
        if len(word) < 3 or word in STOP or word.isdigit():
            continue
        found.add(word[:-1] if word.endswith("s") and not word.endswith("ss") and len(word) > 3 else word)
    return found


class Page(html.parser.HTMLParser):
    """Collects what the checks need from one HTML document, in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang, self.base, self.titles = None, None, []
        self.meta, self.links, self.headings, self.paragraphs = [], [], [], []
        self.anchors, self.buttons, self.images, self.scripts, self.jsonld, self.forms = [], [], [], [], [], []
        self.microdata = self.rdfa = 0
        self._text, self._open, self._order = [], {}, 0
        self._skip = self._svg = 0
        self._in_head, self._form, self._ld, self._script = False, None, None, None

    def _next(self):
        self._order += 1
        return self._order

    def _begin(self, key, record):
        self._end(key)
        record["order"] = self._next()
        self._open[key] = (record, [])
        return record

    def _end(self, key):
        if key in self._open:
            record, parts = self._open.pop(key)
            record["text"] = squash("".join(parts))

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        if "itemscope" in a:
            self.microdata += 1
        if "typeof" in a or "vocab" in a:
            self.rdfa += 1
        if tag in BLOCKS:
            self._end("p")
        if tag == "html":
            self.lang = a.get("lang") or self.lang
        elif tag == "head":
            self._in_head = True
        elif tag == "body":
            self._in_head = False
        elif tag == "base":
            self.base = a.get("href") or self.base
        elif tag == "svg":
            self._svg += 1
        elif tag == "title" and not self._svg:
            self.titles.append(self._begin("title", {}))
        elif tag == "meta":
            self.meta.append(a)
        elif tag == "link":
            self.links.append({"rel": a.get("rel", "").lower().split(), "href": a.get("href", ""),
                               "media": a.get("media", ""), "as": a.get("as", ""), "in_head": self._in_head})
        elif tag == "script":
            kind = a.get("type", "").lower()
            if "ld+json" in kind:
                self._ld = []
            else:
                self._script = {"src": a.get("src", ""), "async": "async" in a, "defer": "defer" in a,
                                "module": kind == "module", "type": kind, "inline": 0, "in_head": self._in_head}
                self.scripts.append(self._script)
                self._skip += 1
        elif tag in SKIPPED:
            self._skip += 1
        elif self._skip:
            return
        elif tag in HEADINGS:
            self.headings.append(self._begin("h", {"level": HEADINGS[tag]}))
        elif tag == "p":
            self.paragraphs.append(self._begin("p", {}))
        elif tag == "a":
            self.anchors.append(self._begin("a", {"href": a.get("href"), "rel": a.get("rel", "").lower().split(),
                                                  "class": a.get("class", ""), "role": a.get("role", ""), "alt": ""}))
        elif tag == "button":
            self.buttons.append(self._begin("b", {"type": a.get("type", "submit").lower(), "class": a.get("class", ""),
                                                  "formaction": a.get("formaction"), "form": self._form,
                                                  "handler": "onclick" in a}))
        elif tag == "input" and a.get("type", "").lower() in ("submit", "button", "image"):
            self.buttons.append({"type": a.get("type", "").lower(), "class": a.get("class", ""), "order": self._next(),
                                 "formaction": a.get("formaction"), "form": self._form, "handler": "onclick" in a,
                                 "text": squash(a.get("value", "") or a.get("alt", ""))})
        elif tag == "img":
            image = {"src": a.get("src", "") or a.get("data-src", ""), "alt": a.get("alt") if "alt" in a else None,
                     "loading": a.get("loading", "").lower(), "order": self._next()}
            self.images.append(image)
            if "a" in self._open and image["alt"]:
                self._open["a"][0]["alt"] = squash(self._open["a"][0]["alt"] + " " + image["alt"])
        elif tag == "form":
            self._form = a.get("action", "")
            self.forms.append({"action": self._form, "method": a.get("method", "get").lower()})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ("meta", "link", "img", "input", "base", "br", "hr"):
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "script":
            if self._ld is not None:
                self.jsonld.append("".join(self._ld))
                self._ld = None
            else:
                self._skip = max(0, self._skip - 1)
                self._script = None
        elif tag in SKIPPED:
            self._skip = max(0, self._skip - 1)
        elif tag == "head":
            self._in_head = False
        elif tag == "svg":
            self._svg = max(0, self._svg - 1)
        elif tag == "title":
            self._end("title")
        elif tag in HEADINGS:
            self._end("h")
        elif tag == "p":
            self._end("p")
        elif tag == "a":
            self._end("a")
        elif tag == "button":
            self._end("b")
        elif tag == "form":
            self._form = None

    def handle_data(self, data):
        if self._ld is not None:
            self._ld.append(data)
            return
        if self._skip:
            if self._script is not None:
                self._script["inline"] += len(data)
            return
        if "title" in self._open:
            self._open["title"][1].append(data)
            return
        if self._svg:
            return
        self._text.append(data)
        for key in ("h", "p", "a", "b"):
            if key in self._open:
                self._open[key][1].append(data)

    def close(self):
        super().close()
        for key in list(self._open):
            self._end(key)

    @property
    def title(self):
        return self.titles[0]["text"] if self.titles else None

    @property
    def text(self):
        return squash(" ".join(self._text))

    def meta_all(self, name):
        name = name.lower()
        return [m.get("content", "").strip() for m in self.meta
                if name in (m.get("name", "").lower(), m.get("property", "").lower())]

    def meta_one(self, name):
        found = self.meta_all(name)
        return found[0] if found else None

    def rel(self, name):
        return [link for link in self.links if name in link["rel"]]

    def built_by_script(self):
        """Few words in the HTML and scripts present: the visible page is probably made in the browser."""
        return len(words(self.text)) < 25 and bool(self.scripts)

    def actions(self):
        """Calls to action, in order: every button, plus links styled as a button or starting with an action verb."""
        found = []
        for button in self.buttons:
            if button["type"] in ("reset",):
                continue
            target = button.get("formaction") or button.get("form")
            found.append({"text": button["text"], "target": target, "kind": "button", "order": button["order"],
                          "handler": button.get("handler", False)})
        for anchor in self.anchors:
            label = anchor["text"] or anchor["alt"]
            if anchor["role"].lower() == "button" or ACTION_CLASS.search(anchor["class"]) or ACTION_TEXT.search(label):
                found.append({"text": label, "target": anchor["href"], "kind": "link", "order": anchor["order"],
                              "handler": False})
        return sorted(found, key=lambda item: item["order"])

    def facts(self):
        return {"lang": self.lang, "title": self.title, "title_count": len(self.titles),
                "description": self.meta_one("description"), "robots": self.meta_all("robots"),
                "canonical": [link["href"] for link in self.rel("canonical")],
                "headings": [[h["level"], h["text"]] for h in self.headings],
                "first_paragraph": next((p["text"] for p in self.paragraphs if p["text"]), None),
                "links": [[a["href"], a["text"] or a["alt"]] for a in self.anchors],
                "actions": [[c["kind"], c["text"], c["target"]] for c in self.actions()],
                "images": [[i["src"], i["alt"]] for i in self.images],
                "scripts": [s["src"] or f"inline ({s['inline']} characters)" for s in self.scripts],
                "stylesheets": [link["href"] for link in self.rel("stylesheet")],
                "jsonld_blocks": len(self.jsonld), "microdata_items": self.microdata, "word_count": len(words(self.text)),
                "open_graph": {m.get("property"): m.get("content", "") for m in self.meta
                               if m.get("property", "").lower().startswith(("og:", "twitter:"))
                               or m.get("name", "").lower().startswith("twitter:")}}


def parse(text):
    page = Page()
    page.feed(text)
    page.close()
    return page


def read_source(source, timeout=15):
    """Return (html text, info). source is a file path or an http(s) address. Raises SourceError."""
    if re.match(r"^https?://", source, re.I):
        problem = url_problem(source)
        if problem:
            raise SourceError(problem)
        got = fetch(source, timeout=timeout)
        if got["error"]:
            raise SourceError(f"{source} could not be fetched: {got['error']}")
        if got["offsite"]:
            raise SourceError(f"{source} redirects to another site ({got['offsite']}); give that address if it is the right one")
        if got["status"] != 200:
            raise SourceError(f"{source} answered with status {got['status']}")
        text = decode(got["body"], got["headers"])
        info = {"kind": "url", "source": source, "final": got["final"], "bytes": len(got["body"]), "headers": got["headers"],
                "body": got["body"], "cut": got["cut"]}
    else:
        path = pathlib.Path(source)
        if not path.is_file():
            raise SourceError(f"{source} is not a file")
        body = path.read_bytes()
        text = decode(body)
        info = {"kind": "file", "source": str(path), "final": None, "bytes": len(body), "headers": {}, "body": body, "cut": False}
    if not text.strip():
        raise SourceError(f"{source} is empty")
    if not looks_like_html(text):
        raise SourceError(f"{source} does not look like HTML")
    return text, info


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="an HTML file, or an http(s) address")
    parser.add_argument("--text", action="store_true", help="print the visible text and nothing else")
    parser.add_argument("--timeout", type=int, default=15, help="seconds allowed for a fetch (default 15)")
    args = parser.parse_args()
    try:
        text, info = read_source(args.source, args.timeout)
    except SourceError as exc:
        return blocked(str(exc))
    page = parse(text)
    if args.text:
        print(page.text)
    else:
        facts = page.facts()
        facts["source"], facts["bytes"] = info["final"] or info["source"], info["bytes"]
        print(json.dumps(facts, indent=2, ensure_ascii=False))
        if page.built_by_script():
            print("note: very little text in the HTML and scripts are present; a browser may show more than this",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
