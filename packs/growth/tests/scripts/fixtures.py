"""Throwaway pages and files for the mstack-growth script tests.

FILES maps a path to its text. {{GOOD}}, {{BAD}} are replaced with the address of the local server that serves
that folder. BINARY maps a path to bytes. Everything describes an invented product, "Tidepool"; no real site,
person or figure is used.
"""
import base64
import hashlib
import struct
import zlib


def png(width=4, height=4):
    """A small valid PNG, grey, made here so no image file has to be shipped."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _tlv(tag, content):
    size = len(content)
    head = bytes([size]) if size < 128 else bytes([0x80 | len(size.to_bytes((size.bit_length() + 7) // 8, "big"))]) + size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([tag]) + head + content


def rsa_public_key(bits):
    """Base64 of a DER public key with a modulus of the given size. The shape is right; it is not a real key pair."""
    seed, raw = b"mstack-growth-fixture", b""
    while len(raw) < bits // 8:
        seed = hashlib.sha256(seed).digest()
        raw += seed
    modulus = bytearray(raw[:bits // 8])
    modulus[0] |= 0x80
    modulus[-1] |= 0x01
    key = _tlv(0x30, _tlv(0x02, b"\x00" + bytes(modulus)) + _tlv(0x02, b"\x01\x00\x01"))
    algorithm = _tlv(0x30, _tlv(0x06, bytes.fromhex("2a864886f70d010101")) + b"\x05\x00")
    return base64.b64encode(_tlv(0x30, algorithm + _tlv(0x03, b"\x00" + key))).decode()


def good_page(path, title, description, h1, body, extra_head=""):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{{{{GOOD}}}}{path}">
<link rel="icon" href="/favicon.ico">
<link rel="stylesheet" href="/site.css">
{extra_head}</head>
<body>
<nav><a href="/">Home</a> <a href="/pricing/">Pricing</a> <a href="/about/">About</a> <a href="/contact/">Contact</a></nav>
<h1>{h1}</h1>
{body}
<footer><a href="/privacy/">Privacy</a> <a href="/terms/">Terms</a></footer>
</body>
</html>
"""


HOME_HEAD = """<meta property="og:title" content="Tidepool: shared tide tables for small harbours">
<meta property="og:description" content="One tide table that every boat owner in the harbour reads on a phone.">
<meta property="og:image" content="{{GOOD}}/og.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Organization", "name": "Tidepool", "url": "{{GOOD}}/", "logo": "{{GOOD}}/og.png"}
</script>
"""

