#!/usr/bin/env python3
"""Check that a built Mac app or disk image is signed, accepted by Gatekeeper and carries its notarisation ticket.

  macverify.py PATH            PATH is an .app bundle or a .dmg disk image
  macverify.py PATH --mount    for a .dmg: also attach it read-only and check the app inside

Three checks, each reported as pass, fail or could not check:

  signature    codesign --verify --deep --strict --verbose=2 PATH
               pass only when the exit code is 0 and the output says "valid on disk"
  gatekeeper   spctl --assess --type execute --verbose=4 PATH        (.app)
               spctl --assess --type open --context context:primary-signature --verbose=4 PATH   (.dmg)
               pass only when the exit code is 0 and the output says "accepted"
  staple       xcrun stapler validate PATH
               pass only when the exit code is 0 and the output says the validate action worked

Details printed but not judged: who signed it, the team id, whether the signature is ad hoc,
whether the hardened runtime flag is set, the architectures, and the version in Info.plist.
Two optional checks are judged when asked for: --expect-version and --expect-team.

Read-only. It signs nothing, notarises nothing, uploads nothing and installs nothing.
Raw tool output is kept under --out (default .mstack/mac-release-verify/<time>/).

Not checked: a first launch on a Mac that has never seen the app. Gatekeeper's answer on
this machine is the nearest thing a script can get; it can be given online, without a
stapled ticket, which is why the staple is a separate check.

Exit codes: 0 = all checks pass
            1 = at least one check failed
            2 = blocked (not macOS, no such file, wrong kind of file) or a check could not run
"""
import argparse
import datetime
import json
import pathlib
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile


def call(command, timeout=300):
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"no answer after {timeout} seconds"
    except OSError as exc:
        return None, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def short(text, lines=4):
    rows = [r.strip() for r in text.splitlines() if r.strip()]
    return " / ".join(rows[-lines:]) if rows else "(no output)"


class Report:
    def __init__(self, out):
        self.rows, self.out = [], out

    def add(self, name, status, detail, command=None, output=None):
        self.rows.append({"check": name, "status": status, "detail": detail})
        print(f"{status:15} {name:16} {detail}")
        if command is not None and self.out is not None:
            safe = re.sub(r"[^a-z0-9]+", "-", name.lower())
            n = sum(1 for _ in self.out.glob(f"{safe}*.txt"))
            (self.out / f"{safe}{'' if n == 0 else '-' + str(n + 1)}.txt").write_text(
                "$ " + " ".join(command) + "\n" + (output or "") + "\n", encoding="utf-8")

    def count(self, status):
        return [r for r in self.rows if r["status"] == status]


def check_signature(report, tools, path, label="signature"):
    if not tools["codesign"]:
        report.add(label, "could not check", "codesign is not on this machine (it comes with the Xcode command-line tools)")
        return
    command = [tools["codesign"], "--verify", "--deep", "--strict", "--verbose=2", str(path)]
    code, out = call(command)
    if code is None:
        report.add(label, "could not check", f"codesign did not run: {out}", command, out)
    elif code == 0 and "valid on disk" in out:
        report.add(label, "pass", "valid on disk" + ("; satisfies its designated requirement" if "satisfies its Designated Requirement" in out else ""), command, out)
    else:
        report.add(label, "fail", f"codesign exit {code}: {short(out)}", command, out)


def signer_details(tools, path):
    """Return a dict of facts from `codesign -dv --verbose=4`. Empty when the tool cannot say."""
    if not tools["codesign"]:
        return {}
    code, out = call([tools["codesign"], "-dv", "--verbose=4", str(path)])
    if code != 0 or "not signed at all" in out:
        return {"signed": False}
    flags = re.search(r"flags=0x[0-9a-f]+\(([^)]*)\)", out)
    team = re.search(r"^TeamIdentifier=(.+)$", out, re.M)
    return {"signed": True, "authorities": re.findall(r"^Authority=(.+)$", out, re.M),
            "team": team.group(1).strip() if team else None,
            "adhoc": "Signature=adhoc" in out or bool(flags and "adhoc" in flags.group(1)),
            "hardened_runtime": bool(flags and "runtime" in flags.group(1).split(","))}


