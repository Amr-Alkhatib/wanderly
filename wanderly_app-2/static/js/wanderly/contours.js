/* Wanderly contour field.
   Topographic lines drawn from animated simplex noise with marching squares.
   In "live" mode the pointer raises a summit, so wherever you point is the
   highest ground on the map; when the pointer leaves, the summit wanders.
   Usage: <canvas data-contours="live|static" data-contour-tone="dark|light"> */
(function () {
  'use strict';

  /* ---- 3D simplex noise (after Stefan Gustavson's public-domain reference) ---- */
  var grad3 = new Float32Array([1,1,0,-1,1,0,1,-1,0,-1,-1,0,1,0,1,-1,0,1,1,0,-1,-1,0,-1,0,1,1,0,-1,1,0,1,-1,0,-1,-1]);
  function makeNoise(seed) {
    var p = new Uint8Array(256), perm = new Uint8Array(512), permMod12 = new Uint8Array(512);
    var s = seed || 1;
    function rnd() { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; }
    for (var i = 0; i < 256; i++) p[i] = i;
    for (i = 255; i > 0; i--) { var r = Math.floor(rnd() * (i + 1)); var t = p[i]; p[i] = p[r]; p[r] = t; }
    for (i = 0; i < 512; i++) { perm[i] = p[i & 255]; permMod12[i] = perm[i] % 12; }
    var F3 = 1 / 3, G3 = 1 / 6;
    return function (xin, yin, zin) {
      var n0, n1, n2, n3;
      var s = (xin + yin + zin) * F3;
      var i = Math.floor(xin + s), j = Math.floor(yin + s), k = Math.floor(zin + s);
      var t = (i + j + k) * G3;
      var x0 = xin - (i - t), y0 = yin - (j - t), z0 = zin - (k - t);
      var i1, j1, k1, i2, j2, k2;
      if (x0 >= y0) {
        if (y0 >= z0) { i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 1; k2 = 0; }
        else if (x0 >= z0) { i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 0; k2 = 1; }
        else { i1 = 0; j1 = 0; k1 = 1; i2 = 1; j2 = 0; k2 = 1; }
      } else {
        if (y0 < z0) { i1 = 0; j1 = 0; k1 = 1; i2 = 0; j2 = 1; k2 = 1; }
        else if (x0 < z0) { i1 = 0; j1 = 1; k1 = 0; i2 = 0; j2 = 1; k2 = 1; }
        else { i1 = 0; j1 = 1; k1 = 0; i2 = 1; j2 = 1; k2 = 0; }
      }
      var x1 = x0 - i1 + G3, y1 = y0 - j1 + G3, z1 = z0 - k1 + G3;
      var x2 = x0 - i2 + 2 * G3, y2 = y0 - j2 + 2 * G3, z2 = z0 - k2 + 2 * G3;
      var x3 = x0 - 1 + 3 * G3, y3 = y0 - 1 + 3 * G3, z3 = z0 - 1 + 3 * G3;
      var ii = i & 255, jj = j & 255, kk = k & 255, g;
      var t0 = 0.6 - x0 * x0 - y0 * y0 - z0 * z0;
      if (t0 < 0) n0 = 0; else { g = permMod12[ii + perm[jj + perm[kk]]] * 3; t0 *= t0; n0 = t0 * t0 * (grad3[g] * x0 + grad3[g + 1] * y0 + grad3[g + 2] * z0); }
      var t1 = 0.6 - x1 * x1 - y1 * y1 - z1 * z1;
      if (t1 < 0) n1 = 0; else { g = permMod12[ii + i1 + perm[jj + j1 + perm[kk + k1]]] * 3; t1 *= t1; n1 = t1 * t1 * (grad3[g] * x1 + grad3[g + 1] * y1 + grad3[g + 2] * z1); }
      var t2 = 0.6 - x2 * x2 - y2 * y2 - z2 * z2;
      if (t2 < 0) n2 = 0; else { g = permMod12[ii + i2 + perm[jj + j2 + perm[kk + k2]]] * 3; t2 *= t2; n2 = t2 * t2 * (grad3[g] * x2 + grad3[g + 1] * y2 + grad3[g + 2] * z2); }
      var t3 = 0.6 - x3 * x3 - y3 * y3 - z3 * z3;
      if (t3 < 0) n3 = 0; else { g = permMod12[ii + 1 + perm[jj + 1 + perm[kk + 1]]] * 3; t3 *= t3; n3 = t3 * t3 * (grad3[g] * x3 + grad3[g + 1] * y3 + grad3[g + 2] * z3); }
      return 32 * (n0 + n1 + n2 + n3);
    };
  }

  var TONES = {
    dark:  { line: [150, 192, 201], a: 0.12, index: 0.26, hot: [244, 132, 95], cool: [46, 156, 148] },
    light: { line: [26, 60, 78],    a: 0.09, index: 0.17, hot: [244, 132, 95], cool: [46, 156, 148] }
  };

  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var finePointer = window.matchMedia && matchMedia('(hover: hover) and (pointer: fine)').matches;

  function mount(canvas) {
    if (canvas.__contours) return canvas.__contours;
    var ctx = canvas.getContext('2d');
    if (!ctx) return null;
    var live = canvas.dataset.contours === 'live' && !reduce;
    var tone = TONES[canvas.dataset.contourTone] || TONES.dark;
    var seed = parseInt(canvas.dataset.contourSeed, 10) || Math.floor(Math.random() * 1e6) + 1;
    var noise = makeNoise(seed);
    var cell = parseFloat(canvas.dataset.contourCell) || (live ? 14 : 12);
    var scale = parseFloat(canvas.dataset.contourScale) || 1;
    var dpr = Math.min(window.devicePixelRatio || 1, 1.75);
    var W = 0, H = 0, cols = 0, rows = 0, field = null;
    var t = seed % 100;
    var visible = true, raf = 0, last = 0, started = performance.now();
    var introMs = live ? 1800 : 0;
    // summit position (smoothed) and strength
    var px = 0.7, py = 0.35, tx = 0.7, ty = 0.35, amp = 0, tamp = live ? 0.55 : 0, pointerIn = false;

    function resize() {
      var r = canvas.getBoundingClientRect();
      W = Math.max(1, r.width); H = Math.max(1, r.height);
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cols = Math.ceil(W / cell) + 2; rows = Math.ceil(H / cell) + 2;
      field = new Float32Array(cols * rows);
      draw(performance.now());
    }

    function sample(now) {
      var f = 0.0021 / scale;
      var sx = px * W, sy = py * H, sig = Math.min(W, H) * 0.22, inv = 1 / (2 * sig * sig);
      for (var j = 0; j < rows; j++) {
        var y = j * cell;
        for (var i = 0; i < cols; i++) {
          var x = i * cell;
          var v = noise(x * f, y * f, t) * 0.9 + noise(x * f * 2.3, y * f * 2.3, t * 1.4 + 7) * 0.35;
          if (amp > 0.001) { var dx = x - sx, dy = y - sy; v += amp * 1.6 * Math.exp(-(dx * dx + dy * dy) * inv); }
          field[j * cols + i] = v;
        }
      }
    }

    function lerp(a, b, l) { return (l - a) / (b - a); }

    function contour(level) {
      ctx.beginPath();
      for (var j = 0; j < rows - 1; j++) {
        var y0 = j * cell, y1 = y0 + cell;
        for (var i = 0; i < cols - 1; i++) {
          var a = field[j * cols + i], b = field[j * cols + i + 1], c = field[(j + 1) * cols + i + 1], d = field[(j + 1) * cols + i];
          var idx = (a > level ? 8 : 0) | (b > level ? 4 : 0) | (c > level ? 2 : 0) | (d > level ? 1 : 0);
          if (idx === 0 || idx === 15) continue;
          var x0 = i * cell, x1 = x0 + cell;
          // edge points: top (a-b), right (b-c), bottom (d-c), left (a-d)
          var tX = x0 + cell * lerp(a, b, level), rY = y0 + cell * lerp(b, c, level);
          var bX = x0 + cell * lerp(d, c, level), lY = y0 + cell * lerp(a, d, level);
          switch (idx) {
            case 1: case 14: ctx.moveTo(x0, lY); ctx.lineTo(bX, y1); break;
            case 2: case 13: ctx.moveTo(bX, y1); ctx.lineTo(x1, rY); break;
            case 3: case 12: ctx.moveTo(x0, lY); ctx.lineTo(x1, rY); break;
            case 4: case 11: ctx.moveTo(tX, y0); ctx.lineTo(x1, rY); break;
            case 5: ctx.moveTo(x0, lY); ctx.lineTo(tX, y0); ctx.moveTo(bX, y1); ctx.lineTo(x1, rY); break;
            case 6: case 9: ctx.moveTo(tX, y0); ctx.lineTo(bX, y1); break;
            case 7: case 8: ctx.moveTo(x0, lY); ctx.lineTo(tX, y0); break;
            case 10: ctx.moveTo(tX, y0); ctx.lineTo(x1, rY); ctx.moveTo(x0, lY); ctx.lineTo(bX, y1); break;
          }
        }
      }
      ctx.stroke();
    }

    function rgba(c, a) { return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }

    function draw(now) {
      if (!field) return;
      sample(now);
      ctx.clearRect(0, 0, W, H);
      ctx.lineJoin = 'round'; ctx.lineCap = 'round';
      var intro = introMs ? Math.min(1, (now - started) / introMs) : 1;
      var sx = px * W, sy = py * H, R = Math.min(W, H) * 0.55;
      var levels = 22, lo = -1.05, step = 0.115;
      for (var k = 0; k < levels; k++) {
        var level = lo + k * step;
        var isIndex = k % 5 === 0;
        // intro: lines rise from the valleys up to the summit
        var la = Math.max(0, Math.min(1, intro * 1.6 - k / levels * 0.6));
        if (la <= 0) continue;
        var base = (isIndex ? tone.index : tone.a) * la;
        if (amp > 0.02) {
          var g = ctx.createRadialGradient(sx, sy, 0, sx, sy, R);
          g.addColorStop(0, rgba(tone.hot, Math.min(0.75, base * 3.2)));
          g.addColorStop(0.35, rgba(tone.cool, base * 1.8));
          g.addColorStop(1, rgba(tone.line, base));
          ctx.strokeStyle = g;
        } else {
          ctx.strokeStyle = rgba(tone.line, base);
        }
        ctx.lineWidth = isIndex ? 1.25 : 0.8;
        contour(level);
      }
    }

    function frame(now) {
      raf = 0;
      if (!visible || document.hidden) return;
      raf = requestAnimationFrame(frame);
      if (now - last < 33) return; // ~30 fps is plenty for drifting terrain
      var dt = Math.min(0.1, (now - last) / 1000); last = now;
      t += dt * 0.045;
      if (!pointerIn) { // let the summit wander on a slow lissajous
        var w = now / 1000;
        tx = 0.62 + Math.sin(w * 0.11) * 0.22; ty = 0.42 + Math.cos(w * 0.083) * 0.2;
      }
      px += (tx - px) * 0.06; py += (ty - py) * 0.06; amp += (tamp - amp) * 0.05;
      draw(now);
    }

    function start() { if (live && !raf) { last = performance.now(); raf = requestAnimationFrame(frame); } }

    if (live) {
      if (finePointer) {
        window.addEventListener('pointermove', function (e) {
          var r = canvas.getBoundingClientRect();
          var x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
          pointerIn = x >= 0 && x <= 1 && y >= 0 && y <= 1;
          if (pointerIn) { tx = x; ty = y; tamp = 0.85; } else { tamp = 0.55; }
        }, { passive: true });
      }
      if ('IntersectionObserver' in window) {
        new IntersectionObserver(function (es) { visible = es[0].isIntersecting; if (visible) start(); }).observe(canvas);
      }
      document.addEventListener('visibilitychange', function () { if (!document.hidden) start(); });
    }

    // static fields still get the slow "rise" once, the first time they scroll into view
    var staticIntro = !live && !reduce && canvas.dataset.contourIntro !== 'off' && 'IntersectionObserver' in window;
    if (staticIntro) {
      introMs = 1600; started = Infinity;
      var introRaf = function (now) { draw(now); if (now - started < introMs) requestAnimationFrame(introRaf); };
      var io = new IntersectionObserver(function (es) {
        if (!es[0].isIntersecting) return;
        io.disconnect(); started = performance.now(); requestAnimationFrame(introRaf);
      }, { rootMargin: '0px 0px -10% 0px' });
      io.observe(canvas);
    }

    var ro = 'ResizeObserver' in window ? new ResizeObserver(function () { resize(); }) : null;
    if (ro) ro.observe(canvas); else window.addEventListener('resize', resize);
    resize();
    start();

    var api = { redraw: function () { draw(performance.now()); }, resize: resize };
    canvas.__contours = api;
    return api;
  }

  window.WanderlyContours = { mount: mount };
  function boot() { document.querySelectorAll('canvas[data-contours]').forEach(mount); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
