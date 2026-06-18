// AURA Service Worker — オフラインサポート
const CACHE_NAME = 'aura-v4';
const STATIC_ASSETS = [
    '/',
    '/static/css/style.css',
    '/static/js/app.js',
    '/static/manifest.json',
    '/static/icons/icon.svg',
];

// インストール: 静的アセットをプリキャッシュ
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

// アクティベート: 古いキャッシュを削除
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(key => key !== CACHE_NAME)
                    .map(key => caches.delete(key))
            )
        ).then(() => self.clients.claim())
    );
});

// フェッチ: ネットワークファースト、失敗時はキャッシュ
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // APIリクエストはキャッシュしない
    if (url.pathname.startsWith('/api/')) {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then(response => {
                // 成功レスポンスをキャッシュに保存
                if (response.ok) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => {
                        cache.put(event.request, clone);
                    });
                }
                return response;
            })
            .catch(() => {
                // オフライン時はキャッシュから返却
                return caches.match(event.request);
            })
    );
});
