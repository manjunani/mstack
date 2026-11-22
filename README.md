# mstack

Agent skills that run something and prove the result. Small packs, one per domain. Install only what you need.

A skill is a folder with a `SKILL.md` that teaches a coding agent (Claude Code, Codex, Cursor and others) how to do one job. mstack is a library of them with four rules that most skill collections do not have:

1. **Every skill runs a script.** No skill is only advice. The script produces the check; the model does not grade its own work.
2. **Every skill ends in one of four states:** pass, fail, not verified, or blocked. "Not verified" never counts as a pass.
3. **Every skill is tested for when it starts.** Ten requests where it should start, ten where it should stay quiet, and the result is published below, including the bad ones.
4. **Packs are small.** A coding agent can only keep so many skill descriptions in view. Install the pack for the work you do, not three thousand skills.

## Why this exists

Before writing anything, we counted. Twelve public skill libraries hold 23,064 skill files with 10,579 different names. Of those names:

- about 55% have a description that never says when to use the skill, so an agent has no way to choose it;
- 19% ship a script;
- 1% ship tests of their own.

The skills that held up under reading were the ones that run a tool and end with a verdict. mstack is built only from that kind.

## Install

Claude Code:

```
/plugin marketplace add manjunani/mstack
/plugin install mstack-core@mstack
```

Then add any other pack the same way, for example `/plugin install mstack-dev@mstack`.

Other agents that read the Agent Skills format: copy the folders under `packs/<pack>/skills/` into your agent's skills folder. The skills are plain Markdown and standard-library Python. The guard hook in `mstack-core` works in Claude Code only; elsewhere the same steps are instructions and nothing enforces them. Installing through other tools' installers has not been tested yet.

## Using it

You do not type commands. Say what you want in plain words and the matching skill starts:

| You say | Skill | What happens |
|---|---|---|
| "are we done? is it safe to commit?" | `verify` | Runs your project's own test, lint and build commands, records each result against the exact code state, and reports what is proven and what is not |
| "delete the old migrations folder" | `safe-delete` | Lists what would go, what refers to it and what git cannot bring back; moves it to a trash folder; gives you one undo command |
| "only touch files in src/billing" | `scope-lock` | Locks edits to that folder until you release it |
| "we're going with Postgres, note that" | `remember` | Saves a short decision record with its reason; refuses duplicates and secrets |
| "I'm stopping for today" | `handoff` | Writes one file a fresh session can continue from |
| "what did you just change?" | `debrief` | Explains the real diff, and says what is not done and not verified |
| "is this skill safe to install?" | `skill-check` | Reads a third-party skill without running it and reports what a person should look at |
| "is there a skill for this?" | `mstack` | Looks it up in the skill map and names one, or says none fits |

### One setting

Add one line to your project's `CLAUDE.md` or `AGENTS.md` to choose how much the skills explain:

```
mstack-level: beginner
```

`beginner`, `standard` (the default) or `expert`. It changes how much is explained and asked. It never removes a check or a safety step.

### The guard hook

`mstack-core` ships a hook for Claude Code that looks at commands before they run. It denies a recursive delete and points to `safe-delete`, asks before commands such as `git reset --hard`, a forced push or `DROP TABLE`, and asks before MCP tools whose names look destructive. It is a seat belt, not a security boundary: it matches patterns and can be wrong in both directions. Switch it off with `MSTACK_GUARD=off`.

## Packs and skills

The table is generated from the skills themselves by `tools/build_map.py`. "Tests" shows measured results: `trigger` is how many of ten fitting requests started the skill, `silence` is how many of ten unfitting requests started it (lower is better). "not tested" means exactly that.

<!-- skills:start -->

### mstack-3d

3D models and scenes, proven by numbers and pixels: glTF gate, three.js render check, rig motion check, Blender jobs, text-to-3D acceptance.

