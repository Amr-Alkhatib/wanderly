/* Wanderly page enhancements. These only listen and animate: every click
   handler, fetch and filter in the templates keeps doing its own job, and
   this file reacts to what those handlers change (classes, children). */
(function () {
  'use strict';
  var W = (window.W = window.W || {});
  var $ = function (s, root) { return (root || document).querySelector(s); };
  var $$ = function (s, root) { return Array.prototype.slice.call((root || document).querySelectorAll(s)); };
  var anim = function () { return !!window.gsap && !W.reduce; };
  var some = function (a) { return a && a.length; };

  /* ---------- sliding ink for segmented controls ----------
     Follows whichever child carries .active, however it got there. */
  function ink(container, itemSel, kind) {
    if (!container) return;
    var bar = document.createElement('span');
    bar.className = 'seg-ink seg-ink-' + kind;
    bar.setAttribute('aria-hidden', 'true');
    container.insertBefore(bar, container.firstChild);
    container.classList.add('has-ink');
    var first = true;
    function place() {
      var a = $(itemSel + '.active', container);
      if (!a) { bar.style.opacity = 0; return; }
      var props = { x: a.offsetLeft, y: a.offsetTop, width: a.offsetWidth, height: a.offsetHeight, opacity: 1 };
      if (first || !anim()) { first = false; if (window.gsap) gsap.set(bar, props); else bar.style.cssText = 'opacity:1;width:' + props.width + 'px;height:' + props.height + 'px;transform:translate(' + props.x + 'px,' + props.y + 'px)'; }
      else gsap.to(bar, Object.assign(props, { duration: 0.65, ease: 'expo.out', overwrite: true }));
    }
    new MutationObserver(place).observe(container, { attributes: true, attributeFilter: ['class'], subtree: true });
    // controls inside a hidden tab measure as zero; re-place once they get a size
    if ('ResizeObserver' in window) new ResizeObserver(function () { first = true; place(); }).observe(container);
    else window.addEventListener('resize', place);
    if (document.fonts) document.fonts.ready.then(place);
    place();
  }
  ink($('.cp-tab-bar'), '.cp-tab', 'line');
  ink($('.saved-tabs'), '.saved-tab', 'pill');
  ink($('.lt-filter-bar'), '.lt-filter-pill', 'pill');
  ink($('.itin-daytabs'), '.itin-daytab', 'pill');

  /* ---------- replay the "build-up" animations inside a panel ---------- */
  function build(scope) {
    if (!anim()) return;
    $$('.cp-bar-fill', scope).forEach(function (b, i) {
      gsap.fromTo(b, { scaleX: 0 }, { scaleX: 1, duration: 1.3, delay: 0.1 + i * 0.08, ease: 'expo.out', overwrite: true });
    });
    $$('.cp-month-bar', scope).forEach(function (b, i) {
      gsap.fromTo(b, { scaleY: 0 }, { scaleY: 1, duration: 1, delay: 0.15 + i * 0.035, ease: 'expo.out', overwrite: true });
    });
    $$('.strata', scope).forEach(function (s, i) {
      if (some(s.children)) gsap.fromTo(s.children, { scaleX: 0 }, { scaleX: 1, duration: 1.1, stagger: 0.08, delay: 0.1 + i * 0.05, overwrite: true });
    });
    $$('.factor-meter i', scope).forEach(function (b, i) {
      gsap.fromTo(b, { scaleX: 0 }, { scaleX: 1, duration: 1.2, delay: 0.15 + i * 0.07, overwrite: true });
    });
  }

  /* ---------- destination tabs: panel entrance + scroll into place ---------- */
  var tabBar = $('.cp-tab-bar');
  if (tabBar) {
    tabBar.addEventListener('click', function (e) {
      var tab = e.target.closest('.cp-tab');
      if (!tab) return;
      var panel = document.getElementById(tab.dataset.target);
      if (!panel) return;
      // keep the tab bar in view: if the panel starts above the fold, glide back up to it
      var wrapper = $('.cp-tab-bar-wrapper');
      var top = wrapper.getBoundingClientRect().top + window.scrollY - (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--nav-top')) || 14) - 4;
      if (window.scrollY > top + 4) {
        if (W.lenis) W.lenis.scrollTo(top, { duration: 0.9 }); else window.scrollTo({ top: top, behavior: W.reduce ? 'auto' : 'smooth' });
      }
      if (anim()) {
        var blocks = $$('.cp-section, .cp-sidebar > *, .sp-card, .sp-risk-card, .sp-tips-card, .sp-emergency-card, .lt-filter-bar, .lt-section, .itin-head, .itin-daytabs, .itin-layout, .cp-placeholder-state, .cost-tier', panel)
          .filter(function (el) { return el.offsetParent !== null; });
        if (some(blocks)) gsap.fromTo(blocks, { y: 28, opacity: 0 }, { y: 0, opacity: 1, duration: 0.9, stagger: 0.045, ease: 'expo.out', overwrite: true, clearProps: 'transform' });
        build(panel);
      }
      if (window.ScrollTrigger) setTimeout(function () { ScrollTrigger.refresh(); }, 60);
    });
  }

  /* first paint of the visible panel(s) */
  if (anim() && window.ScrollTrigger) {
    $$('.cp-bar-fill').forEach(function (b) { gsap.set(b, { scaleX: 0 }); });
    $$('.cp-month-bar').forEach(function (b) { gsap.set(b, { scaleY: 0 }); });
    $$('.factor-meter i').forEach(function (b) { gsap.set(b, { scaleX: 0 }); });
    $$('.cp-section, .cp-sidebar-card, .cost-tier').forEach(function (sec) {
      ScrollTrigger.create({
        trigger: sec, start: 'top 90%', once: true,
        onEnter: function () {
          $$('.cp-bar-fill', sec).forEach(function (b, i) { gsap.to(b, { scaleX: 1, duration: 1.3, delay: i * 0.08 }); });
          $$('.cp-month-bar', sec).forEach(function (b, i) { gsap.to(b, { scaleY: 1, duration: 1, delay: i * 0.035 }); });
          $$('.factor-meter i', sec).forEach(function (b, i) { gsap.to(b, { scaleX: 1, duration: 1.2, delay: i * 0.07 }); });
        }
      });
    });
    // anything inside a hidden panel is finished off so it is never stuck at zero
    $$('.cp-tab-panel:not(.active)').forEach(function (p) {
      var bars = $$('.cp-bar-fill, .factor-meter i', p), months = $$('.cp-month-bar', p);
      if (some(bars)) gsap.set(bars, { scaleX: 1 });
      if (some(months)) gsap.set(months, { scaleY: 1 });
    });
  }

  /* ---------- filters that hide and show items: let the survivors glide (GSAP Flip) ---------- */
  function flipFilter(bar, triggerSel, itemsSel) {
    if (!bar || !window.Flip || !anim()) return;
    var state = null;
    bar.addEventListener('click', function (e) {
      if (e.target.closest(triggerSel)) state = Flip.getState($$(itemsSel));
    }, true); // capture: runs before the template's own click handler
    bar.addEventListener('click', function (e) {
      if (!state || !e.target.closest(triggerSel)) return;
      Flip.from(state, {
        duration: 0.7, ease: 'expo.out', simple: true,
        onEnter: function (els) { return gsap.fromTo(els, { opacity: 0, y: 24, scale: 0.97 }, { opacity: 1, y: 0, scale: 1, duration: 0.7, stagger: 0.04 }); }
      });
      state = null;
      if (window.ScrollTrigger) setTimeout(function () { ScrollTrigger.refresh(); }, 750);
    });
  }
  flipFilter($('.lt-filter-bar'), '.lt-filter-pill', '.lt-section, .lt-gem-card, .lt-do, .lt-dont, .lt-offbeat-card');
  flipFilter($('.saved-tabs'), '.saved-tab', '.saved-card');

  /* ---------- the itinerary arrives later: give it an entrance ---------- */
  var layout = document.getElementById('itin-layout');
  if (layout) {
    new MutationObserver(function () {
      if (!anim()) return;
      var cards = $$('.itin-card', layout), rowsIn = $$('.itin-row', layout);
      if (some(cards)) gsap.fromTo(cards, { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 1, stagger: 0.09 });
      if (some(rowsIn)) gsap.fromTo(rowsIn, { x: -14, opacity: 0 }, { x: 0, opacity: 1, duration: 0.8, stagger: 0.03, delay: 0.2 });
      var side = $('.itin-summary-card', layout);
      if (side) gsap.fromTo(side, { x: 40, opacity: 0 }, { x: 0, opacity: 1, duration: 1.1, delay: 0.25 });
      if (window.ScrollTrigger) setTimeout(function () { ScrollTrigger.refresh(); }, 80);
    }).observe(layout, { childList: true });
  }
  var overlay = document.getElementById('itin-loading');
  if (overlay) {
    var msg = $('p', overlay);
    new MutationObserver(function () {
      var open = overlay.classList.contains('show');
      if (W.lenis) { if (open) W.lenis.stop(); else W.lenis.start(); }
      if (open && msg && W.decrypt) W.decrypt(msg, { duration: 1.1 });
    }).observe(overlay, { attributes: true, attributeFilter: ['class'] });
  }

  /* ---------- top picks: a photo follows the pointer down the ranked list ---------- */
  var picks = $('.picks-list');
  if (picks && W.fine && anim()) {
    var pv = document.createElement('div');
    pv.className = 'pick-preview';
    pv.setAttribute('aria-hidden', 'true');
    pv.innerHTML = '<img alt="" />';
    document.body.appendChild(pv);
    var img = pv.firstChild;
    var px = gsap.quickTo(pv, 'x', { duration: 0.6, ease: 'power3' });
    var py = gsap.quickTo(pv, 'y', { duration: 0.6, ease: 'power3' });
    var rot = gsap.quickTo(pv, 'rotation', { duration: 0.8, ease: 'power3' });
    var lastX = 0;
    picks.addEventListener('pointermove', function (e) {
      px(e.clientX + 28); py(e.clientY - 150);
      rot(gsap.utils.clamp(-10, 10, (e.clientX - lastX) * 0.6)); lastX = e.clientX;
    });
    $$('.pick-row', picks).forEach(function (row) {
      row.addEventListener('pointerenter', function (e) {
        var src = row.querySelector('.pick-thumb img');
        if (!src) return;
        img.src = src.currentSrc || src.src;
        gsap.set(pv, { x: e.clientX + 28, y: e.clientY - 150 });
        gsap.to(pv, { opacity: 1, scale: 1, duration: 0.5, ease: 'expo.out', overwrite: 'auto' });
      });
      row.addEventListener('pointerleave', function () {
        gsap.to(pv, { opacity: 0, scale: 0.6, duration: 0.4, ease: 'power3.out', overwrite: 'auto' });
      });
    });
  }

  /* ---------- compare: the verdicts decode as they come into view ---------- */
  if (anim() && window.ScrollTrigger) {
    $$('.cmp-verdict-winner').forEach(function (el, i) {
      ScrollTrigger.create({ trigger: el, start: 'top 95%', once: true, onEnter: function () { W.decrypt(el, { delay: i * 0.08 }); } });
    });
  }
})();
