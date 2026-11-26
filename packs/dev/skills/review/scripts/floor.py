#!/usr/bin/env python3
"""Floor guard: list every place a change makes a safety check weaker.

Reads one git diff and reports, with file, line and the quoted text:

  test-deleted        a test file was deleted
  test-removed        test functions or cases were removed and not replaced (the count in that file drops)
  assert-removed      assertions were removed from a test file and not replaced (the count drops)
  assert-loosened     an assertion was replaced by a weaker one (assertEqual -> assertTrue,
                      toStrictEqual -> toEqual, assert a == b -> assert a)
  threshold-weakened  a number that sets a bar moved the weak way: a coverage or other minimum lowered,
                      a timeout, retry count or tolerance raised
  threshold-removed   a coverage minimum (fail-under, coverageThreshold) was deleted
  retry-added         a retry or rerun was added (@flaky, retries: 3, --reruns, jest.retryTimes)
  test-skipped        a skip, xfail or focus marker was added (pytest.mark.skip, @unittest.skip, it.skip,
                      it.only, xit, fdescribe, t.Skip, #[ignore], @Disabled)
  check-disabled      a check was switched off: "|| true", continue-on-error: true, allow_failure: true,
                      --no-verify, eslint-disable, # type: ignore, # noqa, @ts-ignore, @ts-nocheck,
                      # pylint: disable, # nosec, istanbul ignore, "if: false" on a CI job
  ci-step-removed     CI steps (run, uses, script, name) were removed from a workflow file and not replaced
  ci-file-deleted     a CI workflow or hook file was deleted

The range (positional, optional):
  (none)          the working folder against HEAD, untracked files included
  BASE..HEAD      the diff between two commits; BASE...HEAD uses their merge base
  REF             the same as REF..HEAD

A line that only moved (the same text removed and added somewhere in the diff) does not count as added.
Lines of removed code are cited with their line number before the change, marked "(before)".

  --allow "<file>:<reason>"   accept every finding in that file (a path or a glob, relative to the
                              repository root). The reason is required and has to be real words: at least
                              three different words, at least 15 characters, and one common word such as
                              "the", "is" or "because". Repeat the option for more files.

Output: one line per finding, accepted findings marked "accepted", then the RESULT line.
Exit codes: 0 = pass (nothing weakened, or every finding accepted), 1 = fail (an unaccepted finding),
2 = blocked (not a git repository, no commit, a range git does not know, an --allow without a real reason).
This script only reads: it runs git diff and reads untracked files. It writes nothing.
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys
from collections import Counter

GIT = os.environ.get("MSTACK_GIT") or "git"
STATE = ".mstack"
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|specs?)/|(^|/)test_[^/]*\.py$|_test\.(py|go|rb|exs?)$"
    r"|\.(test|spec)\.[cm]?[jt]sx?$|_spec\.rb$|Tests?\.(java|kt|swift|cs|scala)$|(^|/)conftest\.py$")
CI_PATH = re.compile(
    r"(^|/)\.github/workflows/[^/]+\.ya?ml$|(^|/)\.gitlab-ci\.ya?ml$|(^|/)\.circleci/config\.ya?ml$"
    r"|(^|/)azure-pipelines\.ya?ml$|(^|/)bitbucket-pipelines\.ya?ml$|(^|/)Jenkinsfile$|(^|/)\.buildkite/"
    r"|(^|/)\.pre-commit-config\.ya?ml$|(^|/)\.husky/|(^|/)\.github/settings\.ya?ml$")
REQUIRED_PATH = re.compile(r"settings\.ya?ml$|protection|rulesets?", re.I)

TEST_DEFS = [
    re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\("),
    re.compile(r"^\s*func\s+(Test\w*|test\w*)\s*\("),
    re.compile(r"^\s*[xf]?(?:it|test|specify)(?:\.(?:only|skip|todo|concurrent|each\(.*?\)))?\s*\(\s*(['\"`])(.*?)\1"),
    re.compile(r"^\s*(?:pub\s+)?fn\s+(test_\w*)\s*\("),
    re.compile(r"^\s*(?:public\s+|private\s+)?(?:void|fun)\s+(test\w*)\s*\("),
    re.compile(r"^\s*(@Test)\b"),
    re.compile(r"^\s*(#\[test\])"),
]
ASSERT = re.compile(
    r"\bassert\w*\b|\bexpect\s*\(|\bXCTAssert\w*|\.should\w*\b|\brequire\.\w+\(|\bt\.(?:Error|Errorf|Fatal|Fatalf)\("
    r"|\bassert_\w+!?\(|\bpytest\.raises\b|\bself\.fail\(")
STRICT = re.compile(r"toStrictEqual|strictEqual|deepStrictEqual|\bassertIs\b|XCTAssertIdentical|assertSame|assert_eq!")
EQUAL = re.compile(
    r"assert(?:Equals?|DictEqual|ListEqual|CountEqual|AlmostEqual|SetEqual|TupleEqual|In|NotIn|Raises\w*|Greater\w*|Less\w*|Regex\w*)\b"
    r"|assert_equal|toEqual|toBe\(|toMatchObject|toHaveLength|toContain|toThrow|XCTAssertEqual|assert\.equal|deepEqual"
    r"|\.eql?\(|pytest\.raises|require\.Equal|assert\.Equal")
WEAK = re.compile(
    r"assertTrue|assertFalse|assertIsNotNone|assertIsNone|toBeTruthy|toBeFalsy|toBeDefined|not\.toBeNull|toBeUndefined"
    r"|XCTAssertTrue|XCTAssertFalse|XCTAssertNotNil|assert\.ok|assert!\(|require\.NotNil|assert\.NotNil|assert\.True")
PY_ASSERT = re.compile(r"^\s*assert\s+(.*)$")
COMPARE = re.compile(r"==|!=|<=|>=|<|>|\bin\b|\bis\b")
NONE_CHECK = re.compile(r"\bis\s+(?:not\s+)?None\b")

HIGHER_WEAKER = re.compile(
    r"timeout|retr(?:y|ies)|rerun|attempt|toleran|\btol\b|\babs\s*=|\brel\s*=|\bdelta\b|epsilon|\beps\b"
    r"|max[_-]?(?:warnings|fail\w*|errors)|allowed[_-]?fail\w*|grace|deadline", re.I)
LOWER_WEAKER = re.compile(
    r"cover|fail[_-]?under|\bmin(?:imum)?\b|min[_-]|threshold|branches|statements|functions|\blines\b|places|score", re.I)
COVERAGE_LINE = re.compile(r"fail[_-]?under|coverageThreshold|min[_-]?coverage|coverage[_-]?min", re.I)
NUMBER = re.compile(r"\d+(?:\.\d+)?")
RETRY = re.compile(
    r"@flaky\b|pytest\.mark\.flaky|--reruns\b|jest\.retryTimes|this\.retries\(|\bretries\s*[:=(]|\bretry\s*[:=(]"
    r"|\breruns\s*[:=]|\bmax_attempts\s*[:=]", re.I)
SKIP = re.compile(
    r"@(?:unittest\.)?skip\w*|\bpytest\.mark\.(?:skip|skipif|xfail)\b|\bpytest\.(?:skip|xfail)\(|\bself\.skipTest\("
    r"|\b(?:it|test|describe|context|suite|specify)\.(?:skip|only|todo)\b"
    r"|(?<![\w.])(?:xit|xtest|xdescribe|xcontext|fit|fdescribe|fcontext)\s*\(|\bt\.Skip(?:Now|f)?\(|#\[ignore\]"
    r"|@Ignore\b|@Disabled\b|\bXCTSkip\w*|\bmarkTestSkipped\(")
DISABLE = [
    (re.compile(r"\|\|\s*(?:true|:)(?=\s*(?:$|[;&|)#\"']))"), "a failing command now counts as success"),
    (re.compile(r"continue-on-error:\s*true", re.I), "the CI step may fail without failing the run"),
    (re.compile(r"allow_failure:\s*true", re.I), "the CI job may fail without failing the pipeline"),
    (re.compile(r"^\s*if:\s*(?:false|\$\{\{\s*false\s*\}\})\s*$"), "the CI job or step never runs"),
    (re.compile(r"--no-verify\b"), "git hooks are skipped"),
    (re.compile(r"eslint-disable"), "a lint rule is turned off"),
    (re.compile(r"#\s*type:\s*ignore"), "a type error is silenced"),
    (re.compile(r"#\s*noqa\b", re.I), "a lint warning is silenced"),
    (re.compile(r"@ts-ignore|@ts-nocheck"), "a type error is silenced"),
    (re.compile(r"#\s*pylint:\s*disable"), "a lint rule is turned off"),
    (re.compile(r"#\s*nosec\b|nosemgrep"), "a security check is silenced"),
    (re.compile(r"istanbul ignore|c8 ignore|#\s*pragma:\s*no cover"), "code is left out of coverage"),
]
CI_STEP = re.compile(r"^\s*-\s*(?:name|run|uses|script|id|repo)\s*:|^\s*(?:run|uses|script)\s*:|^\s*(?:stage|sh)\s*[('\"]")
LIST_ITEM = re.compile(r"^\s*-\s+\S")
COMMENT = re.compile(r"^\s*(?:#|//|/\*|\*)")

COMMON = set("the a an is are was were be to of for in on by and or not no it its this that with so as from "
             "until because we our they there here only while when".split())
PLACEHOLDER = set("todo tbd fixme xxx na none ok okay test asdf qwerty whatever because reason fine yes no later "
                  "temp wip lorem ipsum foo bar baz".split())


def git(root, *args):
    try:
        out = subprocess.run([GIT, "--no-optional-locks", "-C", root, "-c", "core.quotePath=false", *args],
                             capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    text = out.stdout.decode("utf-8", "replace")
    return out.returncode, text if out.returncode == 0 else text + out.stderr.decode("utf-8", "replace")


def resolve(root, ref):
    code, out = git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return out.strip() if code == 0 and out.strip() else None


def unquote(name):
    name = name.split("\t")[0]
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        name = name[1:-1]
    return name


def parse(diff):
    """Return a list of files: path, deleted, hunks of (removed [(line, text)], added [(line, text)])."""
    files, cur, old_left, new_left = [], None, 0, 0
    for raw in diff.splitlines():
        if old_left > 0 or new_left > 0:
            hunk = cur["hunks"][-1]
            if raw.startswith("-"):
                hunk[0].append((hunk[2], raw[1:])); hunk[2] += 1; old_left -= 1
            elif raw.startswith("+"):
                hunk[1].append((hunk[3], raw[1:])); hunk[3] += 1; new_left -= 1
            elif raw.startswith(" "):
                hunk[2] += 1; hunk[3] += 1; old_left -= 1; new_left -= 1
            continue
        if raw.startswith("diff --git "):
            cur = {"path": None, "old": None, "deleted": False, "hunks": []}
            files.append(cur)
        elif cur is None:
            continue
        elif raw.startswith("deleted file mode"):
            cur["deleted"] = True
        elif raw.startswith("--- "):
            name = unquote(raw[4:])
            cur["old"] = None if name == "/dev/null" else name[2:] if name.startswith("a/") else name
        elif raw.startswith("+++ "):
            name = unquote(raw[4:])
            cur["path"] = None if name == "/dev/null" else name[2:] if name.startswith("b/") else name
        elif raw.startswith("rename to "):
            cur["path"] = raw[len("rename to "):]
        elif raw.startswith("rename from "):
            cur["old"] = raw[len("rename from "):]
        else:
            match = HUNK.match(raw)
            if match:
                old_left = int(match.group(2) or "1")
                new_left = int(match.group(4) or "1")
                cur["hunks"].append([[], [], int(match.group(1)), int(match.group(3))])
    for item in files:
        item["path"] = item["path"] or item["old"]
        item["hunks"] = [(h[0], h[1]) for h in item["hunks"]]
    return [f for f in files if f["path"] and not f["path"].startswith(STATE + "/")]


def untracked(root):
    code, out = git(root, "ls-files", "--others", "--exclude-standard", "-z")
    result = []
    for name in (out.split("\0") if code == 0 else []):
        if not name or name.startswith(STATE + "/"):
            continue
        try:
            with open(os.path.join(root, name), "rb") as handle:
                data = handle.read(2_000_000)
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        lines = data.decode("utf-8", "replace").splitlines()
        result.append({"path": name, "old": None, "deleted": False,
                       "hunks": [([], [(i, text) for i, text in enumerate(lines, 1)])]})
    return result


def quote(text):
    text = text.strip()
    return text if len(text) <= 100 else text[:97] + "..."


def test_name(text):
    if COMMENT.match(text) and not text.lstrip().startswith("#["):
        return None
    for pattern in TEST_DEFS:
        match = pattern.match(text)
        if match:
            return match.group(match.lastindex)
    return None


def is_assert(text):
    return not COMMENT.match(text) and bool(ASSERT.search(text))


def rank(text):
    """3 strict, 2 compares a value, 1 only truthiness or presence, None unknown."""
    if STRICT.search(text):
        return 3
    if WEAK.search(text):
        return 1
    if EQUAL.search(text):
        return 2
    match = PY_ASSERT.match(text)
    if match:
        body = match.group(1)
        if NONE_CHECK.search(body):
            return 1
        return 2 if COMPARE.search(body) else 1
    return None


def unmatched(removed, added):
    """Removed items whose key has no partner among the added ones."""
    pool = Counter(key for _, _, key in added)
    left = []
    for item in removed:
        if pool[item[2]] > 0:
            pool[item[2]] -= 1
        else:
            left.append(item)
    return left


def scan(files):
    findings = []

    def add(rule, path, line, text, why, before=False):
        findings.append({"rule": rule, "path": path, "line": line, "text": quote(text), "why": why, "before": before})

    removed_anywhere = Counter(t.strip() for f in files for h in f["hunks"] for _, t in h[0] if t.strip())

    def moved(text):
        key = text.strip()
        if key and removed_anywhere[key] > 0:
            removed_anywhere[key] -= 1
            return True
        return False

    for f in files:
        path, is_test, is_ci = f["path"], bool(TEST_PATH.search(f["path"])), bool(CI_PATH.search(f["path"]))
        all_removed = [r for h in f["hunks"] for r in h[0]]
        all_added = [a for h in f["hunks"] for a in h[1]]
        if f["deleted"]:
            first = next(((n, t) for n, t in all_removed if test_name(t)), None) or \
                next(((n, t) for n, t in all_removed if t.strip()), (1, "(empty file)"))
            if is_test:
                add("test-deleted", path, first[0], first[1], "a test file was deleted", True)
            if is_ci:
                add("ci-file-deleted", path, first[0], first[1], "a CI file was deleted", True)
            continue

        if is_test:
            gone = [(n, t, test_name(t)) for n, t in all_removed if test_name(t)]
            new = [(n, t, test_name(t)) for n, t in all_added if test_name(t)]
            if len(gone) > len(new):
                for n, t, _ in unmatched(gone, new):
                    add("test-removed", path, n, t, f"tests in this file: -{len(gone)} +{len(new)}", True)
            gone = [(n, t, t.strip()) for n, t in all_removed if is_assert(t)]
            new = [(n, t, t.strip()) for n, t in all_added if is_assert(t)]
            if len(gone) > len(new):
                for n, t, _ in unmatched(gone, new):
                    add("assert-removed", path, n, t, f"assertions in this file: -{len(gone)} +{len(new)}", True)
            for removed, added in f["hunks"]:
                before = [(t, rank(t)) for _, t in removed if is_assert(t) and rank(t)]
                after = [(n, t, rank(t)) for n, t in added if is_assert(t) and rank(t)]
                for (old_text, old_rank), (n, t, new_rank) in zip(before, after):
                    if new_rank < old_rank:
                        add("assert-loosened", path, n, t, f"weaker than the line it replaced: {quote(old_text)}")

        if is_ci:
            gone = [(n, t, t.strip()) for n, t in all_removed if CI_STEP.match(t)]
            new = [(n, t, t.strip()) for n, t in all_added if CI_STEP.match(t)]
            if len(gone) > len(new):
                for n, t, _ in unmatched(gone, new):
                    add("ci-step-removed", path, n, t, f"CI steps in this file: -{len(gone)} +{len(new)}", True)
            if REQUIRED_PATH.search(path):
                gone = [(n, t, t.strip()) for n, t in all_removed if LIST_ITEM.match(t)]
                new = [(n, t, t.strip()) for n, t in all_added if LIST_ITEM.match(t)]
                for n, t, _ in (unmatched(gone, new) if len(gone) > len(new) else []):
                    add("ci-step-removed", path, n, t, "a required check or listed item was removed", True)

        used = set()
        for removed, added in f["hunks"]:
            for line_no, old in removed:
                if not NUMBER.search(old):
                    continue
                shape = NUMBER.sub("#", " ".join(old.split()))
                partner = next(((n, t) for n, t in added if (n not in used)
                                and NUMBER.sub("#", " ".join(t.split())) == shape and t.strip() != old.strip()), None)
                if partner is None:
                    if COVERAGE_LINE.search(old) and not any(COVERAGE_LINE.search(t) for _, t in all_added):
                        add("threshold-removed", path, line_no, old, "a coverage minimum was deleted", True)
                    continue
                used.add(partner[0])
                pairs = [(float(a), float(b)) for a, b in zip(NUMBER.findall(old), NUMBER.findall(partner[1])) if a != b]
                if not pairs:
                    continue
                was, now = pairs[0]
                if HIGHER_WEAKER.search(old) and now > was:
                    add("threshold-weakened", path, partner[0], partner[1], f"raised from {quote(old)}")
                elif not HIGHER_WEAKER.search(old) and LOWER_WEAKER.search(old) and now < was:
                    add("threshold-weakened", path, partner[0], partner[1], f"lowered from {quote(old)}")

        for n, t in all_added:
            if not t.strip() or n in used:
                continue
            checks = []
            if SKIP.search(t):
                checks.append(("test-skipped", "a test is skipped, expected to fail or focused"))
            if RETRY.search(t):
                checks.append(("retry-added", "a failing test or step is now retried"))
            for pattern, why in DISABLE:
                if pattern.search(t):
                    checks.append(("check-disabled", why))
                    break
            if checks and not moved(t):
                for rule, why in checks:
                    add(rule, path, n, t, why)
    return findings


def real_reason(reason):
    words = re.findall(r"[A-Za-z]+", reason)
    real = {w.lower() for w in words if len(w) >= 2 and re.search(r"[aeiouy]", w, re.I)}
    return (len(reason.strip()) >= 15 and len(real - PLACEHOLDER) >= 3
            and bool(real & COMMON) and sum(len(w) for w in words) >= 0.6 * len(reason.strip()))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("range", nargs="?", help="BASE..HEAD, BASE...HEAD or REF (default: working folder against HEAD)")
    parser.add_argument("--allow", action="append", default=[], metavar="FILE:REASON",
                        help="accept the findings in FILE (path or glob), with a reason in real words")
    args = parser.parse_args()

    allows = []
    for item in args.allow:
        name, _, reason = item.partition(":")
        if not name.strip() or not reason.strip():
            print(f"RESULT blocked: --allow needs \"<file>:<reason>\", got: {item}")
            return 2
        if not real_reason(reason):
            print(f"RESULT blocked: the reason for {name.strip()} is not real words: {reason.strip()!r}. "
                  "Write a sentence that says why the weaker check is right")
            return 2
        allows.append([name.strip(), reason.strip(), 0])

    code, top = git(os.getcwd(), "rev-parse", "--show-toplevel")
    if code != 0 or not top.strip():
        print("RESULT blocked: not inside a git repository")
        return 2
    root = top.strip()
    head = resolve(root, "HEAD")
    if head is None:
        print("RESULT blocked: the repository has no commit yet")
        return 2

    if args.range:
        spec = args.range
        three = "..." in spec
        left, _, right = spec.partition("...") if three else spec.partition("..") if ".." in spec else (spec, "", "HEAD")
        base, tip = resolve(root, left or "HEAD"), resolve(root, right or "HEAD")
        if base is None or tip is None:
            print(f"RESULT blocked: git does not know the range {spec}: {(left or 'HEAD') if base is None else (right or 'HEAD')} is no commit")
            return 2
        if three:
            code, out = git(root, "merge-base", base, tip)
            if code != 0:
                print(f"RESULT blocked: {left} and {right} share no history")
                return 2
            base = out.strip()
        label = f"{base}..{tip}"
        code, diff = git(root, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "-U0", "-M", base, tip, "--")
        extra = []
    else:
        label = f"uncommitted changes against HEAD {head}"
        code, diff = git(root, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "-U0", "-M", "HEAD", "--")
        extra = untracked(root)
    if code != 0:
        print(f"RESULT blocked: git diff failed: {diff.strip()[:300]}")
        return 2

    files = parse(diff) + extra
    findings = scan(files)
    findings.sort(key=lambda f: (f["path"], f["line"], f["rule"]))
    print(f"range: {label}")
    tests = sum(1 for f in files if TEST_PATH.search(f["path"]))
    ci = sum(1 for f in files if CI_PATH.search(f["path"]))
    print(f"checked: {len(files)} changed files ({tests} test files, {ci} CI files)")

    open_count = accepted = 0
    for f in findings:
        where = f"{f['path']}:{f['line']}" + (" (before)" if f["before"] else "")
        allow = next((a for a in allows if a[0] == f["path"] or fnmatch.fnmatch(f["path"], a[0])), None)
        if allow:
            allow[2] += 1
            accepted += 1
            print(f"accepted {f['rule']} {where} \"{f['text']}\" reason: {allow[1]}")
        else:
            open_count += 1
            print(f"FLOOR {f['rule']} {where} \"{f['text']}\" {f['why']}")
    for name, _, hits in allows:
        if hits == 0:
            print(f"unused --allow: no finding in {name}")

    if open_count:
        print(f"RESULT fail: {open_count} place{'s' if open_count != 1 else ''} weaken a safety floor"
              + (f" ({accepted} more accepted)" if accepted else ""))
        return 1
    print(f"{accepted} finding{'s' if accepted != 1 else ''} accepted with a reason" if accepted else "nothing weakened")
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