```
/plugin install mstack-3d --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `blender-task` | Runs a Blender job in background mode with a script and proves the result from a state file of objects, sizes, polygon counts, modifiers and applied scale, checked against facts from the request. | python3, Blender | smoke: trigger 2/2, silence 0/2 |
| `gltf-gate` | Stops a .glb or .gltf model from shipping until it is a real file, sound in structure, inside a budget and looked at. | python3; optional gltf_validator, gltf-transform, a browser for renders | smoke: trigger 2/2, silence 0/2 |
| `rig-motion-check` | Checks a rigged or animated .glb by numbers: lists bones and clips, then follows a foot or hand bone through each clip and reports height above the floor, sliding while planted, sinking and scale drift, with a per-sample table. | python3 | smoke: trigger 2/2, silence 0/2 |
| `text-to-3d` | Gets one 3D model from a text-to-3D provider the user picked, with the cost agreed first, then accepts or rejects the downloaded file by running real-file, structure and budget checks and recording the spend. | python3, the provider's own tool or account | smoke: trigger 2/2, silence 0/2 |
| `three-verify` | Proves a three.js or React Three Fiber scene renders and reports its cost. | python3, a browser with a screenshot tool; node optional | smoke: trigger 2/2, silence 0/2 |

### mstack-ai

Checks for building with AI models and agents: gate an evaluation run, probe an MCP server, triage an agent trace, lint tool definitions, score retrieval, measure spend, test for prompt injection, check an LLM grader.

```
/plugin install mstack-ai --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `eval-gate` | Decides whether a change to a prompt, model, tool or agent made results worse, by comparing a new evaluation run with a saved baseline, case by case over repeated trials. | python3 | smoke: trigger 2/2, silence 0/2 |
| `injection-test` | Tests whether planted instructions in documents can steer an agent, using eight harmless test documents that ask for a marker word or a forbidden tool call, then reads the saved transcripts and reports which documents the agent obeyed. | python3, the user's own agent | smoke: trigger 2/2, silence 0/2 |
| `judge-check` | Tests whether an LLM grader can be trusted, by comparing its verdicts with examples a person labelled and reporting agreement, a confusion table, Cohen's kappa and every disagreement. | python3 | smoke: trigger 2/2, silence 0/2 |
| `mcp-check` | Proves a stdio MCP server works by starting it, running the initialize and tools/list exchange, checking that every tool's input schema is well formed, and calling the tools the user names to compare each answer with its schema. | python3, the server's own runtime | smoke: trigger 2/2, silence 0/2 |
| `rag-check` | Measures whether retrieval returns the passage that holds the answer, from a gold set of questions and the ranked ids a retriever returned, with hit rate at k, mean reciprocal rank, the misses and the change against a saved baseline. | python3 | smoke: trigger 2/2, silence 0/2 |
| `spend-check` | Measures the tokens and cost of an AI flow from its own usage log and compares them with a budget, with totals by model or feature tag, the cache read share, and rows without a price kept apart. | python3 | smoke: trigger 2/2, silence 0/2 |
| `tool-lint` | Checks tool definitions before a model sees them and flags names that are unclear or collide, descriptions that do not say when to use the tool, missing required lists, untyped parameters and pairs of tools whose descriptions overlap. | python3 | smoke: trigger 2/2, silence 0/2 |
| `trace-triage` | Reads the saved trace of an agent run and names where it went wrong, with line numbers for the first failing step, repeated identical tool calls, tool errors the agent ignored, turns with no progress and the largest context contributors. | python3 | smoke: trigger 2/2, silence 0/2 |

### mstack-apps

iPhone apps in SwiftUI and Mac apps in Tauri: prove a screen on the simulator, record a flow, check store readiness, accessibility, signing and notarisation, Tauri configuration, crash reports, app size and release notes.

