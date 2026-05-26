/**
 * AURA — フロントエンドロジック v3
 *
 * 設計方針:
 * - 「気になるのはどこ？」から始める
 * - 専門用語を使わない
 * - 必要な情報だけを、読みやすく
 * - APIが返す構造化データをそのまま活用
 * - XSS対策: DB由来データはescapeHtml()で処理
 * - SPA風ルーティング + ボトムナビ連動
 * - プレミアムなマイクロアニメーション
 */

// ==========================================
// XSS対策ユーティリティ
// ==========================================

/**
 * HTMLエスケープ — DB由来の文字列をinnerHTMLに注入する前に必ず使用
 * 構造的HTMLタグ（div, span等）は通常通り使用する
 */
function escapeHtml(str) {
    if (str == null) return '';
    const d = document.createElement('div');
    d.textContent = String(str);
    return d.innerHTML;
}

// ==========================================
// API通信
// ==========================================

async function api(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
}

async function apiPost(path, body) {
    const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
}

// ==========================================
// ナビゲーション（SPA風ルーティング）
// ==========================================

const navLinks = document.querySelectorAll('.nav-link');
const pages = document.querySelectorAll('.page');

function navigate(pageName) {
    // ヘッダーナビの更新
    navLinks.forEach(l => l.classList.toggle('active', l.dataset.page === pageName));

    // ページの切り替え（アニメーション付き）
    const currentPage = document.querySelector('.page.active');
    const nextPage = document.getElementById(`page-${pageName}`);
    if (currentPage && nextPage && currentPage !== nextPage) {
        currentPage.classList.add('page-exit');
        setTimeout(() => {
            currentPage.classList.remove('active', 'page-exit');
            nextPage.classList.add('active', 'page-enter');
            setTimeout(() => nextPage.classList.remove('page-enter'), 300);
        }, 150);
    } else {
        pages.forEach(p => p.classList.toggle('active', p.id === `page-${pageName}`));
    }
    window.scrollTo(0, 0);

    // URL更新（SPA風）
    const url = pageName === 'home' ? '/' : `/${pageName}`;
    history.pushState({ page: pageName }, '', url);

    // ボトムナビの更新
    document.querySelectorAll('.bottom-nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === pageName);
    });

    // 必要なデータのロード
    if (pageName === 'home' && !homeLoaded) loadHome();
    if (pageName === 'procedures' && !procLoaded) loadProcs();
    if (pageName === 'clinics' && !clinicsInitialized) initClinics();
    if (pageName === 'favorites') renderFavorites();
}

// ヘッダーナビのイベントリスナー
navLinks.forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        navigate(link.dataset.page);
    });
});

// ボトムナビのイベントリスナー
document.querySelectorAll('.bottom-nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        navigate(item.dataset.page);
    });
});

// ブラウザの戻る/進むボタン対応
window.addEventListener('popstate', (e) => {
    const page = e.state?.page || 'home';
    // 直接ページ切り替え（pushStateを再度呼ばないため、個別に処理）
    navLinks.forEach(l => l.classList.toggle('active', l.dataset.page === page));
    pages.forEach(p => p.classList.toggle('active', p.id === `page-${page}`));
    document.querySelectorAll('.bottom-nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
    });
    window.scrollTo(0, 0);

    if (page === 'home' && !homeLoaded) loadHome();
    if (page === 'procedures' && !procLoaded) loadProcs();
    if (page === 'clinics' && !clinicsInitialized) initClinics();
});

function navigateWithConcern(category) {
    navigate('procedures');
    loadProcs(category);
}

// ==========================================
// スクロール連動ヘッダー
// ==========================================

let lastScrollY = 0;

window.addEventListener('scroll', () => {
    const header = document.getElementById('site-header');
    if (!header) return;
    if (window.scrollY > lastScrollY && window.scrollY > 100) {
        // 下スクロール時: ヘッダーを隠す
        header.style.transform = 'translateY(-100%)';
    } else {
        // 上スクロール時: ヘッダーを表示
        header.style.transform = 'translateY(0)';
    }
    lastScrollY = window.scrollY;
}, { passive: true });

// ==========================================
// Intersection Observer — フェードインアニメーション
// ==========================================

const fadeObserver = new IntersectionObserver((entries) => {
    entries.forEach(e => {
        if (e.isIntersecting) {
            e.target.classList.add('visible');
        }
    });
}, { threshold: 0.1 });

document.querySelectorAll('.fade-in-section').forEach(el => fadeObserver.observe(el));

// ==========================================
// 数字カウントアップアニメーション
// ==========================================

/**
 * 要素内の数字をカウントアップ表示する
 * data-count属性の値を目標値として使用
 */
