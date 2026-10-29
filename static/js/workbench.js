/* 工作台：模式切换、TTS / ASR 两条流水线、结果预览、历史记录 */
(function () {
  'use strict';

  var el = {};
  var mode = 'tts';
  var maxLen = 2000;
  var maxMb = 7;

  // 输出区当前状态
  var outAudioUrl = null;
  var outAudioName = null;
  var outWave = null;

  // ASR 录音
  var file = null;
  var rec = { recorder: null, stream: null, chunks: [], timer: null, start: 0 };
  var liveWave = null;

  var SAMPLES = [
    '今天的天气不错，适合出去走走。顺手把这份语音合成的效果也试一下。',
    '欢迎使用语音工具箱，这里可以把任意文字转换成自然的人声。',
    '夜色落下来的时候，城市才开始说真话。'
  ];

  function $(id) { return document.getElementById(id); }

  /* ------------------------------------------------------------ 通用 */

  function setAlert(host, msg) {
    host.innerHTML = msg ? '<div class="alert">' + fmt.esc(msg) + '</div>' : '';
  }

  function setStatus(text, kind, busy) {
    el.status.className = 'status-line' + (kind ? ' is-' + kind : '');
    el.status.innerHTML = busy ? '<span class="spinner"></span>' + fmt.esc(text) : fmt.esc(text);
  }

  function setChip(html) { el.outChip.innerHTML = html || ''; }

  function busy(btn, on, label) {
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

  /* ------------------------------------------------------------ 模式切换 */

  function setMode(next) {
    mode = next;
    document.querySelectorAll('.mode-card').forEach(function (c) {
      var on = c.dataset.mode === next;
      c.classList.toggle('is-active', on);
      c.setAttribute('aria-pressed', String(on));
    });
    el.inputTitle.textContent = next === 'tts' ? '文本输入' : '语音输入';
    el.paneTts.hidden = next !== 'tts';
    el.paneAsr.hidden = next !== 'asr';
    el.sampleBtn.hidden = next !== 'tts';
    if (next === 'asr' && !liveWave) {
      liveWave = new Waveform(el.liveWave, { bars: 36, color: '#00B4D8', idleColor: '#CBD5E1' });
    }
  }

  /* ------------------------------------------------------------ 输出区 */

  function showOutput(o) {
    outAudioUrl = o.audioUrl || null;
    outAudioName = o.audioName || 'voice.wav';

    el.outText.value = o.text || '';
    el.outChars.textContent = (o.text || '').length + ' 字';
    el.dlAudio.disabled = !outAudioUrl;
    el.copyOut.disabled = !o.text;

    el.outPlayer.innerHTML = '';
    el.outDuration.textContent = '';
    if (outAudioUrl) {
      var p = window.VoicePlayer.create({
        src: Api.authed(outAudioUrl),
        autoplay: true
      });
      el.outPlayer.appendChild(p);
      p.addEventListener('loadedmetadata', function () {});
      var a = p.querySelector('audio') || null;
      // 播放器内部懒创建 audio，这里轮询一次拿到时长
      var tries = 0;
      var t = setInterval(function () {
        var au = el.outPlayer.querySelector('audio');
        if (au && isFinite(au.duration) && au.duration > 0) {
          el.outDuration.textContent = '音频时长 ' + fmt.clock(au.duration);
          clearInterval(t);
        }
        if (++tries > 40) clearInterval(t);
      }, 120);
      if (!outWave) outWave = new Waveform(el.outWave, { bars: 56, color: '#00B4D8', idleColor: '#CBD5E1' });
      outWave.animateSynthetic();
    }
  }

  function resetOutput() {
    el.outText.value = '';
    el.outChars.textContent = '0 字';
    el.outPlayer.innerHTML = '';
    el.outDuration.textContent = '';
    el.dlAudio.disabled = true;
    el.copyOut.disabled = true;
    setChip('');
    if (outWave) outWave.idle();
  }

  /* ------------------------------------------------------------ TTS */

  async function loadVoices() {
    var opt = await Api.get('/api/tts/options');
    var mine = await Api.get('/api/voices?page_size=100');
    maxLen = opt.max_text_length || 2000;
    el.ttsLimit.textContent = '上限 ' + maxLen + ' 字';

    var html = '';
    if (mine.items && mine.items.length) {
      html += '<optgroup label="我的音色">' + mine.items.map(function (v) {
        return '<option value="mine:' + fmt.esc(v.id) + '">' + fmt.esc(v.name) + '</option>';
      }).join('') + '</optgroup>';
    }
    html += '<optgroup label="预置音色">' + (opt.voices || []).map(function (v) {
      return '<option value="preset:' + fmt.esc(v.id) + '">' + fmt.esc(v.name + ' · ' + v.desc) + '</option>';
    }).join('') + '</optgroup>';
    el.ttsVoice.innerHTML = html;
  }

  function updateTtsStats() {
    var n = el.ttsText.value.length;
    el.ttsChars.textContent = n + ' 字';
    el.ttsChars.style.color = n > maxLen ? 'var(--danger)' : '';
  }

  async function runTts() {
    setAlert(el.ttsAlert, '');
    var text = el.ttsText.value.trim();
    if (!text) { setAlert(el.ttsAlert, '请先输入需要合成的文本'); el.ttsText.focus(); return; }
    if (text.length > maxLen) { setAlert(el.ttsAlert, '文本超过 ' + maxLen + ' 字，请精简后再试'); return; }

    var sel = el.ttsVoice.value || '';
    var payload = {
      text: text,
      audio_format: el.ttsFormat.value,
      speed: parseFloat(el.ttsSpeed.value),
      pitch: parseFloat(el.ttsPitch.value)
    };
    if (el.ttsRate.value) payload.sample_rate = parseInt(el.ttsRate.value, 10);
    if (sel.indexOf('mine:') === 0) payload.voice_preset_id = sel.slice(5);
    else payload.voice = sel.slice(7);

    busy(el.ttsSubmit, true);
    setStatus('正在合成，请稍候', 'busy', true);
    setChip('');

    try {
      var r = await Api.post('/api/tts/synthesize', payload);
      showOutput({
        text: r.text_final || text,
        audioUrl: r.audio_url,
        audioName: 'voice_' + r.id + '.' + (r.mime === 'audio/mpeg' ? 'mp3' : 'wav')
      });
      setStatus('合成完成', 'ok');
      setChip('<span class="chip chip-ok">成功</span>' +
        '<span class="chip">' + fmt.esc(r.voice_name || '未命名音色') + '</span>' +
        '<span class="chip">' + r.latency_ms + ' ms</span>');
      if (r.effects && r.effects.duration) {
        el.outDuration.textContent = '音频时长 ' + fmt.clock(r.effects.duration) +
          '（已应用语速/音调/采样率）';
      }
      toast('合成完成', 'ok');
      History.refresh();
    } catch (err) {
      setStatus('合成失败：' + err.message, 'err');
      setChip('<span class="chip chip-err">失败</span>');
      setAlert(el.ttsAlert, err.message);
      toast(err.message, 'err');
    } finally {
      busy(el.ttsSubmit, false);
    }
  }

  async function saveVoice() {
    var name = el.vdName.value.trim();
    var desc = el.vdDesc.value.trim();
    if (!name || !desc) { toast('请填写音色名称和描述', 'err'); return; }
    try {
      await Api.post('/api/voices', { name: name, description: desc });
      toast('已保存音色「' + name + '」', 'ok');
      el.vdName.value = '';
      el.vdDesc.value = '';
      el.designPanel.hidden = true;
      await loadVoices();
    } catch (e) {
      toast(e.message, 'err');
    }
  }

  /* ------------------------------------------------------------ ASR */

  function micSupported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }

  function setFile(f) {
    if (!f) return;
    var name = (f.name || '').toLowerCase();
    if (!/\.(wav|mp3)$/.test(name)) { setAlert(el.asrAlert, '仅支持 wav 或 mp3 格式的音频'); return; }
    if (f.size > maxMb * 1024 * 1024) {
      setAlert(el.asrAlert, '文件体积 ' + fmt.bytes(f.size) + '，超过上限 ' + maxMb + 'MB'); return;
    }
    file = f;
    el.asrSubmit.disabled = false;
    el.drop.classList.add('has-file');
    el.dropInner.innerHTML =
      '<div class="big">' + fmt.esc(f.name) + '</div>' +
      '<div class="small">' + fmt.bytes(f.size) + ' · 点击可更换</div>';
    setAlert(el.asrAlert, '');
    setStatus('已就绪，可以开始识别');
  }

  function clearAsr() {
    file = null;
    el.asrFile.value = '';
    el.asrSubmit.disabled = true;
    el.drop.classList.remove('has-file');
    el.dropInner.innerHTML =
      '<div class="big">拖拽上传音频，或点击选择文件</div>' +
      '<div class="small">支持 mp3 / wav，不超过 ' + maxMb + 'MB</div>';
    setAlert(el.asrAlert, '');
    setStatus('等待任务');
  }

  /** 录音结果 → 16kHz 单声道 16bit WAV（上游只接受 wav/mp3） */
  async function toWav(blob, targetRate) {
    var arr = await blob.arrayBuffer();
    var Ctx = window.AudioContext || window.webkitAudioContext;
    var ctx = new Ctx();
    var decoded = await ctx.decodeAudioData(arr);

    var len = Math.max(1, Math.ceil(decoded.duration * targetRate));
    var offline = new OfflineAudioContext(1, len, targetRate);
    var src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start();
    var rendered = await offline.startRendering();

    var d = rendered.getChannelData(0);
    var bytes = new Uint8Array(44 + d.length * 2);
    var view = new DataView(bytes.buffer);
    function str(off, s) { for (var i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); }
    str(0, 'RIFF'); view.setUint32(4, 36 + d.length * 2, true); str(8, 'WAVE');
    str(12, 'fmt '); view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, targetRate, true); view.setUint32(28, targetRate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    str(36, 'data'); view.setUint32(40, d.length * 2, true);
    var o = 44;
    for (var i = 0; i < d.length; i++, o += 2) {
      var s = Math.max(-1, Math.min(1, d[i]));
      view.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    try { ctx.close(); } catch (e) { /* 忽略 */ }
    return new Blob([bytes], { type: 'audio/wav' });
  }

  async function toggleRecord() {
    if (rec.recorder && rec.recorder.state !== 'inactive') { stopRecord(); return; }
    if (!micSupported()) { toast('当前浏览器不支持录音，请上传音频文件', 'err'); return; }

    try {
      rec.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      toast('无法访问麦克风：' + (err && err.message ? err.message : '权限被拒绝'), 'err');
      return;
    }

    rec.chunks = [];
    rec.recorder = new MediaRecorder(rec.stream);
    rec.recorder.ondataavailable = function (e) { if (e.data && e.data.size) rec.chunks.push(e.data); };
    rec.recorder.onstop = async function () {
      clearInterval(rec.timer);
      el.asrMic.classList.remove('is-rec');
      rec.stream.getTracks().forEach(function (t) { t.stop(); });
      if (liveWave) liveWave.idle();
      el.recMeta.textContent = '未录音';

      if (!rec.chunks.length) { setStatus('没有录到声音，请再试一次', 'err'); return; }
      setStatus('正在转换录音…', 'busy', true);
      try {
        var wav = await toWav(new Blob(rec.chunks, { type: rec.recorder.mimeType || 'audio/webm' }), 16000);
        setFile(new File([wav], 'recording.wav', { type: 'audio/wav' }));
        await runAsr();
      } catch (e) {
        setStatus('录音转换失败：' + (e && e.message ? e.message : e), 'err');
      }
    };

    rec.recorder.start();
    rec.start = Date.now();
    el.asrMic.classList.add('is-rec');
    if (liveWave) liveWave.animateSynthetic();
    rec.timer = setInterval(function () {
      el.recMeta.textContent = fmt.clock((Date.now() - rec.start) / 1000);
    }, 250);
    setStatus('正在录音，说完再点一次麦克风停止');
  }

  function stopRecord() {
    if (rec.recorder && rec.recorder.state !== 'inactive') rec.recorder.stop();
  }

  async function runAsr() {
    if (!file) { setAlert(el.asrAlert, '请先录音或上传一个音频文件'); return; }
    setAlert(el.asrAlert, '');

    var fd = new FormData();
    fd.append('file', file);
    fd.append('language', el.asrLang.value);
    fd.append('punctuate', el.asrPunct.checked ? 'true' : 'false');
    fd.append('segment', el.asrSeg.checked ? 'true' : 'false');

    busy(el.asrSubmit, true);
    setStatus('正在识别，请稍候', 'busy', true);
    setChip('');

    try {
      var r = await Api.post('/api/asr/transcribe', fd);
      var text = (r.segments && r.segments.length) ? r.segments.join('\n') : r.transcript;
      showOutput({
        text: text,
        audioUrl: r.audio_url,
        audioName: 'source_' + r.id + '.wav'
      });
      setStatus('识别完成', 'ok');
      setChip('<span class="chip chip-accent">ASR</span>' +
        '<span class="chip chip-ok">成功</span>' +
        (r.audio_seconds ? '<span class="chip">' + fmt.clock(r.audio_seconds) + '</span>' : '') +
        '<span class="chip">' + r.latency_ms + ' ms</span>');
      toast('识别完成', 'ok');
      History.refresh();
    } catch (err) {
      setStatus('识别失败：' + err.message, 'err');
      setChip('<span class="chip chip-err">失败</span>');
      setAlert(el.asrAlert, err.message);
      toast(err.message, 'err');
    } finally {
      busy(el.asrSubmit, false);
    }
  }

  /* ------------------------------------------------------------ 历史记录 */

  var History = {
    state: { tab: 'all', page: 1, size: 10, total: 0 },

    item: function (r) {
      var isTts = r.type === 'tts';
      var d = document.createElement('div');
      d.className = 'hist-item';

      var body = isTts ? (r.text_final || r.text_input) : (r.transcript || '（无结果）');
      if (r.status === 'failed') body = '失败原因：' + (r.error_message || '未知');

      var meta = [fmt.dateTime(r.created_at)];
      if (isTts) {
        if (r.voice_name) meta.push('音色 ' + r.voice_name);
        if (r.speed && Math.abs(r.speed - 1) > 0.01) meta.push('语速 ' + Number(r.speed).toFixed(1) + '×');
        if (r.pitch) meta.push('音调 ' + r.pitch);
        if (r.sample_rate) meta.push(r.sample_rate + ' Hz');
        if (r.audio_size) meta.push(fmt.bytes(r.audio_size));
      } else {
        meta.push('语种 ' + ({ auto: '自动', zh: '中文', en: '英文' }[r.language] || r.language));
        if (r.audio_seconds) meta.push('时长 ' + fmt.clock(r.audio_seconds));
        if (r.filename) meta.push(r.filename);
      }
      if (r.latency_ms) meta.push(r.latency_ms + ' ms');

      d.innerHTML =
        '<div class="hist-top">' +
          '<span class="chip ' + (isTts ? '' : 'chip-accent') + '">' +
            (isTts ? 'TTS 合成' : 'ASR 识别') + '</span>' +
          (r.status === 'failed'
            ? '<span class="chip chip-err">失败</span>'
            : '<span class="chip chip-ok">成功</span>') +
        '</div>' +
        '<div class="hist-body">' + fmt.esc(body) + '</div>' +
        '<div class="hist-meta">' + meta.map(function (m) {
          return '<span>' + fmt.esc(m) + '</span>';
        }).join('') + '</div>' +
        '<div class="hist-acts">' +
          (r.status === 'success' && r.has_audio
            ? '<button class="btn btn-sm btn-ghost" data-act="play">播放</button>' +
              '<a class="btn btn-sm btn-ghost" href="' + Api.authed('/api/' + r.type + '/' + r.id + '/download') + '">下载音频</a>'
            : '') +
          (isTts && r.status === 'success'
            ? '<button class="btn btn-sm btn-ghost" data-act="reuse">载入文本</button>' : '') +
          '<button class="btn btn-sm btn-danger" data-act="del">删除</button>' +
        '</div>';

      var play = d.querySelector('[data-act="play"]');
      if (play) {
        play.addEventListener('click', function () {
          if (d.querySelector('.player')) return;
          d.appendChild(window.VoicePlayer.create({
            src: Api.authed('/api/' + r.type + '/' + r.id + '/download'), autoplay: true
          }));
        });
      }
      var reuse = d.querySelector('[data-act="reuse"]');
      if (reuse) {
        reuse.addEventListener('click', function () {
          setMode('tts');
          el.ttsText.value = r.text_input || '';
          updateTtsStats();
          el.workbench.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      }
      d.querySelector('[data-act="del"]').addEventListener('click', async function () {
        if (!confirm('删除这条记录？对应的音频也会一并删除。')) return;
        try {
          await Api.del('/api/history/' + r.type + '/' + r.id);
          toast('已删除', 'ok');
          History.refresh();
        } catch (e) { toast(e.message, 'err'); }
      });
      return d;
    },

    load: async function (append) {
      if (!append) {
        el.histList.innerHTML =
          '<div class="skeleton" style="height:70px;margin-bottom:8px"></div>' +
          '<div class="skeleton" style="height:70px"></div>';
      }
      try {
        var q = '/api/history?type=' + History.state.tab +
          '&page=' + History.state.page + '&page_size=' + History.state.size;
        var r = await Api.get(q);
        History.state.total = r.total;
        if (!append) el.histList.innerHTML = '';

        if (!r.items.length && !append) {
          el.histList.innerHTML =
            '<div class="empty">还没有记录，完成一次合成或识别后会出现在这里</div>';
          el.histMore.hidden = true;
          return;
        }
        r.items.forEach(function (i) { el.histList.appendChild(History.item(i)); });
        var shown = el.histList.querySelectorAll('.hist-item').length;
        el.histMore.hidden = shown >= r.total;
      } catch (e) {
        el.histList.innerHTML = '<div class="alert">' + fmt.esc(e.message) + '</div>';
      }
    },

    refresh: function () { History.state.page = 1; History.load(false); }
  };
  window.History = History;

  /* ------------------------------------------------------------ 启动 */

  async function boot() {
    el = {
      workbench: $('workbench'),
      inputTitle: $('inputTitle'), sampleBtn: $('sampleBtn'),
      paneTts: $('pane-tts'), paneAsr: $('pane-asr'),
      ttsText: $('ttsText'), ttsChars: $('ttsChars'), ttsLimit: $('ttsLimit'),
      ttsVoice: $('ttsVoice'), ttsFormat: $('ttsFormat'), ttsRate: $('ttsRate'),
      ttsSpeed: $('ttsSpeed'), ttsSpeedVal: $('ttsSpeedVal'),
      ttsPitch: $('ttsPitch'), ttsPitchVal: $('ttsPitchVal'),
      ttsSubmit: $('ttsSubmit'), ttsClear: $('ttsClear'), ttsAlert: $('ttsAlert'),
      vdToggle: $('vdToggle'), designPanel: $('designPanel'),
      vdName: $('vdName'), vdDesc: $('vdDesc'), vdSave: $('vdSave'), vdCancel: $('vdCancel'),
      asrMic: $('asrMic'), liveWave: $('asrLiveWave'), recMeta: $('recMeta'),
      asrDrop: $('asrDrop'), dropInner: $('dropInner'), asrFile: $('asrFile'),
      asrLang: $('asrLang'), asrPunct: $('asrPunct'), asrSeg: $('asrSeg'),
      asrSubmit: $('asrSubmit'), asrClear: $('asrClear'), asrAlert: $('asrAlert'),
      status: $('statusLine'), outChip: $('outChip'), outText: $('outText'),
      outChars: $('outChars'), outWave: $('outWave'), outPlayer: $('outPlayer'),
      outDuration: $('outDuration'),
      dlAudio: $('dlAudio'), copyOut: $('copyOut'),
      histList: $('histList'), histMore: $('histMore')
    };

    // 模式卡
    document.querySelectorAll('.mode-card').forEach(function (c) {
      c.addEventListener('click', function () { setMode(c.dataset.mode); });
    });

    // TTS
    el.ttsText.addEventListener('input', updateTtsStats);
    el.ttsSubmit.addEventListener('click', runTts);
    el.ttsClear.addEventListener('click', function () {
      el.ttsText.value = ''; updateTtsStats(); setAlert(el.ttsAlert, '');
    });
    el.sampleBtn.addEventListener('click', function () {
      el.ttsText.value = SAMPLES[Math.floor(Math.random() * SAMPLES.length)];
      updateTtsStats();
      toast('已填入示例文本', 'ok');
    });
    el.ttsSpeed.addEventListener('input', function () {
      el.ttsSpeedVal.textContent = parseFloat(el.ttsSpeed.value).toFixed(1) + '×';
    });
    el.ttsPitch.addEventListener('input', function () {
      var v = parseInt(el.ttsPitch.value, 10);
      el.ttsPitchVal.textContent = (v > 0 ? '+' : '') + v;
    });
    el.vdToggle.addEventListener('click', function () {
      el.designPanel.hidden = !el.designPanel.hidden;
    });
    el.vdCancel.addEventListener('click', function () { el.designPanel.hidden = true; });
    el.vdSave.addEventListener('click', saveVoice);

    // ASR
    el.asrMic.addEventListener('click', toggleRecord);
    el.asrDrop.addEventListener('click', function () { el.asrFile.click(); });
    el.asrFile.addEventListener('change', function () { setFile(this.files[0]); });
    ['dragenter', 'dragover'].forEach(function (t) {
      el.asrDrop.addEventListener(t, function (e) { e.preventDefault(); el.asrDrop.classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (t) {
      el.asrDrop.addEventListener(t, function (e) { e.preventDefault(); el.asrDrop.classList.remove('over'); });
    });
    el.asrDrop.addEventListener('drop', function (e) {
      if (e.dataTransfer && e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
    });
    el.asrSubmit.addEventListener('click', runAsr);
    el.asrClear.addEventListener('click', clearAsr);

    // 输出区操作
    el.dlAudio.addEventListener('click', function () {
      if (!outAudioUrl) return;
      var a = document.createElement('a');
      a.href = Api.authed(outAudioUrl);
      a.download = outAudioName;
      a.click();
    });
    el.copyOut.addEventListener('click', function () {
      if (el.outText.value) copyText(el.outText.value);
    });

    // 历史
    document.querySelectorAll('.seg button').forEach(function (b) {
      b.addEventListener('click', function () {
        document.querySelectorAll('.seg button').forEach(function (x) {
          x.setAttribute('aria-selected', String(x === b));
        });
        History.state.tab = b.dataset.tab;
        History.refresh();
      });
    });
    $('histRefresh').addEventListener('click', function () { History.refresh(); });
    $('histClear').addEventListener('click', async function () {
      if (!confirm('清空全部历史记录与音频文件？该操作不可撤销。')) return;
      try {
        await Api.del('/api/history');
        toast('已清空', 'ok');
        History.refresh();
      } catch (e) { toast(e.message, 'err'); }
    });
    el.histMore.addEventListener('click', function () {
      History.state.page += 1;
      History.load(true);
    });

    outWave = new Waveform(el.outWave, { bars: 56, color: '#00B4D8', idleColor: '#CBD5E1' });

    if (!micSupported()) {
      el.asrMic.disabled = true;
      el.asrMic.title = '当前浏览器不支持录音，请上传音频文件';
    }

    updateTtsStats();
    setMode('tts');
    setStatus('等待任务');
    resetOutput();

    try {
      await loadVoices();
    } catch (e) { /* 未登录时静默，登录后会重新加载 */ }

    try {
      var opt = await Api.get('/api/asr/options');
      maxMb = opt.max_upload_mb || 7;
      $('asrMaxMb').textContent = maxMb;
    } catch (e) { /* 同上 */ }
  }

  window.Workbench = {
    boot: boot,
    onLogin: function () {
      loadVoices().catch(function () {});
      History.refresh();
    },
    resetOutput: resetOutput,
    setStatus: setStatus
  };
})();
