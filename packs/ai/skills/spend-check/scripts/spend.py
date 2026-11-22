#!/usr/bin/env python3
"""Measure the tokens and cost of a flow from its usage log and compare them with a budget.

  spend.py <usage.jsonl> [--prices FILE] [--budget USD | --budget-tokens N] [--per run|request] [--by model|tag]

The usage log is JSON lines your own code wrote, one row per model response:
  {"model": "example-medium", "input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 4000,
   "cache_creation_input_tokens": 0, "tag": "summarise", "run": "r1"}
A row may also hold these fields inside "usage". prompt_tokens and completion_tokens are read as input and output.
The script calls no API.

Cost = tokens x price per million from the prices file (default: references/prices.json). A model with no
price is kept apart as "unknown cost", never counted as zero. Every price marked "verified": false is
named in a warning: check the provider's pricing page before trusting a cost figure.

--per run divides the totals by the number of distinct "run" values, --per request by the number of rows,
and compares that figure with the budget.

Exit codes: 0 = pass: within the budget, every row read, every model priced
            1 = fail: over the budget
            2 = not verified (no budget, rows not read, models without a price) or blocked (bad input)
The last line printed is the result.
"""
import argparse
import json
import pathlib
import sys

PRICES = pathlib.Path(__file__).resolve().parent.parent / "references" / "prices.json"
FIELDS = {
    "input": ("input_tokens", "prompt_tokens"),
    "output": ("output_tokens", "completion_tokens"),
    "cache_read": ("cache_read_input_tokens", "cache_read_tokens", "cached_tokens"),
    "cache_write": ("cache_creation_input_tokens", "cache_write_tokens", "cache_creation_tokens"),
}
CHECK_NOTE = "check the provider's pricing page before trusting any cost figure"


class Blocked(Exception):
    """Input that cannot be used. Ends the run as blocked."""


def end(state, why=""):
    why = " ".join(str(why).split())  # the result stays on one line, whatever text it quotes
    print(f"RESULT {state}" + (f": {why}" if why else ""))
    return {"pass": 0, "fail": 1}.get(state, 2)


def count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return value


def read_row(row):
    """Return {input, output, cache_read, cache_write} and whether any token field was found."""
    places = [row] + ([row["usage"]] if isinstance(row.get("usage"), dict) else [])
    out, found = {}, False
    for kind, names in FIELDS.items():
        value = None
        for place in places:
            for name in names:
                if name in place:
                    value = count(place[name])
                    if value is None:
                        raise ValueError(f"{name} is not a token count")
                    found = True
                    break
            if value is not None:
                break
        out[kind] = value or 0
    details = row.get("usage", {}).get("prompt_tokens_details") if isinstance(row.get("usage"), dict) else None
    if isinstance(details, dict) and count(details.get("cached_tokens")):
        # In this shape the cached tokens are part of prompt_tokens; split them out so they are not counted twice.
        cached = details["cached_tokens"]
        out["cache_read"] = cached
        out["input"] = max(0, out["input"] - cached)
    return out, found


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("usage", help="usage log, JSON lines")
    parser.add_argument("--prices", default=str(PRICES), help="prices file (default: this skill's references/prices.json)")
    parser.add_argument("--budget", type=float, help="budget in the prices file's currency")
    parser.add_argument("--budget-tokens", type=int, help="budget in total tokens (input + output + cache read + cache write)")
    parser.add_argument("--per", choices=("all", "run", "request"), default="all", help="compare the budget with the total, the mean per run, or the mean per request")
    parser.add_argument("--by", choices=("model", "tag"), default="model", help="how to group the table (default %(default)s)")
    args = parser.parse_args()
    if args.budget is not None and args.budget_tokens is not None:
        return end("blocked", "give --budget or --budget-tokens, not both")
    try:
        return run(args)
    except Blocked as exc:
        return end("blocked", str(exc))


