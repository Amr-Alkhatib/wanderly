/* Wanderly compass.
   A pocket compass built entirely from code: lathe profiles, extruded shapes and
   canvas-drawn faces, lit by a small photo studio baked into the environment.
   Its five parts are the five parts of a Wanderly score, and the scroll takes it
   apart on camera:
     glass crystal   -> the why (the plain-language explanation)
     teal bezel      -> safety
     blued needle    -> interests
     gold rose dial  -> climate
     copper case     -> budget
   The verb: hold to find north. The needle spins up, ticks, and settles. */
let THREE = null; // three.js is fetched and parsed only when the scene is about to be built

const html = document.documentElement;
const section = document.querySelector('[data-inside]');
const W = window.W || {};
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const lite = matchMedia('(hover: none), (max-width: 899px)').matches;
const isMobile = () => matchMedia('(max-width: 899px)').matches;
const D2R = Math.PI / 180;
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const ease = (t) => { t = clamp(t); return t * t * (3 - 2 * t); };
const KEYS = ['polar', 'az', 'fit', 'ty', 'explode', 'env'];
const mix = (a, b, t) => { const o = {}; for (const k of KEYS) o[k] = a[k] + (b[k] - a[k]) * t; return o; };

/* camera cues, framed by size (mm on screen), not distance, so phones and monitors match */
const SHOTS = {
  enter:   { polar: 32, az: 16, fit: 0.86, ty: 5, explode: 0, env: -0.6 },
  lift:    { polar: 46, az: 24, fit: 0.86, ty: 9, explode: 0.06, env: -0.2 },
  apart:   { polar: 70, az: 30, fit: 0.9, ty: 29, explode: 1, env: 0.5 },
  rebuild: { polar: 16, az: 6, fit: 0.88, ty: 5, explode: 0, env: -0.4 },
};


function fail(err) {
  html.classList.remove('webgl');
  html.classList.add('no-webgl');
  if (err && window.console) console.warn('[wanderly] compass disabled:', err);
}

function hasRealGPU() {
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl2', { failIfMajorPerformanceCaveat: true }) || c.getContext('webgl', { failIfMajorPerformanceCaveat: true });
    if (!gl) return false;
    const info = gl.getExtension('WEBGL_debug_renderer_info');
    const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : '';
    const lose = gl.getExtension('WEBGL_lose_context'); if (lose) lose.loseContext();
    return !/swiftshader|llvmpipe|softpipe|software|basic render/i.test(name);
  } catch (e) { return false; }
}

// Setup runs in small steps, and only while the page is NOT being scrolled: each step waits for
// the scroll to go quiet and for an idle moment, so building the scene never lands on a scrolled frame.
let lastScroll = 0;
window.addEventListener('scroll', () => { lastScroll = performance.now(); }, { passive: true });
const idle = () => new Promise((r) => {
  const attempt = () => {
    if (performance.now() - lastScroll < 250) { setTimeout(attempt, 120); return; }
    if (window.requestIdleCallback) requestIdleCallback(() => r(), { timeout: 300 }); else setTimeout(r, 16);
  };
  attempt();
});

/* Until this finishes, the section is a plain list (the no-WebGL fallback). It is only
   upgraded to the tall, scroll-driven stage once the scene is built and its shaders are
   compiled, so the visitor never scrolls into a half-ready canvas. */
