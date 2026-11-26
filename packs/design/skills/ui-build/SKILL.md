---
name: ui-build
description: Builds a new screen, or reworks one that looks generic, so it fits this product: a short written direction first, then the build, a lint for unfinished work and default-look traits, and at most three render-and-inspect rounds. Use when the user asks to build, make or redesign a page, landing page, dashboard or component, or says the UI looks like every AI template. Not for checking a finished page (use design-review) or copying a mockup exactly (use ui-match).
license: MIT
metadata:
  pack: design
  version: 0.3.0
  needs: python3, a browser the agent can drive for the render step
---

# UI build

Produces a screen built from the product's own parts, a lint result with no unfinished work, and a record of each render round.

## Done when

- A direction of five lines or fewer was written to `.mstack/ui-build/direction.md` and the user agreed to it (open briefs only).
- `scripts/lint_ui.py lint` on the changed files exits 0. Default-look warnings may remain if the brief asked for them.
- The screen was rendered and looked at, at phone and desktop width, and each round is recorded with `scripts/lint_ui.py round` (three at most).
- No proof was invented: user counts, ratings, logos and quotes come from the user or are marked placeholders listed in the report.

End in exactly one state: **pass**, **fail** (blocking lint lines remain), **not verified** (the screen could not be rendered; say so), or **blocked** (waiting for the user's answer on the direction, or three rounds used).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A way to render | the dev server starts, or the host browser tool opens the file | build and lint anyway, end as not verified |

## Steps

The script is `scripts/lint_ui.py` in this skill's folder.

1. **Triage an existing screen.** Look at it rendered. Decide: heavy rework, light pass, or leave it. A screen that works is left alone and the skill ends as pass with that reason.
2. **Read what exists.** Tokens, components, fonts, the product's own pages. Build from these first.
3. **Write the direction** (open briefs only): who uses the screen, its one main job, the type and colour taken from the product, one thing that makes it this product's screen, and what it will not do. Ask whether it is the default any brief of this kind would get; if so, rewrite it. Show it and wait for a yes.
4. **Build.** Real labels and data shapes. Every state the screen has: empty, loading, error, long text.
5. **Lint.**
   ```
   python3 scripts/lint_ui.py lint src/pages/orders
   ```
   Each line gives a rule id, the file and line, and a one-line reason. `BLOCK` is unfinished work: filler text, TODO markers, placeholder copy, stand-in names (Acme, John Doe, Your Company), placeholder image services, example.com links, invented proof, dead handlers and links, removed focus outlines. Fix every one. `warn` is a default look: stock gradients and brand colours, stock hero phrases and calls to action, glass, glow and blurred blobs, sparkle and emoji icons, everything centred, the same card or icon tile repeated, same-length card copy, too many font weights, skipped heading levels. Read the warnings against the brief; keep a trait only if the brief wants it. The list and its thresholds are dated (`references/default-looks.json`).
6. **Render and inspect**, phone and desktop width. Record the round:
   ```
   python3 scripts/lint_ui.py round --note "320 px: header wraps; 1440 px: fine" --screenshot shots/r1-320.png
   ```
   Fix, then repeat. The fourth round is refused: list what is still wrong and ask.
7. **Hand over** to `design-review` if it is installed; otherwise say the page has not been gated.
8. **Report.** End state, the direction, lint counts, rounds used, placeholders that need real content.

## Rules

- The brief and the product win over any list of looks. Warnings are taste; they never block.
- Never invent testimonials, customer logos, user counts, ratings or percentages. Use a visible placeholder and list it.
- Reuse before adding: an existing component or token beats a new one.
- Reading the code is not inspecting the screen. Without a render the result is not verified.

## Not for

- Gating a finished page before release → use `design-review`.
- Reproducing a screenshot or mockup and measuring the match → use `ui-match`.
- Fixing the words only → use `ui-copy`.

## Level

- beginner: explain the direction step and why the lint flags each item.
- standard: as written.
- expert: the direction, lint counts and round notes only. Lint, render and the round limit still apply.