FILES = {
    # ---- a small site with nothing wrong -------------------------------------------------------------------
    "site-good/index.html": good_page(
        "/", "Tidepool: shared tide tables for small harbours",
        "Tidepool gives a harbour master one tide table that every boat owner can read on a phone, with no account to set up.",
        "Tide tables your whole harbour can share",
        """<p>Tidepool keeps one tide table for the harbour and shows it to every boat owner on a phone.</p>
<a class="btn" href="/signup/">Start a harbour table</a>
<img src="/og.png" alt="A tide table shown on a phone">
<h2>How it works</h2>
<p>The harbour master enters the port once. Boat owners open a link and see today's high and low water.</p>
<h2>Who it is for</h2>
<p>Harbours with fewer than two hundred berths that still print the tide table on paper each week.</p>""", HOME_HEAD),
    "site-good/pricing/index.html": good_page(
        "/pricing/", "Tidepool pricing for harbours and marinas",
        "What Tidepool costs for a harbour: one plan per harbour, billed yearly, with every boat owner included at no extra charge.",
        "One plan per harbour",
        "<p>A harbour pays once a year. Boat owners never pay and never need an account to read the table.</p>\n"
        "<a class=\"btn\" href=\"/signup/\">Start a harbour table</a>"),
    "site-good/about/index.html": good_page(
        "/about/", "About the people who build Tidepool",
        "Tidepool is built by two former harbour staff who were tired of pinning a printed tide table to the office door each Monday.",
        "Built by former harbour staff",
        "<p>We worked the office of a small harbour for six seasons. In our own test on 3 March the shared table "
        "loaded in 312 ms on a mid-range phone.</p>"),
    "site-good/contact/index.html": good_page(
        "/contact/", "Contact the Tidepool team by email",
        "How to reach Tidepool: write to the address on this page and a person who has worked in a harbour office will answer.",
        "Write to us",
        "<p>Send a message to hello at the address of this site and we answer within two working days.</p>"),
    "site-good/privacy/index.html": good_page(
        "/privacy/", "Tidepool privacy notice in plain words",
        "What Tidepool stores about a harbour and its boat owners, how long it is kept, and how to have it removed on request.",
        "Privacy notice",
        "<p>We store the harbour's name, its port and the email address of the harbour master. Nothing about boat owners is stored.</p>"),
    "site-good/terms/index.html": good_page(
        "/terms/", "Tidepool terms of use for harbour accounts",
        "The terms a harbour agrees to when it opens a Tidepool account, including what happens to its data when the account closes.",
        "Terms of use",
        "<p>A harbour may close its account at any time. Tide predictions are a guide and never replace the official tables.</p>"),
    "site-good/signup/index.html": good_page(
        "/signup/", "Start a Tidepool table for your harbour",
        "Open a Tidepool account for a harbour: name the port, add the harbour master's email address and share the link you get.",
        "Start a harbour table",
        "<form action=\"/signup/\" method=\"post\"><label>Harbour name <input name=\"harbour\"></label> "
        "<button type=\"submit\">Create the table</button></form>\n<p>You get one link to share with every boat owner in the harbour.</p>"),
    "site-good/robots.txt": "User-agent: *\nAllow: /\nDisallow: /admin/\n\nSitemap: {{GOOD}}/sitemap.xml\n",
    "site-good/sitemap.xml": """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{{GOOD}}/</loc></url>
  <url><loc>{{GOOD}}/pricing/</loc></url>
  <url><loc>{{GOOD}}/about/</loc></url>
  <url><loc>{{GOOD}}/contact/</loc></url>
  <url><loc>{{GOOD}}/privacy/</loc></url>
  <url><loc>{{GOOD}}/terms/</loc></url>
  <url><loc>{{GOOD}}/signup/</loc></url>
</urlset>
""",
    "site-good/site.css": "body { font-family: sans-serif; max-width: 40rem; margin: 2rem auto; }\n.btn { padding: 0.5rem 1rem; }\n",

    # ---- a site with planted faults --------------------------------------------------------------------------
    "site-bad/index.html": """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Tidepool the tide table application for harbours, marinas, sailing clubs, rowing clubs and ferry operators everywhere</title>
</head>
<body>
<h2>Welcome</h2>
<h4>Lorem ipsum dolor sit amet</h4>
<p>Lorem ipsum dolor sit amet, placeholder words left in by mistake before the launch of this page.</p>
<img src="/missing-photo.jpg">
<a href="#">Sign up</a>
<a href="/gone/">Old page</a> <a href="/dup-a/">First copy</a> <a href="/dup-b/">Second copy</a> <a href="/hidden/">Hidden</a>
</body>
</html>
""",
    "site-bad/dup-a/index.html": """<!doctype html>
<html lang="en"><head><title>Tide tables for every harbour office</title>
<meta name="description" content="The same description is used on two different pages of this site, which a crawler will notice.">
</head><body><h1>First copy</h1><p>This page shares its title with another page.</p><a href="/">Home</a></body></html>
""",
    "site-bad/dup-b/index.html": """<!doctype html>
<html lang="en"><head><title>Tide tables for every harbour office</title>
<meta name="description" content="The same description is used on two different pages of this site, which a crawler will notice.">
</head><body><h1>Second copy</h1><h1>And a second top heading</h1><p>This page shares its title with another page.</p><a href="/">Home</a></body></html>
""",
    "site-bad/hidden/index.html": """<!doctype html>
<html lang="en"><head><title>A page that asks to stay out of search</title>
<meta name="robots" content="noindex, follow">
<meta name="description" content="This page is listed in the sitemap and at the same time tells search engines not to index it.">
</head><body><h1>Hidden page</h1><p>Listed in the sitemap and marked noindex at once.</p><a href="/">Home</a></body></html>
""",
    "site-bad/robots.txt": "User-agent: *\nAllow: /\nSitemap: {{BAD}}/sitemap.xml\n",
    "site-bad/sitemap.xml": """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{{BAD}}/</loc></url>
  <url><loc>{{BAD}}/hidden/</loc></url>
  <url><loc>{{BAD}}/nowhere/</loc></url>
  <url><loc>http://other-host.invalid/page</loc></url>
</urlset>
""",

    # ---- a site closed by robots.txt, and a page built by script ---------------------------------------------
    "site-closed/index.html": "<!doctype html><html lang=\"en\"><head><title>Closed for now, opening soon</title></head>"
                              "<body><h1>Closed</h1><p>Nothing to read here yet.</p></body></html>\n",
    "site-closed/robots.txt": "User-agent: *\nDisallow: /\n",
    "site-spa/index.html": "<!doctype html><html lang=\"en\"><head><title>Tidepool app shell for the harbour table</title>"
                           "<script src=\"/app.js\"></script></head><body><div id=\"app\"></div></body></html>\n",
    "site-spa/app.js": "document.getElementById('app').textContent = 'Tide tables your whole harbour can share';\n",

    # ---- structured data ------------------------------------------------------------------------------------
    "files/jsonld-good.html": """<!doctype html>
<html lang="en"><head><title>Tidepool harbour plan</title>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Tidepool harbour plan",
 "image": "https://tidepool.test/og.png", "description": "One shared tide table for a harbour.",
 "offers": {"@type": "Offer", "price": "240.00", "priceCurrency": "EUR"}}
</script>
<script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "BreadcrumbList", "itemListElement": [
     {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://tidepool.test/"},
     {"@type": "ListItem", "position": 2, "name": "Pricing"}]},
  {"@type": "FAQPage", "mainEntity": [
     {"@type": "Question", "name": "Do boat owners need an account?",
      "acceptedAnswer": {"@type": "Answer", "text": "No. They open a link."}}]}
]}
</script>
</head><body><h1>Tidepool harbour plan</h1>
<h2>Do boat owners need an account?</h2><p>No. They open a link.</p></body></html>
""",
    "files/jsonld-bad.html": """<!doctype html>
<html lang="en"><head><title>Broken markup</title>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Organization", "name": "Tidepool",}
</script>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "description": "A product with no name and nothing to buy."}
</script>
<script type="application/ld+json">
{"@type": "Organization", "name": "No context here"}
</script>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": "Is it free?"}]}
</script>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "Tidepool", "offers": {"@type": "Offer", "price": "0"},
 "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.9", "reviewCount": "1200"}}
</script>
</head><body><h1>Broken markup</h1><p>Nothing on this page shows a rating or a question to a visitor reading it.</p></body></html>
""",
    "files/jsonld-none.html": "<!doctype html><html lang=\"en\"><head><title>No markup at all</title></head><body><h1>Plain page</h1>"
                              "<p>This page carries no structured data of any kind, and that is a valid state for a page to be in "
                              "when nothing on it suits a schema type.</p></body></html>\n",
    "files/jsonld-unknown.html": """<!doctype html><html lang="en"><head><title>A type with no rules</title>
<script type="application/ld+json">{"@context": "https://schema.org", "@type": "Recipe", "name": "Harbour stew"}</script>
</head><body><h1>Harbour stew</h1><p>A recipe page, a type that the data file of this skill does not carry a property list for at all.</p></body></html>
""",
    "files/jsonld-microdata.html": "<!doctype html><html lang=\"en\"><head><title>Microdata only</title></head><body>"
                                   "<div itemscope itemtype=\"https://schema.org/Product\"><h1 itemprop=\"name\">Tidepool</h1>"
                                   "<p>This page marks up its product with microdata attributes in the body and has no JSON-LD "
                                   "block in the head or anywhere else.</p></div></body></html>\n",

    # ---- posts ----------------------------------------------------------------------------------------------
    "files/post-x-ok.md": "Tidepool is open today: one tide table your whole harbour can share, read on any phone. "
                          "https://tidepool.test/launch #harbours\n",
    "files/post-x-long.md": "Tidepool is open today. It gives a harbour master one tide table that every boat owner in the harbour can "
                            "read on a phone, with no account to set up and nothing to install, and the harbour pays once a year "
                            "while boat owners never pay at all, which is how we think it should work for small harbours. "
                            "https://tidepool.test/launch-day-announcement-with-a-very-long-address-that-counts-as-twenty-three\n",
    "files/post-x-marker.md": "Tidepool is open today. Harbours cut printing by 80% [unverified] in the first season. "
                              "https://tidepool.test/launch\n",
    "files/post-linkedin-tags.md": "Tidepool opens today for small harbours.\n\nOne shared tide table, read on a phone.\n\n"
                                   "#harbours #marinas #tides #sailing #boating #launch #startup\n",
    "files/post-blog-ok.md": """---
title: Tidepool opens to small harbours
description: What Tidepool does on its first day and who can use it.
date: 2026-11-22
image: cover.png
---

# Tidepool opens to small harbours

Today a harbour master can set up one shared tide table.

![The table on a phone](cover.png)

Read more at [the launch page](https://tidepool.test/launch).
""",
    "files/post-blog-bad.md": """---
title: Tidepool opens to small harbours
date: next Tuesday
---

Today a harbour master can set up one shared tide table. TODO add the screenshot.

![The table on a phone](missing-shot.png)
""",
    "files/post-remote-image.md": "Tidepool is open today.\n\n![The table](https://tidepool.test/og.png)\n",
    "files/post-empty.md": "---\ntitle: nothing below\n---\n\n",

    # ---- claims ---------------------------------------------------------------------------------------------
    "files/copy.md": """# Tidepool for harbours

Tidepool is the only tide table built for harbours with fewer than 200 berths.
The shared table loads 3x faster than the printed sheet takes to find.

- Set up in an afternoon
- Trusted by 14 harbours on the east coast

> "We stopped printing the table in our second week." Harbour master, Northquay

Boat owners open a link and read today's high and low water.
""",
    "files/copy-plain.md": "# Tidepool for harbours\n\nBoat owners open a link and read the high and low water for the day.\n"
                           "The harbour master enters the port once.\n",
    "files/evidence/berths.md": "Survey of products, November: none of the other tide table products lists a plan for harbours "
                                "under 200 berths.\n",
    "files/evidence/timing.md": "Timing test, 3 March. Finding today's line on the printed sheet: median 19 seconds.\n"
                                "Opening the shared table on a phone: median 6 seconds. Ratio 3.2 to 1.\n",
    "files/evidence/northquay.md": "Email from the harbour master at Northquay, 9 October: \"We stopped printing the table in our "
                                   "second week.\" Permission to quote given in the same email.\n",
    "files/sources-ok.json": """{"sources": [
  {"match": "the only tide table built for harbours with fewer than 200 berths", "evidence": "evidence/berths.md",
   "quote": "none of the other tide table products lists a plan for harbours under 200 berths"},
  {"match": "3x faster than the printed sheet", "evidence": "evidence/timing.md", "quote": "Ratio 3.2 to 1"},
  {"match": "Trusted by 14 harbours", "evidence": "evidence/accounts.png", "attested_by": "the founder, 2026-11-20"},
  {"match": "We stopped printing the table in our second week", "evidence": "evidence/northquay.md",
   "quote": "We stopped printing the table in our second week", "permission": "harbour master at Northquay, by email, 9 October"}
]}
""",
    "files/sources-gaps.json": """{"sources": [
  {"match": "3x faster than the printed sheet", "evidence": "evidence/timing.md", "quote": "Ratio 9 to 1"},
  {"match": "Trusted by 14 harbours", "evidence": "evidence/no-such-file.png", "attested_by": "the founder"},
  {"match": "We stopped printing the table in our second week", "evidence": "evidence/northquay.md",
   "quote": "We stopped printing the table in our second week"}
]}
""",
    "files/sources-web.json": """{"sources": [
  {"match": "the only tide table built for harbours with fewer than 200 berths", "status": "not a claim",
   "reason": "test entry: this sentence is set aside so the web entry below decides the result"},
  {"match": "3x faster than the printed sheet", "evidence": "{{GOOD}}/about/", "quote": "loaded in 312 ms on a mid-range phone"},
  {"match": "Trusted by 14 harbours", "evidence": "evidence/accounts.png", "attested_by": "the founder, 2026-11-20"},
  {"match": "We stopped printing the table in our second week", "evidence": "evidence/northquay.md",
   "quote": "We stopped printing the table in our second week", "permission": "harbour master at Northquay, by email, 9 October"}
]}
""",

    # ---- first screen ---------------------------------------------------------------------------------------
    "files/landing-vague.html": """<!doctype html>
<html lang="en"><head><title>Tidepool: shared tide tables for small harbours</title>
<meta name="description" content="One tide table that every boat owner in the harbour reads on a phone.">
</head><body>
<h1>Welcome to something wonderful</h1>
<p>We are thrilled you stopped by and cannot wait to show you around.</p>
<a class="btn" href="#">Get started</a>
</body></html>
""",
    "files/landing-button.html": """<!doctype html>
<html lang="en"><head><title>Tidepool: shared tide tables for small harbours</title>
<meta name="description" content="One tide table that every boat owner in the harbour reads on a phone.">
<script src="app.js" defer></script>
</head><body>
<h1>Tide tables your whole harbour can share</h1>
<p>Tidepool keeps one tide table for the harbour and shows it to every boat owner on a phone.</p>
<button id="start">Start a harbour table</button>
</body></html>
""",

    # ---- tracking -------------------------------------------------------------------------------------------
    "files/expect.json": """{"endpoint": "stats.tidepool.test/collect",
 "events": [
   {"name": "page_view", "count": "any"},
   {"name": "sign_up", "properties": {"plan": "harbour", "method": "*"}, "count": 1}
 ]}
""",
    "files/capture-good.har": """{"log": {"version": "1.2", "entries": [
  {"request": {"method": "GET", "url": "https://tidepool.test/signup/"}, "response": {"status": 200}},
  {"request": {"method": "POST", "url": "https://stats.tidepool.test/collect?v=2&en=page_view&dl=%2Fsignup%2F"}, "response": {"status": 204}},
  {"request": {"method": "POST", "url": "https://stats.tidepool.test/collect?v=2&en=sign_up&ep.plan=harbour&ep.method=email_link"}, "response": {"status": 204}}
]}}
""",
    "files/capture-double.har": """{"log": {"version": "1.2", "entries": [
  {"request": {"method": "POST", "url": "https://stats.tidepool.test/collect?v=2&en=page_view"}, "response": {"status": 204}},
  {"request": {"method": "POST", "url": "https://stats.tidepool.test/collect?v=2&en=sign_up&ep.plan=harbour&ep.method=email_link"}, "response": {"status": 204}},
  {"request": {"method": "POST", "url": "https://stats.tidepool.test/collect?v=2&en=sign_up&ep.plan=harbour&ep.method=email_link"}, "response": {"status": 204}}
]}}
""",
    "files/capture-leak.har": """{"log": {"version": "1.2", "entries": [
  {"request": {"method": "POST", "url": "https://stats.tidepool.test/collect?v=2&en=page_view"}, "response": {"status": 204}},
  {"request": {"method": "POST", "url": "https://stats.tidepool.test/collect?v=2&en=sign_up&ep.plan=free&ep.method=email_link&ep.user=mina.okafor%40northquay.test"}, "response": {"status": 204}}
]}}
""",
    "files/capture-other.har": """{"log": {"version": "1.2", "entries": [
  {"request": {"method": "GET", "url": "https://tidepool.test/signup/"}, "response": {"status": 200}},
  {"request": {"method": "GET", "url": "https://tidepool.test/site.css"}, "response": {"status": 200}}
]}}
""",
    "files/capture-blocked.har": """{"log": {"version": "1.2", "entries": [
  {"request": {"method": "POST", "url": "https://stats.tidepool.test/collect?v=2&en=page_view"}, "response": {"status": 204}},
  {"request": {"method": "POST", "url": "https://stats.tidepool.test/collect?v=2&en=sign_up&ep.plan=harbour&ep.method=email_link"}, "response": {"status": 0}}
]}}
""",
    "files/capture-list.json": """[
  {"url": "https://stats.tidepool.test/collect", "method": "POST", "status": 200,
   "body": "{\\"events\\": [{\\"event\\": \\"page_view\\"}, {\\"event\\": \\"sign_up\\", \\"properties\\": {\\"plan\\": \\"harbour\\", \\"method\\": \\"email_link\\"}}]}"}
]
""",
    "files/capture-urls.txt": "https://stats.tidepool.test/collect?en=page_view\n"
                              "https://stats.tidepool.test/collect?en=sign_up&ep.plan=harbour&ep.method=email_link\n",
    "files/capture-empty.har": "{\"log\": {\"version\": \"1.2\", \"entries\": []}}\n",

    # ---- store listing --------------------------------------------------------------------------------------
    "files/listing-ok.json": """{"store": "apple",
 "name": "Tidepool: Harbour Tides",
 "subtitle": "One table for the harbour",
 "promotional_text": "Share one tide table with every boat owner in the harbour.",
 "description": "Tidepool keeps one tide table for the harbour. Boat owners open a link and read the high and low water for today. The harbour master enters the port once.",
 "keywords": "tide,harbour,marina,boat,sailing,mooring,berth",
 "screenshots": ["shots/one.png", "shots/two.png"]}
""",
    "files/listing-bad.json": """{"store": "apple",
 "name": "Tidepool: The Best Harbour Tide Table App",
 "subtitle": "The #1 tide app",
 "description": "Tidepool is trusted by 10,000 harbours and is faster than any other tide app. TODO write the rest.",
 "keywords": "tide, tides, harbour, tide, marina, boat, sailing, mooring, berth, anchorage, slipway, pontoon, quay, jetty, breakwater, lighthouse",
 "screenshots": ["shots/one.png", "shots/not-there.png"]}
""",
    "files/listing-google.json": """{"store": "google",
 "name": "Tidepool: Harbour Tides",
 "short_description": "One tide table for the whole harbour.",
 "description": "Tidepool keeps one tide table for the harbour. Boat owners open a link and read the high and low water for today.",
 "screenshots": ["shots/one.png"]}
""",
    "files/listing-claims.json": """{"store": "apple",
 "name": "Tidepool: Harbour Tides",
 "subtitle": "One table for the harbour",
 "description": "Tidepool is the only tide table built for harbours with fewer than 200 berths.",
 "keywords": "tide,harbour,marina",
 "screenshots": ["shots/one.png"]}
""",
    "files/listing-nostore.json": "{\"store\": \"amazon\", \"name\": \"Tidepool\"}\n",

    # ---- page compare ---------------------------------------------------------------------------------------
    "files/theirs.html": """<!doctype html>
<html lang="en"><head><title>Quayline tide boards for marinas</title>
<meta name="description" content="Quayline puts a tide board on a screen in the marina office.">
<script type="application/ld+json">{"@context": "https://schema.org", "@type": "Organization", "name": "Quayline"}</script>
</head><body>
<h1>A tide board for the marina office</h1>
<p>Quayline shows the next four tides on a wall screen so that visiting crews can plan their departure without asking at the desk.</p>
<h2>Hardware</h2><p>The screen and its small computer arrive ready to hang.</p>
<img src="board.jpg" alt="The board on a wall"><img src="crew.jpg">
<a class="button" href="/order">Order a board</a> <button type="button">Watch the film</button>
</body></html>
""",
    "files/copied.html": """<!doctype html>
<html lang="en"><head><title>Tidepool tide boards</title></head><body>
<h1>Tide boards from Tidepool</h1>
<p>Quayline shows the next four tides on a wall screen so that visiting crews can plan their departure without asking at the desk.</p>
<p>The screen and its small computer arrive ready to hang.</p>
<a class="btn" href="/signup/">Start a harbour table</a>
</body></html>
""",

    # ---- mail records ---------------------------------------------------------------------------------------
    "files/records-good.txt": """; pasted from the DNS panel
mail.tidepool.test.        300 IN TXT "v=spf1 include:_spf.mailer.test ip4:203.0.113.24 ~all"
_dmarc.mail.tidepool.test. 300 IN TXT "v=DMARC1; p=reject; rua=mailto:dmarc@tidepool.test; adkim=s"
s1._domainkey.mail.tidepool.test. 300 IN TXT "v=DKIM1; k=rsa; p=%(key2048a)s" "%(key2048b)s"
""" % {"key2048a": rsa_public_key(2048)[:200], "key2048b": rsa_public_key(2048)[200:]},
    "files/records-open.txt": """mail.tidepool.test TXT "v=spf1 ip4:10.0.0.0/4 mx +all"
_dmarc TXT "v=DMARC1; p=none"
s1._domainkey TXT "v=DKIM1; k=rsa; p=%s"
""" % rsa_public_key(512),
    "files/records-monitor.txt": """v=spf1 include:_spf.mailer.test -all
v=DMARC1; p=none; rua=mailto:dmarc@tidepool.test
""",
    "files/records-nodmarc.txt": "mail.tidepool.test. 300 IN TXT \"v=spf1 include:_spf.mailer.test -all\"\n"
                                 "mail.tidepool.test. 300 IN TXT \"some-site-verification=abc123\"\n",
    "files/records-broken.txt": """mail.tidepool.test TXT "v=spf1 include:_spf.mailer.test -all"
mail.tidepool.test TXT "v=spf1 ip4:203.0.113.24 -all"
_dmarc TXT "v=DMARC1; p=rejected; pct=150; rua=dmarc@tidepool.test"
s1._domainkey TXT "v=DKIM1; k=rsa; p="
""",
    "files/records-junk.txt": "nothing in this file is a DNS record\n",
}

BINARY = {
    "site-good/favicon.ico": png(2, 2),
    "site-good/og.png": png(8, 8),
    "files/cover.png": png(),
    "files/shots/one.png": png(),
    "files/shots/two.png": png(),
    "files/evidence/accounts.png": png(),
}
