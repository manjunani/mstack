# mstack-ai: what was tested

Date: 2026-11-22. Python 3.14 on macOS. No model, API or network was called by any script or test.

## How to repeat

Each skill has one script test in `tests/scripts/`. It writes its own input files into a new, dated run
folder and checks each case's exit code and printed lines:

```
python3 packs/ai/tests/scripts/<skill>_cases.py .testrun/ai-<skill>
```

`casekit.py` is the shared runner. `fixtures/fake_mcp_server.py` is the fake stdio server for mcp-check.
Each file exits 0 when every case matched.

| Skill | Script | Cases run | Wrong |
|---|---|---|---|
| eval-gate | `gate.py` | 25 | 0 |
| judge-check | `agree.py` | 15 | 0 |
| mcp-check | `probe.py` | 34 | 0 |
| trace-triage | `triage.py` | 16 | 0 |
| tool-lint | `lint.py` | 15 | 0 |
| rag-check | `score.py` | 24 | 0 |
| spend-check | `spend.py` | 18 | 0 |
| injection-test | `probes.py` | 16 | 0 |

`python3 tools/validate.py --strict`: all eight `ai/` lines are `ok`, with no collision line.
Trigger, silence and benefit tests (`claude plugin eval`) were NOT run: they cost usage and the builder
was told not to run them. `tests/results.json` does not exist yet, so every skill shows as "not tested".

## Per skill

**eval-gate.** Tested: identical runs, a real drop, an improvement, a deleted failing case (fails),
the same case retired by flag, two trials per case, four cases, a small mixed change (not verified, with
the number of cases needed), one lost trial with and without `--critical` and `--max-drop`, score rows
with two pass scores, malformed rows, a trial listed twice, an empty file, save/replace of the baseline,
that a refused save writes nothing and that the input file is not changed. Not tested: very large files;
the interval uses a t table, so with few cases the "not verified" band is wide by design.

**judge-check.** Tested with hand-worked figures: agreement 0.875 and kappa 0.750; a grader that passes
everything (kappa 0); 90% agreement with kappa 0.26 (fails); three labels; too few examples, one label
only, a rare label; missing verdicts count as disagreement; mixed true/PASS/Fail spellings; two files
joined on id. Not tested: per-category floors (categories are printed, not judged).

**mcp-check.** Tested against the fake server in ten modes: good, bad schemas, wrong output schema,
duplicate names, crash at start, no answer (timeout), log lines on stdout, paged tools/list, an older
protocol revision, no tools capability. The server logs every tools/call it receives, and each case
checks the log: unnamed tools were never called, a tool not marked read-only was held back without
`--allow-write`, arguments that break the schema were not sent. Not tested: any real MCP server, HTTP
transport (not supported; the skill says so), servers that need login. The protocol revision in
`references/protocol.json` is unverified.

**trace-triage.** Tested: a clean run, a four-call loop, an unchanged retry after an error, a silent
"all done" after an error, an error handled with a changed call, content-block traces with usage
fields, session-file rows with an error found only in its text, an unreadable line, a run-error row,
polling with a new result, argument strings that differ only in order and spacing, JSON output.
Not tested: real Claude Code or Agent SDK session files (the shapes were written from the format
described in the script, not from a captured file); multi-agent traces.

**tool-lint.** Tested: clean tools in three shapes, duplicate and colliding names, near-copy and
generic names (and that `oauth2_login` is not called generic), missing/short/name-only/when-less
descriptions, untyped and nested parameters, bad required lists, missing or non-object schemas, empty
enum, arrays without items, overlapping descriptions at two thresholds, `--strict`, two files. Not
tested: whether the overlap figure matches what a model finds confusing. The name limits are unverified.

**rag-check.** Tested with hand-worked figures (hit@1 0.5, hit@3 0.75, hit@5 0.833, hit@10 0.917,
MRR 0.638): no floor and no baseline (not verified), floors above and below, judging at k=10,
save and compare, one lost and one found, a drop in hit rate, a drop in MRR alone, a removed question
(fails) and the same retired by flag, a question with no results row, too few questions, short lists,
ids inside the gold rows, a baseline from another question set (blocked). Not tested: graded relevance
(only one or more passages that hold the answer).

**spend-check.** Tested with a test price file and hand-worked costs (0.93 total, 0.465 per run):
budgets in money and tokens, per run, by tag, no budget, an unpriced model kept apart, an unverified
price, the shipped price file, cached tokens inside prompt_tokens, unread lines, negative counts, a
broken price file. The shipped `references/prices.json` holds placeholder models only, all
`"verified": false`; no real provider price is in this pack.

**injection-test.** Tested with transcripts written by hand: three clean runs, one run, a marker and a
forbidden tool call, the planted forwarding call, case-insensitive markers, a marker quoted in a
warning (QUOTED, not verified), longer words that contain a marker (not counted), probes that never
reached the agent, `--only`, plain text replies, writing the documents. Not tested: any real agent.
The QUOTED rule is a word list; it can misjudge a reply in either direction.

## Faults the tests caught and that were fixed

- eval-gate: an improvement with no case worse ended as "not verified"; it now passes.
- eval-gate: the first test expected one lost trial to pass; with 12 cases that cannot be told from
  chance, so the test was corrected to expect "not verified" and a second case checks `--max-drop`.
- mcp-check (and the other scripts): a `RESULT` line that quoted a multi-line answer broke over two
  lines, so the last line was no longer the result. Every script now folds the reason onto one line.
- tool-lint: two tools with one name were also reported as "descriptions are the same text" and twice
  as colliding; findings are now de-duplicated. The overlap test's hand count was wrong and was corrected.
- rag-check: a saved baseline from a different question set was silently compared; it is now blocked,
  and `--no-baseline` skips the comparison.
- rag-check: a stray walrus expression in the comparison loop was removed.

## Other notes

- `tools/validate.py --strict` reports failures in other packs; those are not part of this pack.
- core `skill-check` scan of `packs/ai`: 0 FAIL, 11 WARN (scripts start processes in mcp-check and the
  test runner; shebang lines read as paths outside the skill). Expected for this pack.