```
/plugin install mstack-apps --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `app-release-notes` | Drafts "What's New" notes for an app version from the real commits between two tags and checks them: each line names a commit in the range, and each user-facing feat, fix or perf commit appears or is skipped on purpose. | python3, git | smoke: trigger 2/2, silence 0/2 |
| `app-size` | Measures a built .app or .ipa by part (executable, frameworks, Assets.car, resources) and lists the largest files, keeps a baseline under .mstack, and shows what grew, what is new and what was removed since that baseline. | python3 | smoke: trigger 2/2, silence 0/2 |
| `crash-read` | Reads an Apple crash report (.ips or .crash) and names the failing frame from the app's own code. | python3; dwarfdump and atos (Xcode command-line tools) only for unsymbolicated reports | smoke: trigger 2/2, silence 0/2 |
| `ios-a11y-check` | Finds SwiftUI code that breaks VoiceOver and Dynamic Type, with file and line. | python3; the simulator only for the screenshots | smoke: trigger 2/2, silence 0/2 |
| `ios-submit-check` | Finds the mechanical reasons an iPhone app upload or App Store review would bounce: missing purpose strings for camera, location or photos, an incomplete privacy manifest, mismatched version and build numbers, a bad 1024 icon, wrong screenshot sizes. | python3 | smoke: trigger 2/2, silence 0/2 |
| `mac-release-verify` | Checks that a built Mac app or .dmg will open on other people's Macs: runs codesign strict verification, a Gatekeeper assessment with spctl and stapler validate for the notarisation ticket, and reports each as pass, fail or could not check. | python3, macOS, codesign, spctl, xcrun stapler | smoke: trigger 2/2, silence 0/2 |
| `sim-flow` | Records a user flow on the iPhone simulator step by step and checks the record: each step has an action, the screen expected, what was seen and a non-blank screenshot, with one result for the whole flow. | python3, a tool that can tap on the simulator (the host agent's simulator tool or the project's UI tests) | smoke: trigger 2/2, silence 0/2 |
| `sim-proof` | Proves an iPhone app launches on the simulator and shows a real screen: installs the built .app on a booted simulator, launches it, checks the process stays alive and takes a screenshot that a pixel check confirms is not blank. | python3, Xcode command-line tools (xcrun simctl), a booted simulator, a simulator build of the app | smoke: trigger 2/2, silence 0/2 |
| `tauri-preflight` | Flags release blockers in a Tauri app's tauri.conf.json and capabilities. | python3 | smoke: trigger 2/2, silence 0/2 |

### mstack-core

The base pack: prove work is done, delete safely, keep decisions, hand off a session, find the right skill.

```
/plugin install mstack-core --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `debrief` | Explains what a task really changed, from the actual diff and the checks on record, including what is not done or not verified. | python3, git | trigger 9/10, silence 0/10 |
| `handoff` | Writes one file that lets a fresh session continue unfinished work without the old conversation, with the goal, what is done, the next steps and the exact code state. | python3, git | trigger 10/10, silence 0/10 |
| `mstack` | Looks up which mstack skill or pack fits a task, from the generated map of every skill, and gives the install line for a pack that is missing. | python3 | trigger 10/10, silence 0/10 |
| `remember` | Saves a decision or a lesson as a short record in a plain file in the repository, so no one asks again or repeats a mistake. | python3 | trigger 9/10, silence 0/10 |
| `safe-delete` | Deletes files and folders so the removal can be undone: lists what would go, what refers to it and what git cannot bring back, then moves it to a trash folder with an undo command. | python3, git | trigger 9/10, silence 0/10 |
| `scope-lock` | Keeps file edits inside one folder until released, so a task cannot change files elsewhere by accident. | python3 | trigger 10/10, silence 0/10 |
| `skill-check` | Reads a third-party skill, plugin or skills repository before install and reports what could harm the user, such as downloads piped into a shell, credential reads, hidden text and instructions aimed at the agent. | python3 | trigger 10/10, silence 0/10 |
| `verify` | Proves a "done" claim with fresh evidence: runs the project's own test, type, lint and build commands and records each result for the exact code state. | python3, git | trigger 8/10, silence 0/10 |

### mstack-data

Working with data: profile, check, diff and clean datasets, run and review SQL read-only, trace report numbers, compare groups, and audit charts, spreadsheets and notebooks.

