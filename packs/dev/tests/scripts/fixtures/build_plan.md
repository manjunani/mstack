# Plan: calculator

Goal: The calculator adds and has a command line.
Spec: none

## Task 1: Add numbers

Files: src/calc.py, tests/test_calc.py (new), tests/__init__.py (new)
Makes: add
Check: `python3 -m unittest tests.test_calc`
Expect: Ran 1 test, OK

1. `add(a, b)` returns the sum.

## Task 2: Command line

Files:
- src/cli.py (new)
Uses: add
Check: `python3 src/cli.py 2 3`
Expect: prints 5

1. src/cli.py reads two numbers and prints their sum.
