# How mstack compares (November 2026)

I maintain mstack, so I am not neutral. To keep it fair I asked every project the same three questions, mstack included, and wrote down where each one is better than mine.

1. **Does it check the work?** Does it ship code that tests what the agent did and prints a result, or is it written instructions the agent is trusted to follow?
2. **Does it show its results?** Has it published numbers on what it changes: whether tasks go better with it, or what it costs?
3. **What do you have to trust?** Telemetry, a proxy in front of the model, browser cookies, an install script fetched from the internet.

Stars, licences and skill counts come from the GitHub API on 26 November 2026. Everything else comes from each project's own README and files. I did not rerun anyone's benchmarks, so their numbers are their own.

## Stacks: one person's way of working

A stack is not a catalogue. It is how one person works with a coding agent, written down as skills.

| | gstack | pstack | tstack | mstack |
|---|---|---|---|---|
| Whose | Garry Tan | Lauren Tan, ported to Claude Code by Michael Denyer | Theo (t3dotgg) | Me, the maintainer |
| Size | about 23 tools | about 69 skills, 25 of them principles | 9 skills | 19 in the stack, 103 more in add-on packs |
| Best at | Real browser QA, safety hooks that block | Engineering principles, playbooks, formal verification | Pull requests from change to merge, review by three models | Every step ends in a script's verdict |
| Checks the work? | Partly (QA, hooks) | Partly (verification skills) | Mostly instructions | Every skill |
| Shows its results? | Yes, including a result where it did not help | Not that I found | No | Yes, for every skill |
| What you trust | Opt-in browser cookie import | A routing hook, agents on other models | `gh`, models from other providers | Python and git |
| Beyond code? | Design and docs roles | Mostly code | Pull requests only | Design, data, ops, web, apps, media, 3D, XR, AI agents |
| Stars | 143k | 4.9k | 4.4k | 0 |

**gstack** is Garry Tan's exact setup. Its tools act as a CEO, a designer, an engineering manager, a release manager and QA. The browser QA is real, and its safety hooks stop a dangerous command instead of warning about it. Best of all, it tested itself and published that the pack did not raise the rate of bugs fixed. That is the most honest number in this whole document. The cost: a big workflow to adopt, and cookie import is a sensitive feature even when it is opt-in.

**pstack** started as Lauren Tan's Cursor stack. Michael Denyer's port runs it on Claude Code and about a dozen other agents. You tell `poteto-mode` what you want and it picks a playbook: plan, hand parts to an architect or a swarm of agents, then review and verify. It is the most thoughtful stack here, with principle skills such as "fix root causes" and "prove it works", and skills that set up formal verification. The cost: a lot of machinery, agents on several models, and no published numbers on what it changes.

**tstack** is Theo's nine everyday skills, almost all about pull requests. "Full send" proves a change, reviews it, files the PR, watches CI and merges. `council` asks three models from different providers to review until they agree. It is small and sharp. The cost: it needs models from other providers for review, and it is about pull requests only.

**mstack** is my stack: plan, build, verify, review, commit, land, with debug, secure, handoff and remember around them. Every skill runs a script and ends with pass, fail, not verified or blocked, so the model never grades its own work.

Why you might choose it:

- **"Done" means evidence.** `verify` runs your own tests and saves each result against the exact code state. If the code changes afterwards, the answer becomes "not verified", never a pass.
- **The numbers are public, bad ones included.** Every skill is tested on when it should start (10 real requests) and when it should stay quiet (10 near misses), and on whether its tasks go better with it than without it (three runs each). See the README.
- **It is cheap to run.** Helper agents get file and shell tools only. On a four-task test plan that cut the helper cost from $3.06 to $1.70. One session was still cheaper for that small plan ($1.13), and that is published too.
- **Nothing to trust.** No telemetry, no proxy, no cookies, no second model provider.
- **It grows past code.** When the work is a design, a dataset, a deploy, an App Store upload or a VR scene, add that pack. Same rule: a real check, a clear verdict.

Where it is weaker: it is new, with no stars and one maintainer. The benefit tests are small (two or three tasks per skill, written by me, on one model). Only Claude Code is tested. It has no multi-model review like tstack's `council`, and no full browser QA in the stack like gstack's.

## Skill libraries: catalogues to pick from

These are collections rather than one person's way of working. Most are instructions; a few ship real checks.

### Code

