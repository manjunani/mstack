#!/usr/bin/env python3
"""Check the SPF, DKIM and DMARC records of one sending domain.

  maildomain.py <domain> --records <file> [--selector NAME ...] [--monitoring-ok] [--out report.json]
        check record text the user pasted into a file
  maildomain.py <domain> --lookup [--selector NAME ...]
        read the records with the system resolver command (dig, or nslookup), for that domain only

The records file holds TXT records, one per line, in any of these forms:
  your-domain.tld.  300 IN TXT "v=spf1 include:_spf.mailer.tld ~all"      (as dig prints them)
  _dmarc TXT "v=DMARC1; p=reject; rua=mailto:reports@your-domain.tld"     (name, TXT, value)
  v=DKIM1; k=rsa; p=MIIBIjANBg...                                         (value only; the name is inferred)
Lines starting with # or ; are ignored. Several quoted strings on one line are joined, as DNS does.

Checks:
  SPF    one record at the domain; every term is valid; not "+all"; no huge ip4 range; lookups within the limit
  DMARC  one record at _dmarc.<domain>; tags valid; p= present; p=none fails unless --monitoring-ok
  DKIM   for each --selector, a record at <selector>._domainkey.<domain> with a usable public key
Without a selector a DKIM record cannot be found, so DKIM is listed as not checked and the result is not verified.
Numbers come from references/limits.json, a dated file whose values are unverified.

Exit codes: 0 = pass, 1 = fail, 2 = not verified (DKIM not checked) or blocked (no domain, no records, no resolver).
"""
import argparse
import base64
import binascii
import datetime
import ipaddress
import json
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$")
PLACEHOLDERS = {"example.com", "example.org", "example.net", "yourdomain.com", "domain.com"}
LOOKUP_TERMS = ("include", "a", "mx", "ptr", "exists", "redirect")
POLICIES = ("none", "quarantine", "reject")


class Report:
    """Three lists and one end state. Findings are either failures (block) or warnings (do not)."""

    def __init__(self, title):
        self.title, self.failures, self.warnings, self.fine, self.skipped, self.open, self.notes = title, [], [], [], [], [], []

    def fail(self, text):
        self.failures.append(text)

    def warn(self, text):
        self.warnings.append(text)

    def ok(self, text):
        self.fine.append(text)

    def skip(self, text, blocks=False):
        self.skipped.append(text)
        if blocks:
            self.open.append(text)

    def note(self, text):
        self.notes.append(text)

    def finish(self, out=None):
        if self.failures:
            code, line = 1, f"RESULT fail: {self.failures[0]}" + (f" (and {len(self.failures) - 1} more)" if len(self.failures) > 1 else "")
        elif self.open:
            code, line = 2, f"RESULT not verified: {self.open[0]}" + (f" (and {len(self.open) - 1} more)" if len(self.open) > 1 else "")
        else:
            code, line = 0, "RESULT pass"
        print(f"== {self.title}")
        for text in self.notes:
            print(f"note  {text}")
        print(f"FINDINGS ({len(self.failures)} fail, {len(self.warnings)} warn)")
        for text in self.failures:
            print(f"  FAIL  {text}")
        for text in self.warnings:
            print(f"  warn  {text}")
        print(f"CHECKED AND FINE ({len(self.fine)})")
        for text in self.fine:
            print(f"  ok    {text}")
        print(f"NOT CHECKED ({len(self.skipped)})")
        for text in self.skipped:
            print(f"  --    {text}")
        if out:
            data = {"check": self.title, "made": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                    "result": line, "failures": self.failures, "warnings": self.warnings, "fine": self.fine,
                    "not_checked": self.skipped, "notes": self.notes}
            pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
            with open(out, "x", encoding="utf-8") as handle:
                handle.write(json.dumps(data, indent=2) + "\n")
            print(f"report written to {out}")
        print(line)
        return code


def blocked(text):
    print(f"blocked: {text}")
    return 2


def full_name(name, domain):
    name = name.strip().rstrip(".").lower()
    if name in ("@", ""):
        return domain
    return name if name == domain or name.endswith("." + domain) else f"{name}.{domain}"


