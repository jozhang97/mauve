// GitHub Pages cannot configure response headers. A root-scoped service worker
// supplies them locally; hosts that already isolate the page skip registration.
document.documentElement.inert = true;
window.mauveIsolationReady = (async () => {
  if (self.crossOriginIsolated || !('serviceWorker' in navigator) || !self.isSecureContext) return;
  const key = 'mauve-isolation-reload';
  try {
    await navigator.serviceWorker.register(new URL('../../isolation-sw.js', document.currentScript.src));
    await Promise.race([
      navigator.serviceWorker.ready,
      new Promise(resolve => setTimeout(resolve, 3000)),
    ]);
    if (!navigator.serviceWorker.controller) {
      await Promise.race([
        new Promise(resolve => navigator.serviceWorker.addEventListener('controllerchange', resolve, {once: true})),
        new Promise(resolve => setTimeout(resolve, 3000)),
      ]);
    }
    if (navigator.serviceWorker.controller && !sessionStorage.getItem(key)) {
      sessionStorage.setItem(key, '1');
      location.reload();
      // Don't initialize a workspace just before this one-time reload.
      await new Promise(() => {});
    }
  } catch (_) { /* The ordinary single-thread engine remains available. */ }
})().finally(() => { document.documentElement.inert = false; });
