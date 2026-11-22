"""Shared helper for the mstack-ops script tests. Python standard library only.

Each *_cases.py file builds its own input in a NEW folder, runs one skill's script on it and compares the
exit code and some of the printed text with what is expected. Nothing here talks to a network other than
127.0.0.1, and nothing is installed.
"""
import pathlib
import subprocess
import sys

OPS = pathlib.Path(__file__).resolve().parent.parent.parent


def script(skill, name):
    return str(OPS / "skills" / skill / "scripts" / name)


def new_folder(raw):
    folder = pathlib.Path(raw).resolve()
    if folder.exists():
        sys.exit(f"refusing: {folder} already exists; give a new folder")
    folder.mkdir(parents=True)
    return folder


def run(path, *args, cwd=None, timeout=120):
    done = subprocess.run([sys.executable, path, *map(str, args)], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return done.returncode, done.stdout + done.stderr


class Cases:
    def __init__(self, name):
        self.name, self.count, self.wrong = name, 0, 0

    def check(self, label, got, want, out="", has=(), lacks=(), last=None):
        """Compare an exit code, and optionally text that must or must not be printed, and the last line's start."""
        self.count += 1
        problems = []
        if got != want:
            problems.append(f"exit {got}, want {want}")
        for text in has:
            if text not in out:
                problems.append(f"output lacks {text!r}")
        for text in lacks:
            if text in out:
                problems.append(f"output must not contain {text!r}")
        lines = [line for line in out.strip().splitlines() if line.strip()]
        if last is not None and not (lines and lines[-1].startswith(last)):
            problems.append(f"last line is {lines[-1] if lines else '(nothing)'!r}, want it to start with {last!r}")
        if problems:
            self.wrong += 1
            print(f"BAD  {label}: " + "; ".join(problems))
            for line in lines[-6:]:
                print("       | " + line)
        else:
            print(f"ok   {label}: exit {got}")

    def finish(self):
        print(f"{self.name} cases: {self.count} run, {self.wrong} wrong")
        return 1 if self.wrong else 0
