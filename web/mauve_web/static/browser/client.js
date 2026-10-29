"use strict";
(() => {
  const worker = new Worker(new URL('./worker.mjs', document.currentScript.src), {type: 'module'});
  const pending = new Map(); let serial = 0, failure;
  window.mauveBrowser = {
    request(path, options) {
      if (failure) return Promise.reject(failure);
      return new Promise((resolve, reject) => { const id = ++serial; pending.set(id, {resolve, reject, path, options}); worker.postMessage({id, path, options}); });
    },
  };
  worker.onmessage = ({data}) => {
    if (data.usage) { window.mauveAnalytics?.trackUsage(data.usage); return; }
    if ('progress' in data) { const status = document.getElementById('local-status'); if (status) status.textContent = data.progress || 'Files stay in this browser'; return; }
    const task = pending.get(data.id); if (!task) return; pending.delete(data.id);
    if (data.error) task.reject(Error(data.error)); else { window.mauveAnalytics?.recordResponse(task.path, task.options); task.resolve(data.result); }
  };
  worker.onerror = event => {
    failure = Error(`Could not start browser processing: ${event.message}. Reload the page to retry.`);
    for (const task of pending.values()) task.reject(failure); pending.clear();
  };
  document.addEventListener('click', async event => {
    const link = event.target.closest('a[href^="/api/"]'); if (!link) return;
    event.preventDefault();
    try {
      const {blob, filename} = await window.mauveBrowser.request(link.getAttribute('href'));
      const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = filename; a.click(); window.mauveAnalytics?.recordDownload(link.getAttribute('href')); setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { document.getElementById('notice').textContent = e.message; document.getElementById('notice').hidden = false; }
  });
  document.addEventListener('DOMContentLoaded', async () => {
    try {
      const caps = await window.mauveBrowser.request('/api/capabilities');
      document.getElementById('compute-status').textContent = caps.mode;
      document.getElementById('compute-status').title = caps.adapter || 'Local processing';
    } catch (e) { document.getElementById('compute-status').textContent = e.message; }
  });
})();
