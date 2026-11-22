#!/usr/bin/env python3
"""Rank named options on weighted criteria and compute what would change the winner.

  template FILE --decision D   write an empty comparison to fill in (refuses if FILE exists)
  rank FILE                    rank the options, apply vetoes, report the margin and the flip points

The file is JSON:
  decision  the question being decided
  scale     {"min": 1, "max": 5}; on every criterion a higher score is better
  criteria  [{"name": "running cost", "weight": 3, "veto_below": 2}]
            weight: how much the criterion counts (any positive number; only the proportions matter)
            veto_below: optional; an option scoring below it on this criterion is out, whatever its total
  options   [{"name": "Postgres queue",
              "scores": {"running cost": {"score": 4, "source": "price list read on 2026-11-20"}}}]
            source: where the score comes from. "my estimate" is a source; it is reported as soft.

What rank refuses (exit 2), listing every case:
  - a criterion with no weight, or a weight that is not a positive number
  - an option with no score on a criterion, a score off the scale, or a score with no stated source
  - fewer than two options, no criteria, a name used twice

What rank prints:
  - the total of each option (weighted mean on the scale) and the options removed by a veto
  - the margin between first and second place
  - the smallest change in ONE weight that makes first place change hands
  - the smallest change in ONE score that makes first place change hands
  Each flip point is the value at which the two options tie; past it the other one leads.

Exit codes: 0 = pass: one option is first
            1 = fail: first place is tied, or every option is vetoed
            2 = refused or blocked: the input is incomplete
The result is also written beside the input as <name>.result.json. The input file is never changed.
"""
import argparse
import copy
import json
import pathlib
import re
import sys

PLACEHOLDER = re.compile(r"\b(tbd|todo|fixme|to be decided|fill in|unknown|none)\b|\?\?\?|<[A-Za-z][^<>]{0,40}>", re.I)
SOFT = re.compile(r"\b(guess|guessed|estimate|estimated|assum\w*|gut|opinion|unsure|not sure|feeling|rough|hunch)\b", re.I)
TIE = 1e-9


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def said(value):
    return isinstance(value, str) and len(value.strip()) >= 3 and not PLACEHOLDER.search(value)


