#!/usr/bin/env python3
"""Check GitHub Actions workflow files before they are pushed. Reads files only; contacts nothing.

  workflow.py [PATH ...] [--root DIR] [--require-sha] [--json]

PATH is a workflow file (.yml, .yaml or .json) or a folder. Default: .github/workflows under --root.

FAIL findings (exit 1):
  unknown-top-key      a top-level key that workflows do not have
  no-trigger, no-jobs  the file has no "on" or no jobs
  job-no-steps         a job with no steps (and no "uses" of a reusable workflow)
  job-no-runner        a job with steps but no "runs-on"
  step-shape           a step with neither "run" nor "uses", or with both
  needs-missing        "needs" names a job that does not exist, or the jobs wait on each other in a circle
  secret-echoed        a run step prints a secret (directly, or through an env name set from a secret)
  unpinned-action      an action with no version, or a third-party action pinned to a branch
  no-permissions       no "permissions" block at the top and none in the job
  duplicate-key        the same key twice in one mapping
WARN findings (exit 0 unless --require-sha):
  tag-pinned-action    a third-party action pinned to a tag, which can be moved (FAIL with --require-sha)
  write-all, event-text-in-run, docker-no-digest

The files are read by a small YAML reader inside this script. It covers what workflow files use: nested
mappings and lists, quoted and plain values, one-line [..] and {..}, and | or > text blocks. Anchors,
aliases, tags, several documents in one file and values continued over lines are not supported; a file that
uses them ends as not verified, with the line. This is not the platform's own validation: expression
syntax, action inputs and runner labels are not checked.

Exit codes: 0 = no FAIL finding, 1 = at least one, 2 = not verified or blocked (no files, unreadable YAML).
"""
import argparse
import json
import pathlib
import re
import sys

TOP_KEYS = {"name", "run-name", "on", "permissions", "env", "defaults", "concurrency", "jobs"}
FIRST_PARTY = {"actions", "github"}
PRINTS = re.compile(r"(?<![\w-])(echo|printf|print|cat|console\.log|Write-Host|Write-Output)(?![\w-])")
BLOCK_HEAD = re.compile(r"[|>]([+-]?\d?|\d[+-]?)")


class Unsupported(Exception):
    def __init__(self, line, text):
        super().__init__(f"line {line}: {text}")


class Map(dict):
    def __init__(self, line):
        super().__init__()
        self.line, self.lines, self.dups, self.blocks = line, {}, [], set()


def strip_comment(text):
    quote = None
    for i, ch in enumerate(text):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"" and (i == 0 or text[i - 1] in " \t[{,:"):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
            return text[:i].rstrip()
    return text.rstrip()


def split_key(text):
    """'key: rest' -> (key, rest); None when the text is not a mapping entry."""
    if not text or text[0] in "[{":
        return None
    if text[0] in "'\"":
        end = text.find(text[0], 1)
        after = text[end + 1:] if end != -1 else ""
        if after[:1] == ":" and (len(after) == 1 or after[1] in " \t"):
            return text[1:end], after[1:].strip()
        return None
    quote = None
    for i, ch in enumerate(text):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"" and text[i - 1] in " \t":
            quote = ch
        elif ch == ":" and (i + 1 == len(text) or text[i + 1] in " \t"):
            return text[:i].strip(), text[i + 1:].strip()
    return None


def flow(text, line):
    pos = 0

    def ws():
        nonlocal pos
        while text[pos] in " \t":
            pos += 1

    def atom(stops):
        nonlocal pos
        ws()
        if text[pos] in "'\"":
            end = text.index(text[pos], pos + 1)
            out, pos = text[pos + 1:end], end + 1
            return out
        start = pos
        while text[pos] not in stops:
            pos = text.index("}}", pos) + 2 if text.startswith("${{", pos) else pos + 1
        return text[start:pos].strip()

    def value():
        nonlocal pos
        ws()
        if text[pos] == "[":
            pos += 1
            items = []
            while True:
                ws()
                if text[pos] == "]":
                    pos += 1
                    return items
                items.append(value())
                ws()
                if text[pos] == ",":
                    pos += 1
                elif text[pos] != "]":
                    raise ValueError
        if text[pos] == "{":
            pos += 1
            out = Map(line)
            while True:
                ws()
                if text[pos] == "}":
                    pos += 1
                    return out
                key = atom(":")
                pos += 1
                out[key] = value()
                out.lines[key] = line
                ws()
                if text[pos] == ",":
                    pos += 1
                elif text[pos] != "}":
                    raise ValueError
        return atom(",]}")

    try:
        out = value()
    except (IndexError, ValueError):
        raise Unsupported(line, "a [..] or {..} value that does not close on its own line") from None
    if text[pos:].strip():
        raise Unsupported(line, "text after a [..] or {..} value")
    return out


