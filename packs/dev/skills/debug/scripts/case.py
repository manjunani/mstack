#!/usr/bin/env python3
"""Keep a debugging case on disk so that the order cannot be skipped: reproduce, explain, then fix.

  open        start a case: the symptom in the user's words and one command that shows it
  run         run the reproduction and record whether it fails. Before a fix it is expected to fail
              (that is the proof the bug is caught); after "fix" it is expected to pass
  clean-run   run the reproduction in a fresh checkout of HEAD, to learn whether uncommitted or
              untracked files are part of the cause. Your working folder is not touched
  hypo add    write down one possible cause
  hypo rule   mark a hypothesis confirmed or rejected, with the evidence
  fix         record that a fix was applied for a confirmed hypothesis. Refused until the reproduction
              was seen failing, and refused after three fixes that did not work
  rethink     after three failed fixes: record what the user decided, which allows three more
  close       end the case with the cause (it has to cite file:line) once the reproduction passes,
              or with --diagnosis-only when the user wants the cause and no fix
  status      show the case and what is missing

The case is .mstack/debug/<name>.json. Every run stores exit code, last lines, commit and time.

Exit codes: 0 = the step did what this stage expects, 1 = it did not (not reproduced, fix did not work,
cause cites a line that does not exist), 2 = not verified or blocked (wrong order, command cannot run,
three failed fixes). The last line is the RESULT.
This script runs the reproduction command it was given and writes only under .mstack/.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time

def _find_git():
    """The git program: MSTACK_GIT when set, otherwise the first git that runs. On macOS /usr/bin/git is
    an xcrun shim that fails inside a sandbox (it cannot write its cache), so the real binaries come next."""
    if os.environ.get("MSTACK_GIT"):
        return os.environ["MSTACK_GIT"]
    for candidate in ("git", "/Applications/Xcode.app/Contents/Developer/usr/bin/git",
                      "/Library/Developer/CommandLineTools/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git"):
        try:
            if subprocess.run([candidate, "--version"], capture_output=True, timeout=10).returncode == 0:
                return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    return "git"


GIT = _find_git()
STATE = ".mstack"
FOLDER = "debug"
SCOPE = ["--", ".", f":(exclude){STATE}"]
LIMIT = 3
CITE = re.compile(r"([\w./\-]+\.[A-Za-z0-9]+):(\d+)")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def git(root, *args):
    try:
        out = subprocess.run([GIT, "-C", str(root), *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return out.returncode, out.stdout if out.returncode == 0 else out.stdout + out.stderr


def run_shell(command, cwd, timeout):
    begin = time.monotonic()
    try:
        proc = subprocess.Popen(command, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", start_new_session=True)
    except OSError as exc:
        return 127, str(exc), 0.0
    try:
        out, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        out, _ = proc.communicate()
        out, code = (out or "") + f"\n(timed out after {timeout} seconds)", None
    return code, out or "", round(time.monotonic() - begin, 1)


def code_state(root):
    """(commit, fingerprint of commit plus uncommitted changes, dirty)."""
    code, head = git(root, "rev-parse", "HEAD")
    head = head.strip() if code == 0 else "no-commit"
    _, status = git(root, "status", "--porcelain=v1", "-uall", *SCOPE)
    _, diff = git(root, "diff", "HEAD", *SCOPE)
    digest = hashlib.sha256((head + status + diff).encode("utf-8", "replace")).hexdigest()[:16]
    return head, digest, bool(status.strip())


def folder(root):
    path = root / STATE / FOLDER
    path.mkdir(parents=True, exist_ok=True)
    ignore = root / STATE / ".gitignore"
    known = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    if f"{FOLDER}/" not in known:
        with ignore.open("a", encoding="utf-8") as handle:
            handle.write(f"{FOLDER}/\n")
    return path


def load(root, name=None):
    base = root / STATE / FOLDER
    if not name:
        pointer = base / "current"
        name = pointer.read_text(encoding="utf-8").strip() if pointer.exists() else ""
    path = base / f"{name}.json"
    if not name or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save(root, case):
    base = folder(root)
    path = base / f"{case['name']}.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    (base / "current").write_text(case["name"] + "\n", encoding="utf-8")


def failed_since_rethink(case):
    start = case["rethinks"][-1]["after_attempt"] if case["rethinks"] else 0
    return [a for a in case["attempts"] if a["n"] > start and a["status"] == "failed"]


def open_attempt(case):
    return next((a for a in case["attempts"] if a["status"] == "open"), None)


def need(root, args):
    case = load(root, getattr(args, "name", None))
    if case is None:
        print("RESULT blocked: no case. Start one: case.py open --symptom \"...\" --repro \"<command>\"")
    return case


def cmd_open(root, args):
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", args.name or args.symptom.lower())[:40].strip("-") or "case"
    if (root / STATE / FOLDER / f"{name}.json").exists():
        print(f"RESULT blocked: a case named {name} exists. Continue it (case.py status --name {name}) or pick another --name")
        return 2
    if len(args.symptom.strip()) < 10:
        print("RESULT blocked: the symptom needs a full sentence: what happens, and what should happen")
        return 2
    case = {"name": name, "symptom": args.symptom.strip(), "repro": args.repro, "expect_text": args.expect_text,
            "opened": now(), "state": "open", "seen_failing": False, "runs": [], "hypotheses": [], "attempts": [],
            "rethinks": [], "cause": None}
    save(root, case)
    print(f"case {name} opened")
    print(f"  symptom: {case['symptom']}")
    print(f"  reproduction: {case['repro']}")
    print("next: case.py run   (it has to fail on this symptom before anything is fixed)")
    print("RESULT pass")
    return 0


def do_run(root, case, cwd, timeout, where):
    code, output, seconds = run_shell(case["repro"], cwd, timeout)
    commit, state, dirty = code_state(root)
    fails = code != 0
    wanted = case.get("expect_text")
    entry = {"at": now(), "where": where, "exit_code": code, "seconds": seconds, "fails": fails,
             "symptom_seen": fails and (not wanted or wanted in output), "commit": commit, "code_state": state,
             "dirty": dirty, "tail": output.strip().splitlines()[-15:]}
    case["runs"].append(entry)
    return entry


def cmd_run(root, args):
    case = need(root, args)
    if case is None:
        return 2
    if case["state"] != "open":
        print(f"RESULT blocked: case {case['name']} is closed ({case['state']})")
        return 2
    attempt = open_attempt(case)
    expect = args.expect or ("pass" if attempt else "fail")
    entry = do_run(root, case, root, args.timeout, "working folder")
    shown = "timed out" if entry["exit_code"] is None else f"exit {entry['exit_code']}"
    print(f"reproduction: {case['repro']}")
    print(f"  {shown} in {entry['seconds']}s on commit {entry['commit'][:12]}{' with uncommitted changes' if entry['dirty'] else ''}")
    print("--- last lines:")
    print("\n".join(entry["tail"]))
    if entry["exit_code"] in (126, 127):
        case["runs"].pop()
        save(root, case)
        print("RESULT not verified: the reproduction command could not be run; nothing was recorded")
        return 2
    entry["expected"] = expect
    if expect == "fail":
        if entry["symptom_seen"]:
            case["seen_failing"] = True
            save(root, case)
            print("the reproduction FAILS on the stated symptom: the bug is caught by a repeatable command")
            print("RESULT pass")
            return 0
        save(root, case)
        if entry["fails"]:
            print(f"RESULT fail: it fails, but the output lacks '{case['expect_text']}'; this is another failure, not the stated symptom")
        else:
            print("RESULT fail: not reproduced: the command passes, so it does not show the bug. Change the reproduction (case.py open with a new --name)")
        return 1
    if not entry["fails"]:
        if attempt:
            attempt["status"] = "worked"
        save(root, case)
        print("the reproduction PASSES" + (f" with fix attempt {attempt['n']}" if attempt else ""))
        print("RESULT pass")
        return 0
    if attempt:
        attempt["status"] = "failed"
    save(root, case)
    failed = len(failed_since_rethink(case))
    print(f"the reproduction still FAILS" + (f": fix attempt {attempt['n']} did not work ({failed} of {LIMIT} failed)" if attempt else ""))
    if failed >= LIMIT:
        print(f"{LIMIT} fixes have failed. Stop fixing. The picture of the cause is wrong; show the user what was tried and ask how to go on.")
    print("RESULT fail: the reproduction still fails")
    return 1


def cmd_clean(root, args):
    case = need(root, args)
    if case is None:
        return 2
    code, _ = git(root, "rev-parse", "HEAD")
    if code != 0:
        print("RESULT blocked: no commit to check out")
        return 2
    path = folder(root) / f"clean-{case['name']}-{os.getpid()}"
    code, out = git(root, "worktree", "add", "--detach", str(path), "HEAD")
    if code != 0:
        print(out.strip())
        print("RESULT not verified: git could not create a clean checkout")
        return 2
    try:
        entry = do_run(root, case, path, args.timeout, "clean checkout of HEAD")
    finally:
        code, out = git(root, "worktree", "remove", "--force", str(path))
        git(root, "worktree", "prune")
        removed = code == 0 and not path.exists()
    save(root, case)
    _, status = git(root, "status", "--porcelain=v1", *SCOPE)
    changed = [line[3:] for line in status.splitlines()]
    print(f"reproduction in a clean checkout of HEAD: {'timed out' if entry['exit_code'] is None else 'exit ' + str(entry['exit_code'])}")
    print("--- last lines:")
    print("\n".join(entry["tail"]))
    if not removed:
        print(f"note: the clean checkout at {path} could not be removed; remove it with: git worktree remove {path}")
    if entry["exit_code"] in (126, 127):
        print("RESULT not verified: the reproduction command could not start in the clean checkout")
        return 2
    if entry["symptom_seen"] and case.get("expect_text"):
        print("it fails the same way on committed code alone: uncommitted and untracked files are not needed to cause it")
        print("RESULT pass")
        return 0
    if not entry["fails"]:
        print("it PASSES on committed code alone: the cause needs something that exists only in the working folder")
        print(f"  uncommitted or untracked: {', '.join(changed) or '(none listed by git; look at ignored files: dependencies, build output, local config)'}")
        print("RESULT pass")
        return 0
    print("it fails in the clean checkout, but this case has no --expect-text, so the script cannot tell whether it is the same failure")
    print("(a clean checkout lacks ignored files such as installed dependencies and local config). Compare the last lines above with the symptom.")
    print("RESULT not verified: failure in the clean checkout may be a different one")
    return 2


def cmd_hypo(root, args):
    case = need(root, args)
    if case is None:
        return 2
    if args.action == "add":
        if len(args.text.strip()) < 15:
            print("RESULT blocked: a hypothesis is a full sentence: what is wrong, where, and why that gives the symptom")
            return 2
        entry = {"n": len(case["hypotheses"]) + 1, "text": args.text.strip(), "status": "open", "evidence": None, "at": now()}
        case["hypotheses"].append(entry)
        save(root, case)
        print(f"hypothesis {entry['n']} recorded: {entry['text']}")
        print("RESULT pass")
        return 0
    entry = next((h for h in case["hypotheses"] if h["n"] == args.number), None)
    if entry is None:
        print(f"RESULT blocked: there is no hypothesis {args.number}")
        return 2
    if len(args.evidence.strip()) < 15:
        print("RESULT blocked: the evidence has to say what was observed (a value, a log line, a line of code), not that it was checked")
        return 2
    entry.update(status=args.outcome, evidence=args.evidence.strip(), ruled=now())
    save(root, case)
    print(f"hypothesis {entry['n']} is {args.outcome}: {entry['evidence']}")
    print("RESULT pass")
    return 0


def cmd_fix(root, args):
    case = need(root, args)
    if case is None:
        return 2
    if not case["seen_failing"]:
        print("RESULT blocked: the reproduction has not been seen failing on the symptom. Run: case.py run")
        return 2
    hypothesis = next((h for h in case["hypotheses"] if h["n"] == args.hypothesis), None)
    if hypothesis is None or hypothesis["status"] != "confirmed":
        print(f"RESULT blocked: hypothesis {args.hypothesis} is not confirmed. A fix needs a cause with evidence: case.py hypo rule {args.hypothesis} confirmed --evidence \"...\"")
        return 2
    if open_attempt(case):
        print(f"RESULT blocked: fix attempt {open_attempt(case)['n']} has not been checked yet. Run: case.py run")
        return 2
    failed = len(failed_since_rethink(case))
    if failed >= LIMIT:
        print(f"{failed} fixes failed in a row:")
        for attempt in failed_since_rethink(case):
            print(f"  attempt {attempt['n']} (hypothesis {attempt['hypothesis']}): {attempt['text']}")
        print(f"RESULT blocked: {LIMIT} fixes have failed. No fourth fix: tell the user what was tried and ask whether the design or the "
              f"reproduction is wrong. Record the answer with: case.py rethink --note \"...\"")
        return 2
    entry = {"n": len(case["attempts"]) + 1, "text": args.text.strip(), "hypothesis": args.hypothesis, "status": "open", "at": now()}
    case["attempts"].append(entry)
    save(root, case)
    print(f"fix attempt {entry['n']} recorded ({failed + 1} of {LIMIT} before a stop): {entry['text']}")
    print("next: case.py run   (it is now expected to pass)")
    print("RESULT pass")
    return 0


def cmd_rethink(root, args):
    case = need(root, args)
    if case is None:
        return 2
    if len(failed_since_rethink(case)) < LIMIT:
        print(f"RESULT blocked: nothing to reset; fewer than {LIMIT} fixes have failed since the last rethink")
        return 2
    if len(args.note.strip()) < 20:
        print("RESULT blocked: the note has to say what the user decided and what changes in the approach")
        return 2
    case["rethinks"].append({"note": args.note.strip(), "after_attempt": len(case["attempts"]), "at": now()})
    save(root, case)
    print(f"rethink recorded; {LIMIT} more fix attempts are allowed: {args.note.strip()}")
    print("RESULT pass")
    return 0


def cmd_close(root, args):
    case = need(root, args)
    if case is None:
        return 2
    if not case["seen_failing"]:
        print("RESULT blocked: the reproduction was never seen failing on the symptom, so there is no proof the bug was caught")
        return 2
    cites = CITE.findall(args.cause)
    if not cites:
        print("RESULT blocked: the cause has to cite at least one place as file:line (for example src/pager.py:41)")
        return 2
    for path, line in cites:
        target = root / path
        if not target.is_file():
            print(f"RESULT fail: the cause cites {path}:{line}, but {path} does not exist in this project")
            return 1
        count = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
        if int(line) < 1 or int(line) > count:
            print(f"RESULT fail: the cause cites {path}:{line}, but {path} has {count} lines")
            return 1
    if args.diagnosis_only:
        case.update(state="diagnosed", cause=args.cause.strip(), closed=now())
        save(root, case)
        print(f"case {case['name']} closed as diagnosis only. cause: {case['cause']}")
        print("RESULT pass")
        return 0
    last = case["runs"][-1] if case["runs"] else None
    worked = [a for a in case["attempts"] if a["status"] == "worked"]
    if not worked or last is None or last["fails"] or last.get("where") != "working folder":
        print("RESULT not verified: the last run of the reproduction did not pass after a recorded fix. Run: case.py fix ..., then case.py run")
        return 2
    if code_state(root)[1] != last["code_state"]:
        print("RESULT not verified: the code changed after the last passing run. Run: case.py run --expect pass")
        return 2
    case.update(state="fixed", cause=args.cause.strip(), closed=now())
    save(root, case)
    print(f"case {case['name']} closed as fixed by attempt {worked[-1]['n']}. cause: {case['cause']}")
    print("RESULT pass")
    return 0


def cmd_status(root, args):
    case = load(root, args.name)
    if case is None:
        print("RESULT not verified: no case in .mstack/debug/")
        return 2
    print(f"case {case['name']} ({case['state']}), opened {case['opened']}")
    print(f"  symptom: {case['symptom']}")
    print(f"  reproduction: {case['repro']}" + (f"   expects text: {case['expect_text']}" if case.get("expect_text") else ""))
    print(f"  seen failing on the symptom: {'yes' if case['seen_failing'] else 'no'}   runs: {len(case['runs'])}")
    for h in case["hypotheses"]:
        print(f"  hypothesis {h['n']} [{h['status']}]: {h['text']}" + (f"  evidence: {h['evidence']}" if h["evidence"] else ""))
    for a in case["attempts"]:
        print(f"  fix attempt {a['n']} [{a['status']}] for hypothesis {a['hypothesis']}: {a['text']}")
    for r in case["rethinks"]:
        print(f"  rethink after attempt {r['after_attempt']}: {r['note']}")
    if case["state"] in ("fixed", "diagnosed"):
        print(f"  cause: {case['cause']}")
        print("RESULT pass")
        return 0
    failed = len(failed_since_rethink(case))
    if failed >= LIMIT:
        print(f"RESULT blocked: {LIMIT} fixes have failed; the user decides how to go on (case.py rethink)")
        return 2
    missing = []
    if not case["seen_failing"]:
        missing.append("a failing run of the reproduction")
    if not any(h["status"] == "confirmed" for h in case["hypotheses"]):
        missing.append("a confirmed hypothesis")
    missing.append("close with the cause (case.py close)")
    print("RESULT not verified: still open; missing: " + "; ".join(missing))
    return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def named(p):
        p.add_argument("--name", help="case name (default: the case used last)")
        return p

    one = sub.add_parser("open", help="start a case")
    one.add_argument("--symptom", required=True, help="what happens and what should happen, in the user's words")
    one.add_argument("--repro", required=True, help="one command that exits non-zero while the bug is there")
    one.add_argument("--expect-text", help="text the failing output has to contain, so another failure is not mistaken for the bug")
    one.add_argument("--name", help="short name for the case (default: from the symptom)")
    one.set_defaults(run=cmd_open)
    two = named(sub.add_parser("run", help="run the reproduction and record the result"))
    two.add_argument("--expect", choices=["fail", "pass"], help="default: fail before a fix was recorded, pass after")
    two.add_argument("--timeout", type=int, default=600, help="seconds (default 600)")
    two.set_defaults(run=cmd_run)
    three = named(sub.add_parser("clean-run", help="run the reproduction in a fresh checkout of HEAD"))
    three.add_argument("--timeout", type=int, default=600, help="seconds (default 600)")
    three.set_defaults(run=cmd_clean)
    four = sub.add_parser("hypo", help="add or rule on a hypothesis")
    hypo = four.add_subparsers(dest="action", required=True)
    add = named(hypo.add_parser("add", help="write down one possible cause"))
    add.add_argument("text")
    rule = named(hypo.add_parser("rule", help="confirm or reject a hypothesis with evidence"))
    rule.add_argument("number", type=int)
    rule.add_argument("outcome", choices=["confirmed", "rejected"])
    rule.add_argument("--evidence", required=True, help="what was observed")
    four.set_defaults(run=cmd_hypo)
    five = named(sub.add_parser("fix", help="record a fix for a confirmed hypothesis"))
    five.add_argument("text", help="what was changed")
    five.add_argument("--hypothesis", type=int, required=True, help="number of the confirmed hypothesis this fix follows from")
    five.set_defaults(run=cmd_fix)
    six = named(sub.add_parser("rethink", help="record the user's decision after three failed fixes"))
    six.add_argument("--note", required=True)
    six.set_defaults(run=cmd_rethink)
    seven = named(sub.add_parser("close", help="end the case with its cause"))
    seven.add_argument("--cause", required=True, help="the chain from trigger to symptom, citing file:line")
    seven.add_argument("--diagnosis-only", action="store_true", help="the user wants the cause and no fix")
    seven.set_defaults(run=cmd_close)
    eight = named(sub.add_parser("status", help="show the case"))
    eight.set_defaults(run=cmd_status)
    args = parser.parse_args()
    code, top = git(pathlib.Path.cwd(), "rev-parse", "--show-toplevel")
    root = pathlib.Path(top.strip()) if code == 0 else pathlib.Path.cwd()
    return args.run(root, args)


if __name__ == "__main__":
    sys.exit(main())
