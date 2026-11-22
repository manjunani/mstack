#!/usr/bin/env python3
"""Compare the environment variable NAMES that code reads with the names that are documented and set.

  envnames.py [--root DIR] [--example FILE] [--set-names FILE] [--ignore NAME ...] [--json]

  code      every source file under --root is scanned for reads such as process.env.X, process.env["X"],
            import.meta.env.X, os.environ["X"], os.environ.get("X"), os.getenv("X"), std::env::var("X"),
            env!("X"), option_env!("X"), os.Getenv("X") and ENV["X"]
  example   an example env file (default: .env.example, .env.sample or .env.template under --root)
  set       an optional file listing the names set in the target: one NAME per line, NAME=... lines,
            or JSON (an object keyed by name, or a list of names or of objects with a "name" or "key")

Three lists are printed, names only:
  MISSING        read by code, not set in the target             (fails)
  UNDOCUMENTED   read by code, not in the example file           (fails)
  UNUSED         in the example or set in the target, never read (warning: a platform or tool may read it)

This script never prints, stores or compares a value. From every file it keeps only what stands left of "=".
It reads files only and contacts nothing.

Exit codes: 0 = no missing and no undocumented names, 1 = at least one, 2 = not verified or blocked
(no source files, no example file, or no list of the names set in the target).
"""
import argparse
import json
import os
import pathlib
import re
import sys

NAME = r"([A-Za-z_][A-Za-z0-9_]*)"
READS = [re.compile(p) for p in (
    r"process\.env\." + NAME,
    r"process\.env\[\s*['\"]" + NAME + r"['\"]\s*\]",
    r"import\.meta\.env\." + NAME,
    r"import\.meta\.env\[\s*['\"]" + NAME + r"['\"]\s*\]",
    r"(?:Deno|Bun)\.env\.get\(\s*['\"]" + NAME + r"['\"]",
    r"\benviron(?:\.get\(|\.pop\(|\.setdefault\(|\[)\s*['\"]" + NAME + r"['\"]",
    r"\bgetenv\(\s*['\"]" + NAME + r"['\"]",
    r"\benv::var(?:_os)?\(\s*\"" + NAME + r"\"",
    r"\b(?:option_)?env!\(\s*\"" + NAME + r"\"",
    r"\bos\.(?:Getenv|LookupEnv)\(\s*\"" + NAME + r"\"",
    r"\bENV(?:\.fetch\(|\[)\s*['\"]" + NAME + r"['\"]",
)]
DESTRUCTURE = re.compile(r"\{([^{}]*)\}\s*=\s*(?:process\.env|import\.meta\.env)\b")
DYNAMIC = [re.compile(p) for p in (
    r"process\.env\[\s*[^'\"\s\]]", r"import\.meta\.env\[\s*[^'\"\s\]]",
    r"\benviron(?:\.get\(|\[)\s*[^'\"\s\])]", r"\bgetenv\(\s*[^'\"\s)]", r"\benv::var(?:_os)?\(\s*[^\"\s)]",
)]
SOURCE = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".astro", ".py", ".rs", ".go", ".rb"}
SKIP = {"node_modules", ".git", "dist", "build", "target", ".next", ".nuxt", ".venv", "venv", "__pycache__",
        ".mstack", "vendor", "coverage", ".turbo", ".cache", ".testrun"}
PROVIDED = {"NODE_ENV", "PATH", "HOME", "PWD", "USER", "SHELL", "TMPDIR", "TERM", "LANG", "CI",
            "MODE", "DEV", "PROD", "SSR", "BASE_URL"}
EXAMPLES = (".env.example", ".env.sample", ".env.template", "env.example", ".env.dist")
ENV_LINE = re.compile(r"^\s*(#\s*)?(?:export\s+)?" + NAME + r"\s*=")
BARE = re.compile(r"^\s*" + NAME + r"\s*$")


def scan_code(root):
    """Return ({name: "file:line" of the first read}, [dynamic read places], number of files scanned)."""
    found, dynamic, count = {}, [], 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for name in sorted(files):
            path = pathlib.Path(folder, name)
            if path.suffix not in SOURCE or path.stat().st_size > 2_000_000:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            count += 1
            rel = path.relative_to(root).as_posix()
            for number, line in enumerate(text.splitlines(), 1):
                names = [m.group(1) for pattern in READS for m in pattern.finditer(line)]
                for block in DESTRUCTURE.findall(line):
                    names += [part.split(":")[0].split("=")[0].strip() for part in block.split(",")]
                for item in names:
                    if re.fullmatch(NAME[1:-1], item or ""):
                        found.setdefault(item, f"{rel}:{number}")
                if any(pattern.search(line) for pattern in DYNAMIC):
                    dynamic.append(f"{rel}:{number}")
    return found, dynamic, count