- **Anthropic's skills** (201k stars). The official examples and the format spec, with a `skill-creator` that helps you test your own skills. They are examples rather than a workflow, with no published results, and the licence is set per folder.
- **Superpowers** (327k). One clear flow from idea to finished branch, and skills that start on their own. Heavy for small edits, and no published numbers on what it changes.
- **Matt Pocock's skills** (333k). Short, practical and consistent. No scripts, so quality rests on the model following text, and some skills assume the author's own setup.
- **Everything Claude Code** (311k). Covers almost everything, with profiles to install a smaller core and a security scanner for agent config. Its size makes it hard to audit and easy to overload the context.
- **Karpathy-inspired skills** (236k). Tiny and cheap to load, aimed at real failure modes such as silent assumptions and over-building. No checks, no numbers, and no licence file.
- **Ponytail** (199k). Publishes its benchmark method with dates and tracks cost locally. Always loaded, and the benchmark is its own.
- **Addy Osmani's agent-skills** (120k). The clearest public test design among the code packs. Its trigger test matches words rather than meaning, as its own docs say, and there are no published behaviour results.

### Research

- **Graphify** (153k). A code graph that costs no model tokens, with benchmarks you can reproduce. One more index to keep fresh, and a paid tier.
- **Agent Reach** (115k). Many sources behind one command, with a health check per source. It can copy browser logins, and it installs from a remote file.
- **Understand Anything** (94k). Visual tours of a codebase and the impact of a diff before you commit. Expensive on the first run, and installed by piping a script into the shell.
- **Last 30 Days** (75k). A hard date window and a preview of what a run will read and write. Many dependencies, and opt-in cookie access.
- **REA** (479k). Reverse engineering with evidence attached to each finding. A narrow use for most developers, and no measured results.

### Tokens and workflow

- **Caveman** (123k). Many published measurements with sample sizes, and parts you can switch off. The full install adds a proxy and telemetry, and its own table shows that "say less" alone saves little over "answer concisely".
- **Claude-mem** (120k). Memory stored locally, with an index first and details on demand. A second agent spends tokens of its own, and telemetry is on by default.
- **Headroom** (81k). The most reproducible benchmark in this list. A proxy sits in front of the model, telemetry is on by default, and the gain on prose-heavy work is small.
- **GSD** (12k after a move; 64k on the archived original). Plans sized to fit a fresh context, with state on disk. Large agent prompts and a heavy process for small tasks.
- **BMAD Method** (56k). Shows only the step you need, and ships a test tool for skill authors. The name is trademarked with rules, and the persona style adds ceremony.

### Design

- **UI/UX Pro Max** (154k). A large catalogue of palettes and patterns that works offline. Nothing checks that the built UI follows it, and catalogue picks can look generic.
- **Taste** (122k). A real headless-browser check with clear results. Heavy dependencies, and aimed at marketing sites.
- **Archify** (100k). Checks diagrams before you see them, with sources pinned to a commit. Installs from remote instructions, and its update check calls out.
- **Impeccable** (117k). A real 62-rule design detector that can run in CI. It has telemetry, and a live mode that runs with the sandbox off.
- **PPT Master** (80k). Real editable slides, not pictures of slides. A high token cost by design.
- **Diagram Design** (73k). A clear privacy policy, with contrast and layout checks. One visual style by default.

## What I took away

- Most of these projects are instructions. Only a few ship code that checks the result.
- Published results are rare, and the useful ones are the ones that could have come out badly.
- Stars tell you how many people found a project, not what it changes.
- A "token saver" can spend tokens, or trust, somewhere else. Measure it on your own work.

## Sources

All read on 26 November 2026.

- Stacks: https://github.com/garrytan/gstack (and https://github.com/garrytan/gstack-evals), https://github.com/michael-denyer/pstack-claude (upstream: https://github.com/cursor/plugins/tree/main/pstack), https://github.com/t3dotgg/tstack
- Code: https://github.com/anthropics/skills, https://github.com/obra/superpowers, https://github.com/mattpocock/skills, https://github.com/affaan-m/ECC, https://github.com/multica-ai/andrej-karpathy-skills, https://github.com/DietrichGebert/ponytail, https://github.com/addyosmani/agent-skills
- Research: https://github.com/Graphify-Labs/graphify, https://github.com/Panniantong/Agent-Reach, https://github.com/Egonex-AI/Understand-Anything, https://github.com/mvanhorn/last30days-skill, https://github.com/morluto/rea
- Tokens and workflow: https://github.com/JuliusBrussee/caveman, https://github.com/thedotmack/claude-mem, https://github.com/headroomlabs-ai/headroom, https://github.com/open-gsd/gsd-core, https://github.com/bmad-code-org/BMAD-METHOD
- Design: https://github.com/nextlevelbuilder/ui-ux-pro-max-skill, https://github.com/Leonxlnx/taste-skill, https://github.com/tt-a1i/archify, https://github.com/pbakaus/impeccable, https://github.com/hugohe3/ppt-master, https://github.com/cathrynlavery/diagram-design
- Stars, licences and skill counts: the GitHub REST API.
