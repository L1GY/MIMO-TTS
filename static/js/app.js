/* 应用外壳：鉴权、首页声纹、视图路由 */
(function () {
  'use strict';

  function $(id) { return document.getElementById(id); }

  var views = {
    tts: $('view-tts'),
    design: $('view-design'),
    asr: $('view-asr'),
    records: $('view-records')
  };
  var mounted = {};
  var heroWave = null;

  function go(name, after) {
    if (!views[name]) name = 'tts';

    Object.keys(views).forEach(function (k) { views[k].hidden = (k !== name); });
    document.querySelectorAll('#nav button').forEach(function (b) {
      if (b.dataset.view === name) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });

    // 首屏只在落地页展示
    $('hero').hidden = (name !== 'tts');

    if (name !== 'tts' && window.TTS) TTS.stopAudio();
    if (name !== 'design' && window.Design) Design.stopAudio();

    if (!mounted[name]) {
      if (name === 'tts' && window.TTS) { TTS.mount(); mounted.tts = true; }
      if (name === 'design' && window.Design) { Design.mount(); mounted.design = true; }
      if (name === 'asr' && window.ASR) { ASR.mount(); mounted.asr = true; }
      if (name === 'records' && window.Records) { Records.mount(); mounted.records = true; }
    } else if (name === 'records' && window.Records) {
      Records.reload();
    }

    if (location.hash.slice(1) !== name) history.replaceState(null, '', '#' + name);
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (after) after();
  }

  function renderBanner(meta) {
    var b = $('banner');
    if (meta.live_mode) {
      b.innerHTML = '<div class="banner"><span class="dot"></span>' +
        '<span>已连接语音服务，生成与识别都是真实调用。</span></div>';
    } else {
      b.innerHTML = '<div class="banner"><span class="dot mock"></span>' +
        '<span>当前为模拟模式：未配置密钥或已开启 MOCK_MODE，返回的是本地占位音频与文本。</span></div>';
    }
  }

  async function boot() {
    if (!Api.token) { location.replace('/static/index.html'); return; }

    var me, meta;
    try {
      me = await Api.get('/api/auth/me');
      meta = await Api.get('/api/meta');
    } catch (e) {
      Api.redirectToLogin();
      return;
    }

    Api.setSession(Api.token, me);
    $('whoName').textContent = me.nickname || me.username;
    $('avatar').textContent = (me.nickname || me.username).trim().charAt(0).toUpperCase();
    renderBanner(meta);

    // 首屏声纹
    if (!heroWave) {
      heroWave = new Waveform($('heroWave'), {
        bars: 72,
        color: '#7FD8EA',
        idleColor: 'rgba(232,235,247,.18)'
      });
    }
    heroWave.animateSynthetic();

    $('logoutBtn').addEventListener('click', function () {
      Api.clearSession();
      location.replace('/static/index.html');
    });

    document.querySelectorAll('#nav button').forEach(function (b) {
      b.addEventListener('click', function () { go(b.dataset.view); });
    });

    document.querySelectorAll('.cap').forEach(function (cap) {
      cap.addEventListener('click', function () {
        var target = cap.dataset.goto;
        if (target === 'listen') {
          var panel = document.querySelector('#view-tts .side .card');
          if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
          toast('生成后音频会出现在右侧播放器', 'ok', 3000);
          return;
        }
        go(target);
      });
    });

    var initial = location.hash.slice(1);
    go(views[initial] ? initial : 'tts');
  }

  window.App = { go: go };
  boot();
})();
