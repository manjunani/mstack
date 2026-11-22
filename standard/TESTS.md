# Testing a skill

A skill is published only when it passes three tests. They answer three different questions.

| Test | Question | Pass mark |
|---|---|---|
| **Trigger** | Does the skill start on requests it should answer? | starts on at least 8 of 10 |
| **Silence** | Does it stay quiet on requests it should not answer? | starts on at most 1 of 10 |
| **Benefit** | Is the result better with the skill than without it? | better on at least 2 of 3 tasks |

The pass marks are a first setting. They are reviewed after the first packs have real results.

## What you write

One file per skill, in the pack: `packs/<pack>/tests/<skill>.json`.

```json
{
  "fire": [
    "ten requests where the skill should start",
    "use different wording in each",
    "at least three must not contain the skill's name"
  ],
  "quiet": [
    "ten requests where it should stay quiet",
    "at least five are near misses that belong to the neighbouring skill"
  ],
  "tasks": [
    {
      "name": "short-name",
      "prompt": "A real task, written the way a user would ask.",
      "max_turns": 15,
      "allowed_tools": ["Read", "Glob", "Grep", "Skill", "Bash"],
      "graders": [
        { "name": "ran-check", "type": "tool_used", "tool": "Bash", "input_match": "scripts/check\\.py" },
        { "name": "honest", "type": "llm", "body": "PASS if the reply states an end state (pass, fail, not verified or blocked) and names what was not verified. FAIL otherwise." }
      ]
    }
  ]
}
```

Rules for the requests:

- Write them the way a person types, with typos and half sentences where that is natural.
- Do not write requests to make the skill look good. Near misses in `quiet` are the most valuable lines in the file.
- If a test fails, fix the skill or its description. Do not soften the test.

Grader types come from Claude Code: `tool_used`, `tool_order`, `file_exists`, `regex`, `llm`, `baseline`. Prefer the first four: they cost nothing and cannot be talked round. Use `llm` only for what a script cannot judge.

## Running

```
python3 tools/validate.py --strict        # mstack's own rules
claude plugin validate . --strict         # the plugin format
python3 tools/build_evals.py core         # turn tests/*.json into eval cases
claude plugin eval packs/core --case '*.fire.*'  --ablation none --max-cost-usd 5
claude plugin eval packs/core --case '*.quiet.*' --ablation none --max-cost-usd 5
claude plugin eval packs/core --case '*.task.*'  --max-cost-usd 10
```

- Trigger and silence run with `--ablation none`: one arm, with the pack installed.
- Tasks run in the default mode, which runs each task with the pack and without it and reports the difference.
- Each run is a separate, sandboxed Claude session with no user settings, no other plugins and no memory. That is what makes the result fair. It also means each run costs real usage: state the cost ceiling every time.

## Recording

Results go to `packs/<pack>/tests/results.json`, one entry per skill:

```json
{ "verify": { "trigger": "9/10", "silence": "0/10", "benefit": "3/3" } }
```

`tools/build_map.py` copies them into `skills.json` and the README. A skill with no entry shows as "not tested". Results are never typed by hand; they are taken from the eval output.

## What the tests do not prove

- They do not prove a skill is safe. Read every script. `skill-check` and a human review cover that.
- A trigger result holds for the model and the set of installed skills it was measured with. Installing many other packs can change it.
- Benefit on three tasks is a signal, not a proof. Real use decides.
