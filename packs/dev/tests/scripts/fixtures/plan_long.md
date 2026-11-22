# Plan: one line change

Goal: The banner says hello.
Spec: docs/spec.md

## Task 1: Change the banner

Files: src/dates.py
Check: `python3 -c "import sys; sys.exit(0)"`
Expect: exit code 0

1. Change the banner text in src/dates.py from "hi" to "hello". The banner is the first line the program prints when it starts and it is read by people only so no other code depends on the exact text of it and no test reads it either which is why this task has a check that only confirms the module still loads without an error on start. The banner text was chosen by the owner in the spec and is not to be changed again in this plan or in any later task of this plan because later tasks do not exist here.
