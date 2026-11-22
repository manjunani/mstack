#!/bin/sh
# Exercise the api-check script against a tiny local server (api_server.py, Python http.server).
# Arguments: path to packs/test, path of a NEW folder to create (outside temporary folders).
PACK=$(cd "$1" && pwd); P="$2"
[ -e "$P" ] && { echo "refusing: $P already exists"; exit 9; }
. "$PACK/tests/scripts/lib.sh"
C="$PACK/skills/api-check/scripts/contract.py"
mkdir -p "$P" && cd "$P" || exit 9
P=$(pwd)

cat > good.json <<'EOF'
{
  "openapi": "3.0.3",
  "info": {"title": "users", "version": "1"},
  "servers": [{"url": "https://api.example.com"}],
  "paths": {
    "/users": {
      "get": {"responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/User"}}}}}}},
      "post": {
        "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/NewUser"}}}},
        "responses": {"201": {"description": "created", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/User"}}}},
                      "422": {"description": "invalid"}}
      }
    },
    "/users/{id}": {
      "parameters": [{"name": "id", "in": "path", "required": true, "schema": {"type": "integer"}, "example": 1}],
      "get": {"responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/User"}}}},
                            "404": {"description": "missing"}}},
      "delete": {"responses": {"204": {"description": "gone"}}}
    },
    "/search": {
      "get": {"parameters": [{"name": "q", "in": "query", "required": true, "schema": {"type": "string"}}],
              "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "object", "required": ["hits"], "properties": {"hits": {"type": "array"}, "query": {"type": "string"}}}}}}}}
    }
  },
  "components": {"schemas": {
    "User": {"allOf": [{"$ref": "#/components/schemas/NewUser"}, {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}]},
    "NewUser": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string", "example": "Grace"}, "email": {"type": "string"}}}
  }}
}
EOF
cat > bad.json <<'EOF'
{
  "openapi": "3.1.0",
  "info": {"title": "broken promises", "version": "1"},
  "paths": {
    "/users": {"get": {"responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "array", "items": {"type": "object", "required": ["id", "phone"], "properties": {"id": {"type": "string"}}}}}}}}}},
    "/orders": {"get": {"responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "object", "required": ["items", "total"], "properties": {"items": {"type": "array"}, "total": {"type": "integer"}}}}}}}}},
    "/health": {"get": {"responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "object"}}}}}}},
    "/report": {"get": {"responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "object"}}}}}}},
    "/old": {"get": {"responses": {"200": {"description": "ok"}}}},
    "/strict": {"get": {"responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": false, "properties": {"id": {"type": "integer"}}}}}}}}},
    "/nowhere": {"get": {"responses": {"200": {"description": "ok"}}}}
  }
}
EOF
printf 'openapi: 3.0.3\npaths: {}\n' > spec.yaml
printf '{"swagger": "2.0", "paths": {}}\n' > old.json
printf '{"openapi": "3.0.0", "paths": {}}\n' > empty.json
printf 'not json at all\n' > broken.json

PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
URL="http://127.0.0.1:$PORT"

echo "#### refusals before any request"
t 2 "a public host is refused" python3 "$C" --spec good.json --base-url https://api.example.com
has "Nothing was sent" "says that nothing was sent"
t 2 "a private network address is refused too without the flag" python3 "$C" --spec good.json --base-url http://10.0.0.5:8000
t 2 "not an http address" python3 "$C" --spec good.json --base-url ftp://localhost/x
t 2 "YAML is not read" python3 "$C" --spec spec.yaml --base-url "$URL"
has "JSON only" "says JSON only"
t 2 "Swagger 2 is not read" python3 "$C" --spec old.json --base-url "$URL"
t 2 "a contract that is not JSON" python3 "$C" --spec broken.json --base-url "$URL"
t 2 "a contract with no routes" python3 "$C" --spec empty.json --base-url "$URL"
t 2 "missing contract file" python3 "$C" --spec nope.json --base-url "$URL"
t 2 "the server is not running yet" python3 "$C" --spec good.json --base-url "$URL"
has "Is the API running" "says the server gave no answer"

python3 "$PACK/tests/scripts/api_server.py" "$PORT" "$P/requests.log" &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
python3 - "$PORT" <<'EOF'
import socket, sys, time
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1).close(); break
    except OSError:
        time.sleep(0.1)
EOF

echo "#### a matching contract"
t 2 "read routes match; write routes were not sent, so not verified" python3 "$C" --spec good.json --base-url "$URL" --param q=ada
has "ok        GET /users" "list route"
has "ok        GET /users/{id}" "path parameter from the example"
has "skipped   POST /users" "write route is skipped"
has "skipped   DELETE /users/{id}" "delete is skipped"
t 0 "no write request reached the server" sh -c "! grep -E '^(POST|DELETE)' requests.log"
t 0 "the servers list of the contract was ignored: only local requests" sh -c "grep -c '^GET' requests.log"
t 0 "with --write every route is requested and matches" python3 "$C" --spec good.json --base-url "$URL" --param q=ada --write
t 0 "the POST body was built from the schema and its example" grep -q 'POST /users auth=no body={"name": "Grace"}' requests.log
t 0 "the DELETE was really sent" grep -q '^DELETE /users/1' requests.log
t 1 "an id that does not exist: documented 404 is still not the success answer" python3 "$C" --spec good.json --base-url "$URL" --param id=999 --param q=x --only "GET /users/{id}"
has "request:  GET $URL/users/999" "prints the request"
has "expected: status 200" "prints what was expected"
has "actual:   status 404" "prints what came back"
has "documented, but it is not the success answer" "explains the 404"
t 0 "a guessed query value is reported as guessed" python3 "$C" --spec good.json --base-url "$URL" --only "GET /search"
has "query parameter q had no example" "names the parameter"
t 0 "a header is sent and its value is not printed" python3 "$C" --spec good.json --base-url "$URL" --only "GET /users" --header "Authorization: Bearer test-token-123"
lacks "test-token-123" "the token is not in the output"
t 0 "the header reached the server" grep -q "GET /users auth=yes" requests.log

echo "#### a contract the server breaks"
t 1 "seven routes, seven mismatches" python3 "$C" --spec bad.json --base-url "$URL"
has "mismatch 7" "all seven are counted"
has "body[0].id is integer, expected string" "wrong type inside a list item"
has "body[0] lacks required: phone" "missing required property in a list item"
has "body.items is string, expected array" "wrong type of a top-level property"
has "body lacks required: total" "missing required property"
has "actual:   status 204" "wrong status"
has "content type is 'text/html', expected application/json" "wrong content type"
has "actual:   status 302" "a redirect is reported, not followed"
has "body has properties the contract forbids: debug" "forbidden extra property"
has "status 404 (not documented for this route)" "route missing on the server"
t 0 "the redirect to another host was not followed: one request for /old, none elsewhere" sh -c "[ \"\$(grep -c '^GET /old' requests.log)\" = 1 ] && ! grep -q moved requests.log"
t 0 "results were written as JSON with one row per route" python3 -c "
import json, glob, os
rows = json.load(open(max(glob.glob('.mstack/api-check/results-*.json'), key=os.path.getmtime)))['rows']
assert len(rows) == 7 and all(r['result'] == 'MISMATCH' and r['request'] and r['expected'] and r['actual'] for r in rows)
"

echo "#### allow flag"
t 2 "another name for this machine is refused without the flag" python3 "$C" --spec good.json --base-url "http://0.0.0.0:$PORT" --only "GET /users"
t 0 "and accepted with --allow-host" python3 "$C" --spec good.json --base-url "http://0.0.0.0:$PORT" --allow-host 0.0.0.0 --only "GET /users"

kill $SERVER 2>/dev/null
finish
