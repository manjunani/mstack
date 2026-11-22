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
    "after_dispose": { "calls": 0,  "triangles": 0,     "geometries": 0,  "textures": 0,  "programs": 6 }
  },
  "frame_time_ms": { "median": 8.1, "p95": 11.0, "samples": 120 }
}
```

- `screenshot` paths are relative to the report file. When the file exists it is decoded and wins over `pixels`.
- `frame_time_ms` is null unless measured. A frame time from a software adapter is a fail, not a number.
- Headless Chromium often falls back to a software renderer. Read `adapter.renderer` before saying anything about speed.
