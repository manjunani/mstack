---
name: crash-read
description: Reads an Apple crash report (.ips or .crash) and names the failing frame from the app's own code. Use when an iPhone or Mac app crashed and the user points to a crash log, says "it crashed on launch" or asks "what does this crash report mean". Prints the exception type, crashed thread, whether frames are symbolicated, and checks a dSYM's build id matches before resolving addresses with atos. Not for finding the bug's cause in code (use debug).
license: MIT
metadata:
  pack: apps
  version: 0.1.0
  needs: python3; dwarfdump and atos (Xcode command-line tools) only for unsymbolicated reports
---

# Crash read

Produces one sentence, "this frame, in this binary, for this exception", taken from the report, or the exact reason it cannot be named.

## Done when

- `scripts/crashread.py <report>` exits 0 and its RESULT line is quoted, or the reply gives the missing piece (symbol file with the printed build id, or the binary name).
- Anything the script printed under "could not parse" is in the reply.

End in exactly one state: **pass** (frame named), **fail** (the report contradicts itself or is cut short), **not verified** (own frames are addresses only, or no own frame in the stack), or **blocked** (no report file, or the symbol file does not match).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The report | a path; Mac reports are in `~/Library/Logs/DiagnosticReports/`, simulator crashes land there too | ask for the file |
| dwarfdump, atos | `xcrun -f atos` | only for address-only frames; otherwise not verified |
| The matching dSYM | the build id the script prints | ask the user for the archive's dSYM; never use one with another build id |

## Steps

The script is `scripts/crashread.py` (`"${CLAUDE_SKILL_DIR}/scripts/crashread.py"` in Claude Code).

1. **Read.**
   ```
   python3 scripts/crashread.py <report.ips> [--binary <AppBinary>]
   ```
   `--binary` when the app's image has a different name from the process.
2. **If frames are addresses**, find the dSYM with the build id printed, then:
   ```
   python3 scripts/crashread.py <report.ips> --dsym <App.app.dSYM>
   ```
   A mismatch is refused with both ids shown. Do not resolve with another build's symbols.
3. **Open the named file and line** if the source is here, and say what the code does there. That is reading, not a fix.
4. **Report.** End state, the exception, the failing frame, the runtime message if any, and what could not be parsed.

## Rules

- Never guess a function name from an address.
- The crashed frame is where the app stopped, not always where the bug is; say so when the frame is in system code under app code.
- Crash report format is Apple's; Apple's documentation on diagnosing crashes is the source.

## Not for

- Finding and fixing the cause → use `debug`.
- Filing the crash as an issue → use `bug-report`.
- A crash at launch on the simulator, not yet captured → run `sim-proof` first.

## Level

- beginner: explain threads, frames and symbolication.
- standard: as written.
- expert: the RESULT line and the frame table. The build id check is never skipped.