async function boot() {
  const canvas = section.querySelector('.compass-canvas');
  if (!canvas) return;
  // No real GPU (software rendering)? Then stay on the plain list: a 3D scene drawn by the CPU
  // is the one thing that would make the whole page crawl. Checked on a throwaway context,
  // before three.js is even downloaded. `?force3d` skips the check for testing.
  const force = /[?&]force3d\b/.test(location.search);
  if (!force && !hasRealGPU()) { fail(); return; }
  await idle();
  THREE = await import('../../vendor/three/three.module.min.js');
  await idle();
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !lite, alpha: true, failIfMajorPerformanceCaveat: !force });
  if (!renderer.getContext()) throw new Error('no WebGL context');
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const studio = buildStudio();
  scene.environment = pmrem.fromScene(studio, 0.035).texture;
  studio.traverse((o) => { o.geometry && o.geometry.dispose(); o.material && o.material.dispose(); });
  pmrem.dispose();
  await idle();

  const compass = buildCompass();
  scene.add(compass.root);
  await idle();

  const camera = new THREE.PerspectiveCamera(24, 1, 1, 2000);
  const target = new THREE.Vector3();
  // metal reads sharp well below retina density; capping it is the biggest single GPU saving
  const DPR_MAX = Math.min(window.devicePixelRatio || 1, 1.25);
  let Wd = 1, Hd = 1, dpr = DPR_MAX;
  const cur = { ...SHOTS.enter };
  const pointer = { x: 0, y: 0, sx: 0, sy: 0 };
  let time = 0, visible = true, progress = 0;

  // shaders compile in the background (KHR_parallel_shader_compile) instead of on first draw
  if (renderer.compileAsync && renderer.extensions.has('KHR_parallel_shader_compile')) {
    try { await renderer.compileAsync(scene, camera); } catch (e) { /* falls back to compiling on first draw */ }
  } else { await idle(); renderer.compile(scene, camera); await idle(); }
  // the visitor has already scrolled past: growing the section now would shove the page under them
  if (section.getBoundingClientRect().bottom < 0) { renderer.dispose(); return; }

  /* --- layout is measured on resize only; frames never read it --- */
  const items = Array.from(section.querySelectorAll('.callout'));
  const svg = section.querySelector('.leaders');
  const stage = section.querySelector('.inside-stage');
  const geo = { cl: 0, ct: 0, items: [] };
  const offsetWithin = (el, root) => { let x = 0, y = 0; while (el && el !== root) { x += el.offsetLeft; y += el.offsetTop; el = el.offsetParent; } return [x, y]; };
  let mobile = isMobile(), dirty = true;
  function measure() {
    mobile = isMobile();
    Wd = Math.max(1, canvas.offsetWidth); Hd = Math.max(1, canvas.offsetHeight);
    renderer.setPixelRatio(dpr);
    renderer.setSize(Wd, Hd, false);
    camera.aspect = Wd / Hd;
    const c = offsetWithin(canvas, stage); geo.cl = c[0]; geo.ct = c[1];
    geo.items = items.map((li) => offsetWithin(li, stage));
    last.fill(NaN); dirty = true;
  }

  function place(p) {
    const S = 74; // mm: the compass with its bail
    const dist = S / (2 * p.fit * Math.tan(camera.fov * D2R / 2) * Math.min(camera.aspect, 1));
    const ph = p.polar * D2R, th = p.az * D2R;
    target.set(0, p.ty, 0);
    camera.position.set(dist * Math.sin(ph) * Math.sin(th), p.ty + dist * Math.cos(ph), dist * Math.sin(ph) * Math.cos(th));
    camera.lookAt(target);
    camera.updateProjectionMatrix();
  }

  /* --- scroll: the section is tall and its stage is CSS-sticky; this only measures --- */
  const ST = window.ScrollTrigger;
  if (ST && !reduce) {
    ST.create({ trigger: section, start: 'top top', end: 'bottom bottom', invalidateOnRefresh: true,
      onUpdate: (self) => { progress = self.progress; } });
  }
  function goal() {
    if (reduce) return { ...SHOTS.apart, polar: 66 };
    const p = progress;
    let g;
    if (p < 0.18) g = mix(SHOTS.enter, SHOTS.lift, ease(p / 0.18));
    else if (p < 0.6) {
      g = mix(SHOTS.lift, SHOTS.apart, ease((p - 0.18) / 0.3));
      g.explode = SHOTS.lift.explode + (1 - SHOTS.lift.explode) * ease((p - 0.24) / 0.36);
    } else if (p < 0.78) g = { ...SHOTS.apart };
    else g = mix(SHOTS.apart, SHOTS.rebuild, ease((p - 0.78) / 0.2));
    return g;
  }

  /* --- the verb: hold to find north --- */
  const needle = { h: 2.4, v: 0, holding: false, power: 0, found: false, armed: false };
  section.__needle = needle; // handy when debugging from the console
  const holdBtn = section.querySelector('.hold-btn');
  const result = section.querySelector('.hold-result');
  const sndBtn = section.querySelector('.snd-btn');
  const sound = makeSound();
  let soundOn = true;
  if (sndBtn) sndBtn.addEventListener('click', () => {
    soundOn = !soundOn; sndBtn.setAttribute('aria-pressed', String(soundOn));
    sndBtn.querySelector('span').textContent = soundOn ? 'Sound on' : 'Sound off';
  });
  function startHold(e) {
    if (e && e.button !== undefined && e.button !== 0) return;
    needle.holding = true; needle.t0 = performance.now(); holdBtn.classList.add('is-holding');
    if (soundOn) sound.wake();
  }
  function endHold() {
    if (!needle.holding) return;
    needle.holding = false; holdBtn.classList.remove('is-holding');
    if (performance.now() - needle.t0 > 450) needle.armed = true; // a real hold, not a tap
  }
  if (holdBtn) {
    holdBtn.addEventListener('pointerdown', (e) => { holdBtn.setPointerCapture && holdBtn.setPointerCapture(e.pointerId); startHold(e); });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((t) => holdBtn.addEventListener(t, endHold));
    holdBtn.addEventListener('keydown', (e) => { if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); startHold(); } });
    holdBtn.addEventListener('keyup', (e) => { if (e.key === ' ' || e.key === 'Enter') endHold(); });
    holdBtn.addEventListener('contextmenu', (e) => e.preventDefault());
  }
  let lastSector = 0, ringShown = '';
  function stepNeedle(dt) {
    const TAU = Math.PI * 2;
    if (needle.holding) {
      needle.v = Math.min(13, needle.v + dt * 26);
      // power runs on the wall clock, so the ring fills at the same pace on slow devices
      needle.power = Math.min(1, (performance.now() - needle.t0) / 1300);
    } else {
      // a real compass: an underdamped spring back to north
      let d = ((needle.h % TAU) + TAU) % TAU; if (d > Math.PI) d -= TAU;
      const wob = needle.found ? 0 : Math.sin(time * 0.9) * 0.06;
      needle.v += (-24 * (d - wob) - 3.4 * needle.v) * dt;
      needle.power = Math.max(0, needle.power - dt * 0.6);
    }
    needle.h += needle.v * dt;
    const ring = (needle.holding ? needle.power : needle.power * 0.6).toFixed(2);
    if (holdBtn && ring !== ringShown) { holdBtn.style.setProperty('--p', ring); ringShown = ring; }
    const sector = Math.floor(needle.h / (Math.PI / 6));
    if (sector !== lastSector && Math.abs(needle.v) > 0.8) { if (soundOn) sound.tick(Math.abs(needle.v)); lastSector = sector; }
    // settled after a real hold: reveal where north points today
    if (!needle.holding && needle.armed && Math.abs(needle.v) < 0.35) {
      let d = ((needle.h % TAU) + TAU) % TAU; if (d > Math.PI) d -= TAU;
      if (Math.abs(d) < 0.06) {
        needle.found = true; needle.armed = false;
        if (soundOn) sound.chime();
        if (result) {
          result.hidden = false; result.classList.add('is-found');
          const name = result.querySelector('b');
          if (name && W.decrypt) W.decrypt(name, { duration: 0.9 });
        }
        setTimeout(() => { needle.found = false; }, 2500);
      }
    }
    compass.needle.rotation.y = -needle.h;
  }

  /* --- callouts and leader lines: the DOM is only touched when something actually changed --- */
  const paths = [], dots = [];
  if (svg) items.forEach(() => {
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.setAttribute('r', '3.5'); g.appendChild(p); g.appendChild(c); svg.appendChild(g);
    paths.push(g); dots.push(c);
  });
  const meter = section.querySelector('.inside-meter em');
  const tmp = new THREE.Vector3(), right = new THREE.Vector3();
  const last = new Float32Array(items.length * 2).fill(NaN);
  let onState = items.map(() => null), activeIdx = -2, meterShown = '';
  function callouts(tParts) {
    let active = -1;
    for (let i = 0; i < items.length; i++) {
      const on = reduce ? true : tParts[i] > 0.5;
      if (on) active = i;
      if (on !== onState[i]) { onState[i] = on; items[i].classList.toggle('on', on); if (paths[i]) paths[i].classList.toggle('on', on); }
    }
    if (!reduce && mobile) active = progress < 0.26 ? -1 : Math.min(items.length - 1, Math.floor((progress - 0.26) / 0.075));
    if (active !== activeIdx) { items.forEach((li, i) => li.classList.toggle('current', i === active)); activeIdx = active; }
    const m = cur.explode.toFixed(2);
    if (meter && m !== meterShown) { meter.style.transform = 'scaleX(' + m + ')'; meterShown = m; }
    if (!svg || mobile) return;
    // anchors: each part's edge on the camera's right, projected to the screen
    right.setFromMatrixColumn(camera.matrixWorld, 0); right.y = 0; right.normalize();
    for (let i = 0; i < compass.parts.length; i++) {
      const part = compass.parts[i];
      if (!paths[i] || !geo.items[i]) continue;
      tmp.copy(right).multiplyScalar(part.r);
      tmp.y = part.group.position.y + part.y;
      tmp.project(camera);
      const ax = (tmp.x + 1) / 2 * Wd + geo.cl, ay = (1 - tmp.y) / 2 * Hd + geo.ct;
      if (Math.abs(ax - last[i * 2]) < 0.25 && Math.abs(ay - last[i * 2 + 1]) < 0.25) continue;
      last[i * 2] = ax; last[i * 2 + 1] = ay;
      const cx = geo.items[i][0] - 14, cy = geo.items[i][1] + 16;
      const mx = Math.max(ax + 30, cx - 80);
      paths[i].firstChild.setAttribute('d', `M${ax.toFixed(1)} ${ay.toFixed(1)} C${mx.toFixed(1)} ${ay.toFixed(1)} ${(cx - 60).toFixed(1)} ${cy.toFixed(1)} ${cx.toFixed(1)} ${cy.toFixed(1)}`);
      dots[i].setAttribute('cx', ax.toFixed(1)); dots[i].setAttribute('cy', ay.toFixed(1));
    }
  }

  /* --- one clock: GSAP's ticker drives the frame ---
     The scene is drawn at full rate only while something is really moving (scroll, pointer,
     a held needle). At rest, the slow sway is drawn at ~30 fps, which looks the same and
     halves the GPU work. */
  const EPS = { polar: 0.03, az: 0.03, fit: 0.0006, ty: 0.03, explode: 0.0008, env: 0.002 };
  let lastDraw = 0, slowFrames = 0, busyFrames = 0, inView = true;
  function frame(t, deltaMS) {
    if (!visible || document.hidden) return;
    const dt = Math.min(deltaMS / 1000, 0.05);
    time += dt;
    const g = goal();
    const k = reduce ? 1 : 1 - Math.exp(-dt * 5);
    let busy = dirty;
    for (const key of KEYS) { const d = g[key] - cur[key]; if (Math.abs(d) > EPS[key]) busy = true; cur[key] += d * k; }
    const kp = 1 - Math.exp(-dt * 3);
    if (Math.abs(pointer.x - pointer.sx) + Math.abs(pointer.y - pointer.sy) > 0.004) busy = true;
    pointer.sx += (pointer.x - pointer.sx) * kp; pointer.sy += (pointer.y - pointer.sy) * kp;
    stepNeedle(reduce ? 0 : dt);
    if (needle.holding || needle.armed || Math.abs(needle.v) > 0.25) busy = true;

    // Taken apart, the compass holds still like a diagram, so at rest nothing is drawn at all.
    // Assembled, it sways gently, drawn at ~30 fps.
    const now = performance.now();
    const still = reduce || cur.explode > 0.03 || !inView; // no idle sway while mostly off screen
    if (!busy && (still || now - lastDraw < 31)) return;
    lastDraw = now; dirty = false;

    // the cursor turns the studio, so the light slides across the metal
    scene.environmentRotation.set(pointer.sy * 0.4, cur.env - pointer.sx * 0.8, 0);
    scene.environmentIntensity = 1 + needle.power * 0.35;
    const sway = reduce ? 0 : 1 - clamp(cur.explode / 0.03); // fades out as the parts lift
    compass.root.rotation.y = reduce ? -0.35 : Math.sin(time * 0.3) * 0.08 * sway - 0.35 + pointer.sx * 0.12;
    compass.root.rotation.x = reduce ? 0 : pointer.sy * 0.05;
    compass.root.position.y = Math.sin(time * 0.7) * 0.35 * sway;

    // staggered explode: top parts leave first and come back last
    const e = cur.explode;
    const tParts = compass.parts.map((p) => {
      const delay = (1 - p.order) * 0.42;
      const tt = ease((e - delay) / 0.58);
      p.group.position.y = p.lift * tt;
      p.group.rotation.x = p.tilt * tt;
      return tt;
    });
    place(cur);
    renderer.render(scene, camera);
    callouts(tParts);

    // adaptive quality: if busy frames run long, step the resolution down (never back up mid-visit)
    if (busy) {
      busyFrames++; if (deltaMS > 20) slowFrames++;
      if (busyFrames >= 50) {
        if (slowFrames > 22 && dpr > 0.85) { dpr = Math.max(0.85, dpr - 0.25); measure(); }
        busyFrames = 0; slowFrames = 0;
      }
    }
  }

  window.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'touch' || reduce) return;
    pointer.x = e.clientX / window.innerWidth * 2 - 1; pointer.y = e.clientY / window.innerHeight * 2 - 1;
  }, { passive: true });
  if ('IntersectionObserver' in window) new IntersectionObserver((es) => { visible = es[0].isIntersecting; dirty = true; }, { rootMargin: '0px' }).observe(section);
  if ('IntersectionObserver' in window) new IntersectionObserver((es) => { inView = es[0].intersectionRatio > 0.35; }, { threshold: [0, 0.35, 0.6] }).observe(canvas);

  // ready: switch the section from the plain list to the tall, sticky stage, and draw the first frame
  html.classList.add('webgl');
  measure();
  if ('ResizeObserver' in window) new ResizeObserver(measure).observe(stage); else window.addEventListener('resize', measure);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measure);
  place(cur); renderer.render(scene, camera);
  if (ST) ST.refresh();
  if (window.gsap) window.gsap.ticker.add(frame);
  else { let prev = performance.now(); const loop = (n) => { frame(n, n - prev); prev = n; requestAnimationFrame(loop); }; requestAnimationFrame(loop); }
}

