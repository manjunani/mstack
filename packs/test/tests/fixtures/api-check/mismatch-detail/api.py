"""Small test server for the berth booking API. Run: python3 api.py (serves http://localhost:8000)."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

BERTHS = [
    {"id": 1, "pier": "North", "length_m": 12.5},
    {"id": 2, "pier": "North", "length_m": 9.0},
    {"id": 3, "pier": "East", "length_m": 15.0},
]


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/berths":
            self.send_json(200, BERTHS)
        elif self.path.startswith("/berths/"):
            key = self.path.rsplit("/", 1)[1]
            match = [b for b in BERTHS if str(b["id"]) == key]
            if not match:
                self.send_json(404, {"error": "no such berth"})
            else:
                berth = match[0]
                # Answers with the id as text and without the length.
                self.send_json(200, {"id": str(berth["id"]), "pier": berth["pier"]})
        elif self.path == "/health":
            self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"error": "not found"})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
