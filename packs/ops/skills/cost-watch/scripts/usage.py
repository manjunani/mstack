#!/usr/bin/env python3
"""Read a usage or billing export, sum it by service and day, project the month and compare with a limit.

  usage.py FILE --limit AMOUNT [--month YYYY-MM] [--window DAYS] [--date-col C] [--service-col C] [--cost-col C] [--json]

FILE is a CSV or JSON export the user downloaded (JSON: a list of records, or an object holding one).
Columns are found by name (date/day/timestamp; service/product/project/resource/sku; cost/amount/total/
charge/spend/usd); name them with the --*-col options when the guess is wrong. A currency column, if
present, must hold one currency only.

It prints:
  - spend per service for the month, and the month so far
  - a projection for the whole month: spend so far + the average of the last --window days (default 7)
    times the days left
  - the service whose spend grew most: the last --window days against the --window days before.
    Growth is flagged only when it passes both floors in references/floors.json (a percent and an amount).

The verdict compares with --limit: spend so far over the limit, or a projection over it, fails.
Without --limit, or with fewer than 3 days of data in the month, the projection is not verified.
This script calls no provider API and sends nothing anywhere: it reads the file it is given.

Exit codes: 0 = under the limit, 1 = over (now or projected), 2 = not verified or blocked.
"""
import argparse
import calendar
import csv
import datetime
import json
import pathlib
import re
import sys
from collections import defaultdict

FLOORS = pathlib.Path(__file__).resolve().parent.parent / "references" / "floors.json"
DATE_NAMES = ("date", "day", "usage_date", "usagedate", "billing_date", "period", "start", "start_time", "timestamp", "time")
SERVICE_NAMES = ("service", "service_name", "product", "project", "resource", "sku", "category", "name", "item", "line_item")
COST_NAMES = ("cost", "amount", "total", "charge", "charges", "spend", "usd", "price", "billed", "billed_cost", "cost_usd")


def floors():
    try:
        data = json.loads(FLOORS.read_text(encoding="utf-8"))
        return data["growth_pct"]["value"], data["growth_amount"]["value"], not (data["growth_pct"].get("verified") and data["growth_amount"].get("verified"))
    except (OSError, ValueError, KeyError):
        return 50, 5, True


def load_rows(path):
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() == ".json" or text.lstrip()[:1] in "[{":
        data = json.loads(text)
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [])
        return [r for r in data if isinstance(r, dict)]
    return list(csv.DictReader(text.splitlines()))


def pick(columns, wanted, given):
    if given:
        return given if given in columns else None
    lower = {c.lower().strip().replace(" ", "_"): c for c in columns}
    for name in wanted:
        if name in lower:
            return lower[name]
    for name in wanted:
        for key, original in lower.items():
            if name in key:
                return original
    return None