def guess_name(value, domain, selectors):
    low = value.lower().replace(" ", "")
    if low.startswith("v=spf1"):
        return domain
    if low.startswith("v=dmarc1"):
        return f"_dmarc.{domain}"
    if low.startswith("v=dkim1") or re.search(r"(^|;)p=", low):
        return f"{selectors[0] if selectors else 'unnamed-selector'}._domainkey.{domain}"
    return None


def parse_records(text, domain, selectors):
    """Return {name: [TXT value, ...]} from pasted record text."""
    records = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
        name = None
        if quoted:
            value = "".join(q.replace('\\"', '"') for q in quoted)
            head = line.split('"', 1)[0].split()
            if head and not head[0].lower().startswith("v="):
                name = head[0]
        else:
            match = re.match(r"^(\S+)\s+(?:\d+\s+)?(?:IN\s+)?TXT\s+(.+)$", line, re.I) or re.match(r"^([\w.@-]+)\s*[=:]\s*(v=.+)$", line, re.I)
            if match:
                name, value = match.group(1), match.group(2).strip()
            else:
                value = line
        if not value.strip():
            continue
        target = full_name(name, domain) if name else guess_name(value, domain, selectors)
        if target:
            records.setdefault(target, []).append(value.strip())
    return records


def lookup(name):
    """TXT values for one name from dig or nslookup. Returns (values, problem)."""
    dig, nslookup = shutil.which("dig"), shutil.which("nslookup")
    if dig:
        command = [dig, "+short", "+time=5", "+tries=1", "TXT", name]
    elif nslookup:
        command = [nslookup, "-type=TXT", name]
    else:
        return None, "neither dig nor nslookup is on this machine"
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{command[0]} did not finish: {exc}"
    values = []
    for line in done.stdout.splitlines():
        if not dig and "text =" not in line:
            continue
        quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
        if quoted:
            values.append("".join(quoted))
    if dig and done.returncode != 0:
        return None, f"dig ended with code {done.returncode}: {(done.stderr or done.stdout).strip()[:120]}"
    return values, None


def check_spf(domain, values, limits, report):
    found = [v for v in values if v.lower().startswith("v=spf1")]
    if not found:
        report.fail(f"SPF: no TXT record starting with v=spf1 at {domain}")
        return
    if len(found) > 1:
        report.fail(f"SPF: {len(found)} records at {domain}; receivers treat more than one as an error and SPF fails for all mail")
        return
    terms = found[0].split()[1:]
    problems, lookups, ending, after_all = 0, 0, None, False
    for term in terms:
        if after_all:
            report.warn(f"SPF: '{term}' comes after 'all' and is never read")
            continue
        if re.match(r"^[a-z][\w.-]*=", term, re.I):
            key, _, value = term.partition("=")
            if key.lower() == "redirect":
                lookups += 1
                ending = ending or "redirect"
                if not value:
                    report.fail("SPF: redirect= names no domain")
                    problems += 1
            elif key.lower() != "exp":
                report.warn(f"SPF: unknown modifier '{term}' (receivers ignore it)")
            continue
        qualifier = term[0] if term[0] in "+-~?" else "+"
        body = term[1:] if term[0] in "+-~?" else term
        name, sep, arg = body.partition(":")
        name_only, _, cidr = name.partition("/")
        kind = name_only.lower()
        if kind == "all" and not sep:
            after_all, ending = True, qualifier + "all"
            if qualifier == "+":
                report.fail("SPF: the record ends in '+all' (or a bare 'all'), which lets any server send as this domain")
                problems += 1
            elif qualifier == "?":
                report.warn("SPF: the record ends in '?all', which gives receivers no instruction for other servers")
        elif kind in ("include", "exists"):
            lookups += 1
            if not arg:
                report.fail(f"SPF: '{term}' names no domain")
                problems += 1
        elif kind in ("a", "mx", "ptr"):
            lookups += 1
            if kind == "ptr":
                report.warn("SPF: 'ptr' is slow and the SPF standard says not to use it")
        elif kind in ("ip4", "ip6"):
            try:
                network = ipaddress.ip_network(arg, strict=False)
                if network.version != int(kind[2]):
                    raise ValueError("wrong address family")
            except ValueError:
                report.fail(f"SPF: '{term}' is not a valid {kind} address or range")
                problems += 1
                continue
            if kind == "ip4" and network.prefixlen < limits["spf_ip4_prefix_fail"]["value"]:
                report.fail(f"SPF: '{term}' covers {network.num_addresses} addresses, far too many servers allowed to send")
                problems += 1
            elif kind == "ip4" and network.prefixlen < limits["spf_ip4_prefix_warn"]["value"]:
                report.warn(f"SPF: '{term}' covers {network.num_addresses} addresses; confirm the whole range is yours")
        else:
            report.fail(f"SPF: '{term}' is not a term SPF knows")
            problems += 1
    most = limits["spf_max_lookups"]["value"]
    if lookups > most:
        report.fail(f"SPF: {lookups} terms cause a DNS lookup, over the limit of {most}; receivers stop and SPF fails")
        problems += 1
    if ending is None:
        report.warn("SPF: no 'all' and no redirect at the end, so mail from other servers gets a neutral result")
    if not problems:
        report.ok(f"SPF: one record, {len(terms)} valid terms, {lookups} of {most} lookups used by this record, ends in {ending or 'nothing'}")
    if lookups:
        report.skip("SPF: lookups made inside the include: and redirect= records (they count toward the same limit)")


