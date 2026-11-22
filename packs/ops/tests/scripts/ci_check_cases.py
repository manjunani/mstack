"""Run ci-check's workflow.py on workflow files written by this test, and check its YAML reader directly.

The secret names below are names only; no real secret is involved.
Usage: ci_check_cases.py <new empty folder>
"""
import argparse
import importlib.util
import json

import harness

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
folder = harness.new_folder(parser.parse_args().folder)
tool = harness.script("ci-check", "workflow.py")
cases = harness.Cases("ci-check")
flows = folder / ".github" / "workflows"
flows.mkdir(parents=True)
SHA = "8f4b7f84864484a7bf31766abe9204da3cbe65b3"

GOOD = f"""---
name: CI
on:
  push:
    branches: [main, 'release/**']
  pull_request:
permissions:
  contents: read
env:
  NODE_VERSION: "20"   # a comment
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix: {{ node: [18, 20], os: [ubuntu-latest] }}
    steps:
      - uses: actions/checkout@v4
      - name: Install
        run: npm ci
      - name: Test
        run: |
          npm test
          echo "done: ok"   # not a comment, this is script text
        env:
          TOKEN: ${{{{ secrets.NPM_TOKEN }}}}
  deploy:
    needs: [test]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    permissions:
      contents: read
      deployments: write
    steps:
    - uses: someorg/deploy-action@{SHA}
      with:
        target: production
    - run: echo "${{{{ secrets.REGISTRY_PW }}}}" | docker login --password-stdin -u me
"""
(flows / "ci.yml").write_text(GOOD, encoding="utf-8")

# The reader itself: the parsed structure must be exactly this.
spec = importlib.util.spec_from_file_location("workflow", tool)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
doc = module.parse_yaml(GOOD)
want = {
    "name": "CI",
    "on": {"push": {"branches": ["main", "release/**"]}, "pull_request": None},
    "permissions": {"contents": "read"},
    "env": {"NODE_VERSION": "20"},
    "jobs": {
        "test": {"runs-on": "ubuntu-latest", "strategy": {"matrix": {"node": ["18", "20"], "os": ["ubuntu-latest"]}},
                 "steps": [{"uses": "actions/checkout@v4"}, {"name": "Install", "run": "npm ci"},
                           {"name": "Test", "run": "npm test\necho \"done: ok\"   # not a comment, this is script text",
                            "env": {"TOKEN": "${{ secrets.NPM_TOKEN }}"}}]},
        "deploy": {"needs": ["test"], "runs-on": "ubuntu-latest", "if": "github.ref == 'refs/heads/main'",
                   "permissions": {"contents": "read", "deployments": "write"},
                   "steps": [{"uses": f"someorg/deploy-action@{SHA}", "with": {"target": "production"}},
                             {"run": "echo \"${{ secrets.REGISTRY_PW }}\" | docker login --password-stdin -u me"}]},
    },
}
cases.check("YAML reader returns the expected structure", 0 if doc == want else 1, 0, json.dumps(doc, indent=1))
cases.check("reader keeps line numbers (deploy job is on line 26)", 0 if doc["jobs"].lines["deploy"] == 26 else 1, 0, str(doc["jobs"].lines))

code, out = harness.run(tool, "--root", folder)
cases.check("clean workflow, default folder", code, 0, out, has=("no findings",), last="RESULT pass")

