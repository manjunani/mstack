# Session report read by check_session.py

`session_snippet.js` writes it while a WebXR emulator stands in for the headset.

```json
{
  "emulator": "name and version of the emulator you loaded",
  "session": { "started": true, "mode": "immersive-vr", "ended": true },
  "adapter": { "renderer": "ANGLE (Apple, Apple M2, Metal)" },
  "captures": [
    { "kind": "pose",  "name": "front", "screenshot": "front.png", "pixels": { "spread": 30.1, "dominant_share": 0.4, "transparent_share": 0 } },
    { "kind": "input", "name": "controllers", "screenshot": "controllers.png" },
    { "kind": "input", "name": "hands", "screenshot": "hands.png" }
  ],
  "console_errors": [],
  "counters": { "calls": 40, "triangles": 50000 }
}
```

- Pose and input names are free text; pass the ones you require with `--poses` and `--inputs`.
- How to set a head pose or switch to hands depends on the emulator. Read its current documentation; this pack does not assume an API.
- Untested assumption: reading pixels from the canvas during an emulated session. If the numbers come back flat while the screenshot shows the scene, trust the screenshot file (the checker does).
