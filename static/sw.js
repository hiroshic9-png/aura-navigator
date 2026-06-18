// AURA Service Worker — ネットワークファースト戦略
const CACHE_NAME = 'aura-v7';

// インストール: 即座にactivateさせる
self.addEventListener('install', (event) => {
    self.skipWaiting();
});

// アクティベート: 古いキャッシュを全削除
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

// フェッチ: ネットワークファースト（開発中はキャッシュを使わない）
self.addEventListener('fetch', (event) => {
    // APIリクエストはキャッシュしない
    if (event.request.url.includes('/api/')) {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then(response => {
                // 有効なレスポンスをキャッシュに保存
                if (response.ok) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => {
                        cache.put(event.request, clone);
                    });
                }
                return response;
            })
            .catch(() => {
                // オフライン時のみキャッシュから返す
                return caches.match(event.request);
            })
    );
});