```
/plugin install mstack-data --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `chart-check` | Checks a chart from its JSON spec for a truncated bar axis, missing labels or units, clipped data, too many series, crowded pies, dual axes, categories out of order, values that differ from the source data. | python3 | smoke: trigger 2/2, silence 0/2 |
| `data-check` | Runs written rules against a dataset like tests (not null, unique, allowed values, range, pattern, row count, foreign key into another file) and reports each rule as pass, fail or not run, with the failing row numbers. | python3 | smoke: trigger 2/2, silence 0/2 |
| `data-clean` | Cleans messy values in a CSV into a new file (trim, case, dates to ISO, exact duplicates, mapped codes such as UK and U.K. | python3 | smoke: trigger 1/2, silence 0/2 |
| `data-diff` | Compares two versions of a dataset by key and reports rows added, removed and changed, which columns changed and how often, with before and after values; reordered rows and columns are not counted as changes, and the totals are checked to add up. | python3 | smoke: trigger 2/2, silence 0/2 |
| `data-profile` | Describes a CSV, JSON-lines file or SQLite table as it really is, giving row count, per-column type, empty share, distinct count, min and max, top values, duplicate rows, and columns that look like identifiers or personal data. | python3 | smoke: trigger 2/2, silence 0/2 |
| `notebook-check` | Checks a Jupyter .ipynb file for cells run out of order or never run, error outputs, names used before they are defined, machine-only paths, credentials; re-runs a copy when Jupyter is there. | python3, jupyter (optional, for the re-run) | smoke: trigger 2/2, silence 0/2 |
| `number-trace` | Ties every number in a report to the query or file aggregate that produced it, re-runs each one, and lists numbers that match, do not match, or have no source. | python3 | smoke: trigger 2/2, silence 0/2 |
| `query-review` | Reviews one SQL query without running it and flags SELECT *, joins with no condition, filters wrapped in a function, no LIMIT and, on SQLite, the query plan's full scans and missing indexes. | python3 | smoke: trigger 1/2, silence 0/2 |
| `sheet-audit` | Audits an .xlsx workbook from the file for error cells, numbers typed over formulas, formulas that break their row or column, links to empty cells or other workbooks, hidden sheets, and what it did not read. | python3 | smoke: trigger 2/2, silence 0/2 |
| `sql-run` | Runs one SQL query read-only with the limits inside the runner, with a single SELECT or WITH only, the SQLite file opened read-only, a row cap, a time limit, the query plan printed with the rows. | python3 | smoke: trigger 2/2, silence 0/2 |
| `stat-compare` | Compares two groups from the raw rows (A/B test, before and after, two segments), giving sizes, means, medians, a seeded permutation test, an interval, an effect size, and warnings on small samples, skew and spread. | python3 | smoke: trigger 2/2, silence 0/2 |

### mstack-design

UI and UX checks: gate a rendered page, audit accessibility, check tokens, build and match screens, check interface words, keep work on brand.

```
/plugin install mstack-design --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `a11y-audit` | Finds accessibility failures on a rendered page with axe-core and a Tab-key walk, fixes them, then proves the fix by running the same scan against a saved baseline. | python3, node, Playwright with Chromium and axe-core in the project (or a host browser tool that can run axe) | smoke: trigger 2/2, silence 0/2 |
| `brand-kit` | Captures the user's own brand into one brand.json file (colours with use and never rules, fonts, voice with banned phrases) and checks pages, stylesheets or copy against it, listing every off-brand colour, font and phrase with its location. | python3 | smoke: trigger 2/2, silence 0/2 |
| `design-review` | Gates a rendered page before it is called done, from what the browser drew at phone, tablet and desktop width. | python3, a browser the agent can drive (host browser tool or Playwright) | smoke: trigger 2/2, silence 0/2 |
| `token-check` | Measures every text-on-background colour token pair in light and dark mode, proposes a passing value with the same hue for each failure, and lists hard-coded colours and off-scale sizes in the code. | python3 | smoke: trigger 2/2, silence 0/2 |
| `ui-build` | Builds a new screen, or reworks one that looks generic, so it fits this product: a short written direction first, then the build, a lint for unfinished work and default-look traits, and at most three render-and-inspect rounds. | python3, a browser the agent can drive for the render step | smoke: trigger 2/2, silence 0/2 |
| `ui-copy` | Checks the words in an interface and flags one action with several names, vague buttons like "OK" or "Submit", errors with no way forward, raw error codes and leftover placeholders. | python3; a browser for the best evidence | smoke: trigger 1/2, silence 0/2 |
| `ui-match` | Builds a screen from a screenshot, Figma export or mockup image and proves how close it is by comparing a screenshot of the result with the reference, region by region. | python3, a browser the agent can drive, the reference as PNG | smoke: trigger 1/2, silence 0/2 |

### mstack-dev

Software development with proof at each step: plan, build, prove a test, debug, review, parallel work, commit, land a branch, release, security check.

