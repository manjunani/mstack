#!/usr/bin/env python3
"""Measure whether retrieval returns the passage that holds the answer.

The retriever runs in your own code. This script calls no model and no search service. It reads:
  gold     JSON lines, one question per row, with the id of the passage that holds the answer
           {"id": "q1", "question": "How long is the refund window?", "answer_id": "p7"}
           (answer_ids with a list is accepted when more than one passage holds the answer; category is optional)
  results  JSON lines, the ranked ids your retriever returned for each question, best first
           {"id": "q1", "retrieved": ["p3", "p7", "p1"]}
           (retrieved may also sit in the gold rows, and its items may be objects with an id)

Commands:
  score --gold G [--results R]   hit rate at each k, mean reciprocal rank, the misses, and the change against a baseline
  save  --gold G [--results R]   keep this run as the baseline in .mstack/rag-check/baseline.json

hit rate at k   share of questions whose answer passage is among the first k ids
MRR             mean of 1/rank of the answer passage, 0 when it was not retrieved

A question with no results row is "not answered", which is kept apart from a miss.

Exit codes: 0 = pass: at or above the floor and not below the baseline
            1 = fail: below the floor, below the baseline, or a baseline question was removed
            2 = not verified (too few questions, questions not answered, nothing to judge against) or blocked (bad input)
The last line printed is the result.
"""
import argparse
import datetime
import json
import pathlib
import sys

STATE = pathlib.Path(".mstack") / "rag-check"
DEFAULTS = pathlib.Path(__file__).resolve().parent.parent / "references" / "defaults.json"
ID_KEYS = ("id", "qid", "question_id")
ANSWER_KEYS = ("answer_id", "answer_ids", "gold", "gold_ids", "relevant", "relevant_ids", "expected")
LIST_KEYS = ("retrieved", "ranked", "results", "retrieved_ids", "ids")
ITEM_KEYS = ("id", "doc_id", "chunk_id", "passage_id")


class Blocked(Exception):
    """Input that cannot be used. Ends the run as blocked."""


def end(state, why=""):
    why = " ".join(str(why).split())  # the result stays on one line, whatever text it quotes
    print(f"RESULT {state}" + (f": {why}" if why else ""))
    return {"pass": 0, "fail": 1}.get(state, 2)


def first(row, keys):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def ident(item):
    if isinstance(item, dict):
        item = first(item, ITEM_KEYS)
    if item is None or isinstance(item, (list, dict)):
        return None
    return str(item)


def rows_of(path, what):
    path = pathlib.Path(path)
    if not path.is_file():
        raise Blocked(f"no {what} file at {path}")
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            raise Blocked(f"{path} line {number} is not JSON")
        if not isinstance(row, dict) or first(row, ID_KEYS) is None:
            raise Blocked(f"{path} line {number} has no question id")
        out.append((number, row))
    if not out:
        raise Blocked(f"{path} holds no rows")
    return out


def ranked_list(row, where):
    listed = first(row, LIST_KEYS)
    if listed is None:
        return None
    if not isinstance(listed, list):
        raise Blocked(f"{where}: the retrieved ids are not a list")
    ids = [ident(item) for item in listed]
    if any(i is None for i in ids):
        raise Blocked(f"{where}: a retrieved item has no id")
    return ids


def load(gold_path, results_path):
    """Return {question id: {"question", "answers", "category", "retrieved" or None}} and a list of notes."""
    questions, notes = {}, []
    for number, row in rows_of(gold_path, "gold"):
        qid = str(first(row, ID_KEYS))
        if qid in questions:
            raise Blocked(f"{gold_path} line {number}: question {qid} appears twice")
        answers = first(row, ANSWER_KEYS)
        answers = answers if isinstance(answers, list) else [answers]
        answers = [ident(a) for a in answers]
        if not answers or any(a is None for a in answers):
            raise Blocked(f"{gold_path} line {number}: question {qid} has no answer passage id")
        questions[qid] = {"question": str(row.get("question", "")), "answers": answers, "category": row.get("category"),
                          "retrieved": ranked_list(row, f"{gold_path} line {number}")}
    if results_path:
        seen, unknown = set(), []
        for number, row in rows_of(results_path, "results"):
            qid = str(first(row, ID_KEYS))
            if qid in seen:
                raise Blocked(f"{results_path} line {number}: question {qid} appears twice")
            seen.add(qid)
            listed = ranked_list(row, f"{results_path} line {number}")
            if listed is None:
                raise Blocked(f"{results_path} line {number}: question {qid} has no list of retrieved ids")
            if qid in questions:
                questions[qid]["retrieved"] = listed
            else:
                unknown.append(qid)
        if unknown:
            notes.append(f"{len(unknown)} results rows are for questions that are not in the gold file and were left out: {', '.join(unknown[:8])}")
    return questions, notes


