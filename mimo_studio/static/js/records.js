/* 合成记录页：对仍在排队/生成中的任务做进度轮询，完成后自动刷新列表 */
(function () {
  'use strict';

  var bars = document.querySelectorAll('.js-live-progress');
  if (!bars.length) return;

  var ids = [];
  bars.forEach(function (b) {
    if (b.dataset.task && ids.indexOf(b.dataset.task) === -1) ids.push(b.dataset.task);
  });
  if (!ids.length) return;

  var finished = false;

  function check(id) {
    return fetch('/api/tasks/' + id)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var el = document.querySelector('.js-live-progress[data-task="' + id + '"]');
        if (el) el.style.width = (data.progress || 0) + '%';

        if ((data.status === 'success' || data.status === 'failed') && !finished) {
          finished = true;
          window.toast(data.status === 'success' ? '有新任务完成，正在刷新…' : '有任务失败，正在刷新…',
            data.status === 'success' ? 'success' : 'error', 1800);
          setTimeout(function () { location.reload(); }, 900);
        }
      })
      .catch(function () { /* 忽略单次失败 */ });
  }

  ids.forEach(check);
  var timer = setInterval(function () {
    if (finished) { clearInterval(timer); return; }
    ids.forEach(check);
  }, 3000);
})();
