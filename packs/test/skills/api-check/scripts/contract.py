#!/usr/bin/env python3
"""Send one real request per route of an OpenAPI contract to a local API and compare the answers.

  contract.py --spec openapi.json --base-url http://localhost:8000
  contract.py --spec openapi.json --base-url http://127.0.0.1:8000 --param id=3 --write
  contract.py --spec openapi.json --base-url http://api.staging.test:8000 --allow-host api.staging.test

What is compared, per route (path + method):
  status   the answer has the success status the contract documents (the lowest 2xx code)
  shape    for a JSON answer with a documented schema: the top-level type, the required properties,
           and the type of each documented top-level property (for a list: of its first item)

Limits, stated so nobody reads more into a pass:
  - The contract file has to be OpenAPI 3 in JSON. YAML is not read: export JSON from the framework
    (many serve /openapi.json) or convert the file with a tool you already have.
  - Only GET, HEAD and OPTIONS are sent by default. POST, PUT, PATCH and DELETE change data and need --write.
  - Values for path and query parameters come from --param, then from examples and defaults in the
    contract. Without either, a placeholder is sent and the row says the value was guessed.
  - Nested objects are not checked below the top level. Latency, load and security are not checked.

Host rule: requests go only to localhost, 127.0.0.1 or ::1, or to a host named with --allow-host.
Any other host is refused before anything is sent. Redirects are not followed and proxies are not used.
The `servers` list in the contract is ignored. Header values are never printed.

Exit codes: 0 = pass: every route was requested and matched
            1 = fail: at least one mismatch; request, expected and actual are printed for each
            2 = blocked or not verified: host not allowed, contract unreadable or not JSON, server not
                reachable, no routes, or routes that were not requested (write methods without --write)
Results are also written to .mstack/api-check/ as JSON.
"""
import argparse
import datetime
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
METHODS = ("get", "head", "options", "post", "put", "patch", "delete")
SAFE = {"get", "head", "options"}
STATE = pathlib.Path(".mstack") / "api-check"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def resolve(node, spec, depth=0):
    """Follow local $ref pointers. Anything else is returned as it is."""
    while isinstance(node, dict) and "$ref" in node and depth < 30:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return {}
        target = spec
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            target = target.get(part, {}) if isinstance(target, dict) else {}
        node, depth = target, depth + 1
    return node if isinstance(node, dict) else {}


def flatten(schema, spec, depth=0):
    """Resolve $ref and merge allOf, one level deep, into a plain schema dict."""
    schema = resolve(schema, spec)
    if "allOf" in schema and depth < 10:
        merged = {k: v for k, v in schema.items() if k != "allOf"}
        merged.setdefault("properties", {})
        merged["properties"] = dict(merged["properties"])
        merged["required"] = list(merged.get("required", []))
        for part in schema["allOf"]:
            part = flatten(part, spec, depth + 1)
            merged["properties"].update(part.get("properties", {}))
            merged["required"] += [r for r in part.get("required", []) if r not in merged["required"]]
            merged.setdefault("type", part.get("type"))
        return merged
    return schema


def sample(schema, spec, depth=0):
    """A value for a schema: its example or default when given, else the smallest value of its type.
    Returns (value, guessed)."""
    schema = flatten(schema, spec)
    for key in ("example", "default"):
        if key in schema:
            return schema[key], False
    if schema.get("examples"):
        first = schema["examples"]
        return (first[0] if isinstance(first, list) else next(iter(first.values()))), False
    if schema.get("enum"):
        return schema["enum"][0], False
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    if kind == "object" or "properties" in schema:
        out = {}
        if depth < 5:
            for name in schema.get("required", []):
                out[name], _ = sample(schema.get("properties", {}).get(name, {}), spec, depth + 1)
        return out, True
    if kind == "array":
        return [], True
    if kind == "integer":
        return schema.get("minimum", 1), True
    if kind == "number":
        return schema.get("minimum", 1), True
    if kind == "boolean":
        return True, True
    if schema.get("format") == "uuid":
        return "00000000-0000-4000-8000-000000000000", True
    if schema.get("format") == "date":
        return "2000-01-01", True
    if schema.get("format") == "date-time":
        return "2000-01-01T00:00:00Z", True
    return "1", True