```
/plugin install mstack-dev --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `build` | Carries out a plan task by task and keeps a ledger in which a task is logged complete only when its own test command passes and no file outside its list changed. | python3, git, the project's test runner | smoke: trigger 2/2, silence 0/2 |
| `commit` | Turns a mixed working tree into clean commits, one per reason for change. | python3, git | smoke: trigger 2/2, silence 0/2 |
| `debug` | Finds the real cause of a bug before any fix. | python3, git | smoke: trigger 2/2, silence 0/2 |
| `land` | Finishes a branch in one of three ways the user picks: merge it locally, push it and open a pull request, or keep it as is. | python3, git, gh (only for opening a pull request) | smoke: trigger 2/2, silence 0/2 |
| `parallel` | Runs independent tasks at the same time with separate agents, one git worktree each, then merges the results in order and runs the suite on the merged tree; refuses when two tasks' files overlap. | python3, git 2.17 or newer, a host that can start separate agents | smoke: trigger 1/2, silence 0/2 |
| `plan` | Turns a settled request into a plan file of small ordered tasks, each naming its files, one check command and the output to expect, then lints the plan. | python3, git | smoke: trigger 2/2, silence 0/2 |
| `prove-test` | Shows that a test can catch the bug it protects against. | python3, git, the project's test runner | smoke: trigger 2/2, silence 0/2 |
| `release` | Cuts a version from the exact range since the last tag: lists the commits, migrations, config and dependency changes in it, drafts release notes, and refuses to go on until a rollback step is written in the release file. | python3, git | smoke: trigger 2/2, silence 0/2 |
| `review` | Finds real defects in a change, ranked by severity, and drops every finding whose file, line and quoted text do not match the source. | python3, git | smoke: trigger 2/2, silence 0/2 |
| `secure` | Finds security problems an attacker could use in the current change, with a status per check (ran, failed, not available): secrets in added lines, the dependency audit, changed entry points for untrusted input. | python3, git, the ecosystem's audit tool (npm, pip-audit, cargo-audit, govulncheck, bundler-audit) | smoke: trigger 2/2, silence 0/2 |

### mstack-growth

Getting a product found and understood: site audit, structured data, launch pages, posts, claims, first screen, tracking, store listing, page comparison, mail domain records.

```
/plugin install mstack-growth --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `claim-check` | Finds every number, superlative ("fastest", "best", "only", "first"), comparison and testimonial in marketing text and fails each one that has no entry with evidence in a sources file. | python3; network only with --fetch, to the evidence addresses given | smoke: trigger 2/2, silence 0/2 |
| `first-screen` | Reports what a landing page puts first: the first heading, first paragraph, first call to action and where it leads, whether the headline names the product, whether promised words appear, and the bytes that load first. | python3; network only for a URL | smoke: trigger 2/2, silence 0/2 |
| `launch-site-check` | Asks a site for every page a first visitor needs before launch (home, pricing, privacy, terms, contact, a real 404, favicon, social preview image tags, a working sign-up or download link) and reports each one. | python3, network access to the site named | smoke: trigger 2/2, silence 0/2 |
| `mail-domain-check` | Checks the SPF, DKIM and DMARC records of one sending domain from record text or the system resolver: syntax, a too-permissive SPF, a DMARC policy of none, weak or empty DKIM keys, and missing records. | python3; dig or nslookup only for a live lookup | smoke: trigger 2/2, silence 0/2 |
| `page-compare` | Sets two saved HTML pages side by side on measurable points only, with no verdict on which is better. | python3 | smoke: trigger 2/2, silence 0/2 |
| `post-check` | Checks a draft post against one platform's limits: length counted the platform's way, link and hashtag counts, blog front matter, local images that exist, and no claim still marked unverified or TODO. | python3 | smoke: trigger 2/2, silence 0/2 |
| `site-audit` | Crawls one live site within a page limit, obeying robots.txt, and reports per page the title, meta description, h1, heading order, canonical, lang and image alt text, plus robots.txt, the sitemap and whether its URLs answer. | python3, network access to the site named | smoke: trigger 2/2, silence 0/2 |
| `store-listing-check` | Checks an app store listing kept as a file (name, subtitle, description, keywords, screenshots) against the store's field limits from a dated list, finds repeated keywords and missing screenshots, and fails claims with no source. | python3 | smoke: trigger 2/2, silence 0/2 |
| `structured-data-check` | Validates the JSON-LD on real pages: each block parses, has @context and @type, and Article, Product, Organization, BreadcrumbList, FAQPage and SoftwareApplication items carry the properties in a dated list. | python3, network only for a URL | smoke: trigger 2/2, silence 0/2 |
| `tracking-check` | Reads a HAR file or network capture and confirms each expected analytics event was sent with the right name and properties, flagging doubles, error answers and emails in URLs. | python3, a network capture the user made | smoke: trigger 1/2, silence 0/2 |

### mstack-media

Audio, video and image work with a measured result: word-timed transcripts, subtitles, platform exports, podcast clean-up, show notes, transcript-based cuts and image batches.

