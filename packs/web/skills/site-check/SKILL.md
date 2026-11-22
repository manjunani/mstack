---
name: site-check
description: Checks how a deployed address answers: every redirect hop, the final status, security and cache headers, certificate expiry and mixed content, each marked ok, warn, failed or not checked. Use when a site was just deployed or moved, the user asks "is the site up", "is https set up right", "why does it redirect", or a header or certificate warning came in. Not for confirming a new release is the running version (use deploy-check) or for broken links across pages (use link-check).
license: MIT
metadata:
  pack: web
  version: 0.1.0
  needs: python3
---

# Site check

Produces one line per check for one address the user named, from requests the script made just now.

## Done when

- `scripts/site_check.py` ran on the address the user gave and printed its `RESULT` line.
- Every failed line is quoted in the reply with its detail; every "not checked" line is named with its reason.
- Nothing is called fine that the script marked skip.

End in exactly one state: **pass**, **fail**, **not verified** (no answer, or the certificate could not be read), or **blocked** (bad address, missing file, a decision from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The address | the user named it | ask for it; do not guess a domain |

## Steps

The script is `scripts/site_check.py` in this skill's folder (`"${CLAUDE_SKILL_DIR}/scripts/site_check.py"` in Claude Code).

1. **Check needs.**
2. **Run it on the address as the user gave it**, including `http://` if they gave that, so the redirect to https is checked too.
   ```
   python3 scripts/site_check.py https://example.org/
   python3 scripts/site_check.py http://example.org/ --json site-check.json
   ```
   Options: `--expect-status 401` for a page that should ask for a login; `--require content-security-policy` to make an advised header required; `--require-https` for a local server that should already be https; `--ca-file` for a staging site signed by a private authority.
3. **Read the output, not the exit code alone.** The hop list shows each redirect. `FAIL` lines decide the result. `warn` lines are advice. `skip` lines were not checked.
4. **Check one finding by hand** when it surprises you, for example by running the script again on the final address the hops show.
5. **Report.** End state first. Then the failed checks with their details, then warnings, then what was not checked and why. If the limits file printed an "unverified" note, say the thresholds are mstack defaults, not a standard.

## Rules

- Only the address the user named and the redirects it gives. No path guessing, no probing for hidden files or admin pages; that is security testing and is not done here.
- Thresholds (certificate days, HSTS age, which headers are required) live in `references/checks.json`, dated. Do not quote them as standards; several are marked unverified.
- A plain-http local server is normal during development; the script marks https as not checked there unless `--require-https` is given.
- The script does not sign in, does not retry a refusal and does not change its user agent.

## Not for

- Is the new version live and healthy after a deploy → use `deploy-check`.
- Broken links and missing images across a site → use `link-check`.
- Load time and transfer size → use `page-speed`.
- Search-engine audit of titles and sitemaps → use `site-audit`.

## Level

- beginner: explain each header in one sentence and why a missing one matters.
- standard: as written.
- expert: the failed and not-checked lines and the end state only. Every check still runs.
