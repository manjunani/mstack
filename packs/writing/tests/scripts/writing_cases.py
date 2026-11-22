"""Script test for the writing pack: editcheck.py (copyedit) and parity.py (translate-check).

Each case writes small text files into a new folder and runs a script on them.
Usage: writing_cases.py <new folder>   (for example .testrun/writing)
"""
import argparse
import json
import pathlib
import subprocess
import sys

PACK = pathlib.Path(__file__).resolve().parents[2]
E = PACK / "skills" / "copyedit" / "scripts" / "editcheck.py"
P = PACK / "skills" / "translate-check" / "scripts" / "parity.py"
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder", type=pathlib.Path)
root = parser.parse_args().folder.resolve()
if root.exists():
    sys.exit(f"refusing: {root} already exists")
root.mkdir(parents=True)
total = wrong = 0


def put(name, data):
    path = root / name
    path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def case(name, command, want, must=None):
    global total, wrong
    done = subprocess.run([sys.executable, *map(str, command)], capture_output=True, text=True)
    out = done.stdout + done.stderr
    ok = done.returncode == want and (must is None or must in out)
    total += 1
    wrong += not ok
    print(f"{'ok  ' if ok else 'BAD '}{name}: exit {done.returncode} (expect {want})  |  {(done.stdout.strip().splitlines() or [''])[-1][:140]}")
    if not ok:
        print("      " + "\n      ".join(out.strip().splitlines()[-8:]))


print("#### copyedit")
orig = put("orig.md", "In order to recieve your refund, Maria must utilise the `refund --id 42` command.\n"
                      "The fee is $25 and it was added on 4 March 2026. See [the guide](https://example.com/refunds).\n"
                      "Support said \"we will reply in 3 days\" and Acme kept it's promise.\n")
good = "To receive your refund, Maria must use the `refund --id 42` command.\nThe fee is $25 and it was added on 4 March 2026. See [the guide](https://example.com/refunds).\nSupport said \"we will reply in 3 days\" and Acme kept its promise.\n"
items = [{"category": "correction", "rule": "H1", "before": "In order to recieve", "after": "To receive"},
         {"category": "correction", "rule": "H4", "before": "utilise", "after": "use"},
         {"category": "correction", "rule": "H6", "before": "it's promise", "after": "its promise"},
         {"category": "suggestion", "rule": "H2", "before": "The fee is $25 and it was added", "after": "The $25 fee was added", "applied": False},
         {"category": "query", "before": "4 March 2026", "note": "The invoice says 5 March. Which is right?"}]
put("good.md", good)
put("good.json", {"items": items})
case("rules: list the house style", [E, "rules"], 0, "12 rules")
case("check: clean edit", [E, "check", orig, root / "good.md", "--changes", root / "good.json"], 0, "3 corrections, 1 suggestions (0 accepted), 1 queries")
case("check: an unlisted change", [E, "check", orig, put("extra.md", good.replace("Support said", "Our team said")), "--changes", root / "good.json"], 1, "change not in the list")
case("check: code span changed", [E, "check", orig, put("code.md", good.replace("--id 42", "--id=42")), "--changes", root / "good.json"], 1, "protected code")
case("check: quotation reworded", [E, "check", orig, put("quote.md", good.replace("we will reply", "we'll reply")), "--changes", root / "good.json"], 1, "protected quotation")
case("check: link changed", [E, "check", orig, put("link.md", good.replace("example.com/refunds", "example.com/refund")), "--changes", root / "good.json"], 1, "protected link")
case("check: number changed", [E, "check", orig, put("num.md", good.replace("$25", "$26")), "--changes", root / "good.json"], 1, "number '25'")
case("check: name dropped", [E, "check", orig, put("name.md", good.replace("Maria must", "you must")), "--changes", root / "good.json"], 1, "name 'Maria'")
case("check: query applied as if it were a correction", [E, "check", orig, put("q.md", good.replace("4 March", "5 March")), "--changes", root / "good.json"], 1, "number '4'")
case("check: correction cites no rule", [E, "check", orig, root / "good.md", "--changes", put("norule.json", {"items": [dict(items[0], rule="")] + items[1:]})], 1, "with no rule")
case("check: correction cites a rule the guide lacks", [E, "check", orig, root / "good.md", "--changes", put("badrule.json", {"items": [dict(items[0], rule="H99")] + items[1:]})], 1, "'H99' is not in")
case("check: listed change not in the original", [E, "check", orig, root / "good.md", "--changes", put("ghost.json", {"items": items + [{"category": "correction", "rule": "H6", "before": "teh", "after": "the"}]})], 1, "is not in the original")
accepted = [dict(i, applied=True) if i["category"] == "suggestion" else i for i in items]
case("check: accepted suggestion applied", [E, "check", orig, put("acc.md", good.replace("The fee is $25 and it was added", "The $25 fee was added")), "--changes", put("acc.json", {"items": accepted})], 0)
case("check: second pass finds a new correction", [E, "check", orig, root / "good.md", "--changes", root / "good.json", "--second", put("second.json", {"items": [{"category": "correction", "rule": "H6", "before": "x", "after": "y"}]})], 1, "second pass")
case("check: second pass finds nothing", [E, "check", orig, root / "good.md", "--changes", root / "good.json", "--second", put("second0.json", {"items": []})], 0)
case("check: list file is not a list", [E, "check", orig, root / "good.md", "--changes", orig], 2, "blocked")

