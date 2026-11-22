#!/usr/bin/env python3
"""Keep decisions and lessons as short records in a plain file in the repository.

  find WORDS     show existing records that look like the same subject
  add            append a record (checks for duplicates and secrets first)
  list           list records and their status
  check          lint the file: duplicate ids, missing parts, secrets, broken supersede links

Record ids contain the date and a short hash, so two sessions writing at once cannot collide.
Exit codes: 0 = done, 1 = refused or lint failure, 2 = blocked: bad input or no file.
"""
import argparse
import datetime
import fcntl
import hashlib
import pathlib
import re
import sys

HEAD = re.compile(r"^### (?P<id>[A-Z]-[\w-]+) · (?P<date>\S+) · (?P<scope>.+)$")
SECRETS = [
    (r"AKIA[0-9A-Z]{16}", "an AWS access key"),
    (r"\bsk-[A-Za-z0-9_-]{20,}", "an API key"),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}", "a GitHub token"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}", "a Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "a private key"),
    (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.", "a signed token"),
    (r"(?i)\b(password|passwd|passphrase|secret|token|api[ _-]?key)\b\s*(is|[:=])\s*['\"]?(?=[^\s'\"]*[\d_\-!@#$%^&*])[^\s'\"]{6,}", "a credential value"),
]
STOP = set("a an the and or of to in on for with is are be it this that we use uses using not no do does".split())
KINDS = {"decision": ("D", "Decision"), "lesson": ("L", "Lesson")}
SIZE_WARNING = 100


def find_secret(text):
    for pattern, label in SECRETS:
        if re.search(pattern, text):
            return label
    return None


def stem(word):
    for suffix in ("ing", "ed", "es", "s", "d"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text):
    return {stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2}


def default_file(root, kind):
    name = "DECISIONS.md" if kind == "decision" else "LESSONS.md"
    for candidate in (root / name, root / "docs" / name, root / "docs" / name.lower()):
        if candidate.exists():
            return candidate
    return root / "docs" / name


def parse(text):
    records, current = [], None
    for number, line in enumerate(text.splitlines(), 1):
        match = HEAD.match(line)
        if match:
            current = {**match.groupdict(), "line": number, "body": [], "status": ""}
            records.append(current)
        elif current is not None:
            if line.startswith("### ") or line.startswith("## "):
                current = None
                continue
            current["body"].append(line)
            status = re.match(r"^\*\*Status:\*\*\s*(.*)$", line)
            if status:
                current["status"] = status.group(1).strip()
    for record in records:
        record["text"] = " ".join(record["body"])
    return records


def first_line(record):
    for line in record["body"]:
        match = re.match(r"^\*\*(Decision|Lesson):\*\*\s*(.*)$", line)
        if match:
            return match.group(2)
    return ""


def similar(records, text, whole=False):
    """Score records against text. Default: how alike the two statements are (for duplicates).
    whole=True: what share of the words asked for appear anywhere in the record (for searching)."""
    words = tokens(text)
    scored = []
    for record in records:
        other = tokens(record["text"] if whole else first_line(record))
        if words and other:
            shared = len(words & other)
            scored.append((shared / len(words) if whole else shared / len(words | other), record))
    return sorted(scored, key=lambda pair: -pair[0])


def cmd_find(path, args):
    if not path.exists():
        print(f"no records yet ({path} does not exist)")
        return 0
    hits = [(score, r) for score, r in similar(parse(path.read_text(encoding="utf-8")), " ".join(args.words), whole=True) if score >= 0.5][:5]
    if not hits:
        print("no similar record")
        return 0
    for score, record in hits:
        print(f"{score:.0%}  {record['id']}  [{record['status'] or 'no status'}]  {first_line(record)[:110]}")
    return 0


