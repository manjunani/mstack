#!/usr/bin/env python3
"""A local web server for the mstack-web script tests, built on Python's http.server.

It listens on 127.0.0.1 only and serves the files of one folder, plus routes that a test defines:

  routes = {"/old": {"status": 301, "headers": {"Location": "/new.html"}},
            "/big.js": {"file": "big.js", "gzip": True, "headers": {"Cache-Control": "max-age=600"}},
            "/slow": {"body": "late", "delay": 0.3},
            "/nohead": {"body": "x", "no_head": True}}

Every request is appended to site["log"] (method, path, user agent), so a test can prove what was and
was not requested. Use start() from a test, or run this file to serve a folder by hand:

  fixture_server.py --root DIR [--port 0] [--routes routes.json] [--soft404] [--cert c.pem --key k.pem]
"""
import argparse
import gzip
import http.server
import json
import mimetypes
import pathlib
import ssl
import threading
import time
import urllib.parse


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "mstack-fixture/1"
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.answer()

    def do_HEAD(self):
        self.answer()

    def answer(self):
        site = self.server.site
        path = urllib.parse.urlsplit(self.path).path
        site["log"].append({"method": self.command, "path": self.path, "agent": self.headers.get("User-Agent", ""), "time": time.monotonic()})
        route = site["routes"].get(self.path) or site["routes"].get(path)
        status, headers, body = 200, dict(site.get("default_headers", {})), None
        if route is not None:
            if route.get("delay"):
                time.sleep(route["delay"])
            if route.get("no_head") and self.command == "HEAD":
                status, body = 405, b"HEAD is not accepted here\n"
            else:
                status = route.get("status", 200)
                if "file" in route:
                    body = (site["root"] / route["file"]).read_bytes()
                    headers.setdefault("Content-Type", mimetypes.guess_type(route["file"])[0] or "application/octet-stream")
                else:
                    body = route.get("body", "").encode("utf-8")
            if route.get("replace_headers"):
                headers = {}
            headers.update(route.get("headers", {}))
        else:
            target = (site["root"] / path.lstrip("/")).resolve()
            if target.is_dir():
                target = target / "index.html"
            if site["root"] in target.parents and target.is_file():
                body = target.read_bytes()
                headers.setdefault("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            elif site.get("soft404"):
                body = b"<html><head><title>Oops</title></head><body><p>We could not find that page, sorry.</p></body></html>"
                headers["Content-Type"] = "text/html"
            else:
                status, body = 404, b"<html><body><h1>404</h1><p>Nothing here.</p></body></html>"
                headers["Content-Type"] = "text/html"
        headers.setdefault("Content-Type", "text/html; charset=utf-8")
        if route and route.get("gzip") and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


class QuietServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # a client that hangs up (a refused certificate, a timeout) is part of the tests


def start(root, routes=None, port=0, soft404=False, default_headers=None, cert=None, key=None):
    """Start a server in a thread. Returns (site, base address); site["server"].shutdown() stops it."""
    site = {"root": pathlib.Path(root).resolve(), "routes": routes if routes is not None else {}, "log": [],
            "soft404": soft404, "default_headers": default_headers or {}}
    server = QuietServer(("127.0.0.1", port), Handler)
    server.site = site
    scheme = "http"
    if cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    site["server"] = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return site, f"{scheme}://127.0.0.1:{server.server_address[1]}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, required=True, help="folder to serve")
    parser.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: any free port)")
    parser.add_argument("--routes", type=pathlib.Path, help="JSON file of routes, in the form shown above")
    parser.add_argument("--soft404", action="store_true", help="answer 200 for pages that do not exist")
    parser.add_argument("--cert", help="certificate file, to serve https")
    parser.add_argument("--key", help="key file for --cert")
    args = parser.parse_args()
    routes = json.loads(args.routes.read_text(encoding="utf-8")) if args.routes else {}
    site, base = start(args.root, routes, args.port, args.soft404, cert=args.cert, key=args.key)
    print(f"serving {args.root} at {base} (Ctrl-C to stop)", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        site["server"].shutdown()


if __name__ == "__main__":
    main()
