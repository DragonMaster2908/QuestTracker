// A simple service worker to enable PWA installation
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  // Currently just acts as a pass-through
  event.respondWith(fetch(event.request));
});
