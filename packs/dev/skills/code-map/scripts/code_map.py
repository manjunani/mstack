#!/usr/bin/env python3
"""Show who defines, calls and imports a name, what a change can break, and a short outline of a project,
so the agent reads only the files that matter.

  callers NAME        every definition and every call, import and reference of a function, class, method
                      or module, as file:line plus the line's text. NAME may be qualified (Billing.total,
                      billing::total) or a file path (src/billing/tax.py: who imports that module)
  impact [RANGE|FILES] the definitions a change touched, their callers one and two levels out, the tests that
                      reference them, and the files to read, ranked. RANGE is A..B, A...B (from the merge
                      base), or one commit (that commit against the working folder). With no argument: the
                      working folder (uncommitted and untracked files) against HEAD. Paths of existing files
                      instead of a range: every definition in those files counts as changed
  map [FOLDER]        an outline capped in size: folders, modules, top-level definitions, local import edges

How exact it is:
  Python is parsed with the ast module: every match is "exact" (method calls obj.NAME() match by name; the
  type of obj is not checked). JavaScript, TypeScript, Go, Rust, Swift and other languages are matched with
  regular expressions that skip comments and string text: those matches are marked "text match".

Skipped folders: .git and every other folder that starts with a dot, node_modules, .venv, venv, dist, build,
target, vendor, Pods, DerivedData, coverage, __pycache__, any folder with a pyvenv.cfg, and *.min.js files.
In a git repository the file list comes from git (tracked plus untracked files that are not ignored).

Options: --root FOLDER (default: the current folder; impact uses the repository top), --limit N (lines per
list, default 40), --max-lines N (map output cap, default 120).

Exit codes: 0 = pass, 1 = fail (callers: the name was not found; impact: a removed definition is still
used), 2 = not verified or blocked (not a git repository when impact needs one, a bad range, a missing
folder). The last line is the RESULT. This script reads only; it writes nothing.
"""
import argparse
import ast
import difflib
import os
import pathlib
import re
import subprocess
import sys

GIT = os.environ.get("MSTACK_GIT") or "git"
SKIP_DIRS = {"node_modules", ".venv", "venv", "dist", "build", "target", ".git", "vendor", "Pods",
             "DerivedData", "coverage", "__pycache__", "site-packages"}
MAX_BYTES = 1_000_000
MAX_FILES = 20_000
LANG = {".py": "python", ".pyi": "python",
        ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js", ".mts": "js",
        ".cts": "js", ".vue": "js", ".svelte": "js",
        ".go": "go", ".rs": "rust", ".swift": "swift",
        ".java": "other", ".kt": "other", ".kts": "other", ".scala": "other", ".rb": "other", ".php": "other",
        ".c": "other", ".h": "other", ".cc": "other", ".cpp": "other", ".hpp": "other", ".cs": "other",
        ".m": "other", ".mm": "other", ".lua": "other", ".dart": "other", ".ex": "other", ".exs": "other"}
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|specs|Tests|[A-Za-z]+Tests)/|(^|/)test_[^/]*\.py$|_test\.(py|go)$"
                       r"|\.(test|spec)\.[cm]?[jt]sx?$|Tests?\.(swift|java|kt|cs)$|_spec\.rb$|(^|/)tests\.rs$")
IDENT = r"[A-Za-z_$][\w$]*"
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "else", "new", "typeof", "await",
            "do", "try", "case", "throw", "delete", "void", "yield", "in", "of", "match", "loop", "sizeof"}

