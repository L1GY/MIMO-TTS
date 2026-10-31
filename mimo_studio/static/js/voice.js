/* 我的音色页：拖拽上传、前端校验、时长读取 */
(function () {
  'use strict';

  var zone = document.getElementById('dropZone');
  var input = document.getElementById('fileInput');
  var idle = document.getElementById('dropIdle');
  var fileBox = document.getElementById('dropFile');
  var nameEl = document.getElementById('fileName');
  var metaEl = document.getElementById('fileMeta');
  var errorEl = document.getElementById('fileError');
  var form = document.getElementById('voiceForm');

  if (!zone || !input) return;

  var MIN_SEC = parseFloat(zone.dataset.min || '3');
  var MAX_SEC = parseFloat(zone.dataset.max || '10');
  var MAX_MB = parseFloat(zone.dataset.mb || '10');
  var picked = null;

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.classList.remove('hidden');
  }
  function clearError() {
    errorEl.textContent = '';
    errorEl.classList.add('hidden');
  }

  function humanSize(bytes) {
    var mb = bytes / 1024 / 1024;
    return mb >= 1 ? mb.toFixed(1) + ' MB' : Math.round(bytes / 1024) + ' KB';
  }

  function setFile(file) {
    clearError();
    if (!file) return;

    var ext = (file.name.split('.').pop() || '').toLowerCase();
    if (['wav', 'mp3'].indexOf(ext) === -1) {
      showError('仅支持 wav / mp3 格式');
      return;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      showError('文件 ' + humanSize(file.size) + '，超过 ' + MAX_MB + 'MB 上限');
      return;
    }

    picked = file;
    idle.classList.add('hidden');
    fileBox.classList.remove('hidden');
    nameEl.textContent = file.name;
    metaEl.textContent = humanSize(file.size) + ' · 读取时长…';

    // 用浏览器解码音频读取真实时长，避免用户上传超长文件后才发现
    var url = URL.createObjectURL(file);
    var probe = new Audio();
    probe.preload = 'metadata';
    probe.onloadedmetadata = function () {
      var sec = probe.duration;
      URL.revokeObjectURL(url);
      if (!isFinite(sec) || sec <= 0) {
        metaEl.textContent = humanSize(file.size) + ' · 无法读取时长';
        return;
      }
      var text = humanSize(file.size) + ' · ' + sec.toFixed(1) + ' 秒';
      metaEl.textContent = text;
      if (sec < MIN_SEC) showError('样本只有 ' + sec.toFixed(1) + ' 秒，太短了，建议 ' + MIN_SEC + '-' + MAX_SEC + ' 秒');
      else if (sec > MAX_SEC) showError('样本人声 ' + sec.toFixed(1) + ' 秒，太长了，建议 ' + MIN_SEC + '-' + MAX_SEC + ' 秒');
    };
    probe.onerror = function () {
      URL.revokeObjectURL(url);
      metaEl.textContent = humanSize(file.size) + ' · 浏览器无法解析时长，提交后由服务端校验';
    };
    probe.src = url;
  }

  zone.addEventListener('click', function () { input.click(); });

  ['dragenter', 'dragover'].forEach(function (evt) {
    zone.addEventListener(evt, function (e) {
      e.preventDefault();
      zone.classList.add('drop-active');
    });
  });
  ['dragleave', 'drop'].forEach(function (evt) {
    zone.addEventListener(evt, function (e) {
      e.preventDefault();
      zone.classList.remove('drop-active');
    });
  });
  zone.addEventListener('drop', function (e) {
    var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) {
      input.files = e.dataTransfer.files;
      setFile(file);
    }
  });

  input.addEventListener('change', function () {
    setFile(input.files && input.files[0]);
  });

  form.addEventListener('submit', function (e) {
    var consent = document.getElementById('consentBox');
    if (!picked) {
      e.preventDefault();
      showError('请先选择要上传的音色样本');
      return;
    }
    if (consent && !consent.checked) {
      e.preventDefault();
      window.toast('请先勾选声音授权协议', 'error');
      consent.focus();
      return;
    }
    clearError();
  });
})();