/* ======================= the studio ======================= */
function buildStudio() {
  const s = new THREE.Scene();
  s.add(new THREE.Mesh(new THREE.BoxGeometry(160, 160, 160), new THREE.MeshBasicMaterial({ color: 0x081820, side: THREE.BackSide })));
  const panel = (w, h, k, pos, hex = 0xffffff) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(hex).multiplyScalar(k), side: THREE.DoubleSide }));
    m.position.set(pos[0], pos[1], pos[2]); m.lookAt(0, 0, 0); s.add(m);
  };
  panel(46, 30, 3.4, [-44, 42, 40]);            // key softbox, off-axis
  panel(5, 80, 6.5, [60, 10, 26]);              // strip: the bright edge line
  panel(5, 80, 3.2, [-56, 6, -46], 0xffe2cf);   // warm strip from behind
  panel(30, 30, 0.55, [0, 70, 0], 0xd5ecff);    // soft top fill (kept low: the glass mirrors it)
  panel(80, 8, 2.6, [0, -14, -64], 0xf4845f);   // a low coral sunset kicker
  panel(40, 10, 1.4, [30, -12, 60], 0x2e9c94);  // and a lagoon bounce
  return s;
}

/* ======================= textures, drawn at boot ======================= */
function dialTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 1024;
  const g = c.getContext('2d'), R = 512;
  const grad = g.createRadialGradient(R, R, 30, R, R, R);
  grad.addColorStop(0, '#1A4457'); grad.addColorStop(1, '#0B2230');
  g.fillStyle = grad; g.fillRect(0, 0, 1024, 1024);
  // the house motif: contour lines on the dial
  g.lineWidth = 2;
  for (let k = 1; k < 15; k++) {
    g.strokeStyle = k % 5 === 0 ? 'rgba(134,224,214,.32)' : 'rgba(134,200,206,.16)';
    g.beginPath();
    for (let a = 0; a <= Math.PI * 2 + 0.02; a += 0.02) {
      const r = k * 31 + Math.sin(a * 3 + k * 0.9) * 9 + Math.sin(a * 5 - k * 0.6) * 5;
      const x = R + Math.cos(a) * r, y = R + Math.sin(a) * r;
      if (a === 0) g.moveTo(x, y); else g.lineTo(x, y);
    }
    g.closePath(); g.stroke();
  }
  // degree ring
  for (let i = 0; i < 360; i += 2) {
    const a = i * D2R, major = i % 30 === 0, mid = i % 10 === 0;
    g.strokeStyle = major ? '#F3E7CF' : 'rgba(243,231,207,.5)'; g.lineWidth = major ? 4 : 2;
    g.beginPath(); g.moveTo(R + Math.cos(a) * 490, R + Math.sin(a) * 490);
    g.lineTo(R + Math.cos(a) * (major ? 446 : mid ? 462 : 472), R + Math.sin(a) * (major ? 446 : mid ? 462 : 472)); g.stroke();
  }
  // a 16-point rose, each point split light and shadow
  const point = (ang, len, w, light, dark) => {
    const ax = Math.cos(ang), ay = Math.sin(ang), px = -ay, py = ax;
    g.fillStyle = light; g.beginPath(); g.moveTo(R, R); g.lineTo(R + ax * len, R + ay * len); g.lineTo(R + px * w, R + py * w); g.closePath(); g.fill();
    g.fillStyle = dark; g.beginPath(); g.moveTo(R, R); g.lineTo(R + ax * len, R + ay * len); g.lineTo(R - px * w, R - py * w); g.closePath(); g.fill();
  };
  for (let i = 0; i < 16; i++) { if (i % 4 === 0) continue; const a = i * Math.PI / 8 - Math.PI / 2; point(a, i % 2 ? 175 : 260, i % 2 ? 20 : 32, '#CFA65A', '#8A6A2D'); }
  for (let i = 0; i < 4; i++) { const a = i * Math.PI / 2 - Math.PI / 2; point(a, 395, 50, i === 0 ? '#F79C7C' : '#F2D78E', i === 0 ? '#C85E3B' : '#B5882F'); }
  g.fillStyle = '#F3E7CF'; g.beginPath(); g.arc(R, R, 24, 0, Math.PI * 2); g.fill();
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  return t;
}