# Definition patterns: NAME is replaced by the escaped name, or by a capture group when listing definitions.
DEFS = {
    "js": [r"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?function\s*\*?\s*(NAME)\b",
           r"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?class\s+(NAME)\b",
           r"^\s*(?:export\s+)?(?:declare\s+)?(?:const|let|var)\s+(NAME)\s*(?::[^=]+)?=",
           r"^\s*(?:export\s+)?(?:declare\s+)?(?:interface|type|enum)\s+(NAME)\b",
           r"^\s+(?:(?:public|private|protected|static|async|readonly|override|get|set)\s+)*\*?(NAME)\s*(?:<[^>]*>)?\([^;]*\)\s*(?::\s*[^={;]+)?\{\s*$"],
    "go": [r"^\s*func\s+(?:\([^)]*\)\s*)?(NAME)\s*[\[(]",
           r"^\s*type\s+(NAME)\b",
           r"^\s*(?:var|const)\s+(NAME)\b"],
    "rust": [r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:default\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+\"[^\"]*\"\s+)?fn\s+(NAME)\b",
             r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|type|union|mod|static|const)\s+(NAME)\b",
             r"^\s*macro_rules!\s*(NAME)\b"],
    "swift": [r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|private|internal|fileprivate|open|static|class|final|override|mutating|nonisolated|convenience|required|lazy|weak)\s+)*(?:func|class|struct|enum|protocol|actor|typealias|var|let)\s+(NAME)\b"],
    "other": [r"\b(?:def|function|func|fn|class|struct|interface|enum|trait|module|object|sub|procedure)\s+(?:self\.)?(NAME)\b",
              r"^\s*(?:(?:public|private|protected|internal|static|final|virtual|inline|abstract|override|async|extern|const|unsigned|signed)\s+)*[\w<>\[\],.*&:]+[\s*&]+(NAME)\s*\([^;]*$"],
}
IMPORTS = {
    "js": re.compile(r"^\s*import\b|\brequire\s*\(|^\s*export\s+[^=]*\bfrom\b|\bimport\s*\("),
    "go": re.compile(r"^\s*import\b|^\s*(?:\w+\s+|_\s+|\.\s+)?\"[^\"]+\"\s*$"),
    "rust": re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:use|mod|extern\s+crate)\b"),
    "swift": re.compile(r"^\s*(?:@testable\s+)?import\b"),
    "other": re.compile(r"^\s*(?:import|#include|#import|using|require|require_relative|include|from|use)\b"),
}
STRINGS = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`")


def compile_defs(lang, name=None):
    group = re.escape(name) if name else IDENT
    return [re.compile(p.replace("NAME", group)) for p in DEFS[lang]]


DEF_ANY = {lang: compile_defs(lang) for lang in DEFS}


def git(root, *args):
    try:
        out = subprocess.run([GIT, "-C", str(root), "-c", "core.quotePath=false", *args],
                             capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return out.returncode, out.stdout.decode("utf-8", "replace") + ("" if out.returncode == 0 else out.stderr.decode("utf-8", "replace"))


def is_test(path):
    return bool(TEST_PATH.search(path))


def clip(text, width=150):
    text = text.strip()
    return text if len(text) <= width else text[:width - 3] + "..."


class Project:
    """The source files under a root, read once, with Python files parsed on first use."""

    def __init__(self, root):
        self.root = root
        self.skipped = 0
        self.files = self._list()
        self._lines, self._trees, self._defs = {}, {}, {}

    def _wanted(self, rel):
        parts = rel.split("/")
        for part in parts[:-1]:
            if part in SKIP_DIRS or part.startswith("."):
                return False
        name = parts[-1]
        return pathlib.PurePosixPath(name).suffix in LANG and not name.endswith(".min.js")

    def _list(self):
        code, out = git(self.root, "ls-files", "-co", "--exclude-standard", "--", ".")
        ignored, _ = git(self.root, "check-ignore", "-q", ".")
        if code == 0 and ignored != 0:
            candidates = sorted(set(out.splitlines()))
        else:
            candidates = []
            for here, dirs, names in os.walk(self.root):
                keep = []
                for d in sorted(dirs):
                    if d in SKIP_DIRS or d.startswith(".") or (pathlib.Path(here) / d / "pyvenv.cfg").exists():
                        self.skipped += 1
                    else:
                        keep.append(d)
                dirs[:] = keep
                for n in names:
                    candidates.append(os.path.relpath(os.path.join(here, n), self.root).replace(os.sep, "/"))
            candidates.sort()
        venvs = set()
        result = []
        for rel in candidates:
            if not self._wanted(rel):
                continue
            top = rel.split("/")
            if any("/".join(top[:i]) in venvs for i in range(1, len(top))):
                continue
            for i in range(1, len(top)):
                prefix = "/".join(top[:i])
                if prefix not in venvs and (self.root / prefix / "pyvenv.cfg").exists():
                    venvs.add(prefix)
            if any("/".join(top[:i]) in venvs for i in range(1, len(top))):
                continue
            path = self.root / rel
            try:
                if not path.is_file() or path.stat().st_size > MAX_BYTES:
                    self.skipped += 1
                    continue
            except OSError:
                continue
            result.append(rel)
            if len(result) >= MAX_FILES:
                break
        return result

    def lines(self, rel):
        if rel not in self._lines:
            try:
                data = (self.root / rel).read_bytes()
                self._lines[rel] = [] if b"\0" in data[:2048] else data.decode("utf-8", "replace").splitlines()
            except OSError:
                self._lines[rel] = []
        return self._lines[rel]

    def tree(self, rel):
        if rel not in self._trees:
            try:
                self._trees[rel] = ast.parse("\n".join(self.lines(rel)), filename=rel)
            except (SyntaxError, ValueError):
                self._trees[rel] = None
        return self._trees[rel]

    def definitions(self, rel):
        """List of (name, qualname, kind, first line, last line, top level, exact) in one file."""
        if rel in self._defs:
            return self._defs[rel]
        lang = LANG[pathlib.PurePosixPath(rel).suffix]
        found = []
        tree = self.tree(rel) if lang == "python" else None
        if tree is not None:
            def walk(node, prefix, top):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        kind = "class" if isinstance(child, ast.ClassDef) else "def"
                        qual = prefix + child.name
                        first = min([child.lineno] + [d.lineno for d in child.decorator_list])
                        found.append((child.name, qual, kind, first, child.end_lineno or child.lineno, top, True))
                        walk(child, qual + ".", False)
                    elif not isinstance(child, (ast.Lambda,)):
                        walk(child, prefix, top)
            walk(tree, "", True)
        else:
            pats = DEF_ANY["other" if lang == "python" else lang]
            if lang == "python":
                pats = [re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(" + IDENT + r")\b")]
            lines = self.lines(rel)
            starts = []
            for i, line in enumerate(lines, 1):
                if is_comment(line, lang):
                    continue
                for pat in pats:
                    m = pat.search(line)
                    if m and m.group(1) not in KEYWORDS:
                        kind = "class" if re.search(r"\b(class|struct|enum|interface|trait|protocol|type|actor)\b", line[:m.start(1)]) else "def"
                        starts.append((m.group(1), kind, i, not line[:1].isspace()))
                        break
            for n, (name, kind, first, top) in enumerate(starts):
                last = starts[n + 1][2] - 1 if n + 1 < len(starts) else len(lines)
                found.append((name, name, kind, first, max(first, last), top, False))
        self._defs[rel] = found
        return found

    def enclosing(self, rel, line):
        best = None
        for d in self.definitions(rel):
            if d[3] <= line <= d[4] and (best is None or d[3] >= best[3]):
                best = d
        return best


def is_comment(line, lang):
    s = line.strip()
    if s.startswith(("//", "/*", "*")) and lang != "python":
        return True
    if s.startswith("#") and lang in ("python", "other") and not re.match(r"#\s*(include|import|define|if)", s):
        return True
    return False


# ---------------------------------------------------------------- finding uses


def python_uses(project, rel, name):
    """Exact uses of NAME in one parsed Python file: (line, kind)."""
    tree = project.tree(rel)
    hits, in_call = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == name:
                hits.append((f.lineno, "call")); in_call.add(id(f))
            elif isinstance(f, ast.Attribute) and f.attr == name:
                hits.append((f.end_lineno or f.lineno, "method call")); in_call.add(id(f))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == name or a.name.split(".")[-1] == name:
                    hits.append((node.lineno, "import"))
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")
            if mod[-1] == name or any(a.name == name for a in node.names):
                hits.append((node.lineno, "import"))
    for node in ast.walk(tree):
        if id(node) in in_call:
            continue
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
            hits.append((node.lineno, "reference"))
        elif isinstance(node, ast.Attribute) and node.attr == name and isinstance(node.ctx, ast.Load):
            hits.append((node.end_lineno or node.lineno, "reference"))
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                if (isinstance(base, ast.Name) and base.id == name) or (isinstance(base, ast.Attribute) and base.attr == name):
                    hits.append((base.lineno, "subclass"))
    return hits


def text_uses(project, rel, name, lang):
    """Regex uses of NAME in a non-Python (or unparsable Python) file: (line, kind)."""
    word = re.compile(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])")
    module = re.compile(r"[\"'/:.]" + re.escape(name) + r"(?:\.[\w]+)?[\"']|::" + re.escape(name) + r"\b|\b" + re.escape(name) + r"::")
    imports = IMPORTS["other" if lang == "python" else lang]
    hits = []
    in_go_import = False
    for i, line in enumerate(project.lines(rel), 1):
        if is_comment(line, lang):
            continue
        if lang == "go":
            if re.match(r"^\s*import\s*\(", line):
                in_go_import = True
            elif in_go_import and line.strip() == ")":
                in_go_import = False
        code = re.sub(r"(^|\s)//.*$", "", line) if lang != "python" else re.sub(r"\s#.*$", "", line)
        looks_import = bool(imports.search(code)) and (lang != "go" or in_go_import or code.lstrip().startswith("import"))
        if looks_import and (word.search(STRINGS.sub(lambda m: m.group(0)[0] * 2, code)) or module.search(code)):
            hits.append((i, "import"))
            continue
        bare = STRINGS.sub(lambda m: m.group(0)[0] * 2, code)
        m = word.search(bare)
        if not m:
            continue
        after = bare[m.end():].lstrip()
        before = bare[:m.start()].rstrip()
        if re.search(r"\b(impl|extension)$", before) or re.search(r"\bimpl\b.*\bfor$", before):
            hits.append((i, "impl"))
        elif before.endswith("new") or after.startswith(("(", "!(", "{")) and not before.endswith(("func", "fn", "function")):
            hits.append((i, "call"))
        elif before.endswith("<") and lang == "js":
            hits.append((i, "call"))
        else:
            hits.append((i, "reference"))
    return hits


def find(project, name, module_stem=None):
    """All definitions and uses of NAME. Returns (defs, uses); each item is a dict."""
    defs, uses = [], []
    for rel in project.files:
        lang = LANG[pathlib.PurePosixPath(rel).suffix]
        lines = project.lines(rel)
        if not lines:
            continue
        exact = lang == "python" and project.tree(rel) is not None
        # cheap filter first
        if not any(name in line for line in lines):
            continue
        def_lines = set()
        if exact:
            for d in project.definitions(rel):
                if d[0] == name:
                    at = _def_line(project, rel, d)
                    defs.append(dict(file=rel, line=at, at=at, kind=d[2], qual=d[1], exact=True, text=lines[at - 1]))
                    def_lines.add(at)
            raw = python_uses(project, rel, name)
        else:
            pats = compile_defs("other" if lang == "python" else lang, name)
            if lang == "python":
                pats = [re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+" + re.escape(name) + r"\b")]
            for i, line in enumerate(lines, 1):
                if is_comment(line, lang):
                    continue
                if any(p.search(line) for p in pats):
                    kind = "class" if re.search(r"\b(class|struct|enum|interface|trait|protocol|type|actor)\s+" + re.escape(name), line) else "def"
                    defs.append(dict(file=rel, line=i, at=i, kind=kind, qual=name, exact=False, text=line))
                    def_lines.add(i)
            raw = text_uses(project, rel, name, lang)
        seen = set()
        for line, kind in sorted(raw):
            if line in def_lines or (line, kind) in seen or line in {s[0] for s in seen}:
                continue
            seen.add((line, kind))
            enc = project.enclosing(rel, line)
            uses.append(dict(file=rel, line=line, kind=kind, exact=exact, text=lines[line - 1] if line <= len(lines) else "",
                             inside=enc[1] if enc else None, inside_name=enc[0] if enc else None))
    return defs, uses


def _def_line(project, rel, d):
    """The line of the def/class keyword (decorators come first in the span)."""
    lines = project.lines(rel)
    for i in range(d[3], min(d[4], len(lines)) + 1):
        if re.match(r"^\s*(async\s+)?(def|class)\s+" + re.escape(d[0]) + r"\b", lines[i - 1]):
            return i
    return d[3]


def tag(item):
    return "exact" if item["exact"] else "text match"


def imported_names(project, rel):
    """Every module part, name and alias a parsed Python file imports."""
    tree = project.tree(rel)
    names = set()
    for node in ast.walk(tree) if tree is not None else []:
        if isinstance(node, ast.Import):
            for a in node.names:
                names.update(a.name.split("."))
                names.add(a.asname or "")
        elif isinstance(node, ast.ImportFrom):
            names.update((node.module or "").split("."))
            for a in node.names:
                names.update({a.name, a.asname or ""})
    return names


def split_linked(project, name, defs, uses):
    """Split uses into those that can reach one of the definitions and same-name uses with no import link.
    Only exact (Python) uses in other files are judged; a text match is kept, since it cannot be told apart."""
    if not defs or any(not d["exact"] for d in defs):
        return uses, []
    homes = {d["file"] for d in defs}
    stems = {name}
    for f in homes:
        p = pathlib.PurePosixPath(f)
        stems.add(p.parent.name if p.stem == "__init__" else p.stem)
    method = any("." in d["qual"] for d in defs)
    linked, other = [], []
    for u in uses:
        ok = (u["file"] in homes or not u["exact"] or (method and u["kind"] in ("method call", "reference"))
              or bool(imported_names(project, u["file"]) & stems))
        (linked if ok else other).append(u)
    return linked, other


def split_name(raw):
    """Return (symbol, qualifier, module stem or None) for a NAME argument."""
    raw = raw.strip()
    path = pathlib.PurePosixPath(raw.replace("\\", "/"))
    if path.suffix in LANG:
        return path.stem if path.stem not in ("index", "__init__", "mod") else path.parent.name, None, str(path)
    for sep in ("::", "#", "."):
        if sep in raw:
            qual, _, sym = raw.rpartition(sep)
            return sym, qual, None
    return raw, None, None


# ---------------------------------------------------------------- callers


def cmd_callers(args):
    root = pathlib.Path(args.root).resolve()
    if not root.is_dir():
        print(f"RESULT blocked: {args.root} is not a folder")
        return 2
    symbol, qualifier, module_path = split_name(args.name)
    if not re.fullmatch(IDENT, symbol or ""):
        print(f"RESULT not verified: '{args.name}' is not a name a program can use (letters, digits, _ or $)")
        return 2
    project = Project(root)
    defs, uses = find(project, symbol)
    if qualifier and not module_path:
        last = re.split(r"[.:#]+", qualifier)[-1]
        narrowed = [d for d in defs if d["qual"].endswith(f"{last}.{symbol}") or pathlib.PurePosixPath(d["file"]).stem == last]
        if narrowed:
            defs = narrowed
    if module_path:
        defs = [d for d in defs if d["file"] == module_path] + [dict(file=module_path, line=1, at=1, kind="module", qual=symbol,
                                                                     exact=True, text="(the file itself)")] if (root / module_path).is_file() else defs
        uses = [u for u in uses if u["kind"] == "import" and u["file"] != module_path]
    print(f"code-map callers: {args.name}  (root {root}, {len(project.files)} source files read, vendored folders skipped)")
    if not defs and not uses:
        names = sorted({d[0] for rel in project.files for d in project.definitions(rel)})
        close = difflib.get_close_matches(symbol, names, n=5, cutoff=0.6)
        if close:
            print("similar names that do exist: " + ", ".join(close))
        print(f"RESULT fail: no definition or use of '{symbol}' found in {len(project.files)} files")
        return 1
    limit = args.limit
    print(f"definitions ({len(defs)}):")
    for d in defs[:limit]:
        print(f"  {d['file']}:{d['at']}  {d['kind']} {d['qual']}  [{tag(d)}]  {clip(d['text'])}")
    if len(defs) > limit:
        print(f"  ... {len(defs) - limit} more not shown (--limit)")
    if not defs:
        print("  none found here: it may come from a library, or be defined in a way this script does not read")
    uses, unlinked = split_linked(project, symbol, defs, uses)
    print(f"calls, imports and references ({len(uses)}):")
    for u in uses[:limit]:
        where = f" in {u['inside']}" if u["inside"] else ""
        print(f"  {u['file']}:{u['line']}  {u['kind']}{where}  [{tag(u)}]  {clip(u['text'])}")
    if len(uses) > limit:
        print(f"  ... {len(uses) - limit} more not shown (--limit)")
    if unlinked:
        print(f"same name, but the file imports neither it nor its module, so probably another thing ({len(unlinked)}):")
        for u in unlinked[:max(5, limit // 4)]:
            print(f"  {u['file']}:{u['line']}  {u['kind']}  [{tag(u)}]  {clip(u['text'])}")
        if len(unlinked) > max(5, limit // 4):
            print(f"  ... {len(unlinked) - max(5, limit // 4)} more not shown")
    tests = sorted({u["file"] for u in uses if is_test(u["file"])})
    files = []
    for item in defs + [u for u in uses if not is_test(u["file"])]:
        if item["file"] not in files:
            files.append(item["file"])
    files += tests
    print(f"tests that reference it ({len(tests)}): {', '.join(tests[:limit]) if tests else 'none found'}"
          f"{' ...' if len(tests) > limit else ''}")
    print(f"files to read ({len(files)}): {', '.join(files[:limit])}{' ...' if len(files) > limit else ''}")
    n_exact = sum(1 for x in defs + uses if x["exact"])
    n_text = len(defs) + len(uses) - n_exact
    users = len({u['file'] for u in uses})
    print(f"RESULT pass: {len(defs)} definition{'s' * (len(defs) != 1)}, {len(uses)} use{'s' * (len(uses) != 1)} "
          f"in {users} file{'s' * (users != 1)} (exact: {n_exact}, text match: {n_text})"
          + (f"; {len(unlinked)} same-name uses set apart" if unlinked else ""))
    return 0


# ---------------------------------------------------------------- impact

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_diff(text):
    """Map new path -> {"old": old path or None, "new_lines": [...], "old_lines": [...]}."""
    files, cur = {}, None
    old_path = None
    for line in text.splitlines():
        if line.startswith("--- "):
            name = line[4:].split("\t")[0]
            old_path = None if name == "/dev/null" else (name[2:] if name.startswith("a/") else name)
        elif line.startswith("+++ "):
            name = line[4:].split("\t")[0]
            new_path = None if name == "/dev/null" else (name[2:] if name.startswith("b/") else name)
            key = new_path or old_path
            cur = files.setdefault(key, {"old": old_path, "new": new_path, "new_lines": [], "old_lines": []})
        elif cur is not None:
            m = HUNK.match(line)
            if m:
                os_, oc, ns, nc = int(m.group(1)), int(m.group(2) or "1"), int(m.group(3)), int(m.group(4) or "1")
                cur["old_lines"] += list(range(os_, os_ + oc)) if oc else []
                cur["new_lines"] += list(range(ns, ns + nc)) if nc else [max(ns, 1)]
    return files


class Snapshot(Project):
    """One file's text at a commit, so its definitions can be found without checking it out."""

    def __init__(self, root, text, rel):
        self.root, self.skipped, self.files = root, 0, [rel]
        self._lines = {rel: text.splitlines()}
        self._trees, self._defs = {}, {}


def resolve(root, ref):
    code, out = git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return out.strip() if code == 0 and out.strip() else None


def cmd_impact(args):
    start = pathlib.Path(args.root).resolve()
    code, top = git(start, "rev-parse", "--show-toplevel")
    if code != 0:
        print(f"RESULT blocked: {start} is not inside a git repository; impact needs one (callers and map do not)")
        return 2
    root = pathlib.Path(top.strip())
    targets = args.target
    files_mode = [t for t in targets if ".." not in t and (start / t).is_file()]
    base = head = None
    label = ""
    if files_mode and len(files_mode) == len(targets):
        label = "the definitions in " + ", ".join(targets)
        changed = {}
        for t in targets:
            rel = os.path.relpath((start / t).resolve(), root).replace(os.sep, "/")
            changed[rel] = {"old": rel, "new": rel, "new_lines": None, "old_lines": []}
    else:
        if len(targets) > 1:
            print(f"RESULT not verified: give one range, or only paths of existing files; got: {' '.join(targets)}")
            return 2
        spec = targets[0] if targets else None
        if spec is None:
            base, label = "HEAD", "working folder against HEAD"
        elif "..." in spec:
            a, b = spec.split("...", 1)
            ra, rb = resolve(root, a or "HEAD"), resolve(root, b or "HEAD")
            if ra and rb:
                code, mb = git(root, "merge-base", ra, rb)
                base, head = (mb.strip() if code == 0 else None), rb
            label = spec
        elif ".." in spec:
            a, b = spec.split("..", 1)
            base, head = resolve(root, a or "HEAD"), resolve(root, b or "HEAD")
            label = spec
        else:
            base, label = resolve(root, spec), f"{spec} against the working folder"
            if base is None and not (start / spec).exists():
                print(f"RESULT not verified: '{spec}' is neither a commit, a range nor an existing file")
                return 2
        if base is None or (spec and ".." in spec and head is None):
            if resolve(root, "HEAD") is None:
                print("RESULT blocked: the repository has no commit yet, so there is nothing to compare with")
            else:
                print(f"RESULT not verified: bad range '{spec}': a side is not a commit git knows")
            return 2
        diff_args = ["diff", "-U0", "--no-color", "--no-ext-diff", "-M", base] + ([head] if head else []) + ["--", "."]
        code, out = git(root, *diff_args)
        if code != 0:
            print(f"RESULT not verified: git diff failed: {clip(out, 200)}")
            return 2
        changed = parse_diff(out)
        if head is None:
            _, untracked = git(root, "ls-files", "--others", "--exclude-standard", "--", ".")
            for rel in untracked.splitlines():
                changed.setdefault(rel, {"old": None, "new": rel, "new_lines": None, "old_lines": []})

    project = Project(root)
    print(f"code-map impact: {label}  (root {root}, {len(changed)} file{'s' * (len(changed) != 1)} changed)")
    if head:
        print("note: callers are searched in the working folder as it is now, not at the end of the range")

    touched, removed, other_files = [], [], []
    for rel, info in sorted(changed.items(), key=lambda kv: kv[0] or ""):
        new_rel, old_rel = info["new"], info["old"]
        suffix = pathlib.PurePosixPath(new_rel or old_rel).suffix
        if suffix not in LANG or (new_rel and not project._wanted(new_rel)):
            other_files.append(rel)
            continue
        new_defs = []
        if new_rel:
            if head:
                code, text = git(root, "show", f"{head}:{new_rel}")
                snap = Snapshot(root, text if code == 0 else "", new_rel)
            else:
                snap = project
            new_defs = snap.definitions(new_rel)
            lines = info["new_lines"]
            for d in new_defs:
                if lines is None or any(d[3] <= n <= d[4] for n in lines):
                    touched.append(dict(file=new_rel, line=d[3], name=d[0], qual=d[1], kind=d[2], exact=d[6], how="changed"))
        if old_rel and info["old_lines"]:
            code, text = git(root, "show", f"{base}:{old_rel}")
            if code == 0:
                old = Snapshot(root, text, old_rel)
                still = {d[1] for d in new_defs}
                for d in old.definitions(old_rel):
                    if d[1] not in still and any(d[3] <= n <= d[4] for n in info["old_lines"]):
                        removed.append(dict(file=old_rel, line=d[3], name=d[0], qual=d[1], kind=d[2], exact=d[6], how="removed"))
    # keep the innermost changes only when a class and its method both changed: list both, they are separate names
    all_changed = touched + removed
    print(f"changed definitions ({len(all_changed)}):")
    for c in all_changed[:args.limit]:
        print(f"  {c['file']}:{c['line']}  {c['how']}  {c['kind']} {c['qual']}  [{tag(c)}]")
    if len(all_changed) > args.limit:
        print(f"  ... {len(all_changed) - args.limit} more not shown (--limit)")
    if other_files:
        print(f"changed files with no definitions read: {', '.join(other_files[:args.limit])}")
    if not all_changed:
        print("RESULT pass: nothing to trace; no definition in a source file changed" if changed else "RESULT pass: nothing changed")
        return 0

    score, reasons = {}, {}

    def rank(path, points, why):
        score[path] = score.get(path, 0) + points
        reasons.setdefault(path, [])
        if why not in reasons[path]:
            reasons[path].append(why)

    for c in all_changed:
        if c["how"] == "changed" or (root / c["file"]).is_file():
            rank(c["file"], 100, "changed")
    names = []
    for c in all_changed:
        if c["name"] not in names:
            names.append(c["name"])
    level1, tests, broken = [], {}, []
    set_apart = 0
    next_names = []
    for name in names:
        defs, uses = find(project, name)
        uses, apart = split_linked(project, name, defs, uses)
        set_apart += len(apart)
        own = {(c["file"]) for c in all_changed if c["name"] == name}
        for u in uses:
            if u["file"] in own and u["inside_name"] == name:
                continue
            level1.append((name, u))
            if is_test(u["file"]):
                tests.setdefault(u["file"], set()).add(name)
                rank(u["file"], 20, f"tests {name}")
            else:
                rank(u["file"], 30, f"{u['kind']}s {name}")
                if u["inside_name"] and u["inside_name"] not in names and u["inside_name"] not in next_names:
                    next_names.append(u["inside_name"])
        if any(c["name"] == name and c["how"] == "removed" for c in all_changed) and not defs:
            if uses:
                broken.append((name, uses))
                for u in uses:
                    rank(u["file"], 150, f"still uses removed {name}")
    level2 = []
    for name in next_names[:args.limit]:
        defs, uses = find(project, name)
        uses, apart = split_linked(project, name, defs, uses)
        set_apart += len(apart)
        for u in uses:
            if u["inside_name"] == name:
                continue
            level2.append((name, u))
            if is_test(u["file"]):
                tests.setdefault(u["file"], set()).add(name)
                rank(u["file"], 10, f"tests {name}")
            else:
                rank(u["file"], 5, f"level 2: {u['kind']}s {name}")
    if len(next_names) > args.limit:
        print(f"note: only the first {args.limit} of {len(next_names)} second-level names were followed (--limit)")

    def show(title, rows):
        print(f"{title} ({len(rows)}):")
        for name, u in rows[:args.limit]:
            where = f" in {u['inside']}" if u["inside"] else ""
            print(f"  {name} <- {u['file']}:{u['line']}  {u['kind']}{where}  [{tag(u)}]  {clip(u['text'], 110)}")
        if len(rows) > args.limit:
            print(f"  ... {len(rows) - args.limit} more not shown (--limit)")

    if set_apart:
        print(f"note: {set_apart} same-name uses in files that import neither the name nor its module were left out")
    show("callers, level 1", level1)
    show("callers, level 2", level2)
    print(f"tests that reference them ({len(tests)}):")
    for path in sorted(tests)[:args.limit]:
        print(f"  {path}  ({', '.join(sorted(tests[path]))})")
    if len(tests) > args.limit:
        print(f"  ... {len(tests) - args.limit} more not shown (--limit)")
    if not tests:
        print("  none found: no test file names a changed definition or a direct caller")
    ranked = sorted(score, key=lambda p: (-score[p], p))
    print(f"files to read, most important first ({len(ranked)} of {len(project.files)} source files):")
    for n, path in enumerate(ranked[:args.limit], 1):
        print(f"  {n}. {path}  ({'; '.join(reasons[path][:3])})")
    if len(ranked) > args.limit:
        print(f"  ... {len(ranked) - args.limit} more not shown (--limit)")
    if broken:
        for name, live in broken:
            places = ", ".join(f"{u['file']}:{u['line']}" for u in live[:5])
            print(f"BROKEN {name} was removed and is defined nowhere now, but is still used at {places}")
        name, live = broken[0]
        print(f"RESULT fail: removed {name} is still used in {len(live)} place{'s' * (len(live) != 1)}"
              + (f" (and {len(broken) - 1} more removed names)" if len(broken) > 1 else ""))
        return 1
    print(f"RESULT pass: {len(all_changed)} changed definition{'s' * (len(all_changed) != 1)}, {len(level1)} direct "
          f"use{'s' * (len(level1) != 1)}, {len(level2)} second-level, {len(tests)} test file{'s' * (len(tests) != 1)}, "
          f"{len(ranked)} files to read")
    return 0


# ---------------------------------------------------------------- map


def module_index(files):
    index = {}
    for rel in files:
        p = pathlib.PurePosixPath(rel)
        if p.suffix not in (".py", ".pyi"):
            continue
        parts = list(p.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for i in range(len(parts)):
            index.setdefault(".".join(parts[i:]), rel)
    return index


def python_edges(project, rel, index, local):
    tree = project.tree(rel)
    if tree is None:
        return set()
    here = list(pathlib.PurePosixPath(rel).parent.parts)
    out = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = here[:len(here) - (node.level - 1)] if node.level > 1 else here
                base = ".".join(up + ([base] if base else []))
            names = [f"{base}.{a.name}" if base else a.name for a in node.names] + ([base] if base else [])
        for n in names:
            target = index.get(n)
            if target and target != rel and target in local:
                out.add(target)
                break
    return out


def js_edges(project, rel, local):
    out = set()
    here = pathlib.PurePosixPath(rel).parent
    for line in project.lines(rel):
        for m in re.finditer(r"(?:from\s+|require\s*\(\s*|import\s*\(\s*|^\s*import\s+)[\"'](\.{1,2}/[^\"']+)[\"']", line):
            raw = os.path.normpath(str(here / m.group(1))).replace(os.sep, "/")
            for cand in [raw] + [raw + e for e in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")] + \
                        [raw + "/index" + e for e in (".ts", ".tsx", ".js", ".jsx")]:
                if cand in local:
                    out.add(cand)
                    break
    return out


def cmd_map(args):
    root = pathlib.Path(args.root).resolve()
    folder = (root / args.folder).resolve() if args.folder else root
    if not folder.is_dir():
        print(f"RESULT blocked: {args.folder} is not a folder under {root}")
        return 2
    project = Project(folder)
    files = project.files
    if not files:
        print(f"code-map map: {folder}")
        print(f"RESULT not verified: no source files found in {folder} (vendored and hidden folders are skipped)")
        return 2
    cap = max(args.max_lines, 10)
    out = []
    index = module_index(files)
    local = set(files)
    total_defs = total_edges = 0
    entries = []
    for rel in files:
        lang = LANG[pathlib.PurePosixPath(rel).suffix]
        defs = [d for d in project.definitions(rel) if d[5]]
        methods = {}
        for d in project.definitions(rel):
            if not d[5] and "." in d[1]:
                methods[d[1].split(".")[0]] = methods.get(d[1].split(".")[0], 0) + 1
        shown = []
        for d in defs:
            extra = f"({methods[d[0]]} methods)" if d[2] == "class" and methods.get(d[0]) else ""
            shown.append(("class " if d[2] == "class" else "") + d[0] + extra)
        edges = python_edges(project, rel, index, local) if lang == "python" else js_edges(project, rel, local) if lang == "js" else set()
        total_defs += len(defs)
        total_edges += len(edges)
        entries.append((rel, lang, shown, sorted(edges)))
    folders = {}
    for rel in files:
        top = rel.split("/")[0] + "/" if "/" in rel else "."
        folders[top] = folders.get(top, 0) + 1
    out.append(f"code-map map: {folder}  ({len(files)} source files, {total_defs} top-level definitions, "
               f"{total_edges} local import edges; edges for Python, JavaScript and TypeScript only)")
    out.append("folders: " + ", ".join(f"{k} {v}" for k, v in sorted(folders.items(), key=lambda kv: (-kv[1], kv[0]))[:12]))
    shown_files = 0
    for rel, lang, shown, edges in entries:
        tagtext = "" if lang == "python" else "  [text match]"
        line = f"{rel}: " + (", ".join(shown) if shown else "(no top-level definitions)")
        block = [clip(line, 160) + tagtext]
        if edges:
            block.append("    -> " + clip(", ".join(edges), 150))
        if len(out) + len(block) > cap - 2:
            break
        out += block
        shown_files += 1
    if shown_files < len(entries):
        out.append(f"... {len(entries) - shown_files} more files not shown (cap {cap} lines); run map on a sub-folder, "
                   f"or callers <name> for one name")
    print("\n".join(out))
    print(f"RESULT pass: {len(files)} files, {total_defs} top-level definitions, {total_edges} import edges; "
          f"{shown_files} files shown in {len(out)} lines (cap {cap})")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".", help="project folder (default: current folder)")
    common.add_argument("--limit", type=int, default=40, help="lines shown per list (default 40)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("callers", parents=[common], help="definitions and uses of a name")
    p.add_argument("name")
    p = sub.add_parser("impact", parents=[common], help="what a change touches, its callers and tests")
    p.add_argument("target", nargs="*", help="A..B, A...B, one commit, or file paths; default: working folder vs HEAD")
    p = sub.add_parser("map", parents=[common], help="short outline of a folder")
    p.add_argument("folder", nargs="?", default="")
    p.add_argument("--max-lines", type=int, default=120, help="output cap in lines (default 120)")
    args = parser.parse_args()
    args.limit = max(1, args.limit)
    return {"callers": cmd_callers, "impact": cmd_impact, "map": cmd_map}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
