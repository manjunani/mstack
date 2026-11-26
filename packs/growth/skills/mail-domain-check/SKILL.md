---
name: mail-domain-check
description: Checks the SPF, DKIM and DMARC records of one sending domain from record text or the system resolver: syntax, a too-permissive SPF, a DMARC policy of none, weak or empty DKIM keys, and missing records. Use when newsletters or sign-up emails land in spam, before sending from a new domain, or someone asks if email authentication is set up. Not for status and certificates of a website (use site-check).
license: MIT
metadata:
  pack: growth
  version: 0.3.1
  needs: python3; dig or nslookup only for a live lookup
---

# Mail domain check

Produces one line each for SPF, DMARC and every DKIM selector: valid, faulty with the reason, or not checked.

## Done when

- The user named the real sending domain (and the DKIM selector, if known).
- `scripts/maildomain.py` ran on pasted record text or a live lookup of that domain and ended with a `RESULT` line.
- The reply says whether the records came from DNS or from pasted text, and that a real message was not tested.

End in exactly one state: **pass**, **fail** (a record missing or faulty, `+all`, DMARC `p=none` outside a stated monitoring period, a short or empty DKIM key), **not verified** (no DKIM selector), or **blocked** (no domain, no records, no resolver for a lookup).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The sending domain | the user named it | ask; never guess from a website address |
| dig or nslookup (lookup only) | `command -v dig nslookup` | ask the user to paste the records from the DNS panel instead |

## Steps

The script is `scripts/maildomain.py` in this skill's folder; in Claude Code `"${CLAUDE_SKILL_DIR}/scripts/maildomain.py"`.

1. **Find the selector.** It is the `s=` value in the DKIM-Signature header of a message the domain sent. Ask the user for one.
2. **Run** with pasted records or a lookup of that one domain:
   ```
   python3 scripts/maildomain.py mail.their-site.tld --records .mstack/growth/records.txt --selector s1
   python3 scripts/maildomain.py mail.their-site.tld --lookup --selector s1
   ```
   Add `--monitoring-ok` only when the user says `p=none` is a deliberate first step with reports being read.
3. **Read the output.** Lookups inside `include:` records are not counted; the report lists that as not checked.
4. **Report.** End state first, then each record's line, then not checked (live zone if text was pasted, a real message's Authentication-Results, alignment).

## Rules

- Look up only the domain the user named. No scanning of other domains.
- Never suggest `+all`, `?all` or removing DMARC to make mail "go through".
- Record changes are made by the user in their DNS panel; this skill does not touch DNS.
- No bulk or unsolicited sending is planned or helped here; this checks authentication only.
- Numbers come from `references/limits.json`, dated and unverified.

## Not for

- A website's certificate, redirects and headers → use `site-check`.
- The text of an email → use `claim-check` or `copyedit`.

## Level

- beginner: explain in one sentence each what SPF, DKIM and DMARC prove to a receiving server.
- standard: as written.
- expert: three result lines and the end state. Every check still runs.
