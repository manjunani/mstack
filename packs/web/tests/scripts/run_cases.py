#!/usr/bin/env python3
"""Run every mstack-web script against local servers on 127.0.0.1 and compare each exit code with the expected one.

  run_cases.py --work .testrun/web-run1            build the throwaway pages in a NEW folder and run all cases
  run_cases.py --work .testrun/web-run2 --only link-check page-watch

Nothing here touches the public internet: the servers are fixture_server.py (Python's http.server) on
127.0.0.1, serving pages this file writes. HTTPS cases need the `openssl` command to make a throwaway
certificate; without it they are reported as skipped, never as passed.

Exit code: 0 = every case that ran gave the expected exit code and output, 1 = at least one did not.
"""
import argparse
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PACK = HERE.parent.parent
sys.path.insert(0, str(HERE))
import fixture_server  # noqa: E402
import cases_net  # noqa: E402
import cases_text  # noqa: E402


class Env:
    """What a case needs: folders, the script paths, and a way to start a fixture site."""

    def __init__(self, work):
        self.work, self.sites, self.results, self.skipped, self.show = work, [], [], [], False
        self.project = work / "project"
        self.project.mkdir(parents=True)

    def script(self, skill, name):
        return str(PACK / "skills" / skill / "scripts" / name)

    def site(self, name, files, **options):
        root = self.work / name
        for path, content in files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        root.mkdir(parents=True, exist_ok=True)
        site, base = fixture_server.start(root, **options)
        self.sites.append(site)
        return site, base

    def certificate(self, name, days):
        """Make a throwaway self-signed certificate for 127.0.0.1. Returns (cert, key) or None without openssl."""
        tool = shutil.which("openssl")
        if not tool:
            return None
        cert, key = self.work / f"{name}-cert.pem", self.work / f"{name}-key.pem"
        done = subprocess.run([tool, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
                               "-days", str(days), "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
                               "-addext", "keyUsage=critical,digitalSignature,keyCertSign",
                               "-addext", "basicConstraints=critical,CA:TRUE"], capture_output=True, text=True)
        return (str(cert), str(key)) if done.returncode == 0 else None

    def run(self, skill, name, script, argv, expect, has=(), lacks=(), check=None, cwd=None):
        done = subprocess.run([sys.executable, script, *[str(a) for a in argv]], cwd=cwd or self.project,
                              capture_output=True, text=True, timeout=180)
        output = done.stdout + done.stderr
        lines = [line for line in done.stdout.strip().splitlines() if line.strip()]
        last = lines[-1] if lines else ""
        problems = []
        if done.returncode != expect:
            problems.append(f"exit {done.returncode}, expected {expect}")
        wanted = {0: ("RESULT pass",), 1: ("RESULT fail",), 2: ("RESULT not verified", "blocked:")}[expect]
        if "--help" not in argv and not last.startswith(wanted):
            problems.append(f"last line is '{last[:90]}', expected it to start with {' or '.join(wanted)}")
        problems += [f"output lacks '{text}'" for text in has if text not in output]
        problems += [f"output should not contain '{text}'" for text in lacks if text in output]
        if check and not problems:
            note = check(output)
            if note:
                problems.append(note)
        self.results.append((skill, name, not problems))
        print(f"{'ok ' if not problems else 'BAD'} {skill:13} {name}  (exit {done.returncode}, expect {expect})")
        if self.show and not problems:
            print("     | " + "\n     | ".join(output.strip().splitlines()))
        if problems:
            print("     " + "\n     ".join(problems))
            print("     --- output ---\n     " + "\n     ".join(output.strip().splitlines()[-25:]))
        return output

    def skip(self, skill, name, why):
        self.skipped.append((skill, name, why))
        print(f"skip {skill:13} {name}  ({why})")


def main():
    groups = {**cases_net.GROUPS, **cases_text.GROUPS}
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work", type=pathlib.Path, required=True, help="a NEW folder for the throwaway pages, for example .testrun/web-run1")
    parser.add_argument("--only", nargs="*", default=[], choices=sorted(groups), help="run only these skills")
    parser.add_argument("--show", action="store_true", help="print the full output of every case, to read it yourself")
    args = parser.parse_args()
    work = args.work.resolve()
    if work.exists():
        print(f"refusing: {work} already exists; name a new folder")
        return 2
    env = Env(work)
    env.show = args.show
    for skill in sorted(groups):
        if not args.only or skill in args.only:
            print(f"#### {skill}")
            groups[skill](env)

    agents = {entry["agent"] for site in env.sites for entry in site["log"]}
    honest = all(agent.startswith("mstack-web/") and "github.com/manjunani/mstack" in agent for agent in agents)
    requests = sum(len(site["log"]) for site in env.sites)
    print(f"#### every request seen by the fixture servers: {requests}, distinct user agents: {len(agents)}")
    for agent in sorted(agents):
        print(f"     {agent}")
    env.results.append(("all", f"every request names mstack-web in its user agent ({requests} request(s))", honest))
    copies = {path.read_bytes() for path in PACK.glob("skills/*/scripts/webfetch.py")}
    env.results.append(("all", "the copies of webfetch.py are identical", len(copies) == 1))
    for skill, name, good in env.results[-2:]:
        print(f"{'ok ' if good else 'BAD'} {skill:13} {name}")

    for site in env.sites:
        site["server"].shutdown()
    print("#### totals")
    for skill in sorted({result[0] for result in env.results}):
        mine = [result for result in env.results if result[0] == skill]
        print(f"  {skill:13} {sum(1 for r in mine if r[2])}/{len(mine)} as expected")
    bad = [result for result in env.results if not result[2]]
    print(f"cases: {len(env.results)} run, {len(env.results) - len(bad)} as expected, {len(bad)} not, {len(env.skipped)} skipped")
    for skill, name, why in env.skipped:
        print(f"  skipped: {skill} {name}: {why}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