```
/plugin install mstack-media --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `captions` | Writes .srt and .vtt subtitle files from a word-timed transcript and checks every cue for overlaps, order, line length and reading speed; burns them into the video only when asked. | python3; ffmpeg with the subtitles filter (libass) for burn-in only | smoke: trigger 1/2, silence 0/2 |
| `export-check` | Encodes a finished video or audio file for a named platform and proves the result with ffprobe and a loudness reading. | python3, ffmpeg, ffprobe | smoke: trigger 2/2, silence 0/2 |
| `image-batch` | Applies one resize, crop and export to a whole folder of images into a new folder, and checks every output. | python3; sips (macOS), ImageMagick or Pillow | smoke: trigger 2/2, silence 0/2 |
| `podcast-edit` | Cleans a spoken recording into a new file: shortens long pauses, brings loudness to a named target in two passes, and only on request removes filler words with short crossfades, writing a list of every cut with its time. | python3, ffmpeg, ffprobe; a word-timed transcript for filler removal | smoke: trigger 2/2, silence 0/2 |
| `show-notes` | Writes chapters and show notes for an episode from its word-timed transcript, then checks that chapters start at zero, ascend, are long enough and end inside the recording, and that every quoted line matches the transcript word for word. | python3 | smoke: trigger 2/2, silence 0/2 |
| `transcribe` | Makes a word-timed transcript of an audio or video file (JSON with start, end and confidence per word, plus plain text) and checks that it covers all the speech. | python3, ffmpeg, ffprobe, a local speech recogniser or an API the user names | smoke: trigger 2/2, silence 0/2 |
| `video-edit` | Cuts supplied footage by its transcript into a new file, with a cut list the user approves first. | python3, ffmpeg, ffprobe, a word-timed transcript | smoke: trigger 2/2, silence 0/2 |

### mstack-ops

Running software: check a deploy, a migration, a backup, a CI file, a bill and a log with scripts that end in a stated result, and touch nothing live without a yes.

```
/plugin install mstack-ops --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `ci-check` | Checks GitHub Actions workflow files before a push for unknown keys, jobs with no steps, a needs that names no job, printed secrets, unpinned third-party actions and missing permissions. | python3 | smoke: trigger 2/2, silence 0/2 |
| `ci-fix` | Turns a saved log of a failed CI run into the first failing step, the command it ran and the first error lines, then reruns that command locally and says whether the same error came back. | python3 | smoke: trigger 2/2, silence 0/2 |
| `cost-watch` | Reads a usage or billing export (CSV or JSON), sums it by service and day, projects the month and compares it with the limit the user states, and names the service whose spend grew most. | python3 | smoke: trigger 2/2, silence 0/2 |
| `dep-upgrade` | Upgrades one dependency with a record that proves it: the old version from the lock file, the target, the changelog sections read, and the same test command passing before and after. | python3, the project's package manager | smoke: trigger 2/2, silence 0/2 |
| `deploy-check` | Confirms that the version now running is the one that was meant to ship and that it answers. | python3 | smoke: trigger 2/2, silence 0/2 |
| `env-check` | Lists environment variable names the code reads that are not set or not documented, and names that nothing reads, without showing any value. | python3 | smoke: trigger 2/2, silence 0/2 |
| `log-triage` | Narrows a saved log file to the first error, the distinct error groups with counts (numbers and ids masked), and what changed in the lines just before the first error, such as a deploy, a restart or a config change. | python3 | smoke: trigger 2/2, silence 0/2 |
| `migration-check` | Reads pending SQL migration files and flags statements that lock a table, lose data or leave no way back, each with the reason and a safer form. | python3 | smoke: trigger 2/2, silence 0/2 |
| `perf-check` | Measures whether a change made one command, script or build faster or slower beyond run-to-run noise, from a saved baseline and repeated timings compared by median and spread. | python3 | smoke: trigger 1/2, silence 0/2 |
| `restore-test` | Restores a backup into a new scratch folder and proves the data is in it, by an integrity check and row or file counts compared with numbers the user states. | python3 | smoke: trigger 2/2, silence 0/2 |
| `rollback` | Returns a service to its previous version through a checked plan, then confirms the old version answers. | python3, the hosting platform's own command-line tool or dashboard | smoke: trigger 2/2, silence 0/2 |

### mstack-product

Requirement gathering and brainstorming: settle what is wanted, write a checkable spec, trace it to tests and code, put numbers on quality words, produce and compare options, test a plan's assumptions, and turn interview notes into evidence.

