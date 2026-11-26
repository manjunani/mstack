---
name: post-check
description: Checks a draft post against one platform's limits: characters counted the platform's way (X, a Mastodon toot, Bluesky, LinkedIn), too many hashtags or links, blog front matter and images, and anything still marked [unverified] or TODO. Use when the user asks "is this tweet under the limit", "too many hashtags?", "count the characters in this toot", or whether a draft is ready to post. Not for whether the claims are true (use claim-check) or links that still work (use link-check).
license: MIT
metadata:
  pack: growth
  version: 0.3.0
  needs: python3
---

# Post check

Produces a pass or fail per platform for one draft, with the counted length, and never publishes anything.

## Done when

- `scripts/postcheck.py` ran once per target platform on the saved draft and ended with a `RESULT` line.
- The reply repeats the script's line that the limits are unverified and have to be checked on the platform before posting.
- Any marker such as `[unverified]`, `[citation needed]`, TODO or `{{placeholder}}` is gone, or the result is fail.

End in exactly one state: **pass**, **fail** (over a limit, a missing image or front matter key, a marker left), **not verified** (remote images not opened), or **blocked** (no draft, unknown platform).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The draft as a file | the path exists | save the text the user gave to a new file under `.mstack/growth/` and check that |
| The target platforms | the user named them | `python3 scripts/postcheck.py --list` and ask |

## Steps

The script is `scripts/postcheck.py` in this skill's folder; in Claude Code `"${CLAUDE_SKILL_DIR}/scripts/postcheck.py"`.

1. **One file per platform.** Different platforms need different drafts; check each against its own entry.
2. **Run.**
   ```
   python3 scripts/postcheck.py draft-x.md --platform x --need-link
   python3 scripts/postcheck.py post.md --platform blog --root site/static
   ```
3. **Read the output.** Failures are hard limits; warnings are guidance (hashtag counts, title length). The fold note shows roughly what a reader sees before "see more".
4. **Shorten or fix** in a new file if the user wants changes; never overwrite their draft. Run again.
5. **Check claims.** If the post holds numbers, superlatives or quotes, run `claim-check` on it too.
6. **Report.** End state per platform, the length counted, then not checked (links answering, platform content rules).

## Rules

- This skill stops at a checked draft. Posting, scheduling and sending are the user's action.
- No fake reviews, invented numbers, or mass unsolicited posting or messaging. A draft that needs one of those fails here.
- Limits in `references/platforms.json` are dated and unverified. If a check passes by a few characters, tell the user to confirm the limit on the platform.

## Not for

- Whether a number or quote in the post is backed → use `claim-check`.
- Grammar and style → use `copyedit`.
- Words on buttons and screens in an app → use `ui-copy`.

## Level

- beginner: explain how the platform counts characters and why links count as a fixed length.
- standard: as written.
- expert: end state and counted length per platform only. Every check still runs.