def fmt(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def read(path):
    """Return (model, refusals). model = (decision, low, high, weights, vetoes, scores, sources)."""
    if not path.exists():
        return None, [f"{path} does not exist. Run: compare.py template {path} --decision \"...\""]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return None, [f"{path} is not valid JSON ({exc})"]
    if not isinstance(data, dict):
        return None, [f"{path} must hold one JSON object"]
    refusals = []
    scale = data.get("scale") if isinstance(data.get("scale"), dict) else {}
    low, high = scale.get("min"), scale.get("max")
    if not is_number(low) or not is_number(high) or low >= high:
        refusals.append("scale needs a numeric min and a larger max, for example {\"min\": 1, \"max\": 5}")
        low, high = 1, 5
    if not said(data.get("decision")):
        refusals.append("decision is empty: say what is being decided")
    criteria = data.get("criteria") if isinstance(data.get("criteria"), list) else []
    options = data.get("options") if isinstance(data.get("options"), list) else []
    if not criteria:
        refusals.append("no criteria")
    if len(options) < 2:
        refusals.append(f"{len(options)} option(s): a comparison needs at least two named options")
    weights, vetoes = {}, {}
    for position, criterion in enumerate(criteria, 1):
        name = criterion.get("name") if isinstance(criterion, dict) else None
        if not said(name):
            refusals.append(f"criterion {position}: no name")
            continue
        if name in weights:
            refusals.append(f"criterion '{name}' is listed twice")
        weight = criterion.get("weight")
        if not is_number(weight):
            refusals.append(f"criterion '{name}': the weight is missing. Ask the user how much it counts; do not fill it in")
            weight = 0
        elif weight <= 0:
            refusals.append(f"criterion '{name}': weight {weight} is not a positive number. Remove the criterion if it does not count")
        weights[name] = weight
        if "veto_below" in criterion and criterion["veto_below"] is not None:
            if not is_number(criterion["veto_below"]) or not low < criterion["veto_below"] <= high:
                refusals.append(f"criterion '{name}': veto_below must be on the scale, above {fmt(low)} and at most {fmt(high)}")
            else:
                vetoes[name] = criterion["veto_below"]
    scores, sources = {}, {}
    for position, option in enumerate(options, 1):
        name = option.get("name") if isinstance(option, dict) else None
        if not said(name):
            refusals.append(f"option {position}: no name")
            continue
        if name in scores:
            refusals.append(f"option '{name}' is listed twice")
        cells = option.get("scores") if isinstance(option.get("scores"), dict) else {}
        scores[name], sources[name] = {}, {}
        for criterion in weights:
            cell = cells.get(criterion)
            if not isinstance(cell, dict) or not is_number(cell.get("score")):
                refusals.append(f"'{name}' has no score for '{criterion}'")
                continue
            if not low <= cell["score"] <= high:
                refusals.append(f"'{name}' / '{criterion}': score {cell['score']} is off the scale {fmt(low)} to {fmt(high)}")
            if not said(cell.get("source")):
                refusals.append(f"'{name}' / '{criterion}': score {cell['score']} has no stated source. Say where it comes from, even if that is an estimate")
            scores[name][criterion] = cell["score"]
            sources[name][criterion] = str(cell.get("source", ""))
        for extra in sorted(set(cells) - set(weights)):
            refusals.append(f"'{name}' has a score for '{extra}', which is not a listed criterion")
    return (data.get("decision"), low, high, weights, vetoes, scores, sources), refusals


def rank(weights, vetoes, scores):
    """Return (ranked [(name, total)], vetoed {name: [criterion]}). Totals are weighted means on the scale."""
    total_weight = sum(weights.values())
    ranked, vetoed = [], {}
    for name, cells in scores.items():
        hits = [c for c, limit in vetoes.items() if cells[c] < limit]
        if hits:
            vetoed[name] = hits
        else:
            ranked.append((name, sum(weights[c] * cells[c] for c in weights) / total_weight))
    ranked.sort(key=lambda pair: (-pair[1], pair[0]))
    return ranked, vetoed


def leader(weights, vetoes, scores):
    """The single option in first place, or None when first place is shared or empty."""
    ranked, _ = rank(weights, vetoes, scores)
    if not ranked or (len(ranked) > 1 and abs(ranked[0][1] - ranked[1][1]) <= TIE):
        return None
    return ranked[0][0]


def weight_flips(winner, weights, vetoes, scores):
    """For each criterion, the nearest weight at which the winner stops being alone in first place."""
    ranked, _ = rank(weights, vetoes, scores)
    flips = []
    for criterion in weights:
        best = None
        for rival, _ in ranked:
            if rival == winner:
                continue
            gap = scores[winner][criterion] - scores[rival][criterion]
            if gap == 0:
                continue
            lead = sum(weights[c] * (scores[winner][c] - scores[rival][c]) for c in weights)
            new = weights[criterion] - lead / gap
            if new < 0:
                continue
            change = new - weights[criterion]
            if best is None or abs(change) < abs(best["change"]):
                best = {"criterion": criterion, "from": weights[criterion], "to": new, "change": change, "then_first": rival}
        if best:
            # Recompute the ranking at the new weight: the winner must no longer be alone in first place.
            trial = dict(weights)
            trial[criterion] = best["to"]
            if sum(trial.values()) > 0 and leader(trial, vetoes, scores) != winner:
                flips.append(best)
    return sorted(flips, key=lambda f: abs(f["change"]))


def score_flips(winner, low, high, weights, vetoes, scores):
    """For each score, the nearest value at which the winner stops being alone in first place."""
    ranked, vetoed = rank(weights, vetoes, scores)
    flips = []
    for option in scores:
        for criterion in weights:
            current, weight = scores[option][criterion], weights[criterion]
            targets = []
            if option == winner:
                for rival, _ in ranked:
                    if rival != winner and weight > 0:
                        lead = sum(weights[c] * (scores[winner][c] - scores[rival][c]) for c in weights)
                        targets.append((current - lead / weight, rival, "tie"))
                if criterion in vetoes:
                    second = ranked[1][0] if len(ranked) > 1 else None
                    targets.append((vetoes[criterion], second, "veto"))
            elif option in vetoed:
                if vetoed[option] == [criterion]:
                    lead = sum(weights[c] * (scores[winner][c] - scores[option][c]) for c in weights)
                    needed = current + lead / weight if weight > 0 else vetoes[criterion]
                    targets.append((max(vetoes[criterion], needed), option, "tie"))
            elif weight > 0:
                lead = sum(weights[c] * (scores[winner][c] - scores[option][c]) for c in weights)
                targets.append((current + lead / weight, option, "tie"))
            best = None
            for to, rival, kind in targets:
                if not low - TIE <= to <= high + TIE or rival is None:
                    continue
                # Recompute the ranking with the changed score: at a tie point first place is shared,
                # and just below a veto limit the winner is out.
                trial = copy.deepcopy(scores)
                trial[option][criterion] = to - 0.001 * (high - low) if kind == "veto" else to
                if leader(weights, vetoes, trial) == winner:
                    continue
                if best is None or abs(to - current) < abs(best["to"] - current):
                    best = {"option": option, "criterion": criterion, "from": current, "to": to, "change": to - current,
                            "then_first": rival, "by_veto": kind == "veto"}
            if best:
                flips.append(best)
    return sorted(flips, key=lambda f: abs(f["change"]))


def cmd_template(args):
    if args.file.exists():
        print(f"blocked: {args.file} already exists; it is not overwritten")
        return 2
    data = {"decision": args.decision, "scale": {"min": 1, "max": 5},
            "criteria": [{"name": "", "weight": None}],
            "options": [{"name": "", "scores": {"": {"score": None, "source": ""}}}, {"name": "", "scores": {}}]}
    args.file.parent.mkdir(parents=True, exist_ok=True)
    args.file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.file}: one unnamed criterion with no weight and two unnamed options. rank refuses it until it is filled in.")
    print("RESULT pass")
    return 0


