#!/usr/bin/env python3
"""Test whether an LLM grader agrees with examples a person labelled.

The grader's verdicts come from your own run. This script calls no model. Input is JSON lines, either
one file with both labels in each row:

  {"id": "ex-01", "human": "pass", "judge": "fail", "category": "refunds"}

or two files joined on id: --labels (id, human) and --verdicts (id, judge).
Accepted names: id | case | example; human | label | gold | expected; judge | verdict | grader | predicted;
category (optional). A missing or empty grader verdict counts as "(no verdict)", which never agrees.

It prints the agreement rate with a 95% interval, the confusion table, Cohen's kappa (agreement beyond
what the two label mixes would give by chance), per-label precision and recall of the grader, agreement
per category, and every disagreement.

Exit codes: 0 = pass: agreement and kappa are at or above the floors
            1 = fail: below a floor
            2 = not verified (too few examples, a label too rare, kappa not defined) or blocked (bad input)
The last line printed is the result.
"""
import argparse
import json
import math
import pathlib
import sys

DEFAULTS = pathlib.Path(__file__).resolve().parent.parent / "references" / "defaults.json"
ID_KEYS = ("id", "case", "example")
HUMAN_KEYS = ("human", "label", "gold", "expected")
JUDGE_KEYS = ("judge", "verdict", "grader", "predicted")
NONE = "(no verdict)"
YES = {"true", "pass", "passed", "yes", "1"}
NO = {"false", "fail", "failed", "no", "0"}


class Blocked(Exception):
    """Input that cannot be used. Ends the run as blocked."""


def end(state, why=""):
    why = " ".join(str(why).split())  # the result stays on one line, whatever text it quotes
    print(f"RESULT {state}" + (f": {why}" if why else ""))
    return {"pass": 0, "fail": 1}.get(state, 2)


def first(row, keys):
    for key in keys:
        if key in row:
            return row[key]
    return None