def parse_date(value):
    m = re.match(r"\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})", str(value))
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_amount(value):
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d.,\-]", "", str(value or ""))
    if not text:
        return None
    if "," in text and "." not in text and re.search(r",\d{1,2}$", text):
        text = text.replace(",", ".")
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def money(x):
    return f"{x:,.2f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=pathlib.Path, help="usage or billing export, CSV or JSON")
    parser.add_argument("--limit", type=float, help="the monthly limit the user stated, in the export's currency")
    parser.add_argument("--month", help="YYYY-MM to judge (default: the month of the newest row)")
    parser.add_argument("--window", type=int, default=7, help="days used for the projection and the growth check (default 7)")
    parser.add_argument("--date-col")
    parser.add_argument("--service-col")
    parser.add_argument("--cost-col")
    parser.add_argument("--json", action="store_true", help="also print the sums as JSON")
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"blocked: no export at {args.file}. Download it from the provider's billing page; this script fetches nothing.")
        return 2
    try:
        rows = load_rows(args.file)
    except (ValueError, csv.Error) as exc:
        print(f"blocked: the file does not parse as CSV or JSON: {exc}")
        return 2
    if not rows:
        print("blocked: the export holds no rows")
        return 2
    columns = list(rows[0].keys())
    date_col, service_col, cost_col = pick(columns, DATE_NAMES, args.date_col), pick(columns, SERVICE_NAMES, args.service_col), pick(columns, COST_NAMES, args.cost_col)
    if not date_col or not cost_col:
        print(f"blocked: cannot tell which column is the {'date' if not date_col else 'cost'}. Columns: {', '.join(columns)}. Name it with --date-col or --cost-col.")
        return 2
    currency_col = pick(columns, ("currency", "currency_code"), None)
    currencies = {str(r.get(currency_col)).strip().upper() for r in rows if currency_col and r.get(currency_col)}
    if len(currencies) > 1:
        print(f"blocked: the export mixes currencies ({', '.join(sorted(currencies))}); split it or convert it first")
        return 2
    by_day_service, bad = defaultdict(float), 0
    for row in rows:
        day, amount = parse_date(row.get(date_col)), parse_amount(row.get(cost_col))
        if day is None or amount is None:
            bad += 1
            continue
        service = str(row.get(service_col) or "(none)").strip() if service_col else "(all)"
        by_day_service[(day, service)] += amount
    if not by_day_service:
        print("blocked: no row has both a readable date and a readable amount")
        return 2
    days = sorted({d for d, _ in by_day_service})
    if args.month:
        try:
            year, month = map(int, args.month.split("-"))
            datetime.date(year, month, 1)
        except ValueError:
            print("blocked: --month takes YYYY-MM")
            return 2
    else:
        year, month = days[-1].year, days[-1].month
    in_month = {k: v for k, v in by_day_service.items() if (k[0].year, k[0].month) == (year, month)}
    if not in_month:
        print(f"blocked: no rows in {year}-{month:02d}")
        return 2
    month_days = sorted({d for d, _ in in_month})
    last_day, length = month_days[-1], calendar.monthrange(year, month)[1]
    per_service, per_day = defaultdict(float), defaultdict(float)
    for (day, service), amount in in_month.items():
        per_service[service] += amount
        per_day[day] += amount
    spent = sum(per_service.values())
    window_start = last_day - datetime.timedelta(days=args.window - 1)
    recent = [per_day.get(window_start + datetime.timedelta(days=i), 0.0) for i in range(args.window) if window_start + datetime.timedelta(days=i) >= month_days[0]]
    daily = sum(recent) / len(recent) if recent else 0.0
    left = length - last_day.day
    projected = spent + daily * left
    cur = (" " + next(iter(currencies))) if currencies else ""

    print(f"export: {args.file} ({len(rows)} rows; {bad} without a readable date or amount); columns: date={date_col}, service={service_col or '(none)'}, cost={cost_col}")
    print(f"month {year}-{month:02d}: data for {len(month_days)} day(s), {month_days[0]} to {last_day}; {left} day(s) left")
    print("spend by service this month:")
    for service, amount in sorted(per_service.items(), key=lambda kv: -kv[1]):
        print(f"  {service:30} {money(amount):>12}{cur}")
    print(f"  {'TOTAL so far':30} {money(spent):>12}{cur}")
    print(f"projection: {money(spent)} + {money(daily)}/day (average of the last {len(recent)} day(s)) x {left} = {money(projected)}{cur}")

    pct_floor, amount_floor, unverified = floors()
    growth = []
    services = {s for _, s in by_day_service}
    end = days[-1]
    for service in services:
        now = sum(by_day_service.get((end - datetime.timedelta(days=i), service), 0.0) for i in range(args.window))
        before = sum(by_day_service.get((end - datetime.timedelta(days=args.window + i), service), 0.0) for i in range(args.window))
        growth.append((now - before, service, now, before))
    growth.sort(reverse=True)
    have_prior = days[0] <= end - datetime.timedelta(days=2 * args.window - 1)
    if growth and growth[0][0] > 0:
        change, service, now, before = growth[0]
        pct = (change / before * 100) if before else float("inf")
        flagged = have_prior and change >= amount_floor and pct >= pct_floor
        label = "FLAG" if flagged else "note"
        shown = "new" if before == 0 else f"+{pct:.0f}%"
        print(f"{label} largest growth: {service}: {money(before)} -> {money(now)}{cur} over the last {args.window} days against the {args.window} before ({shown}, +{money(change)})")
        if not have_prior:
            print(f"  note: the export covers less than {2 * args.window} days, so the earlier window is incomplete")
        if unverified:
            print(f"  note: the growth floors ({pct_floor}% and {amount_floor}) are unverified defaults from references/floors.json")
    else:
        print(f"no service grew over the last {args.window} days")
    if args.json:
        print(json.dumps({"month": f"{year}-{month:02d}", "spent": round(spent, 2), "projected": round(projected, 2),
                          "by_service": {k: round(v, 2) for k, v in per_service.items()},
                          "by_day": {str(k): round(v, 2) for k, v in sorted(per_day.items())}}, indent=2))

    if args.limit is None:
        print("RESULT not verified: no limit was stated, so nothing can be judged against it. Ask the user for the monthly limit.")
        return 2
    print(f"limit: {money(args.limit)}{cur}; spent {spent / args.limit * 100:.0f}% of it; projected {projected / args.limit * 100:.0f}%")
    if spent > args.limit:
        print(f"RESULT fail: already over the limit: {money(spent)} spent against {money(args.limit)}")
        return 1
    if len(month_days) < 3:
        print(f"RESULT not verified: under the limit so far ({money(spent)}), but {len(month_days)} day(s) of data are too few to project the month")
        return 2
    if projected > args.limit:
        print(f"RESULT fail: projected {money(projected)} for the month, over the limit of {money(args.limit)} by {money(projected - args.limit)}")
        return 1
    print(f"RESULT pass: {money(spent)} spent, {money(projected)} projected, under the limit of {money(args.limit)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
