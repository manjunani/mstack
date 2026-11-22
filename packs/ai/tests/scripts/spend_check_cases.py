"""Script test for spend-check: usage logs whose cost was worked out by hand, with a test price file.

Test prices (made up for this test, marked verified so the pass path can be reached): model "m-test"
costs 2 per million input, 10 per million output, 0.2 cache read, 2.5 cache write.
Row A: 100,000 in, 20,000 out, 400,000 cache read           -> 0.2 + 0.2 + 0.08       = 0.48
Row B: 50,000 in, 10,000 out, 0 cache read, 100,000 write    -> 0.1 + 0.1 + 0.25       = 0.45
Total 0.93 over two runs, so 0.465 per run.

Usage: spend_check_cases.py <folder>   (a new run folder is made inside it, for example .testrun/ai-spend-check)
"""
import argparse
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("spend-check cases", args.folder)
SPEND = casekit.SKILLS / "spend-check" / "scripts" / "spend.py"

t.json("prices.json", {"currency": "USD", "per_tokens": 1000000, "models": {
    "m-test": {"input": 2, "output": 10, "cache_read": 0.2, "cache_write": 2.5, "source": "made up for this test", "checked": "2026-11-22", "verified": True},
    "m-guess": {"input": 1, "output": 5, "source": "made up for this test", "checked": "2026-11-22", "verified": False}}})
A = {"model": "m-test", "input_tokens": 100000, "output_tokens": 20000, "cache_read_input_tokens": 400000, "tag": "summarise", "run": "r1"}
B = {"model": "m-test", "usage": {"input_tokens": 50000, "output_tokens": 10000, "cache_creation_input_tokens": 100000}, "tag": "classify", "run": "r2"}
t.jsonl("usage.jsonl", [A, B])
P = ["--prices", "prices.json"]
t.run("within a cost budget passes", SPEND, ["usage.jsonl", *P, "--budget", "1"], 0,
      contains=["total                     2      150,000       30,000      400,000      100,000       0.9300", "cache read share of input tokens: 61.5%"])
t.run("over a cost budget fails", SPEND, ["usage.jsonl", *P, "--budget", "0.9"], 1, contains=["is 0.9300 USD, over the budget of 0.9"])
t.run("per run is compared with the budget", SPEND, ["usage.jsonl", *P, "--budget", "0.47", "--per", "run"], 0, contains=["mean per run over 2 runs", "0.4650"])
t.run("per run over a tighter budget fails", SPEND, ["usage.jsonl", *P, "--budget", "0.46", "--per", "run"], 1)
t.run("a token budget", SPEND, ["usage.jsonl", *P, "--budget-tokens", "600000"], 1, contains=["680,000 tokens, over the budget of 600,000"])
t.run("grouped by tag", SPEND, ["usage.jsonl", *P, "--budget", "1", "--by", "tag"], 0, contains=["summarise", "0.4800", "classify", "0.4500"])
t.run("no budget is not verified", SPEND, ["usage.jsonl", *P], 2, contains=["no budget was given"])

t.jsonl("unpriced.jsonl", [A, {"model": "m-unknown", "input_tokens": 1000, "output_tokens": 1000}])
t.run("a model with no price is kept apart, not zero", SPEND, ["unpriced.jsonl", *P, "--budget", "1"], 2,
      contains=["UNKNOWN COST m-unknown", "unknown cost: 1 rows, 2,000 tokens", "the real cost is higher than 0.4800"])
t.run("over budget even without the unpriced rows still fails", SPEND, ["unpriced.jsonl", *P, "--budget", "0.1"], 1, contains=["even without the 1 unpriced rows"])

t.jsonl("guess.jsonl", [{"model": "m-guess", "input_tokens": 1000000, "output_tokens": 0}])
t.run("an unverified price warns and is not verified", SPEND, ["guess.jsonl", *P, "--budget", "5"], 2,
      contains=["WARNING price for m-guess is not verified", "check the provider's pricing page"])
t.run("the shipped price file is all unverified and says so", SPEND, ["guess.jsonl", "--budget", "5"], 2,
      contains=["UNKNOWN COST m-guess"])
t.jsonl("example.jsonl", [{"model": "example-small", "input_tokens": 1000, "output_tokens": 1000}])
t.run("a model from the shipped file prints the check note", SPEND, ["example.jsonl", "--budget", "5"], 2,
      contains=["WARNING price for example-small is not verified", "check the provider's pricing page before trusting any cost figure"])

openai = {"model": "m-test", "usage": {"prompt_tokens": 1000000, "completion_tokens": 0, "prompt_tokens_details": {"cached_tokens": 500000}}}
t.jsonl("openai.jsonl", [openai])
t.run("cached tokens inside prompt_tokens are not counted twice", SPEND, ["openai.jsonl", *P, "--budget", "2"], 0, contains=["1.1000"])

t.write("partial.jsonl", '{"model": "m-test", "input_tokens": 10, "output_tokens": 10}\nnot json\n{"model": "m-test", "note": "no tokens"}\n')
t.run("unread lines make a pass not verified", SPEND, ["partial.jsonl", *P, "--budget", "1"], 2, contains=["NOT READ line 2", "NOT READ line 3: no token fields", "2 lines were not read"])
t.jsonl("negative.jsonl", [{"model": "m-test", "input_tokens": -5, "output_tokens": 1}])
t.run("a negative count is not read", SPEND, ["negative.jsonl", *P, "--budget", "1"], 2, contains=["RESULT blocked", "no rows with token counts"])
t.run("--per run without run fields is blocked", SPEND, ["openai.jsonl", *P, "--budget", "1", "--per", "run"], 2, contains=["needs a 'run' field"])
t.run("a missing usage log is blocked", SPEND, ["nope.jsonl", "--budget", "1"], 2, contains=["RESULT blocked: no usage log"])
t.write("bad-prices.json", "{")
t.run("a broken prices file is blocked", SPEND, ["usage.jsonl", "--prices", "bad-prices.json", "--budget", "1"], 2, contains=["cannot be used"])
sys.exit(t.done())
