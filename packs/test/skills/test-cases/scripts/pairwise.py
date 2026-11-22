#!/usr/bin/env python3
"""Build a small set of test rows in which every pair of parameter values appears at least once.

Parameters come from --param (repeat it) or from a JSON model file:

  pairwise.py --param "browser=chrome,firefox,safari" --param "os=mac,windows,linux" --param "role=admin,member"
  pairwise.py --model model.json --exclude "browser=safari,os=linux" --covers R-004 --out cases-r004.md

  model.json:  {"parameters": {"browser": ["chrome", "firefox"], "os": ["mac", "linux"]},
                "exclude": [{"browser": "safari", "os": "linux"}]}

--exclude names a combination that cannot happen; no row will contain it. A pair that no valid row
can contain is listed as impossible and is not counted as missed.

The rows are printed as a Markdown table (or --format json / csv) with an empty `expected` column.
That column is empty on purpose: the generator knows the inputs, not the right answer. Fill one
specific result per row, then run cases.py check.

After building the rows the script counts the pairs again from the finished rows and refuses to
print a set that misses one. The result is the same for the same input: no randomness is used.

Exit codes: 0 = every possible pair is covered, 1 = internal fault: a pair was missed (nothing is written),
            2 = bad input (fewer than two parameters, an unknown name in --exclude, an output file that exists)
"""
import argparse
import csv
import io
import itertools
import json
import pathlib
import sys

SEEDS_PER_ROW = 25


