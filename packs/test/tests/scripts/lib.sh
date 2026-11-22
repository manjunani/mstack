# Shared helpers for the mstack-test script tests. Source this file; do not run it.
#
#   t <expected exit> "<label>" command [args...]   run a case, compare the exit code
#   has "<text>" "<label>"                          the output of the last case contains the text
#   lacks "<text>" "<label>"                        the output of the last case does not contain the text
#   finish                                          print the totals; return 1 when any case failed
PASSED=0
FAILED=0
LAST=""

t() {
  want="$1"; label="$2"; shift 2
  LAST=$("$@" 2>&1); got=$?
  if [ "$got" = "$want" ]; then
    PASSED=$((PASSED + 1)); echo "ok   [exit $got] $label"
  else
    FAILED=$((FAILED + 1)); echo "FAIL [exit $got, expected $want] $label"
    printf '%s\n' "$LAST" | tail -12 | sed 's/^/     | /'
  fi
}

has() {
  if printf '%s\n' "$LAST" | grep -qF -- "$1"; then
    PASSED=$((PASSED + 1)); echo "ok   [text] $2"
  else
    FAILED=$((FAILED + 1)); echo "FAIL [text missing: $1] $2"
    printf '%s\n' "$LAST" | tail -12 | sed 's/^/     | /'
  fi
}

lacks() {
  if printf '%s\n' "$LAST" | grep -qF -- "$1"; then
    FAILED=$((FAILED + 1)); echo "FAIL [text present: $1] $2"
  else
    PASSED=$((PASSED + 1)); echo "ok   [text absent] $2"
  fi
}

finish() {
  echo "cases: $PASSED passed, $FAILED failed"
  [ "$FAILED" = 0 ]
}
