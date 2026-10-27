/* 登录 / 注册页 */
(function () {
  'use strict';

  if (Api.token) { location.replace('/static/app.html'); return; }

  /* 品牌侧声纹 */
  var brandWave = new Waveform(document.getElementById('brandWave'), {
    bars: 64,
    color: '#7FD8EA',
    idleColor: 'rgba(232,235,247,.20)'
  });
  brandWave.animateSynthetic();

  /* 微信登录开关 */
  Api.get('/api/meta').then(function (m) {
    if (m.wechat_enabled) {
      document.getElementById('wxBtn').hidden = false;
      document.getElementById('wxDivider').hidden = false;
    }
  }).catch(function () { /* 服务未就绪时静默 */ });

  var tabLogin = document.getElementById('tab-login');
  var tabReg = document.getElementById('tab-register');
  var paneLogin = document.getElementById('pane-login');
  var paneReg = document.getElementById('pane-register');

  function switchTo(which) {
    var isLogin = which === 'login';
    tabLogin.setAttribute('aria-selected', String(isLogin));
    tabReg.setAttribute('aria-selected', String(!isLogin));
    paneLogin.hidden = !isLogin;
    paneReg.hidden = isLogin;
    clearAlert('loginAlert');
    clearAlert('regAlert');
  }
  tabLogin.addEventListener('click', function () { switchTo('login'); });
  tabReg.addEventListener('click', function () { switchTo('register'); });

  function clearAlert(id) { document.getElementById(id).innerHTML = ''; }
  function showAlert(id, msg, kind) {
    document.getElementById(id).innerHTML =
      '<div class="alert alert-' + (kind || 'error') + '">' + fmt.esc(msg) + '</div>';
  }

  function busy(btn, on, text) {
    if (on) {
      if (!btn.dataset.label) btn.dataset.label = btn.textContent;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span>' + text;
    } else {
      btn.disabled = false;
      btn.textContent = btn.dataset.label || btn.textContent;
    }
  }

  function afterAuth(data) {
    Api.setSession(data.access_token, data.user);
    toast('欢迎回来，' + (data.user.nickname || data.user.username), 'ok');
    setTimeout(function () { location.href = '/static/app.html'; }, 260);
  }

  var loginBtn = document.getElementById('loginBtn');
  loginBtn.dataset.label = '登录';
  document.getElementById('loginForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    clearAlert('loginAlert');
    var f = e.target;
    var payload = { username: f.username.value.trim(), password: f.password.value };
    if (!payload.username || !payload.password) { showAlert('loginAlert', '请填写用户名和密码'); return; }
    busy(loginBtn, true, '登录中');
    try {
      afterAuth(await Api.post('/api/auth/login', payload));
    } catch (err) {
      showAlert('loginAlert', err.message);
    } finally {
      busy(loginBtn, false);
    }
  });

  var regBtn = document.getElementById('regBtn');
  regBtn.dataset.label = '注册并登录';
  document.getElementById('regForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    clearAlert('regAlert');
    var f = e.target;
    var payload = {
      username: f.username.value.trim(),
      password: f.password.value,
      email: f.email.value.trim() || null
    };
    if (payload.password.length < 6) { showAlert('regAlert', '密码至少需要 6 位'); return; }
    busy(regBtn, true, '创建中');
    try {
      afterAuth(await Api.post('/api/auth/register', payload));
    } catch (err) {
      showAlert('regAlert', err.message);
    } finally {
      busy(regBtn, false);
    }
  });

  document.getElementById('wxBtn').addEventListener('click', async function () {
    try {
      var r = await Api.get('/api/auth/wechat/qr');
      var w = window.open(r.authorize_url, 'wechat_login',
        'width=620,height=620,left=' + (screen.width / 2 - 310) + ',top=' + (screen.height / 2 - 310));
      if (!w) { toast('浏览器拦截了弹窗，请允许后重试', 'err'); return; }
      var timer = setInterval(function () {
        if (w.closed) {
          clearInterval(timer);
          if (Api.token) location.href = '/static/app.html';
        }
      }, 600);
    } catch (err) {
      toast(err.message, 'err');
    }
  });
})();
