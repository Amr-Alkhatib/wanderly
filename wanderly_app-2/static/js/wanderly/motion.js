/* Wanderly motion: one GSAP clock drives Lenis, ScrollTrigger and every reveal.
   Phones keep native scrolling; reduced-motion visitors get the finished page. */
(function () {
  'use strict';
  var W = (window.W = window.W || {});
  var html = document.documentElement;
  var $$ = function (s, root) { return Array.prototype.slice.call((root || document).querySelectorAll(s)); };

  /* ---------- mobile menu (works without GSAP) ---------- */
  (function menu() {
    var btn = document.querySelector('.nav-menu-btn'), sheet = document.getElementById('nav-sheet');
    if (!btn || !sheet) return;
    function set(open) {
      btn.setAttribute('aria-expanded', String(open));
      btn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
      sheet.classList.toggle('open', open);
      document.body.classList.toggle('sheet-open', open);
      if (W.lenis) { if (open) W.lenis.stop(); else W.lenis.start(); }
      if (open && window.gsap && !W.reduce) {
        gsap.fromTo($$('.nav-sheet-links li, .nav-sheet-search, .nav-sheet-foot', sheet),
          { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.8, ease: 'expo.out', stagger: 0.05, delay: 0.12 });
      }
    }
    btn.addEventListener('click', function () { set(btn.getAttribute('aria-expanded') !== 'true'); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && sheet.classList.contains('open')) { set(false); btn.focus(); }
    });
    sheet.addEventListener('click', function (e) { if (e.target.closest('a')) set(false); });
    window.matchMedia('(min-width: 981px)').addEventListener('change', function (e) { if (e.matches) set(false); });
  })();

  /* ---------- "/" focuses search ---------- */
  document.addEventListener('keydown', function (e) {
    if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.closest && e.target.closest('input, textarea, select, [contenteditable]')) return;
    var input = document.querySelector('.hero-search input') || document.querySelector('.nav-search input');
    if (input && input.offsetParent) { e.preventDefault(); input.focus(); }
  });

  if (!window.gsap) { html.classList.remove('motion-ok'); return; }
  window.__wanderly = true;
  var plugins = [window.ScrollTrigger, window.SplitText, window.Flip, window.CustomEase].filter(Boolean);
  gsap.registerPlugin.apply(gsap, plugins);
  if (window.ScrollTrigger) ScrollTrigger.config({ ignoreMobileResize: true });
  gsap.defaults({ ease: 'expo.out', duration: 1 });

  function safe(fn) {
    try { fn(); } catch (err) {
      html.classList.remove('motion-ok');
      if (window.console) console.warn('[wanderly] motion step skipped:', err);
    }
  }
  var arriving = html.classList.contains('pt-arrive');
  var t0 = arriving ? 0.45 : 0.08;
  var fontsReady = document.fonts ? Promise.race([document.fonts.ready, new Promise(function (r) { setTimeout(r, 1200); })]) : Promise.resolve();

  /* ---------- smooth scroll (Lenis on a fine pointer only) ---------- */
  safe(function () {
    if (W.reduce || !W.fine || !window.Lenis || !window.ScrollTrigger) return;
    var lenis = new Lenis({ lerp: 0.1, smoothWheel: true });
    W.lenis = lenis;
    lenis.on('scroll', ScrollTrigger.update);
    gsap.ticker.add(function (t) { lenis.raf(t * 1000); });
    gsap.ticker.lagSmoothing(0);
    document.addEventListener('click', function (e) {
      if (e.defaultPrevented) return;
      var a = e.target.closest && e.target.closest('a[href^="#"]');
      if (!a) return;
      var id = a.getAttribute('href');
      if (id.length < 2) return;
      var target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      lenis.scrollTo(target, { offset: -110, duration: 1.3 });
    });
  });

  /* ---------- page transitions ---------- */
  safe(function () {
    if (W.reduce) return;
    document.addEventListener('click', function (e) {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      var a = e.target.closest && e.target.closest('a[href]');
      if (!a || (a.target && a.target !== '_self') || a.hasAttribute('download') || a.hasAttribute('data-no-transition')) return;
      var href = a.getAttribute('href');
      if (!href || href.charAt(0) === '#' || /^(javascript|mailto|tel):/i.test(href)) return;
      var url = new URL(a.href, location.href);
      if (url.origin !== location.origin) return;
      if (url.pathname === location.pathname && url.search === location.search) return;
      e.preventDefault();
      try { sessionStorage.setItem('w:pt', '1'); } catch (err) {}
      html.classList.add('pt-leaving');
      setTimeout(function () { location.href = url.href; }, 470);
    });
    window.addEventListener('pageshow', function (e) {
      if (e.persisted) html.classList.remove('pt-leaving', 'pt-arrive');
    });
    if (arriving) setTimeout(function () { html.classList.remove('pt-arrive'); }, 1300);
  });

  /* ---------- nav: hide on the way down, back on the way up, progress line ---------- */
  safe(function () {
    var nav = document.querySelector('[data-nav]');
    if (!nav || !window.ScrollTrigger) return;
    var bar = nav.querySelector('.nav-progress');
    ScrollTrigger.create({
      start: 0, end: 'max',
      onUpdate: function (self) {
        var y = self.scroll();
        nav.classList.toggle('is-scrolled', y > 30);
        nav.classList.toggle('is-hidden', self.direction === 1 && y > 260 && !document.body.classList.contains('sheet-open'));
        if (bar) bar.style.transform = 'scaleX(' + self.progress.toFixed(4) + ')';
      }
    });
  });

  /* ---------- the home hero: the one orchestrated moment ---------- */
  safe(function () {
    var hero = document.querySelector('.hero');
    if (!hero) return;
    var h1 = hero.querySelector('h1[data-split]');
    if (h1) W.splitReveal(h1, { scroll: false, delay: t0, duration: 1.3 });
    var sub = hero.querySelector('[data-blur]');
    if (sub) W.blurText(sub, { delay: t0 + 0.5 });
    var items = $$('[data-hero]', hero);
    if (!items.length) {} else if (!W.reduce) {
      gsap.fromTo(items, { y: 26, opacity: 0 }, { y: 0, opacity: 1, duration: 1.1, stagger: 0.09, delay: t0 + 0.65 });
    } else gsap.set(items, { opacity: 1 });
    var card = hero.querySelector('.rank-card');
    if (card && !W.reduce) {
      var rows = $$('.rank-row', card);
      var tl = gsap.timeline({ delay: t0 + 0.55 });
      tl.from(card, { y: 50, opacity: 0, rotate: 1.5, duration: 1.3 })
        .from(rows, { x: 30, opacity: 0, stagger: 0.08, duration: 0.9 }, 0.25);
      rows.forEach(function (row, i) {
        tl.fromTo(row.querySelectorAll('.strata-seg'), { scaleX: 0 }, { scaleX: 1, stagger: 0.09, duration: 1, ease: 'expo.out' }, 0.45 + i * 0.08);
        var n = row.querySelector('[data-count]');
        if (n) { tl.add(W.countUp(n, { scroll: false, duration: 1.4 }) || function () {}, 0.45 + i * 0.08); n.removeAttribute('data-count'); }
      });
      $$('.strata', card).forEach(function (s) { s.setAttribute('data-done', ''); });
    }
    var orbit = hero.querySelector('.orbit');
    if (orbit) {
      W.circularText(orbit);
      if (!W.reduce) gsap.from(orbit, { scale: 0.4, opacity: 0, rotate: -90, duration: 1.4, delay: t0 + 1.1 });
    }
  });

  /* ---------- headings split into masked lines as they scroll in ---------- */
  safe(function () {
    $$('[data-split]').forEach(function (el) {
      if (el.closest('.hero')) return;
      var immediate = el.hasAttribute('data-split-now');
      W.splitReveal(el, { scroll: !immediate, delay: immediate ? t0 : 0 });
    });
  });

  /* ---------- blocks rise in, in batches ---------- */
  safe(function () {
    var els = $$('[data-reveal]');
    if (!els.length) return;
    if (W.reduce || !window.ScrollTrigger) { gsap.set(els, { opacity: 1 }); return; }
    gsap.set(els, { y: 34 });
    ScrollTrigger.batch(els, {
      start: 'top 92%', once: true,
      onEnter: function (batch) {
        gsap.to(batch, {
          opacity: 1, y: 0, duration: 1.1, stagger: 0.08, overwrite: true,
          // hand transforms back to CSS hovers, except where the tilt effect owns them
          onComplete: function () { batch.forEach(function (el) { if (!el.hasAttribute('data-tilt')) gsap.set(el, { clearProps: 'transform' }); }); }
        });
      }
    });
  });

  /* ---------- strata bars build up segment by segment ---------- */
  safe(function () {
    var bars = $$('.strata').filter(function (s) { return !s.hasAttribute('data-done'); });
    if (!bars.length || W.reduce || !window.ScrollTrigger) return;
    bars = bars.filter(function (s) { return s.children.length; });
    if (!bars.length) return;
    bars.forEach(function (s) { gsap.set(s.children, { scaleX: 0 }); });
    ScrollTrigger.batch(bars, {
      start: 'top 94%', once: true,
      onEnter: function (batch) {
        batch.forEach(function (s, i) {
          gsap.to(s.children, { scaleX: 1, duration: 1.1, stagger: 0.08, delay: i * 0.05, ease: 'expo.out' });
        });
      }
    });
  });

  /* ---------- numbers count up ---------- */
  safe(function () { $$('[data-count]').forEach(function (el) { W.countUp(el); }); });

  /* ---------- parallax media ---------- */
  safe(function () {
    if (W.reduce || !window.ScrollTrigger) return;
    $$('[data-parallax]').forEach(function (el) {
      var host = el.closest('section, header, .cp-hero') || el.parentElement;
      gsap.fromTo(el, { yPercent: 0, scale: 1.08 }, {
        yPercent: parseFloat(el.dataset.parallax) || 14, scale: 1.14, ease: 'none',
        scrollTrigger: { trigger: host, start: 'top top', end: 'bottom top', scrub: true }
      });
    });
  });

  /* ---------- pointer toys: tilt, spotlight, magnet ---------- */
  safe(function () {
    $$('[data-tilt]').forEach(function (el) { W.tilt(el, { max: parseFloat(el.dataset.tilt) || 6 }); });
    $$('[data-spotlight]').forEach(W.spotlight);
    $$('[data-magnet]').forEach(function (el) { W.magnet(el); });
  });

  /* ---------- marquee ---------- */
  fontsReady.then(function () { safe(function () { $$('[data-velocity]').forEach(W.scrollVelocity); }); });

  /* ---------- sparks when something gets saved ---------- */
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.trip-save-btn, .saved-btn-complete, [data-spark]');
    if (!b || W.reduce) return;
    // the template's own handler has already run; a button that was saved is being unsaved
    if (b.classList.contains('trip-save-btn') && b.classList.contains('saved')) return;
    var x = e.clientX, y = e.clientY;
    if (!x && !y) { var r = b.getBoundingClientRect(); x = r.left + r.width / 2; y = r.top + r.height / 2; }
    W.clickSpark(x, y);
  });

  window.addEventListener('load', function () { if (window.ScrollTrigger) ScrollTrigger.refresh(); });
})();