def check_gatekeeper(report, tools, path, kind, label="gatekeeper"):
    if not tools["spctl"]:
        report.add(label, "could not check", "spctl is not on this machine")
        return
    code, status = call([tools["spctl"], "--status"])
    if code is None or "disabled" in status:
        report.add(label, "could not check", f"Gatekeeper assessments are switched off on this Mac ({short(status)}); its answer would mean nothing")
        return
    command = [tools["spctl"], "--assess", "--type", "execute", "--verbose=4", str(path)]
    if kind == "dmg":
        command = [tools["spctl"], "--assess", "--type", "open", "--context", "context:primary-signature", "--verbose=4", str(path)]
    code, out = call(command)
    source = re.search(r"^source=(.+)$", out, re.M)
    origin = f" (source: {source.group(1).strip()})" if source else ""
    if code is None:
        report.add(label, "could not check", f"spctl did not run: {out}", command, out)
    elif code == 0 and re.search(r":\s*accepted\s*$", out, re.M):
        report.add(label, "pass", "accepted" + origin, command, out)
    else:
        report.add(label, "fail", f"spctl exit {code}: {short(out)}", command, out)


def check_staple(report, tools, path, label="staple"):
    if not tools["stapler"]:
        report.add(label, "could not check", "stapler was not found through xcrun (it comes with full Xcode)")
        return
    command = [tools["xcrun"], "stapler", "validate", str(path)]
    code, out = call(command)
    if code is None:
        report.add(label, "could not check", f"stapler did not run: {out}", command, out)
    elif code == 0 and "validate action worked" in out:
        report.add(label, "pass", "a notarisation ticket is stapled and valid", command, out)
    elif "does not have a ticket stapled" in out:
        report.add(label, "fail", "no notarisation ticket is stapled to it", command, out)
    else:
        report.add(label, "fail", f"stapler exit {code}: {short(out)}", command, out)


def app_facts(tools, app):
    """Return (facts, problem) read from the bundle itself."""
    plist = app / "Contents" / "Info.plist"
    try:
        with plist.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        return None, f"cannot read {plist}: {exc}"
    facts = {"bundle_id": info.get("CFBundleIdentifier"), "version": info.get("CFBundleShortVersionString"),
             "build": info.get("CFBundleVersion"), "executable": info.get("CFBundleExecutable")}
    binary = app / "Contents" / "MacOS" / str(facts["executable"])
    if not facts["executable"] or not binary.is_file():
        return None, f"the bundle has no executable at {binary}"
    lipo = shutil.which("lipo")
    if lipo:
        code, out = call([lipo, "-archs", str(binary)])
        facts["architectures"] = out.split() if code == 0 else None
    return facts, None


def check_app(report, tools, app, args, prefix=""):
    facts, problem = app_facts(tools, app)
    if problem:
        report.add(prefix + "bundle", "fail", problem)
        return
    signer = signer_details(tools, app)
    print(f"{'detail':15} {prefix}bundle      {facts['bundle_id']} version {facts['version']} (build {facts['build']}), "
          f"architectures: {' '.join(facts.get('architectures') or ['not read'])}")
    if signer.get("signed"):
        who = signer["authorities"][0] if signer["authorities"] else ("ad hoc signature, no certificate" if signer["adhoc"] else "no authority listed")
        print(f"{'detail':15} {prefix}signer      {who}; team {signer['team']}; hardened runtime flag {'set' if signer['hardened_runtime'] else 'NOT set'}")
    elif signer:
        print(f"{'detail':15} {prefix}signer      not signed")
    check_signature(report, tools, app, prefix + "signature")
    check_gatekeeper(report, tools, app, "app", prefix + "gatekeeper")
    check_staple(report, tools, app, prefix + "staple")
    if args.expect_version:
        same = facts["version"] == args.expect_version
        report.add(prefix + "version", "pass" if same else "fail", f"Info.plist says {facts['version']}, expected {args.expect_version}")
    if args.expect_team:
        if not signer:
            report.add(prefix + "team", "could not check", "codesign is not available to read the team id")
        else:
            same = signer.get("team") == args.expect_team
            report.add(prefix + "team", "pass" if same else "fail", f"signed by team {signer.get('team')}, expected {args.expect_team}")


