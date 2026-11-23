# mstack-apps: what was tested and what was not

Date: 2026-11-22. Machine: macOS 27.0.1, Xcode command-line tools present (`xcrun` 72), Python 3.14 and 3.9.
The build machine had no simulator runtime installed (`simctl list devices --json` returned no devices).

## How to repeat

```
sh packs/apps/tests/scripts/run_all.sh .testrun/apps-all/<new name>
```

Each `*_cases.py` builds its throwaway files in the folder it is given (it refuses a folder that exists
or is outside `.testrun/`) and prints `ok` or `BAD` per check with the expected exit code.
Last full run: 502 checks, 502 ok, 0 bad, runner exit 0.

| Test file | Checks | Result |
|---|---|---|
| pngstat_cases.py (shared PNG reader) | 44 | 44 ok |
| sim_proof_cases.py | 49 | 49 ok |
| sim_flow_cases.py | 47 | 47 ok |
| mac_release_verify_cases.py | 33 | 33 ok |
| tauri_preflight_cases.py | 112 | 112 ok |
| crash_read_cases.py | 80 | 80 ok |
| app_size_cases.py | 56 | 56 ok |
| app_release_notes_cases.py | 23 | 23 ok |
| ios_submit_check_cases.py | 39 | 39 ok |
| ios_a11y_check_cases.py | 19 | 19 ok |

Trigger, silence and benefit tests (`claude plugin eval`) were **not run** for any skill (not allowed in
this job: cost). `tests/results.json` therefore does not exist; every skill shows as "not tested".

## Faults the tests caught (all fixed)

- tauri-preflight: on a real Tauri project (read-only) the script treated
  `tauri.bundle.conf.json` as a platform override and ended "not verified". Only platform names
  (macos, linux, windows, android, ios) are overrides now; other files are named as not read. Case added.
- tauri-preflight: the wildcard pattern first matched `https://*.acme.in` as "any host"; narrowed.
- ios-a11y-check: an image after a closed `Button { }` block was taken to be inside the button
  (three-line look-back). Now the enclosing brace is found. The "good" sample also had a real
  unlabelled status image; the sample was wrong, not the script.
- app-size: the test's own zip helper followed a symbolic link and stored it as a file; fixture fixed.

## Per skill

**Shared PNG reader** (`pngstat.py`, copied byte-identical into sim-proof, sim-flow, ios-submit-check,
ios-a11y-check). Tested: decoding of all five row filters, 1/2/8/16-bit, grey, RGB, RGBA, palette with
transparency, pixel by pixel against what was written; a PNG re-encoded by macOS `sips` (Apple's encoder,
filters 1, 2, 4); blank white, black, transparent, low-noise, status-bar-only, too small, cut short,
bad checksum, not a PNG, empty, missing; phone-sized images through the `sips` reduced copy and through
the pure-Python path. Not tested: a real simulator screenshot (none could be taken), interlaced PNGs
decoded through `sips` (only the "cannot judge without sips" path). Thresholds are mstack defaults.

**sim-proof.** Tested: `check` on images; blocked paths (no xcrun, no booted simulator, two booted,
unknown or shut-down udid, device build, bundle without executable or id, not an .app); `devices` on the
real `xcrun simctl list devices --json` of the build machine (read-only, zero devices, blocked as expected);
the `run` sequence through a stand-in xcrun the test writes (install fail, launch fail, no pid, process
gone, no screenshot, blank screenshot, pass, records never overwritten). **Not run:** a real install,
launch and `simctl io screenshot`. Whether a real `simctl launch` prints its pid in the parsed form
(`bundle.id: 1234`) is not proven here. Building the app was not run.

**sim-flow.** Tested: blocked start without a driver; record creation and refusal to overwrite; refusal
of steps without screenshot, observation or reason, with blank, missing or repeated screenshots;
`--same-screen`; roll-up order (fail before not verified before pass); records edited after the fact
(blank, swapped, deleted screenshot, empty field, unknown status, reused screenshot, driver "none",
broken JSON). **Not run:** any real driving; the skill depends on the host's tapping tool, which was not
available or used.

