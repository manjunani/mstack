#!/usr/bin/env python3
"""A tiny local API for the api-check script test. Standard library only.

  api_server.py <port> <log file>

It answers on 127.0.0.1 only and writes one line per request to the log file, so the test can
prove which requests were really sent. Some routes break their contract on purpose.
"""
import argparse
import http.server
import json


def build(log_path):
    users = {1: {"id": 1, "name": "Ada", "email": "ada@example.com"}}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def answer(self, status, body=None, content_type="application/json", headers=None):
            raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
            self.send_response(status)
            if raw:
                self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)

        def handle_any(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"{self.command} {self.path} auth={'yes' if self.headers.get('Authorization') else 'no'} body={body.decode()}\n")
            path, _, query = self.path.partition("?")
            if path == "/users" and self.command == "GET":
                return self.answer(200, list(users.values()))
            if path == "/users" and self.command == "POST":
                data = json.loads(body or b"{}")
                if not isinstance(data.get("name"), str):
                    return self.answer(422, {"error": "name is required"})
                users[2] = {"id": 2, "name": data["name"], "email": data.get("email", "new@example.com")}
                return self.answer(201, users[2])
            if path.startswith("/users/"):
                key = path.rsplit("/", 1)[1]
                user = users.get(int(key)) if key.isdigit() else None
                if user is None:
                    return self.answer(404, {"error": "not found"})
                if self.command == "DELETE":
                    return self.answer(204)
                return self.answer(200, user)
            if path == "/search":
                return self.answer(200, {"query": query, "hits": []})
            if path == "/orders":          # contract: items is a list and total is required
                return self.answer(200, {"items": "none", "extra": True})
            if path == "/health":          # contract: 200 with a body; the server sends 204
                return self.answer(204)
            if path == "/report":          # contract: JSON; the server sends HTML
                return self.answer(200, b"<h1>report</h1>", "text/html")
            if path == "/old":             # contract: 200; the server redirects to another host
                return self.answer(302, headers={"Location": "http://example.com/moved"})
            if path == "/strict":          # contract forbids extra properties
                return self.answer(200, {"id": 1, "debug": "x"})
            return self.answer(404, {"error": "no such route"})

        do_GET = do_POST = do_DELETE = do_HEAD = do_PUT = do_PATCH = handle_any

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port", type=int)
    parser.add_argument("log")
    args = parser.parse_args()
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), build(args.log)).serve_forever()


if __name__ == "__main__":
    main()
