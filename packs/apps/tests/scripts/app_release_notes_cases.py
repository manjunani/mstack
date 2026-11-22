"""Test app-release-notes' script on a throwaway git repository with known commits.

Usage: python3 app_release_notes_cases.py <new folder under .testrun/>
"""
import os
import subprocess
import sys

import fixtures as fx

W = fx.workdir(sys.argv)
SCRIPT = fx.SKILLS / "app-release-notes" / "scripts" / "notescheck.py"
PY = sys.executable
c = fx.Cases("app-release-notes")
repo = W / "repo"
repo.mkdir()
env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
G = "/usr/bin/git"


def git(*args):
    return subprocess.run([G, *args], cwd=repo, capture_output=True, text=True, env=env).stdout.strip()


def commit(message, name):
    (repo / name).write_text(message)
    git("add", name)
    git("commit", "-qm", message)
    return git("rev-parse", "--short=7", "HEAD")


git("init", "-q")
commit("first", "a.txt")
git("tag", "v1.0")
h = {k: commit(m, f"{k}.txt") for k, m in (("feat", "feat(notes): pin a note to the top"), ("fix", "fix: crash when a note title is empty"),
                                           ("chore", "chore: bump lint config"), ("plain", "Faster search on long notes"), ("ci", "ci: cache derived data"))}
git("tag", "v1.1")
run = lambda want, label, args: c.run(want, label, [PY, SCRIPT] + [str(a) for a in args], cwd=repo)

run(0, "collect lists the range grouped by prefix", ["collect", "v1.0", "v1.1"])
c.has("5 commits")
c.has("feat (user-facing): 1")
c.has("chore (internal): 1")
c.has("(none) (user-facing): 1")
c.has("3 of them user-facing")
good = W / "good.md"
good.write_text(f"# What's new\n\n- Pin a note to the top of the list [{h['feat']}]\n- Fixed a crash with empty titles ({h['fix']})\n- Search is faster in long notes {h['plain']}\n")
run(0, "notes that name every user-facing commit pass", ["check", "v1.0", "v1.1", good])
c.last_line("RESULT pass")
invented = W / "invented.md"
invented.write_text(good.read_text() + "- Dark mode for the whole app\n")
run(1, "a line with no commit behind it fails", ["check", "v1.0", "v1.1", invented])
c.has("names no commit in the range: - Dark mode")
wrong = W / "wrong.md"
wrong.write_text(good.read_text() + "- Sync improvements [deadbee]\n")
run(1, "a line with a hash outside the range fails", ["check", "v1.0", "v1.1", wrong])
short = W / "short.md"
short.write_text(f"- Pin a note [{h['feat']}]\n- Faster search {h['plain']}\n")
run(1, "a user-facing fix missing from the notes fails", ["check", "v1.0", "v1.1", short])
c.has(f"missing: {h['fix']} fix: crash when a note title is empty")
c.lacks(f"missing: {h['chore']}", "internal chore commit is not required")
run(0, "the same notes pass when the fix is skipped on purpose", ["check", "v1.0", "v1.1", short, "--skip", h["fix"]])
c.has("left out on purpose")
(W / "empty.md").write_text("# Notes\n\n")
run(1, "notes with no lines fail", ["check", "v1.0", "v1.1", W / "empty.md"])
run(2, "an empty range is not verified", ["collect", "v1.1", "v1.1"])
run(2, "a tag that does not exist is blocked", ["collect", "v0.9", "v1.1"])
c.last_line("blocked:")
run(2, "a missing notes file is blocked", ["check", "v1.0", "v1.1", W / "none.md"])
c.run(2, "outside a git repository is blocked", [PY, SCRIPT, "collect", "a", "b"], cwd=W)
c.run(0, "--help works", [PY, SCRIPT, "--help"])
sys.exit(c.finish())
