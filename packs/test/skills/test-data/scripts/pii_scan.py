#!/usr/bin/env python3
"""Scan fixture, seed and factory files for values that could belong to a real person.

  pii_scan.py                      scan the folders and files that look like test data
  pii_scan.py db/seeds tests/fixtures/users.json
  pii_scan.py --strict             also fail on emails at domains that are not reserved for examples

With no paths it looks in folders named fixtures, seeds, factories, testdata, mocks and similar,
and at files named seed*, *fixture*, *factory*.

It reports:
  email     an address at a public mail provider (gmail.com, outlook.com, ...): a real mailbox may exist.
            An address at any other domain that is not reserved (example.com, *.test, ...) is a warning.
  phone     a number in international or North American form, or any long number on a line that
            mentions phone, mobile or tel, unless it is in a range set aside for fiction or plainly made up
  card      13 to 19 digits that start like a payment card and pass the Luhn check, unless it is a
            test number published by a payment provider
  ssn       a United States social security number that could have been issued
  aadhaar   12 digits that pass the Verhoeff check used by Indian Aadhaar numbers
  pan       the shape of an Indian PAN (shape only: there is no checksum)
  nino      the shape of a United Kingdom National Insurance number (shape only)

Values are printed masked. A value the user has confirmed is made up can be listed, one per line,
in .mstack/test-data/allow.txt; allowed values are counted in the output, never hidden silently.
The reserved ranges and test numbers come from references/safe-values.json, with their source and date.

Exit codes: 0 = pass: files were scanned and nothing was found
            1 = fail: at least one finding (or a warning, with --strict)
            2 = not verified: no file to scan, or the reference file is missing
"""
import argparse
import json
import os
import pathlib
import re
import sys

REFERENCE = pathlib.Path(__file__).resolve().parent.parent / "references" / "safe-values.json"
DATA_DIRS = {"fixtures", "fixture", "__fixtures__", "seeds", "seed", "seeders", "factories", "factory", "testdata", "test_data",
             "test-data", "mocks", "__mocks__", "stubs", "samples", "cassettes", "sampledata", "sample_data", "demo_data"}
DATA_NAME = re.compile(r"(^seed|fixture|factory|factories|^mock_?data|sample_?data|test_?data)", re.I)
SKIP_DIRS = {".git", "node_modules", "dist", "build", "target", ".venv", "venv", "__pycache__", ".mstack", "vendor", ".next", "coverage", ".tox"}
MAX_BYTES = 5_000_000

EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
CARD = re.compile(r"(?<![\d.+-])(?:\d[ -]?){12,18}\d(?![\d.])")
SSN = re.compile(r"(?<![\d-])(\d{3})-(\d{2})-(\d{4})(?![\d-])")
AADHAAR = re.compile(r"(?<![\d-])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![\d-])")
PAN = re.compile(r"\b[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]\b")
NINO = re.compile(r"\b(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z] ?\d{2} ?\d{2} ?\d{2} ?[A-D]\b")
PHONE_INTL = re.compile(r"(?<![\w+])\+\d[\d ().-]{6,20}\d(?!\d)")
PHONE_NANP = re.compile(r"(?<![\d-])\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\d-])")
PHONE_WORD = re.compile(r"phone|mobile|\btel\b|telephone|\bcell\b|msisdn|whatsapp|\bfax\b|contact_?(no|num)", re.I)
PHONE_LOOSE = re.compile(r"(?<![\w.-])\d[\d ()-]{8,17}\d(?![\w.-])")