def scalar(text, line):
    text = text.strip()
    if text in ("", "~", "null"):
        return None
    if text[0] in "&*" or text.startswith("!!"):
        raise Unsupported(line, "anchors, aliases and tags are not supported by this reader")
    if text[0] == "'" and text.endswith("'") and len(text) > 1:
        return text[1:-1].replace("''", "'")
    if text[0] == '"' and text.endswith('"') and len(text) > 1:
        return text[1:-1].replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
    if text[0] in "[{":
        return flow(text, line)
    return text


def parse_yaml(text):
    raw, over = text.splitlines(), {}

    def get(i):
        if i in over:
            return over[i]
        body = raw[i].strip()
        if not body or body.startswith("#"):
            return None
        if body in ("---", "...") and i > first:
            raise Unsupported(i + 1, "several documents in one file are not supported by this reader")
        lead = raw[i][:len(raw[i]) - len(raw[i].lstrip())]
        if "\t" in lead:
            raise Unsupported(i + 1, "a tab is used for indentation")
        return len(lead), strip_comment(body)

    def nxt(i):
        while i < len(raw) and get(i) is None:
            i += 1
        return i

    def is_item(content):
        return content == "-" or content.startswith("- ")

    def block_scalar(head, i, indent):
        body, base, j = [], None, i + 1
        while j < len(raw):
            line = raw[j]
            if line.strip():
                ind = len(line) - len(line.lstrip(" "))
                if ind <= indent:
                    break
                base = ind if base is None else base
                body.append(line[min(base, ind):])
            else:
                body.append("")
            j += 1
        while body and body[-1] == "":
            body.pop()
        return ("\n" if head[0] == "|" else " ").join(body), nxt(j)

    def after_key(rest, i, indent):
        if rest == "":
            j = nxt(i + 1)
            if j < len(raw):
                ind, content = get(j)
                if ind > indent:
                    return block(j, ind)
                if ind == indent and is_item(content):
                    return seq(j, ind)
            return None, j
        if BLOCK_HEAD.fullmatch(rest):
            return block_scalar(rest, i, indent)
        value, j = scalar(rest, i + 1), nxt(i + 1)
        if j < len(raw) and get(j)[0] > indent:
            raise Unsupported(j + 1, "a value continued on the next line")
        return value, j

    def mapping(i, indent):
        out = Map(i + 1)
        while i < len(raw):
            ind, content = get(i)
            if ind < indent or (ind == indent and is_item(content)):
                break
            pair = split_key(content)
            if ind > indent or pair is None:
                raise Unsupported(i + 1, "expected 'key: value' at this indentation")
            key, rest = pair
            if key == "<<":
                raise Unsupported(i + 1, "merge keys are not supported by this reader")
            if key in out:
                out.dups.append((key, i + 1))
            out.lines[key] = i + 1
            if BLOCK_HEAD.fullmatch(rest):
                out.blocks.add(key)
            out[key], i = after_key(rest, i, indent)
        return out, i

    def seq(i, indent):
        items = []
        while i < len(raw):
            ind, content = get(i)
            if ind != indent or not is_item(content):
                if ind > indent:
                    raise Unsupported(i + 1, "unexpected indentation inside a list")
                break
            rest = content[1:]
            body = rest.lstrip(" ")
            if body == "":
                j = nxt(i + 1)
                value, i = block(j, get(j)[0]) if j < len(raw) and get(j)[0] > indent else (None, j)
            elif BLOCK_HEAD.fullmatch(body):
                value, i = block_scalar(body, i, indent)
            elif is_item(body):
                raise Unsupported(i + 1, "a list directly inside a list item")
            elif split_key(body) is not None:
                inner = indent + 1 + len(rest) - len(body)
                over[i] = (inner, body)
                value, i = mapping(i, inner)
            else:
                value, i = scalar(body, i + 1), nxt(i + 1)
            items.append(value)
        return items, i

    def block(i, indent):
        content = get(i)[1]
        if is_item(content):
            return seq(i, indent)
        if split_key(content) is not None:
            return mapping(i, indent)
        return scalar(content, i + 1), nxt(i + 1)

    first = len(raw)
    start = nxt(0)
    if start < len(raw) and raw[start].strip() == "---":
        start = nxt(start + 1)
    first = start
    if start >= len(raw):
        return None
    if raw[start].startswith("%"):
        raise Unsupported(start + 1, "YAML directives are not supported by this reader")
    doc, end = block(start, get(start)[0])
    if end < len(raw):
        raise Unsupported(end + 1, "more content after the document ended (several documents, or broken indentation)")
    return doc