function bezelTexture(inner, outer) {
  const c = document.createElement('canvas'); c.width = c.height = 1024;
  const g = c.getContext('2d'), R = 512, k = 512 / outer;
  for (let i = 0; i < 360; i += 5) {
    if (i % 90 === 0) continue;
    const a = i * D2R, major = i % 45 === 0;
    g.strokeStyle = major ? 'rgba(255,255,255,.95)' : 'rgba(255,255,255,.7)'; g.lineWidth = major ? 7 : 4;
    const r1 = (outer - 0.5) * k, r2 = (outer - (major ? 2.1 : 1.3)) * k;
    g.beginPath(); g.moveTo(R + Math.cos(a) * r1, R + Math.sin(a) * r1); g.lineTo(R + Math.cos(a) * r2, R + Math.sin(a) * r2); g.stroke();
  }
  const fam = getComputedStyle(document.body).fontFamily || 'sans-serif';
  g.textAlign = 'center'; g.textBaseline = 'middle';
  ['N', 'E', 'S', 'W'].forEach((L, i) => {
    const a = i * Math.PI / 2 - Math.PI / 2, r = ((inner + outer) / 2) * k;
    g.save(); g.translate(R + Math.cos(a) * r, R + Math.sin(a) * r); g.rotate(a + Math.PI / 2);
    g.font = '800 64px ' + fam; g.fillStyle = L === 'N' ? '#FFB59A' : '#FFFFFF'; g.fillText(L, 0, 2); g.restore();
  });
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  return t;
}

