#!/usr/bin/env python3
"""Record the user's go-ahead for one paid 3D generation, then accept or reject the file that came back.

This script calls no provider and uses no network. The generation itself is done with the provider's own
tool, by you, after `approve` has recorded a yes.

  approve --provider <name> --cost "<what the provider charges, as stated to the user>" --prompt "<text>" --user-approved
        Writes an approval record for exactly one generation and prints its id. Without --user-approved it
        refuses: that flag is only passed after the user said yes to this provider and this cost.
  accept <file> --id <approval id> --profile <budget profile>
        Confirms the file is a real glTF model (not a web page, an API reply or an empty download), checks its
        structure and the budget profile, and looks for a passing gltf-gate manifest of the same file.
        Records accepted, rejected or waiting in the approval record.
  list  Every approval record with its stated cost and outcome: the ledger of what was spent.

Records live in .mstack/text-to-3d/ under --project (default: the current folder).
One approval covers one generated file. A second file needs a new approval, so the user is asked each time.

Exit codes: 0 = pass (accepted, or approval recorded), 1 = fail (the file is rejected),
            2 = not verified (the full gate has not passed yet) or blocked (no approval, bad input).
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import glb  # noqa: E402

BUDGETS = pathlib.Path(__file__).resolve().parent.parent / "references" / "budgets.json"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def ledger(project):
    return pathlib.Path(project).resolve() / ".mstack" / "text-to-3d"


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def cmd_approve(args):
    if not args.provider.strip() or not args.cost.strip() or len(args.prompt.strip()) < 3:
        print("blocked: --provider, --cost and --prompt all need real text; the cost is what was stated to the user")
        return 2
    if not args.user_approved:
        print(f"blocked: no approval recorded. Tell the user: provider '{args.provider}', cost '{args.cost}', one generation, "
              "and that the prompt is sent to that provider. Run this again with --user-approved only after they say yes.")
        return 2
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    ident = f"t3d-{stamp}-{os.urandom(3).hex()}"  # random part: two approvals in one second must not collide
    folder = ledger(args.project)
    folder.mkdir(parents=True, exist_ok=True)
    record = {"id": ident, "provider": args.provider.strip(), "stated_cost": args.cost.strip(), "prompt": args.prompt.strip(),
              "user_approved": True, "approved_at": now(), "generations_allowed": 1, "status": "approved", "file": None}
    with (folder / f"{ident}.json").open("x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
    print(f"approval {ident}: one generation with {record['provider']}, stated cost {record['stated_cost']}")
    print(f"record: {folder / (ident + '.json')}")
    print("Now run the provider's own tool once, download the model by its named key, then run 'accept'.")
    print("RESULT pass")
    return 0


def find_gate_pass(project, digest):
    folder = pathlib.Path(project).resolve() / ".mstack" / "gltf-gate"
    for path in sorted(folder.glob(f"*-{digest[:8]}.json")) if folder.is_dir() else []:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if manifest.get("sha256") == digest:
            return manifest.get("result"), path
    return None, None


def cmd_accept(args):
    folder = ledger(args.project)
    path = folder / f"{args.id}.json"
    if not path.is_file():
        print(f"blocked: no approval record '{args.id}' in {folder}. A generated file is only judged against a recorded approval; run 'approve' first.")
        return 2
    record = json.loads(path.read_text(encoding="utf-8"))
    if not record.get("user_approved"):
        print(f"blocked: record {args.id} carries no user approval")
        return 2
    profiles, error = glb.load_budgets(args.budgets)
    if error:
        print(f"RESULT not verified: {error}")
        return 2
    if args.profile not in profiles:
        print(f"blocked: no budget profile '{args.profile}'. Choose one of: {', '.join(sorted(profiles))}")
        return 2
    kind, detail = glb.sniff(args.file)
    if kind == "missing":
        print(f"blocked: {args.file}: no such file. Download the model first.")
        return 2
    digest = sha256(args.file)
    if record.get("sha256") and record["sha256"] != digest:
        print(f"blocked: approval {args.id} already covered one generated file (sha256 {record['sha256'][:12]}). "
              "This is a different file: ask the user again and record a new approval.")
        return 2

    reasons, waiting = [], []
    summary = None
    print(f"file: {args.file} ({kind}: {detail})")
    if kind not in ("glb", "gltf"):
        reasons.append(f"not a model file: {detail}")
    else:
        model = glb.load(args.file)
        glb.structure(model)
        if not model.readable:
            reasons.append(model.errors[0])
        else:
            summary = glb.stats(model)
            print("\n".join(glb.describe(summary)))
            for err in model.errors:
                print(f"ERROR           {err}")
            if model.errors:
                reasons.append(f"{len(model.errors)} structural errors (first: {model.errors[0]})")
            if summary["triangles_in_scene"] == 0:
                reasons.append("the model draws no triangles")
            rows = glb.check_budget(summary, profiles[args.profile])
            print(f"== budget: {args.profile} (unverified working values unless marked)")
            for row in rows:
                measured = "unknown" if row["measured"] is None else row["measured"]
                print(f"  {row['key']:<18} {measured!s:>12} / {row['limit']:<9} {row['state'].upper() if row['state'] != 'ok' else 'ok'}")
                if row["state"] == "over":
                    reasons.append(f"{row['key']} {measured} is over the {args.profile} budget of {row['limit']}")
                elif row["state"] == "unknown":
                    waiting.append(f"budget line {row['key']} could not be measured")
            if summary["skins"]:
                print("note: the model has a skeleton; check its motion with rig-motion-check before use")
    gate, manifest = find_gate_pass(args.project, digest)
    if gate == "pass":
        print(f"gltf-gate manifest for this exact file says pass: {manifest}")
        reasons = [r for r in reasons if " is over the " not in r]  # the gate holds the written waivers
    elif gate == "fail":
        reasons.append(f"gltf-gate manifest for this file says fail ({manifest})")
    else:
        waiting.append("the full gate has not passed for this file (validator and render check): run gltf-gate check on it"
                       if gate is None else f"gltf-gate manifest says '{gate}' ({manifest})")

    status = "rejected" if reasons else ("waiting for gate" if waiting else "accepted")
    if kind not in ("glb", "gltf"):
        # A failed download is not the generated model: the approval is not used up by it.
        record.update({"last_bad_download": str(pathlib.Path(args.file).resolve()), "judged_at": now(), "status": "bad download", "reasons": reasons})
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"record updated: {path}. Download the same result again; a NEW generation needs a new approval.")
        print("RESULT fail: rejected: " + "; ".join(reasons))
        return 1
    record.update({"file": str(pathlib.Path(args.file).resolve()), "sha256": digest, "judged_at": now(), "status": status,
                   "profile": args.profile, "reasons": reasons, "waiting": waiting,
                   "triangles": summary["triangles_in_scene"] if summary else None,
                   "bounds_size_m": summary["bounds_m"]["size"] if summary and summary["bounds_m"] else None})
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"record updated: {path} (provider {record['provider']}, stated cost {record['stated_cost']})")
    if reasons:
        print("RESULT fail: rejected: " + "; ".join(reasons))
        return 1
    if waiting:
        print("RESULT not verified: " + "; ".join(waiting))
        return 2
    print("RESULT pass")
    return 0


def cmd_list(args):
    folder = ledger(args.project)
    records = []
    for path in sorted(folder.glob("t3d-*.json")) if folder.is_dir() else []:
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            print(f"unreadable record: {path}")
    for r in records:
        print(f"{r.get('id')}  {r.get('status'):<17} {r.get('provider')}  cost: {r.get('stated_cost')}  file: {r.get('file') or '-'}")
    print(f"{len(records)} approvals recorded" if records else "no approvals recorded: nothing was spent through this skill")
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=".", help="folder that holds .mstack/ (default: current folder)")
    sub = parser.add_subparsers(dest="command", required=True)
    approve = sub.add_parser("approve", help="record the user's yes for one generation")
    approve.add_argument("--provider", required=True)
    approve.add_argument("--cost", required=True, help='the cost as stated to the user, for example "about 0.40 USD per model"')
    approve.add_argument("--prompt", required=True)
    approve.add_argument("--user-approved", action="store_true", help="pass only after the user said yes to this provider and cost")
    accept = sub.add_parser("accept", help="accept or reject the downloaded model")
    accept.add_argument("file")
    accept.add_argument("--id", required=True, help="approval id printed by 'approve'")
    accept.add_argument("--profile", required=True, help="budget profile, for example quest-webxr, phone-ar or desktop-web")
    accept.add_argument("--budgets", type=pathlib.Path, default=BUDGETS)
    sub.add_parser("list", help="show the ledger")
    args = parser.parse_args()
    return {"approve": cmd_approve, "accept": cmd_accept, "list": cmd_list}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