function animateCountUp(el) {
    const target = parseInt(el.dataset.count, 10);
    if (isNaN(target)) return;
    const duration = 1500;
    const start = performance.now();

    function update(now) {
        const progress = Math.min((now - start) / duration, 1);
        // イージング: 緩やかに減速
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.floor(target * eased).toLocaleString();
        if (progress < 1) requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
}

// 統計数字が表示されたらカウントアップ開始
const countObserver = new IntersectionObserver((entries) => {
    entries.forEach(e => {
        if (e.isIntersecting) {
            animateCountUp(e.target);
            countObserver.unobserve(e.target); // 一度だけ実行
        }
    });
}, { threshold: 0.3 });

document.querySelectorAll('.hero-stat-number').forEach(el => countObserver.observe(el));

// ==========================================
// スケルトンローダー
// ==========================================

/**
 * 指定要素にスケルトンUIを表示する
 */
function showSkeleton(el, count = 3) {
    el.innerHTML = Array(count).fill(
        '<div class="skeleton-card">' +
        '<div class="skeleton-line skeleton-line--title"></div>' +
        '<div class="skeleton-line"></div>' +
        '<div class="skeleton-line skeleton-line--short"></div>' +
        '</div>'
    ).join('');
}

// ==========================================
// ホーム — 価格の真実セクション
// ==========================================

let homeLoaded = false;

async function loadHome() {
    homeLoaded = true;
    const el = document.getElementById('price-truth-list');
    el.innerHTML = '<p class="loading-text">読み込み中</p>';

    try {
        const data = await api('/api/analysis/price-gaps?sort_by=gap_ratio');
        const items = (data.rankings || []).filter(r => r.gap_ratio && r.gap_ratio > 1.5).slice(0, 5);

        if (items.length === 0) {
            el.innerHTML = '';
            return;
        }

        el.innerHTML = items.map(r => `
            <div class="price-truth-item">
                <div class="pt-name">${escapeHtml(r.procedure_name)}</div>
                <div class="pt-prices">
                    <span class="pt-ad">広告では <s>${escapeHtml(r.advertised_display || '')}</s></span>
                    <span class="pt-real">実際は ${escapeHtml(r.real_display || '')}</span>
                </div>
                ${r.gap_warning ? `<div class="pt-note">${escapeHtml(truncate(r.gap_warning, 120))}</div>` : ''}
            </div>
        `).join('');
    } catch {
        el.innerHTML = '';
    }

    // ヒーロー統計を動的にAPIから取得
    try {
        const stats = await api('/stats');
        const statEls = document.querySelectorAll('.hero-stat-number');
        const statsMap = {
            'クリニック': stats.clinics || 0,
            '施術データ': stats.procedures || 0,
            '医師情報': stats.doctors || 0,
        };
        statEls.forEach(el => {
            const label = el.closest('.hero-stat')?.querySelector('.hero-stat-label')?.textContent;
            if (label && statsMap[label] !== undefined) {
                el.dataset.count = statsMap[label];
                animateCountUp(el);
            }
        });
    } catch { }
}

function truncate(str, len) {
    if (!str) return '';
    return str.length > len ? str.slice(0, len) + '…' : str;
}

// ==========================================
// 施術一覧
// ==========================================

let procLoaded = false;
let currentCategory = '';

async function loadProcs(category = '') {
    procLoaded = true;
    currentCategory = category;
    const filterEl = document.getElementById('proc-filters');
    const listEl = document.getElementById('proc-list');

    const cats = [
        { key: '', label: 'すべて' },
        { key: 'eye', label: '目もと' },
        { key: 'nose', label: '鼻' },
        { key: 'skin', label: '肌' },
        { key: 'contour', label: '輪郭' },
    ];
    filterEl.innerHTML = cats.map(c =>
        `<button class="filter-btn ${c.key === category ? 'active' : ''}"
                 onclick="loadProcs('${c.key}')">${escapeHtml(c.label)}</button>`
    ).join('');

    // スケルトンUIで読込表示
    showSkeleton(listEl, 4);

    try {
        const params = category ? `?category=${category}` : '';
        const data = await api(`/api/procedures/${params}`);
        const procs = data.procedures || [];

        if (procs.length === 0) {
            listEl.innerHTML = '<p class="loading-text">施術が見つかりませんでした</p>';
            return;
        }

        listEl.innerHTML = procs.map(p => {
            // APIが構造化データを返す（price.advertised, price.real）
            const advDisplay = p.price?.advertised || '';
            const realDisplay = p.price?.real || '';
            const invLabel = {
                low: '負担が軽い',
                medium: '標準的',
                high: '負担が大きい',
            }[p.invasiveness] || '';
            const invClass = {
                low: 'badge-low',
                medium: 'badge-medium',
                high: 'badge-high',
            }[p.invasiveness] || '';

            return `
                <div class="proc-item" onclick="showDetail('${escapeHtml(p.id)}')">
                    <div class="proc-item-header">
                        <span class="proc-item-name">${escapeHtml(p.name)}</span>
                        <span class="proc-item-cat">${escapeHtml(p.category_label || '')}</span>
                    </div>
                    <div class="proc-item-meta">
                        ${p.downtime?.real ? `<span class="proc-meta-dt">回復 ${escapeHtml(truncate(p.downtime.real, 30))}</span>` : ''}
                        ${p.risk_count ? `<span class="proc-meta-risk">リスク ${escapeHtml(String(p.risk_count))}項目</span>` : ''}
                    </div>
                    <div class="proc-item-prices">
                        ${advDisplay ? `<span class="pt-ad">広告 <s>${escapeHtml(truncate(advDisplay, 20))}</s></span>` : ''}
                        ${realDisplay ? `<span class="pt-real">実際 ${escapeHtml(truncate(realDisplay, 25))}</span>` : ''}
                    </div>
                    ${invLabel ? `<span class="proc-item-badge ${invClass}">${escapeHtml(invLabel)}</span>` : ''}
                </div>
            `;
        }).join('');
    } catch (e) {
        listEl.innerHTML = '<p class="loading-text">読み込みに失敗しました</p>';
    }
}

// ==========================================
// 施術詳細パネル
// ==========================================

async function showDetail(id) {
    const overlay = document.getElementById('detail-overlay');
    const body = document.getElementById('detail-body');
    overlay.style.display = 'flex';
    body.innerHTML = '<p class="loading-text">読み込み中</p>';

    try {
        const p = await api(`/api/procedures/${id}`);

        // APIが構造化データを返す
        const pricing = p.pricing || {};
        const advDisplay = pricing.advertised?.display || '';
        const realDisplay = pricing.real?.display || '';
        const hidden = pricing.hidden_costs || [];
        const dt = p.downtime || {};
        const risks = p.risks || [];
        const questions = p.counseling_questions || [];
        const invLabel = {
            low: '負担が軽い',
            medium: '標準的',
            high: '負担が大きい',
        }[p.invasiveness] || '';
        const quality = p.data_quality || {};

        body.innerHTML = `
            <h2 class="detail-name">${escapeHtml(p.name)}</h2>
            <p class="detail-meta">${escapeHtml(p.category_label || '')} ／ ${escapeHtml(invLabel)} ／ ${escapeHtml(p.duration || '')}</p>

            ${p.description ? `<p class="detail-desc">${escapeHtml(p.description)}</p>` : ''}

            <div class="detail-block">
                <div class="detail-block-title">値段について</div>
                <div class="detail-price-grid">
                    <div class="detail-price-box detail-price-box--ad">
                        <div class="detail-price-label">広告の表示</div>
                        <div class="detail-price-value">${escapeHtml(advDisplay)}</div>
                    </div>
                    <div class="detail-price-box detail-price-box--real">
                        <div class="detail-price-label">実際の相場</div>
                        <div class="detail-price-value">${escapeHtml(realDisplay)}</div>
                    </div>
                </div>
                ${pricing.gap_warning ? `<div class="detail-warning">${escapeHtml(pricing.gap_warning)}</div>` : ''}
            </div>

            ${hidden.length > 0 ? `
            <div class="detail-block">
                <div class="detail-block-title">広告に含まれていない費用</div>
                <ul class="detail-list">
                    ${hidden.map(h => `<li>${escapeHtml(h)}</li>`).join('')}
                </ul>
            </div>` : ''}

            <div class="detail-block">
                <div class="detail-block-title">回復にかかる期間</div>
                <div class="detail-dt-row">
                    <div class="detail-dt-item">
                        <span class="detail-dt-label">クリニックの説明</span>
                        <span class="detail-dt-val">${escapeHtml(dt.official || '—')}</span>
                    </div>
                    <div class="detail-dt-item detail-dt-item--real">
                        <span class="detail-dt-label">実際の経過</span>
                        <span class="detail-dt-val">${escapeHtml(dt.real || '—')}</span>
                    </div>
                </div>
            </div>

            ${risks.length > 0 ? `
            <div class="detail-block">
                <div class="detail-block-title">知っておきたいリスク</div>
                <ul class="detail-list">
                    ${risks.map(r => `<li>${escapeHtml(r)}</li>`).join('')}
                </ul>
            </div>` : ''}

            ${questions.length > 0 ? `
            <div class="detail-block">
                <div class="detail-block-title">カウンセリングで聞いておくこと</div>
                <ol class="detail-question-list">
                    ${questions.map(q => `<li>${escapeHtml(q)}</li>`).join('')}
                </ol>
            </div>` : ''}

            <div class="detail-provenance">
                <span>情報の根拠: ${escapeHtml(quality.evidence_label || quality.sources_note || '')}</span>
                ${quality.last_verified ? `<span>最終確認: ${escapeHtml(quality.last_verified.split('T')[0])}</span>` : ''}
            </div>
        `;
    } catch {
        body.innerHTML = '<p class="loading-text">読み込みに失敗しました</p>';
    }
}

document.getElementById('detail-close').addEventListener('click', () => {
    document.getElementById('detail-overlay').style.display = 'none';
});
document.getElementById('detail-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) e.currentTarget.style.display = 'none';
});

// ==========================================
// クリニック検索
// ==========================================

let clinicsInitialized = false;

async function initClinics() {
    clinicsInitialized = true;
    try {
        const stats = await api('/api/clinics/stats');
        const sel = document.getElementById('clinic-area');
        if (stats.by_city) {
            stats.by_city.forEach(item => {
                const city = item.city || item[0];
                const count = item.count || item[1];
                const opt = document.createElement('option');
                opt.value = city;
                opt.textContent = `${city}（${count}件）`;
                sel.appendChild(opt);
            });
        }
    } catch { }
    searchClinics();
}

