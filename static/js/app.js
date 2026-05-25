/**
 * AURA — フロントエンドロジック
 *
 * 設計方針:
 * - 「気になるのはどこ？」から始める
 * - 専門用語を使わない
 * - 必要な情報だけを、読みやすく
 * - APIが返す構造化データをそのまま活用
 */

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
// ナビゲーション
// ==========================================

const navLinks = document.querySelectorAll('.nav-link');
const pages = document.querySelectorAll('.page');

function navigate(pageName) {
    navLinks.forEach(l => l.classList.toggle('active', l.dataset.page === pageName));
    pages.forEach(p => p.classList.toggle('active', p.id === `page-${pageName}`));
    window.scrollTo(0, 0);

    if (pageName === 'home' && !homeLoaded) loadHome();
    if (pageName === 'procedures' && !procLoaded) loadProcs();
    if (pageName === 'clinics' && !clinicsInitialized) initClinics();
}

navLinks.forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        navigate(link.dataset.page);
    });
});

function navigateWithConcern(category) {
    navigate('procedures');
    loadProcs(category);
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
                <div class="pt-name">${r.procedure_name}</div>
                <div class="pt-prices">
                    <span class="pt-ad">広告では <s>${r.advertised_display || ''}</s></span>
                    <span class="pt-real">実際は ${r.real_display || ''}</span>
                </div>
                ${r.gap_warning ? `<div class="pt-note">${truncate(r.gap_warning, 120)}</div>` : ''}
            </div>
        `).join('');
    } catch {
        el.innerHTML = '';
    }
}

function truncate(str, len) {
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
                 onclick="loadProcs('${c.key}')">${c.label}</button>`
    ).join('');

    listEl.innerHTML = '<p class="loading-text">読み込み中</p>';

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
                <div class="proc-item" onclick="showDetail('${p.id}')">
                    <div class="proc-item-header">
                        <span class="proc-item-name">${p.name}</span>
                        <span class="proc-item-cat">${p.category_label || ''}</span>
                    </div>
                    <div class="proc-item-meta">
                        ${p.downtime?.real ? `<span class="proc-meta-dt">回復 ${truncate(p.downtime.real, 30)}</span>` : ''}
                        ${p.risk_count ? `<span class="proc-meta-risk">リスク ${p.risk_count}項目</span>` : ''}
                    </div>
                    <div class="proc-item-prices">
                        ${advDisplay ? `<span class="pt-ad">広告 <s>${truncate(advDisplay, 20)}</s></span>` : ''}
                        ${realDisplay ? `<span class="pt-real">実際 ${truncate(realDisplay, 25)}</span>` : ''}
                    </div>
                    ${invLabel ? `<span class="proc-item-badge ${invClass}">${invLabel}</span>` : ''}
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
            <h2 class="detail-name">${p.name}</h2>
            <p class="detail-meta">${p.category_label || ''} ／ ${invLabel} ／ ${p.duration || ''}</p>

            ${p.description ? `<p class="detail-desc">${p.description}</p>` : ''}

            <div class="detail-block">
                <div class="detail-block-title">値段について</div>
                <div class="detail-price-grid">
                    <div class="detail-price-box detail-price-box--ad">
                        <div class="detail-price-label">広告の表示</div>
                        <div class="detail-price-value">${advDisplay}</div>
                    </div>
                    <div class="detail-price-box detail-price-box--real">
                        <div class="detail-price-label">実際の相場</div>
                        <div class="detail-price-value">${realDisplay}</div>
                    </div>
                </div>
                ${pricing.gap_warning ? `<div class="detail-warning">${pricing.gap_warning}</div>` : ''}
            </div>

            ${hidden.length > 0 ? `
            <div class="detail-block">
                <div class="detail-block-title">広告に含まれていない費用</div>
                <ul class="detail-list">
                    ${hidden.map(h => `<li>${h}</li>`).join('')}
                </ul>
            </div>` : ''}

            <div class="detail-block">
                <div class="detail-block-title">回復にかかる期間</div>
                <div class="detail-dt-row">
                    <div class="detail-dt-item">
                        <span class="detail-dt-label">クリニックの説明</span>
                        <span class="detail-dt-val">${dt.official || '—'}</span>
                    </div>
                    <div class="detail-dt-item detail-dt-item--real">
                        <span class="detail-dt-label">実際の経過</span>
                        <span class="detail-dt-val">${dt.real || '—'}</span>
                    </div>
                </div>
            </div>

            ${risks.length > 0 ? `
            <div class="detail-block">
                <div class="detail-block-title">知っておきたいリスク</div>
                <ul class="detail-list">
                    ${risks.map(r => `<li>${r}</li>`).join('')}
                </ul>
            </div>` : ''}

            ${questions.length > 0 ? `
            <div class="detail-block">
                <div class="detail-block-title">カウンセリングで聞いておくこと</div>
                <ol class="detail-question-list">
                    ${questions.map(q => `<li>${q}</li>`).join('')}
                </ol>
            </div>` : ''}

            <div class="detail-provenance">
                <span>情報の根拠: ${quality.evidence_label || quality.sources_note || ''}</span>
                ${quality.last_verified ? `<span>最終確認: ${quality.last_verified.split('T')[0]}</span>` : ''}
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

    listEl.innerHTML = '<p class="loading-text">検索中</p>';

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
            const tags = depts.slice(0, 3).map(d => `<span class="clinic-tag">${d}</span>`).join('');
            const rating = c.google_rating ? `<span class="clinic-rating">★ ${c.google_rating.toFixed(1)}</span>` : '';
            const reviews = c.google_review_count ? `<span class="clinic-reviews">${c.google_review_count}件の口コミ</span>` : '';
            const noGoogleLabel = !c.google_rating ? '<span class="clinic-tag clinic-tag--muted">厚労省データ</span>' : '';

            // 透明性スコアバッジ
            let transparencyBadge = '';
            if (c.transparency_score && c.transparency_score >= 40) {
                const level = c.transparency_score >= 70 ? 'high' : c.transparency_score >= 50 ? 'mid' : 'low';
                transparencyBadge = `<span class="transparency-badge transparency-badge--${level}">透明性 ${Math.round(c.transparency_score)}</span>`;
            }

            // サムネイル画像（Google写真がある場合）
            const thumbHtml = c.thumbnail_ref
                ? `<div class="clinic-item-thumb" style="background-image:url('/api/clinics/${c.id}/photo?ref=${encodeURIComponent(c.thumbnail_ref)}&maxwidth=200')"></div>`
                : '';
            const hasThumb = c.thumbnail_ref ? ' clinic-item--has-thumb' : '';

            return `
                <div class="clinic-item${hasThumb}" onclick="showClinicDetail('${c.id}')">
                    ${thumbHtml}
                    <div class="clinic-item-content">
                        <div class="clinic-item-header">
                            <div class="clinic-item-name">${c.name}</div>
                            ${rating || reviews ? `<div class="clinic-item-rating">${rating}${reviews}</div>` : ''}
                        </div>
                        <div class="clinic-item-addr">${c.address || c.city || ''}</div>
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
                // Google Placesのphoto_referenceを使った画像表示
                const photoUrl = `/api/clinics/${id}/photo?ref=${encodeURIComponent(ref)}&maxwidth=600`;
                return `<div class="clinic-photo-item ${i === 0 ? 'clinic-photo-item--main' : ''}"
                             style="background-image:url('${photoUrl}')"
                             onclick="openPhotoViewer('${photoUrl}')"></div>`;
            }).join('');
            photoHtml = `<div class="clinic-photo-gallery">${photoItems}</div>`;
        }

        // 診療科目
        const depts = Array.isArray(c.departments) ? c.departments : [];
        const deptTags = depts.map(d => `<span class="clinic-tag">${d}</span>`).join('');

        // 営業時間
        let hoursHtml = '';
        if (c.opening_hours && c.opening_hours.weekday_text && c.opening_hours.weekday_text.length > 0) {
            const hoursList = c.opening_hours.weekday_text.map(h => `<li>${h}</li>`).join('');
            hoursHtml = `
                <div class="detail-block">
                    <div class="detail-block-title">診療時間</div>
                    <ul class="clinic-hours-list">${hoursList}</ul>
                </div>`;
        }

        // 地図（緯度・経度がある場合）
        let mapHtml = '';
        if (c.lat && c.lng && c.lat !== 0 && c.lng !== 0) {
            // OpenStreetMapのembed地図（APIキー不要）
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
                    ${c.google_review_count ? `<span class="clinic-detail-rating-count">${c.google_review_count}件の口コミ</span>` : ''}
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
                    ? `<a href="${item.href}" ${item.external ? 'target="_blank" rel="noopener"' : ''} class="clinic-info-link">${item.value}</a>`
                    : item.value;
                return `<div class="clinic-info-row">
                    <span class="clinic-info-label">${item.label}</span>
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
        if (prov.source) provItems.push(`ソース: ${c.data_quality?.source || prov.source}`);
        if (prov.fetched_at) provItems.push(`取得: ${prov.fetched_at.split('T')[0]}`);
        if (prov.freshness) {
            const freshnessLabel = { fresh: '最新', stale: '要更新', expired: '期限切れ' }[prov.freshness] || prov.freshness;
            provItems.push(`鮮度: ${freshnessLabel}`);
        }

        // Google Maps直リンク
        let gmapsHtml = '';
        if (c.google_place_id) {
            const gmapsUrl = `https://www.google.com/maps/place/?q=place_id:${c.google_place_id}`;
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
                            <span class="transparency-desc">${levelLabel}</span>
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
                const certBadges = certs.slice(0, 2).map(cert => `<span class="doctor-cert">${cert}</span>`).join('');
                return `<div class="doctor-item">
                    <span class="doctor-title">${d.title || '医師'}</span>
                    <span class="doctor-name">${d.name}</span>
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
                    <span class="proc-menu-name">${p.name}</span>
                    ${price ? `<span class="proc-menu-price">${price}</span>` : ''}
                    ${srcLabel ? `<span class="proc-menu-src">${srcLabel}</span>` : ''}
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
            <h2 class="detail-name">${c.name}</h2>
            ${c.branch_name ? `<p class="clinic-detail-branch">${c.branch_name}</p>` : ''}
            ${ratingHtml}
            ${gmapsHtml}
            <p class="clinic-detail-addr">${c.address}</p>
            <div class="clinic-detail-depts">${deptTags}</div>

            ${c.editorial_summary ? `<p class="clinic-detail-summary">${c.editorial_summary}</p>` : ''}

            ${transparencyHtml}
            ${doctorsHtml}
            ${proceduresHtml}
            ${(() => {
                const revs = c.reviews || [];
                if (revs.length === 0) return '';
                const revItems = revs.map(r => {
                    const stars = r.rating ? '★'.repeat(Math.round(r.rating)) + '☆'.repeat(5 - Math.round(r.rating)) : '';
                    return `<div class="review-item">
                        <div class="review-header">
                            <span class="review-stars">${stars}</span>
                            <span class="review-author">${r.author || ''}</span>
                        </div>
                        <div class="review-text">${r.text}</div>
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

// ESCキーでパネルを閉じる
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.getElementById('detail-overlay').style.display = 'none';
        document.getElementById('clinic-detail-overlay').style.display = 'none';
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
        .replace(/(<li>[\s\S]*?<\/li>)/g, (match) => `<ul>${match}</ul>`)
        .replace(/<\/ul>\s*<ul>/g, '')
        .replace(/\n\n/g, '<br><br>')
        .replace(/\n/g, '<br>');
}

function addMsg(role, content) {
    const el = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `msg msg--${role}`;
    div.innerHTML = `<div class="msg-body">${role === 'assistant' ? mdToHtml(content) : escapeHtml(content)}</div>`;
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;

    // 初回メッセージ後はイントロ非表示
    const intro = document.getElementById('advisor-intro');
    if (intro) intro.style.display = 'none';
}

function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

async function sendChat() {
    const input = document.getElementById('chat-input');
    const btn = document.getElementById('chat-send');
    const message = input.value.trim();
    if (!message) return;

    addMsg('user', message);
    input.value = '';
    btn.disabled = true;

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
        addMsg('assistant', data.message);
    } catch {
        loader.remove();
        addMsg('assistant', '通信に失敗しました。もう一度お試しください。');
    }
    btn.disabled = false;
    input.focus();
}

document.getElementById('chat-send').addEventListener('click', sendChat);
document.getElementById('chat-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendChat();
});

// ==========================================
// 初期化
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    navigate('home');
});
