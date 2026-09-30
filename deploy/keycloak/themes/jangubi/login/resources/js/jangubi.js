/* Jàngu Bi · thème de connexion : robustesse du mot de passe, confirmation recopiée,
   coche « adresse valide », état vide du champ date. Amélioration progressive : sans
   JavaScript, tous les champs restent visibles et le formulaire fonctionne. */
(function () {
  'use strict';

  // Règles de la politique du realm (length(10), upperCase, lowerCase, digits) ; le symbole est un bonus.
  var RULES = {
    length: function (v) { return v.length >= 10; },
    case: function (v) { return /[a-z]/.test(v) && /[A-Z]/.test(v); },
    digit: function (v) { return /\d/.test(v); }
  };

  function strength() {
    var input = document.querySelector('[data-jb-strength]');
    if (!input) return;
    var meter = document.querySelector('.jb-strength');
    var bars = meter ? meter.querySelectorAll('.jb-bars span') : [];
    var label = document.querySelector('[data-jb-strength-label]');
    function update() {
      var v = input.value;
      var met = 0;
      Object.keys(RULES).forEach(function (key) {
        var ok = RULES[key](v);
        if (ok) met += 1;
        var item = document.querySelector('[data-rule="' + key + '"]');
        if (item) item.classList.toggle('is-met', ok);
      });
      var level = v ? met + (/[^A-Za-z0-9]/.test(v) ? 1 : 0) : 0;
      var state = !v ? '' : met === 3 ? 'strong' : level >= 2 ? 'fair' : 'weak';
      if (meter) {
        meter.setAttribute('data-level', String(Math.min(level, 4)));
        meter.setAttribute('data-state', state);
      }
      for (var i = 0; i < bars.length; i += 1) bars[i].classList.toggle('is-on', i < level);
      if (label) label.textContent = state ? label.dataset[state === 'strong' ? 'strong' : state === 'fair' ? 'fair' : 'weak'] : '';
    }
    input.addEventListener('input', update);
    update();
  }

  // Keycloak exige « password-confirm » : l'œil sert de vérification, la confirmation est recopiée.
  function confirmCopy() {
    var box = document.querySelector('[data-jb-confirm]');
    var pw = document.getElementById('password');
    var confirm = document.getElementById('password-confirm');
    if (!box || !pw || !confirm) return;
    box.classList.add('jb-sr');
    box.setAttribute('aria-hidden', 'true');
    confirm.setAttribute('tabindex', '-1');
    box.querySelectorAll('button').forEach(function (b) { b.setAttribute('tabindex', '-1'); });
    var sync = function () { confirm.value = pw.value; };
    pw.addEventListener('input', sync);
    var form = pw.form;
    if (form) form.addEventListener('submit', sync);
    sync();
  }

  function validMarks() {
    document.querySelectorAll('[data-jb-valid]').forEach(function (wrap) {
      var input = wrap.querySelector('input');
      if (!input) return;
      var update = function () {
        var ok = !!input.value && input.validity.valid && input.getAttribute('aria-invalid') !== 'true';
        wrap.classList.toggle('is-valid', ok);
      };
      input.addEventListener('input', function () {
        input.removeAttribute('aria-invalid');
        update();
      });
      update();
    });
  }

  function dates() {
    document.querySelectorAll('[data-jb-date]').forEach(function (input) {
      var update = function () { input.classList.toggle('jb-date-empty', !input.value); };
      input.addEventListener('input', update);
      input.addEventListener('change', update);
      update();
    });
  }

  // Un seul envoi par formulaire (double clic, réseau lent).
  function singleSubmit() {
    document.querySelectorAll('form.jb-form').forEach(function (form) {
      form.addEventListener('submit', function () {
        var btn = form.querySelector('button[type="submit"].jb-btn-primary');
        if (btn) window.setTimeout(function () { btn.disabled = true; }, 0);
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    strength();
    confirmCopy();
    validMarks();
    dates();
    singleSubmit();
  });
})();
