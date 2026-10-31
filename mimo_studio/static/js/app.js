/* 全局交互：主题、Toast、用户菜单、确认弹窗、表单防重复提交 */
(function () {
  'use strict';

  /* ---------------------------------------------------------------- Toast */
  var ICONS = { success: 'fa-circle-check', error: 'fa-circle-exclamation', info: 'fa-circle-info' };
  var STYLES = {
    success: 'bg-emerald-600 text-white',
    error: 'bg-rose-600 text-white',
    info: 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
  };

  function toast(message, type, duration) {
    var host = document.getElementById('toastHost');
    if (!host) return;
    var kind = STYLES[type] ? type : 'info';

    var el = document.createElement('div');
    el.className = 'pointer-events-auto flex items-start gap-2.5 rounded-xl px-4 py-3 text-[13px] shadow-lg ' + STYLES[kind];
    el.innerHTML = '<i class="fa-solid ' + ICONS[kind] + ' mt-0.5"></i><span class="flex-1 leading-relaxed"></span>';
    el.querySelector('span').textContent = message;   // textContent 防 XSS
    host.appendChild(el);

    var ttl = duration || (kind === 'error' ? 6000 : 3200);
    setTimeout(function () {
      el.classList.add('is-out');
      setTimeout(function () { el.remove(); }, 220);
    }, ttl);
  }

  window.toast = toast;

  /* ---------------------------------------------------------------- 主题 */
  var themeBtn = document.getElementById('themeToggle');
  function applyTheme(dark) {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('mimo-theme', dark ? 'dark' : 'light');
  }
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      applyTheme(!document.documentElement.classList.contains('dark'));
    });
  }

  /* ---------------------------------------------------------------- 用户菜单 */
  var menuBtn = document.getElementById('userMenuBtn');
  var menu = document.getElementById('userMenu');
  if (menuBtn && menu) {
    menuBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      menu.classList.toggle('hidden');
    });
    document.addEventListener('click', function (e) {
      if (!menu.contains(e.target)) menu.classList.add('hidden');
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') menu.classList.add('hidden');
    });
  }

  /* ---------------------------------------------------------------- 确认删除 */
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement)) return;

    var confirmText = form.getAttribute('data-confirm');
    if (confirmText && !window.confirm(confirmText)) {
      e.preventDefault();
      return;
    }
  });

  /* ---------------------------------------------------------------- 防重复提交 */
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.submitted === '1') {
      e.preventDefault();
      return;
    }
    form.dataset.submitted = '1';

    var btn = form.querySelector('button[type="submit"]');
    if (btn) {
      // 延迟一点再改文案，保证表单数据先被浏览器收集
      setTimeout(function () {
        btn.disabled = true;
        btn.classList.add('opacity-60', 'cursor-not-allowed');
        var span = btn.querySelector('span');
        var original = span ? span.textContent : btn.textContent;
        btn.dataset.label = original;
        if (span) span.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin mr-1"></i>处理中…';
        else btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin mr-1"></i>处理中…';
      }, 0);
    }

    // 若页面被浏览器缓存回来后，恢复可提交状态
    window.addEventListener('pageshow', function () {
      form.dataset.submitted = '0';
    });
  });

  /* ---------------------------------------------------------------- 密码可见 */
  document.querySelectorAll('.js-toggle-pw').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = btn.parentElement.querySelector('input');
      if (!input) return;
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.innerHTML = show ? '<i class="fa-regular fa-eye-slash"></i>' : '<i class="fa-regular fa-eye"></i>';
    });
  });

  /* ---------------------------------------------------------------- 快捷键 */
  window.copyText = function (text, okMessage) {
    if (!text) return;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(function () {
        toast(okMessage || '已复制', 'success', 1600);
      }).catch(function () { toast('复制失败，请手动选择', 'error'); });
    } else {
      toast('当前浏览器不支持自动复制', 'error');
    }
  };
})();