def type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def type_ok(value, schema, spec):
    schema = flatten(schema, spec)
    for key in ("oneOf", "anyOf"):
        if key in schema:
            return any(type_ok(value, option, spec) for option in schema[key])
    wanted = schema.get("type")
    if wanted is None:
        wanted = "object" if "properties" in schema else None
    if wanted is None:
        return True
    wanted = wanted if isinstance(wanted, list) else [wanted]
    actual = type_name(value)
    if actual == "null":
        return "null" in wanted or schema.get("nullable") is True
    return actual in wanted or (actual == "integer" and "number" in wanted)


def describe(schema, spec):
    schema = flatten(schema, spec)
    kind = schema.get("type") or ("object" if "properties" in schema else "any")
    kind = "/".join(kind) if isinstance(kind, list) else kind
    if kind == "object":
        need = ", ".join(f"{n} ({describe_short(schema.get('properties', {}).get(n, {}), spec)})" for n in schema.get("required", []))
        return "object" + (f" with required {need}" if need else "")
    if kind == "array":
        return "array of " + describe(schema.get("items", {}), spec)
    return kind


def describe_short(schema, spec):
    schema = flatten(schema, spec)
    kind = schema.get("type") or ("object" if "properties" in schema else "any")
    return "/".join(kind) if isinstance(kind, list) else kind


def shape_faults(value, schema, spec, where="body"):
    """Top-level comparison of a JSON value with a schema. Returns (faults, notes)."""
    schema = flatten(schema, spec)
    for key in ("oneOf", "anyOf"):
        if key in schema:
            results = [shape_faults(value, option, spec, where) for option in schema[key]]
            best = min(results, key=lambda r: len(r[0]))
            return best
    if not type_ok(value, schema, spec):
        return [f"{where} is {type_name(value)}, expected {describe_short(schema, spec)}"], []
    faults, notes = [], []
    if isinstance(value, dict):
        props = schema.get("properties", {})
        missing = [name for name in schema.get("required", []) if name not in value]
        if missing:
            faults.append(f"{where} lacks required: {', '.join(missing)}")
        for name, sub in props.items():
            if name in value and not type_ok(value[name], sub, spec):
                faults.append(f"{where}.{name} is {type_name(value[name])}, expected {describe_short(sub, spec)}")
        extra = [name for name in value if name not in props]
        if extra and props:
            if schema.get("additionalProperties") is False:
                faults.append(f"{where} has properties the contract forbids: {', '.join(extra)}")
            else:
                notes.append(f"{where} has undocumented properties: {', '.join(extra)}")
    elif isinstance(value, list) and where == "body":
        items = schema.get("items")
        if items is not None and value:
            sub_faults, sub_notes = shape_faults(value[0], items, spec, "body[0]")
            faults += sub_faults
            notes += sub_notes
        elif items is not None:
            notes.append("the list is empty, so the shape of its items was not checked")
    return faults, notes


def success_status(responses):
    codes = sorted(c for c in responses if str(c).isdigit())
    twos = [c for c in codes if str(c).startswith("2")]
    if twos:
        return twos[0]
    if any(str(c).upper() == "2XX" for c in responses) or "default" in responses:
        return "2XX"
    return codes[0] if codes else "2XX"


def json_schema_of(response, spec):
    content = resolve(response, spec).get("content", {})
    for media, body in content.items():
        if "json" in media.lower():
            return body.get("schema"), media
    return None, (next(iter(content), None))


def build_operations(spec):
    ops = []
    for path, item in spec.get("paths", {}).items():
        item = resolve(item, spec)
        shared = [resolve(p, spec) for p in item.get("parameters", [])]
        for method in METHODS:
            if isinstance(item.get(method), dict):
                op = item[method]
                params = {(p.get("in"), p.get("name")): p for p in shared}
                params.update({(p.get("in"), p.get("name")): p for p in (resolve(q, spec) for q in op.get("parameters", []))})
                ops.append({"method": method, "path": path, "op": op, "params": list(params.values())})
    return ops


def param_value(param, overrides, spec):
    name = param.get("name")
    if name in overrides:
        return overrides[name], False
    if "example" in param:
        return param["example"], False
    if param.get("examples"):
        first = resolve(next(iter(param["examples"].values())), spec)
        if "value" in first:
            return first["value"], False
    return sample(param.get("schema", {}), spec)