/* ======================= the compass, in millimetres ======================= */
function lathe(points, segs = 96) {
  return new THREE.LatheGeometry(points.map(([x, y]) => new THREE.Vector2(x, y)), segs);
}
function rounded(pts, r = 0.6, n = 4) {
  // round every corner of a polyline a little: edges are where the light lives
  const out = [];
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i], a = pts[i - 1], b = pts[i + 1];
    if (!a || !b) { out.push(p); continue; }
    const da = Math.hypot(p[0] - a[0], p[1] - a[1]), db = Math.hypot(b[0] - p[0], b[1] - p[1]);
    const ra = Math.min(r, da / 2), rb = Math.min(r, db / 2);
    const s = [p[0] + (a[0] - p[0]) / da * ra, p[1] + (a[1] - p[1]) / da * ra];
    const e = [p[0] + (b[0] - p[0]) / db * rb, p[1] + (b[1] - p[1]) / db * rb];
    for (let j = 0; j <= n; j++) {
      const t = j / n, u = 1 - t;
      out.push([u * u * s[0] + 2 * u * t * p[0] + t * t * e[0], u * u * s[1] + 2 * u * t * p[1] + t * t * e[1]]);
    }
  }
  return out;
}

function buildCompass() {
  const root = new THREE.Group();
  const M = {
    copper: new THREE.MeshPhysicalMaterial({ color: '#C77B57', metalness: 1, roughness: 0.3, anisotropy: 0.7, clearcoat: 0.25, clearcoatRoughness: 0.25, side: THREE.DoubleSide }),
    brass: new THREE.MeshPhysicalMaterial({ color: '#E2BE78', metalness: 1, roughness: 0.12, side: THREE.DoubleSide }),
    enamel: new THREE.MeshPhysicalMaterial({ color: '#2E9C94', metalness: 0.1, roughness: 0.34, clearcoat: 1, clearcoatRoughness: 0.05, side: THREE.DoubleSide }),
    print: new THREE.MeshStandardMaterial({ map: bezelTexture(25.9, 29.5), transparent: true, metalness: 0.5, roughness: 0.35, depthWrite: false }),
    dial: new THREE.MeshPhysicalMaterial({ map: dialTexture(), metalness: 0.3, roughness: 0.46, clearcoat: 0.7, clearcoatRoughness: 0.18 }),
    north: new THREE.MeshPhysicalMaterial({ color: '#F4845F', metalness: 0.2, roughness: 0.32, clearcoat: 0.9, clearcoatRoughness: 0.1 }),
    blued: new THREE.MeshPhysicalMaterial({ color: '#3A5EA8', metalness: 1, roughness: 0.2, iridescence: 0.8, iridescenceIOR: 1.7, iridescenceThicknessRange: [180, 520] }),
    // clear glass: mostly see-through, with the studio caught in its clearcoat
    glass: new THREE.MeshPhysicalMaterial({ color: '#D6F1EC', metalness: 0, roughness: 0.04, transparent: true, opacity: 0.16, clearcoat: 1, clearcoatRoughness: 0.03, envMapIntensity: 1.6, specularIntensity: 1, depthWrite: false, side: THREE.FrontSide }),
  };
  const parts = [];
  const part = (name, order, lift, r, y, tilt) => { const g = new THREE.Group(); g.name = name; root.add(g); const p = { name, order, lift, r, y, tilt, group: g }; parts.push(p); return g; };

  // listed top to bottom, the order they come off
  // when apart, each part also tips toward the camera a little, to show its face
  const glass = part('glass', 1.0, 50, 27.6, 12, 0.22);
  const bezel = part('bezel', 0.8, 36, 29.9, 10, 0.16);
  const needleG = part('needle', 0.6, 25, 22, 5.6, 0.42);
  const dial = part('dial', 0.4, 13, 25.3, 2.8, 0.1);
  const caseG = part('case', 0.1, -4, 30.2, 4.5, 0);

  // copper case: a shallow cup with a rolled rim, plus the bail
  const caseProfile = rounded([[0, 0], [28.6, 0], [30.2, 1.6], [30.2, 8.6], [29.2, 9.2], [28.1, 9.2], [27.8, 8.4], [27.8, 2.2], [0, 2.2]], 0.7);
  caseG.add(new THREE.Mesh(lathe(caseProfile), M.copper));
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(1.9, 2.2, 5.4, 40), M.brass);
  stem.rotation.x = Math.PI / 2; stem.position.set(0, 4.8, -32.2); caseG.add(stem);
  const bail = new THREE.Mesh(new THREE.TorusGeometry(4.6, 1.1, 28, 72), M.brass);
  bail.rotation.x = Math.PI / 2; bail.position.set(0, 4.8, -38.8); caseG.add(bail);

  // teal enamel bezel with printed ticks and N E S W
  const bezelProfile = rounded([[25.4, 9.1], [29.9, 9.1], [29.9, 10.3], [29.4, 10.95], [25.9, 10.95], [25.4, 10.4], [25.4, 9.1]], 0.45);
  bezel.add(new THREE.Mesh(lathe(bezelProfile), M.enamel));
  const ring = new THREE.Mesh(new THREE.RingGeometry(25.9, 29.5, 96, 1), M.print);
  ring.rotation.x = -Math.PI / 2; ring.position.y = 10.97; bezel.add(ring);
  const ringUV = ring.geometry.attributes.uv, pos = ring.geometry.attributes.position;
  for (let i = 0; i < ringUV.count; i++) ringUV.setXY(i, pos.getX(i) / 29.5 * 0.5 + 0.5, pos.getY(i) / 29.5 * 0.5 + 0.5);

  // gold rose dial
  const dialMesh = new THREE.Mesh(new THREE.CylinderGeometry(25.3, 25.3, 1, 96), [M.brass, M.dial, M.brass]);
  dialMesh.position.y = 2.75; dialMesh.rotation.y = Math.PI / 2; // cap UVs run along +X; turn the drawn north to -Z
  dial.add(dialMesh);

  // the needle: coral north, heat-blued south, on a brass pivot
  const needle = new THREE.Group(); needle.position.y = 5.1; needleG.add(needle);
  const half = (tip, mat) => {
    const s = new THREE.Shape(); s.moveTo(0, tip); s.lineTo(2.7, 0); s.lineTo(-2.7, 0); s.closePath();
    const geo = new THREE.ExtrudeGeometry(s, { depth: 0.7, bevelEnabled: true, bevelThickness: 0.22, bevelSize: 0.22, bevelSegments: 3, curveSegments: 1 });
    const m = new THREE.Mesh(geo, mat); m.rotation.x = -Math.PI / 2; return m;
  };
  needle.add(half(21.5, M.north)); needle.add(half(-19.5, M.blued));
  const cap = new THREE.Mesh(new THREE.CylinderGeometry(2.1, 2.6, 1.8, 48), M.brass); cap.position.y = 1.4; needle.add(cap);
  const jewel = new THREE.Mesh(new THREE.SphereGeometry(0.9, 24, 16), M.north); jewel.position.y = 2.4; needle.add(jewel);
  const pivot = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.9, 2.4, 20), M.brass); pivot.position.y = 3.9; needleG.add(pivot);

  // the glass crystal: a thin domed lens
  const dome = [];
  for (let i = 0; i <= 24; i++) { const r = 27.3 * i / 24; dome.push([r, 11.2 + 1.7 * (1 - (r / 27.3) ** 2)]); }
  const under = [];
  for (let i = 24; i >= 0; i--) { const r = 27.3 * i / 24; under.push([r, 10.9 + 1.35 * (1 - (r / 27.3) ** 2)]); }
  glass.add(new THREE.Mesh(lathe([...dome, [27.6, 11.05], ...under]), M.glass));

  root.position.y = 0;
  return { root, parts, needle };
}

