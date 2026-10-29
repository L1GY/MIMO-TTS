/* 自定义音频播放器：播放/暂停、进度条拖拽、时间、加载与结束状态。
   同一时刻只允许一个在播放，切换时自动停止其它播放器。 */
(function () {
  'use strict';

  var active = null;   // 当前正在播放的 Audio

  var ICON_PLAY = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">' +
    '<path d="M3.5 2.2 9.4 6l-5.9 3.8V2.2Z" fill="currentColor"/></svg>';
  var ICON_PAUSE = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">' +
    '<rect x="3" y="2.2" width="2.2" height="7.6" rx="1" fill="currentColor"/>' +
    '<rect x="6.8" y="2.2" width="2.2" height="7.6" rx="1" fill="currentColor"/></svg>';

  function fmtTime(s) {
    if (!isFinite(s) || s < 0) s = 0;
    var m = Math.floor(s / 60);
    var r = Math.floor(s % 60);
    return m + ':' + (r < 10 ? '0' : '') + r;
  }

  /**
   * 创建播放器元素。
   * @param {object} o  {src, onPlay, onEnd, autoplay}
   * @returns {HTMLElement}
   */
  function create(o) {
    o = o || {};
    var wrap = document.createElement('div');
    wrap.className = 'player';

    var btn = document.createElement('button');
    btn.className = 'vp-btn';
    btn.type = 'button';
    btn.setAttribute('aria-label', '播放');
    btn.innerHTML = ICON_PLAY;

    var track = document.createElement('div');
    track.className = 'vp-track';
    track.setAttribute('role', 'slider');
    track.setAttribute('aria-label', '播放进度');
    track.innerHTML = '<div class="vp-fill"></div><div class="vp-knob"></div>';

    var time = document.createElement('span');
    time.className = 'vp-time';
    time.textContent = '0:00 / 0:00';

    var pulse = document.createElement('span');
    pulse.className = 'vp-pulse';

    wrap.appendChild(btn);
    wrap.appendChild(track);
    wrap.appendChild(time);
    wrap.appendChild(pulse);

    var fill = track.querySelector('.vp-fill');
    var knob = track.querySelector('.vp-knob');

    var audio = null;
    var seeking = false;

    function ensureAudio() {
      if (audio) return audio;
      audio = new Audio(o.src);
      audio.preload = 'metadata';

      audio.addEventListener('loadedmetadata', function () {
        time.textContent = fmtTime(audio.currentTime) + ' / ' + fmtTime(audio.duration);
      });
      audio.addEventListener('timeupdate', function () {
        if (seeking) return;
        var p = audio.duration ? audio.currentTime / audio.duration : 0;
        fill.style.width = (p * 100) + '%';
        knob.style.left = (p * 100) + '%';
        time.textContent = fmtTime(audio.currentTime) + ' / ' + fmtTime(audio.duration);
      });
      audio.addEventListener('canplay', function () {
        wrap.classList.remove('is-loading');
        btn.disabled = false;
      });
      audio.addEventListener('waiting', function () {
        wrap.classList.add('is-loading');
      });
      audio.addEventListener('ended', function () {
        wrap.classList.remove('is-playing', 'is-loading');
        btn.innerHTML = ICON_PLAY;
        btn.setAttribute('aria-label', '播放');
        fill.style.width = '0%';
        knob.style.left = '0%';
        if (active === audio) active = null;
        if (o.onEnd) o.onEnd();
      });
      audio.addEventListener('error', function () {
        wrap.classList.remove('is-playing', 'is-loading');
        btn.innerHTML = ICON_PLAY;
        btn.disabled = false;
        time.textContent = '无法播放';
      });
      return audio;
    }

    function pauseOthers() {
      if (active && active !== audio && !active.paused) active.pause();
    }

    btn.addEventListener('click', function () {
      var a = ensureAudio();
      wrap.classList.add('is-loading');
      if (a.paused) {
        pauseOthers();
        active = a;
        var p = a.play();
        if (p && p.catch) {
          p.catch(function () {
            wrap.classList.remove('is-loading', 'is-playing');
            time.textContent = '无法播放';
          });
        }
      } else {
        a.pause();
        wrap.classList.remove('is-loading');
      }
    });

    function playState() {
      if (!audio) return;
      if (audio.paused) {
        wrap.classList.remove('is-playing');
        btn.innerHTML = ICON_PLAY;
        btn.setAttribute('aria-label', '播放');
      } else {
        wrap.classList.remove('is-loading');
        wrap.classList.add('is-playing');
        btn.innerHTML = ICON_PAUSE;
        btn.setAttribute('aria-label', '暂停');
        if (o.onPlay) o.onPlay();
      }
    }
    function bind() {
      if (!audio) return;
      audio.addEventListener('play', playState);
      audio.addEventListener('pause', playState);
    }

    function seekTo(clientX) {
      var a = ensureAudio();
      if (!a.duration) return;
      var r = track.getBoundingClientRect();
      var p = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
      a.currentTime = p * a.duration;
      fill.style.width = (p * 100) + '%';
      knob.style.left = (p * 100) + '%';
      time.textContent = fmtTime(a.currentTime) + ' / ' + fmtTime(a.duration);
    }

    track.addEventListener('pointerdown', function (e) {
      seeking = true;
      bind();
      track.setPointerCapture && track.setPointerCapture(e.pointerId);
      seekTo(e.clientX);
    });
    track.addEventListener('pointermove', function (e) {
      if (seeking) seekTo(e.clientX);
    });
    track.addEventListener('pointerup', function () { seeking = false; });
    track.addEventListener('pointercancel', function () { seeking = false; });

    // 对外暴露的极小接口
    wrap._stop = function () {
      if (audio && !audio.paused) audio.pause();
    };
    wrap._play = function () {
      bind();
      var a = ensureAudio();
      pauseOthers();
      active = a;
      var p = a.play();
      if (p && p.catch) p.catch(function () {});
      playState();
    };
    wrap._setLoading = function (on) {
      wrap.classList.toggle('is-loading', !!on);
      btn.disabled = !!on;
    };

    if (o.autoplay) wrap._play();
    return wrap;
  }

  window.VoicePlayer = {
    create: create,
    stopAll: function () {
      if (active && !active.paused) active.pause();
    }
  };
})();
