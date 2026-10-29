/* 明暗主题切换：跟随系统偏好初始化，之后记住用户选择 */
(function () {
  'use strict';

  var KEY = 'vl_theme';
  var sun = document.getElementById('iconSun');
  var moon = document.getElementById('iconMoon');
  var btn = document.getElementById('themeBtn');

  function apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    if (sun && moon) {
      var dark = theme === 'dark';
      sun.style.display = dark ? 'none' : '';
      moon.style.display = dark ? '' : 'none';
    }
    if (btn) btn.setAttribute('aria-pressed', String(theme === 'dark'));
  }

  function current() {
    var saved = localStorage.getItem(KEY);
    if (saved === 'dark' || saved === 'light') return saved;
    var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    return prefersDark ? 'dark' : 'light';
  }

  apply(current());

  if (btn) {
    btn.addEventListener('click', function () {
      var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      apply(next);
      localStorage.setItem(KEY, next);
    });
  }

  window.Theme = {
    get: function () { return document.documentElement.getAttribute('data-theme') || 'light'; },
    apply: apply
  };
})();
