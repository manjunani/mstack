"""Cases for the mstack-web scripts that read local files only (no server needed)."""
import json


def write(folder, files):
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def cite_check(env):
    script = env.script("cite-check", "cite_check.py")
    run = lambda name, argv, expect, **kw: env.run("cite-check", name, script, argv, expect, **kw)
    base = env.work / "cite"
    sources = write(base / "sources", {
        "S1.txt": "The harbour office reported that\nthe fee is   40 per night for boats under ten metres. Larger boats pay more.",
        "report.html": "<html><body><script>var x='hidden words here';</script><p>Mooring rose by “four percent” — the largest rise since 2019.</p></body></html>",
        "page.json": json.dumps({"title": "Quay notes", "text": "The north quay closes for repairs in March and reopens in May."}),
        "index.json": json.dumps({"R": {"file": "report.html", "url": "https://example.org/report"}, "Q": "page.json"}),
    })
    write(base, {"good.md": (
        "# Draft\n\nThe office says \"the fee is 40 per night\" [S1].\n\n"
        "A report found that mooring rose by \"four percent - the largest rise\" ([report](https://example.org/report)).\n\n"
        "> The north quay closes for repairs ... reopens in May.\n\n— [Q]\n\n"
        "Some call it a \"safe haven\" for boats.\n")})
    good = base / "good.md"
    run("help", ["--help"], 0, has=["--claims"])
    run("all quotes found (spacing, curly quotes, dash, ellipsis, html, page-extract json)", [good, "--sources", sources], 0,
        has=["found (3)", "skipped: 1 quoted phrase", "RESULT pass: 3"])
    write(base, {"bad.md": "He said \"the fee is 45 per night\" [S1].\n\nShe wrote \"hidden words here in a script\" [R].\n\n"
                           "They noted \"a quote that has no reference at all\".\n\nAnd \"from a source never saved\" [S9].\n"})
    run("changed quote, script text, no reference, unsaved source", [base / "bad.md", "--sources", sources], 1,
        has=["not found (2)", "longest run that does match", "source missing (2)", "no source reference", "no saved copy for 'S9'"])
    write(base, {"missing.md": "It says \"the fee is 40 per night\" [S1] and \"never saved anywhere at all\" [S7].\n"})
    run("only a missing source: not verified", [base / "missing.md", "--sources", sources], 2, has=["source missing (1)", "found (1)"])
    write(base, {"case.md": "\"THE FEE IS 40 PER NIGHT\" [S1]\n"})
    run("letter case differs: found with a note", [base / "case.md", "--sources", sources], 0, has=["letter case differs"])
    claims = base / "claims.json"
    claims.write_text(json.dumps([
        {"claim": "Fees are 40", "source": "S1", "verdict": "supported", "quote": "the fee is 40 per night"},
        {"claim": "Repairs in March", "source": "https://example.org/report", "verdict": "contradicted", "quote": "closes in June"},
        {"claim": "No quote given", "source": "S1", "verdict": "supported"},
        {"claim": "Site gone", "source": "S5", "verdict": "unreachable"},
        {"claim": "Not covered", "source": "S1", "verdict": "absent"},
        {"claim": "Bad verdict", "source": "S1", "verdict": "probably"}]))
    write(base, {"empty.md": "No quotes here at all.\n"})
    run("claims file: wrong quote, missing quote, bad verdict, unreachable, absent", [base / "empty.md", "--sources", sources, "--claims", claims], 1,
        has=["not found (2)", "malformed claim entries (2)", "source missing (1)", "found (1)", "marked absent"])
    run("document with nothing to check", [base / "empty.md", "--sources", sources], 2, has=["no quotes or claims were found"])
    out = env.project / "cite.json"
    run("writes the lists", [good, "--sources", sources, "--json", out], 0,
        check=lambda o: None if len(json.loads(out.read_text())["found"]) == 3 else "JSON does not list 3 found")
    run("refuses to overwrite the lists", [good, "--sources", sources, "--json", out], 2, has=["already exists"])
    run("sources folder that does not exist", [good, "--sources", base / "nope"], 2, has=["is not a folder"])
    run("document that does not exist", [base / "nope.md", "--sources", sources], 2, has=["could not be read"])
    write(base / "bad-index", {"index.json": "{not json"})
    run("broken index.json", [good, "--sources", base / "bad-index"], 2, has=["could not be read"])


