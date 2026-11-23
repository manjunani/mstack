import pathlib
import sys

for path in pathlib.Path(sys.argv[1]).glob("*.md"):
    text = path.read_text(encoding="utf-8")
    path.write_text(text.strip() + "\n", encoding="utf-8")
