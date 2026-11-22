"""A tiny web server on 127.0.0.1 for the deploy-check and rollback script tests.

It serves the version found in a text file, so a test can "deploy" or "roll back" by rewriting that file.
  /health   200, body {"version": "<text of the file>"}, header X-Version
  /slow     200 after 0.4 seconds
  /broken   500
  /empty    200 with no body
  /moved    302 to /health
"""
import http.server
import json
import pathlib
import threading
import time


def start(version_file):
    version_file = pathlib.Path(version_file)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            version = version_file.read_text(encoding="utf-8").strip()
            status, body, extra = 200, json.dumps({"ok": True, "version": version}).encode(), {"X-Version": version}
            if self.path == "/slow":
                time.sleep(0.4)
            elif self.path == "/broken":
                status, body = 500, b'{"ok": false}'
            elif self.path == "/empty":
                body = b""
            elif self.path == "/moved":
                status, body, extra = 302, b"", {"Location": "/health"}
            elif self.path != "/health":
                status, body = 404, b"not found"
            self.send_response(status)
            for name, value in extra.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