def walk_maps(node):
    if isinstance(node, Map):
        yield node
        for value in node.values():
            yield from walk_maps(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_maps(value)


def secret_env(*envs):
    names = {}
    for env in envs:
        if isinstance(env, dict):
            for key, value in env.items():
                found = re.findall(r"secrets\.([A-Za-z_][A-Za-z0-9_]*)", str(value))
                if found:
                    names[key] = found[0]
    return names


def check_uses(ref, line, add, require_sha):
    ref = str(ref).strip()
    if ref.startswith("./"):
        return
    if ref.startswith("docker://"):
        if "@sha256:" not in ref:
            add("WARN", line, "docker-no-digest", f"{ref} is not pinned to a digest")
        return
    name, at, version = ref.partition("@")
    owner = name.split("/")[0].lower()
    if not at or not version:
        add("FAIL", line, "unpinned-action", f"{ref} has no version after @")
    elif re.fullmatch(r"[0-9a-f]{40}", version) or owner in FIRST_PARTY:
        return
    elif re.fullmatch(r"v?\d+(\.\d+)*([-.+][\w.]+)?", version):
        add("FAIL" if require_sha else "WARN", line, "tag-pinned-action", f"{ref}: a tag can be moved to other code; pin third-party actions to a full commit SHA")
    else:
        add("FAIL", line, "unpinned-action", f"{ref} follows a branch, so the code it runs can change without notice")


def check_run(script, env_names, line, add):
    for offset, text in enumerate(str(script).splitlines()):
        hit = PRINTS.search(text)
        if hit:
            tail = text[hit.end():]
            names = set(re.findall(r"\$\{\{\s*secrets\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", tail))
            for env_name, secret in env_names.items():
                if re.search(r"(\$\{?|\$env:|%)" + re.escape(env_name) + r"(?![A-Za-z0-9_])", tail):
                    names.add(f"{secret} (through env {env_name})")
            if names and not re.search(r"[|>]", re.sub(r"\$\{\{.*?\}\}", "", tail)):
                add("FAIL", line + offset, "secret-echoed", f"the step prints secret {', '.join(sorted(names))} to the log")
        if re.search(r"\$\{\{\s*github\.(event\.[\w.]*(title|body|message|name|label|ref)|head_ref)", text):
            add("WARN", line + offset, "event-text-in-run", "text from the triggering event is pasted into a shell script; pass it through env instead")


def check_workflow(doc, require_sha):
    found = []

    def add(severity, line, rule, text):
        found.append({"severity": severity, "line": line, "rule": rule, "text": text})

    if not isinstance(doc, Map):
        add("FAIL", 1, "no-jobs", "the file is not a mapping of workflow keys")
        return found
    for item in walk_maps(doc):
        for key, line in item.dups:
            add("FAIL", line, "duplicate-key", f"'{key}' appears twice in the same mapping; the later one silently wins")
    for key in doc:
        if key not in TOP_KEYS:
            add("FAIL", doc.lines.get(key, 1), "unknown-top-key", f"'{key}' is not a top-level workflow key (known: {', '.join(sorted(TOP_KEYS))})")
    if not doc.get("on"):
        add("FAIL", doc.lines.get("on", 1), "no-trigger", "no 'on' trigger, so the workflow never runs")
    jobs = doc.get("jobs")
    if not isinstance(jobs, Map) or not jobs:
        add("FAIL", doc.lines.get("jobs", 1), "no-jobs", "no jobs defined")
        return found
    if doc.get("permissions") == "write-all":
        add("WARN", doc.lines["permissions"], "write-all", "permissions: write-all gives every job full write access")
    uncovered, needs = [], {}
    for job_id, job in jobs.items():
        line = jobs.lines.get(job_id, 1)
        if not isinstance(job, Map):
            add("FAIL", line, "job-no-steps", f"job '{job_id}' is empty")
            continue
        wanted = job.get("needs") or []
        wanted = [wanted] if isinstance(wanted, str) else [str(w) for w in wanted]
        needs[job_id] = wanted
        for other in wanted:
            if other not in jobs:
                add("FAIL", job.lines.get("needs", line), "needs-missing", f"job '{job_id}' needs '{other}', which is not a job in this file")
        if "permissions" not in doc and "permissions" not in job:
            uncovered.append(job_id)
        if job.get("permissions") == "write-all":
            add("WARN", job.lines["permissions"], "write-all", f"job '{job_id}' has permissions: write-all")
        if "uses" in job:
            check_uses(job["uses"], job.lines["uses"], add, require_sha)
            continue
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            add("FAIL", job.lines.get("steps", line), "job-no-steps", f"job '{job_id}' has no steps")
            continue
        if not job.get("runs-on"):
            add("FAIL", line, "job-no-runner", f"job '{job_id}' has steps but no runs-on")
        for number, step in enumerate(steps, 1):
            step_line = step.line if isinstance(step, Map) else line
            if not isinstance(step, Map) or ("run" in step) == ("uses" in step):
                add("FAIL", step_line, "step-shape", f"job '{job_id}' step {number} needs exactly one of 'run' or 'uses'")
                continue
            if "uses" in step:
                check_uses(step["uses"], step.lines["uses"], add, require_sha)
            else:
                names = secret_env(doc.get("env"), job.get("env"), step.get("env"))
                check_run(step["run"], names, step.lines["run"] + ("run" in step.blocks), add)
    if uncovered:
        add("FAIL", doc.lines.get("jobs", 1), "no-permissions", f"no permissions block covers job(s) {', '.join(uncovered)}; the token then gets the repository's default rights. Add 'permissions:' with the least that is needed, for example 'contents: read'")
    state = {}

    def circular(job_id, trail):
        if state.get(job_id) == "done" or job_id not in needs:
            return None
        if state.get(job_id) == "open":
            return trail[trail.index(job_id):] + [job_id]
        state[job_id] = "open"
        for other in needs[job_id]:
            loop = circular(other, trail + [job_id])
            if loop:
                return loop
        state[job_id] = "done"
        return None

    for job_id in needs:
        loop = circular(job_id, [])
        if loop:
            add("FAIL", jobs.lines.get(loop[0], 1), "needs-missing", f"jobs wait on each other in a circle: {' -> '.join(loop)}")
            break
    return found


def to_map(node, line=1):
    """Give parsed JSON the same shape as the YAML reader's output."""
    if isinstance(node, dict):
        out = Map(line)
        for key, value in node.items():
            out[key], out.lines[key] = to_map(value), line
        return out
    return [to_map(v) for v in node] if isinstance(node, list) else node


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", type=pathlib.Path, help="workflow files or folders (default: .github/workflows)")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    parser.add_argument("--require-sha", action="store_true", help="fail on third-party actions pinned to a tag")
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    args = parser.parse_args()

    files = []
    for path in args.paths or [args.root / ".github" / "workflows"]:
        if path.is_dir():
            files += sorted(p for p in path.iterdir() if p.suffix in (".yml", ".yaml", ".json") and p.is_file())
        elif path.is_file():
            files.append(path)
        else:
            print(f"blocked: {path} does not exist")
            return 2
    if not files:
        print("blocked: no workflow files (.yml, .yaml, .json) found")
        return 2
    report, unread, fails, warns = {}, [], 0, 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            doc = to_map(json.loads(text)) if path.suffix == ".json" else parse_yaml(text)
        except Unsupported as exc:
            unread.append(f"{path}: {exc}")
            continue
        except ValueError as exc:
            unread.append(f"{path}: not valid JSON ({exc})")
            continue
        if doc is None:
            unread.append(f"{path}: the file is empty")
            continue
        report[str(path)] = check_workflow(doc, args.require_sha)
    if args.json:
        print(json.dumps({"findings": report, "unread": unread}, indent=2))
    for path, found in report.items():
        fails += sum(f["severity"] == "FAIL" for f in found)
        warns += sum(f["severity"] == "WARN" for f in found)
        if not args.json:
            print(f"{path}: {'no findings' if not found else str(len(found)) + ' finding(s)'}")
            for f in sorted(found, key=lambda f: (f["severity"] != "FAIL", f["line"])):
                print(f"  {f['severity']} line {f['line']} {f['rule']}: {f['text']}")
    for line in unread:
        print(f"  NOT READ {line}")
    if not args.json:
        print("checked: structure, needs, permissions, action pins and printed secrets. Not checked: expression syntax, action inputs, runner labels, and whether the commands exist.")
    if fails:
        print(f"RESULT fail: {fails} failing finding(s) in {len(report)} file(s)" + (f"; {warns} warning(s)" if warns else "") + (f"; {len(unread)} file(s) not read" if unread else ""))
        return 1
    if unread:
        print(f"RESULT not verified: {len(unread)} file(s) could not be read by this script's YAML reader; check them with the platform's own tools")
        return 2
    print(f"RESULT pass: {len(report)} file(s), no failing finding" + (f"; {warns} warning(s)" if warns else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
