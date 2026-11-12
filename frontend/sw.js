// Минимальный service worker (без офлайн-кэша).
// Нужен, чтобы браузер считал сайт устанавливаемым PWA.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {
  // passthrough — браузер сам обрабатывает запрос
});