async function searchClinics(page = 1) {
    const q = document.getElementById('clinic-q').value;
    const area = document.getElementById('clinic-area').value;
    const dept = document.getElementById('clinic-dept').value;
    const sort = document.getElementById('clinic-sort').value;
    const listEl = document.getElementById('clinic-list');
    const pagerEl = document.getElementById('clinic-pager');

    // スケルトンUIで検索中表示
    showSkeleton(listEl, 5);

    const params = new URLSearchParams({ page, per_page: 15, sort_by: sort });
    if (q) params.set('q', q);
    if (area) params.set('city', area);
    if (dept) params.set('department', dept);

    try {
        const data = await api(`/api/clinics/?${params}`);
        const clinics = data.clinics || [];

        if (clinics.length === 0) {
            listEl.innerHTML = '<p class="loading-text">該当するクリニックが見つかりませんでした</p>';
            pagerEl.innerHTML = '';
            return;
        }

        // 結果件数表示
        const resultCount = document.getElementById('clinic-result-count');
        if (resultCount) {
            resultCount.textContent = `${data.total}件のクリニック`;
        }

        listEl.innerHTML = clinics.map(c => {
            const depts = Array.isArray(c.departments) ? c.departments : [];
            const tags = depts.slice(0, 3).map(d => `<span class="clinic-tag">${escapeHtml(d)}</span>`).join('');
            const rating = c.google_rating ? `<span class="clinic-rating">★ ${c.google_rating.toFixed(1)}</span>` : '';
            const reviews = c.google_review_count ? `<span class="clinic-reviews">${escapeHtml(String(c.google_review_count))}件の口コミ</span>` : '';
            const noGoogleLabel = !c.google_rating ? '<span class="clinic-tag clinic-tag--muted">厚労省データ</span>' : '';

            // 透明性スコアバッジ
            let transparencyBadge = '';
            if (c.transparency_score && c.transparency_score >= 40) {
                const level = c.transparency_score >= 70 ? 'high' : c.transparency_score >= 50 ? 'mid' : 'low';
                transparencyBadge = `<span class="transparency-badge transparency-badge--${level}">透明性 ${Math.round(c.transparency_score)}</span>`;
            }

            // サムネイル画像（Google写真がある場合）
            const thumbHtml = c.thumbnail_ref
                ? `<div class="clinic-item-thumb" style="background-image:url('/api/clinics/${escapeHtml(c.id)}/photo?ref=${encodeURIComponent(c.thumbnail_ref)}&maxwidth=200')"></div>`
                : '';
            const hasThumb = c.thumbnail_ref ? ' clinic-item--has-thumb' : '';

            // 比較チェックボックス
            const isCompared = compareList.some(item => item.id === c.id);
            const compareCheckbox = `<input type="checkbox" class="compare-checkbox" 
                data-clinic-id="${escapeHtml(c.id)}" 
                data-clinic-name="${escapeHtml(c.name)}" 
                ${isCompared ? 'checked' : ''}
                onclick="event.stopPropagation(); toggleCompare(this)"
                title="比較に追加">`;

            // お気に入りボタン
            const favBtn = favoriteButtonHtml(c.id);

            return `
                <div class="clinic-item${hasThumb}" onclick="showClinicDetail('${escapeHtml(c.id)}')">
                    ${favBtn}
                    ${compareCheckbox}
                    ${thumbHtml}
                    <div class="clinic-item-content">
                        <div class="clinic-item-header">
                            <div class="clinic-item-name">${escapeHtml(c.name)}</div>
                            ${rating || reviews ? `<div class="clinic-item-rating">${rating}${reviews}</div>` : ''}
                        </div>
                        <div class="clinic-item-addr">${escapeHtml(c.address || c.city || '')}</div>
                        <div class="clinic-item-tags">${tags}${noGoogleLabel}${transparencyBadge}</div>
                    </div>
                </div>
            `;
        }).join('');

        // ページャー
        const totalPages = data.total_pages || 1;
        if (totalPages > 1) {
            let btns = '';
            if (page > 1) btns += `<button class="pager-btn" onclick="searchClinics(${page-1})">前へ</button>`;
            for (let p = Math.max(1, page-2); p <= Math.min(totalPages, page+2); p++) {
                btns += `<button class="pager-btn ${p===page?'active':''}" onclick="searchClinics(${p})">${p}</button>`;
            }
            if (page < totalPages) btns += `<button class="pager-btn" onclick="searchClinics(${page+1})">次へ</button>`;
            pagerEl.innerHTML = btns;
        } else {
            pagerEl.innerHTML = '';
        }
    } catch {
        listEl.innerHTML = '<p class="loading-text">検索に失敗しました</p>';
    }
}

document.getElementById('clinic-search-btn').addEventListener('click', () => searchClinics(1));
document.getElementById('clinic-q').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') searchClinics(1);
});

// ==========================================
// クリニック詳細パネル
// ==========================================

