/* 波形可视化：空闲时静态显示，播放/合成中通过 Web Audio 分析真实音频并跳动。 */
(function () {
  'use strict';

  var reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function Waveform(canvas, opts) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.opts = opts || {};
    this.color = this.opts.color || '#E8541B';
    this.idleColor = this.opts.idleColor || '#CFC8B8';
    this.bars = this.opts.bars || 56;
    this.levels = new Array(this.bars).fill(0.08);
    this.targets = new Array(this.bars).fill(0.08);
    this.raf = null;
    this.analyser = null;
    this.audioEl = null;
    this._resize = this._resize.bind(this);
    window.addEventListener('resize', this._resize);
    this._resize();
    this.idle();
  }

  Waveform.prototype._resize = function () {
    var dpr = window.devicePixelRatio || 1;
    var r = this.canvas.getBoundingClientRect();
    var w = Math.max(1, Math.round(r.width * dpr));
    var h = Math.max(1, Math.round(r.height * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.draw();
  };

  Waveform.prototype.draw = function () {
    var c = this.ctx, W = this.canvas.width, H = this.canvas.height;
    var n = this.bars, gap = Math.max(1, W / n * 0.34);
    var bw = (W - gap * (n - 1)) / n;
    var mid = H / 2;

    c.clearRect(0, 0, W, H);
    for (var i = 0; i < n; i++) {
      var v = Math.max(0.05, Math.min(1, this.levels[i]));
      var bh = Math.max(2, v * (H * 0.86));
      c.fillStyle = this.active ? this.color : this.idleColor;
      var x = i * (bw + gap);
      var y = mid - bh / 2;
      var r = Math.min(bw / 2, 3);
      // 圆角竖条
      c.beginPath();
      if (c.roundRect) { c.roundRect(x, y, bw, bh, r); }
      else { c.rect(x, y, bw, bh); }
      c.fill();
    }
  };

  /* 空闲态：缓慢起伏的静态波形 */
  Waveform.prototype.idle = function () {
    this.active = false;
    this.stop();
    for (var i = 0; i < this.bars; i++) {
      var t = i / this.bars;
      this.levels[i] = 0.10 + 0.20 * Math.abs(Math.sin(t * Math.PI * 3.2)) *
        (1 - 0.35 * Math.abs(t - 0.5) * 2);
    }
    this.draw();
  };

  /* 无真实音频时的合成动画（例如合成中） */
  Waveform.prototype.animateSynthetic = function () {
    this.active = true;
    this.stop();
    if (reduceMotion) { this.draw(); return; }
    var self = this, t = 0;
    var tick = function () {
      t += 0.045;
      for (var i = 0; i < self.bars; i++) {
        var p = i / self.bars;
        self.levels[i] = 0.14 + 0.55 * Math.abs(Math.sin(t + p * 5.5)) * (0.45 + 0.55 * Math.sin(p * Math.PI));
      }
      self.draw();
      self.raf = requestAnimationFrame(tick);
    };
    tick();
  };

  /* 绑定 audio 元素，用 AnalyserNode 做真实频谱驱动 */
  Waveform.prototype.attachAudio = function (audioEl) {
    this.active = true;
    this.audioEl = audioEl;
    this.stop();
    var self = this;

    var onEnd = function () { self.idle(); };
    var onPlay = function () { self._startAnalyser(); };
    audioEl.addEventListener('play', onPlay);
    audioEl.addEventListener('pause', function () { if (self.raf) self.stop(); });
    audioEl.addEventListener('ended', onEnd);

    if (!audioEl.paused) onPlay();
  };

  Waveform.prototype._startAnalyser = function () {
    var self = this;
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) { this.animateSynthetic(); return; }
    try {
      if (!this.audioCtx) this.audioCtx = new AC();
      if (this.audioCtx.state === 'suspended') this.audioCtx.resume();
      if (!this.analyser) {
        // MediaElementSource 每个元素只能创建一次，缓存起来
        if (!this._source) this._source = this.audioCtx.createMediaElementSource(this.audioEl);
        this.analyser = this.audioCtx.createAnalyser();
        this.analyser.fftSize = 256;
        this.analyser.smoothingTimeConstant = 0.75;
        this._source.connect(this.analyser);
        this.analyser.connect(this.audioCtx.destination);
      }
      var buf = new Uint8Array(this.analyser.frequencyBinCount);
      var tick = function () {
        self.analyser.getByteFrequencyData(buf);
        var step = Math.floor(buf.length * 0.62 / self.bars) || 1;
        for (var i = 0; i < self.bars; i++) {
          var sum = 0, cnt = 0;
          for (var j = 0; j < step; j++) {
            var idx = i * step + j;
            if (idx < buf.length) { sum += buf[idx]; cnt++; }
          }
          var v = cnt ? (sum / cnt) / 255 : 0;
          // 低频权重更高，视觉上更自然
          self.levels[i] = self.levels[i] * 0.45 + v * 0.55;
        }
        self.draw();
        self.raf = requestAnimationFrame(tick);
      };
      tick();
    } catch (e) {
      this.animateSynthetic();
    }
  };

  Waveform.prototype.stop = function () {
    if (this.raf) { cancelAnimationFrame(this.raf); this.raf = null; }
  };

  Waveform.prototype.destroy = function () {
    this.stop();
    window.removeEventListener('resize', this._resize);
  };

  window.Waveform = Waveform;
})();