VERHOEFF_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
              [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
              [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
VERHOEFF_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
              [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def luhn(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def card_digits(digits):
    """The card number inside a run of digits, or None. A run may carry an expiry or a code after the
    number, so when the whole run fails the check, its first 16 and first 15 digits are tried as well."""
    if not digits or digits[0] not in "23456":
        return None
    for length in dict.fromkeys((len(digits), 16, 15)):
        if 13 <= length <= 19 and length <= len(digits) and luhn(digits[:length]):
            return digits[:length]
    return None


def verhoeff(digits):
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = VERHOEFF_D[c][VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def made_up(digits):
    """Plainly invented numbers: one or two distinct digits, or a run that counts up or down."""
    if len(set(digits)) <= 2:
        return True
    return any(digits[-n:] in run for n in (9, 10) if len(digits) >= n for run in ("01234567890123456789", "98765432109876543210"))


def mask(text):
    text = text.strip()
    if "@" in text:
        local, _, domain = text.partition("@")
        return f"{local[:1]}***@{domain}"
    return text[:2] + "*" * max(len(text) - 4, 3) + text[-2:]


def load_reference():
    data = json.loads(REFERENCE.read_text(encoding="utf-8"))
    unverified = sorted(k for k, v in data.items() if isinstance(v, dict) and not v.get("verified"))
    dates = sorted({v.get("checked", "?") for v in data.values() if isinstance(v, dict)})
    return data, unverified, dates


def find_files(root, paths):
    found, skipped = [], []

    def consider(path, picked):
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size > MAX_BYTES:
            skipped.append(f"{path}: larger than {MAX_BYTES // 1_000_000} MB")
        elif picked or DATA_NAME.search(path.name) or (set(p.lower() for p in path.parts[len(root.parts):-1]) & DATA_DIRS):
            found.append(path)

    targets = [(root / p) if not pathlib.Path(p).is_absolute() else pathlib.Path(p) for p in paths] or [root]
    for target in targets:
        if target.is_file():
            consider(target, True)
        elif target.is_dir():
            for folder, dirs, files in os.walk(target):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for name in sorted(files):
                    consider(pathlib.Path(folder) / name, bool(paths))
        else:
            skipped.append(f"{target}: not found")
    return found, skipped


def scan_line(line, ref):
    """Return [(kind, value, level)] for one line. level is 'finding' or 'warning'."""
    out, taken = [], []

    def free(match):
        return not any(match.start() < end and start < match.end() for start, end in taken)

    def take(match):
        taken.append((match.start(), match.end()))

    for m in EMAIL.finditer(line):
        take(m)
        domain = m.group(2).lower().rstrip(".")
        tld = domain.rsplit(".", 1)[-1]
        reserved = ref["reserved_email_domains"]["value"]
        if tld in ref["reserved_email_tlds"]["value"] or any(domain == d or domain.endswith("." + d) for d in reserved):
            continue
        public = ref["public_mail_domains"]["value"]
        if any(domain == d or domain.endswith("." + d) for d in public):
            out.append(("email", m.group(0), "finding"))
        elif re.search(r"[a-z]", tld):
            out.append(("email-domain", m.group(0), "warning"))
    for m in SSN.finditer(line):
        if not free(m):
            continue
        take(m)
        rule = ref["ssn_never_issued"]["value"]
        area, group, serial = m.groups()
        never = (area in rule["areas"] or any(lo <= int(area) <= hi for lo, hi in rule["area_ranges"])
                 or group == rule["group"] or serial == rule["serial"])
        lo, hi = rule["advertising_range"]
        if never or m.group(0) in rule["advertising"] or lo <= m.group(0) <= hi or made_up(area + group + serial):
            continue
        out.append(("ssn", m.group(0), "finding"))
    for m in CARD.finditer(line):
        digits = card_digits(re.sub(r"\D", "", m.group(0)))
        if not free(m) or digits is None:
            continue
        take(m)
        if digits in ref["published_test_cards"]["value"] or len(set(digits)) <= 2:
            continue
        out.append(("card", m.group(0), "finding"))
    for m in AADHAAR.finditer(line):
        digits = re.sub(r"\D", "", m.group(0))
        if free(m) and verhoeff(digits) and not made_up(digits):
            take(m)
            out.append(("aadhaar", m.group(0), "finding"))
    for kind, pattern in (("pan", PAN), ("nino", NINO)):
        for m in pattern.finditer(line):
            if free(m):
                take(m)
                out.append((kind, m.group(0), "finding"))
    patterns = [PHONE_INTL, PHONE_NANP] + ([PHONE_LOOSE] if PHONE_WORD.search(line) else [])
    for pattern in patterns:
        for m in pattern.finditer(line):
            digits = re.sub(r"\D", "", m.group(0))
            if not free(m) or not 8 <= len(digits) <= 15:
                continue
            take(m)
            national = digits[-10:]
            lo, hi = ref["nanp_fictional_line_range"]["value"]
            fictional = (national[3:6] == "555" and lo <= int(national[6:]) <= hi and len(digits) in (10, 11))
            if fictional or made_up(digits) or any(digits.startswith(p) for p in ref["fictional_phone_prefixes"]["value"]):
                continue
            out.append(("phone", m.group(0), "finding"))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="files or folders to scan (default: test data folders found under --root)")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    parser.add_argument("--strict", action="store_true", help="count emails at non-reserved domains as findings, not warnings")
    args = parser.parse_args()
    root = args.root.resolve()

    try:
        ref, unverified, dates = load_reference()
    except (OSError, ValueError) as exc:
        print(f"RESULT not verified: cannot read {REFERENCE}: {exc}")
        return 2
    files, skipped = find_files(root, args.paths)
    allow_file = root / ".mstack" / "test-data" / "allow.txt"
    allow = set()
    if allow_file.exists():
        allow = {line.strip() for line in allow_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}

    findings, warnings, allowed, scanned, binary = [], [], 0, 0, 0
    for path in files:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            skipped.append(f"{path}: {exc}")
            continue
        if b"\0" in raw[:4096]:
            binary += 1
            continue
        scanned += 1
        shown = path.relative_to(root) if path.is_relative_to(root) else path
        for number, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
            if len(line) > 20000:
                line = line[:20000]
            for kind, value, level in scan_line(line, ref):
                if value.strip() in allow:
                    allowed += 1
                    continue
                (findings if level == "finding" or args.strict else warnings).append((str(shown), number, kind, mask(value)))

    for name, number, kind, value in findings:
        print(f"  FOUND {kind:13} {name}:{number}: {value}")
    for name, number, kind, value in warnings:
        print(f"  warn  {kind:13} {name}:{number}: {value}   (domain is not reserved for examples; use example.com or a .test name)")
    for line in skipped:
        print(f"  skipped: {line}")
    counts = {}
    for _, _, kind, _ in findings:
        counts[kind] = counts.get(kind, 0) + 1
    print(f"scanned {scanned} text file(s)" + (f", passed over {binary} binary file(s)" if binary else "")
          + f"; findings: {len(findings)}" + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + ")" if counts else "")
          + f"; warnings: {len(warnings)}; allowed by allow.txt: {allowed}")
    if unverified:
        print(f"note: {len(unverified)} reference list(s) in references/safe-values.json are marked unverified "
              f"(written from memory, checked {', '.join(dates)}); a value passed as 'reserved' or 'test number' rests on them")
    if not scanned:
        hint = "the paths given hold no text file" if args.paths else "no fixture, seed or factory file found; pass the paths"
        print(f"RESULT not verified: nothing was scanned: {hint}")
        return 2
    if findings:
        print(f"RESULT fail: {len(findings)} value(s) could belong to a real person; replace them with reserved or generated ones")
        return 1
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
