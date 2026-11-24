---
name: api-check
description: Compares a running API with its OpenAPI contract by sending one real request per route and printing request, expected and actual for every status or response shape that does not match. Use when the user asks whether the API matches the spec or openapi.json, after endpoints changed, or before a client is built against them. Local or test servers only. Not for driving a web page (use qa-run) or for load and latency targets (use nfr-budgets).
license: MIT
metadata:
  pack: test
  version: 0.2.1
  needs: python3, a running local or test server, an OpenAPI 3 contract in JSON
---

# API check

Produces one result row per route in `.mstack/api-check/results-<time>.json`, and a printed request, expected and actual for each mismatch.

## Done when

- `contract.py` sent a request for every route in the contract, or each route it did not send is listed with the reason.
- Every mismatch is shown with its request, expected result and actual result, as the script printed them.
- No request went to a host other than localhost or a host the user named as a test server.

End in exactly one state: **pass**, **fail** (mismatches), **not verified** (routes not requested, server not reachable; say which), or **blocked** (YAML contract, host not allowed, no server; say what is needed).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The contract as OpenAPI 3 JSON | The file starts with `{` and has `"openapi": "3...` | YAML is not read. Ask the user for a JSON export (many frameworks serve `/openapi.json`). End as blocked |
| A running server | The script says "no answer" otherwise | ask how to start it; `server.py` from `qa-run` can start it if installed. End as blocked |
| A host that is local or a test server | localhost, 127.0.0.1, ::1; anything else needs the user to name it | end as blocked; never production |

## Steps

The script is `scripts/contract.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/contract.py"`.

1. **Check needs.** Confirm with the user which server the base URL points at, and that it holds test data.
2. **Run the read routes.**
   ```
   python3 scripts/contract.py --spec openapi.json --base-url http://localhost:8000
   ```
   GET, HEAD and OPTIONS are sent. Routes that change data are listed as skipped.
3. **Supply real values.** A `note:` that a parameter was guessed means the request may hit a missing record. Pass known ids: `--param id=3`. For routes behind a login, pass a test token with `--header "Authorization: Bearer <test token>"`; take it from the project's seed or example config, never a real user's.
4. **Write routes, only with a yes.** POST, PUT, PATCH and DELETE change data on the server. Ask the user, naming the server. Then add `--write`.
5. **Read each mismatch.** The fault can be in the server or in the contract. Say which you think it is and why, from the printed request and answer; do not change either here.
6. **Report.** End state first. Then each mismatch with request, expected and actual as printed, the routes not requested and why, the notes about guessed values, and the results file.

## Rules

- Requests go only to localhost or to a host the user named with `--allow-host`. The script refuses others before sending anything. The `servers` list in the contract is ignored.
- Never use `--allow-host` for a production host, even if the user says it is read only.
- Write methods are sent only after the user said yes for that server.
- The check covers status and top-level shape. Say so: a pass does not prove nested fields, error answers, speed or security.
- A route skipped or unreachable is not a pass.
- Token values are never written into the reply or the report.

## Not for

- Clicking through a web page → use `qa-run`.
- Response times, throughput and error budgets → use `nfr-budgets`.
- Writing the contract → use `spec`.
- Finding out why an endpoint returns the wrong thing → use `debug`.
- A security review of the API → use `secure`.

If a named skill is not installed, say so and stop at the report.

## Level

- beginner: explain what the contract is and what each mismatch line means.
- standard: as written.
- expert: the reply is the end state, the mismatches and the routes not requested. Every route is still requested or listed.