def norm(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip().lower()
    return text or None


def read_rows(path, what):
    path = pathlib.Path(path)
    if not path.is_file():
        raise Blocked(f"no {what} file at {path}")
    rows, bad = [], []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad.append(f"line {number}: not JSON")
            continue
        if not isinstance(row, dict) or norm(first(row, ID_KEYS)) is None:
            bad.append(f"line {number}: no id")
            continue
        rows.append((number, row))
    if bad:
        raise Blocked(f"{path} has {len(bad)} rows that cannot be used ({'; '.join(bad[:8])})")
    if not rows:
        raise Blocked(f"{path} holds no rows")
    return rows


def load(args):
    """Return a list of (id, human, judge, category) and a list of notes."""
    notes, examples = [], []
    if args.file:
        seen = set()
        for number, row in read_rows(args.file, "examples"):
            ident = str(first(row, ID_KEYS))
            if ident in seen:
                raise Blocked(f"{args.file} line {number}: id {ident} appears twice")
            seen.add(ident)
            human = norm(first(row, HUMAN_KEYS))
            if human is None:
                raise Blocked(f"{args.file} line {number}: example {ident} has no human label")
            examples.append((ident, human, norm(first(row, JUDGE_KEYS)) or NONE, norm(row.get("category"))))
        return examples, notes
    labels, verdicts = {}, {}
    for number, row in read_rows(args.labels, "labels"):
        ident = str(first(row, ID_KEYS))
        human = norm(first(row, HUMAN_KEYS))
        if ident in labels:
            raise Blocked(f"{args.labels} line {number}: id {ident} appears twice")
        if human is None:
            raise Blocked(f"{args.labels} line {number}: example {ident} has no human label")
        labels[ident] = (human, norm(row.get("category")))
    for number, row in read_rows(args.verdicts, "verdicts"):
        ident = str(first(row, ID_KEYS))
        if ident in verdicts:
            raise Blocked(f"{args.verdicts} line {number}: id {ident} appears twice")
        verdicts[ident] = norm(first(row, JUDGE_KEYS)) or NONE
    extra = sorted(set(verdicts) - set(labels))
    if extra:
        notes.append(f"{len(extra)} verdicts have no human label and were left out: {', '.join(extra[:8])}")
    for ident, (human, category) in labels.items():
        examples.append((ident, human, verdicts.get(ident, NONE), category))
    return examples, notes


def fold_binary(examples):
    """If every label on both sides is a yes or no word, read them all as pass or fail."""
    words = {h for _, h, _, _ in examples} | {j for _, _, j, _ in examples if j != NONE}
    if not words <= YES | NO:
        return examples
    def fold(w):
        return w if w == NONE else "pass" if w in YES else "fail"
    return [(i, fold(h), fold(j), c) for i, h, j, c in examples]


def wilson(hits, n, z=1.96):
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    try:
        defaults = {k: v for k, v in json.loads(DEFAULTS.read_text(encoding="utf-8")).items() if isinstance(v, dict)}
        d = {k: defaults[k]["value"] for k in ("min_examples", "min_per_label", "min_agreement", "min_kappa")}
    except (OSError, ValueError, KeyError) as exc:
        return end("blocked", f"the defaults file {DEFAULTS} cannot be used ({exc})")
    parser.add_argument("file", nargs="?", help="JSON lines with id, human and judge in each row")
    parser.add_argument("--labels", help="JSON lines with id and human (use together with --verdicts)")
    parser.add_argument("--verdicts", help="JSON lines with id and judge")
    parser.add_argument("--min-examples", type=int, default=d["min_examples"], help="examples needed for a verdict (default %(default)s)")
    parser.add_argument("--min-per-label", type=int, default=d["min_per_label"], help="examples needed of each human label (default %(default)s)")
    parser.add_argument("--min-agreement", type=float, default=d["min_agreement"], help="agreement floor, 0 to 1 (default %(default)s)")
    parser.add_argument("--min-kappa", type=float, default=d["min_kappa"], help="kappa floor (default %(default)s)")
    parser.add_argument("--show", type=int, default=50, help="how many disagreements to list (default %(default)s)")
    args = parser.parse_args()
    if bool(args.file) == bool(args.labels or args.verdicts) or bool(args.labels) != bool(args.verdicts):
        return end("blocked", "give one file with both labels in each row, or both --labels and --verdicts")
    try:
        examples, notes = load(args)
    except Blocked as exc:
        return end("blocked", str(exc))
    examples = fold_binary(examples)

    n = len(examples)
    unverified = [k for k in d if not defaults[k].get("verified")]
    print(f"note: {', '.join(unverified)} are mstack defaults written from memory, not measured values ({DEFAULTS.name}); the flags change them.")
    print(f"floors: agreement {args.min_agreement}, kappa {args.min_kappa}; needs {args.min_examples} examples and {args.min_per_label} of each human label")
    for note in notes:
        print("note: " + note)
    human_labels = sorted({h for _, h, _, _ in examples})
    labels = human_labels + sorted({j for _, _, j, _ in examples} - set(human_labels))
    table = {h: {j: 0 for j in labels} for h in labels}
    for _, h, j, _ in examples:
        table[h][j] += 1
    agree = sum(table[k][k] for k in labels)
    po = agree / n
    low, high = wilson(agree, n)
    row_total = {k: sum(table[k].values()) for k in labels}
    col_total = {k: sum(table[h][k] for h in labels) for k in labels}
    pe = sum(row_total[k] * col_total[k] for k in labels) / (n * n)
    kappa = None if pe >= 1 else (po - pe) / (1 - pe)

    print(f"\nexamples: {n}   agree: {agree}   agreement {po:.3f} (95% interval {low:.3f} to {high:.3f})")
    print(f"agreement expected by chance {pe:.3f}   Cohen's kappa " + ("not defined: both sides used one single label" if kappa is None else f"{kappa:.3f}"))
    width = max(12, max(len(k) for k in labels) + 2)
    print("\nconfusion table (rows: human, columns: grader)")
    print(" " * width + "".join(f"{k[:width - 2]:>{width}}" for k in labels) + f"{'total':>{width}}")
    for h in human_labels:
        print(f"{h[:width - 2]:<{width}}" + "".join(f"{table[h][j]:>{width}}" for j in labels) + f"{row_total[h]:>{width}}")
    print("\nper label (precision: of the grader's X, how many the human also called X; recall: of the human's X, how many the grader found)")
    for k in human_labels:
        precision = f"{table[k][k] / col_total[k]:.2f}" if col_total[k] else "n/a (grader never said it)"
        print(f"  {k}: human {row_total[k]}, grader {col_total[k]}, precision {precision}, recall {table[k][k] / row_total[k]:.2f}")
    if set(human_labels) == {"pass", "fail"}:
        wrong_pass, wrong_fail = table["fail"]["pass"], table["pass"]["fail"]
        print(f"  grader passed {wrong_pass} of {row_total['fail']} examples the human failed; grader failed {wrong_fail} of {row_total['pass']} the human passed")
    silent = col_total.get(NONE, 0)
    if silent:
        print(f"  the grader gave no verdict on {silent} examples; they count as disagreements")
    categories = sorted({c for _, _, _, c in examples if c})
    if categories:
        print("\nper category")
        for c in categories:
            rows = [(h, j) for _, h, j, cat in examples if cat == c]
            same = sum(1 for h, j in rows if h == j)
            flag = "  below the floor" if same / len(rows) < args.min_agreement else ""
            print(f"  {c}: {same} of {len(rows)} agree ({same / len(rows):.2f}){flag}")
    wrong = [(i, h, j) for i, h, j, _ in examples if h != j]
    print(f"\ndisagreements: {len(wrong)}")
    for ident, h, j in wrong[:max(0, args.show)]:
        print(f"  DISAGREE {ident}: human {h}, grader {j}")
    if len(wrong) > args.show:
        print(f"  and {len(wrong) - args.show} more; raise --show to list them")

    if n < args.min_examples:
        return end("not verified", f"{n} examples are too few to judge a grader; at least {args.min_examples} are needed (agreement so far {po:.2f})")
    rare = [f"{k} ({row_total[k]})" for k in human_labels if row_total[k] < args.min_per_label]
    if len(human_labels) < 2:
        return end("not verified", f"every example has the human label '{human_labels[0]}'; a grader that says the same thing each time would score {po:.2f} here. Add examples of the other outcome")
    if rare:
        return end("not verified", f"too few examples of {', '.join(rare)}; each human label needs at least {args.min_per_label}")
    if kappa is None:
        return end("not verified", "kappa is not defined because both sides used one single label")
    problems = []
    if po < args.min_agreement:
        problems.append(f"agreement {po:.3f} is below {args.min_agreement}")
    if kappa < args.min_kappa:
        problems.append(f"kappa {kappa:.3f} is below {args.min_kappa}")
    if problems:
        return end("fail", "; ".join(problems) + f"; {len(wrong)} disagreements listed above")
    return end("pass", f"agreement {po:.3f}, kappa {kappa:.3f} on {n} examples; {len(wrong)} disagreements listed above")


if __name__ == "__main__":
    sys.exit(main())