def web_research(env):
    script = env.script("web-research", "notes_check.py")
    run = lambda name, argv, expect, **kw: env.run("web-research", name, script, argv, expect, **kw)
    base = env.work / "research"
    write(base / "saved", {"fees.txt": "the fee is 40 per night", "council.txt": "council minutes"})
    good = """# Notes
- claim: The quay fee is 40 per night.
  label: quoted
  url: https://harbour.example/fees
  saved: fees.txt
  accessed: 2026-11-20
  quote: "the fee is 40 per night"
- claim: The council approved a rise in 2025.
  label: paraphrased
  url: https://council.example/minutes
  accessed: 2026-11-21
- claim: The rise was the first in five years.
  label: inferred
  from: C1, C2
- conclusion: Fees rose in 2025 after a long pause.
  label: inferred
  from: C1, C2
"""
    write(base, {"good.md": good})
    run("help", ["--help"], 0, has=["single source"])
    run("template", ["--template"], 0, has=["- claim:", "from: C1, C2"])
    run("well-formed notes", [base / "good.md", "--sources", base / "saved"], 0, has=["3 claim(s) (1 quoted, 1 paraphrased, 1 inferred), 1 conclusion(s)"])
    bad = good.replace("  url: https://council.example/minutes\n  accessed: 2026-11-21\n", "") \
              .replace("  from: C1, C2\n- conclusion", "- conclusion").replace("  quote: \"the fee is 40 per night\"\n", "")
    write(base, {"bad.md": bad})
    run("claim with no source, inference with no basis, quoted with no quote", [base / "bad.md"], 1,
        has=["C2 (line 7): no source", "C3 (line 9): inferred with nothing", "C1 (line 2): labelled quoted but has no quote"])
    single = good.replace("https://council.example/minutes", "https://harbour.example/minutes")
    write(base, {"single.md": single, "single-said.md": single.replace("after a long pause.", "after a long pause (single source).")})
    run("conclusion on a single source fails", [base / "single.md"], 1, has=["rests on a single source (harbour.example)"])
    run("conclusion that says single source only warns", [base / "single-said.md"], 0, has=["warn", "the conclusion says so itself"])
    write(base, {"nolabel.md": "- claim: Something.\n  url: https://a.example/x\n  accessed: 2026-11-20\n",
                 "nodate.md": "- claim: Something.\n  label: paraphrased\n  url: https://a.example/x\n",
                 "future.md": "- claim: Something.\n  label: paraphrased\n  url: https://a.example/x\n  accessed: 2999-01-01\n",
                 "badref.md": good.replace("from: C1, C2\n", "from: C1, C9\n", 2).replace("label: inferred\n  from: C1, C9\n- conclusion", "label: inferred\n  from: C1, C2\n- conclusion"),
                 "none.md": "# Notes\nJust thoughts, no claims.\n"})
    run("claim with no label", [base / "nolabel.md"], 1, has=["label is 'missing'"])
    run("url with no saved copy and no access date", [base / "nodate.md"], 1, has=["url without a saved copy or an access date"])
    run("access date in the future", [base / "future.md"], 1, has=["is in the future"])
    run("conclusion rests on a claim that does not exist", [base / "badref.md"], 1, has=["C9, which are not claims"])
    run("no claims at all", [base / "none.md"], 2, has=["no 'claim:' items"])
    run("saved copy missing from the folder", [base / "good.md", "--sources", base], 2, has=["fees.txt is not in"])
    run("notes file that does not exist", [base / "nope.md"], 2, has=["could not be read"])


GROUPS = {"cite-check": cite_check, "web-research": web_research}