def tags_of(value):
    """Return ([(tag, value)], [malformed parts])."""
    pairs, broken = [], []
    for part in value.split(";"):
        part = part.strip()
        if not part:
            continue
        key, sep, inner = part.partition("=")
        if sep and key.strip():
            pairs.append((key.strip().lower(), inner.strip()))
        else:
            broken.append(part)
    return pairs, broken


def check_dmarc(domain, values, report, monitoring_ok):
    name = f"_dmarc.{domain}"
    found = [v for v in values if v.lower().replace(" ", "").startswith("v=dmarc1")]
    if not found:
        report.fail(f"DMARC: no TXT record starting with v=DMARC1 at {name}")
        return
    if len(found) > 1:
        report.fail(f"DMARC: {len(found)} records at {name}; receivers ignore all of them")
        return
    pairs, broken = tags_of(found[0])
    tags, problems = dict(pairs), 0
    for part in broken:
        report.fail(f"DMARC: '{part}' is not a tag=value pair")
        problems += 1
    if pairs[0][0] != "v":
        report.fail("DMARC: the record has to start with v=DMARC1")
        problems += 1
    policy = tags.get("p", "").lower()
    if "p" not in tags:
        report.fail("DMARC: no p= tag, so there is no policy")
        problems += 1
    elif policy not in POLICIES:
        report.fail(f"DMARC: p={tags['p']} is not one of {', '.join(POLICIES)}")
        problems += 1
    elif policy == "none":
        text = "DMARC: p=none tells receivers to deliver mail that fails the checks, so the domain is not protected"
        if monitoring_ok:
            report.warn(text + " (accepted for now with --monitoring-ok)")
        else:
            report.fail(text + "; pass --monitoring-ok if this is a stated monitoring period")
            problems += 1
    if len(pairs) > 1 and "p" in tags and pairs[1][0] != "p":
        report.warn("DMARC: p= should be the second tag, right after v=")
    if "sp" in tags and tags["sp"].lower() not in POLICIES:
        report.fail(f"DMARC: sp={tags['sp']} is not one of {', '.join(POLICIES)}")
        problems += 1
    elif tags.get("sp", "").lower() == "none" and policy in ("quarantine", "reject"):
        report.warn("DMARC: sp=none leaves subdomains unprotected while the main domain has a policy")
    if "pct" in tags:
        if not tags["pct"].isdigit() or not 0 <= int(tags["pct"]) <= 100:
            report.fail(f"DMARC: pct={tags['pct']} is not a number from 0 to 100")
            problems += 1
        elif int(tags["pct"]) < 100:
            report.warn(f"DMARC: pct={tags['pct']} applies the policy to only part of the failing mail")
    for key in ("rua", "ruf"):
        for address in filter(None, (a.strip() for a in tags.get(key, "").split(","))):
            if not re.match(r"^mailto:[^@\s]+@[^@\s!]+(![0-9]+[kmgt]?)?$", address, re.I):
                report.fail(f"DMARC: {key} address '{address}' is not in the form mailto:name@domain")
                problems += 1
    if "rua" not in tags:
        report.warn("DMARC: no rua= address, so no reports arrive and failures stay invisible")
    for key in ("adkim", "aspf"):
        if key in tags and tags[key].lower() not in ("r", "s"):
            report.fail(f"DMARC: {key}={tags[key]} has to be r or s")
            problems += 1
    known = {"v", "p", "sp", "pct", "rua", "ruf", "adkim", "aspf", "fo", "rf", "ri", "np", "psd", "t"}
    extra = [k for k, _ in pairs if k not in known]
    if extra:
        report.warn(f"DMARC: unknown tags (receivers ignore them): {', '.join(extra)}")
    if not problems:
        report.ok(f"DMARC: one record at {name}, policy p={policy}" + (f", reports to {tags['rua']}" if "rua" in tags else ""))


