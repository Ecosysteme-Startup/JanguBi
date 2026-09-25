/* Jàngu Bi · thème de connexion : bandeau liturgique et robustesse du mot de passe. */
(function () {
  'use strict';

  var MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
  var DAYS = ['Dimanche', 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi'];
  var COLORS = { vert: 'Vert', violet: 'Violet', blanc: 'Blanc', rouge: 'Rouge', rose: 'Rose' };

  function banner() {
    var now = new Date();
    var start = new Date(now.getFullYear(), 0, 0);
    var dayNum = Math.floor((now - start) / 86400000);
    var date = document.querySelector('[data-jb-date]');
    var num = document.querySelector('[data-jb-daynum]');
    if (date) date.textContent = DAYS[now.getDay()] + ' ' + now.getDate() + ' ' + MONTHS[now.getMonth()] + ' ' + now.getFullYear();
    if (num) num.textContent = 'Jour ' + dayNum;

    var api = document.body.getAttribute('data-api-url');
    if (!api || !window.fetch) return;
    fetch(api.replace(/\/$/, '') + '/liturgy/today/', { credentials: 'omit' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (day) {
        if (!day || !day.calendar) return;
        var slot = document.querySelector('[data-jb-celebration]');
        if (slot) {
          slot.textContent = '';
          var label = document.createElement('span');
          label.textContent = day.calendar.celebration;
          var pill = document.createElement('span');
          var color = day.calendar.color;
          pill.className = 'jb-pill jb-lit-' + (COLORS[color] ? color : 'vert');
          pill.title = 'Couleur liturgique du jour : ' + (COLORS[color] || 'Vert').toLowerCase();
          pill.textContent = COLORS[color] || 'Vert';
          slot.appendChild(label);
          slot.appendChild(pill);
          slot.hidden = false;
        }
        var refs = (day.readings || []).map(function (r) { return r.citation; }).filter(Boolean);
        var link = document.querySelector('[data-jb-refs]');
        if (link && refs.length) link.textContent = refs.join(' · ');
      })
      .catch(function () { /* hors ligne : la date suffit */ });
  }

  function strength() {
    var input = document.querySelector('[data-jb-strength]');
    if (!input) return;
    var meter = document.querySelector('.jb-strength');
    var label = document.querySelector('[data-jb-strength-label]');
    var rules = {
      length: function (v) { return v.length >= 10; },
      case: function (v) { return /[a-z]/.test(v) && /[A-Z]/.test(v); },
      digit: function (v) { return /\d/.test(v); },
      symbol: function (v) { return /[^A-Za-z0-9]/.test(v); }
    };
    input.addEventListener('input', function () {
      var v = input.value;
      var score = 0;
      Object.keys(rules).forEach(function (key) {
        var ok = rules[key](v);
        if (ok) score += 1;
        var item = document.querySelector('[data-rule="' + key + '"]');
        if (item) item.classList.toggle('is-met', ok);
      });
      if (meter) meter.setAttribute('data-level', v ? String(score) : '0');
      if (label) {
        var word = !v ? '' : score >= 4 ? label.dataset.strong : score >= 3 ? label.dataset.fair : label.dataset.weak;
        label.textContent = word ? label.dataset.prefix + ' : ' + word : '';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    banner();
    strength();
  });
})();
