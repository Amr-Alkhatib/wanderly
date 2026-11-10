/* Wanderly saves: every "Save" button on the site, handled in one place.

   Markup:  <button type="button" data-save data-destination="<city slug>" data-title="<city name>">
            optionally with <span data-save-label data-on="Saved" data-off="Save">Save</span> inside.

   The trips you have saved arrive on <body data-saved-trips='{"slug": "trip id"}'> (an attribute,
   so Django's escaping is undone by the HTML parser and the JSON reads back intact). Every button
   for the same city stays in step, signed-out visitors are sent to log in and brought back, and a
   short message says what happened, including when something went wrong. */
(function () {
  'use strict';
  var W = (window.W = window.W || {});
  var body = document.body;
  var signedIn = body.hasAttribute('data-signed-in');
  var saved = {};
  try { saved = JSON.parse(body.getAttribute('data-saved-trips') || '{}') || {}; } catch (err) { saved = {}; }
  var busy = {};

  /* ---------- a small message at the bottom of the screen ---------- */
  var toastEl = null, toastTimer = 0;
  W.toast = function (text, link) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'toast';
      toastEl.setAttribute('role', 'status');
      toastEl.setAttribute('aria-live', 'polite');
      body.appendChild(toastEl);
    }
    toastEl.textContent = text;
    if (link) {
      var a = document.createElement('a');
      a.href = link.href; a.textContent = link.text; a.className = 'toast-link';
      toastEl.appendChild(document.createTextNode(' '));
      toastEl.appendChild(a);
    }
    toastEl.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('is-on'); }, link ? 5200 : 4200);
  };

  function csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    if (m && m.content) return m.content;
    var c = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return c ? decodeURIComponent(c[1]) : '';
  }
  function login() {
    location.href = '/accounts/login/?next=' + encodeURIComponent(location.pathname + location.search);
  }

  // POST to one of the trip endpoints and read its JSON, turning every way it can fail into an Error
  W.tripPost = function (url, data) {
    var headers = { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' };
    if (data) headers['Content-Type'] = 'application/json';
    return fetch(url, { method: 'POST', credentials: 'same-origin', headers: headers, body: data ? JSON.stringify(data) : undefined })
      .then(function (res) {
        // the session ended: the endpoint answers with a redirect to the login page
        if (res.redirected && /\/accounts\/login\//.test(res.url)) { var l = new Error('signed out'); l.login = true; throw l; }
        return res.json().catch(function () { return {}; }).then(function (json) {
          if (res.ok) return json;
          var e = new Error(json.error || 'HTTP ' + res.status);
          e.status = res.status;
          throw e;
        });
      });
  };
  W.tripError = function (err, what) {
    if (err && err.login) { login(); return; }
    if (window.console) console.error('[saves]', what, err);
    W.toast(err && err.status === 403
      ? 'Your session has expired. Refresh the page and try again.'
      : 'Couldn’t ' + what + ' right now. Please try again.');
  };

  function buttons(slug) {
    return Array.prototype.filter.call(document.querySelectorAll('[data-save]'), function (b) { return b.dataset.destination === slug; });
  }
  function paint(btn) {
    var slug = btn.dataset.destination, on = Object.prototype.hasOwnProperty.call(saved, slug);
    var name = btn.dataset.title || 'this destination';
    btn.classList.toggle('saved', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.title = on ? 'Saved. Click to remove it from your trips' : 'Save to your trips';
    var label = btn.querySelector('[data-save-label]');
    if (label) label.textContent = on ? label.dataset.on : label.dataset.off;
    else btn.setAttribute('aria-label', (on ? 'Remove ' + name + ' from your saved trips' : 'Save ' + name));
  }
  W.paintSaves = function () { document.querySelectorAll('[data-save]').forEach(paint); };

  function toggle(btn) {
    var slug = btn.dataset.destination;
    if (!slug) return;
    if (!signedIn) { login(); return; }
    if (busy[slug]) return;
    var name = btn.dataset.title || slug, group = buttons(slug);
    var wasSaved = Object.prototype.hasOwnProperty.call(saved, slug), tripId = saved[slug];
    if (wasSaved && !tripId) { W.toast('Refresh the page to change this one.'); return; }
    busy[slug] = true;
    group.forEach(function (b) { b.classList.add('saving'); });
    var req = wasSaved
      ? W.tripPost('/api/trips/' + encodeURIComponent(tripId) + '/unsave/')
      : W.tripPost('/api/trips/save/', { destination: slug, title: name });
    req.then(function (json) {
      if (wasSaved) {
        delete saved[slug];
        W.toast(name + ' was removed from your saved trips.');
      } else {
        saved[slug] = json.id || '';
        W.toast(name + ' is in your saved trips.', { href: '/saved/', text: 'View saved' });
      }
    }, function (err) {
      W.tripError(err, wasSaved ? 'remove ' + name : 'save ' + name);
    }).then(function () {
      busy[slug] = false;
      group.forEach(function (b) { b.classList.remove('saving'); paint(b); });
    });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-save]');
    if (!btn) return;
    e.preventDefault();
    toggle(btn);
  });

  W.paintSaves();
})();