print("#### translate-check")
src = put("en.txt", "Your order #4512 of 3 items ships on 12.05.2026. Pay 1,250.00 EUR at https://shop.example.com/pay?id=7 "
                    "or write to help@example.com. Hello {name}, you have %d new <b>invoices</b>. Read the [terms](https://example.com/t). mstack invoice.\n")
de = put("de.txt", "Ihre Bestellung #4512 mit 3 Artikeln wird am 12.05.2026 versandt. Zahlen Sie 1,250.00 EUR unter https://shop.example.com/pay?id=7 "
                   "oder schreiben Sie an help@example.com. Hallo {name}, Sie haben %d neue <b>Rechnungen</b>. Lesen Sie die [AGB](https://example.com/t). mstack Rechnung.\n")
gl = put("glossary.json", {"invoice": "Rechnung", "mstack": "mstack"})
case("text: faithful translation", [P, "text", src, de, "--glossary", gl], 0, "translation quality was not checked")
case("text: placeholder translated", [P, "text", src, put("de-ph.txt", de.read_text().replace("{name}", "{Name}")), "--glossary", gl], 1, "placeholders differ")
case("text: number reformatted", [P, "text", src, put("de-num.txt", de.read_text().replace("1,250.00", "1.250,00")), "--glossary", gl], 1, "numbers differ")
case("text: number reformatted, user allowed it", [P, "text", src, root / "de-num.txt", "--glossary", gl, "--loose-numbers"], 0)
case("text: link address changed", [P, "text", src, put("de-url.txt", de.read_text().replace("pay?id=7", "pay?id=8")), "--glossary", gl], 1, "web addresses differ")
case("text: tag dropped", [P, "text", src, put("de-tag.txt", de.read_text().replace("<b>Rechnungen</b>", "Rechnungen")), "--glossary", gl], 1, "tags differ")
case("text: glossary term translated another way", [P, "text", src, put("de-gl.txt", de.read_text().replace("mstack Rechnung", "mstack Faktura")), "--glossary", gl], 1, "glossary: 'invoice'")
case("text: name translated", [P, "text", src, put("de-name.txt", de.read_text().replace("mstack Rechnung", "m-Stapel Rechnung")), "--glossary", gl], 1, "glossary: 'mstack'")
case("text: empty translation", [P, "text", src, put("empty.txt", "\n")], 1, "empty")
case("text: too long", [P, "text", src, de, "--max-ratio", "1.0"], 1, "times the source length")
s_en = put("en.json", {"cart": {"title": "Cart", "count": "{count} items", "pay": "Pay {amount} now"}, "help": "Mail help@example.com", "brand": "mstack"})
s_de = put("de.json", {"cart": {"title": "Warenkorb", "count": "{count} Artikel", "pay": "Jetzt {amount} zahlen"}, "help": "Mail an help@example.com", "brand": "mstack"})
case("strings: complete file", [P, "strings", s_en, s_de], 0, "identical to the source")
case("strings: a key missing and one empty", [P, "strings", s_en, put("de-miss.json", {"cart": {"title": "", "count": "{count} Artikel"}, "help": "Mail an help@example.com", "brand": "mstack"})], 1, "cart.pay: no translation")
case("strings: placeholder lost in one key", [P, "strings", s_en, put("de-lost.json", {"cart": {"title": "Warenkorb", "count": "Artikel", "pay": "Jetzt {amount} zahlen"}, "help": "Mail an help@example.com", "brand": "mstack"})], 1, "cart.count: placeholders differ")
case("strings: interface length limit", [P, "strings", s_en, s_de, "--limits", put("limits.json", {"cart.title": 6})], 1, "cart.title: 9 characters, limit 6")
case("strings: source file is not JSON", [P, "strings", src, s_de], 2, "blocked")
print(f"writing cases: {total} run, {wrong} wrong")
sys.exit(1 if wrong else 0)