def rank_of(question):
    for position, passage in enumerate(question["retrieved"], 1):
        if passage in question["answers"]:
            return position
    return None


def measure(ranks, ks):
    n = len(ranks)
    hit = {k: sum(1 for r in ranks if r is not None and r <= k) / n for k in ks}
    mrr = sum(1 / r for r in ranks if r is not None) / n
    return hit, mrr


def names(items, limit=8):
    items = list(items)
    return ", ".join(items[:limit]) + (f" and {len(items) - limit} more" if len(items) > limit else "")


def run(args, defaults):
    questions, notes = load(args.gold, args.results)
    ks = sorted(set(args.k) | {args.at})
    answered = {q: v for q, v in questions.items() if v["retrieved"] is not None}
    unanswered = sorted(set(questions) - set(answered))
    print(f"note: k={args.at}, the minimum of {args.min_questions} questions and the allowed drop of {args.max_drop} are mstack defaults or your flags, not measured values ({DEFAULTS.name}).")
    for note in notes:
        print("note: " + note)
    print(f"questions: {len(questions)} in the gold file, {len(answered)} answered, {len(unanswered)} without a results row")
    for qid in unanswered:
        print(f"NOT ANSWERED {qid}: no results row; this is not counted as a miss")
    if not answered:
        raise Blocked("no question has a list of retrieved ids. Run your retriever on the gold questions and pass its output with --results")

    ranks = {q: rank_of(v) for q, v in answered.items()}
    hit, mrr = measure(list(ranks.values()), ks)
    depths = [len(v["retrieved"]) for v in answered.values()]
    print(f"retrieved lists hold {min(depths)} to {max(depths)} ids")
    shallow = [k for k in ks if k > min(depths)]
    if shallow:
        short = sum(1 for d in depths if d < max(shallow))
        print(f"note: {short} lists are shorter than k={max(shallow)}; the hit rate at k={', '.join(map(str, shallow))} is limited by what was returned")
    print("  ".join(f"hit@{k} {hit[k]:.3f}" for k in ks) + f"   MRR {mrr:.3f}")
    misses = [q for q in answered if ranks[q] is None or ranks[q] > args.at]
    for qid in misses:
        v = answered[qid]
        where = "not retrieved" if ranks[qid] is None else f"rank {ranks[qid]}"
        print(f"MISS {qid} ({where}): {v['question'][:70]!r} wanted {', '.join(v['answers'])}; got {', '.join(v['retrieved'][:args.at]) or 'nothing'}")
    categories = sorted({str(v["category"]) for v in answered.values() if v["category"] is not None})
    if categories:
        print(f"per category, hit@{args.at}:")
        for c in categories:
            inside = [q for q, v in answered.items() if str(v["category"]) == c]
            found = sum(1 for q in inside if ranks[q] is not None and ranks[q] <= args.at)
            print(f"  {c}: {found} of {len(inside)} ({found / len(inside):.2f})")
    return questions, answered, unanswered, ranks, hit, mrr, ks, misses