def names_from_env_file(path):
    """Names from NAME=... lines. Commented lines (# NAME=) count too. Values are never kept."""
    names = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = ENV_LINE.match(line)
        if match:
            names.add(match.group(2))
    return names


def names_from_set_file(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith(("{", "[")):
        try:
            data = json.loads(text)
        except ValueError:
            return None
        if isinstance(data, dict):
            return {k for k in data if re.fullmatch(NAME[1:-1], k)}
        names = set()
        for item in data:
            key = item if isinstance(item, str) else (item.get("name") or item.get("key")) if isinstance(item, dict) else None
            if isinstance(key, str) and re.fullmatch(NAME[1:-1], key):
                names.add(key)
        return names
    names = names_from_env_file(path)
    for line in text.splitlines():
        match = BARE.match(line)
        if match:
            names.add(match.group(1))
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="folder holding the source code (default: current folder)")
    parser.add_argument("--example", type=pathlib.Path, help="example env file (default: looked for under --root)")
    parser.add_argument("--set-names", type=pathlib.Path, help="file listing the names set in the target environment")
    parser.add_argument("--ignore", nargs="*", default=[], metavar="NAME", help="names to leave out of every list")
    parser.add_argument("--json", action="store_true", help="print the lists as JSON (names and places only)")
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        print(f"blocked: {root} is not a folder")
        return 2
    example = args.example or next((root / n for n in EXAMPLES if (root / n).is_file()), None)
    for label, path in (("example file", example), ("set-names file", args.set_names)):
        if path is not None and not path.is_file():
            print(f"blocked: {label} {path} does not exist")
            return 2
    reads, dynamic, files = scan_code(root)
    if files == 0:
        print(f"blocked: no source files found under {root}")
        return 2
    skip = PROVIDED | set(args.ignore)
    code = {n for n in reads if n not in skip}
    documented = names_from_env_file(example) - skip if example else None
    target = None
    if args.set_names:
        target = names_from_set_file(args.set_names)
        if target is None:
            print("blocked: the set-names file looks like JSON but does not parse")
            return 2
        target -= skip
    missing = sorted(code - target) if target is not None else []
    undocumented = sorted(code - documented) if documented is not None else []
    unused = sorted(((documented or set()) | (target or set())) - code)

    if args.json:
        print(json.dumps({"read_by_code": {n: reads[n] for n in sorted(code)}, "missing": missing,
                          "undocumented": undocumented, "unused": unused, "dynamic_reads": dynamic}, indent=2))
    else:
        print(f"code: {len(code)} names read in {files} source files under {root}")
        print(f"example file: {example if example else 'none found'}" + (f" ({len(documented)} names)" if example else ""))
        print(f"target names: {args.set_names} ({len(target)} names)" if target is not None else "target names: not given")
        for title, names, show_place in (("MISSING in the target (read by code, not set)", missing, True),
                                         ("UNDOCUMENTED (read by code, not in the example file)", undocumented, True),
                                         ("UNUSED (documented or set, never read by code; warning only)", unused, False)):
            print(f"{title}: {len(names)}")
            for n in names:
                print(f"  {n}" + (f"   first read at {reads[n]}" if show_place else ""))
        if dynamic:
            print(f"DYNAMIC reads the scan cannot name ({len(dynamic)}); open these places and list the names by hand:")
            for place in dynamic[:20]:
                print(f"  {place}")
        print("values: none read into memory beyond the line being parsed, none printed")

    if missing or undocumented:
        parts = ([f"{len(missing)} missing in the target"] if missing else []) + ([f"{len(undocumented)} undocumented"] if undocumented else [])
        print("RESULT fail: " + ", ".join(parts))
        return 1
    gaps = ([] if example else ["no example file, so nothing says which names are documented"]) + \
           ([] if target is not None else ["the names set in the target were not supplied, so the target side is unchecked"])
    if gaps:
        print("RESULT not verified: " + "; ".join(gaps))
        return 2
    tail = f" ({len(dynamic)} dynamic reads not resolved)" if dynamic else ""
    print(f"RESULT pass: all {len(code)} names read by code are documented and set{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
