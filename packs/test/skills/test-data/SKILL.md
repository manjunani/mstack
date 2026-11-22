---
name: test-data
description: Builds factories and seed data that hold no real personal data and give the same result on every run, proven by a scanner and a two-run comparison. Use when the user wants test data, fixtures, a seed script, factories or fake users and orders, or asks whether the fixtures contain real customer data. Not for deciding which cases to test (use test-cases) or for scanning commits for secrets and keys (use commit).
license: MIT
metadata:
  pack: test
  version: 0.1.0
  needs: python3, the project's seed or factory command
---

# Test data

Produces fixture, factory or seed files that pass a personal-data scan and a repeat check, with the saved runs under `.mstack/test-data/`.

## Done when

- `pii_scan.py` scanned the fixture, seed and factory files and found nothing; every warning was shown to the user.
- `repeat_check.py` ran each factory twice with one seed and got the same output.
- `repeat_check.py` ran each seed twice and the data was the same after the second run as after the first.
- No value was added to the allow list without the user confirming that exact value.

End in exactly one state: **pass**, **fail** (a finding is left, or two runs differ), **not verified** (say which file was not scanned or which command could not run), or **blocked** (say what the user has to decide or provide).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The command that builds or loads the data | Run it once against a local or test database | ask the user; the repeat check for it is not verified |
| A local or test database for seeds | Read the connection setting the seed uses | end as blocked; never run a seed against a shared or live database |

## Steps

The scripts are `scripts/pii_scan.py` and `scripts/repeat_check.py` in this skill's folder. In Claude Code the folder is `"${CLAUDE_SKILL_DIR}"`.

1. **Scan what exists** before changing anything.
   ```
   python3 scripts/pii_scan.py                    # test data folders it finds
   python3 scripts/pii_scan.py db/seeds tests/fixtures/users.json
   ```
   Exit 2 with "nothing was scanned" means it found no test data files: pass the paths. Values are printed masked.
2. **Write or repair the data.**
   - One factory per entity: sensible defaults, any field can be overridden, and every random choice comes from one seed that is passed in.
   - Seeds insert by a fixed key and update when the row exists, so a second run changes nothing.
   - Relations are built by the factory that owns them, to a stated depth.
   - Use only values that cannot belong to anyone:

     | Field | Use |
     |---|---|
     | Email | `name@example.com`, or a domain ending in `.test` |
     | Phone | a number from a range set aside for fiction; the scanner accepts those in its reference file |
     | Payment card | the test numbers your payment provider publishes |
     | Name, address | invented ones; not copied from a customer, a colleague or a public figure |
     | National id | a number the issuer never assigns, or one that fails the checksum |
3. **Replace every finding.** For each `FOUND` line, change the value in the file. Do not edit the scanner's lists to make a finding go away.
4. **Scan again** until it passes. A `warn` line (an email at a domain that is not reserved) goes to the user: it passes only if they say the domain is theirs to use.
5. **Check that a factory repeats.**
   ```
   python3 scripts/repeat_check.py --label users -- <factory command with a fixed seed>
   ```
   If a line is meant to differ (a creation time), leave it out with `--ignore "<regex>"`; the report says how many lines were left out.
6. **Check that a seed can run twice.** First read which database the seed writes to. Then:
   ```
   python3 scripts/repeat_check.py --no-stdout --state "<read-only command that prints the data>" -- <seed command>
   ```
   The state command is a dump or a sorted select. "Failed on run 2" or added rows mean the seed is not safe to repeat. A seed that does not fit the schema fails on run 1 and ends as not verified.
7. **Report.** End state first. Then files scanned and findings fixed, warnings and what the user said, each repeat check with its saved runs, and anything not verified.

## Rules

- Never copy rows from production or from a customer export into test data, even "cleaned by hand". If the user asks for that, end as blocked and offer generated data.
- `.mstack/test-data/allow.txt` holds values the user confirmed as invented, one per line. Add a value only after the user confirmed that value. The scanner counts allowed values in its output.
- The scanner's reference lists are marked unverified until someone checks the sources. Repeat that note in the report.
- A seed is run only against a local or test database. If the target is unclear, do not run it.
- An empty scan is not a clean scan: "nothing was scanned" is not verified.
- Shape-only matches (PAN, NINO) can be wrong. Show them; the user decides, and the decision goes into the allow list.

## Not for

- Choosing which inputs and combinations to test → use `test-cases`.
- Finding API keys or passwords in staged changes → use `commit`; for a security pass use `secure`.
- Checking a running API against its contract → use `api-check`.
- Removing old fixture folders → use `safe-delete`.

If a named skill is not installed, say so and leave that part to the user.

## Level

- beginner: explain why a real-looking email or card number in a fixture is a risk, and what "safe to run twice" means.
- standard: as written.
- expert: the reply is the end state, the findings fixed and the repeat results. Both checks still run.
