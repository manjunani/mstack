#!/usr/bin/env python3
"""Check a Jupyter notebook as a file, and re-run a copy of it when Jupyter is there and --run is given.

  nbcheck.py <notebook.ipynb>              read the file: order, errors, hidden state, paths, secrets
  nbcheck.py <notebook.ipynb> --run        also execute a COPY top to bottom in a fresh kernel (runs its code)

From the file alone (nothing is executed):
  - cells run out of order, cells never run, and gaps in the execution counts
  - outputs that hold an error
  - hidden state, by a simple name scan: a name used in a cell before the cell that defines it, or used and
    defined nowhere in the notebook (a deleted cell). Only top-level code is scanned, not function bodies.
  - paths that exist on one machine only (/Users/..., /home/..., C:\\Users\\...)
  - text that looks like a credential in a cell or an output; the value is never printed
With --run, and only when `jupyter nbconvert` is installed: a copy is executed into --out-dir and the script
reports whether every cell ran and which text outputs differ from the saved ones. The notebook itself is never
changed. Without Jupyter, or without --run, that part is listed under "could not check" and the result is
"not verified", because reading a file cannot prove that it runs.

The report keeps three lists apart: findings, checked and fine, could not check.
Exit codes: 0 = the file checks are clean and the re-run succeeded
            1 = cells out of order, error outputs, a name used before it is defined, a machine path, a credential,
                or a cell that fails when re-run
            2 = not verified or blocked: not re-run, a cell that cannot be parsed, or a file that is not a notebook
"""
import argparse
import ast
import builtins
import json
import os
import re
import shutil
import subprocess
import sys

# --- shared block: report (the same text is in every mstack-data script) ---
class Report:
    """Keeps three lists apart: findings, checked and fine, could not check."""

    def __init__(self):
        self.fails, self.warns, self.fine, self.unchecked = [], [], [], []

    def fail(self, text):
        self.fails.append(text)

    def warn(self, text):
        self.warns.append(text)

    def ok(self, text):
        self.fine.append(text)

    def skip(self, text):
        self.unchecked.append(text)

    def as_dict(self):
        return {"findings": [{"level": "fail", "text": t} for t in self.fails] + [{"level": "warn", "text": t} for t in self.warns],
                "checked_and_fine": self.fine, "could_not_check": self.unchecked}

    def show(self):
        print(f"\nFINDINGS ({len(self.fails) + len(self.warns)})")
        for text in self.fails:
            print(f"  [fail] {text}")
        for text in self.warns:
            print(f"  [warn] {text}")
        print(f"\nCHECKED AND FINE ({len(self.fine)})")
        for text in self.fine:
            print(f"  {text}")
        print(f"\nCOULD NOT CHECK ({len(self.unchecked)})")
        for text in self.unchecked:
            print(f"  {text}")
        print()

    def finish(self, why=None):
        """Print the three lists and the RESULT line; return the exit code."""
        self.show()
        if self.fails:
            print(f"RESULT fail: {why or self.fails[0]}" + (f" (and {len(self.fails) - 1} more)" if len(self.fails) > 1 and not why else ""))
            return 1
        if self.unchecked:
            more = f" (and {len(self.unchecked) - 1} more)" if len(self.unchecked) > 1 else ""
            print(f"RESULT not verified: {self.unchecked[0]}{more}")
            return 2
        if self.warns:
            print(f"{len(self.warns)} warning(s) above do not block; report them with the result.")
        print("RESULT pass")
        return 0


def blocked(text):
    print(f"blocked: {text}")
    sys.exit(2)
# --- end of shared block ---

