# Page snapshot, format 1

One JSON file describes what the browser drew. `scripts/collect.js` writes one **view**; `check_page.py merge` joins views into a **snapshot**. design-review, a11y-audit, ui-copy and brand-kit read the same format.

```json
{ "mstack_snapshot": 1, "views": [ <view>, <view> ] }
```

A file holding a single view (no `views` key) is read as a snapshot of one view.

## View

| Key | Type | Meaning |
|---|---|---|
| `viewport` | `{width, height}` | CSS px. `width` is required |
| `theme` | string | `light`, `dark` or any label. Default `light` |
| `state` | string | `default`, `empty`, `error`, `signed out`... Default `default` |
| `url`, `title`, `captured`, `collector` | string | Where and when; for the report only |
| `document` | `{scrollWidth, clientWidth, scrollHeight}` | `scrollWidth` wider than the viewport means sideways scrolling |
| `elements` | list | See below. An empty list is not a capture |
| `skipped` | number | Elements left out past the collector's limit of 2000 |

The view's label is `width/theme/state`, for example `320/dark/empty`. Two views with the same label cannot be merged.

## Element

Only elements with their own text, controls and pictures are listed.

| Key | Type | Meaning |
|---|---|---|
| `selector` | string | A short CSS path, used in findings and waivers |
| `tag`, `role` | string | Tag name; explicit or implicit ARIA role (`button`, `link`, `img`, `heading`, `textbox`...) |
| `name`, `nameFrom` | string | Accessible name and where it came from (`aria-label`, `label`, `content`, `alt`, `title`, `placeholder`) |
| `text` | string | The element's own text, at most 300 characters |
| `box` | `{x, y, width, height}` | Page coordinates in CSS px |
| `color` | string | Text colour as drawn, `rgb()` or `rgba()`; opacity of ancestors is folded into alpha |
| `background` | string | The colour behind the text: own and ancestor backgrounds composited over white |
| `backgroundKnown` | bool | `false` when an image or gradient is in the way; contrast then needs a person |
| `fontSize`, `fontWeight`, `fontFamily` | number, number, string | Computed values |
| `interactive`, `focusable`, `disabled`, `inline` | bool | `inline` marks a link inside a sentence (exempt from target size) |
| `decorative` | bool | `aria-hidden`, role `presentation`/`none`, or `alt=""` |
| `visuallyHidden` | bool | Screen-reader-only text (1 px box or clipped to nothing) |
| `clipped` | bool | Text cut off by its own box with no ellipsis |
| `truncated` | string | `ellipsis` or `line clamp`: shortened on purpose |
| `clippedBy` | string | Selector of an ancestor with hidden overflow that cuts this element |
| `inScroller` | bool | Inside a scrolling container, so leaving the viewport is allowed |
| `href`, `placeholder`, `backgroundImage` | string | When present |

Keys not listed are ignored, so a hand-made or tool-made snapshot can carry more.

## Capturing several views

Set the label before each capture, change the viewport, theme or state, then run the collector again:

```js
window.__mstackView = { theme: 'dark', state: 'empty cart' };
```

The collector cannot see focus rings, hover or motion. Those need a person or a keyboard pass (a11y-audit).
