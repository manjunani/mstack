"""Run env-check's envnames.py on a small project written by this test. The values are made up.

The main thing proven here: no value from the example file, the set-names file or a default in code is printed.
Usage: env_check_cases.py <new empty folder>
"""
import argparse
import json

import harness

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
folder = harness.new_folder(parser.parse_args().folder)
tool = harness.script("env-check", "envnames.py")
app = folder / "app"
(app / "src").mkdir(parents=True)
(app / "node_modules" / "lib").mkdir(parents=True)

VALUES = ["sk-made-up-value-111", "postgres://u:made-up-pw@db.internal/x", "fallback-made-up-222", "made-up-333", "made-up-444"]
(app / "src" / "server.ts").write_text(
    "const url = process.env.DATABASE_URL;\n"
    "const key = process.env['API_KEY'];\n"
    "const { REDIS_URL, PORT: port } = process.env;\n"
    "const site = import.meta.env.VITE_SITE_NAME;\n"
    "const mode = import.meta.env.MODE;\n"
    "const any = process.env[name];\n", encoding="utf-8")
(app / "src" / "worker.py").write_text(
    "import os\n"
    f"token = os.getenv(\"WORKER_TOKEN\", \"{VALUES[2]}\")\n"
    "queue = os.environ[\"QUEUE_NAME\"]\n"
    "region = os.environ.get('REGION')\n", encoding="utf-8")
(app / "src" / "main.rs").write_text(
    "fn main() {\n    let home = std::env::var(\"SERVICE_HOME\").unwrap();\n    let built = env!(\"BUILD_SHA\");\n}\n", encoding="utf-8")
(app / "node_modules" / "lib" / "index.js").write_text("process.env.SHOULD_BE_SKIPPED;\n", encoding="utf-8")
(app / ".env.example").write_text(
    f"DATABASE_URL={VALUES[1]}\nAPI_KEY={VALUES[0]}\nREDIS_URL=\nPORT=3000\nVITE_SITE_NAME=x\nWORKER_TOKEN=\n"
    "QUEUE_NAME=jobs\n# REGION=eu\nSERVICE_HOME=/srv\nOLD_FLAG=1\n", encoding="utf-8")
all_names = ["DATABASE_URL", "API_KEY", "REDIS_URL", "PORT", "VITE_SITE_NAME", "WORKER_TOKEN", "QUEUE_NAME", "REGION", "SERVICE_HOME", "BUILD_SHA"]
(folder / "set-full.txt").write_text("\n".join(f"{n}={VALUES[3]}" for n in all_names) + "\n", encoding="utf-8")
(folder / "set-short.json").write_text(json.dumps({n: VALUES[4] for n in all_names if n not in ("REDIS_URL", "QUEUE_NAME")}), encoding="utf-8")
(folder / "set-names-only.txt").write_text("\n".join(all_names + ["EXTRA_ONE"]) + "\n", encoding="utf-8")

cases = harness.Cases("env-check")

code, out = harness.run(tool, "--root", app, "--set-names", folder / "set-full.txt")
cases.check("BUILD_SHA is read but not documented", code, 1, out, lacks=VALUES + ["SHOULD_BE_SKIPPED"],
            has=("UNDOCUMENTED (read by code, not in the example file): 1", "BUILD_SHA   first read at src/main.rs:3", "OLD_FLAG", "src/server.ts:6"),
            last="RESULT fail")

(app / ".env.example").write_text((app / ".env.example").read_text() + "BUILD_SHA=\n", encoding="utf-8")
code, out = harness.run(tool, "--root", app, "--set-names", folder / "set-full.txt")
cases.check("all documented and set", code, 0, out, lacks=VALUES, has=("10 names read", "1 dynamic reads not resolved"), last="RESULT pass")

code, out = harness.run(tool, "--root", app, "--set-names", folder / "set-short.json")
cases.check("two names missing in the target (JSON list of names set)", code, 1, out, lacks=VALUES,
            has=("MISSING in the target (read by code, not set): 2", "QUEUE_NAME   first read at src/worker.py:3", "REDIS_URL"), last="RESULT fail")

code, out = harness.run(tool, "--root", app, "--set-names", folder / "set-names-only.txt", "--json")
data = json.loads(out[:out.rindex("RESULT")])
cases.check("bare names file, JSON output", code, 0, out, lacks=VALUES)
cases.check("JSON lists EXTRA_ONE and OLD_FLAG as unused", 0 if data["unused"] == ["EXTRA_ONE", "OLD_FLAG"] else 1, 0)

code, out = harness.run(tool, "--root", app)
cases.check("no list of names set in the target", code, 2, out, lacks=VALUES, last="RESULT not verified")

code, out = harness.run(tool, "--root", app, "--set-names", folder / "set-full.txt", "--ignore", "OLD_FLAG", "REGION")
cases.check("--ignore removes names from every list", code, 0, out, lacks=VALUES + ["OLD_FLAG"], has=("9 names read",))

(folder / "empty").mkdir()
code, out = harness.run(tool, "--root", folder / "empty")
cases.check("folder with no source files", code, 2, out, last="blocked")
code, out = harness.run(tool, "--root", app, "--set-names", folder / "nope.txt")
cases.check("set-names file that does not exist", code, 2, out, last="blocked")
(folder / "bad.json").write_text("{ \"A\": \"" + VALUES[0] + "\", ", encoding="utf-8")
code, out = harness.run(tool, "--root", app, "--set-names", folder / "bad.json")
cases.check("broken JSON is refused without echoing it", code, 2, out, lacks=VALUES, last="blocked")

raise SystemExit(cases.finish())
