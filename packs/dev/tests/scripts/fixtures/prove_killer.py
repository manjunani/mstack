"""Test helper for prove_cases.sh. Passes when add() works. When add() is broken (the middle run of prove.py),
it sends the named signal to the prove.py process that started it, to act out a crash or an interrupt.
Usage: prove_killer.py KILL|TERM"""
import argparse
import os
import signal
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("signal", choices=["KILL", "TERM"])
args = parser.parse_args()
sys.path.insert(0, ".")
from src.calc import add  # noqa: E402

if add(2, 3) == 5:
    sys.exit(0)
pid = os.getppid()
for _ in range(6):
    command = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
    if "prove.py" in command:
        os.kill(pid, getattr(signal, "SIG" + args.signal))
        break
    parent = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    pid = int(parent or 1)
sys.exit(1)