def cmd_save(args, defaults):
    questions, answered, unanswered, ranks, hit, mrr, ks, misses = run(args, defaults)
    if unanswered:
        return end("not verified", f"not saved: {len(unanswered)} questions have no results row ({names(unanswered)})")
    if len(answered) < args.min_questions:
        return end("not verified", f"not saved: {len(answered)} questions are too few for a baseline; at least {args.min_questions} are needed")
    STATE.mkdir(parents=True, exist_ok=True)
    target = STATE / "baseline.json"
    if target.exists():
        if not args.replace:
            return end("blocked", f"a baseline already exists at {target}. Replacing it changes what later runs are compared with; ask the user, then run save again with --replace")
        kept = STATE / f"baseline-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        kept.write_bytes(target.read_bytes())
        print(f"the old baseline was kept as {kept}")
    record = {"saved": datetime.datetime.now().isoformat(timespec="seconds"), "gold": str(args.gold), "results": str(args.results or args.gold),
              "note": args.note or "", "at": args.at, "hit": {str(k): hit[k] for k in ks}, "mrr": mrr,
              "questions": {q: {"rank": ranks[q], "answers": answered[q]["answers"]} for q in answered}}
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"baseline saved to {target}")
    return end("pass", f"baseline saved: hit@{args.at} {hit[args.at]:.3f}, MRR {mrr:.3f} on {len(answered)} questions; nothing was compared")