def run(args):
    path = pathlib.Path(args.usage)
    if not path.is_file():
        raise Blocked(f"no usage log at {path}")
    try:
        prices = json.loads(pathlib.Path(args.prices).read_text(encoding="utf-8"))
        table = prices["models"]
        per = prices.get("per_tokens", 1000000)
        currency = prices.get("currency", "")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Blocked(f"the prices file {args.prices} cannot be used ({exc})")

    rows, unread, runs = [], [], set()
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("not an object")
            tokens, found = read_row(row)
        except ValueError as exc:
            unread.append(f"line {number}: {exc}")
            continue
        if not found:
            unread.append(f"line {number}: no token fields")
            continue
        model = str(row.get("model") or (row.get("usage") or {}).get("model") or "(no model)")
        tag = str(row.get("tag") or row.get("feature") or "(no tag)")
        if row.get("run") is not None:
            runs.add(str(row["run"]))
        rows.append({"model": model, "tag": tag, **tokens})
    if not rows:
        raise Blocked(f"{path} holds no rows with token counts ({len(unread)} lines could not be read)")

    unverified = sorted(m for m in {r["model"] for r in rows} if m in table and not table[m].get("verified"))
    unpriced = sorted({r["model"] for r in rows} - set(table))
    groups, totals, unknown = {}, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0, "rows": 0}, {"rows": 0, "tokens": 0}
    for r in rows:
        price = table.get(r["model"])
        cost = None
        if price is not None:
            try:
                cost = sum(r[k] * float(price.get(k, price["input"] if k != "output" else price["output"])) for k in FIELDS) / per
            except (KeyError, TypeError, ValueError) as exc:
                raise Blocked(f"the price entry for {r['model']} cannot be used ({exc})")
        g = groups.setdefault(r[args.by], {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0, "rows": 0, "unpriced": 0})
        for k in FIELDS:
            g[k] += r[k]
            totals[k] += r[k]
        g["rows"] += 1
        totals["rows"] += 1
        if cost is None:
            g["unpriced"] += 1
            unknown["rows"] += 1
            unknown["tokens"] += sum(r[k] for k in FIELDS)
        else:
            g["cost"] += cost
            totals["cost"] += cost

    print(f"usage: {path}: {len(rows)} rows read, {len(unread)} not read, {len(runs)} runs named")
    for item in unread[:8]:
        print(f"NOT READ {item}")
    print(f"prices: {args.prices} ({currency} per {per:,} tokens)")
    for m in unverified:
        entry = table[m]
        print(f"WARNING price for {m} is not verified (source: {entry.get('source', '?')}; checked {entry.get('checked', '?')}); {CHECK_NOTE}")
    for m in unpriced:
        print(f"UNKNOWN COST {m}: no price in the prices file; its rows are kept apart, not counted as zero")
    print(f"\n{args.by:<20} {'rows':>6} {'input':>12} {'output':>12} {'cache read':>12} {'cache write':>12} {'cost':>12}")
    for name in sorted(groups, key=lambda n: -groups[n]["cost"]):
        g = groups[name]
        cost = f"{g['cost']:.4f}" + (" + ?" if g["unpriced"] else "") if g["unpriced"] < g["rows"] else "unknown"
        print(f"{name[:20]:<20} {g['rows']:>6} {g['input']:>12,} {g['output']:>12,} {g['cache_read']:>12,} {g['cache_write']:>12,} {cost:>12}")
    all_input = totals["input"] + totals["cache_read"] + totals["cache_write"]
    total_tokens = all_input + totals["output"]
    print(f"{'total':<20} {totals['rows']:>6} {totals['input']:>12,} {totals['output']:>12,} {totals['cache_read']:>12,} {totals['cache_write']:>12,} {totals['cost']:>12.4f}")
    if all_input:
        print(f"cache read share of input tokens: {totals['cache_read'] / all_input:.1%}")
    if unknown["rows"]:
        print(f"unknown cost: {unknown['rows']} rows, {unknown['tokens']:,} tokens; the cost total above leaves them out")

    divisor, label = 1, "total"
    if args.per == "run":
        if not runs:
            raise Blocked("--per run needs a 'run' field in the rows; none was found")
        divisor, label = len(runs), f"mean per run over {len(runs)} runs"
    elif args.per == "request":
        divisor, label = len(rows), f"mean per request over {len(rows)} requests"
    cost_figure, token_figure = totals["cost"] / divisor, total_tokens / divisor
    print(f"{label}: {token_figure:,.0f} tokens, {cost_figure:.4f} {currency}" + (" (priced rows only)" if unknown["rows"] else ""))
    if unverified:
        print(f"note: the cost uses {len(unverified)} unverified prices; {CHECK_NOTE}")

    gaps = []
    if unread:
        gaps.append(f"{len(unread)} lines were not read")
    if args.budget_tokens is not None:
        if token_figure > args.budget_tokens:
            return end("fail", f"{label} is {token_figure:,.0f} tokens, over the budget of {args.budget_tokens:,}")
        if gaps:
            return end("not verified", f"{token_figure:,.0f} tokens is within {args.budget_tokens:,}, but " + "; ".join(gaps))
        return end("pass", f"{label} is {token_figure:,.0f} tokens, within the budget of {args.budget_tokens:,}")
    if args.budget is not None:
        if cost_figure > args.budget:
            extra = "; prices are unverified" if unverified else ""
            return end("fail", f"{label} is {cost_figure:.4f} {currency}, over the budget of {args.budget} even without the {unknown['rows']} unpriced rows{extra}" if unknown["rows"]
                       else f"{label} is {cost_figure:.4f} {currency}, over the budget of {args.budget}{extra}")
        if unknown["rows"]:
            gaps.append(f"{unknown['rows']} rows have no price, so the real cost is higher than {cost_figure:.4f}")
        if unverified:
            gaps.append(f"prices for {', '.join(unverified)} are not verified; {CHECK_NOTE}")
        if gaps:
            return end("not verified", f"{label} is {cost_figure:.4f} {currency} against a budget of {args.budget}, but " + "; ".join(gaps))
        return end("pass", f"{label} is {cost_figure:.4f} {currency}, within the budget of {args.budget}")
    return end("not verified", f"measured {token_figure:,.0f} tokens and {cost_figure:.4f} {currency} ({label}), but no budget was given; pass --budget or --budget-tokens")


if __name__ == "__main__":
    sys.exit(main())
