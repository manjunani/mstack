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
- Reading pixels from the canvas during an emulated session worked on 2026-11-22 (IWER 2.8.0, three.js r187, Playwright Chromium 159): the numbers matched the screenshots pose by pose. If they come back flat while the screenshot shows the scene, trust the screenshot file (the checker does).
- Desktop Chromium has its own `navigator.xr` with no headset behind it, and it refuses `immersive-vr` with "The specified session configuration is not supported." IWER 2.8 does not replace it unless installed with `device.installRuntime({ forceInstall: true })`. With it, IWER's `device.position`, `device.quaternion` and `device.primaryInputMode = 'controller' | 'hand'` set the head pose and the input mode.
- three.js hands: `renderer.xr.getHand(i)` gives an empty group; nothing shows unless the page draws the joints or a hand model. A hands capture that looks like the pose captures means nothing was drawn for the hands.
