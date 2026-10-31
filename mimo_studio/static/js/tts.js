/* 语音合成页：字数统计、音色切换、语速、提交、任务轮询 */
(function () {
  'use strict';

  var form = document.getElementById('ttsForm');
  if (!form) return;

  var textarea = document.getElementById('ttsText');
  var counter = document.getElementById('charCount');
  var speedRange = document.getElementById('speedRange');
  var speedVal = document.getElementById('speedVal');
  var costHint = document.getElementById('costHint');
  var submitBtn = document.getElementById('submitBtn');
  var maxLen = parseInt(textarea.getAttribute('maxlength') || '3000', 10);

  /* ---------------------------------------------------------------- 字数 */
  function updateCount() {
    var n = textarea.value.length;
    counter.textContent = n;
    counter.classList.toggle('text-rose-500', n > maxLen);
    if (costHint) costHint.textContent = '预计消耗 ' + n + ' 字额度';
  }
  textarea.addEventListener('input', updateCount);
  updateCount();

  document.getElementById('clearText').addEventListener('click', function () {
    textarea.value = '';
    updateCount();
    textarea.focus();
  });

  document.getElementById('fillSample').addEventListener('click', function () {
    textarea.value = '你好，欢迎使用 MiMo 声音工坊。这里可以把任意文字转换成自然流畅的人声，'
      + '也支持上传一段参考音频来克隆你自己的音色。';
    updateCount();
    textarea.focus();
  });

  /* ---------------------------------------------------------------- 音色选择 */
  function refreshSelected() {
    document.querySelectorAll('.voice-card').forEach(function (card) {
      var input = card.querySelector('input[type="radio"]');
      card.classList.toggle('is-selected', !!(input && input.checked));
    });
  }
  document.querySelectorAll('.voice-card input[type="radio"]').forEach(function (input) {
    input.addEventListener('change', refreshSelected);
  });
  refreshSelected();

  // 公共 / 我的 音色 Tab
  var tabs = document.querySelectorAll('.voice-tab');
  var panels = { preset: document.getElementById('tabPreset'), mine: document.getElementById('tabMine') };

  function switchTab(key) {
    tabs.forEach(function (t) {
      var on = t.dataset.tab === key;
      t.classList.toggle('bg-white', on);
      t.classList.toggle('shadow-sm', on);
      t.classList.toggle('text-brand-700', on);
      t.classList.toggle('dark:bg-slate-900', on);
      t.classList.toggle('dark:text-brand-300', on);
      t.classList.toggle('text-slate-500', !on);
    });
    Object.keys(panels).forEach(function (k) {
      if (panels[k]) panels[k].classList.toggle('hidden', k !== key);
    });
  }
  tabs.forEach(function (t) {
    t.addEventListener('click', function () { switchTab(t.dataset.tab); });
  });
  switchTab('preset');

  /* ---------------------------------------------------------------- 语速 */
  function updateSpeed() {
    speedVal.textContent = parseFloat(speedRange.value).toFixed(1) + '×';
  }
  speedRange.addEventListener('input', updateSpeed);
  updateSpeed();

  /* ---------------------------------------------------------------- 样本试听 */
  var sampleAudio = null;
  document.querySelectorAll('.js-play-sample').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      var src = btn.dataset.src;
      if (!src) return;
      if (sampleAudio) { sampleAudio.pause(); sampleAudio = null; }
      sampleAudio = new Audio(src);
      sampleAudio.play().catch(function () { window.toast('样本播放失败', 'error'); });
      sampleAudio.addEventListener('ended', function () {
        btn.innerHTML = '<i class="fa-solid fa-play"></i>';
      });
      btn.innerHTML = '<i class="fa-solid fa-pause"></i>';
    });
  });

  /* ---------------------------------------------------------------- 提交 */
  form.addEventListener('submit', function (e) {
    if (!textarea.value.trim()) {
      e.preventDefault();
      window.toast('请先输入要合成的文本', 'error');
      textarea.focus();
      return;
    }
    if (submitBtn && !submitBtn.disabled) {
      submitBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>提交中…</span>';
    }
  });

  textarea.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      if (submitBtn && !submitBtn.disabled) form.requestSubmit(submitBtn);
    }
  });

  /* ---------------------------------------------------------------- 任务轮询 */
  var card = document.getElementById('taskCard');
  if (!card) return;

  var taskId = card.dataset.taskId;
  if (!taskId) return;

  var statusEl = document.getElementById('taskStatus');
  var progressEl = document.getElementById('taskProgress');
  var hintEl = document.getElementById('taskHint');
  var errorEl = document.getElementById('taskError');
  var resultEl = document.getElementById('taskResult');
  var progressWrap = document.getElementById('taskProgressWrap');
  var timer = null;

  var BADGE = {
    queued: ['bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300', '排队中'],
    running: ['bg-sky-50 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300', '生成中'],
    success: ['bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300', '已完成'],
    failed: ['bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300', '失败']
  };

  function setBadge(status) {
    var meta = BADGE[status] || BADGE.queued;
    statusEl.className = 'rounded-full px-2.5 py-1 text-[11.5px] font-medium ' + meta[0];
    statusEl.textContent = meta[1];
  }

  function renderResult(data) {
    resultEl.classList.remove('hidden');
    var old = resultEl.querySelector('.player-mount');
    var fresh = document.createElement('div');
    fresh.className = 'player-mount';
    fresh.dataset.audio = data.audio_url;
    fresh.dataset.title = '合成结果';
    if (old) old.replaceWith(fresh); else resultEl.prepend(fresh);
    if (window.Player) window.Player.mountAll(resultEl);

    var link = resultEl.querySelector('a[href^="/records/"]');
    if (link && data.download_url) link.href = data.download_url;
  }

  function poll() {
    fetch('/api/tasks/' + taskId, { headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json();
      })
      .then(function (data) {
        if (!data) return;

        setBadge(data.status);
        progressEl.style.width = (data.progress || 0) + '%';

        if (data.status === 'success') {
          clearInterval(timer);
          progressEl.style.width = '100%';
          hintEl.textContent = '已完成 · ' + (data.duration_text || '') + ' · ' + (data.size_text || '');
          errorEl.classList.add('hidden');
          renderResult(data);
          window.toast('合成完成', 'success');
          return;
        }

        if (data.status === 'failed') {
          clearInterval(timer);
          progressWrap.classList.add('hidden');
          errorEl.classList.remove('hidden');
          errorEl.textContent = data.error || '生成失败，请稍后重试';
          window.toast('合成失败', 'error');
          return;
        }

        hintEl.textContent = data.status === 'queued'
          ? '排队中，前面还有任务在跑…'
          : '正在生成（' + (data.progress || 0) + '%），请稍候…';
      })
      .catch(function () { /* 网络抖动时不打断，下个周期再试 */ });
  }

  var initial = card.dataset.taskId && statusEl.textContent ? statusEl.textContent.trim() : '';
  if (initial.indexOf('已完成') === -1 && initial.indexOf('失败') === -1) {
    poll();
    timer = setInterval(poll, 3000);   // 每 3 秒轮询一次
  }
})();
