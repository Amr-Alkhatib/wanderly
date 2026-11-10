/* Wanderly contour field.
   Topographic lines from animated simplex noise and marching squares. In "live"
   mode the pointer raises a summit, so wherever you point is the highest ground.

   Performance: this one file is both the page script and its own Web Worker.
   On the page it hands each <canvas> to the worker (OffscreenCanvas), so all the
   noise and line drawing happens off the main thread and never competes with
   scrolling. Browsers without OffscreenCanvas run the same engine on the page.
   Static fields are traced once per size and cached; only live fields animate.

   Usage: <canvas data-contours="live|static" data-contour-tone="dark|light"> */
(function () {
  'use strict';
  var IS_WORKER = typeof window === 'undefined' && typeof self !== 'undefined' && typeof self.postMessage === 'function';

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
  var LEVELS = 22, LO = -1.05, STEP = 0.115;

  /* ======================= the engine (page or worker) ======================= */
  function Field(canvas, o) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.live = !!o.live;
    this.tone = TONES[o.tone] || TONES.dark;
    this.seed = o.seed || 1;
    this.noise = makeNoise(this.seed);
    this.cell = o.cell || (this.live ? 16 : 12);
    this.scale = o.scale || 1;
    this.dpr = o.dpr || 1;
    this.t = this.seed % 100;
    this.W = 1; this.H = 1; this.cols = 0; this.rows = 0;
    this.visible = true;
    // summit (smoothed position and strength)
    this.px = 0.7; this.py = 0.35; this.tx = 0.7; this.ty = 0.35;
    this.amp = 0; this.tamp = this.live ? 0.55 : 0; this.pointerIn = false;
    // intro: live fields rise at once; static ones rise the first time they are seen
    this.introMs = o.intro ? (this.live ? 1800 : 1600) : 0;
    this.started = this.live || !o.intro ? this.now() : Infinity;
    this.introDone = !o.intro;
    this.last = 0; this.poked = 0; this.paused = false;
    // one segment buffer per level, reused every frame
    this.seg = []; this.segN = new Int32Array(LEVELS);
    for (var k = 0; k < LEVELS; k++) this.seg.push(new Float32Array(4096));
  }
  Field.prototype.resize = function (w, h) {
    this.W = Math.max(1, w); this.H = Math.max(1, h);
    this.canvas.width = Math.round(this.W * this.dpr); this.canvas.height = Math.round(this.H * this.dpr);
    this.cols = Math.ceil(this.W / this.cell) + 2; this.rows = Math.ceil(this.H / this.cell) + 2;
    this.field = new Float32Array(this.cols * this.rows);
    this.trace();
    this.draw(this.now());
  };
  Field.prototype.now = function () { return (typeof performance !== 'undefined' ? performance.now() : Date.now()); };
  Field.prototype.sample = function () {
    var f = 0.0021 / this.scale, n = this.noise, t = this.t, cell = this.cell, cols = this.cols, rows = this.rows, field = this.field;
    var sx = this.px * this.W, sy = this.py * this.H, sig = Math.min(this.W, this.H) * 0.22, inv = 1 / (2 * sig * sig), amp = this.amp * 1.6;
    for (var j = 0; j < rows; j++) {
      var y = j * cell, dy = y - sy, row = j * cols;
      for (var i = 0; i < cols; i++) {
        var x = i * cell;
        var v = n(x * f, y * f, t) * 0.9 + n(x * f * 2.3, y * f * 2.3, t * 1.4 + 7) * 0.35;
        if (amp > 0.0016) { var dx = x - sx; v += amp * Math.exp(-(dx * dx + dy * dy) * inv); }
        field[row + i] = v;
      }
    }
  };
  Field.prototype.push = function (k, x0, y0, x1, y1) {
    var b = this.seg[k], n = this.segN[k];
    if (n + 4 > b.length) { var nb = new Float32Array(b.length * 2); nb.set(b); this.seg[k] = b = nb; }
    b[n] = x0; b[n + 1] = y0; b[n + 2] = x1; b[n + 3] = y1; this.segN[k] = n + 4;
  };
  // marching squares in ONE pass over the grid: each cell only visits the levels it spans
  Field.prototype.trace = function () {
    this.sample();
    var cell = this.cell, cols = this.cols, rows = this.rows, F = this.field;
    for (var k = 0; k < LEVELS; k++) this.segN[k] = 0;
    for (var j = 0; j < rows - 1; j++) {
      var y0 = j * cell, y1 = y0 + cell, r0 = j * cols, r1 = r0 + cols;
      for (var i = 0; i < cols - 1; i++) {
        var a = F[r0 + i], b = F[r0 + i + 1], c = F[r1 + i + 1], d = F[r1 + i];
        var mn = a < b ? a : b; if (c < mn) mn = c; if (d < mn) mn = d;
        var mx = a > b ? a : b; if (c > mx) mx = c; if (d > mx) mx = d;
        var kLo = Math.max(0, Math.ceil((mn - LO) / STEP)), kHi = Math.min(LEVELS - 1, Math.floor((mx - LO) / STEP));
        if (kLo > kHi) continue;
        var x0 = i * cell, x1 = x0 + cell;
        for (var k2 = kLo; k2 <= kHi; k2++) {
          var L = LO + k2 * STEP;
          var idx = (a > L ? 8 : 0) | (b > L ? 4 : 0) | (c > L ? 2 : 0) | (d > L ? 1 : 0);
          if (idx === 0 || idx === 15) continue;
          var tX = x0 + cell * (L - a) / (b - a), rY = y0 + cell * (L - b) / (c - b);
          var bX = x0 + cell * (L - d) / (c - d), lY = y0 + cell * (L - a) / (d - a);
          switch (idx) {
            case 1: case 14: this.push(k2, x0, lY, bX, y1); break;
            case 2: case 13: this.push(k2, bX, y1, x1, rY); break;
            case 3: case 12: this.push(k2, x0, lY, x1, rY); break;
            case 4: case 11: this.push(k2, tX, y0, x1, rY); break;
            case 5: this.push(k2, x0, lY, tX, y0); this.push(k2, bX, y1, x1, rY); break;
            case 6: case 9: this.push(k2, tX, y0, bX, y1); break;
            case 7: case 8: this.push(k2, x0, lY, tX, y0); break;
            case 10: this.push(k2, tX, y0, x1, rY); this.push(k2, x0, lY, bX, y1); break;
          }
        }
      }
    }
  };
  function rgba(c, a) { return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }
  Field.prototype.draw = function (now) {
    var ctx = this.ctx, tone = this.tone;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.W, this.H);
    var intro = this.introMs ? Math.min(1, (now - this.started) / this.introMs) : 1;
    if (!(intro > 0)) return;
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    var hot = this.amp > 0.02, grad = null;
    if (hot) {
      // one gradient per frame; each level only changes globalAlpha
      var sx = this.px * this.W, sy = this.py * this.H, R = Math.min(this.W, this.H) * 0.55;
      grad = ctx.createRadialGradient(sx, sy, 0, sx, sy, R);
      grad.addColorStop(0, rgba(tone.hot, 1)); grad.addColorStop(0.35, rgba(tone.cool, 0.56)); grad.addColorStop(1, rgba(tone.line, 0.31));
      ctx.strokeStyle = grad;
    } else ctx.strokeStyle = rgba(tone.line, 1);
    for (var k = 0; k < LEVELS; k++) {
      var n = this.segN[k]; if (!n) continue;
      var la = Math.max(0, Math.min(1, intro * 1.6 - k / LEVELS * 0.6));
      if (la <= 0) continue;
      var isIndex = k % 5 === 0, base = (isIndex ? tone.index : tone.a) * la;
      ctx.globalAlpha = hot ? Math.min(1, base * 3.2) : base;
      ctx.lineWidth = isIndex ? 1.25 : 0.8;
      var b = this.seg[k];
      ctx.beginPath();
      for (var q = 0; q < n; q += 4) { ctx.moveTo(b[q], b[q + 1]); ctx.lineTo(b[q + 2], b[q + 3]); }
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    if (intro >= 1) this.introDone = true;
  };
  Field.prototype.show = function (v, now) {
    this.visible = v;
    if (v && this.started === Infinity) this.started = now; // static intro, first time on screen
  };
  Field.prototype.pointer = function (x, y, inside) {
    this.pointerIn = inside; this.poked = this.now();
    if (inside) { this.tx = x; this.ty = y; this.tamp = 0.85; } else this.tamp = 0.55;
  };
  Field.prototype.wants = function () {
    return this.visible && !this.paused && (this.live || (!this.introDone && this.started !== Infinity));
  };
  Field.prototype.frame = function (now) {
    if (!this.live) { this.draw(now); return; }
    // 25 fps while the pointer is steering the summit; the slow idle drift needs only half that
    if (now - this.last < (now - this.poked < 1500 || now - this.started < 2500 ? 40 : 80)) return;
    var dt = Math.min(0.1, (now - this.last) / 1000); this.last = now;
    this.t += dt * 0.045;
    if (!this.pointerIn) {
      var w = now / 1000;
      this.tx = 0.62 + Math.sin(w * 0.11) * 0.22; this.ty = 0.42 + Math.cos(w * 0.083) * 0.2;
    }
    this.px += (this.tx - this.px) * 0.07; this.py += (this.ty - this.py) * 0.07; this.amp += (this.tamp - this.amp) * 0.06;
    this.trace();
    this.draw(now);
  };

  /* ======================= worker side ======================= */
  if (IS_WORKER) {
    var fields = {}, running = false, pageHidden = false;
    var raf = self.requestAnimationFrame ? self.requestAnimationFrame.bind(self)
      : function (cb) { return setTimeout(function () { cb(performance.now()); }, 33); };
    var tick = function (now) {
      var any = false;
      if (!pageHidden) for (var id in fields) { var f = fields[id]; if (f.wants()) { f.frame(now); any = true; } }
      if (any) raf(tick); else running = false;
    };
    var kick = function () { if (!running) { running = true; raf(tick); } };
    self.onmessage = function (e) {
      var m = e.data, f = fields[m.id];
      if (m.type === 'add') { f = fields[m.id] = new Field(m.canvas, m.opts); f.resize(m.w, m.h); kick(); return; }
      if (m.type === 'page') { pageHidden = m.hidden; if (!pageHidden) kick(); return; }
      if (!f) return;
      if (m.type === 'size') f.resize(m.w, m.h);
      else if (m.type === 'visible') { f.show(m.v, performance.now()); if (m.v) kick(); }
      else if (m.type === 'pointer') f.pointer(m.x, m.y, m.inside);
      else if (m.type === 'pause') { f.paused = m.v; if (!m.v) kick(); }
    };
    return;
  }

  /* ======================= page side ======================= */
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var finePointer = window.matchMedia && matchMedia('(hover: hover) and (pointer: fine)').matches;
  var src = document.currentScript && document.currentScript.src;
  var canWorker = !!(src && window.Worker && window.OffscreenCanvas && HTMLCanvasElement.prototype.transferControlToOffscreen);
  var worker = null, workerFailed = false, nextId = 1, handed = [];
  function getWorker() {
    if (worker || workerFailed) return worker;
    try { worker = new Worker(src); } catch (err) { workerFailed = true; return null; } // e.g. static files on another origin
    // If the worker cannot start, every canvas it was given is redrawn on the page instead.
    worker.addEventListener('error', function () {
      var w = worker; worker = null; workerFailed = true;
      try { w.terminate(); } catch (err) {}
      handed.splice(0).forEach(function (old) {
        var fresh = old.cloneNode(false);
        if (old.parentNode) { old.parentNode.replaceChild(fresh, old); mount(fresh); }
      });
    });
    document.addEventListener('visibilitychange', function () { if (worker) worker.postMessage({ type: 'page', hidden: document.hidden }); });
    return worker;
  }

  function mount(canvas) {
    if (canvas.__contours) return canvas.__contours;
    var live = canvas.dataset.contours === 'live' && !reduce;
    var opts = {
      live: live,
      tone: canvas.dataset.contourTone,
      seed: parseInt(canvas.dataset.contourSeed, 10) || Math.floor(Math.random() * 1e6) + 1,
      cell: parseFloat(canvas.dataset.contourCell) || 0,
      scale: parseFloat(canvas.dataset.contourScale) || 1,
      // the animated field is capped below full retina density (soft, moving lines don't need it);
      // fields that are drawn once stay crisp
      dpr: Math.min(window.devicePixelRatio || 1, live ? 1.5 : 2),
      intro: !reduce && canvas.dataset.contourIntro !== 'off'
    };
    var r = canvas.getBoundingClientRect();
    var api;
    var w = canWorker ? getWorker() : null; // the worker must exist before a canvas is handed over
    if (w) {
      var id = nextId++, off = canvas.transferControlToOffscreen();
      w.postMessage({ type: 'add', id: id, canvas: off, opts: opts, w: r.width, h: r.height }, [off]);
      handed.push(canvas);
      var post = function (m) { if (worker === w) w.postMessage(m); };
      api = {
        resize: function (wd, ht) { post({ type: 'size', id: id, w: wd, h: ht }); },
        show: function (v) { post({ type: 'visible', id: id, v: v }); },
        pointer: function (x, y, inside) { post({ type: 'pointer', id: id, x: x, y: y, inside: inside }); },
        pause: function (v) { post({ type: 'pause', id: id, v: v }); }
      };
    } else api = mainThread(canvas, opts, r);
    canvas.__contours = api;

    // keep the field sized to its box, and only animate it while it is on screen
    var lastW = r.width, lastH = r.height;
    if ('ResizeObserver' in window) new ResizeObserver(function (es) {
      var b = es[0].contentRect;
      if (Math.abs(b.width - lastW) < 1 && Math.abs(b.height - lastH) < 1) return;
      lastW = b.width; lastH = b.height; api.resize(b.width, b.height);
    }).observe(canvas);
    if ('IntersectionObserver' in window) new IntersectionObserver(function (es) { api.show(es[0].isIntersecting); }, { rootMargin: '0px 0px -8% 0px' }).observe(canvas);
    else api.show(true);
    if (live) {
      // While the page is scrolling the drift is invisible anyway: hold it, and give the frame to the scroll.
      var scrolling = false, stopTimer = 0;
      window.addEventListener('scroll', function () {
        if (!scrolling) { scrolling = true; api.pause(true); }
        clearTimeout(stopTimer);
        stopTimer = setTimeout(function () { scrolling = false; api.pause(false); }, 180);
      }, { passive: true });
    }
    if (live && finePointer) {
      var pending = null;
      window.addEventListener('pointermove', function (e) {
        if (pending) { pending = e; return; }
        pending = e;
        requestAnimationFrame(function () {
          var ev = pending; pending = null;
          var b = canvas.getBoundingClientRect();
          if (b.bottom < 0 || b.top > window.innerHeight) return;
          var x = (ev.clientX - b.left) / b.width, y = (ev.clientY - b.top) / b.height;
          api.pointer(x, y, x >= 0 && x <= 1 && y >= 0 && y <= 1);
        });
      }, { passive: true });
    }
    return api;
  }

  // fallback: same engine on the page, driven by requestAnimationFrame
  function mainThread(canvas, opts, r) {
    var f = new Field(canvas, opts), running = false;
    f.resize(r.width, r.height);
    var loop = function (now) {
      if (!document.hidden && f.wants()) { f.frame(now); requestAnimationFrame(loop); } else running = false;
    };
    var kick = function () { if (!running) { running = true; requestAnimationFrame(loop); } };
    document.addEventListener('visibilitychange', kick);
    return {
      resize: function (w, h) { f.resize(w, h); },
      show: function (v) { f.show(v, performance.now()); if (v) kick(); },
      pointer: function (x, y, inside) { f.pointer(x, y, inside); },
      pause: function (v) { f.paused = v; if (!v) kick(); }
    };
  }

  window.WanderlyContours = { mount: mount };
  function boot() { document.querySelectorAll('canvas[data-contours]').forEach(mount); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
