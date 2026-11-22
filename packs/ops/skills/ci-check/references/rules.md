# Rules of workflow.py

Checked: 2026-11-22. Verified against the platform's documentation: **no**. The list of top-level keys and the
treatment of `actions/*` and `github/*` as first-party were written from memory. If the platform adds a
top-level key, `unknown-top-key` will flag it wrongly: confirm in the platform's workflow syntax reference.

| Rule | Level | Fires on | Limit of the check |
|---|---|---|---|
| `unknown-top-key` | FAIL | A top-level key other than `name`, `run-name`, `on`, `permissions`, `env`, `defaults`, `concurrency`, `jobs` | The list is from memory |
| `no-trigger` | FAIL | No `on`, or an empty one | Does not check that event names exist |
| `no-jobs` | FAIL | No `jobs`, or the file is not a mapping | |
| `job-no-steps` | FAIL | A job with no `steps` and no `uses` | |
| `job-no-runner` | FAIL | A job with steps and no `runs-on` | Runner labels are not checked |
| `step-shape` | FAIL | A step with neither `run` nor `uses`, or with both | |
| `needs-missing` | FAIL | `needs` names a job that is not in the file; or jobs wait on each other in a circle | |
| `secret-echoed` | FAIL | A line of a `run` script calls `echo`, `printf`, `print`, `cat`, `console.log`, `Write-Host` or `Write-Output` with a secret expression, or with an env name that was set from a secret, and the output is not piped or redirected | Misses secrets printed by a program the step calls, and shell tracing (`set -x`) |
| `unpinned-action` | FAIL | `uses:` with no `@version`; or a third-party action at a branch name | "Branch" means: not a 40-character commit and not shaped like a version tag |
| `no-permissions` | FAIL | No `permissions` at the top and none in a job | Does not judge whether the permissions given are the least needed |
| `duplicate-key` | FAIL | The same key twice in one mapping | |
| `tag-pinned-action` | WARN (FAIL with `--require-sha`) | A third-party action at a version tag | A tag can be moved by the action's owner; a full commit cannot |
| `docker-no-digest` | WARN | `uses: docker://image` without `@sha256:` | |
| `write-all` | WARN | `permissions: write-all` | |
| `event-text-in-run` | WARN | A `run` script that pastes a title, body, message, name, label, ref or `head_ref` of the triggering event | A short pattern list, not a full taint check |

## The YAML reader

Supported: mappings and lists by indentation, a list at the same indentation as its key, `- key: value` items,
plain and quoted values, comments, one-line `[a, b]` and `{a: b}`, `|` and `>` text blocks, a leading `---`.

Not supported, reported as NOT READ with the line: anchors and aliases (`&x`, `*x`), merge keys (`<<`), tags
(`!!str`), several documents in one file, tabs for indentation, values or `[..]` lists continued on the next line.

All values are kept as text: `on: push` gives the text `push`, `20` gives `"20"`. The rules need nothing else.