def cmd_rank(args):
    model, refusals = read(args.file)
    if refusals:
        for line in refusals:
            print("  REFUSED  " + line)
        print(f"blocked: {len(refusals)} gap(s) in the comparison; nothing was ranked")
        return 2
    decision, low, high, weights, vetoes, scores, sources = model
    ranked, vetoed = rank(weights, vetoes, scores)
    total_weight = sum(weights.values())
    print(f"Decision: {decision}")
    print("Criteria: " + "; ".join(f"{c} {fmt(100 * w / total_weight)}%" + (f" (veto below {fmt(vetoes[c])})" if c in vetoes else "")
                                   for c, w in weights.items()))
    print(f"Scale {fmt(low)} to {fmt(high)}, higher is better.\n")
    for place, (name, total) in enumerate(ranked, 1):
        print(f"  {place}. {name:28} {fmt(total)}   " + "  ".join(f"{c}={fmt(scores[name][c])}" for c in weights))
    for name, hits in vetoed.items():
        print(f"  out  {name:27} vetoed: " + ", ".join(f"'{c}' is {fmt(scores[name][c])}, below {fmt(vetoes[c])}" for c in hits))
    soft = [(o, c) for o in scores for c in weights if SOFT.search(sources[o][c])]
    result = {"decision": decision, "ranked": [{"option": n, "total": round(t, 4)} for n, t in ranked], "vetoed": vetoed,
              "soft_scores": [f"{o} / {c}" for o, c in soft]}
    out = args.file.with_name(args.file.stem + ".result.json")

    def finish(code, line):
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"\nresult written to {out}")
        print(line)
        return code

    if not ranked:
        result["winner"] = None
        return finish(1, "RESULT fail: every option is vetoed. The vetoes or the options have to change; that is the user's call")
    winner = leader(weights, vetoes, scores)
    if winner is None:
        tied = [n for n, t in ranked if abs(t - ranked[0][1]) <= TIE]
        result["winner"] = None
        return finish(1, f"RESULT fail: first place is tied between {' and '.join(tied)}. Ask the user which criterion separates them")
    margin = ranked[0][1] - ranked[1][1] if len(ranked) > 1 else None
    w_flips = weight_flips(winner, weights, vetoes, scores)
    s_flips = score_flips(winner, low, high, weights, vetoes, scores)
    result.update(winner=winner, margin=None if margin is None else round(margin, 4),
                  weight_flips=w_flips, score_flips=s_flips)

    print(f"\nFirst: {winner}" + (f", ahead of {ranked[1][0]} by {fmt(margin)} points ({fmt(100 * margin / (high - low))}% of the scale)"
                                  if margin is not None else " (the only option left after vetoes)"))
    print("\nSmallest change in one weight that changes first place:")
    if w_flips:
        for flip in w_flips[:3]:
            print(f"  weight of '{flip['criterion']}' from {fmt(flip['from'])} to {fmt(flip['to'])} ({flip['change']:+.2f}): ties with {flip['then_first']}, which leads past that")
    else:
        print("  none: no single weight, changed alone, moves first place")
    print("Smallest change in one score that changes first place:")
    if s_flips:
        for flip in s_flips[:3]:
            if flip["by_veto"]:
                how = f"below {fmt(flip['to'])} is a veto, so {flip['then_first']} leads"
            elif flip["option"] == winner:
                how = f"ties with {flip['then_first']}, which leads past that"
            else:
                how = f"ties with {winner}, and leads past that"
            mark = "  [soft score]" if (flip["option"], flip["criterion"]) in soft else ""
            print(f"  {flip['option']} / '{flip['criterion']}' from {fmt(flip['from'])} to {fmt(flip['to'])} ({flip['change']:+.2f}): {how}{mark}")
    else:
        print("  none: no single score, changed alone within the scale, moves first place")
    if soft:
        print(f"\n  warn  {len(soft)} score(s) rest on an estimate: " + "; ".join(f"{o} / {c}" for o, c in soft[:6]))
    if s_flips and abs(s_flips[0]["change"]) <= 1 + TIE:
        print(f"  warn  the result is fragile: one point or less on a single score ({s_flips[0]['option']} / {s_flips[0]['criterion']}) changes the winner")
    return finish(0, "RESULT pass")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("template", help="write an empty comparison")
    p.add_argument("file", type=pathlib.Path)
    p.add_argument("--decision", required=True, help="the question being decided")
    p = sub.add_parser("rank", help="rank the options and compute the flip points")
    p.add_argument("file", type=pathlib.Path)
    args = parser.parse_args()
    return {"template": cmd_template, "rank": cmd_rank}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