**mac-release-verify.** Tested with the real `codesign`, `spctl` and `stapler` of a macOS build machine, read-only:
an unsigned bundle (3 fail), Calculator.app (signature and Gatekeeper pass, no staple: fail), a notarised
app with a stapled ticket from /Applications (3 pass), a notarised app without a staple (fails on the
staple only), a wrong `--expect-team`, version match and mismatch, an unsigned `.dmg` made with
`hdiutil create`, with `--mount` (attached read-only, inner app checked, detached again), no tools on
PATH (all "could not check"). **Not run:** a signed and notarised `.dmg` (none at hand), Gatekeeper
switched off, a first launch on a clean Mac (a person does that).

**tauri-preflight.** Tested on hand-written version 2 and version 1 configurations: each rule fires and
passes on its sample (identifier, versions incl. workspace inheritance and a version path, CSP string and
object forms, scopes, remote URLs, broad permission names, updater key and endpoints, icons by first
bytes, platform overrides, TOML capability files, unreadable or unknown configs). One real project was
read (pass with 4 warnings). **Not verified:** the identifier, permission and allowlist lists in
`references/tauri-rules.json` are from memory (`"verified": false`); the samples were not produced by
Tauri's generator; no build, `cargo` or `node` command was run.

**crash-read.** Tested: .ips samples using the field names of real macOS crash reports (named and
address-only own frames, frameworks inside the .app, `--binary`, last exception backtrace, bad thread
index, empty thread, bad image index, deep frame, a non-crash JSON report, body-only file); text `.crash`
samples written from memory of that format; `--dsym` against a binary and dSYM compiled with clang
(match resolved by `atos` to `boom.c:4`; mismatch refused with both build ids). Also run read-only on a
batch of real `.ips` crash reports from a macOS machine: every one parsed without the script crashing;
most were system processes with no app frame and ended as not verified. **Not tested:** a real iOS device or TestFlight report,
a real older-format `.crash` file, Objective-C exception reports with `lastExceptionBacktrace` from a
real app.

**app-size.** Tested: bundles and `.ipa`/`.zip` archives with known sizes (totals, parts, largest files,
symlinks counted as 0, grew/new/shrank/removed lists, the three user limits at and over the edge,
baseline refusal and dated replacement, damaged baseline, bad inputs); a real Mac app (Calculator) whose
total matched `find`+`stat`. **Not tested:** a real iOS build or an `.ipa` exported by Xcode. The App
Store's thinned size is out of scope by design.

**app-release-notes.** Tested in a throwaway git repo: collect and grouping; a passing draft; a line with
no commit, a hash outside the range, a missing fix, `--skip`, empty notes, empty range, unknown tag,
missing notes file, outside a repository. **Not tested:** merge-heavy histories, squash workflows,
store text length limits (no limit file was written: the limits were not verified, so the skill points
to the store's documentation instead).

**ios-submit-check.** Tested on hand-written project folders: each blocker (purpose string missing or
placeholder, no manifest, undeclared or reason-less category, bad or missing version, extension version
mismatch, icon with alpha, wrong size, no icon set), the export-compliance warning, `$(MARKETING_VERSION)`
resolved from a project.pbxproj, screenshots of a listed size, an odd size and a blank one, blocked inputs.
**Not verified:** every table in `references/store-rules.json` (screenshot sizes, usage keys,
required-reason APIs) is from memory and marked `"verified": false`; the script prints that. No real Xcode
project was read.

**ios-a11y-check.** Tested: the scan on two hand-written SwiftUI files (icon button, fixed system and
custom fonts, unlabelled image, colour-only state, and a clean file); the screenshot check (real, blank,
expected screen missing, empty folder). **Not run:** the Swift was not compiled; no simulator text-size
change, no VoiceOver pass. The scan is text matching and will miss labels set in other files.

## Names and open points

- Names follow `docs/SKILLS.md`; none changed.
- `sim-flow` may overlap `qa-run` (test pack) as the study note says; its description points web flows
  there.
- `pngstat.py` is copied into four skills because a skill may not depend on another skill's files. A
  change to one copy needs the same change in the others (`cmp` shows whether they match).
