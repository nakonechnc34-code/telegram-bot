const CACHE_NAME = 'wokker-cache-v4'; // Подняли версию, чтобы обновить кэш
const ASSETS = [
    '/',              // Главная (index.html)
    '/admin',         // Админка (admin.html)
    '/timesheet',     // Табель
    '/academy',       // Академия
    '/manifest.json',
    '/static/icon-192.svg',
    '/static/icon-512.svg'
];

self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS);
        })
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cache) => {
                    if (cache !== CACHE_NAME) {
                        return caches.delete(cache);
                    }
                })
            );
        })
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Игнорируем API и скачивание файлов, чтобы не ломать авторизацию
    if (url.pathname.startsWith('/uploads/') || url.pathname.startsWith('/api/')) {
        return; 
    }

    event.respondWith(
        caches.match(event.request).then((response) => {
            return response || fetch(event.request);
        })
    );
});