async function showClinicDetail(id) {
    const overlay = document.getElementById('clinic-detail-overlay');
    const body = document.getElementById('clinic-detail-body');
    overlay.style.display = 'flex';
    body.innerHTML = '<p class="loading-text">読み込み中</p>';

    try {
        const c = await api(`/api/clinics/${id}`);

        // 写真ギャラリー構築
        const photos = c.photos || [];
        let photoHtml = '';
        if (photos.length > 0) {
            // Google Places Photo APIの参照キーからフルパスURLを構築
            const photoItems = photos.slice(0, 6).map((ref, i) => {
                const photoUrl = `/api/clinics/${escapeHtml(id)}/photo?ref=${encodeURIComponent(ref)}&maxwidth=600`;
                return `<div class="clinic-photo-item ${i === 0 ? 'clinic-photo-item--main' : ''}"
                             style="background-image:url('${photoUrl}')"
                             onclick="openPhotoViewer('${photoUrl}')"></div>`;
            }).join('');
            photoHtml = `<div class="clinic-photo-gallery">${photoItems}</div>`;
        }

        // 診療科目
        const depts = Array.isArray(c.departments) ? c.departments : [];
        const deptTags = depts.map(d => `<span class="clinic-tag">${escapeHtml(d)}</span>`).join('');

        // 営業時間
        let hoursHtml = '';
        if (c.opening_hours && c.opening_hours.weekday_text && c.opening_hours.weekday_text.length > 0) {
            const hoursList = c.opening_hours.weekday_text.map(h => `<li>${escapeHtml(h)}</li>`).join('');
            hoursHtml = `
                <div class="detail-block">
                    <div class="detail-block-title">診療時間</div>
                    <ul class="clinic-hours-list">${hoursList}</ul>
                </div>`;
        }

        // 地図（緯度・経度がある場合）
        let mapHtml = '';
        if (c.lat && c.lng && c.lat !== 0 && c.lng !== 0) {
            const osmUrl = `https://www.openstreetmap.org/export/embed.html?bbox=${c.lng - 0.005}%2C${c.lat - 0.003}%2C${c.lng + 0.005}%2C${c.lat + 0.003}&layer=mapnik&marker=${c.lat}%2C${c.lng}`;
            const osmLink = `https://www.openstreetmap.org/?mlat=${c.lat}&mlon=${c.lng}#map=17/${c.lat}/${c.lng}`;
            mapHtml = `
                <div class="detail-block">
                    <div class="detail-block-title">アクセス</div>
                    <div class="clinic-map-container">
                        <iframe src="${osmUrl}" class="clinic-map-iframe" loading="lazy"></iframe>
                    </div>
                    <a href="${osmLink}" target="_blank" rel="noopener" class="clinic-map-link">大きい地図で見る →</a>
                </div>`;
        }

        // Google評価表示
        let ratingHtml = '';
        if (c.google_rating) {
            const stars = '★'.repeat(Math.round(c.google_rating)) + '☆'.repeat(5 - Math.round(c.google_rating));
            ratingHtml = `
                <div class="clinic-detail-rating">
                    <span class="clinic-detail-rating-score">${c.google_rating.toFixed(1)}</span>
                    <span class="clinic-detail-rating-stars">${stars}</span>
                    ${c.google_review_count ? `<span class="clinic-detail-rating-count">${escapeHtml(String(c.google_review_count))}件の口コミ</span>` : ''}
                </div>`;
        }

        // 情報行（電話・医師数・開設者）
        const infoItems = [];
        if (c.phone && c.phone.trim()) infoItems.push({ label: '電話', value: c.phone, href: `tel:${c.phone}` });
        if (c.doctor_count) infoItems.push({ label: '医師数', value: `${c.doctor_count}名` });
        if (c.medical_corp_name && c.medical_corp_name.trim()) infoItems.push({ label: '開設者', value: c.medical_corp_name });
        if (c.website) infoItems.push({ label: 'Webサイト', value: '公式サイトを開く', href: c.website, external: true });

        let infoHtml = '';
        if (infoItems.length > 0) {
            const infoRows = infoItems.map(item => {
                const val = item.href
                    ? `<a href="${escapeHtml(item.href)}" ${item.external ? 'target="_blank" rel="noopener"' : ''} class="clinic-info-link">${escapeHtml(item.value)}</a>`
                    : escapeHtml(item.value);
                return `<div class="clinic-info-row">
                    <span class="clinic-info-label">${escapeHtml(item.label)}</span>
                    <span class="clinic-info-value">${val}</span>
                </div>`;
            }).join('');
            infoHtml = `
                <div class="detail-block">
                    <div class="detail-block-title">基本情報</div>
                    ${infoRows}
                </div>`;
        }

        // データ出典
        const prov = c.data_provenance || {};
        const provItems = [];
        if (prov.source) provItems.push(`ソース: ${escapeHtml(c.data_quality?.source || prov.source)}`);
        if (prov.fetched_at) provItems.push(`取得: ${escapeHtml(prov.fetched_at.split('T')[0])}`);
        if (prov.freshness) {
            const freshnessLabel = { fresh: '最新', stale: '要更新', expired: '期限切れ' }[prov.freshness] || prov.freshness;
            provItems.push(`鮮度: ${escapeHtml(freshnessLabel)}`);
        }

        // Google Maps直リンク
        let gmapsHtml = '';
        if (c.google_place_id) {
            const gmapsUrl = `https://www.google.com/maps/place/?q=place_id:${escapeHtml(c.google_place_id)}`;
            gmapsHtml = `
                <div class="clinic-gmaps-link">
                    <a href="${gmapsUrl}" target="_blank" rel="noopener">Google Mapsで口コミを見る →</a>
                </div>`;
        }

        // 透明性スコア
        let transparencyHtml = '';
        if (c.transparency_score && c.transparency_score > 0) {
            const score = Math.round(c.transparency_score);
            const level = score >= 70 ? 'high' : score >= 50 ? 'mid' : score >= 30 ? 'low' : 'minimal';
            const levelLabel = { high: '情報公開に積極的', mid: '一定の情報公開あり', low: '基本情報のみ', minimal: '情報が限定的' }[level];
            transparencyHtml = `
                <div class="detail-block">
                    <div class="detail-block-title">AURA 透明性スコア</div>
                    <div class="transparency-meter">
                        <div class="transparency-bar">
                            <div class="transparency-fill transparency-fill--${level}" style="width:${score}%"></div>
                        </div>
                        <div class="transparency-label">
                            <span class="transparency-score">${score}<small>/100</small></span>
                            <span class="transparency-desc">${escapeHtml(levelLabel)}</span>
                        </div>
                    </div>
                </div>`;
        }

        // 医師情報
        let doctorsHtml = '';
        const doctors = c.doctors || [];
        if (doctors.length > 0) {
            const docItems = doctors.slice(0, 5).map(d => {
                const certs = d.certifications || [];
                const certBadges = certs.slice(0, 2).map(cert => `<span class="doctor-cert">${escapeHtml(cert)}</span>`).join('');
                return `<div class="doctor-item">
                    <span class="doctor-title">${escapeHtml(d.title || '医師')}</span>
                    <span class="doctor-name">${escapeHtml(d.name)}</span>
                    ${certBadges}
                </div>`;
            }).join('');
            const moreCount = doctors.length > 5 ? `<div class="doctor-more">他 ${doctors.length - 5}名</div>` : '';
            doctorsHtml = `
                <div class="detail-block">
                    <div class="detail-block-title">在籍医師</div>
                    ${docItems}${moreCount}
                </div>`;
        }

        // 施術メニュー
        let proceduresHtml = '';
        const procs = c.procedures || [];
        if (procs.length > 0) {
            const procItems = procs.slice(0, 8).map(p => {
                const price = p.price_advertised ? `¥${Number(p.price_advertised).toLocaleString()}〜` : '';
                const srcLabel = p.source === 'website_scrape' ? '公式' : p.source === 'chain_inference' ? '系列' : '';
                return `<div class="proc-menu-item">
                    <span class="proc-menu-name">${escapeHtml(p.name)}</span>
                    ${price ? `<span class="proc-menu-price">${escapeHtml(price)}</span>` : ''}
                    ${srcLabel ? `<span class="proc-menu-src">${escapeHtml(srcLabel)}</span>` : ''}
                </div>`;
            }).join('');
            const moreProcs = procs.length > 8 ? `<div class="doctor-more">他 ${procs.length - 8}件</div>` : '';
            proceduresHtml = `
                <div class="detail-block">
                    <div class="detail-block-title">対応施術</div>
                    ${procItems}${moreProcs}
                </div>`;
        }

        body.innerHTML = `
            ${photoHtml}
            <h2 class="detail-name">${escapeHtml(c.name)}</h2>
            ${c.branch_name ? `<p class="clinic-detail-branch">${escapeHtml(c.branch_name)}</p>` : ''}
            ${ratingHtml}
            ${gmapsHtml}
            <p class="clinic-detail-addr">${escapeHtml(c.address)}</p>
            <div class="clinic-detail-depts">${deptTags}</div>

            ${c.editorial_summary ? `<p class="clinic-detail-summary">${escapeHtml(c.editorial_summary)}</p>` : ''}

            ${transparencyHtml}
            ${doctorsHtml}
            ${proceduresHtml}
            ${(() => {
                const rs = c.review_summary;
                if (!rs || rs.total === 0) return '';
                const total = rs.positive + rs.neutral + rs.negative;
                if (total === 0) return '';
                const posPct = Math.round(rs.positive / total * 100);
                const neuPct = Math.round(rs.neutral / total * 100);
                const negPct = Math.round(rs.negative / total * 100);
                const sentLabel = rs.avg_sentiment > 0.2 ? '良好' : rs.avg_sentiment < -0.2 ? '注意' : '普通';
                const sentColor = rs.avg_sentiment > 0.2 ? 'var(--success)' : rs.avg_sentiment < -0.2 ? 'var(--warning)' : 'var(--text-muted)';
                const aspectLabels = {service:'接客', skill:'技術', price:'価格', wait:'待ち', facility:'施設'};
                const aspectHtml = Object.entries(rs.aspects || {}).map(([k,v]) =>
                    `<span class="aspect-tag">${aspectLabels[k] || k} ${v}</span>`
                ).join('');
                return `<div class="detail-block">
                    <div class="detail-block-title">口コミ分析 <span style="font-size:0.7rem;color:${sentColor};font-weight:600;margin-left:0.5rem;">${sentLabel}</span></div>
                    <div class="sentiment-bar-container">
                        <div class="sentiment-bar">
                            ${posPct > 0 ? `<div class="sentiment-segment sentiment-pos" style="width:${posPct}%"></div>` : ''}
                            ${neuPct > 0 ? `<div class="sentiment-segment sentiment-neu" style="width:${neuPct}%"></div>` : ''}
                            ${negPct > 0 ? `<div class="sentiment-segment sentiment-neg" style="width:${negPct}%"></div>` : ''}
                        </div>
                        <div class="sentiment-labels">
                            <span class="sentiment-label-pos">好評 ${posPct}%</span>
                            <span class="sentiment-label-neu">普通 ${neuPct}%</span>
                            <span class="sentiment-label-neg">不満 ${negPct}%</span>
                        </div>
                    </div>
                    ${aspectHtml ? `<div class="aspect-tags">${aspectHtml}</div>` : ''}
                    <div style="font-size:0.68rem;color:var(--text-muted);margin-top:0.4rem;">Google口コミ ${rs.total}件の感情分析</div>
                </div>`;
            })()}
            ${(() => {
                const revs = c.reviews || [];
                if (revs.length === 0) return '';
                const revItems = revs.map((r, idx) => {
                    const stars = r.rating ? '★'.repeat(Math.round(r.rating)) + '☆'.repeat(5 - Math.round(r.rating)) : '';
                    const fullText = escapeHtml(r.text || '');
                    const truncLen = 80;
                    const needsTruncate = fullText.length > truncLen;
                    const shortText = needsTruncate ? fullText.slice(0, truncLen) + '...' : fullText;
                    const revId = `review-${Date.now()}-${idx}`;
                    return `<div class="review-item">
                        <div class="review-header">
                            <span class="review-stars">${stars}</span>
                            <span class="review-author">${escapeHtml(r.author || '')}</span>
                        </div>
                        <div class="review-text" id="${revId}-short">${shortText}${needsTruncate ? ` <button class="review-expand-btn" onclick="document.getElementById('${revId}-short').style.display='none'; document.getElementById('${revId}-full').style.display='block';">続きを読む</button>` : ''}</div>
                        ${needsTruncate ? `<div class="review-text" id="${revId}-full" style="display:none;">${fullText} <button class="review-expand-btn" onclick="document.getElementById('${revId}-full').style.display='none'; document.getElementById('${revId}-short').style.display='block';">閉じる</button></div>` : ''}
                    </div>`;
                }).join('');
                return `<div class="detail-block">
                    <div class="detail-block-title">口コミ</div>
                    ${revItems}
                </div>`;
            })()}
            ${infoHtml}
            ${hoursHtml}
            ${mapHtml}

            <div class="detail-provenance">
                ${provItems.map(p => `<span>${p}</span>`).join('')}
            </div>
        `;
    } catch (e) {
        body.innerHTML = '<p class="loading-text">クリニック情報の取得に失敗しました</p>';
    }
}

