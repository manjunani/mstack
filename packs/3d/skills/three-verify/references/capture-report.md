# Capture report read by check_capture.py

`capture_snippet.js` writes it. Hand edits make it worthless; if a field is missing, leave it missing.

```json
{
  "adapter": { "vendor": "...", "renderer": "ANGLE (Apple, Apple M2, Metal)", "masked": false },
  "poses": [
    { "name": "front", "screenshot": "front.png",
      "pixels": { "spread": 41.2, "dominant_share": 0.31, "transparent_share": 0.0 } }
  ],
  "console_errors": [],
  "counters": {
    "before":        { "calls": 0,  "triangles": 0,     "geometries": 0,  "textures": 0,  "programs": 0 },
    "loaded":        { "calls": 42, "triangles": 90000, "geometries": 30, "textures": 12, "programs": 6 },
    "after_dispose": { "calls": 0,  "triangles": 0,     "geometries": 0,  "textures": 0,  "programs": 6 },
    "after_dispose_2": { "calls": 0, "triangles": 0,    "geometries": 0,  "textures": 0,  "programs": 6 }
  },
  "frame_time_ms": { "median": 8.1, "p95": 11.0, "samples": 120 },
  "frame_time_idle_ms": { "median": 8.3, "p95": 8.4, "samples": 120 }
}
```

- `screenshot` paths are relative to the report file. When the file exists it is decoded and wins over `pixels`.
- `frame_time_ms` is null unless measured. A frame time from a software adapter is a fail, not a number.
- Headless Chromium often falls back to a software renderer. Read `adapter.renderer` before saying anything about speed.
- `after_dispose_2` is optional: counters after loading and disposing the scene a second time. three.js r187 keeps one lookup texture once a physically based material was drawn, so the first dispose can leave one texture that is the renderer's own. A count that does not grow from the first dispose to the second is not a leak.
- `frame_time_idle_ms` is optional: the requestAnimationFrame interval with the page's render loop stopped. On an Apple M1 (tested 2026-11-22) in Playwright's Chromium 159, an idle page ran at 33.3 ms in new headless and headed mode and 16.7 ms in the headless shell, so a scene timed at 33.3 ms there says nothing about its cost.
- In Playwright on macOS, the default headless shell draws with SwiftShader (software). Launching with `--use-angle=metal`, or with `channel: 'chromium'` (new headless), gave the hardware adapter "ANGLE Metal Renderer: Apple M1" on the test machine.
