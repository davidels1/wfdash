const CACHE_NAME = 'wf-portal-cache-v1';
const OFFLINE_URL = '/portal/offline/';

const CACHED_URLS = [
    '/portal/',
    '/portal/offline/',
    '/static/portal-manifest.json',
    '/static/images/pwa/icon-192x192.png',
    '/static/images/pwa/icon-512x512.png',
    '/static/images/pwa/apple-touch-icon.png',
    '/static/images/pwa/favicon-16x16.png',
    '/static/images/pwa/favicon-32x32.png',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js',
    'https://kit.fontawesome.com/a076d05399.js'
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
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.filter(cacheName => {
                    return cacheName.startsWith('wf-portal-') && cacheName !== CACHE_NAME;
                }).map(cacheName => {
                    console.log('[ServiceWorker] Deleting old cache:', cacheName);
                    return caches.delete(cacheName);
                })
            );
        })
        .then(() => {
            console.log('[ServiceWorker] Claiming clients');
            return self.clients.claim();
        })
    );
});

self.addEventListener('fetch', (event) => {
    console.log('[ServiceWorker] Fetch', event.request.url);
    
    // Skip cross-origin requests
    if (!event.request.url.startsWith(self.location.origin)) {
        return;
    }
    
    // Network first strategy for form submissions
    if (event.request.method === 'POST') {
        return;
    }
    
    // Handle navigation requests - fallback to offline page
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request)
                .catch(() => {
                    return caches.match(OFFLINE_URL);
                })
        );
        return;
    }
    
    // Cache first, falling back to network for everything else
    event.respondWith(
        caches.match(event.request)
            .then(response => {
                if (response) {
                    return response;
                }
                
                return fetch(event.request)
                    .then(response => {
                        // Don't cache responses with error status codes
                        if (!response || response.status !== 200 || response.type !== 'basic') {
                            return response;
                        }
                        
                        // Clone the response as it can only be consumed once
                        const responseToCache = response.clone();
                        
                        // Store in cache
                        caches.open(CACHE_NAME)
                            .then(cache => {
                                cache.put(event.request, responseToCache);
                            });
                            
                        return response;
                    })
                    .catch(error => {
                        console.error('[ServiceWorker] Fetch failed:', error);
                        // For image requests that fail, you could return a placeholder
                        if (event.request.destination === 'image') {
                            return caches.match('/static/images/pwa/offline-image.png');
                        }
                        return new Response('Network error', { status: 408 });
                    });
            })
    );
});

// Add this after your existing fetch event handler

// Handle background sync for offline form submissions
self.addEventListener('sync', event => {
  if (event.tag === 'submit-form') {
    console.log('[ServiceWorker] Background sync: submit-form');
    event.waitUntil(submitPendingForms());
  }
});

// Helper function to submit pending forms from IndexedDB
async function submitPendingForms() {
  try {
    // Open the IndexedDB database
    const db = await self.indexedDB.open('wf-portal-db', 1);
    const transaction = db.transaction('pending-forms', 'readwrite');
    const store = transaction.objectStore('pending-forms');
    
    // Get all pending forms
    const pendingForms = await store.getAll();
    console.log('[ServiceWorker] Found', pendingForms.length, 'pending forms');
    
    // Submit each form
    for (const form of pendingForms) {
      try {
        const formData = new FormData();
        
        // Convert object back to FormData
        for (const [key, value] of Object.entries(form)) {
          if (key !== 'id' && key !== 'formType' && key !== 'timestamp') {
            formData.append(key, value);
          }
        }
        
        // Submit to the appropriate endpoint
        const url = form.formType === 'quote' 
          ? '/portal/quote-request/' 
          : '/portal/order-request/';
          
        console.log('[ServiceWorker] Submitting pending form to', url);
        
        const response = await fetch(url, {
          method: 'POST',
          body: formData,
          headers: {
            'X-Requested-With': 'XMLHttpRequest'
          }
        });
        
        if (response.ok) {
          // Remove from IndexedDB if successful
          console.log('[ServiceWorker] Successfully submitted form');
          await store.delete(form.id);
        }
      } catch (error) {
        console.error('[ServiceWorker] Failed to submit form:', error);
      }
    }
  } catch (error) {
    console.error('[ServiceWorker] Error in submitPendingForms:', error);
  }
}
