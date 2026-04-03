/**
 * Service Worker for Stock Monitor PWA
 * Provides offline support and caching for static assets
 * Version: 2.0 - Enhanced caching and offline handling
 */

const CACHE_NAME = 'stock-monitor-v2';
const STATIC_ASSETS = [
  '/',
  '/backtest',
  '/static/css/main.css',
  '/static/js/app.js',
  '/static/js/dashboard.js',
  '/static/js/sectors.js',
  '/static/js/watchlist.js',
  '/static/js/strategies.js',
  '/static/js/alerts.js',
  '/static/manifest.json',
  '/static/icons/icon-72.png',
  '/static/icons/icon-96.png',
  '/static/icons/icon-128.png',
  '/static/icons/icon-144.png',
  '/static/icons/icon-152.png',
  '/static/icons/icon-192.png',
  '/static/icons/icon-384.png',
  '/static/icons/icon-512.png'
];

// Maximum cache age for API responses (5 minutes)
const API_CACHE_MAX_AGE = 5 * 60 * 1000;

// Install event - cache static assets with error tolerance
self.addEventListener('install', (event) => {
  console.log('[SW] Installing service worker v2...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[SW] Caching static assets');
        // Use individual cache.add() for better error tolerance
        return Promise.all(
          STATIC_ASSETS.map((url) =>
            cache.add(url).catch((err) => {
              console.warn('[SW] Failed to cache:', url, err.message);
            })
          )
        );
      })
      .then(() => {
        console.log('[SW] All assets cached (some may have failed)');
        return self.skipWaiting();
      })
      .catch((err) => console.error('[SW] Cache failed:', err))
  );
});

// Activate event - clean old caches
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating service worker...');
  event.waitUntil(
    caches.keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames
            .filter((name) => name !== CACHE_NAME)
            .map((name) => {
              console.log('[SW] Removing old cache:', name);
              return caches.delete(name);
            })
        );
      })
      .then(() => self.clients.claim())
  );
});

// Fetch event - smart caching strategy
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // Skip Socket.IO requests (they need real-time connection)
  if (url.pathname.startsWith('/socket.io/')) {
    return;
  }

  // API requests: stale-while-revalidate (show cached data, update in background)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        // Start network fetch in background
        const networkFetch = fetch(request)
          .then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              const responseToCache = networkResponse.clone();
              caches.open(CACHE_NAME).then((cache) => {
                cache.put(request, responseToCache);
              });
            }
            return networkResponse;
          })
          .catch(() => null);

        // Return cached response immediately if available, otherwise wait for network
        return cachedResponse || networkFetch.then((resp) => {
          if (resp) return resp;
          return new Response(
            JSON.stringify({ error: 'Offline', message: '网络不可用，请检查连接', success: false }),
            { status: 503, headers: { 'Content-Type': 'application/json' } }
          );
        });
      })
    );
    return;
  }

  // Static assets: cache first, fallback to network
  event.respondWith(
    caches.match(request)
      .then((cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }

        return fetch(request)
          .then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              const responseToCache = networkResponse.clone();
              caches.open(CACHE_NAME)
                .then((cache) => {
                  cache.put(request, responseToCache);
                });
            }
            return networkResponse;
          })
          .catch(() => {
            // Return offline page for navigation requests
            if (request.mode === 'navigate') {
              return caches.match('/');
            }
            return new Response('Offline', { status: 503 });
          });
      })
  );
});

// Background sync for API data (when online)
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-stock-data') {
    console.log('[SW] Background sync: stock data');
    event.waitUntil(
      fetch('/api/stock')
        .then((response) => response.json())
        .then((data) => {
          // Notify clients of new data
          self.clients.matchAll().then((clients) => {
            clients.forEach((client) => {
              client.postMessage({ type: 'STOCK_UPDATE', data });
            });
          });
        })
        .catch((err) => console.error('[SW] Sync failed:', err))
    );
  }
});

// Push notifications (for future use)
self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};
  const title = data.title || '股票盯盘';
  const options = {
    body: data.body || '有新的市场动态',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-72.png',
    vibrate: [100, 50, 100],
    data: data
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    clients.openWindow('/')
  );
});
