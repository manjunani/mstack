"""Run cost-watch's usage.py on usage exports written by this test. All figures are made up.

Usage: cost_watch_cases.py <new empty folder>
"""
import argparse
import datetime
import json

import harness

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
folder = harness.new_folder(parser.parse_args().folder)
tool = harness.script("cost-watch", "usage.py")
cases = harness.Cases("cost-watch")

# November 1 to 20: api costs 2.00 a day, then 6.00 a day from the 14th; db 1.50 a day; a free row each day.
start = datetime.date(2026, 11, 1)
lines = ["Date,Service,Cost,Currency"]
for i in range(20):
    day = start + datetime.timedelta(days=i)
    lines.append(f"{day},api,{6.0 if day.day >= 14 else 2.0},USD")
    lines.append(f"{day},db,1.50,USD")
    lines.append(f"{day},bandwidth,0,USD")
lines.append("not a date,api,3,USD")
csv_file = folder / "usage.csv"
csv_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
# Sums by hand: api = 13*2 + 7*6 = 68; db = 30; total 98.
# Last 7 days (14..20) average: 6 + 1.5 = 7.5 a day; 10 days left -> 98 + 75 = 173.

code, out = harness.run(tool, csv_file, "--limit", "200")
cases.check("under the limit", code, 0, out,
            has=("api", "68.00", "TOTAL so far", "98.00", "7.50/day", "= 173.00", "1 without a readable date", "FLAG largest growth: api: 14.00 -> 42.00 USD over the last 7 days against the 7 before (+200%, +28.00)"),
            last="RESULT pass: 98.00 spent, 173.00 projected, under the limit of 200.00")
code, out = harness.run(tool, csv_file, "--limit", "150")
cases.check("projected over the limit", code, 1, out, last="RESULT fail: projected 173.00 for the month, over the limit of 150.00 by 23.00")
code, out = harness.run(tool, csv_file, "--limit", "90")
cases.check("already over the limit", code, 1, out, last="RESULT fail: already over the limit")
code, out = harness.run(tool, csv_file)
cases.check("no limit stated", code, 2, out, last="RESULT not verified: no limit")

# JSON export with other column names, and a service whose growth is under the money floor.
records = []
for i in range(20):
    day = start + datetime.timedelta(days=i)
    records.append({"usage_date": f"{day}T00:00:00Z", "product": "functions", "amount_usd": "$0.10" if day.day < 14 else "$0.30"})
    records.append({"usage_date": f"{day}T00:00:00Z", "product": "storage", "amount_usd": "$1.00"})
json_file = folder / "usage.json"
json_file.write_text(json.dumps({"meta": {"x": 1}, "items": records}), encoding="utf-8")
code, out = harness.run(tool, json_file, "--limit", "100", "--json")
cases.check("JSON export, small growth is a note, not a flag", code, 0, out,
            has=("date=usage_date", "service=product", "cost=amount_usd", "note largest growth: functions"), lacks=("FLAG",))

# Two days of data: too early to project.
early = folder / "early.csv"
early.write_text("day,service,cost\n2026-12-01,api,3\n2026-12-02,api,4\n", encoding="utf-8")
code, out = harness.run(tool, early, "--limit", "100")
cases.check("two days of data", code, 2, out, has=("less than 14 days",), last="RESULT not verified: under the limit so far")

# --month picks an earlier month; a missing month is blocked.
code, out = harness.run(tool, csv_file, "--limit", "200", "--month", "2026-11")
cases.check("--month for the same month", code, 0, out)
code, out = harness.run(tool, csv_file, "--limit", "200", "--month", "2026-08")
cases.check("month with no rows", code, 2, out, last="blocked")

bad_cols = folder / "cols.csv"
bad_cols.write_text("when,what,howmuch\n2026-11-01,api,3\n", encoding="utf-8")
code, out = harness.run(tool, bad_cols, "--limit", "10")
cases.check("columns cannot be guessed", code, 2, out, last="blocked")
code, out = harness.run(tool, bad_cols, "--limit", "10", "--date-col", "when", "--cost-col", "howmuch", "--service-col", "what")
cases.check("columns named by the user", code, 2, out, last="RESULT not verified: under the limit so far")

mixed = folder / "mixed.csv"
mixed.write_text("date,service,cost,currency\n2026-11-01,a,1,USD\n2026-11-01,b,1,EUR\n", encoding="utf-8")
code, out = harness.run(tool, mixed, "--limit", "10")
cases.check("mixed currencies", code, 2, out, last="blocked")
code, out = harness.run(tool, folder / "none.csv", "--limit", "10")
cases.check("no export file", code, 2, out, last="blocked")
(folder / "empty.csv").write_text("date,service,cost\n", encoding="utf-8")
code, out = harness.run(tool, folder / "empty.csv", "--limit", "10")
cases.check("export with no rows", code, 2, out, last="blocked")

raise SystemExit(cases.finish())
