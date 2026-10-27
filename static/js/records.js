/* 我的记录：生成记录 + 我的音色，支持试听、导出、删除与分页加载 */
(function () {
  'use strict';

  var PAGE_SIZE = 20;
  var state = {
    tab: 'gen',            // gen | voice
    page: 1,
    keyword: '',
    total: 0,
    items: []
  };
  var el = {};

  function $(id) { return document.getElementById(id); }

  /* ------------------------------------------------------------ 统计 */

  async function loadStats() {
    try {
      var s = await Api.get('/api/history/stats');
      var cells = [
        [s.tts_total, '累计合成'],
        [s.asr_total, '累计识别'],
        [s.tts_chars, '合成字数'],
        [fmt.bytes(s.audio_bytes), '音频体积'],
        [s.failed_total, '失败次数']
      ];
      el.stats.innerHTML = cells.map(function (c) {
        return '<div class="card card-tight"><div style="font-size:22px;font-weight:600;letter-spacing:-.02em">' +
          c[0] + '</div><div style="font-size:12px;color:var(--muted)">' + c[1] + '</div></div>';
      }).join('');
    } catch (e) { /* 静默 */ }
  }

  function refreshStats() { loadStats(); }

  /* ------------------------------------------------------------ 生成记录 */

  function genNode(r) {
    var d = document.createElement('div');
    d.className = 'rec';

    var isTts = r.type === 'tts';
    var title = isTts ? (r.text_final || r.text_input) : (r.transcript || '（无识别结果）');
    var voiceName = isTts ? (r.voice_name || (r.voice ? null : null)) : null;

    var params = [];
    if (isTts) {
      if (voiceName) params.push('音色 ' + voiceName);
      params.push(String(r.audio_format || '').toUpperCase());
      if (r.optimize_text) params.push('文本优化');
    } else {
      params.push('语种 ' + ({ auto: '自动', zh: '中文', en: '英文' }[r.language] || r.language));
      if (r.audio_seconds) params.push(fmt.seconds(r.audio_seconds));
    }
    if (r.latency_ms) params.push(r.latency_ms + ' ms');

    d.innerHTML =
      '<div class="rec-head">' +
        '<span class="badge ' + (isTts ? 'badge-brand' : 'badge-cyan') + '">' +
          (isTts ? '文本转语音' : '音频转文字') + '</span>' +
        (r.status === 'failed'
          ? '<span class="badge badge-err">失败</span>'
          : '<span class="badge badge-ok">成功</span>') +
        '<span class="meta-row" style="margin-left:auto">' +
          '<span>' + fmt.dateTime(r.created_at) + '</span>' +
        '</span>' +
      '</div>' +
      '<div class="rec-body">' + fmt.esc(
        r.status === 'failed' ? ('失败原因：' + (r.error_message || '未知')) : title
      ) + '</div>' +
      '<div class="meta-row" style="margin-top:8px">' +
        params.map(function (p) { return '<span>' + fmt.esc(p) + '</span>'; }).join('') +
        (isTts && r.audio_size ? '<span>' + fmt.bytes(r.audio_size) + '</span>' : '') +
        (!isTts && r.filename ? '<span>' + fmt.esc(r.filename) + '</span>' : '') +
      '</div>' +
      '<div class="rec-actions">' +
        (r.status === 'success' && r.has_audio
          ? '<button class="btn btn-sm btn-ghost" data-act="play">试听</button>' +
            '<a class="btn btn-sm btn-ghost" href="' + Api.authed('/api/' + r.type + '/' + r.id + '/download') + '">导出</a>'
          : '') +
        '<button class="btn btn-sm btn-ghost" data-act="toggle">展开</button>' +
        '<button class="btn btn-sm btn-ghost btn-danger-ghost" data-act="del">删除</button>' +
      '</div>';

    d.querySelector('[data-act="toggle"]').addEventListener('click', function () {
      var b = d.querySelector('.rec-body');
      b.classList.toggle('open');
      this.textContent = b.classList.contains('open') ? '收起' : '展开';
    });

    var play = d.querySelector('[data-act="play"]');
    if (play) {
      play.addEventListener('click', function () {
        var existing = d.querySelector('audio');
        if (existing) { existing.paused ? existing.play() : existing.pause(); return; }
        var a = document.createElement('audio');
        a.className = 'audio-mini';
        a.controls = true;
        a.autoplay = true;
        a.src = Api.authed('/api/' + r.type + '/' + r.id + '/download');
        d.appendChild(a);
      });
    }

    d.querySelector('[data-act="del"]').addEventListener('click', async function () {
      if (!confirm('删除这条记录？对应的音频也会一并删除。')) return;
      try {
        await Api.del('/api/history/' + r.type + '/' + r.id);
        toast('已删除', 'ok');
        load(false);
        loadStats();
      } catch (e) { toast(e.message, 'err'); }
    });

    return d;
  }

  /* ------------------------------------------------------------ 我的音色 */

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
        '<button class="btn btn-sm btn-ghost btn-danger-ghost" data-act="del">删除</button>' +
      '</div>';

    d.querySelector('[data-act="use"]').addEventListener('click', function () {
      App.go('tts', function () {
        TTS.reloadVoices().then(function () {
          TTS.selectVoice('mine:' + v.id);
          toast('已切换到「' + v.name + '」', 'ok');
        });
      });
    });

    d.querySelector('[data-act="del"]').addEventListener('click', async function () {
      if (!confirm('删除音色「' + v.name + '」？已生成的音频记录会保留。')) return;
      try {
        await Api.del('/api/voices/' + v.id);
        toast('已删除', 'ok');
        load(false);
        if (window.TTS) TTS.reloadVoices();
      } catch (e) { toast(e.message, 'err'); }
    });

    return d;
  }

  /* ------------------------------------------------------------ 加载 */

  async function load(append) {
    var host = state.tab === 'gen' ? el.listGen : el.listVoice;
    if (!append) {
      host.innerHTML = '<div class="skeleton" style="height:92px;margin-bottom:10px"></div>' +
                       '<div class="skeleton" style="height:92px"></div>';
    }

    try {
      if (state.tab === 'gen') {
        var q = '/api/history?page=' + state.page + '&page_size=' + PAGE_SIZE +
          '&keyword=' + encodeURIComponent(state.keyword);
        var r = await Api.get(q);
        state.total = r.total;

        if (!append) host.innerHTML = '';
        if (!r.items.length && !append) {
          host.innerHTML = state.keyword
            ? '<div class="empty"><div class="glyph"></div><b>没有匹配的记录</b><p>换个关键词试试。</p></div>'
            : '<div class="empty"><div class="glyph"></div><b>还没有任何生成记录</b>' +
              '<p>去「文本转语音」生成第一段音频，它会出现在这里。</p></div>';
        } else {
          r.items.forEach(function (i) { host.appendChild(genNode(i)); });
        }
      } else {
        var v = await Api.get('/api/voices?page=' + state.page + '&page_size=' + PAGE_SIZE);
        state.total = v.total;

        if (!append) host.innerHTML = '';
        if (!v.items.length && !append) {
          host.innerHTML =
            '<div class="empty"><div class="glyph"></div><b>还没有设计过音色</b>' +
            '<p>到「音色设计」描述一个声音，试听满意后保存，就能在这里看到。</p></div>';
        } else {
          var grid = host.querySelector('.voice-grid');
          if (!grid) {
            grid = document.createElement('div');
            grid.className = 'voice-grid';
            host.appendChild(grid);
          }
          v.items.forEach(function (i) { grid.appendChild(voiceCard(i)); });
        }
      }

      var shown = (state.tab === 'gen' ? el.listGen : el.listVoice).children.length;
      el.count.textContent = '共 ' + state.total + ' 条';
      el.more.hidden = shown >= state.total;
      el.more.textContent = '加载更多';
      el.more.disabled = false;
    } catch (e) {
      host.innerHTML = '<div class="alert alert-error">' + fmt.esc(e.message) + '</div>';
      el.more.hidden = true;
    }
  }

  function switchTab(tab) {
    state.tab = tab;
    state.page = 1;
    Array.prototype.forEach.call(el.tabs.querySelectorAll('button'), function (b) {
      b.setAttribute('aria-selected', String(b.dataset.tab === tab));
    });
    el.listGen.hidden = (tab !== 'gen');
    el.listVoice.hidden = (tab !== 'voice');
    el.clearBtn.hidden = (tab !== 'gen');
    load(false);
  }

  var Records = {
    mount: function () {
      el = {
        stats: $('statGrid'), tabs: document.querySelector('.seg'),
        listGen: $('recListGen'), listVoice: $('recListVoice'),
        more: $('recMore'), count: $('recCount'), keyword: $('recKeyword'),
        clearBtn: $('recClear')
      };

      Array.prototype.forEach.call(el.tabs.querySelectorAll('button'), function (b) {
        b.addEventListener('click', function () { switchTab(b.dataset.tab); });
      });

      el.more.addEventListener('click', function () {
        state.page += 1;
        el.more.disabled = true;
        el.more.textContent = '加载中…';
        load(true);
      });

      $('recSearch').addEventListener('click', function () {
        state.keyword = el.keyword.value.trim(); state.page = 1; load(false);
      });
      el.keyword.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { state.keyword = el.keyword.value.trim(); state.page = 1; load(false); }
      });
      $('recRefresh').addEventListener('click', function () { load(false); loadStats(); });

      el.clearBtn.addEventListener('click', async function () {
        if (!confirm('清空全部生成记录与音频文件？该操作不可撤销。')) return;
        try {
          await Api.del('/api/history');
          toast('已清空', 'ok');
          load(false); loadStats();
          if (window.TTS) TTS.refreshRecent();
          if (window.ASR) ASR.refreshRecent();
        } catch (e) { toast(e.message, 'err'); }
      });

      loadStats();
      switchTab('gen');
    },

    refreshStats: refreshStats,
    reload: function () { load(false); loadStats(); }
  };

  window.Records = Records;
})();
