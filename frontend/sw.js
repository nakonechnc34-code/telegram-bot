const CACHE_NAME = 'wokker-cache-v1';
const ASSETS_TO_CACHE = [
  '/',
  '/admin',
  '/academy',
  '/timesheet',
  '/manifest.json',
  '/static/icon-192.svg',
  '/static/icon-512.svg'
];

// 1. Установка: кэшируем основные файлы
self.addEventListener('install', (event) => {
  self.skipWaiting(); // Принудительно активируем новый SW
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
});

// 2. Активация: удаляем старый кэш, если версия изменилась
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 3. Перехват запросов (Стратегия: Network First для API/HTML, Cache First для картинок)
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // POST запросы и HTML страницы всегда идем в сеть (чтобы получать свежие данные)
  if (event.request.method === 'POST' || event.request.headers.get('accept').includes('text/html')) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          // Кэшируем только успешные GET запросы
          if (event.request.method === 'GET' && response.status === 200) {
             const responseClone = response.clone();
             caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
          }
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Для статики (картинки, css, js) - Cache First (сначала смотрим в кэш)
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) return cachedResponse;
      
      return fetch(event.request).then((response) => {
        if (!response || response.status !== 200 || response.type !== 'basic') {
          return response;
        }
        const responseToCache = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseToCache));
        return response;
      });
    })
  );
});

// 4. Обработка Push-уведомлений
self.addEventListener('push', function(event) {
  let data = { title: 'Wokker', body: 'У вас новое уведомление!' };
  
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data = { title: 'Wokker', body: event.data.text() };
    }
  }

  const options = {
    body: data.body,
    icon: '/static/icon-192.svg',
    badge: '/static/icon-192.svg',
    vibrate: [100, 50, 100],
    data: {
      url: data.url || '/'
    }
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// 5. Клик по уведомлению (открывает приложение)
self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const urlToOpen = event.notification.data.url || '/';
  
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
      // Если приложение уже открыто, фокусируемся на нем
      for (let i = 0; i < clientList.length; i++) {
        const client = clientList[i];
        if (client.url === urlToOpen && 'focus' in client) {
          return client.focus();
        }
      }
      // Иначе открываем новое окно
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen);
      }
    })
  );
});