function openPhotoViewer(url) {
    window.open(url, '_blank');
}

document.getElementById('clinic-detail-close').addEventListener('click', () => {
    document.getElementById('clinic-detail-overlay').style.display = 'none';
});
document.getElementById('clinic-detail-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) e.currentTarget.style.display = 'none';
});

// ==========================================
// クリニック比較機能
// ==========================================

let compareList = []; // 最大3件: { id, name }

/**
 * 比較チェックボックスのトグル
 */
function toggleCompare(checkbox) {
    const clinicId = checkbox.dataset.clinicId;
    const clinicName = checkbox.dataset.clinicName;

    if (checkbox.checked) {
        // 最大3件チェック
        if (compareList.length >= 3) {
            checkbox.checked = false;
            alert('比較できるクリニックは最大3件です');
            return;
        }
        compareList.push({ id: clinicId, name: clinicName });
    } else {
        compareList = compareList.filter(item => item.id !== clinicId);
    }

    updateCompareBar();
}

/**
 * 比較バーの更新
 */
function updateCompareBar() {
    const bar = document.getElementById('compare-bar');
    const itemsEl = document.getElementById('compare-bar-items');

    if (compareList.length === 0) {
        bar.style.display = 'none';
        return;
    }

    bar.style.display = 'flex';
    itemsEl.innerHTML = compareList.map(c => `
        <span class="compare-bar-item">
            ${escapeHtml(c.name)}
            <span class="compare-bar-item-remove" onclick="removeCompare('${escapeHtml(c.id)}')">&times;</span>
        </span>
    `).join('');
}

/**
 * 比較リストからクリニックを削除
 */
function removeCompare(clinicId) {
    compareList = compareList.filter(item => item.id !== clinicId);
    updateCompareBar();

    // チェックボックスの状態も更新
    const checkbox = document.querySelector(`.compare-checkbox[data-clinic-id="${clinicId}"]`);
    if (checkbox) checkbox.checked = false;
}

/**
 * 比較パネルを表示
 */
async function showComparePanel() {
    if (compareList.length < 2) {
        alert('比較するには2件以上選択してください');
        return;
    }

    const overlay = document.getElementById('compare-overlay');
    const body = document.getElementById('compare-body');
    overlay.style.display = 'flex';
    body.innerHTML = '<p class="loading-text">比較データを読み込み中</p>';

    try {
        // 個別にfetchして並べて表示
        const clinicData = await Promise.all(
            compareList.map(item => api(`/api/clinics/${item.id}`))
        );

        body.innerHTML = clinicData.map(c => {
            const depts = Array.isArray(c.departments) ? c.departments : [];
            const rating = c.google_rating ? `★ ${c.google_rating.toFixed(1)}` : '—';
            const reviewCount = c.google_review_count ? `${c.google_review_count}件` : '—';
            const doctorCount = c.doctor_count ? `${c.doctor_count}名` : '—';
            const transparency = c.transparency_score ? `${Math.round(c.transparency_score)}/100` : '—';

            return `
                <div class="compare-col">
                    <div class="compare-col-name">${escapeHtml(c.name)}</div>
                    <div class="compare-row">
                        <span class="compare-row-label">評価</span>
                        <span class="compare-row-value">${rating}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">口コミ数</span>
                        <span class="compare-row-value">${reviewCount}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">医師数</span>
                        <span class="compare-row-value">${doctorCount}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">診療科</span>
                        <span class="compare-row-value">${escapeHtml(depts.join(', ') || '—')}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">透明性</span>
                        <span class="compare-row-value">${transparency}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">所在地</span>
                        <span class="compare-row-value">${escapeHtml(c.city || c.address || '—')}</span>
                    </div>
                </div>
            `;
        }).join('');
    } catch {
        body.innerHTML = '<p class="loading-text">比較データの取得に失敗しました</p>';
    }
}

// 比較ボタンのイベントリスナー
document.getElementById('compare-btn').addEventListener('click', showComparePanel);

// 比較パネルの閉じるボタン
document.getElementById('compare-close').addEventListener('click', () => {
    document.getElementById('compare-overlay').style.display = 'none';
});
document.getElementById('compare-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) e.currentTarget.style.display = 'none';
});

// ==========================================
// ESCキーでパネルを閉じる
// ==========================================

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.getElementById('detail-overlay').style.display = 'none';
        document.getElementById('clinic-detail-overlay').style.display = 'none';
        document.getElementById('compare-overlay').style.display = 'none';
    }
});

// ==========================================
// 相談（チャット）
// ==========================================

let sessionId = null;

function mdToHtml(text) {
    return text
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        .replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>')
        .replace(/((<li>[\s\S]*?<\/li>))/g, (match) => `<ul>${match}</ul>`)
        .replace(/<\/ul>\s*<ul>/g, '')
        .replace(/\n\n/g, '<br><br>')
        .replace(/\n/g, '<br>');
}

/**
 * チャットメッセージを追加
 * matched_clinicsがある場合は推薦カードも表示
 */
