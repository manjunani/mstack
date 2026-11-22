/*
 * mstack three-verify: in-page capture snippet.
 *
 * Paste this file into the page (or load it with a script tag in a test build), then drive it from the
 * browser tool you have. It reads the page's own renderer; it loads nothing and sends nothing anywhere.
 *
 *   const cap = mstackCapture.start({ renderer, scene, camera });   // call before the scene loads if you can
 *   cap.mark('before');                                             // counters with an empty scene
 *   ...load the scene...
 *   await cap.pose('front', () => { camera.position.set(0, 1.5, 4); camera.lookAt(0, 1, 0); });
 *   await cap.pose('side',  () => { camera.position.set(4, 1.5, 0); camera.lookAt(0, 1, 0); });
 *   cap.mark('loaded');
 *   await cap.frameTime(120);                                       // optional; only means something on a real GPU
 *   ...dispose the scene: geometries, materials, textures...
 *   cap.mark('after_dispose');
 *   JSON.stringify(cap.report())                                    // save as report.json for check_capture.py
 *
 * Take a browser screenshot after each pose and add its file name to that pose as "screenshot"; the checker
 * decodes the file and trusts it over the numbers below. The numbers are a second opinion read straight from
 * the drawing buffer, which also works when the screenshot tool captures something else than the canvas.
 *
 * WebGLRenderer only. With another renderer the adapter name and the pixel numbers come back empty and the
 * checker reports them as not verified.
 */
(function (root) {
  'use strict';

  // Same measures as pngstats.py: largest per-channel standard deviation, share of the most common
  // colour among sampled pixels, share of fully transparent pixels.
  function pixelStats(rgba, width, height) {
    var total = width * height;
    if (!total || rgba.length < total * 4) return null;
    var sum = [0, 0, 0], sq = [0, 0, 0], clear = 0;
    for (var i = 0; i < total; i++) {
      for (var c = 0; c < 3; c++) { var v = rgba[i * 4 + c]; sum[c] += v; sq[c] += v * v; }
      if (rgba[i * 4 + 3] === 0) clear++;
    }
    var spread = 0;
    for (var k = 0; k < 3; k++) {
      var mean = sum[k] / total;
      spread = Math.max(spread, Math.sqrt(Math.max(sq[k] / total - mean * mean, 0)));
    }
    var step = Math.max(1, Math.floor(total / 200000)), counts = new Map(), sampled = 0, best = 0, bestKey = 0;
    var hash = 2166136261; // FNV-1a over the sampled pixels: equal images give equal hashes
    for (var p = 0; p < total; p += step) {
      var key = (rgba[p * 4] << 16) | (rgba[p * 4 + 1] << 8) | rgba[p * 4 + 2];
      hash = Math.imul(hash ^ key, 16777619) >>> 0;
      var n = (counts.get(key) || 0) + 1;
      counts.set(key, n); sampled++;
      if (n > best) { best = n; bestKey = key; }
    }
    return {
      width: width, height: height, spread: Math.round(spread * 1000) / 1000,
      dominant_colour: [(bestKey >> 16) & 255, (bestKey >> 8) & 255, bestKey & 255],
      dominant_share: Math.round((best / sampled) * 100000) / 100000,
      transparent_share: Math.round((clear / total) * 100000) / 100000,
      distinct_colours_sampled: counts.size, pixel_hash: 'page-' + hash.toString(16)
    };
  }

  function adapterOf(gl) {
    if (!gl || typeof gl.getParameter !== 'function') return { vendor: null, renderer: null, masked: true };
    var ext = gl.getExtension && gl.getExtension('WEBGL_debug_renderer_info');
    return {
      vendor: String(gl.getParameter(ext ? ext.UNMASKED_VENDOR_WEBGL : gl.VENDOR)),
      renderer: String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER)),
      masked: !ext
    };
  }

  function countersOf(renderer) {
    var info = renderer && renderer.info;
    if (!info) return null;
    return {
      calls: info.render ? info.render.calls : null,
      triangles: info.render ? info.render.triangles : null,
      geometries: info.memory ? info.memory.geometries : null,
      textures: info.memory ? info.memory.textures : null,
      programs: info.programs ? info.programs.length : null
    };
  }

  function nextFrames(count) {
    return new Promise(function (resolve) {
      var raf = root.requestAnimationFrame || function (f) { return setTimeout(function () { f(Date.now()); }, 16); };
      (function tick(left) { if (left <= 0) resolve(); else raf(function () { tick(left - 1); }); })(count);
    });
  }

  function start(options) {
    var renderer = options.renderer, scene = options.scene, camera = options.camera;
    var gl = renderer && typeof renderer.getContext === 'function' ? renderer.getContext() : null;
    var state = { poses: [], console_errors: [], counters: {}, frame_time_ms: null, frames_waited: options.frames || 2 };
    var cons = root.console;
    if (cons && typeof cons.error === 'function') {
      var original = cons.error;
      cons.error = function () {
        state.console_errors.push(Array.prototype.map.call(arguments, String).join(' ').slice(0, 500));
        return original.apply(cons, arguments);
      };
    }
    if (typeof root.addEventListener === 'function') {
      root.addEventListener('error', function (e) { state.console_errors.push('uncaught: ' + (e && e.message)); });
      root.addEventListener('unhandledrejection', function (e) { state.console_errors.push('unhandled rejection: ' + (e && e.reason)); });
    }
    return {
      mark: function (name) { state.counters[name] = countersOf(renderer); return state.counters[name]; },
      pose: function (name, apply) {
        if (typeof apply === 'function') apply();
        return nextFrames(state.frames_waited).then(function () {
          renderer.render(scene, camera); // read in the same task as the draw, or the buffer may already be cleared
          var pixels = null;
          if (gl && typeof gl.readPixels === 'function') {
            var w = gl.drawingBufferWidth, h = gl.drawingBufferHeight, buf = new Uint8Array(w * h * 4);
            gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
            pixels = pixelStats(buf, w, h);
          }
          var entry = { name: name, pixels: pixels, counters: countersOf(renderer) };
          state.poses.push(entry);
          return entry;
        });
      },
      frameTime: function (frames) {
        var raf = root.requestAnimationFrame, times = [];
        if (typeof raf !== 'function') return Promise.resolve(null);
        return new Promise(function (resolve) {
          var last = null;
          raf(function tick(now) {
            if (last !== null) times.push(now - last);
            last = now;
            if (times.length < (frames || 120)) { raf(tick); return; }
            times.sort(function (a, b) { return a - b; });
            state.frame_time_ms = {
              median: Math.round(times[Math.floor(times.length / 2)] * 100) / 100,
              p95: Math.round(times[Math.floor(times.length * 0.95)] * 100) / 100,
              samples: times.length
            };
            resolve(state.frame_time_ms);
          });
        });
      },
      report: function () {
        return {
          tool: 'mstack three-verify capture', version: 1,
          url: root.location ? String(root.location.href) : null,
          three_revision: options.THREE && options.THREE.REVISION ? String(options.THREE.REVISION) : null,
          adapter: adapterOf(gl), frames_waited: state.frames_waited,
          poses: state.poses, console_errors: state.console_errors,
          counters: state.counters, frame_time_ms: state.frame_time_ms
        };
      }
    };
  }

  var api = { start: start, pixelStats: pixelStats, adapterOf: adapterOf, countersOf: countersOf };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.mstackCapture = api;
})(typeof window !== 'undefined' ? window : globalThis);
