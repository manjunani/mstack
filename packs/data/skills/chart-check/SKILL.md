---
name: chart-check
description: Checks a chart from its JSON spec for a truncated bar axis, missing labels or units, clipped data, too many series, crowded pies, dual axes, categories out of order, values that differ from the source data. Use when a chart or dashboard panel is about to be shared, or someone asks "is this chart misleading" or "does this plot match the data". Not for numbers in report text (use number-trace) or for drawing the chart.
license: MIT
metadata:
  pack: data
  version: 0.2.2
  needs: python3
---

# Chart check

Produces a list of what is wrong with a chart's spec and whether its values match the data they claim to show.

## Done when

- A spec of the chart exists (written from the chart code, or exported by the library) and names its source data.
- `scripts/chartcheck.py` ran and its RESULT line is in the reply.
- The reply says that colours, overlap and font sizes were not checked by the script, and whether someone looked at the rendered image.

End in exactly one state: **pass** (no blocking finding and values match the source), **fail** (wrong values, truncated bar axis, clipped data, missing labels, broken spec), **not verified** (no source to compare with, or a bar axis minimum not stated), or **blocked** (no usable spec).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The chart's code or spec, and its data file | the paths exist | ask; without data the values stay not verified |

## Steps

The script is `scripts/chartcheck.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/chartcheck.py"`.

1. **Check needs.**
2. **Write the spec** from what the chart code really passes to the library: the values, the axis range the renderer uses, labels, units. Fields: `references/spec.md`. Copy values from the code, not from the data, or the source check proves nothing.
3. **Check.**
   ```
   python3 scripts/chartcheck.py <spec.json>
   ```
4. **Look at the rendered chart** if it can be opened: colours, labels that overlap, legend. These are taste warnings, not blocks.
5. **Report.** End state first. Then blocking findings, warnings, the source comparison, and what was not checked.

## Rules

- A wrong value or a bar axis that does not start at zero blocks. Series count, pie slices, sorting and dual axes are warnings the user may accept.
- Fix the chart code, not the spec, when a finding is real; then write the spec again from the code and re-run.
- Limits are in `references/limits.json` and are unverified defaults.

## Not for

- Numbers written in report text → use `number-trace`.
- A design review of a whole page → use `design-review`.
- Checking a data file against rules → use `data-check`.

## Level

- beginner: explain why a bar axis must start at zero and what a dual axis hides.
- standard: as written.
- expert: the findings and the RESULT line. Every check still runs.
