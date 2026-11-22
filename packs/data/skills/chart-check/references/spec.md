# Chart spec for chartcheck.py

A JSON object. Write it from the chart code (the values and axis settings the code passes to the library), or ask the library to export its spec.

| field | needed | meaning |
|---|---|---|
| `type` | yes | `bar`, `line`, `area`, `pie` or `scatter` |
| `title` | no (warns) | the chart title |
| `x.label`, `y.label` | yes, except pie | axis titles |
| `y.unit` | no (warns) | unit of the value axis; write `count` or `none` when there is none |
| `y.min`, `y.max` | `min` for bar and area | the axis range the renderer uses; an unstated `min` on a bar chart ends as not verified |
| `y.scale` | no | `log` skips the zero check |
| `x.categories` | for bar, line, area, pie | category labels in drawing order |
| `x.ordered` | no | `true` when order matters; when absent, numbers, dates, months, weekdays and quarters count as ordered |
| `y2` | no | a second value axis, with its own `label`, `unit`, `min`, `max` |
| `series` | yes | list of `{name, values, axis}`; `axis` is `y` (default) or `y2` |
| `source.file` | no (not verified) | CSV, JSON-lines or SQLite file the values came from; relative to the spec |
| `source.table` | no | table for a SQLite source |
| `source.category_column` | with `source` | column that holds the category labels |
| `source.series` | no | object of series name to source column; default is a column with the series name |
| `source.aggregate` | no | `none` (one row per category, default), `sum`, `mean` or `count` |
| `source.scale` | no | multiply source values before comparing (for example 0.001 for thousands) |

Values are compared after rounding to the decimals shown in the spec.

Not checked by the script: colours and colour-blind safety, label overlap, font sizes, legends, annotations, whether the chart answers the question. Look at the rendered image for those.
