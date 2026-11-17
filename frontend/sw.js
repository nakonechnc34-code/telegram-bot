const CACHE_NAME = 'wokker-cache-v3'; // Обновили версию!
const ASSETS = [
    '/',
    '/index.html',
    '/admin.html',
    '/timesheet.html',
    '/academy.html',
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

    // ГЛАВНОЕ ИСПРАВЛЕНИЕ: Игнорируем запросы к API и файлам (PDF)
    // Пусть браузер делает эти запросы напрямую к серверу
    if (url.pathname.startsWith('/uploads/') || url.pathname.startsWith('/api/')) {
        return; 
    }

    // Для остальных запросов (страницы, картинки) работает кэш
    event.respondWith(
        caches.match(event.request).then((response) => {
            return response || fetch(event.request);
        })
    );
});