def check_dmg(report, tools, dmg, args):
    signer = signer_details(tools, dmg)
    if signer and not signer.get("signed"):
        print(f"{'detail':15} image       the disk image itself carries no signature; the signature check below will say so")
    check_signature(report, tools, dmg)
    check_gatekeeper(report, tools, dmg, "dmg")
    check_staple(report, tools, dmg)
    if not args.mount:
        report.add("app inside", "could not check", "the app inside the image was not opened; run again with --mount, or give the mounted .app")
        return
    hdiutil = shutil.which("hdiutil")
    if not hdiutil:
        report.add("app inside", "could not check", "hdiutil is not on this machine")
        return
    with tempfile.TemporaryDirectory(prefix="mstack-macverify-") as scratch:
        point = pathlib.Path(scratch) / "volume"
        point.mkdir()
        code, out = call([hdiutil, "attach", "-readonly", "-nobrowse", "-noautoopen", "-mountpoint", str(point), str(dmg)])
        if code != 0:
            report.add("app inside", "could not check", f"the image did not attach: {short(out)}")
            return
        try:
            apps = sorted(point.glob("*.app"))
            if not apps:
                report.add("app inside", "fail", "the image holds no .app at its top level")
            for app in apps[:1]:
                print(f"{'detail':15} app inside  {app.name} (image attached read-only; it is detached after the checks)")
                check_app(report, tools, app, args, prefix="inner ")
            if len(apps) > 1:
                report.add("app inside", "could not check", f"{len(apps)} apps in the image; only {apps[0].name} was checked")
        finally:
            code, out = call([hdiutil, "detach", str(point)])
            if code != 0:
                print(f"warning: the image is still attached at {point}: {short(out)}. Eject it by hand.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="the .app bundle or .dmg disk image to check")
    parser.add_argument("--mount", action="store_true", help="for a .dmg: attach it read-only and check the app inside, then detach")
    parser.add_argument("--expect-version", help="the version the build should carry (CFBundleShortVersionString)")
    parser.add_argument("--expect-team", help="the team id that should have signed it")
    parser.add_argument("--out", help="folder for raw tool output (default .mstack/mac-release-verify/<time>/)")
    parser.add_argument("--no-save", action="store_true", help="do not keep raw tool output")
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("blocked: these checks need macOS (codesign, spctl and stapler exist only there)")
        return 2
    path = pathlib.Path(args.path)
    kind = {".app": "app", ".dmg": "dmg"}.get(path.suffix.lower())
    if not path.exists():
        print(f"blocked: nothing at {path}. Give the path of the built .app or .dmg.")
        return 2
    if kind is None or (kind == "app") != path.is_dir():
        print(f"blocked: {path} is not an .app bundle or a .dmg disk image")
        return 2
    xcrun = shutil.which("xcrun")
    stapler = None
    if xcrun:
        code, out = call([xcrun, "-f", "stapler"], timeout=60)
        stapler = out.splitlines()[-1] if code == 0 and out else None
    tools = {"codesign": shutil.which("codesign"), "spctl": shutil.which("spctl"), "xcrun": xcrun, "stapler": stapler}

    out = None
    if not args.no_save:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        out = pathlib.Path(args.out) if args.out else pathlib.Path(".mstack") / "mac-release-verify" / stamp
        base, n = out, 1
        while out.exists() and any(out.iterdir()):
            n += 1
            out = base.with_name(f"{base.name}-{n}")
        out.mkdir(parents=True, exist_ok=True)
    report = Report(out)
    print(f"artifact: {path.resolve()} ({kind})")
    if kind == "app":
        check_app(report, tools, path, args)
    else:
        check_dmg(report, tools, path, args)

    passed, failed, unknown = report.count("pass"), report.count("fail"), report.count("could not check")
    print(f"checked: {len(report.rows)} checks; {len(passed)} pass, {len(failed)} fail, {len(unknown)} could not check")
    print("not checked: a first launch on a Mac that has never seen this app. A person does that with a downloaded copy.")
    if out is not None:
        (out / "report.json").write_text(json.dumps({"artifact": str(path.resolve()), "checks": report.rows}, indent=2) + "\n", encoding="utf-8")
        print(f"raw output: {out}")
    if failed:
        print("RESULT fail: " + "; ".join(f"{r['check']}: {r['detail']}" for r in failed))
        return 1
    if unknown:
        print("RESULT not verified: " + "; ".join(f"{r['check']}: {r['detail']}" for r in unknown))
        return 2
    print(f"RESULT pass: {len(passed)} of {len(passed)} checks pass (signature, Gatekeeper, stapled ticket)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
