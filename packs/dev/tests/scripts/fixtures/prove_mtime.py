"""Test helper for prove_cases.sh. Appends the modification second of src/calc.py to a log, then passes when
add() works and fails when it does not. The log shows whether each run of prove.py saw a file with a new
modification time; tools that cache by time and size (Python bytecode, make) need that.
Usage: prove_mtime.py <log file>"""
import argparse
import os
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("log")
args = parser.parse_args()
with open(args.log, "a", encoding="utf-8") as handle:
    handle.write(f"{int(os.stat('src/calc.py').st_mtime)}\n")
sys.path.insert(0, ".")
from src.calc import add  # noqa: E402

sys.exit(0 if add(2, 3) == 5 else 1)