```
/plugin install mstack-product --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `clarify` | Settles what the user wants before anything is built. | python3, a user who can answer | smoke: trigger 2/2, silence 0/2 |
| `compare-options` | Ranks named options on weighted criteria with a script, applies vetoes, and shows the smallest change that would flip the winner. | python3 | smoke: trigger 1/2, silence 0/2 |
| `ideate` | Produces a wide list of options grounded in the project, cuts it with a reason for every cut, and ends with a short list of two or three. | python3 | smoke: trigger 2/2, silence 0/2 |
| `nfr-budgets` | Turns quality words such as fast, reliable or secure into budgets that a command can check. | python3, a project with commands that can be run | smoke: trigger 2/2, silence 0/2 |
| `premortem` | Assumes a chosen plan has already failed, lists the assumptions it rests on, ranks them by impact and confidence with a script, and names the cheapest test for the worst one, with a pass and a fail line. | python3, a written plan or spec | smoke: trigger 2/2, silence 0/2 |
| `research-synthesis` | Turns interview transcripts or research notes into themes backed by exact quotes. | python3, text sources | smoke: trigger 2/2, silence 0/2 |
| `spec` | Writes a one-page spec in which every "done when" line has an id (R-001) and names how it will be checked, then lints it. | python3 | smoke: trigger 2/2, silence 0/2 |
| `trace` | Builds a matrix from each requirement id in the spec (R-001) to the tests, code and commits that mention it, and flags what is missing in either direction. | python3, git, a spec with ids | smoke: trigger 2/2, silence 0/2 |

### mstack-test

Software testing: QA a running app, pin down flaky tests, derive test cases, find untested risks, keep test data free of personal data, check an API against its contract, confirm a bug before reporting it.

```
/plugin install mstack-test --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `api-check` | Compares a running API with its OpenAPI contract by sending one real request per route and printing request, expected and actual for every status or response shape that does not match. | python3, a running local or test server, an OpenAPI 3 contract in JSON | smoke: trigger 2/2, silence 0/2 |
| `bug-report` | Confirms a bug reproduces from a clean start, saves the output as evidence, and writes one report that a lint script checks for steps, expected, actual, evidence files and leaked secrets or personal data. | python3, a command or steps that show the bug | smoke: trigger 2/2, silence 0/2 |
| `flaky-triage` | Makes an intermittent test fail on demand, names the kind of cause from recorded runs, and proves the fix with enough repeated green runs. | python3, the project's test runner, git (for the guard step) | smoke: trigger 2/2, silence 0/2 |
| `qa-run` | Drives a running app through the user flows a change touched and writes a QA report in which every issue has steps, expected, actual and a saved evidence file. | python3, a browser tool of the host agent, git (optional) | smoke: trigger 2/2, silence 0/2 |
| `test-cases` | Turns a spec or a function contract into a table of test cases (boundaries, combinations, properties) in which every requirement has a case and every case has one specific expected result. | python3, a spec or contract with requirement lines | smoke: trigger 2/2, silence 0/2 |
| `test-data` | Builds factories and seed data that hold no real personal data and give the same result on every run, proven by a scanner and a two-run comparison. | python3, the project's seed or factory command | smoke: trigger 2/2, silence 0/2 |
| `test-gaps` | Finds what matters and is not tested. | python3, git (for recent changes) | smoke: trigger 2/2, silence 0/2 |

### mstack-web

Working with the live web, honestly: check a deployed site, find broken links, extract a page, check quotes against saved sources, plan a polite fetch, keep research sourced, measure transfer speed, watch a page for changes.

```
/plugin install mstack-web --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `cite-check` | Confirms that every quote and quoted claim in a document appears word for word in the saved copy of the source it cites, and lists not found, found and source missing. | python3 | smoke: trigger 2/2, silence 0/2 |
| `fetch-plan` | Writes a plan before fetching many pages: robots.txt verdict per address, crawl delay, sitemap, terms link, count, rate and duration; refuses a plan that touches disallowed paths. | python3 | smoke: trigger 1/2, silence 0/2 |
| `link-check` | Finds broken links and missing images, scripts and styles on one site by crawling it within a stated depth and page limit, and sorts every target into broken, fine and could not check. | python3 | smoke: trigger 2/2, silence 0/2 |
| `page-extract` | Turns one web page into clean JSON: title, main text without navigation or scripts, headings, links and tables; fails on an empty result or a page that needs JavaScript. | python3 | smoke: trigger 1/2, silence 0/2 |
| `page-speed` | Measures how a page transfers without a browser: median time to first byte, bytes, requests, uncompressed text and missing cache headers, against the user's budgets. | python3 | smoke: trigger 2/2, silence 0/2 |
| `page-watch` | Tells what changed on one web page since the last look: saves a normalised text snapshot under .mstack/ and on the next run lists added and removed lines, ignoring parts the user marks as noisy (clocks, ads, counters). | python3 | smoke: trigger 2/2, silence 0/2 |
| `site-check` | Checks how a deployed address answers: every redirect hop, the final status, security and cache headers, certificate expiry and mixed content, each marked ok, warn, failed or not checked. | python3 | smoke: trigger 2/2, silence 0/2 |
| `web-research` | Answers a question from the web with a notes file where every claim has a source address, a saved copy or access date, and a label (quoted, paraphrased, inferred), and checks it: unsourced claims fail and a conclusion resting on one source is flagged. | python3, the host's web search and fetch tools | smoke: trigger 2/2, silence 0/2 |

### mstack-writing

Text work with a proof: copy-edits where every change is listed and nothing else moved, and translations where numbers, names, links and placeholders are counted on both sides.

```
/plugin install mstack-writing --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `copyedit` | Proofreads and copy-edits a document to a style guide, house style by default, listing corrections, suggestions and queries apart and proving code, quotes, links and numbers survived. | python3 | smoke: trigger 1/2, silence 0/2 |
| `translate-check` | Translates a text or a JSON strings file and proves nothing countable was lost. | python3 | smoke: trigger 2/2, silence 0/2 |

