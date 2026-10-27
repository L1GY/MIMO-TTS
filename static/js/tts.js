/* 文本转语音视图 */
(function () {
  'use strict';

  var el = {};
  var wave = null;
  var maxLen = 2000;
  var currentAudio = null;

  function $(id) { return document.getElementById(id); }

  function showAlert(msg, kind) {
    el.alert.innerHTML = '<div class="alert alert-' + (kind || 'error') + '">' + fmt.esc(msg) + '</div>';
  }
  function clearAlert() { el.alert.innerHTML = ''; }

  function syncCount() {
    var n = el.text.value.length;
    el.count.textContent = n + ' / ' + maxLen;
    el.count.classList.toggle('over', n > maxLen);
  }

  /** 音色下拉：预置音色 + 我的音色（分组），值形如 preset:<id> 或 mine:<id> */
  async function loadVoices() {
    var opt = await Api.get('/api/tts/options');
    var mine = await Api.get('/api/voices?page_size=100');

    var groups = '';
    if (mine.items && mine.items.length) {
      groups += '<optgroup label="我的音色">' + mine.items.map(function (v) {
        return '<option value="mine:' + fmt.esc(v.id) + '">' + fmt.esc(v.name) + '</option>';
      }).join('') + '</optgroup>';
    }
    groups += '<optgroup label="预置音色">' + opt.voices.map(function (v) {
      return '<option value="preset:' + fmt.esc(v.id) + '">' + fmt.esc(v.name + ' · ' + v.desc) + '</option>';
    }).join('') + '</optgroup>';

    var keep = el.voice.value;
    el.voice.innerHTML = groups;
    if (keep && el.voice.querySelector('option[value="' + keep + '"]')) el.voice.value = keep;

    return { opt: opt, mine: mine.items || [] };
  }

  async function submit() {
    clearAlert();
    var text = el.text.value.trim();
    if (!text) { showAlert('请先写下要合成的文本'); el.text.focus(); return; }
    if (text.length > maxLen) { showAlert('文本超过 ' + maxLen + ' 字，请精简后再试'); return; }

    var sel = el.voice.value || '';
    var payload = { text: text, audio_format: el.format.value };
    var voiceName = '';

    if (sel.indexOf('mine:') === 0) {
      payload.voice_preset_id = sel.slice(5);
      voiceName = el.voice.options[el.voice.selectedIndex].text;
    } else {
      payload.voice = sel.slice(7) || (el.voice.options[el.voice.selectedIndex] || {}).value;
    }

    el.submit.disabled = true;
    el.submit.innerHTML = '<span class="spinner"></span>合成中';
    if (wave) wave.animateSynthetic();

    try {
      var rec = await Api.post('/api/tts/synthesize', payload);
      var audio = window.renderPlayer(el.player, {
        url: rec.audio_url,
        filename: 'voice_' + rec.id + '.' + (rec.mime === 'audio/mpeg' ? 'mp3' : 'wav'),
        size: rec.size,
        latency: rec.latency_ms,
        voiceName: rec.voice_name || voiceName,
        isMock: rec.is_mock,
        text: rec.text_final
      });
      currentAudio = audio;
      if (wave) wave.attachAudio(audio);
      toast('生成完成' + (rec.is_mock ? '（模拟模式）' : ''), 'ok');
      TTS.refreshRecent();
      if (window.Records) Records.refreshStats();
    } catch (err) {
      if (wave) wave.idle();
      showAlert(err.message);
      toast(err.message, 'err');
      TTS.refreshRecent();
    } finally {
      el.submit.disabled = false;
      el.submit.textContent = '生成语音';
    }
  }

  function recLine(r) {
    var d = document.createElement('div');
    d.className = 'rec';
    d.style.padding = '10px 12px';
    d.innerHTML =
      '<div style="font-size:13px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">' +
        fmt.esc(r.text_input) + '</div>' +
      '<div class="meta-row" style="margin-top:6px">' +
        '<span>' + fmt.dateTime(r.created_at) + '</span>' +
        (r.voice_name ? '<span class="badge badge-brand">' + fmt.esc(r.voice_name) + '</span>' : '') +
      '</div>' +
      '<audio class="audio-mini" controls preload="none" src="' + Api.authed('/api/tts/' + r.id + '/download') + '"></audio>';
    return d;
  }

  var TTS = {
    mount: async function () {
      el = {
        text: $('ttsText'), count: $('ttsCount'), voice: $('ttsVoice'),
        format: $('ttsFormat'), submit: $('ttsSubmit'), alert: $('ttsAlert'),
        player: $('ttsPlayer'), recent: $('ttsRecent')
      };

      if (!wave) wave = new Waveform($('ttsWave'), { bars: 48, color: '#3B2FD6' });

      el.text.addEventListener('input', syncCount);
      el.submit.addEventListener('click', submit);
      $('ttsClear').addEventListener('click', function () {
        el.text.value = ''; syncCount(); clearAlert(); el.text.focus();
      });

      try {
        var r = await loadVoices();
        maxLen = r.opt.max_text_length || 2000;
      } catch (e) { /* 使用页面内置默认值 */ }

      syncCount();
      TTS.refreshRecent();
    },

    /** 供音色设计页在保存新音色后刷新下拉，以及外部指定音色 */
    reloadVoices: function () { return el && el.voice ? loadVoices() : null; },

    selectVoice: function (value) {
      if (el && el.voice && el.voice.querySelector('option[value="' + value + '"]')) el.voice.value = value;
    },

    refreshRecent: async function () {
      if (!el.recent) return;
      try {
        var r = await Api.get('/api/tts/history?page_size=5');
        el.recent.innerHTML = '';
        var ok = r.items.filter(function (i) { return i.status === 'success'; });
        if (!ok.length) {
          el.recent.innerHTML = '<div class="empty" style="padding:18px 8px"><p>暂无记录</p></div>';
          return;
        }
        ok.forEach(function (item) { el.recent.appendChild(recLine(item)); });
      } catch (e) { /* 静默 */ }
    },

    stopAudio: function () {
      if (currentAudio && !currentAudio.paused) currentAudio.pause();
      if (el && el.player) {
        var a = el.player.querySelector('audio');
        if (a && !a.paused) a.pause();
      }
    }
  };

  window.TTS = TTS;
})();