IPYTHON_NAMES = {"display", "get_ipython", "In", "Out", "_", "__", "___", "exit", "quit", "__file__", "__name__"}
MACHINE_PATH = re.compile(r"(/Users/|/home/|[A-Za-z]:\\\\?Users\\\\?)([^/\\\s'\"]+)")
SECRETS = (
    ("a value assigned to a name such as password, token or api_key",
     re.compile(r"(?i)\b[\w-]*(pass(word|wd)?|secret|token|api[_-]?key|access[_-]?key)[\w-]*\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']")),
    ("an access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a provider token", re.compile(r"\b(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,})")),
    ("a private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a password inside a connection address", re.compile(r"\b[a-z][a-z0-9+]*://[^\s:/@'\"]+:[^\s:/@'\"]{4,}@")),
)
PASSING_CELL_MAGICS = ("%%time", "%%timeit", "%%capture", "%%prun")


def text_of(source):
    return "".join(source) if isinstance(source, list) else str(source or "")


def python_of(source):
    """The cell's Python with IPython magics and shell lines replaced, or None when the cell is another language."""
    lines = source.splitlines()
    if lines and lines[0].lstrip().startswith("%%"):
        if not lines[0].lstrip().startswith(PASSING_CELL_MAGICS):
            return None
        lines = lines[1:]
    out = []
    for line in lines:
        stripped = line.lstrip()
        indent = line[:len(line) - len(stripped)]
        if stripped.startswith(("%", "!")) or stripped.rstrip().endswith("?"):
            out.append(indent + "pass")
        else:
            out.append(re.sub(r"=\s*[!%].*$", "= None", line))
    return "\n".join(out)


def names_of(tree):
    """Return (defined, used, star_import) for the code that runs when the cell runs. Function bodies run later and are not scanned."""
    defined, used, star = set(), set(), False

    def walk(node):
        nonlocal star
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(child.name)
                for part in child.decorator_list + child.args.defaults + [d for d in child.args.kw_defaults if d is not None]:
                    walk(ast.Expression(part))
                continue
            if isinstance(child, ast.Lambda):
                continue
            if isinstance(child, ast.ClassDef):
                defined.add(child.name)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    star = star or alias.name == "*"
                    defined.add((alias.asname or alias.name).split(".")[0])
                continue
            elif isinstance(child, ast.Name):
                (used if isinstance(child.ctx, ast.Load) else defined).add(child.id)
            elif isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Name):
                used.add(child.target.id)
            elif isinstance(child, ast.ExceptHandler) and child.name:
                defined.add(child.name)
            elif isinstance(child, (ast.Global, ast.Nonlocal)):
                defined.update(child.names)
            walk(child)

    walk(tree)
    return defined, used, star


def output_text(cell):
    parts = []
    for output in cell.get("outputs", []) or []:
        if output.get("output_type") == "stream":
            parts.append(text_of(output.get("text")))
        elif output.get("output_type") in ("execute_result", "display_data"):
            parts.append(text_of((output.get("data") or {}).get("text/plain")))
        elif output.get("output_type") == "error":
            parts.append(f"{output.get('ename')}: {output.get('evalue')}")
    return "\n".join(parts)