/* ======================= Web Audio: ticks and a chime ======================= */
function makeSound() {
  let ctx = null, out = null;
  const wake = () => {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
      ctx = new AC(); out = ctx.createGain(); out.gain.value = 0.32; out.connect(ctx.destination);
    }
    if (ctx.state === 'suspended') ctx.resume();
  };
  const tick = (speed) => {
    if (!ctx) return;
    const t = ctx.currentTime, o = ctx.createOscillator(), g = ctx.createGain();
    o.type = 'triangle'; o.frequency.value = 1700 + Math.min(1200, speed * 70);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.09, t + 0.003); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.04);
    o.connect(g); g.connect(out); o.start(t); o.stop(t + 0.05);
  };
  const chime = () => {
    if (!ctx) return;
    const t = ctx.currentTime;
    [[880, 0], [1318.5, 0.07]].forEach(([f, d]) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'sine'; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t + d); g.gain.exponentialRampToValueAtTime(0.12, t + d + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + d + 0.9);
      o.connect(g); g.connect(out); o.start(t + d); o.stop(t + d + 1);
    });
  };
  return { wake, tick, chime };
}

/* ======================= start-up =======================
   Nothing 3D is downloaded, parsed or compiled while the page is loading and the hero is
   animating. The scene is built in idle time once the page has settled, or sooner if the
   visitor heads straight down the page. */
if (section) {
  let started = false;
  const go = () => { if (!started) { started = true; boot().catch(fail); } };
  if (section.getBoundingClientRect().top < window.innerHeight * 2) go();
  else {
    const whenIdle = (fn) => (window.requestIdleCallback ? requestIdleCallback(fn, { timeout: 3000 }) : setTimeout(fn, 400));
    const arm = () => setTimeout(() => whenIdle(go), 1600);
    if (document.readyState === 'complete') arm(); else window.addEventListener('load', arm, { once: true });
    if ('IntersectionObserver' in window) {
      new IntersectionObserver((es, io) => { if (es[0].isIntersecting) { io.disconnect(); go(); } }, { rootMargin: '200% 0px' }).observe(section);
    }
  }
}