function addMsg(role, content, matchedClinics) {
    const el = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `msg msg--${role}`;

    let bodyContent = '';
    if (role === 'assistant') {
        bodyContent = mdToHtml(content);
    } else {
        bodyContent = escapeHtml(content);
    }

    div.innerHTML = `<div class="msg-body">${bodyContent}</div>`;

    // 推薦カードの表示（アシスタントメッセージのみ）
    if (role === 'assistant' && matchedClinics && matchedClinics.length > 0) {
        matchedClinics.forEach(clinic => {
            const card = document.createElement('div');
            card.className = 'recommendation-card';
            card.onclick = () => showClinicDetail(clinic.id);
            card.innerHTML = `
                <div class="recommendation-card-name">${escapeHtml(clinic.name)}</div>
                ${clinic.rating ? `<div class="recommendation-card-rating">★ ${clinic.rating.toFixed(1)}</div>` : ''}
                ${clinic.reason ? `<div class="recommendation-card-reason">${escapeHtml(clinic.reason)}</div>` : ''}
            `;
            div.appendChild(card);
        });
    }

    el.appendChild(div);
    el.scrollTop = el.scrollHeight;

    // 初回メッセージ後はイントロ非表示
    const intro = document.getElementById('advisor-intro');
    if (intro) intro.style.display = 'none';

    // クイックアクションを非表示
    const quickActions = document.getElementById('chat-quick-actions');
    if (quickActions) quickActions.style.display = 'none';
}

async function sendChat() {
    const input = document.getElementById('chat-input');
    const btn = document.getElementById('chat-send');
    const message = input.value.trim();
    if (!message) return;

    addMsg('user', message);
    input.value = '';
    btn.disabled = true;

    // ストリーミングを試行、失敗時は非ストリーミングにフォールバック
    try {
        await sendChatStream(message);
    } catch (streamErr) {
        console.warn('ストリーミング失敗、非ストリーミングAPIへフォールバック:', streamErr);
        await sendChatLegacy(message);
    }

    btn.disabled = false;
    input.focus();
}

/**
 * ストリーミングチャット送信
 * fetch + ReadableStream で SSE データを受信し、
 * アシスタントバブルにリアルタイム追記する
 */
async function sendChatStream(message) {
    const chatMessages = document.getElementById('chat-messages');

    // ローディング表示（ストリーミング開始前の3点アニメーション）
    const loader = document.createElement('div');
    loader.className = 'msg msg--assistant';
    loader.innerHTML = '<div class="msg-body msg-loading"><span></span><span></span><span></span></div>';
    chatMessages.appendChild(loader);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    const body = { message };
    if (sessionId) body.session_id = sessionId;

    const res = await fetch('/api/advisor/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });

    if (!res.ok) {
        loader.remove();
        throw new Error(`HTTP ${res.status}`);
    }

    // ストリーミング用のアシスタントバブルを作成
    loader.remove();
    const msgDiv = document.createElement('div');
    msgDiv.className = 'msg msg--assistant';
    const bodyDiv = document.createElement('div');
    bodyDiv.className = 'msg-body chat-msg--streaming';
    msgDiv.appendChild(bodyDiv);
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    // イントロとクイックアクションを非表示
    const intro = document.getElementById('advisor-intro');
    if (intro) intro.style.display = 'none';
    const quickActions = document.getElementById('chat-quick-actions');
    if (quickActions) quickActions.style.display = 'none';

    // テキスト蓄積用
    let fullText = '';
    let matchedClinics = [];

    // SSEストリームの読み取り
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // SSEのイベント区切り（\n\n）で分割
        const events = buffer.split('\n\n');
        // 最後の不完全なイベントはバッファに残す
        buffer = events.pop();

        for (const eventStr of events) {
            if (!eventStr.trim()) continue;

            // "data: " プレフィックスを除去
            const lines = eventStr.split('\n');
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const jsonStr = line.slice(6);
                let event;
                try {
                    event = JSON.parse(jsonStr);
                } catch {
                    continue;
                }

                if (event.type === 'start') {
                    // セッションIDを記録
                    sessionId = event.session_id;

                } else if (event.type === 'delta') {
                    // テキストをリアルタイム追記（プレーンテキストで表示）
                    fullText += event.content;
                    bodyDiv.textContent = fullText;
                    chatMessages.scrollTop = chatMessages.scrollHeight;

                } else if (event.type === 'done') {
                    // ストリーミング完了：Markdown→HTML変換を一括実行
                    bodyDiv.classList.remove('chat-msg--streaming');
                    bodyDiv.innerHTML = mdToHtml(fullText);
                    matchedClinics = event.matched_clinics || [];

                    // 推薦クリニックカードを表示
                    if (matchedClinics.length > 0) {
                        matchedClinics.forEach(clinic => {
                            const card = document.createElement('div');
                            card.className = 'recommendation-card';
                            card.onclick = () => showClinicDetail(clinic.clinic_id || clinic.id);
                            card.innerHTML = `
                                <div class="recommendation-card-name">${escapeHtml(clinic.name)}</div>
                                ${clinic.google_rating ? `<div class="recommendation-card-rating">★ ${clinic.google_rating.toFixed(1)}</div>` : ''}
                                ${clinic.match_reasons ? `<div class="recommendation-card-reason">${escapeHtml(clinic.match_reasons.slice(0, 3).join(' / '))}</div>` : ''}
                            `;
                            msgDiv.appendChild(card);
                        });
                    }
                    chatMessages.scrollTop = chatMessages.scrollHeight;

                } else if (event.type === 'error') {
                    // エラー表示
                    bodyDiv.classList.remove('chat-msg--streaming');
                    bodyDiv.textContent = event.message || '通信エラーが発生しました。';
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                }
            }
        }
    }

    // バッファに残ったデータを処理
    if (buffer.trim()) {
        const lines = buffer.split('\n');
        for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
                const event = JSON.parse(line.slice(6));
                if (event.type === 'delta') {
                    fullText += event.content;
                    bodyDiv.textContent = fullText;
                } else if (event.type === 'done') {
                    bodyDiv.classList.remove('chat-msg--streaming');
                    bodyDiv.innerHTML = mdToHtml(fullText);
                }
            } catch { }
        }
    }

    // ストリーミングクラスが残っていたら最終変換
    if (bodyDiv.classList.contains('chat-msg--streaming')) {
        bodyDiv.classList.remove('chat-msg--streaming');
        if (fullText) {
            bodyDiv.innerHTML = mdToHtml(fullText);
        }
    }
}

/**
 * 非ストリーミングチャット送信（フォールバック用）
 * 既存の /api/advisor/chat エンドポイントを使用
 */
async function sendChatLegacy(message) {
    // ローディング表示
    const loader = document.createElement('div');
    loader.className = 'msg msg--assistant';
    loader.innerHTML = '<div class="msg-body msg-loading"><span></span><span></span><span></span></div>';
    document.getElementById('chat-messages').appendChild(loader);

    try {
        const body = { message };
        if (sessionId) body.session_id = sessionId;
        const data = await apiPost('/api/advisor/chat', body);
        sessionId = data.session_id;
        loader.remove();
        addMsg('assistant', data.message, data.matched_clinics);
    } catch {
        loader.remove();
        addMsg('assistant', '通信に失敗しました。もう一度お試しください。');
    }
}

document.getElementById('chat-send').addEventListener('click', sendChat);
document.getElementById('chat-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendChat();
});

// ==========================================
// チャット クイックアクション
// ==========================================

document.querySelectorAll('.chat-quick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const chatInput = document.getElementById('chat-input');
        chatInput.value = btn.dataset.msg;
        sendChat();
    });
});

