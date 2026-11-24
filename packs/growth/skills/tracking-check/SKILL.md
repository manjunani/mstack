---
name: tracking-check
description: Reads a HAR file or network capture and confirms each expected analytics event was sent with the right name and properties, flagging doubles, error answers and emails in URLs. Use when sign_up, signup, purchase or checkout events are not showing, fire twice or carry wrong properties in analytics, or the user shares a HAR or network capture to check. Not for adding a tracking tag or counting sign-ups, or for measuring page load (use page-speed).
license: MIT
metadata:
  pack: growth
  version: 0.2.2
  needs: python3, a network capture the user made
---

# Tracking check

Produces one line per expected event: sent with the right name and properties, missing, doubled, or refused.

## Done when

- The user captured the network requests while doing the action (a HAR export, or a list of requests).
- `scripts/tracking.py` ran on that capture with an expected-events file and ended with a `RESULT` line.
- The reply says that sent is not arrived: whether events reached the account was not checked.

End in exactly one state: **pass**, **fail** (an event missing, doubled, with wrong properties, refused, or personal data in an address), **not verified**, or **blocked** (no capture, or the capture is empty).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A capture of the action | a `.har` or `.json` file exists and holds requests | tell the user how: open the browser's network panel, keep the log, do the action, export as HAR; end as blocked |
| The expected events | names and properties from the user or the tracking plan | ask; do not guess event names |

## Steps

The script is `scripts/tracking.py` in this skill's folder; in Claude Code `"${CLAUDE_SKILL_DIR}/scripts/tracking.py"`.

1. **Write the expected file** with the user, under `.mstack/growth/expect.json`:
   ```json
   {"endpoint": "analytics.their-site.tld/collect",
    "events": [{"name": "sign_up", "properties": {"plan": "pro", "method": "*"}, "count": 1}]}
   ```
   Fire on confirmed success (the thank-you state), not on the click.
2. **Run.**
   ```
   python3 scripts/tracking.py capture.har --expect .mstack/growth/expect.json
   ```
3. **Read the output.** Doubled events usually mean the tag is installed twice or fires on click and on success. Status 0 usually means a blocker stopped it. Email addresses are masked in the output.
4. **Report.** End state first, then each event, then personal-data findings, then not checked (arrival in the account, other browsers, consent).

## Rules

- Captures may hold cookies and personal data. Do not paste their contents into the reply; quote only the masked lines the script prints.
- Personal data in a request address is a fail even if the analytics vendor accepts it.
- Changing a live analytics or ad account is not part of this skill; propose the change and let the user make it.

## Not for

- Load time and what the page downloads → use `page-speed`.
- Whether the site answers and its headers → use `site-check`.
- A whole test pass of a user flow → use `verify`.

## Level

- beginner: explain how to export a HAR file and what an event endpoint is.
- standard: as written.
- expert: event table and end state only. Every check still runs.
