// Portal-specific service worker
const CACHE_NAME = 'wf-rep-portal-cache-v1';
const URLS_TO_CACHE = [
  '/rep/',
  '/rep/quote/',
  '/rep/order/',
  '/static/rep_portal/css/portal.css',
  '/static/rep_portal/js/script.js',
  '/static/rep_portal/img/icon-192x192.png',
  '/static/rep_portal/img/icon-512x512.png'
];

self.addEventListener('install', event => {
  console.log('Rep Portal Service Worker installing.');
  self.skipWaiting(); // Force activation
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Opened rep portal cache');
        return cache.addAll(URLS_TO_CACHE);
      })
  );
});

self.addEventListener('activate', event => {
  console.log('Rep Portal Service Worker activating.');
  // Claim clients immediately
  event.waitUntil(clients.claim());
  
  // Clean up old caches
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.filter(cacheName => {
          return cacheName.startsWith('wf-rep-portal-') && cacheName !== CACHE_NAME;
        }).map(cacheName => {
          return caches.delete(cacheName);
        })
      );
    })
  );
});

self.addEventListener('fetch', event => {
  // Only handle GET requests
  if (event.request.method !== 'GET') return;
  
  // Handle navigation requests differently
  const isNavigationRequest = event.request.mode === 'navigate';
  
  // Check if request is for portal - VERY IMPORTANT for separate PWA
  const isPortalRequest = event.request.url.includes('/rep/');
  
  // Only intercept rep portal requests
  if (!isPortalRequest && !event.request.url.includes('/static/rep_portal/')) {
    return;
  }
  
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        if (response) {
          return response;
        }
        
        return fetch(event.request).then(
          fetchResponse => {
            if (!fetchResponse || fetchResponse.status !== 200) {
              return fetchResponse;
            }
            
            // Clone the response
            let responseToCache = fetchResponse.clone();
            
            caches.open(CACHE_NAME)
              .then(cache => {
                cache.put(event.request, responseToCache);
              });
              
            return fetchResponse;
          }
        ).catch(() => {
          // Return the offline page for navigation requests
          if (isNavigationRequest) {
            return caches.match('/rep/offline/');
          }
        });
      })
  );
});