### mstack-xr

VR and AR without guessing: WebXR checks in an emulator, a numeric comfort audit, platform detection, and phone AR previews at real size.

```
/plugin install mstack-xr --marketplace manjunani/mstack
```

| Skill | What it does | Needs | Tests |
|---|---|---|---|
| `webar-preview` | Turns a .glb into a phone AR preview at true size: compares the model's bounding box in metres with the real object's declared size, checks a .usdz twin with Apple's usdcat and usdchecker, and writes a small page with an AR viewer element. | python3; optional usdcat, usdchecker, a GLB to USDZ converter, a model-viewer build | smoke: trigger 2/2, silence 0/2 |
| `webxr-verify` | Proves a WebXR page works without a headset: checks the code for an XR session, render loop, input and exit, and judges an emulated session by head-pose screenshots and console errors. | python3, a browser the agent can drive, a WebXR emulator | smoke: trigger 2/2, silence 1/2 |
| `xr-comfort-review` | Measures every UI element of a running VR or AR scene: distance from the head, visual angle of text, angle off the forward view, target size and head-locked placement, each with pass or fail against dated limits. | python3, a browser running the scene (three.js) | smoke: trigger 2/2, silence 0/2 |
| `xr-target` | Finds which VR or AR platform and stack a repository targets (three.js WebXR, A-Frame, Babylon, Unity XR, Quest Android, visionOS, Unreal, Godot) and prints one target record with the evidence lines, then names the skill to use next. | python3 | smoke: trigger 2/2, silence 0/2 |

<!-- skills:end -->

The same information is in `skills.json`, the skill map. The `mstack` skill reads it to answer "which skill fits?".

## Status

Version 0.1. Honest state of things:

- Every script was run on throwaway projects, including the failure cases. Those script tests are in each pack's `tests/scripts/`, with notes on what could not be tested in `tests/NOTES.md`.
- The core pack has the full trigger test: ten fitting and ten near-miss requests per skill. The other packs have a smoke test so far, two of each per skill, marked "smoke" in the table. A smoke result of 2/2 is a good sign, not proof.
- All trigger results are from single runs in a clean session with only that pack installed. With many other skills installed, results can differ.
- The "is the result better with the skill than without" test exists for every skill and has not been run yet.
- Skills that need a tool we did not have (a 3D program, a headset, a speech recogniser) detect that tool and stop as blocked. Their live path is untested and marked so.
- Numbers that age, such as platform limits and thresholds, live in dated data files and are marked unverified until someone checks them against the source.

## How a skill is built

`standard/` is the method: the rules, how to write a description that triggers, the skill template, how tests work, and how to build a pack. `tools/validate.py` enforces the rules; `claude plugin validate` checks the plugin format.

## Contributing and reporting

- **A skill started at the wrong time, or stayed quiet:** [open a trigger issue](https://github.com/manjunani/mstack/issues/new/choose) with the exact words you typed. These reports improve the library most.
- **A bug or a new skill idea:** use the matching issue form. Propose a new skill in an issue before writing it.
- **A pull request:** read [CONTRIBUTING.md](CONTRIBUTING.md). One change per pull request; the checks in CI must pass; only the maintainer merges.
- **A security problem:** do not open an issue. Follow [SECURITY.md](SECURITY.md).

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

## What mstack will not contain

Skills that help deceive: fake reviews, invented numbers, getting around bot detection, defeating AI detectors. Skills that are a role ("you are a senior engineer") or a list of tips. Advertising of any kind.

## Licence

MIT. Every skill is written from scratch. Other libraries were studied for ideas; none of their text is used.
