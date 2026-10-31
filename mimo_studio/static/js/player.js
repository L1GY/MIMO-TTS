/* 自定义音频播放器：播放/暂停、进度拖动、音量、时间显示。
   同一时刻只允许一个音频在播放。 */
(function () {
  'use strict';

  var current = null;   // 当前正在播放的 audio

  function fmt(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    var m = Math.floor(sec / 60);
    var s = Math.floor(sec % 60);
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function build(host) {
    if (!host || host.dataset.ready === '1') return;
    var src = host.dataset.audio;
    if (!src) return;
    host.dataset.ready = '1';

    var title = host.dataset.title || '';
    host.innerHTML =
      '<div class="tp" title="' + title.replace(/"/g, '') + '">' +
        '<button type="button" class="tp-btn" aria-label="播放">' +
          '<i class="fa-solid fa-play text-[11px]"></i>' +
        '</button>' +
        '<div class="tp-track" role="slider" aria-label="播放进度" tabindex="0">' +
          '<div class="tp-fill"></div><div class="tp-knob"></div>' +
        '</div>' +
        '<span class="tp-time">0:00 / 0:00</span>' +
        '<button type="button" class="tp-vol-btn" aria-label="静音">' +
          '<i class="fa-solid fa-volume-high text-[11px]"></i>' +
        '</button>' +
        '<input type="range" class="tp-volume" min="0" max="1" step="0.01" value="1" aria-label="音量">' +
      '</div>';

    var wrap = host.querySelector('.tp');
    var btn = host.querySelector('.tp-btn');
    var icon = btn.querySelector('i');
    var track = host.querySelector('.tp-track');
    var fill = host.querySelector('.tp-fill');
    var knob = host.querySelector('.tp-knob');
    var time = host.querySelector('.tp-time');
    var volBtn = host.querySelector('.tp-vol-btn');
    var volIcon = volBtn.querySelector('i');
    var vol = host.querySelector('.tp-volume');

    var audio = null;
    var seeking = false;
    var lastVolume = 1;
    // 服务端已经算好的时长：拼接后的 mp3 没有 Xing 头，浏览器可能拿不到 duration
    var knownDuration = parseFloat(host.dataset.duration || '0') || 0;

    function totalDuration() {
      // 优先用服务端解析出来的真实时长：浏览器对无 Xing 头的 VBR mp3 只能估算，
      // 会出现显示比实际短、进度条对不上的问题
      if (knownDuration > 0) return knownDuration;
      if (audio && isFinite(audio.duration) && audio.duration > 0) return audio.duration;
      return 0;
    }

    function ensure() {
      if (audio) return audio;
      audio = new Audio(src);
      audio.preload = 'auto';
      audio.volume = parseFloat(vol.value);

      function refreshTime() {
        var d = totalDuration();
        time.textContent = fmt(audio.currentTime) + ' / ' + fmt(d);
      }
      audio.addEventListener('loadedmetadata', refreshTime);
      audio.addEventListener('durationchange', refreshTime);
      audio.addEventListener('loadeddata', refreshTime);
      audio.addEventListener('timeupdate', function () {
        if (seeking) return;
        var d = totalDuration();
        var ratio = d ? audio.currentTime / d : 0;
        fill.style.width = (ratio * 100) + '%';
        knob.style.left = (ratio * 100) + '%';
        time.textContent = fmt(audio.currentTime) + ' / ' + fmt(d);
      });
      audio.addEventListener('play', function () {
        wrap.classList.add('is-playing');
        icon.className = 'fa-solid fa-pause text-[11px]';
        btn.classList.remove('is-loading');
        if (current && current !== audio) current.pause();
        current = audio;
      });
      audio.addEventListener('pause', function () {
        wrap.classList.remove('is-playing');
        icon.className = 'fa-solid fa-play text-[11px]';
      });
      audio.addEventListener('ended', function () {
        wrap.classList.remove('is-playing');
        icon.className = 'fa-solid fa-play text-[11px]';
        fill.style.width = '0%';
        knob.style.left = '0%';
        if (current === audio) current = null;
      });
      audio.addEventListener('waiting', function () { btn.classList.add('is-loading'); });
      audio.addEventListener('canplay', function () { btn.classList.remove('is-loading'); });
      audio.addEventListener('error', function () {
        btn.classList.remove('is-loading');
        time.textContent = '无法播放';
      });
      return audio;
    }

    btn.addEventListener('click', function () {
      var a = ensure();
      if (a.paused) {
        btn.classList.add('is-loading');
        var p = a.play();
        if (p && p.catch) p.catch(function () {
          btn.classList.remove('is-loading');
          time.textContent = '无法播放';
        });
      } else {
        a.pause();
      }
    });

    function seekTo(clientX) {
      var a = ensure();
      var d = totalDuration();
      if (!d) return;
      var rect = track.getBoundingClientRect();
      var ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      a.currentTime = ratio * d;
      fill.style.width = (ratio * 100) + '%';
      knob.style.left = (ratio * 100) + '%';
      time.textContent = fmt(a.currentTime) + ' / ' + fmt(d);
    }

    track.addEventListener('pointerdown', function (e) {
      seeking = true;
      ensure();
      track.setPointerCapture && track.setPointerCapture(e.pointerId);
      seekTo(e.clientX);
    });
    track.addEventListener('pointermove', function (e) { if (seeking) seekTo(e.clientX); });
    track.addEventListener('pointerup', function () { seeking = false; });
    track.addEventListener('pointercancel', function () { seeking = false; });
    track.addEventListener('keydown', function (e) {
      var a = ensure();
      var d = totalDuration();
      if (!d) return;
      if (e.key === 'ArrowRight') { a.currentTime = Math.min(d, a.currentTime + 5); e.preventDefault(); }
      if (e.key === 'ArrowLeft') { a.currentTime = Math.max(0, a.currentTime - 5); e.preventDefault(); }
    });

    vol.addEventListener('input', function () {
      var v = parseFloat(vol.value);
      ensure().volume = v;
      lastVolume = v > 0 ? v : lastVolume;
      volIcon.className = 'fa-solid ' + (v === 0 ? 'fa-volume-xmark' : v < 0.5 ? 'fa-volume-low' : 'fa-volume-high') + ' text-[11px]';
    });

    // 构建时就把元数据读出来；即使浏览器拿不到 duration，也用服务端算好的时长兜底
    var probe = ensure();
    if (knownDuration) time.textContent = '0:00 / ' + fmt(knownDuration);
    probe.load();

    volBtn.addEventListener('click', function () {
      var a = ensure();
      if (a.volume > 0) {
        lastVolume = a.volume;
        a.volume = 0;
        vol.value = 0;
        volIcon.className = 'fa-solid fa-volume-xmark text-[11px]';
      } else {
        a.volume = lastVolume || 1;
        vol.value = a.volume;
        volIcon.className = 'fa-solid fa-volume-high text-[11px]';
      }
    });
  }

  function mountAll(root) {
    (root || document).querySelectorAll('.player-mount').forEach(build);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { mountAll(); });
  } else {
    mountAll();
  }

  window.Player = { mountAll: mountAll };
})();
