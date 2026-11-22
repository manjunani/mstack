#!/bin/sh
# Exercise the safe-delete script in a throwaway project. Arguments: manifest.py path, project path.
M="$1"; P="$2"
mkdir -p "$P/docs/old" "$P/src" "$P/node_modules/x" && cd "$P" || exit 9
/usr/bin/git init -q
echo "a" > docs/old/a.md
echo "see docs/old/a.md and old notes" > src/app.py
echo "node_modules/" > .gitignore
echo "j" > node_modules/x/i.js
/usr/bin/git add -A && /usr/bin/git -c user.name=t -c user.email=t@t commit -qm init
echo "only copy" > docs/old/draft.md

echo "== plan"; python3 "$M" plan docs/old --reason "not needed"; echo "exit $?"
ID=$(python3 "$M" list | awk '{print $1}' | head -1)
echo "== refused: project folder itself"; python3 "$M" plan . | grep -E "REFUSED|RESULT"
echo "== refused: outside, .git, missing"; python3 "$M" plan /etc/hosts .git/config nope | grep -E "REFUSED|RESULT"
echo "== target changes after plan, then apply"; echo "more" >> docs/old/a.md; python3 "$M" apply "$ID"; echo "exit $?"
echo "== plan again and apply"; python3 "$M" plan docs/old > /dev/null
ID=$(python3 "$M" list | awk '$2=="planned"{print $1}' | tail -1)
python3 "$M" apply "$ID"; echo "exit $?"
echo "docs now holds: $(ls docs | tr '\n' ' ')"; echo "trash holds: $(ls .mstack/trash/$ID/docs/old | tr '\n' ' ')"
echo "== undo"; python3 "$M" undo "$ID"; echo "exit $?"; echo "docs/old holds: $(ls docs/old | tr '\n' ' ')"
echo "== regenerable folder: apply, purge without and with confirm"
python3 "$M" plan node_modules | head -3
ID2=$(python3 "$M" list | awk '$2=="planned"{print $1}' | tail -1)
python3 "$M" apply "$ID2" | tail -1
python3 "$M" purge "$ID2"; echo "exit $?"
python3 "$M" purge "$ID2" --confirm "$ID2"; echo "exit $?"
echo "== list"; python3 "$M" list
echo "== git sees"; /usr/bin/git status --porcelain
