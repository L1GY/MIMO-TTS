/* 接口访问层：令牌管理、错误处理、提示与格式化。 */
(function () {
  'use strict';

  var TOKEN_KEY = 'va_token';
  var USER_KEY = 'va_user';

  var Api = {
    get token() { return localStorage.getItem(TOKEN_KEY) || ''; },
    get user() {
      try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); }
      catch (e) { return null; }
    },
    setSession: function (token, user) {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(USER_KEY, JSON.stringify(user || {}));
    },
    clearSession: function () {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    },
    redirectToLogin: function () {
      Api.clearSession();
      if (!/index\.html$/.test(location.pathname)) {
        location.href = '/static/index.html';
      }
    },

    /** 把令牌拼到 URL 上，供 <audio src> 等无法自定义请求头的场景使用。 */
    authed: function (url) {
      return url + (url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(Api.token);
    },

    request: async function (path, options) {
      options = options || {};
      var headers = {};
      var body = options.body;

      if (body && !(body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
        body = JSON.stringify(body);
      }
      if (Api.token) headers['Authorization'] = 'Bearer ' + Api.token;

      var resp;
      try {
        resp = await fetch(path, { method: options.method || 'GET', headers: headers, body: body });
      } catch (e) {
        throw new Error('网络连接失败，请检查服务是否已启动');
      }

      if (resp.status === 401) {
        Api.redirectToLogin();
        throw new Error('登录状态已失效，请重新登录');
      }

      var isJson = (resp.headers.get('content-type') || '').indexOf('application/json') >= 0;
      var data = isJson ? await resp.json() : await resp.text();

      if (!resp.ok) {
        var msg = '请求失败（HTTP ' + resp.status + '）';
        var code = '';
        if (data && data.error) {
          msg = data.error.message || msg;
          code = data.error.code || '';
        }
        var err = new Error(msg);
        err.code = code;
        err.status = resp.status;
        throw err;
      }
      return data;
    },

    get: function (p) { return Api.request(p); },
    post: function (p, b) { return Api.request(p, { method: 'POST', body: b }); },
    patch: function (p, b) { return Api.request(p, { method: 'PATCH', body: b }); },
    del: function (p) { return Api.request(p, { method: 'DELETE' }); }
  };

  /* ------------------------------------------------------------ 提示条 */

  function toast(message, kind, ms) {
    var host = document.getElementById('toasts');
    if (!host) {
      host = document.createElement('div');
      host.id = 'toasts';
      document.body.appendChild(host);
    }
    var el = document.createElement('div');
    el.className = 'toast' + (kind === 'err' ? ' err' : kind === 'ok' ? ' ok' : '');
    el.textContent = message;
    host.appendChild(el);
    setTimeout(function () {
      el.style.transition = 'opacity .2s ease, transform .2s ease';
      el.style.opacity = '0';
      el.style.transform = 'translateY(6px)';
      setTimeout(function () { el.remove(); }, 220);
    }, ms || (kind === 'err' ? 5200 : 2800));
  }

  /* ------------------------------------------------------------ 格式化 */

  function formatBytes(n) {
    if (n === null || n === undefined) return '—';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(2) + ' MB';
  }

  function formatDateTime(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    var p = function (x) { return x < 10 ? '0' + x : '' + x; };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
      ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  function formatSeconds(s) {
    if (s === null || s === undefined) return '—';
    return Number(s).toFixed(1) + ' 秒';
  }

  function escapeHtml(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function copy(text, okMsg) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { toast(okMsg || '已复制到剪贴板', 'ok'); },
        function () { toast('复制失败，请手动选择文本', 'err'); }
      );
    } else {
      toast('当前浏览器不支持自动复制', 'err');
    }
  }

  window.Api = Api;
  window.toast = toast;
  window.copyText = copy;
  window.fmt = {
    bytes: formatBytes,
    dateTime: formatDateTime,
    seconds: formatSeconds,
    esc: escapeHtml
  };

  /* 生成/播放共用：把一段结果渲染成播放器，供多个视图复用 */
  window.renderPlayer = function (host, opts) {
    var url = Api.authed(opts.url);
    var html =
      '<div class="player"><audio controls src="' + url + '"></audio></div>' +
      '<div class="row-end" style="margin-top:12px">' +
        '<a class="btn btn-outline" href="' + url + '" download="' + (opts.filename || 'voice.wav') + '">下载音频</a>' +
        (opts.text ? '<button class="btn btn-ghost" data-act="copy">复制文本</button>' : '') +
      '</div>' +
      '<div class="meta-row" style="margin-top:12px">' +
        (opts.size ? '<span>' + fmt.bytes(opts.size) + '</span>' : '') +
        (opts.latency ? '<span>' + opts.latency + ' ms</span>' : '') +
        (opts.voiceName ? '<span class="badge badge-brand">' + fmt.esc(opts.voiceName) + '</span>' : '') +
        (opts.isMock ? '<span class="badge badge-mock">模拟音频</span>' : '') +
      '</div>';
    host.innerHTML = html;

    var btn = host.querySelector('[data-act="copy"]');
    if (btn) btn.addEventListener('click', function () { copy(opts.text || ''); });

    return host.querySelector('audio');
  };
})();