BAD = """name: Release
on: push
job:
  oops: true
env:
  API_TOKEN: ${{ secrets.API_TOKEN }}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout
      - uses: thirdparty/setup-thing@main
      - uses: thirdparty/cache-thing@v2
      - name: Debug
        run: |
          set -e
          echo "token is $API_TOKEN"
          echo ${{ secrets.DEPLOY_KEY }}
      - name: Both
        run: make
        uses: actions/setup-node@v4
      - name: Neither
      - run: echo "${{ github.event.pull_request.title }}"
  lint:
    runs-on: ubuntu-latest
    runs-on: macos-latest
  publish:
    needs: [build, package]
    steps:
      - run: make publish
  a:
    needs: b
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
  b:
    needs: a
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
"""
bad = folder / "bad.yml"
bad.write_text(BAD, encoding="utf-8")
code, out = harness.run(tool, bad, "--json")
data = json.loads(out[:out.rindex("RESULT")])
found = data["findings"][str(bad)]
got = sorted((f["rule"], f["line"]) for f in found)
want_found = sorted([
    ("unknown-top-key", 3), ("unpinned-action", 11), ("unpinned-action", 12), ("tag-pinned-action", 13),
    ("secret-echoed", 17), ("secret-echoed", 18), ("step-shape", 19), ("step-shape", 22), ("event-text-in-run", 23),
    ("duplicate-key", 26), ("job-no-steps", 24), ("needs-missing", 28), ("job-no-runner", 27), ("no-permissions", 7),
    ("needs-missing", 31),
])
cases.check("bad workflow fails", code, 1, out, last="RESULT fail")
cases.check(f"all {len(want_found)} findings, each on its line", 0 if got == want_found else 1, 0,
            "missing: " + str(sorted(set(want_found) - set(got))) + "\n extra: " + str(sorted(set(got) - set(want_found))))
texts = " ".join(f["text"] for f in found)
cases.check("finding text names the secret, both ways", 0 if "API_TOKEN (through env API_TOKEN)" in texts and "DEPLOY_KEY" in texts else 1, 0, texts)

tagged = folder / "tagged.yml"
tagged.write_text("on: push\npermissions: {}\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: thirdparty/cache-thing@v2.1.0\n      - uses: docker://alpine:3.20\n", encoding="utf-8")
code, out = harness.run(tool, tagged)
cases.check("tag pin and docker tag are warnings", code, 0, out, has=("WARN line 7 tag-pinned-action", "WARN line 8 docker-no-digest"), last="RESULT pass")
code, out = harness.run(tool, tagged, "--require-sha")
cases.check("--require-sha turns the tag pin into a failure", code, 1, out, has=("FAIL line 7 tag-pinned-action",), last="RESULT fail")

as_json = folder / "flow.json"
as_json.write_text(json.dumps({"on": "push", "jobs": {"t": {"runs-on": "ubuntu-latest", "steps": [{"run": "make test"}]}}}), encoding="utf-8")
code, out = harness.run(tool, as_json)
cases.check("JSON workflow with no permissions block", code, 1, out, has=("no-permissions",), last="RESULT fail")

anchors = folder / "anchors.yml"
anchors.write_text("on: push\npermissions: {}\njobs:\n  a: &base\n    runs-on: ubuntu-latest\n    steps:\n      - run: make\n  b: *base\n", encoding="utf-8")
code, out = harness.run(tool, anchors)
cases.check("anchors are not read: not verified, with the line", code, 2, out, has=("NOT READ", "line 4"), last="RESULT not verified")

for name, text, marker in (("tabs.yml", "on: push\njobs:\n\tx:\n\t\truns-on: y\n", "tab"),
                           ("openflow.yml", "on: [push,\n  pull_request]\njobs: {}\n", "does not close"),
                           ("multi.yml", "on: push\n---\non: pull_request\n", "several documents"),
                           ("empty.yml", "# nothing\n", "empty")):
    path = folder / name
    path.write_text(text, encoding="utf-8")
    code, out = harness.run(tool, path)
    cases.check(f"{name}: not verified", code, 2, out, has=(marker,), last="RESULT not verified")

code, out = harness.run(tool, bad, anchors)
cases.check("a failing file and an unread file together fail", code, 1, out, has=("1 file(s) not read",), last="RESULT fail")
code, out = harness.run(tool, "--root", folder / "nowhere")
cases.check("no workflow folder", code, 2, out, last="blocked")
(folder / "none").mkdir()
code, out = harness.run(tool, folder / "none")
cases.check("folder with no workflow files", code, 2, out, last="blocked")

raise SystemExit(cases.finish())