def send(opener, method, url, headers, body, timeout):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method.upper())
    for key, value in headers.items():
        request.add_header(key, value)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with opener.open(request, timeout=timeout) as answer:
            return answer.status, answer.headers.get("Content-Type", ""), answer.read(2_000_000)
    except urllib.error.HTTPError as answer:
        return answer.code, answer.headers.get("Content-Type", ""), answer.read(2_000_000)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", type=pathlib.Path, required=True, help="the OpenAPI 3 contract, as a JSON file")
    parser.add_argument("--base-url", required=True, help="where the API runs, for example http://localhost:8000")
    parser.add_argument("--allow-host", action="append", default=[], metavar="HOST",
                        help="a host other than localhost that is a test server you own; repeat for more. Never production")
    parser.add_argument("--write", action="store_true", help="also send POST, PUT, PATCH and DELETE (they change data on the server)")
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE", help="value for a path or query parameter, for example id=3")
    parser.add_argument("--header", action="append", default=[], metavar="NAME: VALUE", help="a header to send with every request (the value is not printed)")
    parser.add_argument("--only", action="append", default=[], metavar="'GET /path'", help="check only this route; repeat for more")
    parser.add_argument("--timeout", type=float, default=10, help="seconds to wait per request (default 10)")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder for the results file (default: current folder)")
    args = parser.parse_args()

    url = urllib.parse.urlsplit(args.base_url)
    host = (url.hostname or "").lower()
    if url.scheme not in ("http", "https") or not host:
        print(f"blocked: --base-url '{args.base_url}' is not an http or https address")
        return 2
    if host not in LOCAL_HOSTS and host not in {h.lower() for h in args.allow_host}:
        print(f"blocked: host '{host}' is not localhost. Nothing was sent. If it is a test server you own, "
              f"run again with --allow-host {host}. Do not point this at production")
        return 2

    if args.spec.suffix.lower() in (".yaml", ".yml"):
        print(f"blocked: {args.spec.name} is YAML. This script reads OpenAPI as JSON only; export or convert the contract to JSON")
        return 2
    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"blocked: cannot read the contract: {exc}")
        return 2
    except ValueError as exc:
        print(f"blocked: {args.spec} is not valid JSON ({exc}). This script reads OpenAPI as JSON only")
        return 2
    if not isinstance(spec, dict) or not str(spec.get("openapi", "")).startswith("3"):
        found = spec.get("swagger") if isinstance(spec, dict) else None
        print("blocked: the contract is not OpenAPI 3" + (f" (it says swagger {found})" if found else " (no `openapi: 3.x` field)"))
        return 2
    operations = build_operations(spec)
    if args.only:
        wanted = {" ".join(o.split()).lower() for o in args.only}
        operations = [o for o in operations if f"{o['method']} {o['path']}".lower() in wanted]
    if not operations:
        print("RESULT not verified: the contract has no routes" + (" matching --only" if args.only else ""))
        return 2

    overrides, headers = {}, {}
    for text in args.param:
        name, sep, value = text.partition("=")
        if not sep:
            print(f"blocked: --param '{text}' is not in the form name=value")
            return 2
        overrides[name] = value
    for text in args.header:
        name, sep, value = text.partition(":")
        if not sep:
            print(f"blocked: --header needs the form 'Name: value'")
            return 2
        headers[name.strip()] = value.strip()

    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
    base = args.base_url.rstrip("/")
    rows, reached = [], False
    print(f"contract: {args.spec}  ({len(operations)} route(s))   target: {base}" + (f"   headers sent: {', '.join(headers)}" if headers else ""))
    for item in operations:
        method, path, op = item["method"], item["path"], item["op"]
        label = f"{method.upper()} {path}"
        row = {"route": label, "result": "", "request": "", "expected": "", "actual": "", "notes": []}
        rows.append(row)
        if method not in SAFE and not args.write:
            row["result"] = "skipped"
            row["notes"].append("changes data; not sent without --write")
            continue
        real_path, query = path, {}
        for param in item["params"]:
            where, name = param.get("in"), param.get("name")
            if where == "path" or (where == "query" and (param.get("required") or name in overrides)):
                value, guessed = param_value(param, overrides, spec)
                if guessed:
                    row["notes"].append(f"{where} parameter {name} had no example; sent '{value}' (pass --param {name}=<value>)")
                if where == "path":
                    real_path = real_path.replace("{" + name + "}", urllib.parse.quote(str(value), safe=""))
                else:
                    query[name] = value
            elif where == "header" and param.get("required") and name not in headers and name.lower() not in {h.lower() for h in headers}:
                row["notes"].append(f"required header {name} was not given (pass --header)")
        if "{" in real_path:
            row["result"] = "error"
            row["notes"].append("a path parameter is not declared in the contract, so no request could be built")
            continue
        body = None
        if method in ("post", "put", "patch"):
            content = resolve(op.get("requestBody", {}), spec).get("content", {})
            media = next((m for m in content if "json" in m.lower()), None)
            if media:
                entry = content[media]
                if "example" in entry:
                    body = entry["example"]
                elif entry.get("examples"):
                    body = resolve(next(iter(entry["examples"].values())), spec).get("value")
                else:
                    body, guessed = sample(entry.get("schema", {}), spec)
                    if guessed:
                        row["notes"].append("the request body was built from the schema, not from an example")
        target = base + real_path + ("?" + urllib.parse.urlencode(query) if query else "")
        row["request"] = f"{method.upper()} {target}" + (f"  body {json.dumps(body)[:300]}" if body is not None else "")

        responses = op.get("responses", {})
        want = success_status(responses)
        schema, media = json_schema_of(responses.get(want, responses.get("default", {})), spec) if responses else (None, None)
        row["expected"] = f"status {want}" + (f", {media} body: {describe(schema, spec)}" if schema is not None else (f", {media}" if media else ""))
        try:
            status, content_type, raw = send(opener, method, target, headers, body, args.timeout)
            reached = True
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            if not reached:
                print(f"RESULT not verified: no answer from {base} ({reason}). Is the API running? Start it and run again")
                return 2
            row["result"], row["actual"] = "error", f"no answer: {reason}"
            continue
        faults = []
        if not (str(status) == str(want) or (want == "2XX" and 200 <= status < 300)):
            documented = " (documented, but it is not the success answer)" if str(status) in responses else " (not documented for this route)"
            faults.append(f"status {status}{documented}")
        elif schema is not None and method != "head":
            if "json" not in content_type.lower():
                faults.append(f"content type is '{content_type or 'none'}', expected {media}")
            else:
                try:
                    value = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    faults.append("body is not valid JSON")
                else:
                    shape, notes = shape_faults(value, schema, spec)
                    faults += shape
                    row["notes"] += notes
        elif schema is None and str(want).startswith("2") and str(want) != "204" and method != "head":
            row["notes"].append("no JSON schema documented for the success answer; only the status was compared")
        preview = raw[:200].decode("utf-8", "replace").replace("\n", " ")
        row["actual"] = f"status {status}, {content_type or 'no content type'}" + ("; " + "; ".join(faults) if faults else "") + (f"; body starts: {preview}" if faults and preview else "")
        row["result"] = "MISMATCH" if faults else "ok"

    print()
    for row in rows:
        print(f"  {row['result']:9} {row['route']}")
        for note in row["notes"]:
            print(f"            note: {note}")
    mismatches = [r for r in rows if r["result"] == "MISMATCH"]
    for row in mismatches:
        print(f"\nMISMATCH {row['route']}")
        print(f"  request:  {row['request']}")
        print(f"  expected: {row['expected']}")
        print(f"  actual:   {row['actual']}")

    folder = args.root.resolve() / STATE
    folder.mkdir(parents=True, exist_ok=True)
    ignore = folder.parent / ".gitignore"
    listed = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if "api-check/\n" not in listed:
        ignore.write_text(listed + "api-check/\n", encoding="utf-8")
    out = folder / f"results-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    n = 1
    while out.exists():
        n += 1
        out = folder / f"results-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{n}.json"
    out.write_text(json.dumps({"contract": str(args.spec), "target": base, "rows": rows}, indent=2) + "\n", encoding="utf-8")

    count = {k: sum(1 for r in rows if r["result"] == k) for k in ("ok", "MISMATCH", "skipped", "error")}
    print(f"\nroutes: {len(rows)}   ok {count['ok']}   mismatch {count['MISMATCH']}   skipped {count['skipped']}   error {count['error']}   results: {out}")
    if mismatches:
        print(f"RESULT fail: {len(mismatches)} of {len(rows)} route(s) do not match the contract")
        return 1
    if count["skipped"] or count["error"]:
        print(f"RESULT not verified: {count['skipped'] + count['error']} route(s) were not requested"
              + (" (write methods need --write)" if count["skipped"] else ""))
        return 2
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