def rerun(notebook, out_dir, seconds, cells, report):
    jupyter = shutil.which("jupyter")
    probe = subprocess.run([jupyter, "nbconvert", "--version"], capture_output=True, text=True) if jupyter else None
    if not jupyter or probe.returncode != 0:
        report.skip("not re-run: `jupyter nbconvert` was not found on this machine. Install Jupyter in the project's own environment "
                    "(for example `python3 -m pip install nbconvert ipykernel`), or run the notebook top to bottom yourself")
        return
    if out_dir is None:
        report.skip("not re-run: Jupyter is installed, but --run was not given. Re-running executes the notebook's code; ask first, then pass --run")
        return
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(notebook))[0] + ".rerun.ipynb"
    target = os.path.join(out_dir, name)
    if os.path.exists(target):
        report.skip(f"not re-run: {target} already exists; move it or choose another --out-dir")
        return
    command = [jupyter, "nbconvert", "--to", "notebook", "--execute", f"--ExecutePreprocessor.timeout={int(seconds)}",
               "--output", name, "--output-dir", os.path.abspath(out_dir), notebook]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=seconds * max(1, len(cells)) + 120)
    except subprocess.TimeoutExpired:
        report.fail(f"the re-run did not finish within the time limit ({seconds}s per cell)")
        return
    if done.returncode != 0 or not os.path.exists(target):
        tail = " | ".join(line.strip() for line in done.stderr.strip().splitlines()[-4:])
        report.fail(f"the re-run stopped: a cell failed in a fresh kernel ({tail[:400]})")
        return
    with open(target, encoding="utf-8") as handle:
        fresh = [c for c in json.load(handle).get("cells", []) if c.get("cell_type") == "code"]
    saved = [c for c in cells if c.get("cell_type") == "code"]
    differ = [str(i) for i, (old, new) in enumerate(zip(saved, fresh), 1) if output_text(old).strip() != output_text(new).strip()]
    report.ok(f"re-run: all {len(fresh)} code cells ran top to bottom in a fresh kernel (copy at {target})")
    if differ:
        report.warn(f"text output of {len(differ)} code cell(s) differs between the saved file and the re-run: code cells {', '.join(differ[:20])}")
    else:
        report.ok("re-run: text outputs match the saved ones")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("notebook", help="the .ipynb file")
    parser.add_argument("--run", action="store_true", help="execute a copy with jupyter nbconvert (this runs the notebook's code)")
    parser.add_argument("--out-dir", default=os.path.join(".mstack", "notebook-check"), help="folder for the executed copy (default .mstack/notebook-check)")
    parser.add_argument("--timeout", type=int, default=300, help="seconds allowed per cell when re-running (default 300)")
    args = parser.parse_args()

    try:
        with open(args.notebook, encoding="utf-8") as handle:
            notebook = json.load(handle)
    except OSError as exc:
        blocked(f"cannot read {args.notebook}: {exc.strerror}")
    except ValueError as exc:
        blocked(f"{args.notebook} is not valid JSON, so it is not a notebook file: {exc}")
    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        blocked(f"{args.notebook} has no 'cells' list; notebooks older than format 4 are not read")
    cells = [c for c in notebook["cells"] if isinstance(c, dict)]
    code = [(number, c) for number, c in enumerate(cells, 1) if c.get("cell_type") == "code" and text_of(c.get("source")).strip()]
    language = ((notebook.get("metadata") or {}).get("kernelspec") or {}).get("language", "python")
    report = Report()
    print(f"NOTEBOOK CHECK {args.notebook}: {len(cells)} cells, {len(code)} code cells with content, kernel language {language}")
    print("  cell numbers count every cell from the top, starting at 1")
    if not code:
        report.fail("the notebook has no code cells with content")
        return report.finish()

    counts = [(number, c.get("execution_count")) for number, c in code]
    ran = [(number, count) for number, count in counts if isinstance(count, int)]
    never = [number for number, count in counts if not isinstance(count, int)]
    if not ran:
        report.skip("no cell carries an execution count (outputs were cleared, or it was never run), so run order cannot be read from the file")
    else:
        backwards = [f"cell {b} [{cb}] ran before cell {a} [{ca}]" for (a, ca), (b, cb) in zip(ran, ran[1:]) if cb < ca]
        if backwards:
            report.fail(f"cells were run out of order: {'; '.join(backwards[:6])}" + (f" and {len(backwards) - 6} more" if len(backwards) > 6 else ""))
        if never:
            report.warn(f"{len(never)} code cell(s) were never run: cells {', '.join(map(str, never[:20]))}")
        numbers = [count for _, count in ran]
        if not backwards and not never and numbers == list(range(1, len(numbers) + 1)):
            report.ok(f"every code cell ran once, top to bottom (counts 1 to {len(numbers)})")
        elif not backwards and numbers != list(range(numbers[0], numbers[0] + len(numbers))) or (not backwards and numbers[0] != 1):
            report.warn(f"execution counts are in order but do not run 1, 2, 3 (they are {', '.join(map(str, numbers[:12]))}{'...' if len(numbers) > 12 else ''}): "
                        "cells were re-run or deleted, so the saved outputs may not come from one clean run")

    errors = []
    for number, cell in code:
        for output in cell.get("outputs", []) or []:
            if output.get("output_type") == "error":
                errors.append(f"cell {number}: {output.get('ename')}: {str(output.get('evalue'))[:80]}")
    if errors:
        report.fail(f"{len(errors)} saved output(s) hold an error: {'; '.join(errors[:6])}")
    else:
        report.ok("no saved output holds an error")

    if language.lower() != "python":
        report.skip(f"hidden state was not scanned: the name scan reads Python, and this notebook's kernel is {language}")
    else:
        scans, unparsed, star = [], [], False
        for number, cell in code:
            python = python_of(text_of(cell.get("source")))
            if python is None:
                scans.append((number, set(), set()))
                continue
            try:
                defined, used, has_star = names_of(ast.parse(python))
            except SyntaxError:
                unparsed.append(number)
                scans.append((number, set(), set()))
                continue
            star = star or has_star
            scans.append((number, defined, used))
        known = set(dir(builtins)) | IPYTHON_NAMES
        first_defined = {}
        for number, defined, _ in scans:
            for name in defined:
                first_defined.setdefault(name, number)
        early, nowhere, seen = [], [], set()
        for number, defined, used in scans:
            for name in sorted(used - defined - seen - known):
                if name in first_defined:
                    early.append(f"cell {number} uses `{name}`, first defined in cell {first_defined[name]}")
                elif not star:
                    nowhere.append(f"cell {number} uses `{name}`")
            seen |= defined
        if early:
            report.fail(f"hidden state: {len(early)} name(s) are used above the cell that defines them, so a top-to-bottom run fails: {'; '.join(early[:8])}"
                        + (f" and {len(early) - 8} more" if len(early) > 8 else ""))
        if nowhere:
            report.warn(f"hidden state: {len(nowhere)} name(s) are used but defined nowhere in the notebook (a deleted cell, or a name set by a magic): {'; '.join(nowhere[:8])}"
                        + (f" and {len(nowhere) - 8} more" if len(nowhere) > 8 else ""))
        if not early and not nowhere:
            report.ok("name scan: every name used at the top level of a cell is defined in that cell or above it")
        if unparsed:
            report.skip(f"{len(unparsed)} cell(s) do not parse as Python and were not scanned for names: cells {', '.join(map(str, unparsed))}")
        if star:
            report.skip("a cell uses `from ... import *`, so names defined nowhere could not be told from imported ones")

    paths, secrets = [], []
    for number, cell in enumerate(cells, 1):
        source = text_of(cell.get("source"))
        if cell.get("cell_type") == "code":
            for match in MACHINE_PATH.finditer(source):
                paths.append(f"cell {number}: {match.group(1)}<name>...")
        for where, text in (("cell", source), ("output of cell", output_text(cell) if cell.get("cell_type") == "code" else "")):
            for label, pattern in SECRETS:
                if pattern.search(text):
                    secrets.append(f"{where} {number}: looks like {label}")
    if paths:
        report.fail(f"{len(paths)} path(s) exist on one machine only: {'; '.join(sorted(set(paths))[:8])}")
    else:
        report.ok("no home-folder paths in code cells")
    if secrets:
        report.fail(f"{len(secrets)} place(s) look like a credential (values not shown): {'; '.join(secrets[:8])}. Remove them, clear the outputs, and change the credential: it is in the file's history.")
    else:
        report.ok("no text that looks like a credential in cells or outputs")

    rerun(args.notebook, args.out_dir if args.run else None, args.timeout, cells, report)
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())
