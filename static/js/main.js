/* 启动：鉴权闸门（页内遮罩，不跳页面）、账号区渲染、登录/注册表单 */
(function () {
  'use strict';

  function $(id) { return document.getElementById(id); }

  var slot = $('authSlot');
  var loginOverlay = $('loginOverlay');
  var regOverlay = $('regOverlay');

  function openLogin() { regOverlay.classList.remove('is-open'); loginOverlay.classList.add('is-open'); }
  function openReg() { loginOverlay.classList.remove('is-open'); regOverlay.classList.add('is-open'); }
  function closeAll() { loginOverlay.classList.remove('is-open'); regOverlay.classList.remove('is-open'); }

  function renderAuth(user) {
    slot.innerHTML = '';
    if (user) {
      var chip = document.createElement('div');
      chip.className = 'user-chip';
      var av = document.createElement('div');
      av.className = 'avatar';
      av.textContent = (user.nickname || user.username || '?').trim().charAt(0).toUpperCase();
      var who = document.createElement('span');
      who.className = 'who';
      who.textContent = user.nickname || user.username;
      chip.appendChild(av);
      chip.appendChild(who);
      slot.appendChild(chip);

      var out = document.createElement('button');
      out.className = 'btn btn-ghost btn-sm';
      out.textContent = '退出';
      out.addEventListener('click', function () {
        Api.clearSession();
        renderAuth(null);
        openLogin();
        if (window.Workbench) Workbench.resetOutput();
        location.reload();
      });
      slot.appendChild(out);
    } else {
      var b = document.createElement('button');
      b.className = 'btn btn-primary btn-sm';
      b.textContent = '登录 / 注册';
      b.addEventListener('click', openLogin);
      slot.appendChild(b);
    }
  }

  function setAlert(host, msg) {
    host.innerHTML = msg ? '<div class="alert">' + fmt.esc(msg) + '</div>' : '';
  }

  function busy(btn, on) {
    if (on) {
      if (!btn.dataset.label) btn.dataset.label = btn.textContent;
      btn.classList.add('is-loading');
      btn.disabled = true;
    } else {
      btn.classList.remove('is-loading');
      btn.disabled = false;
      if (btn.dataset.label) btn.textContent = btn.dataset.label;
    }
  }

  function afterAuth(data) {
    Api.setSession(data.access_token, data.user);
    renderAuth(data.user);
    closeAll();
    toast('欢迎，' + (data.user.nickname || data.user.username), 'ok');
    if (window.Workbench) Workbench.onLogin();
  }

  $('loginForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    setAlert($('loginAlert'), '');
    var f = e.target;
    var payload = { username: f.username.value.trim(), password: f.password.value };
    if (!payload.username || !payload.password) { setAlert($('loginAlert'), '请填写用户名和密码'); return; }
    var btn = $('loginBtn');
    busy(btn, true);
    try {
      afterAuth(await Api.post('/api/auth/login', payload));
    } catch (err) {
      setAlert($('loginAlert'), err.message);
    } finally {
      busy(btn, false);
    }
  });

  $('regForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    setAlert($('regAlert'), '');
    var f = e.target;
    var payload = {
      username: f.username.value.trim(),
      password: f.password.value,
      email: f.email.value.trim() || null
    };
    if (payload.password.length < 6) { setAlert($('regAlert'), '密码至少需要 6 位'); return; }
    var btn = $('regBtn');
    busy(btn, true);
    try {
      afterAuth(await Api.post('/api/auth/register', payload));
    } catch (err) {
      setAlert($('regAlert'), err.message);
    } finally {
      busy(btn, false);
    }
  });

  $('toRegBtn').addEventListener('click', openReg);
  $('toLoginBtn').addEventListener('click', openLogin);

  // 点击遮罩空白处关闭
  [loginOverlay, regOverlay].forEach(function (o) {
    o.addEventListener('click', function (e) { if (e.target === o) closeAll(); });
  });

  async function boot() {
    if (window.Workbench) Workbench.boot();

    if (Api.token) {
      try {
        var me = await Api.get('/api/auth/me');
        renderAuth(me);
        if (window.Workbench) Workbench.onLogin();
        return;
      } catch (e) {
        Api.clearSession();
      }
    }
    renderAuth(null);
    openLogin();
  }

  boot();
})();
