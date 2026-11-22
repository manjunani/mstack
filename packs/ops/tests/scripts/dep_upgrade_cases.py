"""Run dep-upgrade's upgrade.py through a whole upgrade in a project written by this test.

The "upgrade" is made by rewriting the lock file, as a package manager would; nothing is installed.
Usage: dep_upgrade_cases.py <new empty folder>
"""
import argparse
import json
import sys

import harness

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
folder = harness.new_folder(parser.parse_args().folder)
tool = harness.script("dep-upgrade", "upgrade.py")
cases = harness.Cases("dep-upgrade")
app = folder / "app"
app.mkdir()
r = ("--root", app)


def lock(version):
    (app / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "": {"dependencies": {"left-pad": "^1.1.0"}},
        "node_modules/left-pad": {"version": version},
        "node_modules/other/node_modules/left-pad": {"version": "1.0.0"}}}), encoding="utf-8")


lock("1.1.3")
(app / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "^1.1.0"}}), encoding="utf-8")
(app / "test.py").write_text(
    "import json, sys\nv = json.load(open('package-lock.json'))['packages']['node_modules/left-pad']['version']\n"
    "print('3 tests,', 'version', v)\nsys.exit(1 if v.startswith('2.0') else 0)\n", encoding="utf-8")
test = ("--", sys.executable, "test.py")
notes = folder / "CHANGELOG.md"
notes.write_text("# Changelog\n\n## 1.3.0 - 2026-10-01\n- new option\n\n## [1.2.0] - 2026-06-01\n- faster\n\n## 1.1.3\n- fix\n", encoding="utf-8")

code, out = harness.run(tool, *r, "check", "left-pad")
cases.check("check with no record", code, 2, out, last="blocked")
code, out = harness.run(tool, *r, "start", "left-pad", "--to", "1.1.3")
cases.check("target already in place", code, 2, out, last="blocked")
code, out = harness.run(tool, *r, "start", "right-pad", "--to", "2.0.0")
cases.check("package not in any file", code, 2, out, last="blocked")
code, out = harness.run(tool, *r, "start", "left-pad", "--to", "1.3.0")
cases.check("start reads 1.1.3 from the lock file", code, 0, out, has=("left-pad: 1.1.3 in package-lock.json (lock); other versions in the same file: 1.0.0",), last="RESULT pass")
code, out = harness.run(tool, *r, "start", "left-pad", "--to", "1.3.0")
cases.check("second start does not overwrite the record", code, 2, out, last="blocked")

code, out = harness.run(tool, *r, "check", "left-pad")
cases.check("nothing done yet: not verified, four gaps", code, 2, out, last="RESULT not verified")

code, out = harness.run(tool, *r, "changelog", "left-pad", "--file", notes)
cases.check("changelog has sections 1.2.0 and 1.3.0", code, 0, out, has=("between 1.1.3 and 1.3.0: 1.3.0, 1.2.0",), last="RESULT pass")
code, out = harness.run(tool, *r, "test", "left-pad", "--phase", "before", *test)
cases.check("tests before, on 1.1.3", code, 0, out, has=("version 1.1.3",), last="RESULT pass")

code, out = harness.run(tool, *r, "check", "left-pad")
cases.check("check before the upgrade is made", code, 2, out, has=("MISS target in place: package-lock.json holds 1.1.3",), last="RESULT not verified")
code, out = harness.run(tool, *r, "test", "left-pad", "--phase", "after", *test)
code, out = harness.run(tool, *r, "check", "left-pad")
cases.check("'after' run on the old version: the upgrade did not happen", code, 1, out, has=("still holds 1.1.3",), last="RESULT fail")

lock("1.3.0")
code, out = harness.run(tool, *r, "test", "left-pad", "--phase", "before", *test)
cases.check("'before' refused once the target is in place", code, 2, out, last="blocked")
code, out = harness.run(tool, *r, "test", "left-pad", "--phase", "after", "--", sys.executable, "-c", "pass")
cases.check("'after' with another command is refused", code, 2, out, last="blocked")
code, out = harness.run(tool, *r, "check", "left-pad")
cases.check("upgraded but tests after not run", code, 2, out, has=("MISS tests after: exit 0 on 1.1.3, 1.0.0; STALE",), last="RESULT not verified: missing tests after")
code, out = harness.run(tool, *r, "test", "left-pad", "--phase", "after", *test)
cases.check("tests after, on 1.3.0", code, 0, out, last="RESULT pass")
code, out = harness.run(tool, *r, "check", "left-pad")
cases.check("all four pieces: done", code, 0, out, lacks=("MISS",), last="RESULT pass: left-pad 1.1.3 to 1.3.0")

# A major upgrade that breaks the tests, with release notes that skip the target.
lock("1.3.0")
code, out = harness.run(tool, *r, "start", "left-pad", "--to", "2.0.1", "--restart")
cases.check("major upgrade is called out", code, 0, out, has=("MAJOR",))
code, out = harness.run(tool, *r, "changelog", "left-pad", "--file", notes)
cases.check("changelog without the target's section", code, 2, out, last="RESULT not verified: no section for 2.0.1")
code, out = harness.run(tool, *r, "test", "left-pad", "--phase", "before", *test)
lock("2.0.1")
code, out = harness.run(tool, *r, "test", "left-pad", "--phase", "after", *test)
cases.check("tests fail after the major upgrade", code, 1, out, last="RESULT fail")
code, out = harness.run(tool, *r, "check", "left-pad")
cases.check("check refuses: passed before, fails after", code, 1, out, has=("Revert the upgrade",), last="RESULT fail")

# Other ecosystems: the version is read from each file type.
other = folder / "eco"
other.mkdir()
files = {
    "poetry.lock": ('[[package]]\nname = "Requests"\nversion = "2.31.0"\n\n[[package]]\nname = "idna"\nversion = "3.6"\n', "requests", "2.31.0"),
    "Cargo.lock": ('[[package]]\nname = "serde"\nversion = "1.0.190"\n', "serde", "1.0.190"),
    "go.mod": ("module x\n\nrequire (\n\tgithub.com/pkg/errors v0.9.1\n)\n", "github.com/pkg/errors", "v0.9.1"),
    "Gemfile.lock": ("GEM\n  specs:\n    rack (3.0.8)\n      something\n", "rack", "3.0.8"),
    "requirements.txt": ("Django==4.2.7  # web\nflask>=2.0\n", "django", "4.2.7"),
    "yarn.lock": ('"lodash@^4.17.0", lodash@^4.17.21:\n  version "4.17.21"\n  resolved "x"\n', "lodash", "4.17.21"),
    "pnpm-lock.yaml": ("packages:\n\n  /zod@3.22.4:\n    resolution: {integrity: x}\n", "zod", "3.22.4"),
}
for name, (text, package, version) in files.items():
    sub = other / name.replace(".", "_")
    sub.mkdir()
    (sub / name).write_text(text, encoding="utf-8")
    code, out = harness.run(tool, "--root", sub, "start", package, "--to", "99.0.0")
    cases.check(f"{name}: reads {package} {version}", code, 0, out, has=(f"{package}: {version} in {name}",))

raise SystemExit(cases.finish())
