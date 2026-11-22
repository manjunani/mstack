#!/usr/bin/env python3
"""Read a third-party skill, plugin or skills repository and report what a person should look at before installing it.

  scan.py PATH [--all] [--json]

It only reads files. It never runs, imports or installs anything from PATH.
Findings are of two kinds:
  FAIL  strong signs of harm: a download piped into a shell, a command that reads credentials,
        invisible characters, text telling the agent to override its rules or hide things from the user,
        an encoded payload that is decoded and run
  WARN  things that are normal in some skills and need a human read: network calls, shell commands,
        installs, hooks, paths outside the skill, advertising, mentions of credential files
WARN lines are grouped by kind; --all lists every one.
Exit codes: 0 = nothing found, 1 = at least one FAIL, 2 = only WARN findings: not verified until a person reads them.
A clean result is not proof of safety. It means these checks found nothing.
"""
import argparse
import collections
import json
import pathlib
import re
import sys

MAX_BYTES = 400_000
TEXT_TYPES = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs",
              ".ts", ".rb", ".pl", ".ps1", ".tmpl", ".html", ".xml", ".cfg", ".ini", ""}
CODE_TYPES = {".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".ps1"}

# Pattern pieces are joined from parts so that this file does not match its own rules.
HOME = r"(~|\$HOME|\$\{HOME\}|/Users/[^/\s]+|/home/[^/\s]+)"
CRED_PATH = HOME + r"/\.(s" + r"sh|a" + r"ws|gnupg|netrc|npmrc|config/gh|docker/config)\b|\bid_(r" + r"sa|ed25519|ecdsa)\b|(?<![\w.])\.en" + r"v\b(?!\.example|\.sample)"
READ_VERB = r"\b(cat|cp|scp|rsync|tar|zip|base64|curl|wget|less|head|tail|source|open|read|readFile\w*|read_text|load)\b"
SHELL = r"(sudo\s+)?(ba|z|da)?s" + r"h\b"
FAIL_COMMAND = [
    (r"\b(curl|wget)\b[^\n|]*(https?://|\$\{?\w+)[^\n|]*\|\s*" + SHELL, "downloads a script and runs it"),
    (r"base64\s+(-d|--decode|-D)\b[^\n]*\|\s*" + SHELL + r"|ev" + r"al\s*\(\s*atob\(|ex" + r"ec\s*\(\s*base64\.b64decode", "decodes hidden content and runs it"),
    (r"security\s+find-(generic|internet)-pass" + r"word\b", "reads the system keychain"),
]
FAIL_TEXT = [
    (r"ignore\s+(all\s+|any\s+)?(the\s+|your\s+)?(previous|prior|above|other|system)\s+(instructions|rules|prompts?)", "tells the agent to ignore its instructions"),
    (r"(do\s+not|don't|never)\s+(tell|inform|notify|alert)\s+(the\s+)?(user|human|operator)\s+(about|that\s+(you|this|we|it)\b|what\s+you)", "tells the agent to hide something from the user"),
    (r"without\s+(asking|telling|informing|notifying)\s+(the\s+)?(user|human)\b[^.\n]{0,60}\b(send|upload|post|delete|install|run|push|email)", "tells the agent to act without the user knowing"),
    (r"(disregard|override|bypass|disable)\s+(the\s+|any\s+|all\s+)?(user'?s?\s+instructions|safety\s+(rules|checks)|permission\s+(prompts?|checks?)|guard\s+hooks?)", "tells the agent to bypass a rule"),
    (r"(send|post|upload|forward|email|exfiltrate)\b[^.\n]{0,40}\b(your|the\s+user'?s|their|all|any)\s+(credentials|api[ _-]?keys?|access\s+tokens?|secrets|passwords?|ssh\s+keys?)\b[^.\n]{0,40}\bto\s+(https?://|\S+@\S+\.\S+|[\w-]+\.[a-z]{2,}\b)", "asks for secrets to be sent to an address"),
]
WARN_CODE = [
    (r"\b(curl|wget)\b|requests\.(get|post|put)|urllib\.request|http\.client|fetch\(|axios\.|socket\.(socket|connect)|\bnc\s+-", "makes a network call"),
    (r"subprocess\.|os\.system|os\.popen|child_process|\bexecSync\(|\bev" + r"al\(|\b(bash|sh|zsh)\s+-c\b", "runs shell commands or evaluates code"),
    (r"\b(pip3?|uv)\s+install\b|\bnpm\s+(i|install)\b|\bnpx\s+\S|\bbrew\s+install\b|\bcargo\s+install\b|\bgo\s+install\b", "installs software"),
    (r"\b(GITHUB_TOKEN|ANTHROPIC_API_KEY|OPENAI_API_KEY|AWS_SECRET_ACCESS_KEY)\b", "uses a secret from the environment"),
    (r"\bsudo\b|\bcrontab\b|\blaunchctl\b|\bsystemctl\b", "needs elevated rights or sets something to run later"),
]
WARN_TEXT = [
    (r"(always|must)\s+(use|invoke|run|call|prefer)\s+this\s+(skill|tool|plugin)|prefer\s+(this|our)\s+\w+\s+over", "pushes the agent to choose it over other tools"),
    (r"star\s+(this|the|our)\s+repo|sponsor(ed)?\s+by|promo\s*code|free\s+credits?|affiliate\s+link|upgrade\s+to\s+(pro|premium)", "advertising or an incentive"),
    (r"<!--[^>]{0,400}\b(you|agent|assistant|claude|model)\s+(should|must|will|can|need)\b[^>]{0,400}-->", "a hidden comment addressed to the agent"),
]
RANGES = [(0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x2064), (0xE0000, 0xE007F)]
HIDDEN = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in RANGES) + "]")
BOM = chr(0xFEFF)
URL = re.compile(r"https?://([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
COMMENT = re.compile(r"^\s*(#|//|\*|/\*|--|<!--|\"\"\"|''')")


def scan_file(path, rel, findings, hosts):
    try:
        raw = path.read_bytes()[:MAX_BYTES]
    except OSError:
        return
    if b"\x00" in raw[:2000]:
        findings.append(("WARN", rel, 0, "binary file that was not read"))
        return
    text = raw.decode("utf-8", "replace")
    is_code = path.suffix.lower() in CODE_TYPES
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if number == 1:
            line = line.lstrip(BOM)
        if line.strip().startswith("```"):
            fenced = not fenced
        command_like = is_code or fenced or bool(re.match(r"\s*(\$|>)\s", line)) or "`" in line
        comment = is_code and bool(COMMENT.match(line))
        negated = bool(re.search(r"\b(never|do not|don't|must not|should not|avoid|refuse|block|deny|reject)\b", line, re.I))

        if HIDDEN.search(line) or BOM in line:
            findings.append(("FAIL", rel, number, "contains invisible characters that can hide text from a reader"))
        for pattern, label in FAIL_COMMAND:
            if re.search(pattern, line, re.I):
                level = "WARN" if comment or (negated and not is_code) else "FAIL"
                findings.append((level, rel, number, label + (" (in a comment or a warning; read it)" if level == "WARN" else "")))
        template_copy = re.search(r"\.env\.(example|sample|template|dist)\b", line)  # creating a config from a template reads no secret
        if re.search(CRED_PATH, line) and not template_copy:
            reads = re.search(READ_VERB + r"[^\n]{0,60}(" + CRED_PATH + ")", line)
            if reads and command_like and not comment and not negated:
                findings.append(("FAIL", rel, number, "a command reads a credential file"))
            else:
                findings.append(("WARN", rel, number, "mentions a credential file"))
        if not is_code:
            for pattern, label in FAIL_TEXT:
                if re.search(pattern, line, re.I):
                    findings.append(("FAIL", rel, number, label))
        for pattern, label in WARN_TEXT:
            if re.search(pattern, line, re.I):
                findings.append(("WARN", rel, number, label))
        if command_like:
            for pattern, label in WARN_CODE:
                if re.search(pattern, line):
                    findings.append(("WARN", rel, number, label))
        if re.search(r"(?<![\w.])\.\./\.\./|(?<![\w/.])/(etc|usr|var|Library|System)/\w", line) and command_like:
            findings.append(("WARN", rel, number, "refers to a path outside the skill"))
        hosts.update(URL.findall(line))
    if path.name == "SKILL.md" and text.startswith("---"):
        end = text.find("\n---", 3)
        head = text[:end] if end != -1 else ""
        if re.search(r"^hooks\s*:", head, re.M):
            findings.append(("WARN", rel, 1, "declares hooks, which run by themselves while the skill is active"))
        if re.search(r"^allowed-tools\s*:.*\bBash\b(?!\()|Bash\(\s*\*\s*\)", head, re.M):
            findings.append(("WARN", rel, 1, "asks for unrestricted shell access"))
        desc = re.search(r"^description\s*:\s*(.+)$", head, re.M)
        if desc and len(desc.group(1).strip()) < 40 and desc.group(1).strip() not in (">", "|", ">-", "|-"):
            findings.append(("WARN", rel, 1, "has no real description, so it cannot be judged from its listing"))
    if path.name in ("hooks.json", ".mcp.json"):
        findings.append(("WARN", rel, 0, "configures code or servers that run without being asked"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=pathlib.Path, help="a skill folder, a plugin folder or a repository")
    parser.add_argument("--all", action="store_true", help="list every WARN line instead of grouping them")
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    args = parser.parse_args()
    root = args.path.expanduser().resolve()
    if not root.exists():
        print(f"blocked: {root} does not exist")
        return 2
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts)
    findings, hosts, read = [], set(), 0
    skills = sum(1 for p in files if p.name == "SKILL.md")
    for path in files:
        rel = str(path.relative_to(root)) if root.is_dir() else path.name
        if path.is_symlink():
            findings.append(("WARN", rel, 0, "a symbolic link, which can point outside the skill"))
            continue
        if path.suffix.lower() not in TEXT_TYPES:
            continue
        read += 1
        scan_file(path, rel, findings, hosts)

    unique = list(dict.fromkeys(findings))
    fails = [f for f in unique if f[0] == "FAIL"]
    warns = [f for f in unique if f[0] == "WARN"]
    verdict = "fail" if fails else ("not verified" if warns else "pass")
    if args.json:
        print(json.dumps({"verdict": verdict, "files_read": read, "skills": skills, "hosts": sorted(hosts),
                          "findings": [{"level": l, "file": f, "line": n, "what": w} for l, f, n, w in unique]}, indent=2))
        return {"pass": 0, "fail": 1, "not verified": 2}[verdict]

    print(f"scanned {read} text files, {skills} skills, in {root}")
    for level, rel, number, what in fails:
        print(f"FAIL {rel}:{number}: {what}")
    if args.all:
        for level, rel, number, what in warns:
            print(f"WARN {rel}:{number}: {what}")
    else:
        groups = collections.defaultdict(list)
        for level, rel, number, what in warns:
            groups[what].append(f"{rel}:{number}")
        for what, places in sorted(groups.items(), key=lambda item: -len(item[1])):
            files_hit = len({p.rsplit(":", 1)[0] for p in places})
            more = f", and {len(places) - 3} more (--all lists them)" if len(places) > 3 else ""
            print(f"WARN {what}: {len(places)} lines in {files_hit} files. First: {', '.join(places[:3])}{more}")
    if hosts:
        print(f"web addresses mentioned ({len(hosts)}): {', '.join(sorted(hosts)[:25])}" + (" ..." if len(hosts) > 25 else ""))
    print(f"{len(fails)} FAIL, {len(warns)} WARN")
    if verdict == "pass":
        print("RESULT pass: these checks found nothing. That is not proof of safety; read any script before trusting it.")
    elif verdict == "fail":
        print("RESULT fail: do not install until each FAIL line is explained.")
    else:
        print("RESULT not verified: a person has to read the WARN lines and decide.")
    return {"pass": 0, "fail": 1, "not verified": 2}[verdict]


if __name__ == "__main__":
    sys.exit(main())
