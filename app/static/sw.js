const CACHE_NAME = 'topp-nfs-v3'; 

// Wir cachen nur die Basis-Dateien (kein HTML!)
const ASSETS_TO_CACHE = [
  '/static/manifest.json',
  '/static/images/icon.svg',
  '/static/images/logo.svg',
  '/static/images/logo-white.svg',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css'
];

self.addEventListener('install', (event) => {
  self.skipWaiting(); // Zwingt den Browser, den neuen Worker sofort zu nutzen
  
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Fehlertolerantes Laden
      return Promise.allSettled(
        ASSETS_TO_CACHE.map(url => {
          return cache.add(url).catch(err => console.warn('Konnte nicht gecacht werden:', url));
        })
      );
    })
  );
});

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

// Der wichtigste Teil: Wenn Daten angefragt werden
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  // 1. Wenn nach einer HTML-Seite gesucht wird (z.B. App-Start)
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => {
        // WIR SIND OFFLINE: Der Service Worker baut live eine Ersatz-Ansicht!
        return new Response(
          `<!DOCTYPE html>
          <html lang="de">
          <head>
              <meta charset="UTF-8">
              <meta name="viewport" content="width=device-width, initial-scale=1.0">
              <title>Topp-NFS | Offline</title>
              <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
              <style>
                  body { background-color: #1a1d21; color: #f8f9fa; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; text-align: center; padding: 20px; font-family: sans-serif; margin: 0; }
                  .icon { font-size: 5rem; margin-bottom: 20px; }
              </style>
          </head>
          <body>
              <div class="icon">📡</div>
              <h2 style="font-weight: 600;">Keine Verbindung</h2>
              <p style="color: #adb5bd; margin-bottom: 30px;">Du bist momentan offline. Um Prüfungen oder BPR-Algorithmen zu laden, benötigst du eine Internetverbindung.</p>
              <button onclick="location.reload()" style="background-color: #0d6efd; color: white; border: none; padding: 12px 30px; border-radius: 50px; font-weight: bold; font-size: 1rem;">Erneut versuchen</button>
          </body>
          </html>`,
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      })
    );
    return;
  }

  // 2. Für alle anderen Dateien (CSS, Bilder etc.)
  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request);
    })
  );
});