def cmd_add(path, args):
    prefix, label = KINDS[args.type]
    leak = find_secret(args.text + " " + args.why)
    if leak:
        print(f"RESULT fail: the text looks like it contains {leak}. Records are committed and shared; say where the secret lives, not what it is.")
        return 1
    if len(args.text.split()) < 4 or len(args.why.split()) < 3:
        print("blocked: a record needs a full sentence for the text and a reason someone else could judge by")
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        content = handle.read()
        records = parse(content)
        active = [r for r in records if r["status"].startswith("active")]
        close = [(s, r) for s, r in similar(active, args.text) if s >= 0.6 and r["id"] != args.supersedes]
        if close and not args.force:
            score, record = close[0]
            print(f"RESULT fail: {record['id']} already says nearly the same ({score:.0%} overlap): {first_line(record)[:110]}")
            print("Update or supersede that record (--supersedes ID), or pass --force if this is truly a different subject.")
            return 1
        if args.supersedes and args.supersedes not in {r["id"] for r in records}:
            print(f"blocked: no record {args.supersedes} to supersede")
            return 2
        today = datetime.date.today()
        salt = hashlib.sha256((args.text + datetime.datetime.now().isoformat()).encode()).hexdigest()[:4]
        ident = f"{prefix}-{today:%Y%m%d}-{salt}"
        if args.supersedes:
            lines, inside = content.splitlines(), False
            for i, line in enumerate(lines):
                match = HEAD.match(line)
                if match:
                    inside = match.group("id") == args.supersedes
                elif inside and line.startswith("**Status:**"):
                    lines[i] = f"**Status:** superseded by {ident}"
                    inside = False
            content = "\n".join(lines) + "\n"
        if not content.strip():
            content = f"# {'Decisions' if args.type == 'decision' else 'Lessons'}\n"
        entry = (f"\n### {ident} · {today.isoformat()} · {args.scope}\n**{label}:** {args.text.strip()}\n"
                 f"**Why:** {args.why.strip()}\n**Status:** active\n")
        handle.seek(0)
        handle.truncate()
        handle.write(content.rstrip("\n") + "\n" + entry)
    print(f"saved {ident} in {path}")
    if args.supersedes:
        print(f"marked {args.supersedes} as superseded by {ident}")
    if len(records) + 1 > SIZE_WARNING:
        print(f"note: {len(records) + 1} records. Consider moving superseded ones to an archive file.")
    print("RESULT pass")
    return 0


def cmd_list(path, args):
    if not path.exists():
        print(f"blocked: {path} does not exist")
        return 2
    for record in parse(path.read_text(encoding="utf-8")):
        if args.active and not record["status"].startswith("active"):
            continue
        print(f"{record['id']:18} {record['date']}  [{record['status'] or 'no status'}]  {first_line(record)[:90]}")
    return 0


def cmd_check(path, args):
    if not path.exists():
        print(f"blocked: {path} does not exist")
        return 2
    text = path.read_text(encoding="utf-8")
    records, problems = parse(text), []
    ids = [r["id"] for r in records]
    for ident in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"id {ident} is used {ids.count(ident)} times")
    for record in records:
        where = f"{record['id']} (line {record['line']})"
        if not first_line(record):
            problems.append(f"{where}: no **Decision:** or **Lesson:** line")
        if "**Why:**" not in record["text"]:
            problems.append(f"{where}: no **Why:** line")
        if not record["status"]:
            problems.append(f"{where}: no **Status:** line")
        target = re.match(r"superseded by (\S+)", record["status"])
        if target and target.group(1) not in ids:
            problems.append(f"{where}: superseded by {target.group(1)}, which does not exist")
        leak = find_secret(record["text"])
        if leak:
            problems.append(f"{where}: looks like it contains {leak}")
    for problem in problems:
        print(f"FAIL {problem}")
    active = sum(1 for r in records if r["status"].startswith("active"))
    print(f"{len(records)} records, {active} active, {len(problems)} problems")
    print("RESULT fail" if problems else "RESULT pass")
    return 1 if problems else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    parser.add_argument("--file", type=pathlib.Path, help="records file (default: an existing DECISIONS.md or LESSONS.md, else docs/)")
    parser.add_argument("--type", choices=sorted(KINDS), default="decision", help="which records file to use (default: decision)")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("find", help="look for records on the same subject").add_argument("words", nargs="+")
    p = sub.add_parser("add", help="append a record")
    p.add_argument("--text", required=True, help="the decision or lesson, as one sentence stated as a rule")
    p.add_argument("--why", required=True, help="the reason, so a later reader can judge edge cases")
    p.add_argument("--scope", default="project", help="what it applies to (default: project)")
    p.add_argument("--supersedes", help="id of the record this one replaces")
    p.add_argument("--force", action="store_true", help="save even if a similar active record exists")
    sub.add_parser("list", help="list records").add_argument("--active", action="store_true")
    sub.add_parser("check", help="lint the records file")
    args = parser.parse_args()
    root = args.root.resolve()
    path = args.file if args.file else default_file(root, args.type)
    path = path if path.is_absolute() else root / path
    return {"find": cmd_find, "add": cmd_add, "list": cmd_list, "check": cmd_check}[args.action](path, args)


if __name__ == "__main__":
    sys.exit(main())
