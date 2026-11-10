/* Wanderly bits: vanilla ports of React Bits components (reactbits.dev),
   rebuilt on GSAP so they run in Django templates without a React runtime.
   Each one is a small function on window.W that takes an element. */
(function () {
  'use strict';
  var W = (window.W = window.W || {});
  var mq = function (q) { return window.matchMedia && window.matchMedia(q).matches; };
  W.reduce = mq('(prefers-reduced-motion: reduce)');
  W.fine = mq('(hover: hover) and (pointer: fine)');
  var ok = function () { return !!window.gsap && !W.reduce; };

  /* ---- SplitText (React Bits <SplitText>): masked lines or chars rise into place ---- */
  W.splitReveal = function (el, o) {
    o = o || {};
    if (!ok() || !window.SplitText) { el.classList.add('is-split'); return; }
    var mode = el.dataset.split === 'chars' ? 'chars' : 'lines';
    var run = function () {
      SplitText.create(el, {
        type: mode === 'chars' ? 'chars,words,lines' : 'words,lines',
        mask: 'lines',
        linesClass: 'split-line',
        autoSplit: true,
        onSplit: function (self) {
          el.classList.add('is-split');
          var targets = mode === 'chars' ? self.chars : self.lines;
          return gsap.from(targets, {
            yPercent: 118, rotate: mode === 'chars' ? 4 : 0, duration: o.duration || 1.15, ease: 'expo.out',
            stagger: mode === 'chars' ? 0.022 : 0.085, delay: o.delay || 0,
            scrollTrigger: o.scroll === false ? undefined : { trigger: el, start: 'top 88%', once: true }
          });
        }
      });
    };
    // split after fonts settle so line breaks match the final typeface
    if (document.fonts && document.fonts.status !== 'loaded') {
      Promise.race([document.fonts.ready, new Promise(function (r) { setTimeout(r, 900); })]).then(run);
    } else run();
  };

  /* ---- BlurText (React Bits <BlurText>): the sentence comes out of the blur word by word.
          The words fade and rise one by one; the blur itself is ONE layer on the whole
          paragraph, because a filter per word is exactly what makes a laptop GPU stutter. ---- */
  W.blurText = function (el, o) {
    o = o || {};
    if (!ok() || !window.SplitText) { el.style.opacity = 1; return; }
    var split = SplitText.create(el, { type: 'words' });
    gsap.set(el, { opacity: 1 });
    gsap.fromTo(el, { filter: 'blur(9px)' }, { filter: 'blur(0px)', duration: 1.2, ease: 'power2.out', delay: o.delay || 0, clearProps: 'filter' });
    return gsap.from(split.words, {
      opacity: 0, y: 8, duration: 0.9, ease: 'power3.out',
      stagger: o.stagger || 0.035, delay: o.delay || 0
    });
  };

  /* ---- CountUp (React Bits <CountUp>) ---- */
  W.countUp = function (el, o) {
    o = o || {};
    var m = (el.textContent || '').trim().match(/^(\D*?)(\d[\d,]*)(.*)$/);
    if (!m || !ok()) return;
    var prefix = m[1], target = parseInt(m[2].replace(/,/g, ''), 10), suffix = m[3];
    if (!isFinite(target)) return;
    var obj = { v: 0 };
    el.textContent = prefix + '0' + suffix;
    return gsap.to(obj, {
      v: target, duration: o.duration || 1.6, ease: 'power3.out', delay: o.delay || 0,
      scrollTrigger: o.scroll === false ? undefined : { trigger: el, start: 'top 92%', once: true },
      onUpdate: function () { el.textContent = prefix + Math.round(obj.v) + suffix; },
      onComplete: function () { el.textContent = prefix + target + suffix; }
    });
  };

  /* ---- ScrollVelocity (React Bits <ScrollVelocity>): marquee rows that speed up,
          and turn around, with the scroll. One transform write per row per frame. ---- */
  W.scrollVelocity = function (root) {
    var rows = Array.prototype.slice.call(root.querySelectorAll('.marquee-row'));
    if (!rows.length || !ok()) return;
    var state = rows.map(function (row, i) {
      var group = row.firstElementChild;
      // repeat the group until the row is at least two screens wide
      var w = group.getBoundingClientRect().width || 1;
      var copies = Math.max(2, Math.ceil((window.innerWidth * 2) / w) + 1);
      for (var c = 1; c < copies; c++) {
        var clone = group.cloneNode(true);
        clone.setAttribute('aria-hidden', 'true');
        clone.querySelectorAll('a').forEach(function (a) { a.tabIndex = -1; });
        row.appendChild(clone);
      }
      return { row: row, w: w, x: i % 2 ? -w : 0, dir: i % 2 ? 1 : -1, base: parseFloat(row.dataset.speed) || 60 };
    });
    var vel = 0, smooth = 0, sign = 1, visible = false, skew = 0;
    ScrollTrigger.create({
      trigger: root, start: 'top bottom', end: 'bottom top',
      onUpdate: function (self) { vel = self.getVelocity(); if (vel) sign = vel > 0 ? 1 : -1; },
      onToggle: function (self) { visible = self.isActive; }
    });
    gsap.ticker.add(function (time, dt) {
      if (!visible) return;
      smooth += (vel - smooth) * 0.08; vel *= 0.9;
      var boost = 1 + Math.min(6, Math.abs(smooth) / 260);
      var s = Math.min(dt, 50) / 1000;
      skew += (gsap.utils.clamp(-8, 8, -smooth / 320) - skew) * 0.12;
      var sk = Math.abs(skew) > 0.02 ? ' skewX(' + skew.toFixed(2) + 'deg)' : '';
      for (var i = 0; i < state.length; i++) {
        var st = state[i];
        st.x += st.dir * sign * st.base * boost * s;
        st.x = gsap.utils.wrap(-st.w, 0, st.x);
        st.row.style.transform = 'translate3d(' + st.x.toFixed(1) + 'px,0,0)' + sk;
      }
    });
  };

  /* pointer handlers read the latest position once per frame, never once per event */
  function perFrame(fn) {
    var ev = null;
    return function (e) {
      if (ev) { ev = e; return; }
      ev = e;
      requestAnimationFrame(function () { var x = ev; ev = null; fn(x); });
    };
  }

  /* ---- TiltedCard (React Bits <TiltedCard>). Set up lazily, on first hover. ---- */
  W.tilt = function (el, o) {
    if (!ok() || !W.fine) return;
    o = o || {};
    var max = o.max || 7, rx, ry, sc, rect = null;
    el.addEventListener('pointerenter', function () {
      if (!rx) {
        gsap.set(el, { transformPerspective: 1000 });
        rx = gsap.quickTo(el, 'rotationX', { duration: 0.6, ease: 'power3' });
        ry = gsap.quickTo(el, 'rotationY', { duration: 0.6, ease: 'power3' });
        sc = gsap.quickTo(el, 'scale', { duration: 0.6, ease: 'power3' });
      }
      rect = el.getBoundingClientRect(); // measured once per hover, not per move
      el.style.willChange = 'transform';
    });
    el.addEventListener('pointermove', perFrame(function (e) {
      if (!rect || !rx) return;
      var x = (e.clientX - rect.left) / rect.width, y = (e.clientY - rect.top) / rect.height;
      ry((x - 0.5) * max * 2); rx((0.5 - y) * max * 2); sc(o.scale || 1.015);
      el.style.setProperty('--gx', (x * 100).toFixed(1) + '%'); el.style.setProperty('--gy', (y * 100).toFixed(1) + '%');
    }));
    el.addEventListener('pointerleave', function () {
      rect = null;
      if (rx) { rx(0); ry(0); sc(1); }
      setTimeout(function () { if (!rect) el.style.willChange = ''; }, 700);
    });
    window.addEventListener('scroll', function () { if (rect) rect = el.getBoundingClientRect(); }, { passive: true });
  };

  /* ---- SpotlightCard (React Bits <SpotlightCard>) ---- */
  W.spotlight = function (el) {
    if (!W.fine) return;
    el.addEventListener('pointermove', perFrame(function (e) {
      var r = el.getBoundingClientRect();
      el.style.setProperty('--mx', (e.clientX - r.left).toFixed(0) + 'px');
      el.style.setProperty('--my', (e.clientY - r.top).toFixed(0) + 'px');
    }));
  };

  /* ---- Magnet (React Bits <Magnet>) ---- */
  var magnets = [];
  W.magnet = function (el, o) {
    if (!ok() || !W.fine) return;
    o = o || {};
    magnets.push({
      el: el, pad: o.padding || 60, strength: o.strength || 3.2, on: false,
      x: gsap.quickTo(el, 'x', { duration: 0.5, ease: 'power3' }),
      y: gsap.quickTo(el, 'y', { duration: 0.5, ease: 'power3' })
    });
    if (magnets.length === 1) {
      window.addEventListener('pointermove', perFrame(function (e) {
        for (var i = 0; i < magnets.length; i++) {
          var m = magnets[i], r = m.el.getBoundingClientRect();
          var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
          var near = Math.abs(e.clientX - cx) < r.width / 2 + m.pad && Math.abs(e.clientY - cy) < r.height / 2 + m.pad;
          if (!near && !m.on) continue; // far away and already at rest: nothing to write
          m.on = near;
          m.x(near ? (e.clientX - cx) / m.strength : 0); m.y(near ? (e.clientY - cy) / m.strength : 0);
        }
      }), { passive: true });
    }
  };

  /* ---- ClickSpark (React Bits <ClickSpark>) ---- */
  var layer;
  W.clickSpark = function (x, y, o) {
    if (!ok()) return;
    o = o || {};
    if (!layer) {
      layer = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      layer.setAttribute('class', 'spark-layer'); layer.setAttribute('aria-hidden', 'true');
      layer.setAttribute('width', '100%'); layer.setAttribute('height', '100%');
      document.body.appendChild(layer);
    }
    var n = o.count || 9, color = o.color || '#F4845F', r0 = 8, r1 = o.radius || 30;
    for (var i = 0; i < n; i++) {
      var a = (Math.PI * 2 * i) / n + Math.random() * 0.25;
      var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('stroke', i % 3 === 2 ? '#2E9C94' : color);
      line.setAttribute('stroke-width', '2.2'); line.setAttribute('stroke-linecap', 'round');
      var cos = Math.cos(a), sin = Math.sin(a);
      var p = { a: r0, b: r0 };
      (function (line, cos, sin, p) {
        layer.appendChild(line);
        gsap.timeline({ onComplete: function () { line.remove(); } })
          .to(p, { b: r1, duration: 0.42, ease: 'power3.out' }, 0)
          .to(p, { a: r1, duration: 0.42, ease: 'power2.in' }, 0.08)
          .eventCallback('onUpdate', function () {
            line.setAttribute('x1', x + cos * p.a); line.setAttribute('y1', y + sin * p.a);
            line.setAttribute('x2', x + cos * p.b); line.setAttribute('y2', y + sin * p.b);
          });
      })(line, cos, sin, p);
    }
  };

  /* ---- DecryptedText (React Bits <DecryptedText>) ---- */
  var GLYPHS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ';
  W.decrypt = function (el, o) {
    if (!ok()) return;
    o = o || {};
    var final = el.dataset.final || el.textContent;
    el.dataset.final = final;
    if (!el.getAttribute('aria-label')) el.setAttribute('aria-label', final);
    var prog = { p: 0 };
    return gsap.to(prog, {
      p: 1, duration: o.duration || Math.min(1.4, 0.35 + final.length * 0.04), ease: 'none', delay: o.delay || 0,
      onUpdate: function () {
        var shown = Math.floor(prog.p * final.length), out = '';
        for (var i = 0; i < final.length; i++) {
          var ch = final[i];
          out += i < shown || ch === ' ' ? ch : GLYPHS[(Math.random() * GLYPHS.length) | 0];
        }
        el.textContent = out;
      },
      onComplete: function () { el.textContent = final; }
    });
  };

  /* ---- CircularText (React Bits <CircularText>): spins, and speeds up on hover.
          A Web Animation, so the endless spin runs on the compositor, not in JavaScript. ---- */
  W.circularText = function (el) {
    var svg = el.querySelector('.orbit-text');
    if (!svg || W.reduce || !svg.animate) return;
    var spin = svg.animate([{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }], { duration: 26000, iterations: Infinity, easing: 'linear' });
    el.addEventListener('pointerenter', function () { spin.updatePlaybackRate(5); });
    el.addEventListener('pointerleave', function () { spin.updatePlaybackRate(1); });
  };
})();