def rsa_bits(der):
    """Bit length of the RSA modulus in a DER public key, or None when it cannot be read."""
    def read(pos):
        tag, length = der[pos], der[pos + 1]
        pos += 2
        if length & 0x80:
            size = length & 0x7F
            length = int.from_bytes(der[pos:pos + size], "big")
            pos += size
        return tag, length, pos

    try:
        _, _, pos = read(0)
        tag, length, inner = read(pos)
        if tag != 0x02:
            _, _, pos = read(inner + length)
            _, _, pos = read(pos + 1)
            tag, length, inner = read(pos)
        if tag != 0x02:
            return None
        return int.from_bytes(der[inner:inner + length], "big").bit_length()
    except (IndexError, ValueError):
        return None


def check_dkim(name, values, limits, report):
    found = [v for v in values if re.search(r"(^|;)\s*p\s*=", v) or v.lower().replace(" ", "").startswith("v=dkim1")]
    if not found:
        report.fail(f"DKIM: no key record at {name}")
        return
    if len(found) > 1:
        report.fail(f"DKIM: {len(found)} key records at {name}; there has to be one")
        return
    pairs, broken = tags_of(found[0])
    tags, problems = dict(pairs), 0
    for part in broken:
        report.fail(f"DKIM: '{part[:40]}' is not a tag=value pair")
        problems += 1
    if "v" in tags and (tags["v"] != "DKIM1" or pairs[0][0] != "v"):
        report.fail("DKIM: v= has to be DKIM1 and come first")
        problems += 1
    kind = tags.get("k", "rsa").lower()
    key = re.sub(r"\s+", "", tags.get("p", ""))
    if "p" not in tags:
        report.fail(f"DKIM: the record at {name} has no p= (public key)")
        return
    if not key:
        report.fail(f"DKIM: p= is empty at {name}, which means the key was withdrawn; mail signed with it fails")
        return
    try:
        der = base64.b64decode(key, validate=True)
    except (binascii.Error, ValueError):
        report.fail(f"DKIM: p= at {name} is not valid base64 (often a record cut short when it was pasted)")
        return
    if kind == "rsa":
        bits = rsa_bits(der)
        if bits is None:
            report.skip(f"DKIM: the RSA key at {name} decodes but its length could not be read", blocks=True)
        elif bits < limits["dkim_min_rsa_bits"]["value"]:
            report.fail(f"DKIM: the RSA key at {name} is {bits} bits, under the minimum of {limits['dkim_min_rsa_bits']['value']}")
            problems += 1
        elif bits < limits["dkim_recommended_rsa_bits"]["value"]:
            report.warn(f"DKIM: the RSA key at {name} is {bits} bits; {limits['dkim_recommended_rsa_bits']['value']} is recommended")
    elif kind == "ed25519":
        if len(der) != 32:
            report.fail(f"DKIM: an ed25519 key is 32 bytes; the one at {name} is {len(der)}")
            problems += 1
    else:
        report.fail(f"DKIM: k={kind} is not rsa or ed25519")
        problems += 1
    if "y" in tags.get("t", "").lower().split(":"):
        report.warn(f"DKIM: t=y at {name} marks the key as a test; receivers may ignore the signature")
    if not problems:
        size = f"{rsa_bits(der)} bit rsa" if kind == "rsa" and rsa_bits(der) else kind
        report.ok(f"DKIM: one key record at {name} ({size})")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("domain", help="the domain mail is sent from, for example mail.your-site.tld")
    parser.add_argument("--records", type=pathlib.Path, help="a file holding the TXT records as text")
    parser.add_argument("--lookup", action="store_true", help="read the records with dig or nslookup, for this domain only")
    parser.add_argument("--selector", action="append", default=[], help="a DKIM selector to check (repeatable)")
    parser.add_argument("--monitoring-ok", action="store_true", help="treat a DMARC policy of none as a warning, not a failure")
    parser.add_argument("--limits", type=pathlib.Path, default=HERE.parent / "references" / "limits.json",
                        help="dated limits (default: references/limits.json)")
    parser.add_argument("--out", help="also write the three lists as JSON to this new file")
    args = parser.parse_args()

    domain = args.domain.strip().rstrip(".").lower()
    if not DOMAIN.match(domain):
        return blocked(f"'{args.domain}' is not a domain name; give the real sending domain, it is never guessed")
    if args.out and pathlib.Path(args.out).exists():
        return blocked(f"{args.out} exists; reports are never overwritten, name a new file")
    if bool(args.records) == bool(args.lookup):
        return blocked("give exactly one of --records <file> (pasted record text) or --lookup (ask DNS for this domain)")
    for selector in args.selector:
        if not re.match(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$", selector, re.I):
            return blocked(f"'{selector}' is not a DKIM selector name")
    try:
        limits = json.loads(args.limits.read_text(encoding="utf-8"))
        loose = [k for k, e in limits.items() if isinstance(e, dict) and not e.get("verified")]
    except (OSError, ValueError) as exc:
        return blocked(f"limits file {args.limits} cannot be read: {exc}")

    selectors = [s.lower() for s in args.selector]
    wanted = [domain, f"_dmarc.{domain}"] + [f"{s}._domainkey.{domain}" for s in selectors]
    if args.lookup:
        if domain in PLACEHOLDERS or domain.endswith((".example", ".invalid", ".test", ".localhost")):
            return blocked(f"'{domain}' is a placeholder or reserved name; give the real sending domain")
        records = {}
        for name in wanted:
            values, problem = lookup(name)
            if values is None:
                return blocked(f"{problem}; paste the records into a file and use --records")
            records[name] = values
        origin = "read from DNS just now"
    else:
        if not args.records.is_file():
            return blocked(f"{args.records} is not a file")
        text = args.records.read_text(encoding="utf-8", errors="replace")
        records = parse_records(text, domain, selectors)
        if not records:
            return blocked(f"{args.records} holds no TXT record this script can read; see --help for the accepted forms")
        origin = f"taken from {args.records}"

    report = Report(f"mail-domain-check {domain} (records {origin})")
    if loose:
        report.note(f"{len(loose)} numbers in {args.limits.name} are unverified (written from memory): {', '.join(loose)}")
    check_spf(domain, records.get(domain, []), limits, report)
    check_dmarc(domain, records.get(f"_dmarc.{domain}", []), report, args.monitoring_ok)
    keys = {name for name in records if name.endswith(f"._domainkey.{domain}")} | set(wanted[2:])
    if not keys:
        report.skip("DKIM: no selector was named and no key record was given; a key can only be found by its selector "
                    "(the s= tag in the DKIM-Signature header of a sent message)", blocks=True)
    for name in sorted(keys):
        check_dkim(name, records.get(name, []), limits, report)
    elsewhere = sorted(name for name in records if name not in wanted and name not in keys and records[name])
    if elsewhere:
        report.note(f"records for other names were given and not checked: {', '.join(elsewhere)}")
    if not args.lookup:
        report.skip("whether DNS serves these records right now: the text given was checked, not the live zone")
    report.skip("whether a real message passes: send one and read its Authentication-Results header")
    report.skip("alignment between the From address and the domains that SPF and DKIM vouch for")
    return report.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
