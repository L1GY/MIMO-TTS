/* 音频转文字视图 */
(function () {
  'use strict';

  var el = {};
  var file = null;
  var maxMb = 7;
  var lastResult = null;

  function $(id) { return document.getElementById(id); }

  function showAlert(msg, kind) {
    el.alert.innerHTML = '<div class="alert alert-' + (kind || 'error') + '">' + fmt.esc(msg) + '</div>';
  }
  function clearAlert() { el.alert.innerHTML = ''; }

  function pickFile(f) {
    if (!f) return;
    var name = (f.name || '').toLowerCase();
    if (!/\.(wav|mp3)$/.test(name)) { showAlert('仅支持 wav 或 mp3 格式的音频'); return; }
    if (f.size > maxMb * 1024 * 1024) {
      showAlert('文件体积 ' + fmt.bytes(f.size) + '，超过上限 ' + maxMb + 'MB'); return;
    }
    if (f.size === 0) { showAlert('这个文件是空的'); return; }

    file = f;
    clearAlert();
    el.drop.classList.add('has-file');
    el.dropInner.innerHTML =
      '<div class="big">' + fmt.esc(f.name) + '</div>' +
      '<div class="small">' + fmt.bytes(f.size) + ' · 点击可更换文件</div>';
    el.fileName.textContent = fmt.bytes(f.size);
    el.submit.disabled = false;
  }

  function reset() {
    file = null;
    el.file.value = '';
    el.drop.classList.remove('has-file');
    el.dropInner.innerHTML =
      '<div class="big">点击选择音频，或把文件拖到这里</div>' +
      '<div class="small">支持 wav / mp3，不超过 ' + maxMb + 'MB</div>';
    el.fileName.textContent = '未选择';
    el.submit.disabled = true;
    el.result.textContent = '识别结果会显示在这里';
    el.result.classList.add('placeholder');
    el.meta.innerHTML = '';
    el.copy.disabled = true;
    el.downloadTxt.disabled = true;
    el.listen.disabled = true;
    lastResult = null;
    clearAlert();
  }

  async function submit() {
    if (!file) return;
    clearAlert();
    var fd = new FormData();
    fd.append('file', file);
    fd.append('language', el.lang.value);

    el.submit.disabled = true;
    el.submit.innerHTML = '<span class="spinner"></span>识别中';
    el.result.textContent = '正在识别，请稍候…';
    el.result.classList.add('placeholder');

    try {
      var r = await Api.post('/api/asr/transcribe', fd);
      lastResult = r;
      el.result.textContent = r.transcript;
      el.result.classList.remove('placeholder');
      el.meta.innerHTML =
        '<span>' + (r.audio_seconds ? fmt.seconds(r.audio_seconds) : '') + '</span>' +
        '<span>' + r.latency_ms + ' ms</span>' +
        (r.is_mock ? '<span class="badge badge-mock">模拟结果</span>' : '<span class="badge badge-ok">完成</span>');
      el.copy.disabled = false;
      el.downloadTxt.disabled = false;
      el.listen.disabled = false;
      toast('识别完成' + (r.is_mock ? '（模拟模式）' : ''), 'ok');
      ASR.refreshRecent();
    } catch (err) {
      el.result.textContent = '识别失败';
      el.result.classList.add('placeholder');
      showAlert(err.message);
      toast(err.message, 'err');
      ASR.refreshRecent();
    } finally {
      el.submit.disabled = false;
      el.submit.textContent = '开始识别';
    }
  }

  function downloadText() {
    if (!lastResult) return;
    var blob = new Blob([lastResult.transcript], { type: 'text/plain;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'transcript_' + lastResult.id + '.txt';
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }

  var ASR = {
    mount: async function () {
      el = {
        drop: $('drop'), dropInner: $('dropInner'), file: $('asrFile'), fileName: $('asrFileName'),
        lang: $('asrLang'), submit: $('asrSubmit'), alert: $('asrAlert'), result: $('asrResult'),
        meta: $('asrMeta'), copy: $('asrCopy'), downloadTxt: $('asrDownloadTxt'),
        listen: $('asrListen'), recent: $('asrRecent')
      };

      try {
        var opt = await Api.get('/api/asr/options');
        maxMb = opt.max_upload_mb || 7;
        $('asrMaxMb').textContent = maxMb;
      } catch (e) { /* 用默认值 */ }

      el.drop.addEventListener('click', function () { el.file.click(); });
      el.drop.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.file.click(); }
      });
      el.file.addEventListener('change', function () { pickFile(this.files[0]); });

      ['dragenter', 'dragover'].forEach(function (t) {
        el.drop.addEventListener(t, function (e) { e.preventDefault(); el.drop.classList.add('over'); });
      });
      ['dragleave', 'drop'].forEach(function (t) {
        el.drop.addEventListener(t, function (e) { e.preventDefault(); el.drop.classList.remove('over'); });
      });
      el.drop.addEventListener('drop', function (e) {
        if (e.dataTransfer && e.dataTransfer.files.length) pickFile(e.dataTransfer.files[0]);
      });

      el.submit.addEventListener('click', submit);
      $('asrReset').addEventListener('click', reset);
      el.copy.addEventListener('click', function () {
        if (lastResult) copyText(lastResult.transcript);
      });
      el.downloadTxt.addEventListener('click', downloadText);
      el.listen.addEventListener('click', function () {
        if (!lastResult) return;
        var a = new Audio(Api.authed(lastResult.audio_url));
        a.play().catch(function () { toast('无法播放该音频', 'err'); });
      });

      reset();
      ASR.refreshRecent();
    },

    refreshRecent: async function () {
      if (!el.recent) return;
      try {
        var r = await Api.get('/api/asr/history?page_size=6');
        el.recent.innerHTML = '';
        if (!r.items.length) {
          el.recent.innerHTML = '<div class="empty" style="padding:18px 8px"><p>暂无记录</p></div>';
          return;
        }
        r.items.forEach(function (item) {
          var d = document.createElement('div');
          d.className = 'rec';
          d.style.padding = '10px 12px';
          d.innerHTML =
            '<div style="font-size:13px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">' +
              fmt.esc(item.transcript || item.filename || '（无结果）') + '</div>' +
            '<div class="meta-row" style="margin-top:6px">' +
              '<span>' + fmt.dateTime(item.created_at) + '</span>' +
              (item.status === 'failed'
                ? '<span class="badge badge-err">失败</span>'
                : '<span>' + fmt.esc(item.language) + '</span>') +
            '</div>';
          el.recent.appendChild(d);
        });
      } catch (e) { /* 静默 */ }
    }
  };

  window.ASR = ASR;
})();
