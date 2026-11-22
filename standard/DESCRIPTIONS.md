# Writing a description

The description is the most important line in a skill. The model sees only the name and description of every installed skill, and from those decides whether to start one. A good skill with a weak description never runs.

In a study of 10,579 public skills, about 55% had no wording that says when to use them.

## The shape

Three parts, in this order:

```
<What it does, as a result the user gets>. Use when <situations, in words a user would type>. Not for <the nearest other job> (use <that skill>).
```

Example:

```
description: Prove a WebXR page works without a headset: starts a session in an emulator, takes a screenshot for each head pose and reports frame cost. Use when a WebXR or VR page was built or changed, or the user asks whether it works on Quest. Not for plain three.js pages with no XR session (use three-verify).
```

## Rules

1. **Put the trigger early.** The first 200 characters must contain what the skill does and the main "use when". Long lists get cut off in some tools.
2. **Use the user's words, not yours.** Write "the tests fail sometimes", not "intermittent test nondeterminism". Include the nouns people really type: file types (`.glb`, `.srt`), tool names (ffmpeg, Playwright), and plain phrases ("is it done", "delete the old folder").
3. **Say the result, not the topic.** "Checks every colour pair for contrast" tells the model what it will get. "Design tokens" does not.
4. **Name the neighbour.** Every description ends with what the skill is not for and which skill handles that. This is what stops two skills answering the same request.
5. **No pressure words.** No "always", "must", "critical", "before anything else". They make a skill start on requests it does not fit.
6. **Third person, present tense.** "Finds", "checks", "writes". Not "I will" or "You should".
7. **Length:** 250 to 600 characters. The hard limit of the open standard is 1,024.
8. **One job in the first sentence.** If the first sentence needs "and" between two different results, split the skill.

## Checking a description

Before a skill is accepted:

1. Write ten requests where the skill should start. Use different wording in each; at least three must not contain the skill's name or its main keyword.
2. Write ten requests where it should stay quiet. At least five must be near misses: requests that belong to the neighbouring skill.
3. Run them (see `TESTS.md`). Pass mark: starts on at least 8 of the first ten, and on at most 1 of the second ten.
4. Run the collision check: no other mstack skill may claim the same "use when".

If a description fails, change the description, not the test requests.

## Names

- Lower case, words joined by hyphens, at most three words.
- A verb or a plain noun for the job: `verify`, `flaky-triage`, `gltf-gate`.
- Avoid words that mean something else in common use. "Interview" mostly means a job interview; the mstack skill is called `clarify`.
- Unique across all mstack packs.