// ==========================================
// 初期化
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    // URLに基づいてページを表示（リロード対応）
    const path = window.location.pathname.replace(/^\//, '') || 'home';
    const validPages = ['home', 'procedures', 'clinics', 'advisor'];
    const initialPage = validPages.includes(path) ? path : 'home';

    // 初期状態をhistoryに記録
    history.replaceState({ page: initialPage }, '', initialPage === 'home' ? '/' : `/${initialPage}`);
    navigate(initialPage);

    // 法的行動支援ツールの読み込み
    loadTools();
});

// ==========================================
// トースト通知
// ==========================================

/**
 * トースト通知を表示する
 * @param {string} message - 表示メッセージ
 * @param {string} type - 'success' | 'error' | 'info'
 */
function showToast(message, type = 'info') {
    // 既存のトーストがあれば削除
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    const icons = { success: '✓', error: '✕', info: 'ℹ' };
    toast.innerHTML = `<span class="toast-icon">${icons[type] || icons.info}</span><span class="toast-text">${escapeHtml(message)}</span>`;
    document.body.appendChild(toast);

    // アニメーションで表示
    requestAnimationFrame(() => {
        toast.classList.add('toast--visible');
    });

    // 3秒後に消す
    setTimeout(() => {
        toast.classList.add('toast--exit');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ==========================================
// ボタン リップル効果
// ==========================================

document.addEventListener('click', (e) => {
    const btn = e.target.closest('.cta-button, .search-btn, .chat-send-btn, .filter-btn');
    if (!btn) return;

    const rect = btn.getBoundingClientRect();
    const ripple = document.createElement('span');
    ripple.className = 'btn-ripple';
    ripple.style.left = `${e.clientX - rect.left}px`;
    ripple.style.top = `${e.clientY - rect.top}px`;
    btn.style.position = 'relative';
    btn.style.overflow = 'hidden';
    btn.appendChild(ripple);
    setTimeout(() => ripple.remove(), 600);
});

// ==========================================
// 法的行動支援ツール
// ==========================================

/**
 * ツール一覧を取得してカードグリッドに描画する
 * ページ読み込み時にDOMContentLoaded内から呼ばれる
 */
async function loadTools() {
    const grid = document.getElementById('tools-grid');
    if (!grid) return; // ツールセクションが無い場合はスキップ

    grid.innerHTML = '<p class="loading-text">読み込み中</p>';

    try {
        const data = await api('/api/advisor/tools');
        const tools = data.tools || [];

        if (tools.length === 0) {
            grid.innerHTML = '<p class="loading-text">現在ご利用いただけるツールはありません</p>';
            return;
        }

        grid.innerHTML = tools.map(tool => `
            <div class="tool-card" onclick="openTool('${escapeHtml(tool.id)}')">
                <span class="tool-card-icon">${escapeHtml(tool.icon || '🔧')}</span>
                <div class="tool-card-title">${escapeHtml(tool.title)}</div>
                <div class="tool-card-desc">${escapeHtml(tool.description || '')}</div>
                ${tool.badge ? `<span class="tool-card-badge">${escapeHtml(tool.badge)}</span>` : ''}
            </div>
        `).join('');
    } catch {
        grid.innerHTML = '<p class="loading-text">ツールの読み込みに失敗しました</p>';
    }
}

/**
 * ツールカードクリック時にAPIを呼び出し、モーダルで結果を表示する
 * @param {string} toolId - ツールのID
 */
async function openTool(toolId) {
    // price_checkツールはチャットへ誘導
    if (toolId === 'price_check') {
        navigate('advisor');
        const chatInput = document.getElementById('chat-input');
        if (chatInput) {
            chatInput.value = 'この施術の適正価格を教えてください';
            chatInput.focus();
        }
        showToast('チャットで施術名をお伝えください', 'info');
        return;
    }

    // モーダルオーバーレイを取得または作成
    let overlay = document.getElementById('tool-modal-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'tool-modal-overlay';
        overlay.className = 'tool-modal-overlay';
        overlay.innerHTML = `
            <div class="tool-modal">
                <button class="tool-modal-close" onclick="closeToolModal()">&times;</button>
                <div id="tool-modal-content"></div>
            </div>
        `;
        // オーバーレイ背景クリックで閉じる
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeToolModal();
        });
        document.body.appendChild(overlay);
    }

    const contentEl = document.getElementById('tool-modal-content');
    contentEl.innerHTML = '<p class="loading-text">読み込み中</p>';

    // モーダルを表示
    overlay.classList.add('active');

    try {
        const result = await apiPost(`/api/advisor/tools/${toolId}`, {});
        contentEl.innerHTML = renderToolModal(toolId, result);
    } catch {
        contentEl.innerHTML = '<p class="loading-text">ツールの実行に失敗しました。もう一度お試しください。</p>';
    }
}

/**
 * ツールIDに応じたモーダルコンテンツのHTMLを生成する
 * @param {string} toolId - ツールのID
 * @param {object} result - APIから返されたツール実行結果
 * @returns {string} モーダル内に表示するHTML
 */
function renderToolModal(toolId, result) {
    const title = escapeHtml(result.title || 'ツール結果');

    // テンプレート表示系ツール（クーリングオフ通知書、カルテ開示請求書）
    if (toolId === 'cooling_off' || toolId === 'medical_records') {
        const template = result.template || '';
        const instructions = result.instructions || [];
        const legalBasis = result.legal_basis || '';

        let html = `<h2>${title}</h2>`;

        if (template) {
            html += `<h3>テンプレート</h3>`;
            html += `<pre>${escapeHtml(template)}</pre>`;
            html += `<button class="tool-copy-btn" onclick="copyTemplate(this.previousElementSibling.textContent)">📋 コピーする</button>`;
        }

        if (instructions.length > 0) {
            html += `<h3>使い方・手順</h3>`;
            html += `<ul>${instructions.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>`;
        }

        if (legalBasis) {
            html += `<div class="legal-basis">📖 ${escapeHtml(legalBasis)}</div>`;
        }

        return html;
    }

    // チェックリスト系ツール（契約書チェック、クリニック比較）
    if (toolId === 'contract_check' || toolId === 'clinic_compare') {
        const checklist = result.checklist || {};
        const redFlags = result.red_flags || [];
        const advice = result.advice || '';

        let html = `<h2>${title}</h2>`;

        // カテゴリ別チェックリスト
        const categories = Object.keys(checklist);
        if (categories.length > 0) {
            html += `<h3>チェックリスト</h3>`;
            categories.forEach(category => {
                html += `<div class="checklist-category">${escapeHtml(category)}</div>`;
                const items = checklist[category] || [];
                html += `<ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
            });
        }

        // 危険信号
        if (redFlags.length > 0) {
            html += `<h3>⚠️ 危険信号（レッドフラグ）</h3>`;
            html += `<ul>${redFlags.map(flag => `<li class="red-flag">${escapeHtml(flag)}</li>`).join('')}</ul>`;
        }

        // アドバイス
        if (advice) {
            html += `<div class="warning-box">💡 ${escapeHtml(advice)}</div>`;
        }

        return html;
    }

    // 術後ケアツール
    if (toolId === 'post_surgery') {
        const normalSigns = result.normal_signs || [];
        const warningSigns = result.warning_signs || [];
        const emergencyContacts = result.emergency_contacts || [];

        let html = `<h2>${title}</h2>`;

        if (normalSigns.length > 0) {
            html += `<h3>✅ 正常な経過サイン</h3>`;
            html += `<ul>${normalSigns.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>`;
        }

        if (warningSigns.length > 0) {
            html += `<h3>🚨 要注意サイン（すぐ受診）</h3>`;
            html += `<ul>${warningSigns.map(s => `<li class="red-flag">${escapeHtml(s)}</li>`).join('')}</ul>`;
        }

        if (emergencyContacts.length > 0) {
            html += `<h3>📞 緊急連絡先</h3>`;
            html += `<ul>${emergencyContacts.map(c => `<li>${escapeHtml(c)}</li>`).join('')}</ul>`;
        }

        return html;
    }

    // 消費生活センターツール
    if (toolId === 'consumer_center') {
        const hotline = result.hotline || '';
        const prepareBefore = result.prepare_before_call || [];
        const timelineTemplate = result.timeline_template || '';

        let html = `<h2>${title}</h2>`;

        if (hotline) {
            html += `<div class="warning-box">📞 消費者ホットライン: <strong>${escapeHtml(hotline)}</strong></div>`;
        }

        if (prepareBefore.length > 0) {
            html += `<h3>📋 電話前に準備するもの</h3>`;
            html += `<ul>${prepareBefore.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
        }

        if (timelineTemplate) {
            html += `<h3>📝 経緯まとめテンプレート</h3>`;
            html += `<pre>${escapeHtml(timelineTemplate)}</pre>`;
            html += `<button class="tool-copy-btn" onclick="copyTemplate(this.previousElementSibling.textContent)">📋 コピーする</button>`;
        }

        return html;
    }

    // price_checkはopenTool内で処理済みだが、念のためフォールバック
    if (toolId === 'price_check') {
        return `<h2>${title}</h2><p>チャットで施術名をお伝えいただくと、適正価格をお調べします。</p>`;
    }

    // 未知のツールタイプ: レスポンスをそのまま表示
    let html = `<h2>${title}</h2>`;
    if (result.message) {
        html += `<p>${escapeHtml(result.message)}</p>`;
    }
    return html;
}

/**
 * ツールモーダルを閉じる
 */
function closeToolModal() {
    const overlay = document.getElementById('tool-modal-overlay');
    if (overlay) {
        overlay.classList.remove('active');
    }
}

/**
 * テンプレートテキストをクリップボードにコピーする
 * @param {string} text - コピーするテキスト
 */
async function copyTemplate(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('テンプレートをコピーしました', 'success');
    } catch {
        // フォールバック: 古いブラウザ用
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        showToast('テンプレートをコピーしました', 'success');
    }
}

// ESCキーでツールモーダルも閉じる
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeToolModal();
    }
});


// ==========================================
// お気に入り機能
// ==========================================

/**
 * お気に入りストア — LocalStorageで永続化
 */
const favoritesStore = {
    key: 'aura_favorites',

    /** お気に入りIDの一覧を取得 */
    getAll() {
        try {
            return JSON.parse(localStorage.getItem(this.key) || '[]');
        } catch { return []; }
    },

    /** お気に入りに追加 */
    add(clinicId) {
        const favs = this.getAll();
        if (!favs.includes(clinicId)) {
            favs.push(clinicId);
            localStorage.setItem(this.key, JSON.stringify(favs));
        }
    },

    /** お気に入りから削除 */
    remove(clinicId) {
        const favs = this.getAll().filter(id => id !== clinicId);
        localStorage.setItem(this.key, JSON.stringify(favs));
    },

    /** トグル（追加/削除）*/
    toggle(clinicId) {
        if (this.isFavorite(clinicId)) {
            this.remove(clinicId);
            return false;
        } else {
            this.add(clinicId);
            return true;
        }
    },

    /** お気に入りかどうか */
    isFavorite(clinicId) {
        return this.getAll().includes(clinicId);
    },

    /** 件数 */
    count() {
        return this.getAll().length;
    },
};


/**
 * お気に入りボタン（ハート）をトグル
 */
function toggleFavorite(event, clinicId) {
    event.stopPropagation();
    const added = favoritesStore.toggle(clinicId);

    // ハートアイコンの更新
    document.querySelectorAll(`.favorite-btn[data-clinic-id="${clinicId}"]`).forEach(btn => {
        btn.classList.toggle('active', added);
        btn.setAttribute('aria-label', added ? 'お気に入りから削除' : 'お気に入りに追加');
    });

    // トースト
    showToast(added ? 'お気に入りに追加しました' : 'お気に入りから削除しました', 'info');

    // お気に入りページが表示中なら再レンダリング
    const favPage = document.getElementById('page-favorites');
    if (favPage && favPage.classList.contains('active')) {
        renderFavorites();
    }

    // ボトムナビのバッジ更新
    updateFavoritesBadge();
}


/**
 * ハートボタンのHTMLを生成
 */
function favoriteButtonHtml(clinicId) {
    const isFav = favoritesStore.isFavorite(clinicId);
    return `<button class="favorite-btn ${isFav ? 'active' : ''}" 
                data-clinic-id="${escapeHtml(clinicId)}"
                onclick="toggleFavorite(event, '${escapeHtml(clinicId)}')"
                aria-label="${isFav ? 'お気に入りから削除' : 'お気に入りに追加'}">
                <svg viewBox="0 0 24 24" width="18" height="18" 
                     fill="${isFav ? 'currentColor' : 'none'}" 
                     stroke="currentColor" stroke-width="2">
                    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
                </svg>
            </button>`;
}


/**
 * お気に入りページを描画
 */
async function renderFavorites() {
    const listEl = document.getElementById('favorites-list');
    const emptyEl = document.getElementById('favorites-empty');
    const favIds = favoritesStore.getAll();

    if (favIds.length === 0) {
        listEl.innerHTML = '';
        emptyEl.style.display = 'flex';
        return;
    }

    emptyEl.style.display = 'none';

    // お気に入りクリニックの情報を取得
    const clinics = [];
    for (const id of favIds) {
        try {
            const c = await api(`/api/clinics/${id}`);
            clinics.push(c);
        } catch { /* 削除済みなどは無視 */ }
    }

    if (clinics.length === 0) {
        listEl.innerHTML = '';
        emptyEl.style.display = 'flex';
        return;
    }

    listEl.innerHTML = clinics.map(c => {
        const rating = c.google_rating ? `<span class="clinic-rating">★ ${c.google_rating}</span>` : '';
        const reviews = c.google_review_count ? `<span class="clinic-reviews">(${c.google_review_count}件)</span>` : '';

        let transparencyBadge = '';
        if (c.transparency_score != null) {
            const level = c.transparency_score >= 70 ? 'high' : c.transparency_score >= 40 ? 'mid' : 'low';
            transparencyBadge = `<span class="transparency-badge transparency-badge--${level}">透明性 ${Math.round(c.transparency_score)}</span>`;
        }

        return `
            <div class="clinic-item favorite-item" onclick="showClinicDetail('${escapeHtml(c.id)}')">
                ${favoriteButtonHtml(c.id)}
                <div class="clinic-item-content">
                    <div class="clinic-item-header">
                        <div class="clinic-item-name">${escapeHtml(c.name)}</div>
                        ${rating || reviews ? `<div class="clinic-item-rating">${rating}${reviews}</div>` : ''}
                    </div>
                    <div class="clinic-item-addr">${escapeHtml(c.address || c.city || '')}</div>
                    <div class="clinic-item-tags">
                        ${c.phone ? `<span class="clinic-tag">📞 ${escapeHtml(c.phone)}</span>` : ''}
                        ${transparencyBadge}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}


/**
 * ボトムナビにバッジ表示
 */
function updateFavoritesBadge() {
    const count = favoritesStore.count();
    const navItem = document.querySelector('.bottom-nav-item[data-page="favorites"]');
    if (!navItem) return;

    let badge = navItem.querySelector('.nav-badge');
    if (count > 0) {
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'nav-badge';
            navItem.appendChild(badge);
        }
        badge.textContent = count;
    } else if (badge) {
        badge.remove();
    }
}

// 初期バッジ表示
updateFavoritesBadge();
