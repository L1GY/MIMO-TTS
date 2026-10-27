/* 音色设计视图：描述 → 试听 → 保存为我的音色 */
(function () {
  'use strict';

  var el = {};
  var wave = null;
  var maxLen = 2000;
  var lastPresetId = null;   // 当前试听所用/刚保存的音色
  var lastDesc = '';

  function $(id) { return document.getElementById(id); }

  function showAlert(msg, kind) {
    el.alert.innerHTML = '<div class="alert alert-' + (kind || 'error') + '">' + fmt.esc(msg) + '</div>';
  }
  function clearAlert() { el.alert.innerHTML = ''; }

  var INSPIRATIONS = [
    '温柔的成年女声，语速偏慢，适合有声书朗读',
    '沉稳的男声，吐字有力，像纪录片的旁白',
    '活泼的少女音，语速快，尾音微微上扬',
    '冷静知性的女声，节奏平稳，适合新闻播报',
    '低沉磁性的中年男声，语速慢，适合深夜电台'
  ];

  function renderChips() {
    el.chips.innerHTML = INSPIRATIONS.map(function (t) {
      return '<button class="chip" type="button">' + fmt.esc(t) + '</button>';
    }).join('');
    Array.prototype.forEach.call(el.chips.querySelectorAll('.chip'), function (btn) {
      btn.addEventListener('click', function () {
        el.desc.value = btn.textContent;
        el.desc.focus();
      });
    });
  }

  async function preview() {
    clearAlert();
    var desc = el.desc.value.trim();
    var text = el.sample.value.trim();
    if (!desc) { showAlert('先用一句话描述你想要的音色'); el.desc.focus(); return; }
    if (!text) { showAlert('填一段试听文本，才能听到效果'); el.sample.focus(); return; }
    if (text.length > maxLen) { showAlert('试听文本超过 ' + maxLen + ' 字'); return; }

    lastDesc = desc;
    el.previewBtn.disabled = true;
    el.previewBtn.innerHTML = '<span class="spinner"></span>生成中';
    if (wave) wave.animateSynthetic();

    try {
      var rec = await Api.post('/api/tts/synthesize', {
        text: text,
        voice_desc: desc,
        audio_format: el.format.value
      });
      var audio = window.renderPlayer(el.player, {
        url: rec.audio_url,
        filename: 'voice_' + rec.id + '.' + (rec.mime === 'audio/mpeg' ? 'mp3' : 'wav'),
        size: rec.size,
        latency: rec.latency_ms,
        voiceName: rec.voice_name,
        isMock: rec.is_mock,
        text: rec.text_final
      });
      if (wave) wave.attachAudio(audio);
      toast('试听已生成', 'ok');
    } catch (err) {
      if (wave) wave.idle();
      showAlert(err.message);
      toast(err.message, 'err');
    } finally {
      el.previewBtn.disabled = false;
      el.previewBtn.textContent = '生成试听';
    }
  }

  async function save() {
    clearAlert();
    var name = el.name.value.trim();
    var desc = el.desc.value.trim();
    if (!name) { showAlert('给你的音色起个名字'); el.name.focus(); return; }
    if (!desc) { showAlert('音色描述不能为空'); el.desc.focus(); return; }

    el.saveBtn.disabled = true;
    try {
      var v = await Api.post('/api/voices', {
        name: name,
        description: desc,
        sample_text: el.sample.value.trim() || null
      });
      lastPresetId = v.id;
      toast('已保存音色「' + v.name + '」', 'ok');
      await Design.refreshMine();
      if (window.TTS) TTS.reloadVoices();
    } catch (err) {
      showAlert(err.message);
      toast(err.message, 'err');
    } finally {
      el.saveBtn.disabled = false;
    }
  }

  function voiceCard(v) {
    var d = document.createElement('div');
    d.className = 'voice-card';
    d.style.setProperty('--vc', v.color || '#3B2FD6');
    d.innerHTML =
      '<div class="vc-head"><span class="vc-dot"></span><b>' + fmt.esc(v.name) + '</b></div>' +
      '<div class="desc">' + fmt.esc(v.description) + '</div>' +
      '<div class="meta-row" style="margin-top:10px">' +
        '<span>' + fmt.dateTime(v.created_at) + '</span>' +
        '<span>已用 ' + (v.use_count || 0) + ' 次</span>' +
      '</div>' +
      '<div class="row-end" style="margin-top:12px">' +
        '<button class="btn btn-sm btn-outline" data-act="use">用它合成</button>' +
        '<button class="btn btn-sm btn-ghost" data-act="fill">载入描述</button>' +
        '<button class="btn btn-sm btn-ghost btn-danger-ghost" data-act="del">删除</button>' +
      '</div>';

    d.querySelector('[data-act="use"]').addEventListener('click', function () {
      // 切到合成页并选中该音色
      App.go('tts', function () {
        TTS.reloadVoices().then(function () {
          TTS.selectVoice('mine:' + v.id);
          toast('已切换到「' + v.name + '」', 'ok');
        });
      });
    });

    d.querySelector('[data-act="fill"]').addEventListener('click', function () {
      el.desc.value = v.description;
      el.name.value = v.name;
      if (v.sample_text) el.sample.value = v.sample_text;
      lastPresetId = v.id;
      el.desc.focus();
    });

    d.querySelector('[data-act="del"]').addEventListener('click', async function () {
      if (!confirm('删除音色「' + v.name + '」？已生成的记录会保留。')) return;
      try {
        await Api.del('/api/voices/' + v.id);
        toast('已删除', 'ok');
        Design.refreshMine();
        if (window.TTS) TTS.reloadVoices();
      } catch (e) { toast(e.message, 'err'); }
    });

    return d;
  }

  var Design = {
    mount: async function () {
      el = {
        desc: $('vdDesc'), chips: $('vdChips'), name: $('vdName'), format: $('vdFormat'),
        sample: $('vdSample'), alert: $('vdAlert'), player: $('vdPlayer'), mine: $('vdMine'),
        previewBtn: $('vdPreview'), saveBtn: $('vdSave')
      };

      if (!wave) wave = new Waveform($('vdWave'), { bars: 48, color: '#7448E8' });

      renderChips();
      el.previewBtn.addEventListener('click', preview);
      el.saveBtn.addEventListener('click', save);

      if (!el.sample.value) {
        el.sample.value = '夜色落下来的时候，城市才开始说真话。';
      }

      try {
        var opt = await Api.get('/api/tts/options');
        maxLen = opt.max_text_length || 2000;
      } catch (e) { /* 用默认值 */ }

      Design.refreshMine();
    },

    refreshMine: async function () {
      if (!el.mine) return;
      el.mine.innerHTML = '<div class="skeleton" style="height:110px"></div>';
      try {
        var r = await Api.get('/api/voices?page_size=100');
        el.mine.innerHTML = '';
        if (!r.items.length) {
          el.mine.innerHTML =
            '<div class="empty"><div class="glyph"></div>' +
            '<b>还没有保存过音色</b><p>描述一个音色并试听，满意后点「保存为我的音色」。</p></div>';
          return;
        }
        var grid = document.createElement('div');
        grid.className = 'voice-grid';
        r.items.forEach(function (v) { grid.appendChild(voiceCard(v)); });
        el.mine.appendChild(grid);
      } catch (e) {
        el.mine.innerHTML = '<div class="alert alert-error">' + fmt.esc(e.message) + '</div>';
      }
    },

    stopAudio: function () {
      if (el && el.player) {
        var a = el.player.querySelector('audio');
        if (a && !a.paused) a.pause();
      }
    }
  };

  window.Design = Design;
})();
