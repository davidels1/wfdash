const CACHE_NAME = 'wf-sales-cache-v2';
const OFFLINE_URL = '/offline/';

const CACHED_URLS = [
    '/',
    '/offline/',
    '/manifest.json',
    '/static/images/pwa/icon-192x192.png',
    '/static/images/pwa/icon-512x512.png',
    '/static/images/pwa/apple-touch-icon.png',
    '/static/images/pwa/favicon-16x16.png',
    '/static/images/pwa/favicon-32x32.png',
    '/static/assets/css/style.css',
    '/static/assets/js/plugins/bootstrap.min.js',
    '/static/assets/css/plugins/bootstrap.min.css',
    'https://code.jquery.com/jquery-3.7.1.min.js'
];

self.addEventListener('install', (event) => {
    console.log('[ServiceWorker] Installing...');
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('[ServiceWorker] Caching app shell');
                return cache.addAll(CACHED_URLS);
            })
            .then(() => {
                console.log('[ServiceWorker] Install completed');
                return self.skipWaiting();
            })
    );
});

self.addEventListener('activate', (event) => {
    console.log('[ServiceWorker] Activating...');
    event.waitUntil(
        Promise.all([
            self.clients.claim(),
            caches.keys().then(cacheNames => {
                return Promise.all(
                    cacheNames
                        .filter(cacheName => cacheName !== CACHE_NAME)
                        .map(cacheName => {
                            console.log('[ServiceWorker] Removing old cache:', cacheName);
                            return caches.delete(cacheName);
                        })
                );
            })
        ])
    );
});

self.addEventListener('fetch', (event) => {
    console.log('[ServiceWorker] Fetch:', event.request.url);
    event.respondWith(
        caches.match(event.request)
            .then(response => {
                if (response) {
                    console.log('[ServiceWorker] Returning cached:', event.request.url);
                    return response;
                }
                console.log('[ServiceWorker] Fetching:', event.request.url);
                return fetch(event.request)
                    .then(response => {
                        // Cache successful responses
                        if (response && response.status === 200) {
                            const responseToCache = response.clone();
                            caches.open(CACHE_NAME)
                                .then(cache => {
                                    cache.put(event.request, responseToCache);
                                });
                        }
                        return response;
                    })
                    .catch(() => {
                        console.log('[ServiceWorker] Fetch failed, returning offline page');
                        return caches.match(OFFLINE_URL);
                    });
            })
    );
});

self.addEventListener('push', (event) => {
    console.log('Push message received:', event.data?.text());
    const options = {
        body: event.data?.text() || 'New notification',
        icon: '/static/images/pwa/icon-192x192.png',
        badge: '/static/images/pwa/icon-192x192.png',
        vibrate: [100, 50, 100]
    };
    
    event.waitUntil(
        self.registration.showNotification('WF Sales', options)
    );
});