def parse_params(args):
    params = {}
    if args.model:
        try:
            model = json.loads(args.model.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read the model file {args.model}: {exc}")
        if not isinstance(model, dict) or not isinstance(model.get("parameters"), dict):
            raise ValueError('the model file needs an object "parameters": {"name": ["value", ...]}')
        for name, values in model["parameters"].items():
            if not isinstance(values, list):
                raise ValueError(f"parameter '{name}' in the model file is not a list of values")
            params[str(name)] = [str(v) for v in values]
        excludes = [{str(k): str(v) for k, v in item.items()} for item in model.get("exclude", [])]
    else:
        excludes = []
    for text in args.param or []:
        name, sep, values = text.partition("=")
        if not sep or not name.strip():
            raise ValueError(f"--param '{text}' is not in the form name=value1,value2")
        params[name.strip()] = [v.strip() for v in values.split(",")]
    for text in args.exclude or []:
        combo = {}
        for part in text.split(","):
            name, sep, value = part.partition("=")
            if not sep:
                raise ValueError(f"--exclude '{text}' is not in the form name=value,name=value")
            combo[name.strip()] = value.strip()
        excludes.append(combo)
    if len(params) < 2:
        raise ValueError("at least two parameters are needed to form pairs")
    for name, values in params.items():
        if not values or any(v == "" for v in values):
            raise ValueError(f"parameter '{name}' has no values or an empty value")
        if len(set(values)) != len(values):
            raise ValueError(f"parameter '{name}' lists a value twice")
    for combo in excludes:
        if len(combo) < 2:
            raise ValueError(f"an exclusion needs at least two parameters: {combo}. To drop a single value, remove it from the parameter")
        for name, value in combo.items():
            if name not in params:
                raise ValueError(f"exclusion names an unknown parameter '{name}'")
            if value not in params[name]:
                raise ValueError(f"exclusion names an unknown value '{value}' for parameter '{name}'")
    return params, excludes


def allowed(row, excludes):
    """False when the partly filled row already contains a whole excluded combination."""
    return not any(all(row.get(name) == value for name, value in combo.items()) for combo in excludes)


def build(params, excludes):
    names = list(params)
    index = {name: i for i, name in enumerate(names)}

    def key(n1, v1, n2, v2):
        return ((n1, v1), (n2, v2)) if index[n1] < index[n2] else ((n2, v2), (n1, v1))

    uncovered = []
    for n1, n2 in itertools.combinations(names, 2):
        for v1 in params[n1]:
            for v2 in params[n2]:
                uncovered.append(key(n1, v1, n2, v2))
    todo = dict.fromkeys(uncovered)  # ordered set

    def gain(row, name, value):
        return sum(1 for other, chosen in row.items() if key(name, value, other, chosen) in todo)

    def complete(row, remaining):
        if not remaining:
            return dict(row)
        name = remaining[0]
        order = sorted(params[name], key=lambda v: -gain(row, name, v))
        for value in order:
            row[name] = value
            if allowed(row, excludes):
                done = complete(row, remaining[1:])
                if done is not None:
                    del row[name]
                    return done
            del row[name]
        return None

    rows, impossible = [], []
    while todo:
        best, best_score = None, -1
        for seed in list(itertools.islice(todo, SEEDS_PER_ROW)):
            (n1, v1), (n2, v2) = seed
            start = {n1: v1, n2: v2}
            row = complete(start, [n for n in names if n not in start]) if allowed(start, excludes) else None
            if row is None:
                impossible.append(seed)
                del todo[seed]
                continue
            score = sum(1 for a, b in itertools.combinations(names, 2) if key(a, row[a], b, row[b]) in todo)
            if score > best_score:
                best, best_score = row, score
        if best is None:
            continue
        rows.append({name: best[name] for name in names})
        for a, b in itertools.combinations(names, 2):
            todo.pop(key(a, best[a], b, best[b]), None)
    return rows, impossible, uncovered, key


def recount(params, rows, impossible, all_pairs, key):
    """Count covered pairs from the finished rows only. Returns the pairs that are neither covered nor impossible."""
    names = list(params)
    seen = set()
    for row in rows:
        for a, b in itertools.combinations(names, 2):
            seen.add(key(a, row[a], b, row[b]))
    gone = set(impossible)
    return [p for p in all_pairs if p not in seen and p not in gone], len(seen)


def render(rows, names, args):
    ids = [f"{args.prefix}-{n:03d}" for n in range(args.start, args.start + len(rows))]
    if args.format == "json":
        return json.dumps([{"id": i, "covers": args.covers, **row, "expected": ""} for i, row in zip(ids, rows)], indent=2) + "\n"
    header = ["id", "covers", *names, "expected"]
    table = [[i, args.covers, *[row[n] for n in names], ""] for i, row in zip(ids, rows)]
    if args.format == "csv":
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(table)
        return out.getvalue()
    def cells(values):
        return "| " + " | ".join(str(v).replace("|", "\\|") for v in values) + " |"
    return "\n".join([cells(header), "|" + "---|" * len(header), *[cells(r) for r in table]]) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--param", action="append", metavar="NAME=V1,V2", help="one parameter and its values; repeat for each parameter")
    parser.add_argument("--model", type=pathlib.Path, help="JSON file with parameters and exclusions")
    parser.add_argument("--exclude", action="append", metavar="NAME=V,NAME=V", help="a combination that cannot occur; repeat for more")
    parser.add_argument("--covers", default="", help="requirement id(s) for the covers column, for example R-004")
    parser.add_argument("--prefix", default="TC", help="prefix of the case ids (default TC)")
    parser.add_argument("--start", type=int, default=1, help="number of the first case id (default 1)")
    parser.add_argument("--format", choices=("md", "json", "csv"), default="md", help="output format (default md)")
    parser.add_argument("--out", type=pathlib.Path, help="write the rows to this new file instead of the screen")
    args = parser.parse_args()

    try:
        params, excludes = parse_params(args)
    except ValueError as exc:
        print(f"blocked: {exc}")
        return 2
    if args.out and args.out.exists():
        print(f"blocked: {args.out} already exists; choose another name (this script does not overwrite)")
        return 2

    rows, impossible, all_pairs, key = build(params, excludes)
    missed, covered = recount(params, rows, impossible, all_pairs, key)
    names = list(params)
    product = 1
    for values in params.values():
        product *= len(values)

    broken = [row for row in rows if not allowed(row, excludes)]
    if broken:
        print(f"RESULT fail: internal fault: {len(broken)} row(s) contain an excluded combination; nothing was written")
        return 1
    if missed:
        for (n1, v1), (n2, v2) in missed[:20]:
            print(f"  missed: {n1}={v1} with {n2}={v2}")
        print(f"RESULT fail: internal fault: {len(missed)} pair(s) are in no row; nothing was written")
        return 1
    if not rows:
        print("RESULT fail: the exclusions leave no valid row at all")
        return 1

    text = render(rows, names, args)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {len(rows)} rows to {args.out}")
    else:
        print(text, end="")
    print()
    print(f"parameters: {len(names)} ({', '.join(f'{n}:{len(v)}' for n, v in params.items())})")
    print(f"rows: {len(rows)}   all combinations would be: {product}")
    print(f"pairs covered: {covered} of {len(all_pairs) - len(impossible)} possible (recounted from the rows)")
    for (n1, v1), (n2, v2) in impossible:
        print(f"  impossible under the exclusions: {n1}={v1} with {n2}={v2}")
    print("the expected column is empty: fill one specific result per row, then run cases.py check")
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
