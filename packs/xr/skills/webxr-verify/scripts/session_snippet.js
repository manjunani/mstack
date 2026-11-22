/*
 * mstack webxr-verify: in-page session snippet.
 *
 * Load it in the page AFTER a WebXR emulator has replaced navigator.xr (for example Meta's open-source
 * IWER, or a browser extension that emulates a headset). Check the emulator's own documentation for how
 * to set the head pose and switch between controllers and hands: those calls differ between emulators and
 * versions, so this snippet takes them as functions you pass in. It loads nothing and sends nothing.
 *
 *   const run = mstackXR.start({ renderer, THREE });          // three.js WebGLRenderer with xr.enabled
 *   await run.enter('immersive-vr');                           // requests the session and hands it to three.js
 *   await run.capture('pose', 'front', () => setHeadPose(...)) // your emulator call goes in the function
 *   await run.capture('pose', 'left',  () => setHeadPose(...))
 *   await run.capture('input', 'controllers', () => useControllers())
 *   await run.capture('input', 'hands', () => useHands())
 *   await run.exit();
 *   JSON.stringify(run.report())                               // save as report.json for check_session.py
 *
 * After each capture take a browser screenshot and add its file name to that capture as "screenshot".
 */
(function (root) {
  'use strict';
  function stats(rgba, w, h) {
    var total = w * h;
    if (!total || rgba.length < total * 4) return null;
    var sum = [0, 0, 0], sq = [0, 0, 0], clear = 0, counts = new Map(), best = 0, sampled = 0;
    var step = Math.max(1, Math.floor(total / 200000));
    for (var i = 0; i < total; i++) {
      for (var c = 0; c < 3; c++) { var v = rgba[i * 4 + c]; sum[c] += v; sq[c] += v * v; }
      if (rgba[i * 4 + 3] === 0) clear++;
      if (i % step === 0) {
        var key = (rgba[i * 4] << 16) | (rgba[i * 4 + 1] << 8) | rgba[i * 4 + 2];
        var n = (counts.get(key) || 0) + 1; counts.set(key, n); sampled++;
        if (n > best) best = n;
      }
    }
    var spread = 0;
    for (var k = 0; k < 3; k++) { var m = sum[k] / total; spread = Math.max(spread, Math.sqrt(Math.max(sq[k] / total - m * m, 0))); }
    return { spread: Math.round(spread * 1000) / 1000, dominant_share: Math.round(best / sampled * 100000) / 100000,
             transparent_share: Math.round(clear / total * 100000) / 100000 };
  }
  function frames(session, n) {
    return new Promise(function (resolve) {
      var raf = session ? session.requestAnimationFrame.bind(session) : root.requestAnimationFrame;
      (function tick(left) { if (left <= 0) resolve(); else raf(function () { tick(left - 1); }); })(n);
    });
  }
  function start(opts) {
    var renderer = opts.renderer, gl = renderer.getContext(), session = null;
    var out = { tool: 'mstack webxr-verify session', emulator: opts.emulator || null, session: { started: false },
                captures: [], console_errors: [], counters: {}, adapter: {} };
    var ext = gl.getExtension('WEBGL_debug_renderer_info');
    out.adapter = { renderer: String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER)), masked: !ext };
    var original = root.console.error;
    root.console.error = function () { out.console_errors.push(Array.prototype.map.call(arguments, String).join(' ').slice(0, 500)); return original.apply(root.console, arguments); };
    root.addEventListener('error', function (e) { out.console_errors.push('uncaught: ' + e.message); });
    return {
      enter: function (mode) {
        if (!navigator.xr) { out.session = { started: false, error: 'navigator.xr is missing: no emulator loaded, or not a secure context' }; return Promise.resolve(false); }
        return navigator.xr.requestSession(mode, opts.sessionInit || { optionalFeatures: ['local-floor', 'hand-tracking'] })
          .then(function (s) {
            session = s; out.session = { started: true, mode: mode, ended: false };
            s.addEventListener('end', function () { out.session.ended = true; });
            return renderer.xr.setSession(s);
          })
          .then(function () { return true; })
          .catch(function (e) { out.session = { started: false, mode: mode, error: String(e && e.message || e) }; return false; });
      },
      capture: function (kind, name, apply) {
        if (typeof apply === 'function') apply();
        return frames(session, opts.frames || 3).then(function () {
          var w = gl.drawingBufferWidth, h = gl.drawingBufferHeight, buf = new Uint8Array(w * h * 4);
          gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
          var entry = { kind: kind, name: name, pixels: stats(buf, w, h) };
          out.captures.push(entry);
          var info = renderer.info;
          out.counters = { calls: info.render.calls, triangles: info.render.triangles, geometries: info.memory.geometries, textures: info.memory.textures };
          return entry;
        });
      },
      exit: function () { return session ? session.end() : Promise.resolve(); },
      report: function () { return out; }
    };
  }
  var api = { start: start, stats: stats };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.mstackXR = api;
})(typeof window !== 'undefined' ? window : globalThis);
