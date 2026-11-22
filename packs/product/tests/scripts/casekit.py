"""Small helper shared by the mstack-product script tests. Python standard library only.

Each case runs one script command in a throwaway project and compares the exit code with the expected one.
A case may also require a piece of text in the output, so a right exit code for the wrong reason is caught.
"""
import json
import pathlib
import subprocess
import sys


class Cases:
    def __init__(self, script, folder, name):
        self.script = str(pathlib.Path(script).resolve())
        self.folder = pathlib.Path(folder).resolve()
        self.name = name
        self.ran = 0
        self.wrong = 0
        if self.folder.exists():
            sys.exit(f"refusing: {self.folder} already exists; give a new folder")
        self.folder.mkdir(parents=True)

    def write(self, relative, content):
        """Write a fixture file. Dicts and lists are written as JSON."""
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, (dict, list)):
            content = json.dumps(content, indent=2) + "\n"
        path.write_text(content, encoding="utf-8")
        return path

    def run(self, label, want, *args, expect=None, absent=None):
        """Run the script with args inside the folder. `expect` must appear in the output, `absent` must not."""
        done = subprocess.run([sys.executable, self.script, *[str(a) for a in args]],
                              cwd=self.folder, capture_output=True, text=True, timeout=120)
        out = done.stdout + done.stderr
        problems = []
        if done.returncode != want:
            problems.append(f"exit {done.returncode}, want {want}")
        if expect is not None and expect not in out:
            problems.append(f"output lacks '{expect}'")
        if absent is not None and absent in out:
            problems.append(f"output contains '{absent}'")
        self.ran += 1
        if problems:
            self.wrong += 1
            print(f"BAD  {label}: {'; '.join(problems)}")
            for line in out.strip().splitlines()[-4:]:
                print("       " + line)
        else:
            print(f"ok   exit {done.returncode} | {label}")
        return out

    def check(self, label, condition):
        """Record a check made by the test itself (a file exists, a value was written)."""
        self.ran += 1
        if condition:
            print(f"ok   | {label}")
        else:
            self.wrong += 1
            print(f"BAD  | {label}")

    def done(self):
        print(f"{self.name} cases: {self.ran} run, {self.wrong} wrong")
        sys.exit(1 if self.wrong else 0)
