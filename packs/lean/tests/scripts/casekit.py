"""Shared helper for the script tests of the mstack-lean pack.

Each *_cases.py file builds a made-up home folder, project and transcripts in a new run folder, runs one skill's
script on them, and compares the exit code and the printed result with what is expected. Nothing here reads the
real home folder, calls a model or uses the network.
"""
import datetime
import json
import pathlib
import re
import subprocess
import sys

SKILLS = pathlib.Path(__file__).resolve().parent.parent.parent / "skills"


def slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", str(pathlib.Path(path).resolve()))


def turn(mid, inp, read, write, out, ts="2026-11-20T10:00:00Z", tools=(), cwd="/work/shop"):
    """One assistant record as Claude Code writes it. tools: tool names used in this message."""
    content = [{"type": "text", "text": "made-up reply"}]
    content += [{"type": "tool_use", "id": f"{mid}-{i}", "name": t, "input": {}} for i, t in enumerate(tools)]
    return {"type": "assistant", "timestamp": ts, "cwd": cwd, "uuid": f"u-{mid}",
            "message": {"id": mid, "role": "assistant", "content": content,
                        "usage": {"input_tokens": inp, "cache_read_input_tokens": read,
                                  "cache_creation_input_tokens": write, "output_tokens": out}}}


def user(text="made-up question", ts="2026-11-20T10:00:00Z", cwd="/work/shop"):
    return {"type": "user", "timestamp": ts, "cwd": cwd, "message": {"role": "user", "content": text}}


class Cases:
    def __init__(self, title, folder):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.title = title
        self.root = pathlib.Path(folder).resolve() / f"run-{stamp}"
        self.root.mkdir(parents=True, exist_ok=False)
        self.count = 0
        self.wrong = 0
        print(f"#### {title}  (inputs in {self.root})")

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def jsonl(self, name, rows):
        return self.write(name, "".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows))

    def json(self, name, data):
        return self.write(name, json.dumps(data, indent=2) + "\n")

    def run(self, label, script, args, want, contains=(), absent=(), cwd=None, timeout=60):
        """Run one case. want is the expected exit code; contains and absent are checked in stdout."""
        out = subprocess.run([sys.executable, str(script), *[str(a) for a in args]], capture_output=True, text=True,
                             cwd=str(cwd or self.root), timeout=timeout)
        lines = [l for l in out.stdout.splitlines() if l.strip()]
        last = lines[-1] if lines else ""
        faults = []
        if out.returncode != want:
            faults.append(f"exit {out.returncode}, want {want}")
        if not last.startswith("RESULT "):
            faults.append("last line is not a RESULT line")
        faults += [f"missing text: {c!r}" for c in contains if c not in out.stdout]
        faults += [f"unexpected text: {a!r}" for a in absent if a in out.stdout]
        if "Traceback" in out.stderr:
            faults.append("the script crashed: " + out.stderr.strip().splitlines()[-1])
        self.count += 1
        self.wrong += bool(faults)
        print(f"{'BAD ' if faults else 'ok  '}{label}: exit {out.returncode} (want {want})")
        print(f"      {last[:230]}")
        for fault in faults:
            print(f"      -> {fault}")
        return out

    def check(self, label, ok, detail=""):
        """Record a check that is not a script run (for example: a file was or was not written)."""
        self.count += 1
        self.wrong += not ok
        print(f"{'ok  ' if ok else 'BAD '}{label}{': ' + detail if detail else ''}")

    def done(self):
        print(f"{self.title}: {self.count} run, {self.wrong} wrong")
        return 1 if self.wrong else 0
