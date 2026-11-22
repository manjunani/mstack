# Shared helpers for the mstack-dev script tests. Source this file; do not run it.
#
#   t <expected exit> <label> <command ...>   run the command, compare its exit code, keep its output in $OUT
#   has <text>                                the output of the last t call contains the text
#   hasnt <text>                              the output of the last t call does not contain the text
#   same <label> <a> <b>                      two strings are equal
#   finish                                    print the totals; exit 1 if any case was wrong
#
# Every case prints one line: "ok" or "WRONG". A wrong case also prints the output it saw.

PASSED=0
FAILED=0
OUT=""
export MSTACK_GIT=/usr/bin/git
G=/usr/bin/git
GC="/usr/bin/git -c user.name=tester -c user.email=tester@example.invalid -c commit.gpgsign=false"

t() {
  want="$1"; label="$2"; shift 2
  OUT=$("$@" 2>&1); got=$?
  if [ "$got" = "$want" ]; then
    PASSED=$((PASSED + 1)); echo "ok    exit $got  $label"
  else
    FAILED=$((FAILED + 1)); echo "WRONG exit $got (expected $want)  $label"
    printf '%s\n' "$OUT" | sed 's/^/      | /'
  fi
}

has() {
  case "$OUT" in
    *"$1"*) PASSED=$((PASSED + 1)); echo "ok            output has: $1" ;;
    *) FAILED=$((FAILED + 1)); echo "WRONG         output lacks: $1"; printf '%s\n' "$OUT" | sed 's/^/      | /' ;;
  esac
}

hasnt() {
  case "$OUT" in
    *"$1"*) FAILED=$((FAILED + 1)); echo "WRONG         output must not have: $1"; printf '%s\n' "$OUT" | sed 's/^/      | /' ;;
    *) PASSED=$((PASSED + 1)); echo "ok            output is free of: $1" ;;
  esac
}

same() {
  if [ "$2" = "$3" ]; then
    PASSED=$((PASSED + 1)); echo "ok            $1"
  else
    FAILED=$((FAILED + 1)); echo "WRONG         $1"; echo "      | first:  $2"; echo "      | second: $3"
  fi
}

finish() {
  echo "CASES $NAME: $PASSED passed, $FAILED wrong"
  [ "$FAILED" = 0 ]
}

# new_project <folder>: refuse an existing folder, create it, start a git repository with one commit.
new_project() {
  [ -e "$1" ] && { echo "refusing: $1 already exists"; exit 9; }
  mkdir -p "$1" && cd "$1" || exit 9
  # Stop git from finding a repository above the test folders, so "$1.nogit" really is outside any repository.
  GIT_CEILING_DIRECTORIES=$(dirname "$(pwd)"); export GIT_CEILING_DIRECTORIES
  $G init -q -b main . || exit 9
  echo "# sample" > README.md
  $G add README.md && $GC commit -qm "first commit" || exit 9
}
