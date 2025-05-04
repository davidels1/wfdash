const CACHE_NAME = 'wf-sales-cache-v1';
const urlsToCache = [
  '/',
  '/static/manifest.json',
  '/static/images/pwa/icon-192x192.png',
  '/static/images/pwa/icon-512x512.png',
  '/static/images/pwa/apple-touch-icon.png',
  '/static/images/pwa/add-quote-192x192.png',
  '/static/images/pwa/add-quote-96x96.png',
  '/static/images/pwa/collections-192x192.png',
  '/static/images/pwa/collections-96x96.png',
  '/quotes/new',
  '/drivers/pool'
];

self.addEventListener('install', function(event) {
  console.log('Service Worker installing.');
  
  // Perform install steps
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function(cache) {
        console.log('Opened cache');
        return cache.addAll(urlsToCache);
      })
  );
  
  event.waitUntil(
    caches.open('orders-cache-v1').then((cache) => {
      return cache.addAll([
        '/',
        '/static/css/main.css',
        '/static/js/app.js',
        '/static/images/logo.png',
        '/offline.html'
      ]);
    })
  );

  // Pre-cache company information for faster search
  event.waitUntil(
    caches.open('company-data-v1').then((cache) => {
      return fetch('/api/companies/frequently-used')
        .then(response => response.json())
        .then(companies => {
          // Store top companies in cache
          cache.put('/api/companies/top', new Response(
            JSON.stringify(companies),
            { headers: { 'Content-Type': 'application/json' } }
          ));
        });
    })
  );

  self.skipWaiting();
});

self.addEventListener('activate', function(event) {
  console.log('Service Worker activated.');
  
  // Clean up old caches
  event.waitUntil(
    caches.keys().then(function(cacheNames) {
      return Promise.all(
        cacheNames.map(function(cacheName) {
          if (cacheName !== CACHE_NAME) {
            console.log('Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  
  // Ensure the service worker takes control immediately
  event.waitUntil(clients.claim());
  return self.clients.claim();
});

self.addEventListener('fetch', function(event) {
  // Track navigation for back button availability
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).then(function(response) {
        // Post message to client about navigation
        self.clients.matchAll().then(function(clients) {
          clients.forEach(function(client) {
            client.postMessage({
              type: 'navigation',
              url: event.request.url
            });
          });
        });
        return response;
      })
    );
  } else {
    event.respondWith(
      caches.match(event.request)
        .then(function(response) {
          // Cache hit - return response
          if (response) {
            return response;
          }
          return fetch(event.request).catch(() => {
            return caches.match('/offline.html');
          });
        })
    );
  }
});

// Handle shortcuts
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'OPEN_SHORTCUT') {
    const url = event.data.url;
    console.log('Opening shortcut URL:', url);
    
    // Open the shortcut URL
    self.clients.matchAll().then(clients => {
      if (clients && clients.length > 0) {
        clients[0].navigate(url);
        clients[0].focus();
      } else {
        self.clients.openWindow(url);
      }
    });
  }
});

// Handle home navigation
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'NAVIGATE_HOME') {
    console.log('Service worker handling navigation to home');
    
    // Get the URL to navigate to
    const url = event.data.url || '/';
    
    // Try to find an existing client window to navigate
    self.clients.matchAll({
      type: 'window'
    }).then(clients => {
      if (clients && clients.length > 0) {
        // Use the first available client
        const client = clients[0];
        
        // First clear the client's cache for the URL to ensure fresh content
        caches.match(url).then(cachedResponse => {
          if (cachedResponse) {
            console.log('Clearing cached version of home page');
            caches.open(CACHE_NAME).then(cache => {
              cache.delete(url);
            });
          }
        });
        
        // Navigate the client
        client.navigate(url).then(newClient => {
          // Focus the client
          if (newClient) {
            newClient.focus();
          }
        });
      } else {
        // If no clients available, open a new window
        self.clients.openWindow(url);
      }
    });
  }
});

// Handle test notifications from the test page
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SHOW_TEST_NOTIFICATION') {
    console.log('Showing test notification:', event.data.notification);
    
    const notificationData = event.data.notification;
    
    self.registration.showNotification(notificationData.title, {
      body: notificationData.body,
      icon: '/static/images/pwa/icon-192x192.png',
      badge: '/static/images/pwa/apple-touch-icon.png',
      vibrate: [100, 50, 100],
      data: {
        url: notificationData.url
      },
      actions: [
        { action: 'view', title: 'View Details' }
      ]
    }).then(() => {
      // Notify the client that the notification was shown
      event.source.postMessage({
        type: 'NOTIFICATION_SHOWN',
        success: true
      });
    }).catch(error => {
      console.error('Error showing notification:', error);
      event.source.postMessage({
        type: 'NOTIFICATION_SHOWN',
        success: false,
        error: error.message
      });
    });
  }
});

// Handle notification clicks
self.addEventListener('notificationclick', event => {
  console.log('Notification click received:', event);
  
  event.notification.close();
  
  if (event.action === 'view') {
    console.log('User clicked "View" action');
  }
  
  // This looks at the data attached to the notification
  const urlToOpen = event.notification.data && event.notification.data.url 
    ? event.notification.data.url 
    : '/';
  
  event.waitUntil(
    self.clients.matchAll({type: 'window'}).then(clientList => {
      // If a window tab is already open, focus it
      for (const client of clientList) {
        if (client.url === urlToOpen && 'focus' in client) {
          return client.focus();
        }
      }
      
      // If no window is open, open a new one
      if (self.clients.openWindow) {
        return self.clients.openWindow(urlToOpen);
      }
    })
  );
});

// Request permission
function requestNotificationPermission() {
  Notification.requestPermission().then(permission => {
    if (permission === 'granted') {
      // Subscribe the user
      subscribeUserToPush();
    }
  });
}

// In your service worker
self.addEventListener('push', (event) => {
  const data = event.data.json();
  const options = {
    body: data.body,
    icon: '/static/images/notification-icon.png',
    actions: [
      { action: 'view', title: 'View Order' }
    ]
  };
  
  event.waitUntil(
    self.registration.showNotification('New Order Alert', options)
  );
});

// In your service worker
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-orders') {
    event.waitUntil(syncOrders());
  }
});

async function syncOrders() {
  const orders = await getUnsentOrders();
  for (const order of orders) {
    try {
      await fetch('/api/orders', {
        method: 'POST',
        body: JSON.stringify(order),
        headers: {'Content-Type': 'application/json'}
      });
      await markOrderAsSent(order.id);
    } catch (error) {
      // Will retry on next sync
    }
  }
}