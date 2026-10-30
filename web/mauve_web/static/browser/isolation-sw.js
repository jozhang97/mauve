// Served at the Pages root so it controls /repo/ and all nested workers.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  // Preserve cross-origin API/download behavior. No caching or data storage.
  if (new URL(event.request.url).origin !== self.location.origin) return;
  if (event.request.cache === 'only-if-cached' && event.request.mode !== 'same-origin') return;
  event.respondWith((async () => {
    const response = await fetch(event.request);
    if (response.status === 0) return response;
    const headers = new Headers(response.headers);
    headers.set('Cross-Origin-Opener-Policy', 'same-origin');
    headers.set('Cross-Origin-Embedder-Policy', 'credentialless');
    return new Response(response.body, {status: response.status, statusText: response.statusText, headers});
  })());
});