def cmd_score(args, defaults):
    questions, answered, unanswered, ranks, hit, mrr, ks, misses = run(args, defaults)
    at = args.at
    baseline_path = pathlib.Path(args.baseline) if args.baseline else STATE / "baseline.json"
    baseline = None
    if args.no_baseline:
        pass
    elif baseline_path.is_file():
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            old = baseline["questions"]
        except (ValueError, KeyError, TypeError) as exc:
            raise Blocked(f"the baseline {baseline_path} cannot be read ({exc})")
    elif args.baseline:
        raise Blocked(f"no baseline at {baseline_path}")

    removed, drop_reasons = [], []
    if baseline:
        retired = set(args.retired or [])
        removed = sorted(set(old) - set(questions) - retired)
        shared = sorted(set(old) & set(answered))
        if not set(old) & set(questions):
            raise Blocked(f"the baseline {baseline_path} shares no question with this gold file, so it belongs to another question set. "
                          f"Name the right one with --baseline, or score without one with --no-baseline")
        print(f"\nbaseline {baseline_path} (saved {baseline.get('saved', '?')}{', ' + baseline['note'] if baseline.get('note') else ''}): "
              f"{len(old)} questions, {len(shared)} shared with this run, {len(set(answered) - set(old))} new, {len(removed)} removed")
        for qid in removed:
            print(f"REMOVED {qid}: in the baseline, not in the gold file")
        relabelled = [q for q in shared if sorted(old[q].get("answers") or []) != sorted(answered[q]["answers"])]
        for qid in relabelled:
            print(f"RELABELLED {qid}: the answer passage in the gold file differs from the one in the baseline")
        if shared:
            before_hit, before_mrr = measure([old[q]["rank"] for q in shared], [at])
            now_hit, now_mrr = measure([ranks[q] for q in shared], [at])
            print(f"on the {len(shared)} shared questions: hit@{at} {before_hit[at]:.3f} -> {now_hit[at]:.3f} ({now_hit[at] - before_hit[at]:+.3f}), "
                  f"MRR {before_mrr:.3f} -> {now_mrr:.3f} ({now_mrr - before_mrr:+.3f})")
            for qid in shared:
                was, now = old[qid]["rank"], ranks[qid]
                was_hit, now_is_hit = was is not None and was <= at, now is not None and now <= at
                if was_hit and not now_is_hit:
                    print(f"NEWLY MISSED {qid}: rank {was} in the baseline, {'not retrieved' if now is None else 'rank ' + str(now)} now")
                elif now_is_hit and not was_hit:
                    print(f"NEWLY FOUND {qid}: {'not retrieved' if was is None else 'rank ' + str(was)} in the baseline, rank {now} now")
            if before_hit[at] - now_hit[at] > args.max_drop + 1e-9:
                drop_reasons.append(f"hit@{at} fell from {before_hit[at]:.3f} to {now_hit[at]:.3f}")
            if before_mrr - now_mrr > args.max_drop + 1e-9:
                drop_reasons.append(f"MRR fell from {before_mrr:.3f} to {now_mrr:.3f}")

    if removed:
        return end("fail", f"{len(removed)} baseline questions were removed from the gold file ({names(removed)}). Put them back, or name them with --retired if the user removed them on purpose")
    if unanswered:
        return end("not verified", f"{len(unanswered)} of {len(questions)} questions have no results row ({names(unanswered)}); hit@{at} on the rest is {hit[at]:.3f}")
    if len(answered) < args.min_questions:
        return end("not verified", f"{len(answered)} questions are too few to judge retrieval; at least {args.min_questions} are needed (hit@{at} so far {hit[at]:.3f}, MRR {mrr:.3f})")
    reasons = list(drop_reasons)
    if args.floor is not None and hit[at] < args.floor - 1e-9:
        reasons.insert(0, f"hit@{at} is {hit[at]:.3f}, below the floor of {args.floor}")
    if reasons:
        return end("fail", "; ".join(reasons) + f"; {len(misses)} misses listed above")
    if args.floor is None and not baseline:
        return end("not verified", f"measured hit@{at} {hit[at]:.3f} and MRR {mrr:.3f} on {len(answered)} questions, but there is no floor and no baseline to judge them against. "
                                   f"Agree a floor with the user (--floor), or keep this run with: score.py save")
    against = " and ".join(([f"the floor of {args.floor}"] if args.floor is not None else []) + (["the baseline"] if baseline else []))
    return end("pass", f"hit@{at} {hit[at]:.3f}, MRR {mrr:.3f} on {len(answered)} questions, checked against {against}; {len(misses)} misses listed above")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    try:
        defaults = json.loads(DEFAULTS.read_text(encoding="utf-8"))
        d = {k: defaults[k]["value"] for k in ("at_k", "k_list", "min_questions", "max_drop")}
    except (OSError, ValueError, KeyError) as exc:
        return end("blocked", f"the defaults file {DEFAULTS} cannot be used ({exc})")
    subs = parser.add_subparsers(dest="command", required=True)
    for name, handler, text in (("score", cmd_score, "score a retrieval run and judge it"), ("save", cmd_save, "keep a retrieval run as the baseline")):
        s = subs.add_parser(name, help=text)
        s.add_argument("--gold", required=True, help="JSON lines: question id, question, answer passage id")
        s.add_argument("--results", help="JSON lines: question id and the ranked ids retrieved (omit if they are in the gold rows)")
        s.add_argument("-k", type=int, nargs="+", default=d["k_list"], help="values of k to report (default %(default)s)")
        s.add_argument("--at", type=int, default=d["at_k"], help="the k that is judged (default %(default)s)")
        s.add_argument("--min-questions", type=int, default=d["min_questions"], help="questions needed for a verdict (default %(default)s)")
        s.add_argument("--max-drop", type=float, default=d["max_drop"], help="hit rate or MRR the run may lose against the baseline (default %(default)s)")
        if name == "score":
            s.add_argument("--floor", type=float, help="lowest acceptable hit rate at the judged k, 0 to 1 (no default)")
            s.add_argument("--baseline", help="baseline file (default: .mstack/rag-check/baseline.json when it exists)")
            s.add_argument("--no-baseline", action="store_true", help="do not compare with a saved baseline")
            s.add_argument("--retired", nargs="+", metavar="QUESTION", help="baseline questions the user removed on purpose")
        else:
            s.add_argument("--replace", action="store_true", help="replace an existing baseline (the old one is kept under a dated name)")
            s.add_argument("--note", help="one line on what this baseline is: index, embedding model, chunking, date")
        s.set_defaults(run=handler)
    args = parser.parse_args()
    if args.at < 1 or any(k < 1 for k in args.k) or args.min_questions < 1 or not 0 <= args.max_drop <= 1:
        return end("blocked", "k values and --min-questions need 1 or more, --max-drop a value from 0 to 1")
    if getattr(args, "floor", None) is not None and not 0 <= args.floor <= 1:
        return end("blocked", "--floor needs a value from 0 to 1")
    try:
        return args.run(args, defaults)
    except Blocked as exc:
        return end("blocked", str(exc))


if __name__ == "__main__":
    sys.exit(main())
