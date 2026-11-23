"""The reports page: a filter form and the matching ledger rows."""
import html
import http.server
import urllib.parse

from tallybook import ledger


def render_reports_page(rows, client=None, month=None):
    lines = [f"<tr><td>{r['date']}</td><td>{html.escape(r['client'])}</td><td>{r['account']}</td>"
             f"<td class='num'>{r['amount']:.2f}</td></tr>" for r in rows]
    return ("<h1>Reports</h1>"
            f"<form><input name='client' value='{html.escape(client or '')}' placeholder='Client'>"
            f"<input name='month' value='{html.escape(month or '')}' placeholder='YYYY-MM'><button>Filter</button></form>"
            "<table><tr><th>Date</th><th>Client</th><th>Account</th><th>Amount</th></tr>" + "".join(lines) + "</table>"
            f"<p>{len(rows)} rows, total {ledger.total(rows):.2f}</p>")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path != "/reports":
            self.send_error(404)
            return
        query = urllib.parse.parse_qs(url.query)
        client, month = query.get("client", [None])[0], query.get("month", [None])[0]
        body = render_reports_page(ledger.filter_rows(ledger.load_rows(), client, month), client, month).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    http.server.HTTPServer(("127.0.0.1", 8040), Handler).serve_forever()
