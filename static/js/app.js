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
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * 価格ソースに応じたバッジHTMLを生成する
 * @param {string} source - 価格ソース（estimated/website_scrape/chain_inference/department_inference）
 * @returns {string} バッジHTML文字列
 */
function _priceSourceBadge(source) {
    if (!source) return '';
    if (source === 'website_scrape') {
        return '<span class="price-source-badge price-source--official">公式</span>';
    }
    if (source === 'estimated') {
        return '<span class="price-source-badge price-source--estimated" data-tooltip="市場統計データに基づく推定値です。実際の価格はクリニックにご確認ください。">参考価格</span>';
    }
    if (source === 'chain_inference' || source === 'department_inference') {
        return '<span class="price-source-badge price-source--inferred">推定</span>';
    }
    return '';
}

// Phase 62: トレンドSVG矢印を生成する
const _TREND_ARROWS = {
    improving: '<svg class="trend-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="7" y1="17" x2="17" y2="7"/><polyline points="7 7 17 7 17 17"/></svg>',
    declining: '<svg class="trend-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="7" y1="7" x2="17" y2="17"/><polyline points="17 7 17 17 7 17"/></svg>',
    stable:    '<svg class="trend-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="14 7 19 12 14 17"/></svg>',
};
const _TREND_LABELS = { improving: '改善傾向', stable: '安定', declining: '低下傾向' };
const _TREND_MODIFIERS = { improving: 'improving', stable: 'stable', declining: 'declining' };

/**
 * 詳細パネル用トレンドバッジを生成する
 * @param {Object} trend - {direction, recent_avg, older_avg, recent_count}
 * @returns {string} HTML文字列
 */
function renderTrendBadge(trend) {
    if (!trend || !trend.direction) return '';
    const dir = trend.direction;
    const arrow = _TREND_ARROWS[dir] || _TREND_ARROWS.stable;
    const label = _TREND_LABELS[dir] || '安定';
    const mod = _TREND_MODIFIERS[dir] || 'stable';
    // ツールチップ用テキスト
    const recentAvg = trend.recent_avg != null ? trend.recent_avg : '-';
    const olderAvg = trend.older_avg != null ? trend.older_avg : '-';
    const tooltip = `最近の口コミ評価: ${escapeHtml(String(recentAvg))} / 過去: ${escapeHtml(String(olderAvg))}`;
    const detail = (trend.recent_avg != null && trend.older_avg != null)
        ? `<span class="trend-detail">最近 ${escapeHtml(String(recentAvg))} / 過去 ${escapeHtml(String(olderAvg))}</span>`
        : '';
    return `<div class="trend-badge trend-badge--${mod}" title="${tooltip}">
        ${arrow}${escapeHtml(label)}${detail}
    </div>`;
}

/**
 * リスト用のミニトレンドバッジを生成する
 * @param {Object|undefined} trend - {direction} （リスト用は軽量版）
 * @returns {string} HTML文字列
 */
function renderTrendMini(trend) {
    if (!trend || !trend.direction) return '';
    const dir = trend.direction;
    const arrow = _TREND_ARROWS[dir] || _TREND_ARROWS.stable;
    const label = _TREND_LABELS[dir] || '安定';
    const mod = _TREND_MODIFIERS[dir] || 'stable';
    return `<span class="trend-mini trend-mini--${mod}" title="${escapeHtml(label)}">${arrow}</span>`;
}


/**
 * スケルトンローダーを生成
 * @param {number} count - カード数
 * @returns {string} HTML文字列
 */
function renderSkeletons(count = 3) {
    return Array.from({ length: count }, () =>
        `<div class="skeleton skeleton-card"></div>`
    ).join('');
}

/**
 * エラーステートを表示
 * @param {string} containerId - コンテナのID
 * @param {string} message - エラーメッセージ
 * @param {Function} retryFn - リトライ関数
 */
function showError(containerId, message, retryFn) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = `
        <div class="error-state">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <circle cx="12" cy="12" r="10"/>
                <path d="M12 8v4m0 4h.01"/>
            </svg>
            <p>${escapeHtml(message)}</p>
            <p style="font-size:0.8rem;">しばらくしてからお試しください</p>
            ${retryFn ? '<button class="retry-btn" id="retry-' + containerId + '">再読み込み</button>' : ''}
        </div>
    `;
    if (retryFn) {
        const btn = document.getElementById('retry-' + containerId);
        if (btn) btn.addEventListener('click', retryFn);
    }
}

// テーマ初期化（フラッシュ防止のため即座実行）
(function() {
    const saved = localStorage.getItem('aura-theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
})();

// ==========================================
// フォーカストラップ — アクセシビリティ
// ==========================================

/**
 * フォーカストラップ — オーバーレイ内にTabキーフォーカスを閉じ込める
 * @param {HTMLElement} container - トラップ対象のコンテナ
 * @returns {Function} 解除関数
 */
function trapFocus(container) {
    const focusableSelector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const focusableElements = container.querySelectorAll(focusableSelector);
    if (focusableElements.length === 0) return () => {};

    const firstEl = focusableElements[0];
    const lastEl = focusableElements[focusableElements.length - 1];

    function handleKeydown(e) {
        if (e.key !== 'Tab') return;
        if (e.shiftKey) {
            if (document.activeElement === firstEl) {
                e.preventDefault();
                lastEl.focus();
            }
        } else {
            if (document.activeElement === lastEl) {
                e.preventDefault();
                firstEl.focus();
            }
        }
    }

    container.addEventListener('keydown', handleKeydown);
    // 最初のフォーカス可能要素にフォーカス
    firstEl.focus();

    return () => container.removeEventListener('keydown', handleKeydown);
}

// フォーカストラップ解除関数の保持用
let releaseDetailTrap = null;
let releaseClinicDetailTrap = null;
let releaseCompareTrap = null;

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

// SEO: ページ別タイトル・meta descriptionマッピング
const _PAGE_SEO = {
    home: {
        title: 'AURA — 美容整形の値段・リスク・口コミを徹底比較｜後悔しないクリニック選び',
        desc: '美容整形の広告価格と実際の費用のギャップ、施術ごとのリスク、1,358施設の口コミ評価を徹底比較。カウンセリング前に知っておくべき情報を、広告費ゼロの中立な立場でお届けします。',
    },
    procedures: {
        title: '施術を調べる — 広告ではわからない本当の値段・リスク・回復期間｜AURA',
        desc: '二重埋没法・脂肪吸引・ヒアルロン酸・ボトックスなど42施術の実際の費用、ダウンタイム、リスク、後悔率をデータで比較。広告に書かれていない隠れコストも掲載。',
    },
    clinics: {
        title: 'クリニックを探す — 1,358施設の口コミ・専門医・価格を比較｜AURA',
        desc: '厚労省認可の東京都内1,358施設を、Google口コミ評価・専門医在籍数・価格透明性で客観評価。広告費を一切受け取らない中立なランキング。',
    },
    doctors: {
        title: 'ドクターを探す — 専門医資格・経験年数・情報開示度で比較｜AURA',
        desc: '1,469名の美容外科医を情報開示スコアで比較。専門医資格（JSAPS/JSAS）・経験年数・勤務経歴から、信頼できる医師を探すお手伝い。',
    },
    advisor: {
        title: 'AIに相談する — 施術の費用・リスク・クリニック選びの疑問に回答｜AURA',
        desc: '二重・鼻・シミ取り・脂肪吸引など、美容医療について何でもAIに相談。特定の施術やクリニックを勧めない中立なアドバイス。',
    },
    favorites: {
        title: 'お気に入り — クリニック比較・カウンセリング準備シート｜AURA',
        desc: '気になるクリニックを保存して比較。カウンセリング準備シートの自動生成で、聞くべき質問を整理できます。',
    },
    'case-photos': {
        title: '症例写真検索 — Before/Afterで施術効果を確認｜AURA',
        desc: '大手美容クリニックの症例写真をカテゴリ・ソース別に横断検索。施術前後のリアルな仕上がりをチェックできます。',
    },
};

function navigate(pageName) {
    // SEO: ページ別タイトル・meta description動的更新
    const seo = _PAGE_SEO[pageName];
    if (seo) {
        document.title = seo.title;
        const metaDesc = document.querySelector('meta[name="description"]');
        if (metaDesc) metaDesc.setAttribute('content', seo.desc);
    }

    // ヘッダーナビの更新
    navLinks.forEach(l => l.classList.toggle('active', l.dataset.page === pageName));

    // ページの切り替え（アニメーション付き）
    const currentPage = document.querySelector('.page.active');
    const nextPage = document.getElementById(`page-${pageName}`);
    if (currentPage && nextPage && currentPage !== nextPage) {
        currentPage.classList.add('page-exit');
        setTimeout(() => {
            currentPage.classList.remove('active', 'page-exit');
            // フェードインアニメーション
            nextPage.style.opacity = '0';
            nextPage.style.transform = 'translateY(8px)';
            nextPage.classList.add('active');
            requestAnimationFrame(() => {
                nextPage.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                nextPage.style.opacity = '1';
                nextPage.style.transform = 'translateY(0)';
            });
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
    if (pageName === 'doctors' && !doctorsInitialized) initDoctors();
    if (pageName === 'favorites') renderFavorites();
    if (pageName === 'advisor') renderChatStarters();
    if (pageName === 'dashboard') renderDashboard();
    if (pageName === 'terms') renderTerms();
    if (pageName === 'privacy') renderPrivacy();
    if (pageName === 'case-photos' && !casePhotosInitialized) initCasePhotos();
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
    if (page === 'doctors' && !doctorsInitialized) initDoctors();
    if (page === 'case-photos' && !casePhotosInitialized) initCasePhotos();
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
            fadeObserver.unobserve(e.target); // 一度だけ実行
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
    el.innerHTML = renderSkeletons(3);

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
    } catch (err) {
        console.warn('価格データの取得に失敗:', err);
        showError('price-truth-list', '価格データの読み込みに失敗しました', loadHome);
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
    } catch (err) { console.warn('統計データの取得に失敗:', err); }

    // Phase 15: 施術相場セクション
    try {
        const priceData = await api('/api/procedures/market-prices');
        const mpList = document.getElementById('market-prices-home-list');
        if (mpList && priceData.market_prices && priceData.market_prices.length > 0) {
            const catLabels = { eye: '目元', nose: '鼻', contour: '輪郭', skin: '肌・美白', anti_aging: 'エイジング', body: 'ボディ', breast: '豊胸', hair_removal: '脱毛' };
            // カテゴリごとにグループ化
            const groups = {};
            priceData.market_prices.forEach(p => {
                const cat = p.category || 'other';
                if (!groups[cat]) groups[cat] = [];
                groups[cat].push(p);
            });
            let html = '<div class="market-home-grid">';
            Object.entries(groups).forEach(([cat, items]) => {
                const label = catLabels[cat] || cat;
                html += `<div class="market-home-cat"><div class="market-home-cat-title">${label}</div>`;
                items.sort((a, b) => (a.median || 0) - (b.median || 0));
                items.forEach(p => {
                    html += `<div class="market-home-item" onclick="navigate('procedures'); setTimeout(() => showDetail && showDetail('${escapeHtml(p.procedure_id)}'), 300)">
                        <span class="market-home-name">${escapeHtml(p.procedure_name.substring(0, 18))}</span>
                        <span class="market-home-median">${escapeHtml(p.median_display)}</span>
                        <span class="market-home-range">${escapeHtml(p.range_display)}</span>
                    </div>`;
                });
                html += '</div>';
            });
            html += '</div>';
            mpList.innerHTML = html;
        }
    } catch (err) { console.warn('施術相場データの取得に失敗:', err); }

    // Phase 17: エリア分析ダッシュボード
    try {
        const areaData = await api('/api/clinics/area-stats');
        const dashEl = document.getElementById('area-dashboard');
        if (dashEl && areaData.areas && areaData.areas.length > 0) {
            dashEl.innerHTML = areaData.areas.slice(0, 12).map(area => {
                const ratingColor = area.avg_rating >= 4.0 ? 'var(--success)' : area.avg_rating >= 3.5 ? 'var(--warning)' : 'var(--text-muted)';
                return `
                    <div class="area-card" onclick="navigate('clinics'); document.getElementById('clinic-area').value='${escapeHtml(area.city)}'; searchClinics()">
                        <div class="area-card-name">${escapeHtml(area.city)}</div>
                        <div class="area-card-stats">
                            <div class="area-stat">
                                <span class="area-stat-value">${area.clinic_count}</span>
                                <span class="area-stat-label">クリニック</span>
                            </div>
                            <div class="area-stat">
                                <span class="area-stat-value" style="color:${ratingColor}">${area.avg_rating ? area.avg_rating.toFixed(1) : '—'}</span>
                                <span class="area-stat-label">平均評価</span>
                            </div>
                            <div class="area-stat">
                                <span class="area-stat-value">${area.doctor_count || 0}</span>
                                <span class="area-stat-label">医師数</span>
                            </div>
                        </div>
                        ${area.jsaps_count > 0 ? `<div class="area-card-badge">JSAPS ${area.jsaps_count}名</div>` : ''}
                        ${area.red_flag_count > 3 ? `<div class="area-card-caution">注意口コミ ${area.red_flag_count}件</div>` : ''}
                    </div>
                `;
            }).join('');
        }
    } catch (err) { console.warn('エリア分析データの取得に失敗:', err); }

    // Phase 43: 信頼度の高いクリニック
    try {
        const topData = await api('/api/clinics/?grade=A&sort_by=score&per_page=6');
        const topEl = document.getElementById('top-clinics-home');
        if (topEl && topData.clinics && topData.clinics.length > 0) {
            topEl.innerHTML = topData.clinics.map(c => {
                const rating = c.google_rating ? `★ ${c.google_rating.toFixed(1)}` : '';
                const reviews = c.google_review_count ? `${c.google_review_count}件` : '';
                const gradeColor = { A: '#10b981', B: '#3b82f6', C: '#f59e0b' }[c.clinic_grade] || '#94a3b8';
                const score = c.clinic_score ? Math.round(c.clinic_score) : '';
                const summary = c.editorial_summary ? c.editorial_summary.substring(0, 60) + '…' : '';
                const chainTag = c.chain_name ? `<span class="top-clinic-chain">${escapeHtml(c.chain_name)}</span>` : '';
                return `
                    <div class="top-clinic-card" onclick="showClinicDetail('${escapeHtml(c.id)}')">
                        <div class="top-clinic-header">
                            <span class="top-clinic-grade" style="background:${gradeColor}">A</span>
                            <span class="top-clinic-score">${score}</span>
                        </div>
                        <div class="top-clinic-name">${escapeHtml(c.name)}</div>
                        <div class="top-clinic-meta">
                            ${rating ? `<span class="top-clinic-rating">${rating}</span>` : ''}
                            ${reviews ? `<span class="top-clinic-reviews">${reviews}</span>` : ''}
                            ${chainTag}
                        </div>
                        ${summary ? `<div class="top-clinic-summary">${escapeHtml(summary)}</div>` : ''}
                        <div class="top-clinic-addr">${escapeHtml(c.city || '')}</div>
                    </div>
                `;
            }).join('');
        }
    } catch (err) { console.warn('おすすめクリニックの取得に失敗:', err); }

    // Phase 43: 口コミ傾向レポート
    try {
        const reviewData = await api('/api/analysis/dashboard');
        const trendEl = document.getElementById('review-trends-home');
        if (trendEl && reviewData) {
            const rs = reviewData.review_summary || {};
            const total = rs.total || 0;
            const positive = rs.positive || 0;
            const negative = rs.negative || 0;
            const neutral = rs.neutral || 0;
            const avgSent = rs.avg_sentiment || 0;
            const redFlags = reviewData.red_flag_summary || {};

            if (total > 0) {
                const posPct = Math.round(positive / total * 100);
                const negPct = Math.round(negative / total * 100);
                const neuPct = Math.round(neutral / total * 100);

                trendEl.innerHTML = `
                    <div class="review-trend-card">
                        <div class="review-trend-title">口コミ感情分布</div>
                        <div class="review-trend-bar">
                            <div class="review-bar-pos" style="width:${posPct}%"></div>
                            <div class="review-bar-neu" style="width:${neuPct}%"></div>
                            <div class="review-bar-neg" style="width:${negPct}%"></div>
                        </div>
                        <div class="review-trend-legend">
                            <span class="review-legend-item review-legend--pos"><span class="legend-dot" style="background:#10b981"></span>ポジティブ ${posPct}%</span>
                            <span class="review-legend-item review-legend--neu"><span class="legend-dot" style="background:#a3a3a3"></span>ニュートラル ${neuPct}%</span>
                            <span class="review-legend-item review-legend--neg"><span class="legend-dot" style="background:#ef4444"></span>ネガティブ ${negPct}%</span>
                        </div>
                        <div class="review-trend-total">${total.toLocaleString()}件の口コミを分析</div>
                    </div>
                    <div class="review-trend-card">
                        <div class="review-trend-title">注意が必要な口コミ</div>
                        <div class="review-trend-stats">
                            <div class="review-stat-item">
                                <span class="review-stat-num">${redFlags.total_red_flags || 0}</span>
                                <span class="review-stat-label">レッドフラグ検出</span>
                            </div>
                            <div class="review-stat-item">
                                <span class="review-stat-num">${redFlags.clinics_with_flags || 0}</span>
                                <span class="review-stat-label">該当クリニック</span>
                            </div>
                        </div>
                        <p class="review-trend-note">施術の強引な勧誘・追加費用・術後対応に関する口コミを自動検出しています。</p>
                    </div>
                `;
            }
        }
    } catch (err) { console.warn('口コミ傾向の取得に失敗:', err); }

    // 人気の施術セクション
    renderPopularProcedures();

    // トラブル実態セクション
    renderTroubleSection();
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
        { key: 'anti_aging', label: 'エイジング' },
        { key: 'body', label: '痩身' },
        { key: 'hair_removal', label: '脱毛' },
        { key: 'breast', label: 'バスト' },
    ];
    filterEl.innerHTML = cats.map(c =>
        `<button class="filter-btn ${c.key === category ? 'active' : ''}"
                 aria-pressed="${c.key === category}"
                 onclick="loadProcs('${c.key}')">${escapeHtml(c.label)}</button>`
    ).join('');

    // スケルトンUIで読込表示（シマーアニメーション付き）
    listEl.innerHTML = renderSkeletons(4);

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
                non_invasive: '非侵襲',
                injection: '注射',
                surgical: '手術',
            }[p.invasiveness] || '';
            const invClass = {
                low: 'badge-low',
                medium: 'badge-medium',
                high: 'badge-high',
                non_invasive: 'badge-low',
                injection: 'badge-medium',
                surgical: 'badge-high',
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
                    <div class="proc-item-footer">
                        ${invLabel ? `<span class="proc-item-badge ${invClass}">${escapeHtml(invLabel)}</span>` : ''}
                        <label class="proc-compare-checkbox-label" onclick="event.stopPropagation()">
                            <input type="checkbox" class="proc-compare-checkbox" data-proc-id="${escapeHtml(p.id)}" data-proc-name="${escapeHtml(p.name)}" onchange="toggleProcCompare(this)">
                            <span>比較</span>
                        </label>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.warn('施術一覧の取得に失敗:', e);
        showError('proc-list', '施術データの読み込みに失敗しました', () => loadProcs(currentCategory));
    }
}

// ==========================================
// 施術詳細パネル
// ==========================================

async function showDetail(id) {
    const overlay = document.getElementById('detail-overlay');
    const body = document.getElementById('detail-body');
    overlay.style.display = 'flex';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    body.innerHTML = '<p class="loading-text">読み込み中</p>';
    // フォーカストラップを設定（コンテンツ読込後に再設定）
    releaseDetailTrap = trapFocus(overlay);

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

        // Phase 18: ユーザー行動コンテキストに施術閲覧を記録
        browsingContext.trackProcedure(id, p.name, p.category);

        body.innerHTML = `
            <h2 class="detail-name">${escapeHtml(p.name)}</h2>
            <p class="detail-meta">${escapeHtml(p.category_label || '')} ／ ${escapeHtml(invLabel)} ／ ${escapeHtml(p.duration || '')}</p>

            <div id="recommended-clinics-area"></div>

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
                ${p.market_price ? `
                <div class="market-price-section">
                    <div class="market-price-title">東京エリア市場価格</div>
                    <div class="market-price-stats">
                        <div class="market-price-median">
                            <span class="market-price-label">中央値</span>
                            <span class="market-price-value">${escapeHtml(p.market_price.median_display)}</span>
                        </div>
                        <div class="market-price-range">
                            <span class="market-price-label">価格帯</span>
                            <span class="market-price-value">${escapeHtml(p.market_price.range_display)}</span>
                        </div>
                    </div>
                    <div class="market-price-note">${p.market_price.sample_count}クリニックの実データから算出</div>
                </div>` : ''}
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
            \u003c/div\u003e` : ''}

            ${(() => {
                const photos = p.case_photos || [];
                if (photos.length === 0) return '';
                return `
                <div class="detail-block">
                    <div class="detail-block-title">症例写真 (${photos.length}件)</div>
                    <div class="case-photo-gallery">
                        ${photos.map(ph => `
                        <div class="case-photo-item" ${ph.source_url ? `onclick="window.open('${escapeHtml(ph.source_url)}', '_blank')" style="cursor:pointer;"` : ''}>
                            <div class="case-photo-pair">
                                <div class="case-photo-img">
                                    <span class="case-photo-label">Before</span>
                                    <img src="${escapeHtml(ph.before_image_url)}" alt="Before" loading="lazy" onerror="this.parentElement.style.display='none'">
                                </div>
                                ${ph.after_image_url ? `
                                <div class="case-photo-img">
                                    <span class="case-photo-label case-photo-label--after">After</span>
                                    <img src="${escapeHtml(ph.after_image_url)}" alt="After" loading="lazy" onerror="this.parentElement.style.display='none'">
                                </div>` : ''}
                            </div>
                            ${ph.price || ph.clinic_name ? `
                            <div class="case-photo-meta">
                                ${ph.price ? `<span class="case-photo-price">${escapeHtml(ph.price)}</span>` : ''}
                                ${ph.clinic_name ? `<span class="case-photo-clinic">${escapeHtml(ph.clinic_name)}</span>` : ''}
                            </div>` : ''}
                        </div>
                        `).join('')}
                    </div>
                </div>`;
            })()}

            <div id="timeline-section-${escapeHtml(p.id)}" class="detail-block timeline-section"></div>

            <div class="detail-block">
                <button class="find-clinics-btn" onclick="findClinicsForProcedure('${escapeHtml(p.id)}', '${escapeHtml(p.name)}')">
                    この施術のクリニックを探す
                </button>
                <div id="proc-clinic-results-${escapeHtml(p.id)}" class="proc-clinic-results"></div>
                <button class="review-advisor-link" onclick="closeDetail(); navigate('advisor'); setTimeout(() => { document.getElementById('chat-input').value='${escapeHtml(p.name)}について、費用やリスク、カウンセリングで聞くべきことを教えてください'; sendChat(); }, 300);">
                    ${escapeHtml(p.name)}についてアドバイザーに相談する
                </button>
                <button class="share-btn" onclick="shareProcedure('${escapeHtml(p.id)}', '${escapeHtml(p.name)}')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
                    リンクをコピー
                </button>
            </div>

            ${questions.length > 0 ? `
            <div class="detail-block">
                <div class="detail-block-title">カウンセリングで聞いておくこと</div>
                <div class="counseling-questions-grid">
                    ${questions.map((q, i) => `
                    <div class="counseling-q-card">
                        <span class="counseling-q-num">Q${i + 1}</span>
                        <span class="counseling-q-text">${escapeHtml(q)}</span>
                    </div>`).join('')}
                </div>
            </div>` : ''}

            ${(() => {
                const suitFor = p.suitable_for || [];
                const notSuitFor = p.not_suitable_for || [];
                if (suitFor.length === 0 && notSuitFor.length === 0) return '';
                return `
                <div class="detail-block">
                    <div class="detail-block-title">向き・不向き</div>
                    <div class="suitability-grid">
                        ${suitFor.length > 0 ? `
                        <div class="suitability-col suitability-col--good">
                            <div class="suitability-header"><span class="suitability-check"></span> こんな人に向いています</div>
                            <ul class="suitability-list">${suitFor.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>
                        </div>` : ''}
                        ${notSuitFor.length > 0 ? `
                        <div class="suitability-col suitability-col--caution">
                            <div class="suitability-header"><span class="suitability-caution"></span> こんな場合は注意</div>
                            <ul class="suitability-list">${notSuitFor.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>
                        </div>` : ''}
                    </div>
                </div>`;
            })()}

            ${p.satisfaction && typeof p.satisfaction === 'object' && p.satisfaction.rate ? `
            <div class="detail-block satisfaction-section">
                <div class="detail-block-title">この施術の満足度</div>
                <div class="satisfaction-bar-container">
                    <div class="satisfaction-bar" style="width: ${p.satisfaction.rate}%"></div>
                    <span class="satisfaction-label">${p.satisfaction.rate}% が満足</span>
                </div>
                <div class="regret-rate">
                    <span>後悔率: ${100 - p.satisfaction.rate}%</span>
                </div>
                ${p.satisfaction.common_regrets && p.satisfaction.common_regrets.length > 0 ? `
                <div class="common-regrets">
                    <h4>よくある後悔</h4>
                    <ul>
                        ${p.satisfaction.common_regrets.map(r => `<li>${escapeHtml(r)}</li>`).join('')}
                    </ul>
                </div>` : ''}
                ${p.satisfaction.regret_prevention && p.satisfaction.regret_prevention.length > 0 ? `
                <div class="regret-prevention">
                    <h4>後悔を防ぐには</h4>
                    <ul>
                        ${p.satisfaction.regret_prevention.map(r => `<li>${escapeHtml(r)}</li>`).join('')}
                    </ul>
                </div>` : ''}
                ${p.satisfaction.completion_months ? `
                <p class="completion-note">完成形までに約${p.satisfaction.completion_months}ヶ月かかります。それまでは不安になることもありますが、それは普通です。</p>` : ''}
                ${p.satisfaction.note || p.satisfaction.sample_note ? `
                <div class="satisfaction-source">
                    <span class="satisfaction-source-text">
                        ${p.satisfaction.note ? escapeHtml(p.satisfaction.note) : ''}
                        ${p.satisfaction.sample_note ? '<br>' + escapeHtml(p.satisfaction.sample_note) : ''}
                    </span>
                </div>` : ''}
            </div>` : ''}

            <div class="detail-provenance">
                <span>情報の根拠: ${escapeHtml(quality.evidence_label || quality.sources_note || '')}</span>
                ${quality.last_verified ? `<span>最終確認: ${escapeHtml(quality.last_verified.split('T')[0])}</span>` : ''}
            </div>

        `;
        // おすすめクリニックを非同期でロード
        renderRecommendedClinics(p.name);
        // タイムラインを非同期でロード
        loadTimeline(p.id);
        // Deep Linking: URLをprocedureのパスに更新
        history.replaceState({ page: 'procedures', detail: p.id }, '', `/procedures/${p.id}`);
        // コンテンツ読込完了後にフォーカストラップを再設定
        if (releaseDetailTrap) releaseDetailTrap();
        releaseDetailTrap = trapFocus(overlay);
    } catch {
        body.innerHTML = '<p class="loading-text">読み込みに失敗しました</p>';
    }
}

/**
 * おすすめクリニック推薦セクションを非同期でレンダリング
 * 施術詳細パネルの最上部に「この施術のおすすめクリニック」を表示する
 */
async function renderRecommendedClinics(procedureName) {
    const container = document.getElementById('recommended-clinics-area');
    if (!container) return;

    try {
        const res = await fetch(`/api/procedures/recommended-clinics/${encodeURIComponent(procedureName)}`);
        if (!res.ok) return;
        const data = await res.json();

        if (!data.recommended || data.recommended.length === 0) {
            container.innerHTML = '';
            return;
        }

        let html = '<div class="recommended-section">';
        html += '<h3 class="recommended-title">この施術のおすすめクリニック</h3>';
        html += '<p class="recommended-subtitle">口コミ評価・専門医資格・価格透明性の客観データに基づく推薦</p>';

        data.recommended.forEach((clinic, i) => {
            html += `
                <div class="recommended-card" onclick="showClinicDetail('${escapeHtml(clinic.clinic_id)}')">
                    <div class="recommended-rank">${i + 1}</div>
                    <div class="recommended-info">
                        <div class="recommended-name">${escapeHtml(clinic.clinic_name)}</div>
                        <div class="recommended-area">${escapeHtml(clinic.area)}</div>
                        <div class="recommended-reasons">
                            ${clinic.reasons.map(r => `<span class="reason-badge">${escapeHtml(r)}</span>`).join('')}
                        </div>
                        <div class="recommended-price">
                            ${clinic.price_range ? `${clinic.price_range.min.toLocaleString()}円 〜 ${clinic.price_range.max.toLocaleString()}円` : '価格情報なし'}
                            ${clinic.price_range && clinic.price_range.source === 'website_scrape' ? '<span class="price-source-badge price-source--official">公式</span>' : ''}
                        </div>
                    </div>
                    <div class="recommended-grade">AURA ${escapeHtml(clinic.aura_grade)}</div>
                </div>
            `;
        });

        html += `<p class="recommended-disclaimer">${escapeHtml(data.disclaimer)}</p>`;
        html += '</div>';
        container.innerHTML = html;
    } catch (err) {
        console.warn('おすすめクリニック推薦の取得に失敗:', err);
        container.innerHTML = '';
    }
}

/**
 * Phase 16: 施術特化型クリニック検索
 * 施術詳細パネルから呼び出し、その施術を提供するクリニックのランキングを表示
 */
async function findClinicsForProcedure(procId, procName) {
    const container = document.getElementById(`proc-clinic-results-${procId}`);
    if (!container) return;
    container.innerHTML = '<p class="loading-text">おすすめクリニックを分析中...</p>';

    try {
        const data = await api(`/api/procedures/${procId}/top-clinics?limit=10`);
        if (!data.clinics || data.clinics.length === 0) {
            container.innerHTML = '<p class="loading-text">この施術を提供するクリニックが見つかりませんでした</p>';
            return;
        }

        container.innerHTML = _renderProcClinicResults(data, procId, procName, 'score');
    } catch (err) {
        console.warn('施術クリニック検索に失敗:', err);
        container.innerHTML = '<p class="loading-text">検索に失敗しました</p>';
    }
}

/**
 * Phase 56: 施術クリニック検索結果のHTML生成（共通化）
 */
function _renderProcClinicResults(data, procId, procName, sortBy) {
    const sortLabel = { score: 'おすすめ', price: '価格順', rating: '評価順' }[sortBy] || 'おすすめ';

    let html = `<div class="proc-clinic-header">
        <span>${escapeHtml(procName)} — ${escapeHtml(sortLabel)}（${data.total}院中）</span>
        ${data.median_price_display ? `<span class="proc-clinic-median">相場中央値: ${escapeHtml(data.median_price_display)}</span>` : ''}
    </div>
    <div class="proc-clinic-sort" style="display:flex;gap:6px;margin:6px 0;">
        <button class="proc-sort-btn ${sortBy === 'score' ? 'proc-sort-btn--active' : ''}" onclick="sortProcClinics('${escapeHtml(procId)}','${escapeHtml(procName)}','score')">おすすめ順</button>
        <button class="proc-sort-btn ${sortBy === 'price' ? 'proc-sort-btn--active' : ''}" onclick="sortProcClinics('${escapeHtml(procId)}','${escapeHtml(procName)}','price')">価格順</button>
        <button class="proc-sort-btn ${sortBy === 'rating' ? 'proc-sort-btn--active' : ''}" onclick="sortProcClinics('${escapeHtml(procId)}','${escapeHtml(procName)}','rating')">評価順</button>
    </div>`;

    html += data.clinics.map(c => {
        const gradeColors = { A: '#10b981', B: '#3b82f6', C: '#f59e0b', D: '#f97316', E: '#94a3b8' };
        const gradeBadge = c.clinic_grade ? `<span class="clinic-grade-badge" style="--grade-color: ${gradeColors[c.clinic_grade] || '#94a3b8'}">${c.clinic_grade}</span>` : '';
        const chainLabel = c.chain_name ? `<span class="proc-clinic-chain">${escapeHtml(c.chain_name)}</span>` : '';

        // Phase 56: 医師情報 + Phase 67: 専門性マッチバッジ
        let doctorHtml = '';
        if (c.top_doctor) {
            const d = c.top_doctor;
            const certBadge = d.has_certification ? '<span class="proc-clinic-doctor-badge">専門医</span>' : '';
            const expLabel = d.experience_years ? `<span class="proc-clinic-doctor-exp">経験${d.experience_years}年</span>` : '';
            // Phase 67: 専門性マッチバッジ
            let specBadge = '';
            if (d.specialty_match >= 0.8) {
                specBadge = `<span class="specialty-match-badge specialty-match-badge--high">${escapeHtml(d.specialty_match_label || '専門分野一致')}</span>`;
            } else if (d.specialty_match >= 0.5) {
                specBadge = `<span class="specialty-match-badge specialty-match-badge--medium">${escapeHtml(d.specialty_match_label || '関連分野')}</span>`;
            }
            doctorHtml = `<div class="proc-clinic-doctor">
                <svg class="proc-clinic-doctor-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                <span class="proc-clinic-doctor-name">${escapeHtml(d.name)}</span>
                ${certBadge}${specBadge}${expLabel}
            </div>`;
        }

        // Phase 56: 相場対比ラベル
        let marketHtml = '';
        if (c.market_context) {
            const mc = c.market_context;
            const isAffordable = mc.ratio !== null && mc.ratio < 1.0;
            const mcClass = isAffordable ? 'proc-clinic-market--affordable' : 'proc-clinic-market--high';
            const mcLabel = escapeHtml(mc.label);
            marketHtml = `<span class="proc-clinic-market ${mcClass}">${mcLabel}</span>`;
        }

        return `<div class="proc-clinic-row" onclick="closeDetail(); setTimeout(() => showClinicDetail('${escapeHtml(c.clinic_id)}'), 200)">
            <span class="proc-clinic-rank">${c.rank}</span>
            <div class="proc-clinic-info">
                <span class="proc-clinic-name">${gradeBadge}${escapeHtml(c.name)}</span>
                <span class="proc-clinic-city">${escapeHtml(c.city || '')}${chainLabel}</span>
                ${doctorHtml}
            </div>
            <div class="proc-clinic-price-area">
                ${c.price_display ? `<span class="proc-clinic-price">${escapeHtml(c.price_display)}</span>` : '<span class="proc-clinic-price">—</span>'}
                ${_priceSourceBadge(c.price_source || c.data_source)}
                ${marketHtml}
            </div>
            ${c.google_rating ? `<span class="proc-clinic-rating">★${c.google_rating.toFixed(1)}</span>` : ''}
        </div>`;
    }).join('');

    return html;
}

/**
 * 施術クリニックランキングのソート切替
 */
async function sortProcClinics(procId, procName, sortBy) {
    const container = document.getElementById(`proc-clinic-results-${procId}`);
    if (!container) return;
    container.innerHTML = '<p class="loading-text">並べ替え中...</p>';
    try {
        const data = await api(`/api/procedures/${procId}/top-clinics?sort_by=${sortBy}&limit=10`);
        container.innerHTML = _renderProcClinicResults(data, procId, procName, sortBy);
    } catch (err) {
        console.warn('ソート変更に失敗:', err);
    }
}

document.getElementById('detail-close').addEventListener('click', () => {
    if (releaseDetailTrap) { releaseDetailTrap(); releaseDetailTrap = null; }
    document.getElementById('detail-overlay').style.display = 'none';
});
document.getElementById('detail-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) {
        if (releaseDetailTrap) { releaseDetailTrap(); releaseDetailTrap = null; }
        e.currentTarget.style.display = 'none';
    }
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
    } catch (err) { console.warn('クリニック統計の取得に失敗:', err); }
    searchClinics();
}

async function searchClinics(page = 1) {
    const q = document.getElementById('clinic-q').value;
    const area = document.getElementById('clinic-area').value;
    const dept = document.getElementById('clinic-dept').value;
    const grade = document.getElementById('clinic-grade')?.value || '';
    const sort = document.getElementById('clinic-sort').value;
    const listEl = document.getElementById('clinic-list');
    const pagerEl = document.getElementById('clinic-pager');

    // スケルトンUIで検索中表示（シマーアニメーション付き）
    listEl.innerHTML = renderSkeletons(5);

    const params = new URLSearchParams({ page, per_page: 15, sort_by: sort });
    if (q) params.set('q', q);
    if (area) params.set('city', area);
    // Phase 18: エリア検索をコンテキストに記録
    if (area) browsingContext.trackArea(area);
    if (dept) params.set('department', dept);
    if (grade) params.set('grade', grade);

    // Phase 61: 予算フィルタ
    const priceRange = document.getElementById('clinic-price-range')?.value || '';
    if (priceRange) {
        const [pMin, pMax] = priceRange.split('-');
        if (pMin) params.set('price_min', pMin);
        if (pMax) params.set('price_max', pMax);
    }

    try {
        const data = await api(`/api/clinics/?${params}`);
        const clinics = data.clinics || [];

        // Phase 49: マップ用にデータ保存
        lastClinicSearchData = clinics;
        if (currentClinicView === 'map') {
            renderClinicMapMarkers(clinics);
        }

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
            // データ充実度: 口コミデータがない場合の表示改善
            const dc = c.data_completeness || {};
            const noGoogleLabel = !c.google_rating
                ? (dc.has_google_reviews === false
                    ? '<span class="no-review-notice">口コミデータなし</span>'
                    : '<span class="clinic-tag clinic-tag--muted">厚労省データ</span>')
                : '';

            // 透明性スコアバッジ
            let transparencyBadge = '';
            if (c.transparency_score && c.transparency_score >= 40) {
                const level = c.transparency_score >= 70 ? 'high' : c.transparency_score >= 50 ? 'mid' : 'low';
                transparencyBadge = `<span class="transparency-badge transparency-badge--${level}">透明性 ${Math.round(c.transparency_score)}</span>`;
            }

            // サムネイル画像（Google写真がある場合）
            const thumbHtml = c.thumbnail_ref
                ? `<div class="clinic-item-thumb"><img src="/api/clinics/${escapeHtml(c.id)}/photo?ref=${encodeURIComponent(c.thumbnail_ref)}&maxwidth=200" alt="${escapeHtml(c.name)}の写真" loading="lazy" class="clinic-item-thumb-img"></div>`
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

            // クリニックグレードバッジ
            let gradeBadge = '';
            if (c.clinic_grade) {
                const gradeColors = { A: '#10b981', B: '#3b82f6', C: '#f59e0b', D: '#f97316', E: '#94a3b8' };
                const gradeLabels = { A: '情報充実', B: '情報良好', C: '標準', D: 'やや不足', E: '収集中' };
                gradeBadge = `<span class="clinic-grade-badge" style="--grade-color: ${gradeColors[c.clinic_grade] || '#94a3b8'}" title="${gradeLabels[c.clinic_grade] || ''}">${c.clinic_grade}</span>`;
            }

            // チェーン名タグ
            const chainTag = c.chain_name ? `<span class="clinic-tag clinic-tag--chain">${escapeHtml(c.chain_name)}</span>` : '';

            // 一般診療タグ（美容クリニックでない場合に表示）
            const generalTag = (c.is_beauty_only === false && depts.length > 0) ? '<span class="clinic-tag clinic-tag--general">一般診療も対応</span>' : '';

            return `
                <div class="clinic-item${hasThumb}" onclick="showClinicDetail('${escapeHtml(c.id)}')">
                    ${favBtn}
                    ${compareCheckbox}
                    ${thumbHtml}
                    <div class="clinic-item-content">
                        <div class="clinic-item-header">
                            <div class="clinic-item-name">${gradeBadge}${escapeHtml(c.name)}</div>
                            <div class="clinic-item-score-area">
                                ${c.clinic_score ? `<span class="clinic-item-score">${Math.round(c.clinic_score)}</span>` : ''}
                                ${rating || reviews ? `<div class="clinic-item-rating">${rating}${reviews}</div>` : ''}
                            </div>
                        </div>
                        <div class="clinic-item-addr">${escapeHtml(c.address || c.city || '')}</div>
                        <div class="clinic-item-tags">${chainTag}${generalTag}${tags}${noGoogleLabel}${transparencyBadge}${renderTrendMini(c.recent_trend)}</div>
                        ${c.editorial_summary ? `<div class="clinic-item-summary">${escapeHtml(c.editorial_summary.substring(0, 80))}${c.editorial_summary.length > 80 ? '…' : ''}</div>` : ''}
                    </div>
                </div>
            `;
        }).join('');

        // ページャー — nav要素で囲みアクセシビリティ向上
        const totalPages = data.total_pages || 1;
        if (totalPages > 1) {
            let btns = '';
            if (page > 1) btns += `<button class="pager-btn" onclick="searchClinics(${page-1})">前へ</button>`;
            for (let p = Math.max(1, page-2); p <= Math.min(totalPages, page+2); p++) {
                btns += `<button class="pager-btn ${p===page?'active':''}" onclick="searchClinics(${p})">${p}</button>`;
            }
            if (page < totalPages) btns += `<button class="pager-btn" onclick="searchClinics(${page+1})">次へ</button>`;
            pagerEl.innerHTML = `<nav aria-label="ページネーション">${btns}</nav>`;
        } else {
            pagerEl.innerHTML = '';
        }
    } catch (err) {
        console.warn('クリニック検索に失敗:', err);
        showError('clinic-list', 'クリニックの検索に失敗しました', () => searchClinics(page));
    }
}

document.getElementById('clinic-search-btn').addEventListener('click', () => searchClinics(1));
document.getElementById('clinic-q').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') searchClinics(1);
});
// テキスト入力にデバウンス付き検索（500ms）——不要なAPIリクエストを削減
let clinicSearchDebounce = null;
document.getElementById('clinic-q').addEventListener('input', () => {
    clearTimeout(clinicSearchDebounce);
    clinicSearchDebounce = setTimeout(() => searchClinics(1), 500);
});

// Phase 49: マップビュー
let clinicMap = null;
let clinicClusterGroup = null;
let currentClinicView = 'list';
let lastClinicSearchData = null;

function switchClinicView(view) {
    currentClinicView = view;
    const listEl = document.getElementById('clinic-list');
    const mapEl = document.getElementById('clinic-map-container');
    const listBtn = document.getElementById('view-list-btn');
    const mapBtn = document.getElementById('view-map-btn');

    if (view === 'map') {
        listEl.style.display = 'none';
        mapEl.style.display = '';
        listBtn.classList.remove('view-toggle-btn--active');
        mapBtn.classList.add('view-toggle-btn--active');
        initClinicMap();
        if (lastClinicSearchData) {
            renderClinicMapMarkers(lastClinicSearchData);
        }
    } else {
        listEl.style.display = '';
        mapEl.style.display = 'none';
        listBtn.classList.add('view-toggle-btn--active');
        mapBtn.classList.remove('view-toggle-btn--active');
    }
}

function initClinicMap() {
    if (clinicMap) return;
    // 東京都中心（新宿あたり）
    clinicMap = L.map('clinic-map').setView([35.6895, 139.6917], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 18,
    }).addTo(clinicMap);

    // Phase 51: マーカークラスタグループを初期化
    clinicClusterGroup = L.markerClusterGroup({
        maxClusterRadius: 50,
        spiderfyOnMaxZoom: true,
        showCoverageOnHover: false,
        disableClusteringAtZoom: 16,
    });
    clinicMap.addLayer(clinicClusterGroup);

    // マップのサイズが正しく計算されない場合に再描画
    setTimeout(() => clinicMap.invalidateSize(), 200);
}

function renderClinicMapMarkers(clinics) {
    if (!clinicMap || !clinicClusterGroup) return;

    // 既存マーカーをクリア
    clinicClusterGroup.clearLayers();

    const gradeColors = { A: '#10b981', B: '#3b82f6', C: '#f59e0b', D: '#f97316', E: '#94a3b8' };
    const bounds = [];

    clinics.forEach(c => {
        if (!c.lat || !c.lng) return;
        const color = gradeColors[c.clinic_grade] || '#94a3b8';
        const icon = L.divIcon({
            className: 'map-clinic-marker',
            html: `<div style="background:${color};width:12px;height:12px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.3)"></div>`,
            iconSize: [16, 16],
            iconAnchor: [8, 8],
        });

        const rating = c.google_rating ? `★ ${c.google_rating.toFixed(1)}` : '';
        const score = c.clinic_score ? `スコア ${Math.round(c.clinic_score)}` : '';
        const grade = c.clinic_grade ? `<span style="background:${color};color:#fff;padding:1px 4px;border-radius:3px;font-size:10px;font-weight:700">${c.clinic_grade}</span>` : '';

        const popup = L.popup({ maxWidth: 220 }).setContent(`
            <div style="font-family:var(--font);font-size:12px;line-height:1.4">
                <div style="font-weight:600;margin-bottom:3px">${grade} ${c.name}</div>
                <div style="color:#666;font-size:11px">${c.city || ''}</div>
                <div style="margin-top:4px">${rating} ${score}</div>
                <button onclick="showClinicDetail('${c.id}')" style="margin-top:6px;padding:4px 10px;background:#8B6914;color:#fff;border:none;border-radius:4px;font-size:11px;cursor:pointer">詳細を見る</button>
            </div>
        `);

        const marker = L.marker([c.lat, c.lng], { icon }).bindPopup(popup);
        clinicClusterGroup.addLayer(marker);
        bounds.push([c.lat, c.lng]);
    });

    // 全マーカーが見えるよう調整
    if (bounds.length > 0) {
        clinicMap.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 });
    }
}

// ==========================================
// クリニック検索サジェスト
// ==========================================

let suggestTimeout = null;
const clinicInput = document.getElementById('clinic-q');
if (clinicInput) {
    clinicInput.addEventListener('input', (e) => {
        clearTimeout(suggestTimeout);
        const q = e.target.value.trim();
        if (q.length < 2) {
            hideSuggestions();
            return;
        }
        suggestTimeout = setTimeout(async () => {
            try {
                const resp = await fetch(`/api/clinics/suggest?q=${encodeURIComponent(q)}`);
                const data = await resp.json();
                showSuggestions(data.suggestions);
            } catch (err) {
                console.warn('サジェスト取得エラー:', err);
            }
        }, 300);
    });
}

/**
 * サジェストドロップダウンを表示する
 * @param {Array} items - サジェスト候補の配列
 */
function showSuggestions(items) {
    let container = document.getElementById('search-suggestions');
    if (!container) {
        container = document.createElement('div');
        container.id = 'search-suggestions';
        container.className = 'search-suggestions';
        const inputField = document.getElementById('clinic-q');
        inputField.parentElement.style.position = 'relative';
        inputField.parentElement.appendChild(container);
    }
    if (items.length === 0) {
        hideSuggestions();
        return;
    }
    container.innerHTML = items.map(item =>
        `<button class="suggest-item" data-id="${escapeHtml(item.id)}">
            <span class="suggest-name">${escapeHtml(item.name)}</span>
            <span class="suggest-addr">${escapeHtml(item.address || '')}</span>
        </button>`
    ).join('');
    container.style.display = 'block';
    container.querySelectorAll('.suggest-item').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById('clinic-q').value = btn.querySelector('.suggest-name').textContent;
            hideSuggestions();
            document.getElementById('clinic-search-btn').click();
        });
    });
}

/**
 * サジェストドロップダウンを非表示にする
 */
function hideSuggestions() {
    const container = document.getElementById('search-suggestions');
    if (container) container.style.display = 'none';
}

// 外側クリックでサジェストを閉じる
document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-row')) hideSuggestions();
});

// ==========================================
// クリニック詳細パネル
// ==========================================

async function showClinicDetail(id) {
    const overlay = document.getElementById('clinic-detail-overlay');
    const body = document.getElementById('clinic-detail-body');
    overlay.style.display = 'flex';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    body.innerHTML = '<p class="loading-text">読み込み中</p>';
    // フォーカストラップを設定
    releaseClinicDetailTrap = trapFocus(overlay);

    try {
        const c = await api(`/api/clinics/${id}`);

        // Phase 18: ユーザー行動コンテキストにクリニック閲覧を記録
        browsingContext.trackClinic(id, c.name, c.city);

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
        } else {
            ratingHtml = `<div class="clinic-detail-rating"><span class="no-review-notice">Google口コミデータがありません</span></div>`;
        }

        // データ充実度バッジ
        const dc = c.data_completeness || {};
        const dcLevelLabels = { high: 'データ充実', medium: '一部データなし', low: 'データ収集中' };
        const dcLabel = dcLevelLabels[dc.level] || '';
        const dataCompletenessBadgeHtml = dcLabel
            ? `<div class="data-completeness-badge data-completeness--${escapeHtml(dc.level)}">${escapeHtml(dcLabel)}</div>`
            : '';

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

        // AURA総合スコアブレークダウン
        let clinicScoreHtml = '';
        if (c.clinic_score && c.clinic_grade) {
            const cs = c.clinic_score;
            const cg = c.clinic_grade;
            const gradeColors = { A: '#10b981', B: '#3b82f6', C: '#f59e0b', D: '#f97316', E: '#94a3b8' };
            const gradeLabels = { A: '情報充実', B: '情報良好', C: '標準', D: 'やや不足', E: '収集中' };
            const gc = gradeColors[cg] || '#94a3b8';

            // スコアブレークダウン（APIから取得できない場合はスコアから推定）
            const bd = c.clinic_score_breakdown || {};
            const axes = [
                { key: 'transparency', label: '情報透明性', max: 20, icon: 'T' },
                { key: 'review_quality', label: '口コミ評価', max: 25, icon: 'R' },
                { key: 'red_flag_penalty', label: 'リスク指標', max: 25, icon: 'F' },
                { key: 'doctor_quality', label: '医師品質', max: 20, icon: 'D' },
                { key: 'freshness', label: 'データ鮮度', max: 10, icon: 'N' },
            ];

            const axisHtml = axes.map(a => {
                const val = bd[a.key] ?? 0;
                const pct = Math.round(val / a.max * 100);
                return `<div class="score-axis-row">
                    <span class="score-axis-icon score-axis-icon--letter">${a.icon}</span>
                    <span class="score-axis-label">${a.label}</span>
                    <div class="score-axis-bar">
                        <div class="score-axis-fill" style="width:${pct}%; background:${gc}"></div>
                    </div>
                    <span class="score-axis-val">${Math.round(val)}/${a.max}</span>
                </div>`;
            }).join('');

            // データ不足時の注記
            const dcLevel = (c.data_completeness || {}).level;
            const dataShortageNote = (dcLevel === 'low' || dcLevel === 'medium')
                ? '<p class="clinic-score-note clinic-score-note--shortage">※ データ不足のため低い可能性があります</p>'
                : '';

            clinicScoreHtml = `
                <div class="detail-block">
                    <div class="detail-block-title">AURA クリニックスコア <span class="score-info-tooltip">情報充実度</span></div>
                    <div class="clinic-score-overview">
                        <div class="clinic-score-big" style="--grade-color: ${gc}">
                            <span class="clinic-score-grade">${cg}</span>
                            <span class="clinic-score-num">${Math.round(cs)}</span>
                            <span class="clinic-score-max">/100</span>
                        </div>
                        <span class="clinic-score-label">${escapeHtml(gradeLabels[cg] || '')}</span>
                    </div>
                    <div class="clinic-score-axes">${axisHtml}</div>
                    <p class="clinic-score-note">客観データのみに基づく評価です。広告・提携要素は含みません。</p>
                    ${dataShortageNote}
                </div>`;
        }

        // 医師情報（リッチカード表示）
        let doctorsHtml = '';
        const doctors = c.doctors || [];
        if (doctors.length > 0) {
            const docItems = doctors.slice(0, 8).map(d => {
                // 資格バッジ
                const certs = d.certifications || [];
                const certBadges = certs.slice(0, 3).map(cert => `<span class="doctor-cert">${escapeHtml(cert)}</span>`).join('');

                // JSAPSバッジ
                const jsapsBadge = d.jsaps_certified ? '<span class="doctor-cert doctor-cert--jsaps">JSAPS専門医</span>' : '';

                // 経験年数
                const expHtml = d.experience_years
                    ? `<div class="doctor-meta-item">経験 ${d.experience_years}年</div>`
                    : '';

                // 勤務経歴
                const bgHtml = d.hospital_background
                    ? `<div class="doctor-meta-item"><span class="doctor-meta-icon doctor-meta-icon--text">経歴</span> ${escapeHtml(d.hospital_background.substring(0, 40))}</div>`
                    : '';

                // 情報開示スコア
                let scoreHtml = '';
                if (d.trust_score !== null && d.trust_score !== undefined) {
                    if (d.trust_score >= 30) {
                        const color = d.trust_score >= 70 ? '#4CAF50' : d.trust_score >= 50 ? '#2196F3' : '#FF9800';
                        scoreHtml = `<div class="doctor-detail-score" style="--doc-color:${color}">
                            <span class="doctor-detail-score-num">${Math.round(d.trust_score)}</span>
                            <span class="doctor-detail-score-label">${escapeHtml(d.trust_level || '')}</span>
                        </div>`;
                    } else if (d.trust_score >= 20) {
                        scoreHtml = `<div class="doctor-detail-score doctor-detail-score--low">
                            <span class="doctor-detail-score-label">情報限定</span>
                        </div>`;
                    }
                }

                // 専門分野
                const specs = d.specialties || [];
                const specHtml = specs.length > 0
                    ? `<div class="doctor-meta-item"><span class="doctor-meta-icon">⚕️</span> ${escapeHtml(specs.slice(0, 3).join(' / '))}</div>`
                    : '';

                return `<div class="doctor-card-detail" onclick="showDoctorDetail('${escapeHtml(d.id || '')}')" style="cursor:pointer;">
                    <div class="doctor-card-header">
                        <div class="doctor-card-identity">
                            <span class="doctor-title">${escapeHtml(d.title || '医師')}</span>
                            <span class="doctor-name">${escapeHtml(d.name)}</span>
                        </div>
                        ${scoreHtml}
                    </div>
                    <div class="doctor-card-certs">${jsapsBadge}${certBadges}</div>
                    <div class="doctor-card-meta">
                        ${expHtml}${bgHtml}${specHtml}
                    </div>
                </div>`;
            }).join('');
            const moreCount = doctors.length > 8 ? `<div class="doctor-more">他 ${doctors.length - 8}名</div>` : '';
            doctorsHtml = `
                <div class="detail-block">
                    <div class="detail-block-title">在籍医師 <span class="detail-count">${doctors.length}名</span></div>
                    ${docItems}${moreCount}
                </div>`;
        }

        // 施術メニュー
        let proceduresHtml = '';
        const procs = c.procedures || [];
        if (procs.length > 0) {
            const procItems = procs.slice(0, 8).map(p => {
                const price = p.price_advertised ? `¥${Number(p.price_advertised).toLocaleString()}〜` : '';
                // 価格ソースバッジ（推定値/公式/推論を区別）
                const sourceBadge = _priceSourceBadge(p.price_source || p.source);
                // Phase 15: 相場対比バッジ
                let marketBadge = '';
                if (p.market_context) {
                    const mc = p.market_context;
                    const badgeClass = mc.label === 'お手頃' ? 'market-badge--affordable' :
                                       mc.label === '平均的' ? 'market-badge--average' :
                                       mc.label === 'やや高め' ? 'market-badge--high' : 'market-badge--premium';
                    marketBadge = `<span class="market-badge ${badgeClass}">${escapeHtml(mc.label)}</span>`;
                }
                return `<div class="proc-menu-item">
                    <span class="proc-menu-name">${escapeHtml(p.name)}</span>
                    <div class="proc-menu-right">
                        ${price ? `<span class="proc-menu-price">${escapeHtml(price)}</span>` : ''}
                        ${sourceBadge}
                        ${marketBadge}
                    </div>
                </div>`;
            }).join('');
            const moreProcs = procs.length > 8 ? `<div class="doctor-more">他 ${procs.length - 8}件</div>` : '';
            proceduresHtml = `
                <div class="detail-block">
                    <div class="detail-block-title">対応施術 <span class="detail-count">${procs.length}件</span></div>
                    ${procItems}${moreProcs}
                </div>`;
        }

        body.innerHTML = `
            ${photoHtml}
            <h2 class="detail-name">${escapeHtml(c.name)}</h2>
            ${c.branch_name ? `<p class="clinic-detail-branch">${escapeHtml(c.branch_name)}</p>` : ''}
            ${dataCompletenessBadgeHtml}
            ${ratingHtml}
            ${gmapsHtml}
            <p class="clinic-detail-addr">${escapeHtml(c.address)}</p>
            <div class="clinic-detail-depts">${deptTags}</div>

            ${c.editorial_summary ? `<p class="clinic-detail-summary">${escapeHtml(c.editorial_summary)}</p>` : ''}

            ${c.chain_name ? `<div class="clinic-detail-chain"><span class="clinic-tag clinic-tag--chain">${escapeHtml(c.chain_name)}</span></div>` : ''}

            ${transparencyHtml}
            ${clinicScoreHtml}
            ${doctorsHtml}
            ${proceduresHtml}
            ${(() => {
                const casePhotos = c.case_photos || [];
                if (casePhotos.length === 0) return '';
                return `
                <div class="detail-block">
                    <div class="detail-block-title">症例写真 <span class="detail-count">${c.case_photo_count || casePhotos.length}件</span></div>
                    <div class="case-photo-gallery">
                        ${casePhotos.map(ph => `
                        <div class="case-photo-item" ${ph.source_url ? `onclick="window.open('${escapeHtml(ph.source_url)}', '_blank')" style="cursor:pointer;"` : ''}>
                            <div class="case-photo-pair">
                                <div class="case-photo-img">
                                    <span class="case-photo-label">Before</span>
                                    <img src="${escapeHtml(ph.before_image_url)}" alt="Before" loading="lazy" onerror="this.parentElement.style.display='none'">
                                </div>
                                ${ph.after_image_url ? `
                                <div class="case-photo-img">
                                    <span class="case-photo-label case-photo-label--after">After</span>
                                    <img src="${escapeHtml(ph.after_image_url)}" alt="After" loading="lazy" onerror="this.parentElement.style.display='none'">
                                </div>` : ''}
                            </div>
                            <div class="case-photo-meta">
                                ${ph.procedure_name ? `<span class="case-photo-proc">${escapeHtml(ph.procedure_name)}</span>` : ''}
                                ${ph.price ? `<span class="case-photo-price">${escapeHtml(ph.price)}</span>` : ''}
                            </div>
                        </div>
                        `).join('')}
                    </div>
                </div>`;
            })()}
            ${(() => {
                const rs = c.review_summary;
                if (!rs || rs.total === 0) {
                    // 口コミがない場合の明示表示
                    const dcInfo = c.data_completeness || {};
                    if (dcInfo.has_google_reviews === false) {
                        return '<div class="detail-block"><div class="detail-block-title">口コミ分析</div><p class="no-review-notice no-review-notice--block">口コミデータがありません。Google Mapsでの評価が見つからなかったクリニックです。</p></div>';
                    }
                    return '';
                }
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

                // 星分布バー
                const sd = rs.star_distribution || {};
                const totalRated = Object.values(sd).reduce((a,b) => a + b, 0);
                let starDistHtml = '';
                if (totalRated > 0) {
                    const avgR = rs.avg_rating || 0;
                    const avgStars = '★'.repeat(Math.round(avgR)) + '☆'.repeat(5 - Math.round(avgR));
                    starDistHtml = `<div class="star-dist-section">
                        <div class="star-dist-header">
                            <div class="star-dist-avg">
                                <span class="star-dist-avg-num">${avgR}</span>
                                <div class="star-dist-avg-stars">${avgStars}</div>
                                <span class="star-dist-avg-count">${totalRated}件の評価</span>
                            </div>
                            <div class="star-dist-bars">
                                ${[5,4,3,2,1].map(n => {
                                    const cnt = sd[n] || 0;
                                    const pct = Math.round(cnt / totalRated * 100);
                                    return `<div class="star-dist-row">
                                        <span class="star-dist-label">${n}</span>
                                        <div class="star-dist-bar"><div class="star-dist-fill star-dist-fill--${n}" style="width:${pct}%"></div></div>
                                        <span class="star-dist-count">${cnt}</span>
                                    </div>`;
                                }).join('')}
                            </div>
                        </div>
                    </div>`;
                }

                return `<div class="detail-block">
                    <div class="detail-block-title">口コミ分析 <span style="font-size:0.7rem;color:${sentColor};font-weight:600;margin-left:0.5rem;">${sentLabel}</span></div>
                    ${starDistHtml}
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
                    ${(() => {
                        const trend = rs.recent_trend;
                        if (!trend) return '';
                        return renderTrendBadge(trend);
                    })()}
                    ${(() => {
                        const flags = rs.red_flags;
                        if (!flags || Object.keys(flags).length === 0) return '';
                        const flagLabels = {
                            pressure_sales: {label: '圧力販売の報告'},
                            treatment_trouble: {label: '施術トラブルの報告'},
                            staff_issue: {label: 'スタッフ対応の問題'},
                            billing_issue: {label: '会計トラブルの報告'},
                        };
                        const flagItems = Object.entries(flags).map(([cat, count]) => {
                            const info = flagLabels[cat] || {label: cat};
                            return `<div class="red-flag-item">${info.label}（${count}件）</div>`;
                        }).join('');
                        return `<div class="red-flag-section">
                            <div class="red-flag-title">注意情報</div>
                            ${flagItems}
                        </div>`;
                    })()}
                    <div style="font-size:0.68rem;color:var(--text-muted);margin-top:0.4rem;">Google口コミ ${rs.total}件の感情分析${rs.avg_quality ? ` / 平均品質: ${Math.round(rs.avg_quality)}pt` : ''}</div>
                </div>`;
            })()}
            ${(() => {
                const revs = c.reviews || [];
                if (revs.length === 0) return '';

                // ユニークIDを生成（DOM操作用）
                const blockId = `rev-block-${Date.now()}`;
                const initialShow = 5;

                const revItems = revs.map((r, idx) => {
                    const stars = r.rating ? '★'.repeat(Math.round(r.rating)) + '☆'.repeat(5 - Math.round(r.rating)) : '';
                    const starVal = r.rating ? Math.round(r.rating) : 0;
                    const fullText = escapeHtml(r.text || '');
                    const truncLen = 80;
                    const needsTruncate = fullText.length > truncLen;
                    const shortText = needsTruncate ? fullText.slice(0, truncLen) + '...' : fullText;
                    const revId = `review-${Date.now()}-${idx}`;

                    let qualityBadge = '';
                    if (r.quality_score !== null && r.quality_score !== undefined) {
                        if (r.quality_score >= 70) {
                            qualityBadge = '<span class="review-quality review-quality--high">信頼性高</span>';
                        } else if (r.quality_score < 30) {
                            qualityBadge = '<span class="review-quality review-quality--low">参考程度</span>';
                        }
                    }

                    const flagLabels = {pressure_sales:'圧力販売', treatment_trouble:'施術トラブル', staff_issue:'対応問題', billing_issue:'会計問題'};
                    const flagTags = (r.red_flags || []).map(f => `<span class="review-flag-tag">${flagLabels[f.category] || f.category}</span>`).join('');
                    const dateHtml = r.date ? `<span class="review-date">${escapeHtml(r.date)}</span>` : '';

                    const hiddenClass = idx >= initialShow ? ' review-item--hidden' : '';

                    return `<div class="review-item${hiddenClass}" data-stars="${starVal}">
                        <div class="review-header">
                            <span class="review-stars">${stars}</span>
                            <span class="review-author">${escapeHtml(r.author || '')}</span>
                            ${dateHtml}
                            ${qualityBadge}
                        </div>
                        ${flagTags ? `<div class="review-flags">${flagTags}</div>` : ''}
                        <div class="review-text" id="${revId}-short">${shortText}${needsTruncate ? ` <button class="review-expand-btn" onclick="document.getElementById('${revId}-short').style.display='none'; document.getElementById('${revId}-full').style.display='block';">続きを読む</button>` : ''}</div>
                        ${needsTruncate ? `<div class="review-text" id="${revId}-full" style="display:none;">${fullText} <button class="review-expand-btn" onclick="document.getElementById('${revId}-full').style.display='none'; document.getElementById('${revId}-short').style.display='block';">閉じる</button></div>` : ''}
                    </div>`;
                }).join('');

                // フィルタボタン
                const filterHtml = `<div class="review-filter-bar" id="${blockId}-filter">
                    <button class="review-filter-btn review-filter-btn--active" data-star="0" onclick="filterReviews('${blockId}', 0, this)">全て</button>
                    ${[5,4,3,2,1].map(n => `<button class="review-filter-btn" data-star="${n}" onclick="filterReviews('${blockId}', ${n}, this)">★${n}</button>`).join('')}
                </div>`;

                // もっと見るボタン
                const moreBtn = revs.length > initialShow ? `<button class="review-more-btn" id="${blockId}-more" onclick="showMoreReviews('${blockId}', this)">残り${revs.length - initialShow}件を表示</button>` : '';

                // アドバイザー導線
                const advisorLink = `<button class="review-advisor-link" onclick="document.getElementById('clinic-detail-overlay').style.display='none'; document.body.style.overflow=''; navigate('advisor'); setTimeout(() => { document.getElementById('chat-input').value='${escapeHtml(c.name)}の口コミについて詳しく教えてください'; sendChat(); }, 300);">この口コミについてアドバイザーに相談する</button>`;

                return `<div class="detail-block" id="${blockId}">
                    <div class="detail-block-title">口コミ <span class="review-count-badge">${revs.length}件</span></div>
                    ${filterHtml}
                    <div class="review-list" id="${blockId}-list">
                        ${revItems}
                    </div>
                    ${moreBtn}
                    ${advisorLink}
                </div>`;
            })()}
            ${infoHtml}
            ${hoursHtml}
            ${mapHtml}

            <div class="detail-provenance">
                ${provItems.map(p => `<span>${p}</span>`).join('')}
            </div>

            <div id="review-summary-${escapeHtml(c.id)}" class="detail-block review-summary-section"></div>

            <div id="similar-clinics-${escapeHtml(c.id)}" class="similar-clinics-section"></div>

            <button class="share-btn" onclick="shareClinic('${escapeHtml(c.id)}', '${escapeHtml(c.name)}')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
                リンクをコピー
            </button>
        `;
        // 口コミ要約を非同期でロード
        loadReviewSummary(c.id);
        // Phase 55: 類似クリニックを非同期でロード
        loadSimilarClinics(c.id);
        // Phase 63: 構造化データ(JSON-LD)を非同期で埋め込み
        injectClinicJsonLd(c.id);
        // Deep Linking: URLをclinicのパスに更新
        history.replaceState({ page: 'clinics', detail: c.id }, '', `/clinics/${c.id}`);
        // コンテンツ読込完了後にフォーカストラップを再設定
        if (releaseClinicDetailTrap) releaseClinicDetailTrap();
        releaseClinicDetailTrap = trapFocus(overlay);
    } catch (e) {
        body.innerHTML = '<p class="loading-text">クリニック情報の取得に失敗しました</p>';
    }
}

/**
 * 口コミを星評価でフィルタ
 * @param {string} blockId - 口コミブロックのID
 * @param {number} star - フィルタする星数（0=全て）
 * @param {HTMLElement} btn - クリックされたボタン
 */
function filterReviews(blockId, star, btn) {
    const list = document.getElementById(`${blockId}-list`);
    const moreBtn = document.getElementById(`${blockId}-more`);
    if (!list) return;

    // ボタンのアクティブ状態を切替
    const filterBar = document.getElementById(`${blockId}-filter`);
    if (filterBar) {
        filterBar.querySelectorAll('.review-filter-btn').forEach(b => b.classList.remove('review-filter-btn--active'));
        btn.classList.add('review-filter-btn--active');
    }

    const items = list.querySelectorAll('.review-item');
    let visibleCount = 0;
    items.forEach(item => {
        if (star === 0 || parseInt(item.dataset.stars) === star) {
            item.style.display = '';
            item.classList.remove('review-item--hidden');
            visibleCount++;
        } else {
            item.style.display = 'none';
        }
    });

    // フィルタ中は「もっと見る」を非表示
    if (moreBtn) moreBtn.style.display = star === 0 ? '' : 'none';
}

/**
 * 非表示の口コミを全て表示
 * @param {string} blockId - 口コミブロックのID
 * @param {HTMLElement} btn - もっと見るボタン
 */
function showMoreReviews(blockId, btn) {
    const list = document.getElementById(`${blockId}-list`);
    if (!list) return;
    list.querySelectorAll('.review-item--hidden').forEach(item => {
        item.classList.remove('review-item--hidden');
    });
    btn.style.display = 'none';
}

// ==========================================
// Phase 55: 類似クリニック推薦
// ==========================================

/**
 * 類似クリニックを非同期で取得・描画する
 * @param {string} clinicId - 対象クリニックID
 */
async function loadSimilarClinics(clinicId) {
    const container = document.getElementById(`similar-clinics-${clinicId}`);
    if (!container) return;

    try {
        const data = await api(`/api/clinics/${clinicId}/similar`);
        const clinics = data.similar_clinics || [];
        if (clinics.length === 0) return;

        const gradeColors = { A: '#10b981', B: '#3b82f6', C: '#f59e0b', D: '#f97316', E: '#94a3b8' };

        const cardsHtml = clinics.map(c => {
            // グレードバッジ
            let gradeBadge = '';
            if (c.clinic_grade) {
                const gc = gradeColors[c.clinic_grade] || '#94a3b8';
                gradeBadge = `<span class="clinic-grade-badge" style="--grade-color: ${gc}">${c.clinic_grade}</span>`;
            }

            // Google評価
            const ratingHtml = c.google_rating
                ? `<span class="similar-clinic-rating">${c.google_rating.toFixed(1)}</span>`
                : '';
            const reviewCount = c.google_review_count
                ? `<span class="similar-clinic-reviews">${c.google_review_count}件</span>`
                : '';

            // Phase 68: 平均価格
            const avgPriceHtml = c.avg_price
                ? `<span class="similar-clinic-price">avg ¥${Number(c.avg_price).toLocaleString()}</span>`
                : '';

            // 類似理由タグ
            const reasonTags = (c.similarity_reasons || []).map(r =>
                `<span class="similar-reason-tag">${escapeHtml(r)}</span>`
            ).join('');

            // エディトリアルサマリー（先頭60文字）
            const summary = c.editorial_summary
                ? `<div class="similar-clinic-summary">${escapeHtml(c.editorial_summary.substring(0, 60))}${c.editorial_summary.length > 60 ? '...' : ''}</div>`
                : '';

            return `<div class="similar-clinic-card" onclick="showClinicDetail('${escapeHtml(c.id)}')">
                <div class="similar-clinic-header">
                    <div class="similar-clinic-name">${gradeBadge}${escapeHtml(c.name)}</div>
                    <div class="similar-clinic-meta">
                        <span class="similar-clinic-city">${escapeHtml(c.city || '')}</span>
                        ${ratingHtml}${reviewCount}${avgPriceHtml}
                    </div>
                </div>
                ${summary}
                <div class="similar-reason-tags">${reasonTags}</div>
            </div>`;
        }).join('');

        container.innerHTML = `
            <div class="detail-block-title">似たクリニック</div>
            <div class="similar-clinics-grid">${cardsHtml}</div>
        `;
    } catch (err) {
        // 類似クリニック取得失敗は静かに無視（必須機能ではない）
        console.warn('類似クリニック取得エラー:', err);
    }
}

function openPhotoViewer(url) {
    window.open(url, '_blank');
}

// ==========================================
// Phase 63: 構造化データ(JSON-LD)動的埋め込み
// ==========================================

/**
 * クリニックJSON-LDを<head>に動的埋め込み
 * MedicalClinic型の構造化データをAPIから取得し、
 * <script type="application/ld+json">タグとして挿入する。
 * @param {string} clinicId - 対象クリニックID
 */
async function injectClinicJsonLd(clinicId) {
    // 既存のクリニックJSON-LDを削除
    removeClinicJsonLd();
    try {
        const data = await api(`/api/clinics/${clinicId}/jsonld`);
        const script = document.createElement('script');
        script.type = 'application/ld+json';
        script.id = 'clinic-jsonld';
        script.textContent = JSON.stringify(data);
        document.head.appendChild(script);
    } catch (err) {
        // JSON-LD取得失敗はSEO影響のみ、ユーザー体験に影響なし
        console.warn('JSON-LD取得エラー:', err);
    }
}

/**
 * クリニックJSON-LDタグを<head>から削除
 * 詳細パネルを閉じる際に呼び出す
 */
function removeClinicJsonLd() {
    const existing = document.getElementById('clinic-jsonld');
    if (existing) existing.remove();
}

document.getElementById('clinic-detail-close').addEventListener('click', () => {
    if (releaseClinicDetailTrap) { releaseClinicDetailTrap(); releaseClinicDetailTrap = null; }
    document.getElementById('clinic-detail-overlay').style.display = 'none';
    removeClinicJsonLd();
});
document.getElementById('clinic-detail-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) {
        if (releaseClinicDetailTrap) { releaseClinicDetailTrap(); releaseClinicDetailTrap = null; }
        e.currentTarget.style.display = 'none';
        removeClinicJsonLd();
    }
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
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    body.innerHTML = '<p class="loading-text">比較データを読み込み中</p>';
    // フォーカストラップを設定
    releaseCompareTrap = trapFocus(overlay);

    try {
        // Phase 16: 新しい比較APIを使用
        const ids = compareList.map(c => c.id).join(',');
        const data = await api(`/api/clinics/compare/side-by-side?ids=${ids}`);
        const clinics = data.clinics;

        // 最良値を判定
        const maxRating = Math.max(...clinics.map(c => c.google_rating || 0));
        const maxReviews = Math.max(...clinics.map(c => c.google_review_count || 0));
        const maxDoctors = Math.max(...clinics.map(c => c.doctor_count || 0));
        const maxJsaps = Math.max(...clinics.map(c => c.jsaps_doctor_count || 0));
        const maxTransparency = Math.max(...clinics.map(c => c.transparency_score || 0));
        const maxReviewQuality = Math.max(...clinics.map(c => c.avg_review_quality || 0));

        const best = (val, max) => val && val === max && max > 0 ? 'compare-row-value--best' : '';

        body.innerHTML = clinics.map(c => {
            const rating = c.google_rating ? `★ ${c.google_rating.toFixed(1)}` : '—';
            const reviewCount = c.google_review_count ? `${c.google_review_count}件` : '—';
            const doctorInfo = `${c.doctor_count}名${c.jsaps_doctor_count > 0 ? ` (JSAPS ${c.jsaps_doctor_count})` : ''}`;
            const transparency = c.transparency_score ? `${Math.round(c.transparency_score)}/100` : '—';
            const avgTrust = c.avg_trust_score ? `${c.avg_trust_score}pt` : '—';
            const depts = c.departments.join(', ') || '—';
            const reviewQuality = c.avg_review_quality ? `${c.avg_review_quality}pt` : '—';

            return `
                <div class="compare-col">
                    <div class="compare-col-name">${escapeHtml(c.name)}</div>
                    <div class="compare-row">
                        <span class="compare-row-label">Google評価</span>
                        <span class="compare-row-value ${best(c.google_rating, maxRating)}">${rating}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">口コミ数</span>
                        <span class="compare-row-value ${best(c.google_review_count, maxReviews)}">${reviewCount}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">口コミ品質</span>
                        <span class="compare-row-value ${best(c.avg_review_quality, maxReviewQuality)}">${reviewQuality}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">医師数</span>
                        <span class="compare-row-value ${best(c.doctor_count, maxDoctors)}">${doctorInfo}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">JSAPS専門医</span>
                        <span class="compare-row-value ${best(c.jsaps_doctor_count, maxJsaps)}">${c.jsaps_doctor_count > 0 ? `${c.jsaps_doctor_count}名` : '—'}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">医師情報開示</span>
                        <span class="compare-row-value">${avgTrust}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">施術メニュー</span>
                        <span class="compare-row-value">${c.procedure_count}件 (価格${c.price_data_count})</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">情報開示</span>
                        <span class="compare-row-value ${best(c.transparency_score, maxTransparency)}">${transparency}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">診療科</span>
                        <span class="compare-row-value">${escapeHtml(depts)}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">所在地</span>
                        <span class="compare-row-value">${escapeHtml(c.city || '—')}</span>
                    </div>
                    <button class="compare-detail-btn" onclick="document.getElementById('compare-overlay').style.display='none'; showClinicDetail('${escapeHtml(c.id)}')">詳細を見る</button>
                </div>
            `;
        }).join('');
        // コンテンツ読込完了後にフォーカストラップを再設定
        if (releaseCompareTrap) releaseCompareTrap();
        releaseCompareTrap = trapFocus(overlay);
    } catch {
        body.innerHTML = '<p class="loading-text">比較データの取得に失敗しました</p>';
    }
}

// 比較ボタンのイベントリスナー
document.getElementById('compare-btn').addEventListener('click', showComparePanel);

// 比較パネルの閉じるボタン
document.getElementById('compare-close').addEventListener('click', () => {
    if (releaseCompareTrap) { releaseCompareTrap(); releaseCompareTrap = null; }
    document.getElementById('compare-overlay').style.display = 'none';
});
document.getElementById('compare-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) {
        if (releaseCompareTrap) { releaseCompareTrap(); releaseCompareTrap = null; }
        e.currentTarget.style.display = 'none';
    }
});

// ==========================================
// ESCキーでパネルを閉じる
// ==========================================

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        // フォーカストラップを解除してからオーバーレイを閉じる
        if (releaseDetailTrap) { releaseDetailTrap(); releaseDetailTrap = null; }
        if (releaseClinicDetailTrap) { releaseClinicDetailTrap(); releaseClinicDetailTrap = null; }
        if (releaseCompareTrap) { releaseCompareTrap(); releaseCompareTrap = null; }
        document.getElementById('detail-overlay').style.display = 'none';
        document.getElementById('clinic-detail-overlay').style.display = 'none';
        document.getElementById('compare-overlay').style.display = 'none';
        document.getElementById('proc-compare-overlay').style.display = 'none';
        closeFavCompareModal(); // お気に入り比較モーダル
        closeToolModal(); // ツールモーダルもESCで閉じる
    }
});

// ==========================================
// 相談（チャット）
// ==========================================

let sessionId = null;

// ==========================================
// ユーザー行動コンテキスト追跡
// Phase 18: アドバイザー会話品質向上のため、ユーザーの閲覧履歴をコンテキストとして収集
// ==========================================

// ==========================================
// チャット履歴永続化
// ==========================================

const chatStore = {
    key: 'aura-chat-history',
    maxMessages: 50,

    /** 履歴を保存 */
    save(role, content) {
        try {
            const data = this.load();
            data.messages.push({ role, content, timestamp: Date.now() });
            // 最大件数を超過したら古いものを削除
            while (data.messages.length > this.maxMessages) data.messages.shift();
            data.lastUpdated = Date.now();
            localStorage.setItem(this.key, JSON.stringify(data));
        } catch (e) { console.warn('チャット履歴の保存に失敗:', e); }
    },

    /** 履歴を読み込み */
    load() {
        try {
            const raw = localStorage.getItem(this.key);
            if (raw) return JSON.parse(raw);
        } catch (e) { /* 無視 */ }
        return { messages: [], lastUpdated: null };
    },

    /** 履歴をクリア */
    clear() {
        localStorage.removeItem(this.key);
    },

    /** 履歴があるか */
    hasHistory() {
        return this.load().messages.length > 0;
    }
};

// ==========================================
// 閲覧コンテキスト追跡（localStorage永続化付き）
// ==========================================

const browsingContext = {
    viewedProcedures: [],
    viewedClinics: [],
    viewedDoctors: [],
    searchedAreas: [],
    comparedClinics: [],

    _storageKey: 'aura-browsing-context',

    /** localStorageから復元 */
    restore() {
        try {
            const raw = localStorage.getItem(this._storageKey);
            if (raw) {
                const data = JSON.parse(raw);
                this.viewedProcedures = data.viewedProcedures || [];
                this.viewedClinics = data.viewedClinics || [];
                this.viewedDoctors = data.viewedDoctors || [];
                this.searchedAreas = data.searchedAreas || [];
                this.comparedClinics = data.comparedClinics || [];
            }
        } catch (e) { /* 無視 */ }
    },

    /** localStorageに保存 */
    _persist() {
        try {
            localStorage.setItem(this._storageKey, JSON.stringify({
                viewedProcedures: this.viewedProcedures,
                viewedClinics: this.viewedClinics,
                viewedDoctors: this.viewedDoctors,
                searchedAreas: this.searchedAreas,
                comparedClinics: this.comparedClinics,
            }));
        } catch (e) { /* 無視 */ }
    },

    trackProcedure(id, name, category) {
        if (this.viewedProcedures.some(p => p.id === id)) return;
        this.viewedProcedures.push({ id, name, category, timestamp: Date.now() });
        if (this.viewedProcedures.length > 10) this.viewedProcedures.shift();
        this._persist();
    },

    trackClinic(id, name, city) {
        if (this.viewedClinics.some(c => c.id === id)) return;
        this.viewedClinics.push({ id, name, city, timestamp: Date.now() });
        if (this.viewedClinics.length > 10) this.viewedClinics.shift();
        this._persist();
    },

    trackDoctor(id, name) {
        if (this.viewedDoctors.some(d => d.id === id)) return;
        this.viewedDoctors.push({ id, name, timestamp: Date.now() });
        if (this.viewedDoctors.length > 10) this.viewedDoctors.shift();
        this._persist();
    },

    trackArea(city) {
        if (!city || this.searchedAreas.includes(city)) return;
        this.searchedAreas.push(city);
        if (this.searchedAreas.length > 5) this.searchedAreas.shift();
        this._persist();
    },

    toSummary() {
        const parts = [];
        if (this.viewedProcedures.length > 0) {
            parts.push('閲覧した施術: ' + this.viewedProcedures.map(p => p.name).join(', '));
        }
        if (this.viewedClinics.length > 0) {
            parts.push('閲覧したクリニック: ' + this.viewedClinics.map(c => c.name).join(', '));
        }
        if (this.viewedDoctors.length > 0) {
            parts.push('閲覧した医師: ' + this.viewedDoctors.map(d => d.name).join(', '));
        }
        if (this.searchedAreas.length > 0) {
            parts.push('検索したエリア: ' + this.searchedAreas.join(', '));
        }
        if (this.comparedClinics.length > 0) {
            parts.push('比較したクリニック: ' + this.comparedClinics.join(', '));
        }
        return parts.length > 0 ? parts.join('\n') : '';
    },

    hasContext() {
        return this.viewedProcedures.length > 0 || this.viewedClinics.length > 0 || this.viewedDoctors.length > 0;
    }
};

// 起動時に復元
browsingContext.restore();

/**
 * 簡易HTMLサニタイズ — 危険なタグを除去
 * LLM応答に万が一悪意あるHTMLが混入した場合に対応
 */
function sanitizeHtml(html) {
    // script, iframe, object, embed, form, input, img, svg, video, audioタグを除去
    return html
        .replace(/<script[\s\S]*?<\/script>/gi, '')
        .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
        .replace(/<object[\s\S]*?<\/object>/gi, '')
        .replace(/<embed[^>]*>/gi, '')
        .replace(/<form[\s\S]*?<\/form>/gi, '')
        .replace(/<input[^>]*>/gi, '')
        .replace(/<link[^>]*>/gi, '')
        .replace(/<meta[^>]*>/gi, '')
        .replace(/<style[\s\S]*?<\/style>/gi, '')
        .replace(/<img[^>]*>/gi, '')
        .replace(/<svg[\s\S]*?<\/svg>/gi, '')
        .replace(/<video[\s\S]*?<\/video>/gi, '')
        .replace(/<audio[\s\S]*?<\/audio>/gi, '')
        // on*イベントハンドラを除去
        .replace(/\s+on\w+\s*=\s*["'][^"']*["']/gi, '')
        .replace(/\s+on\w+\s*=\s*\S+/gi, '')
        // javascript: URLを除去
        .replace(/href\s*=\s*["']javascript:[^"']*["']/gi, 'href="#"')
        .replace(/src\s*=\s*["']javascript:[^"']*["']/gi, 'src=""');
}

function mdToHtml(text) {
    let html = text
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
    // 危険なHTMLタグをサニタイズ
    return sanitizeHtml(html);
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

    // スターターを非表示
    const starters = document.getElementById('chat-starters');
    if (starters) starters.style.display = 'none';

    // リセットボタンを表示
    const resetBtn = document.getElementById('chat-reset');
    if (resetBtn) resetBtn.style.display = '';

    // localStorageに保存
    chatStore.save(role, content);
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

    // タイピングインジケーターを表示（応答待ち中のアニメーション）
    const typingEl = document.createElement('div');
    typingEl.className = 'chat-msg assistant typing-indicator';
    typingEl.innerHTML = `
        <div class="chat-avatar">A</div>
        <div class="chat-bubble">
            <div class="typing-dots">
                <span></span><span></span><span></span>
            </div>
        </div>
    `;
    chatMessages.appendChild(typingEl);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    const body = { message };
    if (sessionId) body.session_id = sessionId;

    // Phase 18: ユーザー行動コンテキストを添付
    const ctx = browsingContext.toSummary();
    if (ctx) body.browsing_context = ctx;

    const res = await fetch('/api/advisor/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });

    if (!res.ok) {
        typingEl.remove();
        throw new Error(`HTTP ${res.status}`);
    }

    // タイピングインジケーターを削除してアシスタントバブルを作成
    typingEl.remove();
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

                            // 医師情報の要約を生成
                            let doctorHtml = '';
                            if (clinic.doctors && clinic.doctors.length > 0) {
                                const topDocs = clinic.doctors.slice(0, 2);
                                const docLines = topDocs.map(doc => {
                                    let info = `${escapeHtml(doc.title || '')} ${escapeHtml(doc.name)}`;
                                    const tags = [];
                                    if (doc.jsaps_certified) tags.push('JSAPS');
                                    if (doc.certifications && doc.certifications.length > 0) {
                                        const shortCert = doc.certifications[0].replace(/日本|学会|認定/g, '').substring(0, 8);
                                        tags.push(shortCert);
                                    }
                                    if (doc.experience_years) tags.push(`${doc.experience_years}年`);
                                    // Phase 15: 専門医バッジ
                                    if (doc.specialty_confidence === 'high') tags.push('専門');
                                    if (tags.length > 0) info += ` <span class="rec-doc-tags">${tags.join(' · ')}</span>`;
                                    return info;
                                }).join('<br>');
                                doctorHtml = `<div class="recommendation-card-doctors">${docLines}</div>`;
                            }

                            // Phase 15: 施術価格表示
                            let procPriceHtml = '';
                            if (clinic.procedures && clinic.procedures.length > 0) {
                                const priceItems = clinic.procedures.slice(0, 2).filter(p => p.price_display).map(p =>
                                    `<span class="rec-proc-price">${escapeHtml(p.name.substring(0, 12))}: ${escapeHtml(p.price_display)}</span>`
                                ).join('');
                                if (priceItems) procPriceHtml = `<div class="recommendation-card-prices">${priceItems}</div>`;
                            }

                            // Phase 15: 注意バッジ
                            let cautionBadge = '';
                            const cautions = clinic.cautions || [];
                            const hasRedFlag = cautions.some(c => c.includes('勧誘') || c.includes('トラブル'));
                            if (hasRedFlag) {
                                cautionBadge = '<span class="rec-caution-badge">注意情報あり</span>';
                            }

                            // Phase 15: レビュー品質
                            let reviewBadge = '';
                            if (clinic.review_summary && clinic.review_summary.avg_quality) {
                                const q = Math.round(clinic.review_summary.avg_quality);
                                if (q >= 60) reviewBadge = `<span class="rec-review-badge rec-review-badge--good">口コミ品質 ${q}pt</span>`;
                            }

                            card.innerHTML = `
                                <div class="recommendation-card-header">
                                    <div class="recommendation-card-name">${escapeHtml(clinic.name)}</div>
                                    ${clinic.google_rating ? `<div class="recommendation-card-rating">★ ${clinic.google_rating.toFixed(1)}${clinic.google_review_count ? ` <span class="rec-review-count">(${clinic.google_review_count})</span>` : ''}</div>` : ''}
                                </div>
                                ${doctorHtml}
                                ${procPriceHtml}
                                <div class="recommendation-card-badges">
                                    ${clinic.match_reasons ? clinic.match_reasons.slice(0, 3).map(r => `<span class="rec-reason-tag">${escapeHtml(r)}</span>`).join('') : ''}
                                    ${cautionBadge}
                                    ${reviewBadge}
                                </div>
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
        // Phase 18: ユーザー行動コンテキストを添付
        const ctx = browsingContext.toSummary();
        if (ctx) body.browsing_context = ctx;
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

// リセットボタン
const chatResetBtn = document.getElementById('chat-reset');
if (chatResetBtn) {
    chatResetBtn.addEventListener('click', resetChat);
}

// ==========================================
// チャット クイックアクション
// ==========================================

document.querySelectorAll('.chat-quick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const chatInput = document.getElementById('chat-input');
        chatInput.value = btn.dataset.msg;
        // スターターを非表示にする
        const starters = document.getElementById('chat-starters');
        if (starters) starters.style.display = 'none';
        sendChat();
    });
});

/**
 * 過去の相談セッション一覧を表示
 */
async function showSessionHistory() {
    try {
        const data = await api('/api/advisor/sessions');
        const sessions = data.sessions || [];

        if (sessions.length === 0) {
            showToast('過去の相談履歴はありません', 'info');
            return;
        }

        // モーダル表示
        const overlay = document.createElement('div');
        overlay.className = 'session-history-overlay';
        overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

        const modal = document.createElement('div');
        modal.className = 'session-history-modal';
        modal.innerHTML = `
            <div class="session-history-header">
                <h3>過去の相談</h3>
                <button class="session-history-close" onclick="this.closest('.session-history-overlay').remove()">✕</button>
            </div>
            <div class="session-history-list">
                ${sessions.map(s => `
                    <div class="session-history-item" onclick="resumeSession('${escapeHtml(s.session_id)}'); this.closest('.session-history-overlay').remove();">
                        <div class="session-history-summary">${escapeHtml(s.summary)}</div>
                        <div class="session-history-meta">
                            <span>${s.message_count}件のやりとり</span>
                            ${s.concern ? `<span class="session-history-concern">${escapeHtml(s.concern)}</span>` : ''}
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
        overlay.appendChild(modal);
        document.body.appendChild(overlay);
    } catch (err) {
        console.warn('セッション履歴取得に失敗:', err);
        showToast('履歴の取得に失敗しました', 'error');
    }
}

/**
 * 過去のセッションを復元
 */
async function resumeSession(sessionId) {
    try {
        const data = await api(`/api/advisor/session/${sessionId}`);
        const messages = data.messages || [];

        // 既存チャットをクリア
        const el = document.getElementById('chat-messages');
        el.innerHTML = '';

        // セッションIDを設定
        currentSessionId = sessionId;

        // メッセージを復元
        messages.forEach(msg => {
            appendChatMessage(msg.role, msg.content);
        });

        // UI状態更新
        const intro = document.getElementById('advisor-intro');
        if (intro) intro.style.display = 'none';
        const quickActions = document.getElementById('chat-quick-actions');
        if (quickActions) quickActions.style.display = 'none';
        const starters = document.getElementById('chat-starters');
        if (starters) starters.style.display = 'none';
        const resetBtn = document.getElementById('chat-reset');
        if (resetBtn) resetBtn.style.display = '';

        showToast('過去の相談を復元しました', 'info');
    } catch (err) {
        console.warn('セッション復元に失敗:', err);
        showToast('セッション復元に失敗しました', 'error');
    }
}

/**
 * チャット履歴をlocalStorageから復元
 */
function restoreChatHistory() {
    const data = chatStore.load();
    if (data.messages.length === 0) return false;

    const el = document.getElementById('chat-messages');
    if (!el) return false;

    // イントロ・クイックアクションを非表示
    const intro = document.getElementById('advisor-intro');
    if (intro) intro.style.display = 'none';
    const quickActions = document.getElementById('chat-quick-actions');
    if (quickActions) quickActions.style.display = 'none';

    // メッセージを復元（addMsgを使わず直接DOM操作 — localStorage再保存を避ける）
    data.messages.forEach(m => {
        const div = document.createElement('div');
        div.className = `msg msg--${m.role}`;
        const bodyContent = m.role === 'assistant' ? mdToHtml(m.content) : escapeHtml(m.content);
        div.innerHTML = `<div class="msg-body">${bodyContent}</div>`;
        el.appendChild(div);
    });
    el.scrollTop = el.scrollHeight;

    // リセットボタンを表示
    const resetBtn = document.getElementById('chat-reset');
    if (resetBtn) resetBtn.style.display = '';

    return true;
}

/**
 * チャットをリセット（新しい相談を始める）
 */
function resetChat() {
    chatStore.clear();
    const el = document.getElementById('chat-messages');
    if (el) el.innerHTML = '';
    const intro = document.getElementById('advisor-intro');
    if (intro) intro.style.display = '';
    const quickActions = document.getElementById('chat-quick-actions');
    if (quickActions) quickActions.style.display = '';
    const resetBtn = document.getElementById('chat-reset');
    if (resetBtn) resetBtn.style.display = 'none';
    // スターターを再表示
    renderChatStarters();
}

/**
 * チャットスターターを生成
 * browsingContextがある場合はコンテキスト対応サジェストを表示
 */
function renderChatStarters() {
    const container = document.getElementById('chat-starters');
    const messages = document.getElementById('chat-messages');
    if (!container) return;

    // 既にメッセージがある場合は表示しない
    if (messages && messages.children.length > 0) {
        container.style.display = 'none';
        return;
    }

    // 履歴復元を試行
    if (chatStore.hasHistory()) {
        const restored = restoreChatHistory();
        if (restored) {
            container.style.display = 'none';
            return;
        }
    }

    let cards = [];

    // browsingContextがある場合 — コンテキスト対応サジェスト
    if (typeof browsingContext !== 'undefined' && browsingContext.hasContext()) {
        const vp = browsingContext.viewedProcedures;
        const vc = browsingContext.viewedClinics;
        const sa = browsingContext.searchedAreas;

        if (vp.length > 0) {
            const last = vp[vp.length - 1];
            cards.push({
                icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>',
                label: `${last.name}について詳しく知りたい`,
                msg: `${last.name}について、費用やリスク、カウンセリングで聞くべきことを教えてください`
            });
        }
        if (vc.length > 0) {
            const last = vc[vc.length - 1];
            cards.push({
                icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.657 16.657L13.414 20.9a2 2 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"/><circle cx="12" cy="11" r="3"/></svg>',
                label: `${last.name}の口コミを教えて`,
                msg: `${last.name}（${last.city || '東京'}）の評判や口コミ、注意点を教えてください`
            });
        }
        if (sa.length > 0) {
            const area = sa[sa.length - 1];
            cards.push({
                icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>',
                label: `${area}のクリニックを比較したい`,
                msg: `${area}で評価の高いクリニックを比較して教えてください`
            });
        }
        if (cards.length < 4) {
            cards.push({
                icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
                label: '初めてのカウンセリング、何を聞けばいい？',
                msg: '初めてのカウンセリングで聞くべき質問リストを作ってください'
            });
        }
    } else {
        cards = [
            { icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>', label: '二重整形を考えています', msg: '二重整形を考えています。埋没法と切開法の違い、費用、リスクを教えてください' },
            { icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>', label: '自分に合った施術がわからない', msg: '自分に合った美容施術がわからなくて悩んでいます。どう選べばいいですか？' },
            { icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>', label: 'カウンセリングで聞くべきことは？', msg: '初めてのカウンセリングで聞くべき質問リストを作ってください' },
            { icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>', label: 'クーリングオフの方法を知りたい', msg: 'クーリングオフの方法と条件を教えてください' },
        ];
    }

    container.innerHTML = `
        <div class="chat-starters-title">何でも聞いてください</div>
        <div class="chat-starters-grid">
            ${cards.map(c => `
                <button class="chat-starter-card" data-msg="${escapeHtml(c.msg)}">
                    <span class="chat-starter-icon">${c.icon}</span>
                    <span class="chat-starter-label">${escapeHtml(c.label)}</span>
                </button>
            `).join('')}
        </div>
    `;
    container.style.display = 'block';

    container.querySelectorAll('.chat-starter-card').forEach(card => {
        card.addEventListener('click', () => {
            document.getElementById('chat-input').value = card.dataset.msg;
            container.style.display = 'none';
            sendChat();
        });
    });
}

// ==========================================
// 初期化
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    // URLに基づいてページを表示（リロード対応）
    const path = window.location.pathname.replace(/^\//, '') || 'home';
    const validPages = ['home', 'procedures', 'clinics', 'doctors', 'favorites', 'advisor', 'dashboard', 'terms', 'privacy'];
    const initialPage = validPages.includes(path) ? path : 'home';

    // 初期状態をhistoryに記録
    history.replaceState({ page: initialPage }, '', initialPage === 'home' ? '/' : `/${initialPage}`);
    navigate(initialPage);

    // 法的行動支援ツールの読み込み
    loadTools();

    // ダークモード切替ボタンのイベントリスナー
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            const current = document.documentElement.getAttribute('data-theme');
            const isDark = current === 'dark' ||
                (!current && window.matchMedia('(prefers-color-scheme: dark)').matches);
            const next = isDark ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('aura-theme', next);
        });
    }

    // --- アクセシビリティ: 悩みカードにキーボード操作対応 ---
    // Enter/Spaceキーで悩みカードをクリック可能にする
    document.querySelectorAll('.concern-card').forEach(card => {
        card.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                card.click();
            }
        });
    });

    // モバイル: キーボード表示時にチャットエリアをスクロール
    const chatInputMobile = document.getElementById('chat-input');
    const chatMsgArea = document.getElementById('chat-messages');
    if (chatInputMobile && chatMsgArea) {
        chatInputMobile.addEventListener('focus', () => {
            setTimeout(() => {
                chatMsgArea.scrollTop = chatMsgArea.scrollHeight;
            }, 300);
        });
    }

    // スクロールトップボタン
    const scrollTopBtn = document.getElementById('scroll-top-btn');
    if (scrollTopBtn) {
        window.addEventListener('scroll', () => {
            scrollTopBtn.style.display = window.scrollY > 400 ? 'flex' : 'none';
        });
        scrollTopBtn.addEventListener('click', () => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }
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

        // 見積もりチェッカーカードを先頭に追加
        const quoteCheckerCard = `
            <div class="tool-card" onclick="showQuoteChecker()">
                <span class="tool-card-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="2" width="16" height="20" rx="2"/><line x1="8" y1="6" x2="16" y2="6"/><line x1="8" y1="10" x2="16" y2="10"/><line x1="8" y1="14" x2="12" y2="14"/><path d="M14 18h2"/></svg></span>
                <div class="tool-card-title">見積もりチェッカー</div>
                <div class="tool-card-desc">カウンセリングでもらった見積もりが適正かチェック</div>
                <span class="tool-card-badge">NEW</span>
            </div>
        `;

        grid.innerHTML = quoteCheckerCard + tools.map(tool => `
            <div class="tool-card" onclick="openTool('${escapeHtml(tool.id)}')">
                <span class="tool-card-icon">${tool.icon && !tool.icon.match(/[\u{1F300}-\u{1FAFF}]/u) ? escapeHtml(tool.icon) : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>'}</span>
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

    // cooling_off_checkツールはインタラクティブフォームを表示
    if (toolId === 'cooling_off_check') {
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
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) closeToolModal();
            });
            document.body.appendChild(overlay);
        }
        overlay.classList.add('active');

        const contentEl = document.getElementById('tool-modal-content');
        contentEl.innerHTML = `
            <h2>クーリングオフ判定</h2>
            <p>契約情報を入力してください</p>
            <form id="cooling-off-form" class="defense-form">
                <label>契約日
                    <input type="date" id="co-contract-date" required>
                </label>
                <label>施術内容
                    <input type="text" id="co-procedure" placeholder="例: 脱毛、シミ除去">
                </label>
                <label>契約金額（円）
                    <input type="number" id="co-amount" placeholder="例: 298000">
                </label>
                <label>契約期間
                    <input type="text" id="co-period" placeholder="例: 3ヶ月">
                </label>
                <label class="checkbox-label">
                    <input type="checkbox" id="co-sameday">
                    即日施術だった
                </label>
                <button type="submit" class="defense-submit">判定する</button>
            </form>
        `;
        document.getElementById('cooling-off-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const params = {
                contract_date: document.getElementById('co-contract-date').value,
                procedure_type: document.getElementById('co-procedure').value,
                total_amount: document.getElementById('co-amount').value,
                contract_period: document.getElementById('co-period').value,
                same_day_treatment: document.getElementById('co-sameday').checked,
            };
            contentEl.innerHTML = '<p class="loading-text">判定中…</p>';
            try {
                const result = await apiPost('/api/advisor/tools/cooling_off_check', { params });
                contentEl.innerHTML = renderToolModal('cooling_off_check', result.result);
            } catch {
                contentEl.innerHTML = '<p class="loading-text">判定に失敗しました</p>';
            }
        });
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
            html += `<button class="tool-copy-btn" onclick="copyTemplate(this.previousElementSibling.textContent)">コピーする</button>`;
        }

        if (instructions.length > 0) {
            html += `<h3>使い方・手順</h3>`;
            html += `<ul>${instructions.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>`;
        }

        if (legalBasis) {
            html += `<div class="legal-basis">${escapeHtml(legalBasis)}</div>`;
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
            html += `<h3>危険信号（レッドフラグ）</h3>`;
            html += `<ul>${redFlags.map(flag => `<li class="red-flag">${escapeHtml(flag)}</li>`).join('')}</ul>`;
        }

        // アドバイス
        if (advice) {
            html += `<div class="warning-box">${escapeHtml(advice)}</div>`;
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
            html += `<h3>正常な経過サイン</h3>`;
            html += `<ul>${normalSigns.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>`;
        }

        if (warningSigns.length > 0) {
            html += `<h3>要注意サイン（すぐ受診）</h3>`;
            html += `<ul>${warningSigns.map(s => `<li class="red-flag">${escapeHtml(s)}</li>`).join('')}</ul>`;
        }

        if (emergencyContacts.length > 0) {
            html += `<h3>緊急連絡先</h3>`;
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
            html += `<div class="warning-box">消費者ホットライン: <strong>${escapeHtml(hotline)}</strong></div>`;
        }

        if (prepareBefore.length > 0) {
            html += `<h3>電話前に準備するもの</h3>`;
            html += `<ul>${prepareBefore.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
        }

        if (timelineTemplate) {
            html += `<h3>経緯まとめテンプレート</h3>`;
            html += `<pre>${escapeHtml(timelineTemplate)}</pre>`;
            html += `<button class="tool-copy-btn" onclick="copyTemplate(this.previousElementSibling.textContent)">コピーする</button>`;
        }

        return html;
    }

    // カウンセリング防衛カード（圧力対抗セリフ集）
    if (toolId === 'counseling_armor') {
        const r = result;
        let html = `<h2>${escapeHtml(r.title || '')}</h2>`;
        html += `<p class="tool-philosophy">${escapeHtml(r.philosophy || '')}</p>`;

        // 圧力対抗セリフ集
        html += '<h3>圧力をかわすセリフ</h3>';
        html += '<div class="pressure-scripts">';
        (r.pressure_scripts || []).forEach(s => {
            html += `
                <div class="pressure-card">
                    <div class="pressure-line">${escapeHtml(s.pressure)}</div>
                    <div class="response-line">→ ${escapeHtml(s.response)}</div>
                    <div class="response-note">${escapeHtml(s.note)}</div>
                </div>`;
        });
        html += '</div>';

        // カウンセリング前チェックリスト
        html += '<h3>カウンセリング前の準備</h3>';
        html += '<ul class="defense-checklist">';
        (r.before_counseling_checklist || []).forEach(item => {
            html += `<li>${escapeHtml(item)}</li>`;
        });
        html += '</ul>';

        // カウンセリング後チェックリスト
        html += '<h3>帰宅後の確認</h3>';
        html += '<ul class="defense-checklist">';
        (r.after_counseling_checklist || []).forEach(item => {
            html += `<li>${escapeHtml(item)}</li>`;
        });
        html += '</ul>';

        // 録音ガイド
        if (r.recording_guide) {
            html += `<h3>${escapeHtml(r.recording_guide.title)}</h3>`;
            html += `<p class="legal-basis">${escapeHtml(r.recording_guide.legal_basis)}</p>`;
            html += '<ul>';
            (r.recording_guide.tips || []).forEach(tip => {
                html += `<li>${escapeHtml(tip)}</li>`;
            });
            html += '</ul>';
        }

        return html;
    }

    // 施術別質問リスト生成
    if (toolId === 'question_generator') {
        const r = result;
        let html = `<h2>${escapeHtml(r.title || '')}</h2>`;
        html += `<p class="tool-subtitle">${escapeHtml(r.subtitle || '')}</p>`;

        // カテゴリセレクター（施術別質問を切り替え）
        if (r.available_categories && r.available_categories.length > 0) {
            html += '<div class="question-category-selector">';
            html += '<span>施術を選ぶ:</span> ';
            r.available_categories.forEach(cat => {
                html += `<button class="category-pill" onclick="regenerateQuestions('${escapeHtml(cat)}')">${escapeHtml(cat)}</button> `;
            });
            html += '</div>';
        }

        // 質問リスト
        (r.questions || []).forEach(group => {
            html += `<h3>${escapeHtml(group.category)}</h3>`;
            html += '<ol class="question-list">';
            (group.questions || []).forEach(q => {
                html += `<li>${escapeHtml(q)}</li>`;
            });
            html += '</ol>';
        });

        html += `<p class="usage-guide">${escapeHtml(r.usage_guide || '')}</p>`;

        return html;
    }

    // クーリングオフ判定結果の表示
    if (toolId === 'cooling_off_check') {
        const r = result;
        let html = `<h2>${escapeHtml(r.title || '')}</h2>`;
        html += `<div class="judgment-banner ${r.judgment?.includes('OK') || r.judgment?.includes('可能') ? 'judgment-ok' : 'judgment-warning'}">${escapeHtml(r.judgment || '')}</div>`;

        if (r.deadline_info) {
            html += `<p class="deadline-info">${escapeHtml(r.deadline_info)}</p>`;
        }
        if (r.same_day_warning) {
            html += `<div class="same-day-warning">${escapeHtml(r.same_day_warning)}</div>`;
        }

        // 各チェック結果
        (r.checks || []).forEach(check => {
            html += `
                <div class="check-result">
                    <span class="check-status">${check.status}</span>
                    <span class="check-detail">${escapeHtml(check.detail)}</span>
                </div>`;
        });

        // 次のステップ
        if (r.next_steps) {
            html += '<h3>次にすべきこと</h3>';
            html += '<ul>';
            r.next_steps.forEach(step => {
                html += `<li>${escapeHtml(step)}</li>`;
            });
            html += '</ul>';
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
 * 見積もりチェッカーを表示する
 * 施術を選択 → 金額入力 → 市場統計と比較して判定
 */
async function showQuoteChecker() {
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
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeToolModal();
        });
        document.body.appendChild(overlay);
    }
    overlay.classList.add('active');

    const contentEl = document.getElementById('tool-modal-content');
    contentEl.innerHTML = '<p class="loading-text">施術データを読み込み中</p>';

    // 施術一覧を取得してドロップダウンに表示
    try {
        const data = await api('/api/procedures/');
        const procs = data.procedures || [];

        contentEl.innerHTML = `
            <h2>見積もりチェッカー</h2>
            <p style="font-size:0.85rem; color:var(--text-secondary); line-height:1.7;">カウンセリングで提示された金額が適正か、市場データと比較してチェックします。</p>
            <form id="quote-checker-form" class="quote-checker-form">
                <label>施術を選択
                    <select id="qc-procedure" required>
                        <option value="">-- 選択してください --</option>
                        ${procs.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}（${escapeHtml(p.category_label || '')}）</option>`).join('')}
                    </select>
                </label>
                <label>見積もり金額（税込・円）
                    <input type="number" id="qc-price" placeholder="例: 150000" min="1000" required>
                </label>
                <button type="submit" class="quote-checker-submit">チェックする</button>
            </form>
        `;

        document.getElementById('quote-checker-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const procName = document.getElementById('qc-procedure').value;
            const price = document.getElementById('qc-price').value;
            if (!procName || !price) return;

            const submitBtn = e.target.querySelector('.quote-checker-submit');
            submitBtn.disabled = true;
            submitBtn.textContent = '判定中...';

            try {
                const result = await api(`/api/procedures/market-check/${encodeURIComponent(procName)}?price=${price}`);
                _renderQuoteResult(contentEl, result);
            } catch (err) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'チェックする';
                showToast('判定に失敗しました。もう一度お試しください', 'error');
            }
        });
    } catch {
        contentEl.innerHTML = '<p class="loading-text">施術データの読み込みに失敗しました</p>';
    }
}

/**
 * 見積もりチェッカーの判定結果を描画する
 * @param {HTMLElement} container - 結果を表示するコンテナ要素
 * @param {object} result - APIから返された判定結果
 */
function _renderQuoteResult(container, result) {
    const formatYen = (n) => n ? `${Math.round(n).toLocaleString()}円` : '---';

    let html = `
        <h2>見積もりチェッカー</h2>
        <h3 style="margin-top:0.5rem; font-size:1rem;">${escapeHtml(result.procedure_name)}</h3>

        <div class="quote-verdict quote-verdict--${escapeHtml(result.verdict)}">
            ${escapeHtml(result.verdict_label)}
        </div>

        <div class="quote-stats">
            <div class="quote-stat-item">
                <span class="quote-stat-label">あなたの見積もり</span>
                <span class="quote-stat-value">${formatYen(result.input_price)}</span>
            </div>
            <div class="quote-stat-item">
                <span class="quote-stat-label">市場中央値</span>
                <span class="quote-stat-value">${formatYen(result.market_median)}</span>
            </div>
            <div class="quote-stat-item">
                <span class="quote-stat-label">相場範囲 (25-75%)</span>
                <span class="quote-stat-value">${formatYen(result.market_p25)}〜${formatYen(result.market_p75)}</span>
            </div>
            <div class="quote-stat-item">
                <span class="quote-stat-label">隠れコスト込み推定</span>
                <span class="quote-stat-value">${formatYen(result.total_estimated)}</span>
            </div>
        </div>
    `;

    // 隠れコスト
    if (result.hidden_costs && result.hidden_costs.length > 0) {
        html += `
            <div class="quote-hidden-costs">
                <h4>見積もりに含まれていない可能性のある費用</h4>
                <ul>
                    ${result.hidden_costs.map(c => `<li>${escapeHtml(c)}</li>`).join('')}
                </ul>
            </div>
        `;
    }

    // 確認すべき質問
    if (result.questions_to_ask && result.questions_to_ask.length > 0) {
        html += `
            <div class="quote-questions">
                <h4>カウンセリングで確認すべき質問</h4>
                <ol>
                    ${result.questions_to_ask.map(q => `<li>${escapeHtml(q)}</li>`).join('')}
                </ol>
            </div>
        `;
    }

    // 再チェックボタン
    html += `
        <div style="text-align:center; margin-top:1.5rem;">
            <button class="quote-checker-submit" onclick="showQuoteChecker()">別の施術をチェック</button>
        </div>
    `;

    container.innerHTML = html;
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

/**
 * 施術カテゴリを選択して質問リストを再生成する
 * @param {string} category - 施術カテゴリ名
 */
async function regenerateQuestions(category) {
    const contentEl = document.getElementById('tool-modal-content');
    contentEl.innerHTML = '<p class="loading-text">読み込み中…</p>';
    try {
        const result = await apiPost('/api/advisor/tools/question_generator', { params: { procedure_type: category } });
        contentEl.innerHTML = renderToolModal('question_generator', result.result);
    } catch {
        contentEl.innerHTML = '<p class="loading-text">読み込みに失敗しました</p>';
    }
}

// ESCキーでツールモーダルを閉じる処理はL1000-1006に統合済み


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

    // お気に入りクリニックの情報を並列取得
    const clinics = (await Promise.all(
        favIds.map(id => api(`/api/clinics/${id}`).catch(() => null))
    )).filter(Boolean);

    if (clinics.length === 0) {
        listEl.innerHTML = '';
        emptyEl.style.display = 'flex';
        return;
    }

    listEl.innerHTML = clinics.map(c => {
        const rating = c.google_rating ? `<span class="clinic-rating">${c.google_rating}</span>` : '';
        const reviews = c.google_review_count ? `<span class="clinic-reviews">(${c.google_review_count}件)</span>` : '';

        let transparencyBadge = '';
        if (c.transparency_score != null) {
            const level = c.transparency_score >= 70 ? 'high' : c.transparency_score >= 40 ? 'mid' : 'low';
            transparencyBadge = `<span class="transparency-badge transparency-badge--${level}">透明性 ${Math.round(c.transparency_score)}</span>`;
        }

        // グレードバッジ
        const gradeBadge = c.clinic_grade ? `<span class="fav-grade-badge fav-grade-badge--${escapeHtml(c.clinic_grade.toLowerCase())}">${escapeHtml(c.clinic_grade)}</span>` : '';

        // AURAスコア
        const scoreBadge = c.clinic_score != null ? `<span class="fav-score-badge">${Math.round(c.clinic_score)}</span>` : '';

        return `
            <div class="clinic-item favorite-item" onclick="showClinicDetail('${escapeHtml(c.id)}')">
                <label class="fav-compare-check" onclick="event.stopPropagation()">
                    <input type="checkbox" class="fav-compare-checkbox" data-clinic-id="${escapeHtml(c.id)}" onchange="updateFavCompareSelection()">
                    <span class="fav-compare-checkmark"></span>
                </label>
                ${favoriteButtonHtml(c.id)}
                <div class="clinic-item-content">
                    <div class="clinic-item-header">
                        <div class="clinic-item-name">${gradeBadge}${escapeHtml(c.name)}</div>
                        <div class="clinic-item-rating">${scoreBadge}${rating}${reviews}</div>
                    </div>
                    <div class="clinic-item-addr">${escapeHtml(c.address || c.city || '')}</div>
                    <div class="clinic-item-tags">
                        ${c.phone ? `<span class="clinic-tag"><span class="tag-icon">TEL</span> ${escapeHtml(c.phone)}</span>` : ''}
                        ${transparencyBadge}
                    </div>
                </div>
            </div>
        `;
    }).join('');

    // カウンセリング準備シートボタンの表示
    const actionsEl = document.getElementById('favorites-actions');
    if (actionsEl) actionsEl.style.display = clinics.length > 0 ? '' : 'none';

    // 比較ボタンの初期状態をリセット
    updateFavCompareSelection();

    // Phase 48: 閲覧履歴の表示
    renderBrowsingHistory();
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

// Phase 48: お気に入りエクスポート
function exportFavorites(format) {
    const favIds = favoritesStore.getAll();
    if (favIds.length === 0) {
        alert('お気に入りがありません');
        return;
    }

    // お気に入りの表示中データからクリニック情報を抽出
    const cards = document.querySelectorAll('#favorites-list .favorite-item');
    const clinics = [];
    cards.forEach(card => {
        const name = card.querySelector('.clinic-item-name')?.textContent?.trim() || '';
        const addr = card.querySelector('.clinic-item-addr')?.textContent?.trim() || '';
        const rating = card.querySelector('.clinic-rating')?.textContent?.trim() || '';
        const phone = card.querySelector('.clinic-tag')?.textContent?.replace('TEL ', '')?.trim() || '';
        clinics.push({ name, addr, rating, phone });
    });

    if (format === 'csv') {
        // CSV形式でダウンロード
        let csv = 'クリニック名,住所,Google評価,電話番号\n';
        clinics.forEach(c => {
            csv += `"${c.name}","${c.addr}","${c.rating}","${c.phone}"\n`;
        });
        const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `aura_favorites_${new Date().toISOString().split('T')[0]}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    } else {
        // テキスト形式でクリップボードにコピー
        let text = '【AURA お気に入りクリニック一覧】\n';
        text += `作成日: ${new Date().toLocaleDateString('ja-JP')}\n\n`;
        clinics.forEach((c, i) => {
            text += `${i + 1}. ${c.name}\n`;
            text += `   住所: ${c.addr}\n`;
            if (c.rating) text += `   評価: ${c.rating}\n`;
            if (c.phone) text += `   電話: ${c.phone}\n`;
            text += '\n';
        });
        text += `\n※ AURAで詳細を確認: ${location.origin}\n`;
        navigator.clipboard.writeText(text).then(() => {
            showToast('テキストをコピーしました');
        }).catch(() => {
            // フォールバック
            const ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            showToast('テキストをコピーしました');
        });
    }
}

// ==========================================
// Phase 58: お気に入りクリニック比較機能
// ==========================================

/**
 * お気に入り比較チェックボックスの選択状態を更新する
 * 2-4件選択時のみ比較ボタンを有効化
 */
function updateFavCompareSelection() {
    const checked = document.querySelectorAll('.fav-compare-checkbox:checked');
    const btn = document.getElementById('fav-compare-btn');
    const label = document.getElementById('fav-compare-label');
    if (!btn || !label) return;

    const count = checked.length;
    if (count >= 2 && count <= 4) {
        btn.disabled = false;
        label.textContent = `比較する (${count}件)`;
    } else {
        btn.disabled = true;
        label.textContent = count > 4 ? '最大4件まで' : '比較する';
    }
}

/**
 * お気に入り比較モーダルを開く
 * 選択されたクリニックのIDをAPIに送って比較データを取得
 */
async function openFavCompareModal() {
    const checked = document.querySelectorAll('.fav-compare-checkbox:checked');
    const ids = Array.from(checked).map(cb => cb.dataset.clinicId);
    if (ids.length < 2 || ids.length > 4) return;

    const overlay = document.getElementById('fav-compare-overlay');
    const body = document.getElementById('fav-compare-body');
    if (!overlay || !body) return;

    overlay.style.display = 'flex';
    body.innerHTML = '<p class="loading-text">比較データを読み込み中...</p>';

    try {
        const data = await apiPost('/api/favorites/compare', { clinic_ids: ids });
        body.innerHTML = renderFavCompareContent(data);
        // バーチャートのアニメーション発火
        requestAnimationFrame(() => {
            body.querySelectorAll('.fc-bar-fill').forEach(el => {
                el.style.width = el.dataset.width;
            });
        });
    } catch (err) {
        console.warn('比較データ取得失敗:', err);
        body.innerHTML = '<p class="loading-text">比較データの取得に失敗しました</p>';
    }
}

/**
 * お気に入り比較モーダルを閉じる
 */
function closeFavCompareModal() {
    const overlay = document.getElementById('fav-compare-overlay');
    if (overlay) overlay.style.display = 'none';
}

/**
 * 比較コンテンツをレンダリングする
 * @param {Object} data - 比較APIレスポンス
 * @returns {string} HTML文字列
 */
function renderFavCompareContent(data) {
    const clinics = data.clinics || [];
    const commonProcs = data.common_procedures || [];
    const insights = data.insights || [];

    if (clinics.length === 0) return '<p class="loading-text">比較データがありません</p>';

    let html = '';

    // === 1. ヘッダー: 各クリニック名 + グレードバッジ ===
    html += '<div class="fc-header-row">';
    clinics.forEach(c => {
        const grade = c.clinic_grade || '';
        const gradeClass = grade ? `fc-grade--${escapeHtml(grade.toLowerCase())}` : '';
        html += `<div class="fc-header-cell">
            ${grade ? `<span class="fc-grade ${gradeClass}">${escapeHtml(grade)}</span>` : ''}
            <span class="fc-clinic-name">${escapeHtml(c.name)}</span>
            ${c.city ? `<span class="fc-clinic-city">${escapeHtml(c.city)}</span>` : ''}
        </div>`;
    });
    html += '</div>';

    // === 2. スコア比較行 ===
    const metrics = [
        { key: 'clinic_score', label: 'AURAスコア', max: 100, color: 'var(--accent-gold)' },
        { key: 'google_rating', label: 'Google評価', max: 5, color: 'var(--success)' },
        { key: 'google_review_count', label: '口コミ数', max: null, color: 'var(--warning)' },
        { key: 'transparency_score', label: '透明性', max: 100, color: 'var(--accent)' },
    ];

    html += '<div class="fc-section"><h3 class="fc-section-title">スコア比較</h3>';
    metrics.forEach(m => {
        const values = clinics.map(c => c[m.key] || 0);
        const maxVal = m.max || Math.max(...values, 1);
        const bestVal = Math.max(...values);

        html += `<div class="fc-metric-row">
            <div class="fc-metric-label">${escapeHtml(m.label)}</div>
            <div class="fc-bar-group">`;
        clinics.forEach((c, i) => {
            const val = c[m.key] || 0;
            const pct = Math.min((val / maxVal) * 100, 100);
            const isBest = val === bestVal && val > 0;
            const displayVal = m.key === 'google_rating' ? val.toFixed(1) : Math.round(val);
            html += `<div class="fc-bar-row${isBest ? ' fc-winner' : ''}">
                <span class="fc-bar-clinic-name">${escapeHtml(c.name.substring(0, 12))}</span>
                <div class="fc-bar-track">
                    <div class="fc-bar-fill" data-width="${pct}%" style="width: 0; background: ${m.color};">
                        <span class="fc-bar-value">${displayVal}</span>
                    </div>
                </div>
            </div>`;
        });
        html += '</div></div>';
    });
    html += '</div>';

    // === 3. 口コミ感情分布 ===
    html += '<div class="fc-section"><h3 class="fc-section-title">口コミ傾向</h3>';
    html += '<div class="fc-sentiment-grid">';
    clinics.forEach(c => {
        const s = c.review_sentiment || { positive: 0, neutral: 0, negative: 0 };
        html += `<div class="fc-sentiment-card">
            <div class="fc-sentiment-name">${escapeHtml(c.name.substring(0, 15))}</div>
            <div class="fc-sentiment-stack">
                <div class="fc-sentiment-bar fc-sentiment-pos" style="width:${s.positive}%"></div>
                <div class="fc-sentiment-bar fc-sentiment-neu" style="width:${s.neutral}%"></div>
                <div class="fc-sentiment-bar fc-sentiment-neg" style="width:${s.negative}%"></div>
            </div>
            <div class="fc-sentiment-legend">
                <span class="fc-legend-pos">${s.positive}%</span>
                <span class="fc-legend-neu">${s.neutral}%</span>
                <span class="fc-legend-neg">${s.negative}%</span>
            </div>
        </div>`;
    });
    html += '</div></div>';

    // === 4. 共通施術価格比較 ===
    if (commonProcs.length > 0) {
        html += '<div class="fc-section"><h3 class="fc-section-title">共通施術の価格比較</h3>';
        html += '<div class="fc-price-table-wrap"><table class="fc-price-table"><thead><tr>';
        html += '<th>施術名</th>';
        clinics.forEach(c => {
            html += `<th>${escapeHtml(c.name.substring(0, 10))}</th>`;
        });
        html += '</tr></thead><tbody>';

        commonProcs.forEach(proc => {
            const prices = clinics.map(c => proc.prices[c.id]);
            const validPrices = prices.filter(p => p != null && p > 0);
            const minPrice = validPrices.length > 0 ? Math.min(...validPrices) : null;

            html += `<tr><td class="fc-price-proc">${escapeHtml(proc.name)}</td>`;
            clinics.forEach(c => {
                const price = proc.prices[c.id];
                const isMin = price != null && price === minPrice && validPrices.length > 1;
                if (price != null && price > 0) {
                    const cellSource = (proc.sources && proc.sources[c.id]) || '';
                    const cellBadge = _priceSourceBadge(cellSource);
                    html += `<td class="${isMin ? 'fc-price-best' : ''}">\u00a5${price.toLocaleString()}${cellBadge ? `<span class="fc-price-source">${cellBadge}</span>` : ''}</td>`;
                } else {
                    html += '<td class="fc-price-na">--</td>';
                }
            });
            html += '</tr>';
        });

        html += '</tbody></table></div></div>';
    }

    // === 5. 強み/懸念点 ===
    html += '<div class="fc-section"><h3 class="fc-section-title">特徴</h3>';
    html += '<div class="fc-traits-grid">';
    clinics.forEach(c => {
        html += `<div class="fc-traits-card">
            <div class="fc-traits-name">${escapeHtml(c.name.substring(0, 15))}</div>`;
        if (c.strengths && c.strengths.length > 0) {
            html += '<div class="fc-traits-list fc-traits-good">';
            c.strengths.forEach(s => {
                html += `<span class="fc-trait-tag fc-trait-good">${escapeHtml(s)}</span>`;
            });
            html += '</div>';
        }
        if (c.concerns && c.concerns.length > 0) {
            html += '<div class="fc-traits-list fc-traits-bad">';
            c.concerns.forEach(s => {
                html += `<span class="fc-trait-tag fc-trait-bad">${escapeHtml(s)}</span>`;
            });
            html += '</div>';
        }
        if ((!c.strengths || c.strengths.length === 0) && (!c.concerns || c.concerns.length === 0)) {
            html += '<div class="fc-traits-none">口コミデータ不足</div>';
        }
        html += '</div>';
    });
    html += '</div></div>';

    // === 6. インサイト ===
    if (insights.length > 0) {
        html += '<div class="fc-section fc-insights"><h3 class="fc-section-title">比較インサイト</h3>';
        html += '<ul class="fc-insight-list">';
        insights.forEach(text => {
            html += `<li>${escapeHtml(text)}</li>`;
        });
        html += '</ul></div>';
    }

    return html;
}

// Phase 48: 閲覧履歴の表示
function renderBrowsingHistory() {
    const section = document.getElementById('browsing-history-section');
    const listEl = document.getElementById('browsing-history-list');
    if (!section || !listEl) return;

    const history = browsingContext.getHistory ? browsingContext.getHistory() : [];
    // localStorageから直接取得
    let items = [];
    try {
        const stored = localStorage.getItem('aura_browsing_context');
        if (stored) {
            const data = JSON.parse(stored);
            items = (data.clinics || []).slice(-10).reverse();
        }
    } catch { /* ignore */ }

    if (items.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = '';
    listEl.innerHTML = items.map(item => {
        const time = item.timestamp ? new Date(item.timestamp).toLocaleDateString('ja-JP', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
        return `
            <div class="history-item" onclick="showClinicDetail('${escapeHtml(item.id)}')">
                <div class="history-item-name">${escapeHtml(item.name || '')}</div>
                <div class="history-item-meta">
                    <span class="history-item-area">${escapeHtml(item.city || '')}</span>
                    <span class="history-item-time">${escapeHtml(time)}</span>
                </div>
            </div>
        `;
    }).join('');
}

// トースト通知
function showToast(message) {
    let toast = document.getElementById('aura-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'aura-toast';
        toast.className = 'aura-toast';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('aura-toast--visible');
    setTimeout(() => toast.classList.remove('aura-toast--visible'), 2500);
}

// ==========================================
// Phase 25: カウンセリング準備シート
// ==========================================

/**
 * カウンセリング準備シートを生成
 * お気に入りクリニック + 閲覧した施術情報を集約
 */
async function generatePrepSheet() {
    const modal = document.getElementById('prep-sheet-modal');
    const body = document.getElementById('prep-sheet-body');
    if (!modal || !body) return;

    modal.style.display = 'flex';
    body.innerHTML = '<p class="loading-text">準備シートを生成中...</p>';

    try {
        const favIds = favoritesStore.getAll();
        const viewedProcs = browsingContext.procedures || [];

        // お気に入りクリニック情報を取得
        const clinics = (await Promise.all(
            favIds.map(id => api(`/api/clinics/${id}`).catch(() => null))
        )).filter(Boolean);

        // 閲覧した施術の詳細を取得（最新5件）
        const procIds = [...new Set(viewedProcs.map(p => p.id))].slice(0, 5);
        const procedures = (await Promise.all(
            procIds.map(id => api(`/api/procedures/${id}`).catch(() => null))
        )).filter(Boolean);

        const now = new Date();
        const dateStr = `${now.getFullYear()}/${now.getMonth()+1}/${now.getDate()}`;

        let html = `
            <div class="ps-date">作成日: ${dateStr}</div>
        `;

        // セクション1: 検討中の施術
        if (procedures.length > 0) {
            html += `<div class="ps-section">
                <h3 class="ps-section-title">検討中の施術</h3>`;
            procedures.forEach(p => {
                const pricing = p.pricing || {};
                const realDisplay = pricing.real?.display || '—';
                const questions = p.counseling_questions || [];
                const risks = p.risks || [];

                html += `<div class="ps-proc-card">
                    <div class="ps-proc-name">${escapeHtml(p.name)}</div>
                    <div class="ps-proc-meta">${escapeHtml(p.category_label || '')} ／ ${escapeHtml(p.duration || '')}</div>
                    <div class="ps-proc-price">実際の相場: <strong>${escapeHtml(realDisplay)}</strong></div>
                    ${p.market_price ? `<div class="ps-proc-market">市場中央値: ${escapeHtml(p.market_price.median_display)} (${escapeHtml(p.market_price.range_display)})</div>` : ''}
                    ${risks.length > 0 ? `<div class="ps-subsection">
                        <div class="ps-sub-title">知っておくべきリスク</div>
                        <ul class="ps-list">${risks.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul>
                    </div>` : ''}
                    ${questions.length > 0 ? `<div class="ps-subsection">
                        <div class="ps-sub-title">カウンセリングで聞くこと</div>
                        <ol class="ps-list ps-list--numbered">${questions.map(q => `<li>${escapeHtml(q)}</li>`).join('')}</ol>
                    </div>` : ''}
                </div>`;
            });
            html += '</div>';
        }

        // セクション2: 検討中のクリニック
        if (clinics.length > 0) {
            html += `<div class="ps-section">
                <h3 class="ps-section-title">検討中のクリニック</h3>`;
            clinics.forEach(c => {
                const rs = c.review_summary || {};
                const sentLabel = rs.avg_sentiment > 0.2 ? '好評' : rs.avg_sentiment < -0.2 ? '注意' : '普通';
                const flags = rs.red_flags || {};
                const flagLabels = {pressure_sales:'圧力販売', treatment_trouble:'施術トラブル', staff_issue:'対応問題', billing_issue:'会計問題'};

                html += `<div class="ps-clinic-card">
                    <div class="ps-clinic-name">${escapeHtml(c.name)}</div>
                    <div class="ps-clinic-addr">${escapeHtml(c.address || c.city || '')}</div>
                    ${c.phone ? `<div class="ps-clinic-phone">${escapeHtml(c.phone)}</div>` : ''}
                    <div class="ps-clinic-stats">
                        ${c.google_rating ? `<span>Google ★${c.google_rating}${c.google_review_count ? ` (${c.google_review_count}件)` : ''}</span>` : ''}
                        ${c.transparency_score != null ? `<span>透明性: ${Math.round(c.transparency_score)}pt</span>` : ''}
                        ${rs.total ? `<span>口コミ傾向: ${sentLabel}</span>` : ''}
                    </div>
                    ${Object.keys(flags).length > 0 ? `<div class="ps-flags">
                        <span class="ps-flag-label">注意:</span>
                        ${Object.entries(flags).map(([cat, count]) => `<span class="ps-flag">${flagLabels[cat] || cat}(${count}件)</span>`).join('')}
                    </div>` : ''}
                </div>`;
            });
            html += '</div>';
        }

        // セクション3: 共通の確認事項チェックリスト
        html += `<div class="ps-section">
            <h3 class="ps-section-title">カウンセリング共通チェックリスト</h3>
            <div class="ps-checklist">
                <label class="ps-check"><input type="checkbox"><span>施術の具体的な流れと所要時間を確認した</span></label>
                <label class="ps-check"><input type="checkbox"><span>合計費用（麻酔・アフターケア含む）を確認した</span></label>
                <label class="ps-check"><input type="checkbox"><span>ダウンタイムの実際の期間を確認した</span></label>
                <label class="ps-check"><input type="checkbox"><span>施術を担当する医師の経歴を確認した</span></label>
                <label class="ps-check"><input type="checkbox"><span>リスクと副作用の説明を受けた</span></label>
                <label class="ps-check"><input type="checkbox"><span>修正が必要になった場合の対応を確認した</span></label>
                <label class="ps-check"><input type="checkbox"><span>クーリングオフの条件を確認した</span></label>
                <label class="ps-check"><input type="checkbox"><span>当日契約を迫られていないか確認した</span></label>
            </div>
        </div>`;

        // セクション4: メモ欄
        html += `<div class="ps-section ps-memo-section">
            <h3 class="ps-section-title">メモ</h3>
            <div class="ps-memo" contenteditable="true" placeholder="カウンセリングで気になったことを記録..."></div>
        </div>`;

        html += `<div class="ps-footer">AURA — あなたの理想を、後悔なく叶えるために。</div>`;

        body.innerHTML = html;
    } catch (err) {
        console.warn('準備シート生成に失敗:', err);
        body.innerHTML = '<p class="loading-text">準備シートの生成に失敗しました</p>';
    }
}

/** 準備シートを印刷 */
function printPrepSheet() {
    const body = document.getElementById('prep-sheet-body');
    if (!body) return;
    const printWin = window.open('', '_blank');
    printWin.document.write(`
        <html><head><title>カウンセリング準備シート — AURA</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Noto Sans JP', sans-serif; padding: 20px; color: #333; font-size: 12px; line-height: 1.6; }
            h2 { font-size: 18px; margin-bottom: 8px; }
            h3 { font-size: 14px; margin: 16px 0 8px; border-bottom: 1px solid #ccc; padding-bottom: 4px; }
            .ps-proc-card, .ps-clinic-card { border: 1px solid #ddd; border-radius: 6px; padding: 10px; margin: 8px 0; }
            .ps-proc-name, .ps-clinic-name { font-weight: 700; font-size: 13px; }
            .ps-proc-meta, .ps-clinic-addr, .ps-clinic-phone, .ps-proc-market { color: #666; font-size: 11px; }
            .ps-proc-price { font-size: 12px; margin: 4px 0; }
            .ps-sub-title { font-weight: 600; font-size: 11px; margin-top: 8px; }
            .ps-list { margin-left: 18px; font-size: 11px; }
            .ps-clinic-stats { display: flex; gap: 12px; font-size: 11px; margin-top: 4px; color: #666; }
            .ps-flags { font-size: 11px; color: #c0392b; margin-top: 4px; }
            .ps-checklist { display: grid; gap: 6px; }
            .ps-check { display: flex; gap: 6px; font-size: 11px; }
            .ps-check input { margin-top: 2px; }
            .ps-memo { border: 1px solid #ccc; min-height: 100px; padding: 8px; border-radius: 4px; }
            .ps-footer { margin-top: 20px; text-align: center; font-size: 10px; color: #999; }
            .ps-date { font-size: 11px; color: #999; margin-bottom: 8px; }
            @media print { body { padding: 10px; } }
        </style>
        </head><body>
        <h2>カウンセリング準備シート</h2>
        ${body.innerHTML}
        </body></html>
    `);
    printWin.document.close();
    setTimeout(() => printWin.print(), 300);
}

/** 準備シートモーダルを閉じる */
function closePrepSheet() {
    const modal = document.getElementById('prep-sheet-modal');
    if (modal) modal.style.display = 'none';
}


// ==========================================
// ドクター検索
// ==========================================

let doctorsInitialized = false;

/**
 * ドクターページの初期化
 * エリアセレクトボックスの値をクリニックの区データで埋める
 */
async function initDoctors() {
    doctorsInitialized = true;
    try {
        // クリニックの区データを流用
        const stats = await api('/api/clinics/stats');
        const sel = document.getElementById('doctor-area');
        if (stats.by_city && sel) {
            stats.by_city.forEach(item => {
                const city = item.city || item[0];
                const opt = document.createElement('option');
                opt.value = city;
                opt.textContent = city;
                sel.appendChild(opt);
            });
        }
    } catch (err) { console.warn('エリアデータの取得に失敗:', err); }

    // 統計表示
    loadDoctorStats();
    // 初回検索
    searchDoctors();
}

/**
 * 医師DB統計を表示
 */
async function loadDoctorStats() {
    const el = document.getElementById('doctor-stats');
    if (!el) return;
    try {
        const stats = await api('/api/doctors/stats');
        el.innerHTML = `
            <div class="doctor-stats-grid">
                <div class="doctor-stat-item">
                    <span class="doctor-stat-number">${(stats.total || 0).toLocaleString()}</span>
                    <span class="doctor-stat-label">登録医師数</span>
                </div>
                <div class="doctor-stat-item">
                    <span class="doctor-stat-number">${stats.certification_rate || 0}%</span>
                    <span class="doctor-stat-label">専門医資格保有率</span>
                </div>
                <div class="doctor-stat-item">
                    <span class="doctor-stat-number">${stats.with_trust_score || 0}</span>
                    <span class="doctor-stat-label">スコア算出済み</span>
                </div>
                ${stats.avg_trust_score ? `
                <div class="doctor-stat-item">
                    <span class="doctor-stat-number">${stats.avg_trust_score}</span>
                    <span class="doctor-stat-label">平均スコア</span>
                </div>` : ''}
            </div>
            <p class="doctor-stats-note">${escapeHtml(stats.note || '')}</p>
        `;
    } catch (err) { console.warn('医師統計の取得に失敗:', err); }
}

/**
 * ドクター検索実行
 */
async function searchDoctors(page = 1) {
    const q = document.getElementById('doctor-q')?.value?.trim() || '';
    const area = document.getElementById('doctor-area')?.value || '';
    const certOnly = document.getElementById('doctor-cert-filter')?.checked || false;
    const sort = document.getElementById('doctor-sort')?.value || 'score';
    const listEl = document.getElementById('doctor-list');
    const pagerEl = document.getElementById('doctor-pager');
    const showAll = document.getElementById('doctor-show-all')?.checked || false;

    if (!listEl) return;
    listEl.innerHTML = renderSkeletons(5);

    // フリーワード検索がある場合は検索APIを使用
    if (q) {
        try {
            const params = new URLSearchParams({ q, page, per_page: 20 });
            const data = await api(`/api/doctors/search?${params}`);
            renderDoctorList(data, page, listEl, pagerEl);
        } catch (err) {
            showError('doctor-list', '医師の検索に失敗しました', () => searchDoctors(page));
        }
        return;
    }

    // フィルタ付き一覧取得
    const params = new URLSearchParams({ page, per_page: 20, sort_by: sort });
    if (area) params.set('city', area);
    if (certOnly) params.set('has_certification', 'true');
    if (showAll) params.set('show_all', 'true');

    try {
        const data = await api(`/api/doctors/?${params}`);
        renderDoctorList(data, page, listEl, pagerEl);
    } catch (err) {
        showError('doctor-list', '医師情報の読み込みに失敗しました', () => searchDoctors(page));
    }
}

/**
 * ドクター一覧をレンダリング
 */
function renderDoctorList(data, page, listEl, pagerEl) {
    const doctors = data.doctors || [];
    const resultEl = document.getElementById('doctor-result-count');

    if (doctors.length === 0) {
        listEl.innerHTML = '<p class="loading-text">該当する医師が見つかりませんでした</p>';
        if (pagerEl) pagerEl.innerHTML = '';
        if (resultEl) resultEl.textContent = '';
        return;
    }

    if (resultEl) {
        resultEl.textContent = `${data.total}名の医師`;
    }

    listEl.innerHTML = doctors.map(d => renderDoctorCard(d)).join('');

    // ページャー
    if (pagerEl) {
        const totalPages = data.total_pages || Math.ceil((data.total || 0) / 20);
        if (totalPages > 1) {
            let btns = '';
            if (page > 1) btns += `<button class="pager-btn" onclick="searchDoctors(${page-1})">前へ</button>`;
            for (let p = Math.max(1, page-2); p <= Math.min(totalPages, page+2); p++) {
                btns += `<button class="pager-btn ${p===page?'active':''}" onclick="searchDoctors(${p})">${p}</button>`;
            }
            if (page < totalPages) btns += `<button class="pager-btn" onclick="searchDoctors(${page+1})">次へ</button>`;
            pagerEl.innerHTML = `<nav aria-label="ページネーション">${btns}</nav>`;
        } else {
            pagerEl.innerHTML = '';
        }
    }
}

/**
 * 医師カードのHTMLを生成
 * 情報開示スコアバッジ + 資格 + 経験年数 + 所属クリニック
 */
function renderDoctorCard(d) {
    const score = d.trust_score;
    const level = d.trust_level || {};
    const certs = d.certifications || [];
    const specs = d.specialties || [];
    const clinic = d.clinic || {};

    // スコアバッジの色とラベル（閾値による3段階表示）
    let scoreHtml = '';
    if (score !== null && score !== undefined) {
        if (score >= 30) {
            // 30pt以上: SVGリング表示
            const color = level.color || '#9E9E9E';
            const label = (level.label || '未評価').replace('信頼', '開示');
            scoreHtml = `
                <div class="doctor-score-badge" style="--score-color: ${color}">
                    <div class="doctor-score-ring">
                        <svg viewBox="0 0 36 36" class="doctor-score-svg">
                            <path class="doctor-score-bg" d="M18 2.0845
                                a 15.9155 15.9155 0 0 1 0 31.831
                                a 15.9155 15.9155 0 0 1 0 -31.831" />
                            <path class="doctor-score-fill" stroke="${color}" stroke-dasharray="${score}, 100" d="M18 2.0845
                                a 15.9155 15.9155 0 0 1 0 31.831
                                a 15.9155 15.9155 0 0 1 0 -31.831" />
                        </svg>
                        <span class="doctor-score-number">${Math.round(score)}</span>
                    </div>
                    <span class="doctor-score-label">${escapeHtml(label)}</span>
                </div>
            `;
        } else if (score >= 20) {
            // 20-29pt: テキストのみ（リングなし）
            scoreHtml = `
                <div class="doctor-score-badge doctor-score-badge--text-only">
                    <span class="doctor-score-number-text">${Math.round(score)}</span>
                    <span class="doctor-score-label">情報限定</span>
                </div>
            `;
        } else {
            // 20pt未満: スコア非表示、「情報収集中」
            scoreHtml = `
                <div class="doctor-score-badge doctor-score-badge--pending">
                    <span class="doctor-score-pending-icon">—</span>
                    <span class="doctor-score-label">情報収集中</span>
                </div>
            `;
        }
    }

    // 資格バッジ
    const certHtml = certs.length > 0
        ? certs.slice(0, 2).map(c => `<span class="doctor-cert-tag">${escapeHtml(c)}</span>`).join('')
        : '';

    // JSAPSバッジ
    const jsapsHtml = d.jsaps_certified
        ? '<span class="doctor-cert-tag doctor-cert-tag--jsaps">JSAPS専門医</span>'
        : '';

    // 専門分野
    const specHtml = specs.length > 0
        ? `<div class="doctor-specs">専門: ${specs.slice(0, 3).map(s => escapeHtml(s)).join(', ')}</div>`
        : '';

    // 経験年数
    const expHtml = d.experience_years
        ? `<span class="doctor-exp">経験${d.experience_years}年</span>`
        : '';

    // 勤務経歴
    const bgHtml = d.hospital_background
        ? `<div class="doctor-background"><span class="doctor-bg-label">経歴</span> ${escapeHtml(d.hospital_background.substring(0, 35))}</div>`
        : '';

    // 所属クリニック
    const clinicHtml = clinic.name
        ? `<div class="doctor-clinic">
            <span class="doctor-clinic-name">${escapeHtml(clinic.name)}</span>
            ${clinic.city ? `<span class="doctor-clinic-area">${escapeHtml(clinic.city)}</span>` : ''}
           </div>`
        : '';

    // 医師写真サムネイル
    const photoHtml = d.photo_url
        ? `<div class="doctor-photo"><img src="${escapeHtml(d.photo_url)}" alt="${escapeHtml(d.name)}" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\'doctor-photo-placeholder\'>👤</span>'"></div>`
        : `<div class="doctor-photo"><span class="doctor-photo-placeholder">👤</span></div>`;

    return `
        <div class="doctor-card" onclick="showDoctorDetail('${escapeHtml(d.id || '')}')" style="cursor:pointer;">
            ${scoreHtml}
            <div class="doctor-card-info">
                <div class="doctor-card-header">
                    ${photoHtml}
                    <div class="doctor-card-header-text">
                        <span class="doctor-name">${escapeHtml(d.name)}</span>
                        ${d.title ? `<span class="doctor-title">${escapeHtml(d.title)}</span>` : ''}
                        ${expHtml}
                    </div>
                </div>
                ${(jsapsHtml || certHtml) ? `<div class="doctor-certs">${jsapsHtml}${certHtml}</div>` : ''}
                ${specHtml}
                ${bgHtml}
                ${clinicHtml}
            </div>
        </div>
    `;
}

// ドクター検索イベントリスナー
const doctorSearchBtn = document.getElementById('doctor-search-btn');
if (doctorSearchBtn) {
    doctorSearchBtn.addEventListener('click', () => searchDoctors(1));
}
const doctorQ = document.getElementById('doctor-q');
if (doctorQ) {
    doctorQ.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') searchDoctors(1);
    });
}

// ==========================================
// 医師詳細パネル
// ==========================================

/**
 * 医師詳細オーバーレイを表示
 * GET /api/doctors/{id} から全情報を取得し表示
 */
async function showDoctorDetail(doctorId) {
    if (!doctorId) return;
    const overlay = document.getElementById('doctor-detail-overlay');
    const body = document.getElementById('doctor-detail-body');
    if (!overlay || !body) return;

    overlay.style.display = 'flex';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    body.innerHTML = renderSkeletons(3);
    document.body.style.overflow = 'hidden';

    try {
        const d = await api(`/api/doctors/${doctorId}`);

        // browsingContext追跡
        if (typeof browsingContext !== 'undefined') {
            browsingContext.trackDoctor(d.id, d.name);
        }

        // 情報開示スコア — SVGリング大表示
        let scoreHtml = '';
        const score = d.trust_score;
        if (score !== null && score !== undefined && score >= 20) {
            const color = score >= 70 ? '#4CAF50' : score >= 50 ? '#2196F3' : score >= 30 ? '#FF9800' : '#9E9E9E';
            const pct = Math.min(score, 100);
            scoreHtml = `
                <div class="dd-score-section">
                    <div class="dd-score-ring" style="--dd-color: ${color}">
                        <svg viewBox="0 0 36 36" class="dd-score-svg">
                            <path class="dd-score-bg" d="M18 2.0845
                                a 15.9155 15.9155 0 0 1 0 31.831
                                a 15.9155 15.9155 0 0 1 0 -31.831" />
                            <path class="dd-score-fill" stroke="${color}" stroke-dasharray="${pct}, 100" d="M18 2.0845
                                a 15.9155 15.9155 0 0 1 0 31.831
                                a 15.9155 15.9155 0 0 1 0 -31.831" />
                        </svg>
                        <span class="dd-score-num">${Math.round(score)}</span>
                    </div>
                    <span class="dd-score-title">情報開示スコア</span>
                </div>`;
        }

        // 5軸スコア内訳（v4: APIレスポンスのto_dict()から動的生成）
        let breakdownHtml = '';
        const bd = d.trust_score_breakdown;
        if (bd) {
            const axisKeys = ['certification', 'background', 'experience', 'case_volume', 'data_completeness'];
            const bars = axisKeys.map(key => {
                const axis = bd[key];
                if (!axis) return '';
                const val = axis.score || 0;
                const max = axis.max || 25;
                const label = axis.label || key;
                const pct = Math.round(val / max * 100);
                return `<div class="dd-axis">
                    <span class="dd-axis-label">${escapeHtml(label)}</span>
                    <div class="dd-axis-bar"><div class="dd-axis-fill" style="width:${pct}%"></div></div>
                    <span class="dd-axis-val">${val}/${max}</span>
                </div>`;
            }).filter(Boolean).join('');
            breakdownHtml = `<div class="dd-breakdown">${bars}</div>`;
        }

        // 資格バッジ
        const certs = d.certifications || [];
        const jsapsHtml = d.jsaps_certified
            ? '<span class="doctor-cert-tag doctor-cert-tag--jsaps">JSAPS専門医</span>'
            : '';
        const certBadges = certs.slice(0, 3).map(c =>
            `<span class="doctor-cert-tag">${escapeHtml(c)}</span>`
        ).join('');
        const certsSection = (jsapsHtml || certBadges)
            ? `<div class="dd-certs">${jsapsHtml}${certBadges}</div>`
            : '';

        // 専門分野
        const specs = d.specialties || [];
        const specsHtml = specs.length > 0
            ? `<div class="dd-info-row"><span class="dd-info-label">専門分野</span><span class="dd-info-val">${escapeHtml(specs.join(' / '))}</span></div>`
            : '';

        // 経験年数
        const expHtml = d.experience_years
            ? `<div class="dd-info-row"><span class="dd-info-label">経験年数</span><span class="dd-info-val">${d.experience_years}年</span></div>`
            : '';

        // 勤務経歴
        const bgHtml = d.hospital_background
            ? `<div class="dd-info-row"><span class="dd-info-label">勤務経歴</span><span class="dd-info-val">${escapeHtml(d.hospital_background)}</span></div>`
            : '';

        // 年間症例数
        const caseHtml = d.annual_case_count
            ? `<div class="dd-info-row"><span class="dd-info-label">年間症例数</span><span class="dd-info-val">${d.annual_case_count}件</span></div>`
            : '';

        // 所属クリニック
        let clinicHtml = '';
        const clinic = d.clinic;
        if (clinic) {
            clinicHtml = `
                <div class="dd-clinic" onclick="event.stopPropagation(); document.getElementById('doctor-detail-overlay').style.display='none'; document.body.style.overflow=''; showClinicDetail('${escapeHtml(clinic.id)}');" style="cursor:pointer;">
                    <span class="dd-clinic-label">所属クリニック</span>
                    <div class="dd-clinic-card">
                        <span class="dd-clinic-name">${escapeHtml(clinic.name)}</span>
                        ${clinic.city ? `<span class="dd-clinic-city">${escapeHtml(clinic.city)}</span>` : ''}
                        ${clinic.google_rating ? `<span class="dd-clinic-rating">★ ${clinic.google_rating}</span>` : ''}
                        <span class="dd-clinic-link">詳細を見る →</span>
                    </div>
                </div>`;
        }

        // データ品質ノート
        const noteHtml = d.data_quality_note
            ? `<div class="dd-note">${escapeHtml(d.data_quality_note)}</div>`
            : '';

        // 医師写真
        const photoHtml = d.photo_url
            ? `<div class="dd-photo"><img src="${escapeHtml(d.photo_url)}" alt="${escapeHtml(d.name)}" onerror="this.parentElement.style.display='none'"></div>`
            : '';

        // SNSリンク
        let snsHtml = '';
        const sns = d.sns || {};
        const snsLinks = [];
        if (sns.instagram) snsLinks.push(`<a href="${escapeHtml(sns.instagram)}" target="_blank" rel="noopener" class="dd-sns-link dd-sns-ig" title="Instagram">📷 Instagram</a>`);
        if (sns.twitter) snsLinks.push(`<a href="${escapeHtml(sns.twitter)}" target="_blank" rel="noopener" class="dd-sns-link dd-sns-tw" title="X (Twitter)">𝕏 X</a>`);
        if (sns.tiktok) snsLinks.push(`<a href="${escapeHtml(sns.tiktok)}" target="_blank" rel="noopener" class="dd-sns-link dd-sns-tt" title="TikTok">🎵 TikTok</a>`);
        if (sns.youtube) snsLinks.push(`<a href="${escapeHtml(sns.youtube)}" target="_blank" rel="noopener" class="dd-sns-link dd-sns-yt" title="YouTube">▶ YouTube</a>`);
        if (snsLinks.length > 0) {
            snsHtml = `<div class="dd-sns">${snsLinks.join('')}</div>`;
        }

        body.innerHTML = `
            <div class="dd-header">
                ${photoHtml}
                <div class="dd-identity">
                    <span class="dd-title">${escapeHtml(d.title || '医師')}</span>
                    <h2 class="dd-name">${escapeHtml(d.name)}</h2>
                </div>
                ${scoreHtml}
            </div>
            ${certsSection}
            ${snsHtml}
            ${breakdownHtml}
            <div class="dd-info-block">
                ${specsHtml}${expHtml}${bgHtml}${caseHtml}
            </div>
            ${clinicHtml}
            ${noteHtml}
            <button class="review-advisor-link" onclick="document.getElementById('doctor-detail-overlay').style.display='none'; document.body.style.overflow=''; navigate('advisor'); setTimeout(() => { document.getElementById('chat-input').value='${escapeHtml(d.name)}先生について教えてください。経歴や専門分野を踏まえた評価を知りたいです'; sendChat(); }, 300);">
                ${escapeHtml(d.name)}先生についてアドバイザーに相談する
            </button>
        `;

    } catch (err) {
        console.warn('医師詳細の取得に失敗:', err);
        body.innerHTML = '<p class="loading-text">医師情報の取得に失敗しました</p>';
    }
}

// 医師詳細パネルの閉じるイベント
const doctorDetailClose = document.getElementById('doctor-detail-close');
if (doctorDetailClose) {
    doctorDetailClose.addEventListener('click', () => {
        document.getElementById('doctor-detail-overlay').style.display = 'none';
        document.body.style.overflow = '';
    });
}
document.getElementById('doctor-detail-overlay')?.addEventListener('click', (e) => {
    if (e.target.classList.contains('overlay')) {
        document.getElementById('doctor-detail-overlay').style.display = 'none';
        document.body.style.overflow = '';
    }
});

// ==========================================
// Phase 24: グローバル横断検索
// ==========================================

(() => {
    const toggle = document.getElementById('global-search-toggle');
    const bar = document.getElementById('global-search-bar');
    const input = document.getElementById('global-search-input');
    const results = document.getElementById('global-search-results');
    if (!toggle || !bar || !input || !results) return;

    let debounceTimer = null;
    let isOpen = false;

    /** 検索バーの表示/非表示 */
    function toggleSearch() {
        isOpen = !isOpen;
        bar.style.display = isOpen ? '' : 'none';
        toggle.classList.toggle('active', isOpen);
        if (isOpen) {
            input.focus();
        } else {
            input.value = '';
            results.innerHTML = '';
        }
    }

    toggle.addEventListener('click', toggleSearch);

    // Cmd+K / Ctrl+K ショートカット
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            toggleSearch();
        }
        if (e.key === 'Escape' && isOpen) {
            toggleSearch();
        }
    });

    // 検索バー外クリックで閉じる
    document.addEventListener('click', (e) => {
        if (isOpen && !bar.contains(e.target) && !toggle.contains(e.target)) {
            toggleSearch();
        }
    });

    /** デバウンス付き検索 */
    input.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const q = input.value.trim();
        if (q.length < 2) {
            results.innerHTML = '';
            return;
        }
        debounceTimer = setTimeout(() => runGlobalSearch(q), 500);
    });

    /** 並列API検索 */
    async function runGlobalSearch(query) {
        results.innerHTML = '<div class="gs-loading">検索中...</div>';

        try {
            const [procRes, clinicRes, docRes] = await Promise.allSettled([
                api(`/api/procedures?q=${encodeURIComponent(query)}&per_page=5`),
                api(`/api/clinics?q=${encodeURIComponent(query)}&per_page=5`),
                api(`/api/doctors?q=${encodeURIComponent(query)}&per_page=5`),
            ]);

            const procs = procRes.status === 'fulfilled' ? (procRes.value.procedures || []) : [];
            const clinics = clinicRes.status === 'fulfilled' ? (clinicRes.value.clinics || []) : [];
            const docs = docRes.status === 'fulfilled' ? (docRes.value.doctors || []) : [];

            if (procs.length === 0 && clinics.length === 0 && docs.length === 0) {
                results.innerHTML = '<div class="gs-empty">見つかりませんでした</div>';
                return;
            }

            let html = '';

            if (procs.length > 0) {
                html += '<div class="gs-category"><span class="gs-category-label">施術</span>';
                html += procs.map(p => `
                    <div class="gs-item" onclick="document.getElementById('global-search-bar').style.display='none'; document.getElementById('global-search-toggle').classList.remove('active'); navigate('procedures'); setTimeout(() => showDetail('${escapeHtml(p.id)}'), 200);">
                        <span class="gs-item-name">${escapeHtml(p.name)}</span>
                        <span class="gs-item-meta">${escapeHtml(p.category_label || p.category || '')}</span>
                    </div>
                `).join('');
                html += '</div>';
            }

            if (clinics.length > 0) {
                html += '<div class="gs-category"><span class="gs-category-label">クリニック</span>';
                html += clinics.map(c => `
                    <div class="gs-item" onclick="document.getElementById('global-search-bar').style.display='none'; document.getElementById('global-search-toggle').classList.remove('active'); showClinicDetail('${escapeHtml(c.id)}');">
                        <span class="gs-item-name">${escapeHtml(c.name)}</span>
                        <span class="gs-item-meta">${escapeHtml(c.city || '')}${c.google_rating ? ` ★${c.google_rating.toFixed(1)}` : ''}</span>
                    </div>
                `).join('');
                html += '</div>';
            }

            if (docs.length > 0) {
                html += '<div class="gs-category"><span class="gs-category-label">医師</span>';
                html += docs.map(d => `
                    <div class="gs-item" onclick="document.getElementById('global-search-bar').style.display='none'; document.getElementById('global-search-toggle').classList.remove('active'); showDoctorDetail('${escapeHtml(d.id)}');">
                        <span class="gs-item-name">${escapeHtml(d.name)}</span>
                        <span class="gs-item-meta">${escapeHtml((d.specialties || []).slice(0, 2).join(', ') || '')}</span>
                    </div>
                `).join('');
                html += '</div>';
            }

            results.innerHTML = html;
        } catch {
            results.innerHTML = '<div class="gs-empty">検索に失敗しました</div>';
        }
    }
})();

// ==========================================
// Phase 26: 施術比較機能
// ==========================================

let procCompareList = []; // 最大4件: { id, name }

/**
 * 施術比較チェックボックスのトグル
 */
function toggleProcCompare(checkbox) {
    const procId = checkbox.dataset.procId;
    const procName = checkbox.dataset.procName;

    if (checkbox.checked) {
        if (procCompareList.length >= 4) {
            checkbox.checked = false;
            showToast('比較できる施術は最大4件です');
            return;
        }
        procCompareList.push({ id: procId, name: procName });
    } else {
        procCompareList = procCompareList.filter(item => item.id !== procId);
    }
    updateProcCompareBar();
}

/**
 * 施術比較バーの更新
 */
function updateProcCompareBar() {
    const bar = document.getElementById('proc-compare-bar');
    const itemsEl = document.getElementById('proc-compare-bar-items');

    if (procCompareList.length === 0) {
        bar.style.display = 'none';
        return;
    }

    bar.style.display = 'flex';
    itemsEl.innerHTML = procCompareList.map(p => `
        <span class="compare-bar-item">
            ${escapeHtml(p.name)}
            <span class="compare-bar-item-remove" onclick="removeProcCompare('${escapeHtml(p.id)}')">&times;</span>
        </span>
    `).join('');
}

/**
 * 施術比較リストから削除
 */
function removeProcCompare(procId) {
    procCompareList = procCompareList.filter(item => item.id !== procId);
    updateProcCompareBar();
    const checkbox = document.querySelector(`.proc-compare-checkbox[data-proc-id="${procId}"]`);
    if (checkbox) checkbox.checked = false;
}

/**
 * 施術比較パネルを表示
 */
async function showProcComparePanel() {
    if (procCompareList.length < 2) {
        showToast('比較するには2件以上選択してください');
        return;
    }

    const overlay = document.getElementById('proc-compare-overlay');
    const body = document.getElementById('proc-compare-body');
    overlay.style.display = 'flex';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    body.innerHTML = '<p class="loading-text">比較データを読み込み中</p>';

    try {
        const ids = procCompareList.map(p => p.id).join(',');
        const data = await api(`/api/procedures/compare?ids=${ids}`);
        const procs = data.procedures || [];

        if (procs.length < 2) {
            body.innerHTML = '<p class="loading-text">比較できる施術が2件未満です</p>';
            return;
        }

        body.innerHTML = procs.map(p => {
            const pricing = p.pricing || {};
            const dt = p.downtime || {};
            const risks = p.risks || [];
            const sat = p.satisfaction || {};
            const questions = p.counseling_questions || [];

            return `
                <div class="compare-col">
                    <div class="compare-col-name">${escapeHtml(p.name)}</div>
                    <div class="compare-row">
                        <span class="compare-row-label">カテゴリ</span>
                        <span class="compare-row-value">${escapeHtml(p.category_label || p.category || '—')}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">侵襲度</span>
                        <span class="compare-row-value">${escapeHtml(p.invasiveness || '—')}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">広告価格</span>
                        <span class="compare-row-value">${escapeHtml(pricing.advertised_display || '—')}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">実際の価格</span>
                        <span class="compare-row-value compare-row-value--accent">${escapeHtml(pricing.real_display || '—')}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">DT（公式）</span>
                        <span class="compare-row-value">${escapeHtml(dt.official || '—')}</span>
                    </div>
                    <div class="compare-row">
                        <span class="compare-row-label">DT（実際）</span>
                        <span class="compare-row-value compare-row-value--accent">${escapeHtml(dt.real || '—')}</span>
                    </div>
                    ${sat.rate ? `
                    <div class="compare-row">
                        <span class="compare-row-label">満足度</span>
                        <span class="compare-row-value">${sat.rate}%</span>
                    </div>` : ''}
                    <div class="compare-row">
                        <span class="compare-row-label">リスク</span>
                        <span class="compare-row-value compare-row-value--small">${risks.length > 0 ? risks.map(r => escapeHtml(r)).join('<br>') : '—'}</span>
                    </div>
                    ${questions.length > 0 ? `
                    <div class="compare-row">
                        <span class="compare-row-label">質問</span>
                        <span class="compare-row-value compare-row-value--small">${questions.slice(0, 3).map(q => escapeHtml(q)).join('<br>')}</span>
                    </div>` : ''}
                    <button class="compare-detail-btn" onclick="document.getElementById('proc-compare-overlay').style.display='none'; showDetail('${escapeHtml(p.id)}')">詳細を見る</button>
                </div>
            `;
        }).join('');
    } catch {
        body.innerHTML = '<p class="loading-text">比較データの取得に失敗しました</p>';
    }
}

// 施術比較ボタン
document.getElementById('proc-compare-btn')?.addEventListener('click', showProcComparePanel);

// 施術比較パネル閉じる
document.getElementById('proc-compare-close')?.addEventListener('click', () => {
    document.getElementById('proc-compare-overlay').style.display = 'none';
});
document.getElementById('proc-compare-overlay')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) e.currentTarget.style.display = 'none';
});

// ==========================================
// Phase 27: Deep Linking — URL初期ルーティング
// ==========================================

(() => {
    const path = window.location.pathname;

    // /procedures/xxx → 施術詳細を開く
    const procMatch = path.match(/^\/procedures\/([^/]+)$/);
    if (procMatch) {
        navigate('procedures');
        setTimeout(() => showDetail(procMatch[1]), 400);
        return;
    }

    // /clinics/xxx → クリニック詳細を開く
    const clinicMatch = path.match(/^\/clinics\/([^/]+)$/);
    if (clinicMatch) {
        navigate('clinics');
        setTimeout(() => showClinicDetail(clinicMatch[1]), 400);
        return;
    }

    // /doctors/xxx → 医師詳細を開く
    const doctorMatch = path.match(/^\/doctors\/([^/]+)$/);
    if (doctorMatch) {
        navigate('doctors');
        setTimeout(() => showDoctorDetail(doctorMatch[1]), 400);
        return;
    }

    // /procedures, /clinics, /doctors, /advisor, /favorites → ページ遷移
    const pageMap = {
        '/procedures': 'procedures',
        '/clinics': 'clinics',
        '/doctors': 'doctors',
        '/advisor': 'advisor',
        '/favorites': 'favorites',
    };
    if (pageMap[path]) {
        navigate(pageMap[path]);
    }
})();

// ==========================================
// Phase 28: タイムライン表示
// ==========================================

/**
 * 施術の回復タイムラインをロードして表示
 */
async function loadTimeline(procedureId) {
    const container = document.getElementById(`timeline-section-${procedureId}`);
    if (!container) return;

    try {
        const data = await api(`/api/procedures/${procedureId}/timeline`);
        const phases = data.phases || [];

        if (phases.length === 0) {
            container.style.display = 'none';
            return;
        }

        const colors = ['#FF6B6B', '#FFA94D', '#FFD43B', '#69DB7C', '#4ECDC4', '#74C0FC'];

        let html = `
            <div class="detail-block-title">回復タイムライン</div>
            <div class="timeline-bar">
                ${phases.map((ph, i) => `
                    <div class="timeline-phase" style="background: ${colors[i % colors.length]}20; border-left: 3px solid ${colors[i % colors.length]};" onclick="this.classList.toggle('timeline-phase--expanded')">
                        <div class="timeline-phase-header">
                            <span class="timeline-phase-num">${ph.phase_number}</span>
                            <span class="timeline-phase-label">${escapeHtml(ph.label)}</span>
                            <span class="timeline-phase-duration">${escapeHtml(ph.duration)}</span>
                        </div>
                        <div class="timeline-phase-detail">
                            ${ph.symptoms?.length ? `<div class="tl-row"><strong>症状:</strong> ${ph.symptoms.map(s => escapeHtml(s)).join('、')}</div>` : ''}
                            ${ph.do?.length ? `<div class="tl-row tl-do"><strong>やるべきこと:</strong> ${ph.do.map(d => escapeHtml(d)).join('、')}</div>` : ''}
                            ${ph.avoid?.length ? `<div class="tl-row tl-avoid"><strong>避けること:</strong> ${ph.avoid.map(a => escapeHtml(a)).join('、')}</div>` : ''}
                        </div>
                    </div>
                `).join('')}
            </div>
            ${data.total_recovery_days ? `<div class="timeline-total">完全回復まで約${data.total_recovery_days}日</div>` : ''}
        `;

        container.innerHTML = html;
    } catch {
        container.style.display = 'none';
    }
}

// ==========================================
// Phase 29: 口コミ要約 — クリニック詳細パネルに統合
// ==========================================

/**
 * クリニックの口コミ要約をロードして表示
 */
async function loadReviewSummary(clinicId) {
    const container = document.getElementById(`review-summary-${clinicId}`);
    if (!container) return;

    try {
        const data = await api(`/api/clinics/${clinicId}/review-summary`);

        if (!data.total_reviews || data.total_reviews === 0) {
            container.innerHTML = '<p class="review-summary-empty">口コミデータはまだありません</p>';
            return;
        }

        const sd = data.sentiment_distribution || {};
        const topics = data.topics || [];
        const hl = data.highlights || {};
        const rf = data.red_flag_summary || {};
        const trend = data.trend || {};

        let html = `
            <div class="detail-block-title">口コミの傾向</div>
            <div class="rs-overview">
                <span class="rs-total">${data.total_reviews}件の口コミ</span>
                <span class="rs-avg">平均 ★${(data.avg_rating || 0).toFixed(1)}</span>
                ${trend.direction ? `<span class="rs-trend rs-trend--${trend.direction}">${trend.direction === 'improving' ? '↑ 改善傾向' : trend.direction === 'declining' ? '↓ 低下傾向' : '→ 安定'}</span>` : ''}
            </div>

            <div class="rs-sentiment">
                <div class="rs-bar">
                    <div class="rs-bar-pos" style="width:${sd.positive || 0}%" title="ポジティブ ${sd.positive || 0}%"></div>
                    <div class="rs-bar-neu" style="width:${sd.neutral || 0}%" title="ニュートラル ${sd.neutral || 0}%"></div>
                    <div class="rs-bar-neg" style="width:${sd.negative || 0}%" title="ネガティブ ${sd.negative || 0}%"></div>
                </div>
                <div class="rs-bar-labels">
                    <span>${sd.positive || 0}% pos</span>
                    <span>${sd.neutral || 0}% neu</span>
                    <span>${sd.negative || 0}% neg</span>
                </div>
            </div>`;

        if (topics.length > 0) {
            html += `<div class="rs-topics">`;
            const maxCount = Math.max(...topics.map(t => t.count));
            topics.forEach(t => {
                const sentClass = t.avg_sentiment > 0.2 ? 'rs-topic--pos' : t.avg_sentiment < -0.2 ? 'rs-topic--neg' : 'rs-topic--neu';
                html += `
                    <div class="rs-topic-row">
                        <span class="rs-topic-name">${escapeHtml(t.topic)}</span>
                        <div class="rs-topic-bar-bg">
                            <div class="rs-topic-bar ${sentClass}" style="width:${(t.count / maxCount) * 100}%"></div>
                        </div>
                        <span class="rs-topic-count">${t.count}件</span>
                    </div>`;
            });
            html += `</div>`;
        }

        if (hl.strengths?.length || hl.concerns?.length) {
            html += `<div class="rs-highlights">`;
            if (hl.strengths?.length) {
                html += `<div class="rs-hl-group rs-hl-good">
                    <div class="rs-hl-title">良い点</div>
                    ${hl.strengths.slice(0, 5).map(s => `<span class="rs-hl-item">${escapeHtml(s)}</span>`).join('')}
                </div>`;
            }
            if (hl.concerns?.length) {
                html += `<div class="rs-hl-group rs-hl-concern">
                    <div class="rs-hl-title">注意すべき点</div>
                    ${hl.concerns.slice(0, 5).map(c => `<span class="rs-hl-item">${escapeHtml(c)}</span>`).join('')}
                </div>`;
            }
            html += `</div>`;
        }

        if (rf.total > 0) {
            const rfLabels = { pressure_sales: '圧力販売', treatment_trouble: '施術トラブル', staff_issue: 'スタッフ問題', billing_issue: '会計問題' };
            html += `<div class="rs-redflags">
                <div class="rs-rf-title">レッドフラグ (${rf.total}件)</div>
                <div class="rs-rf-cats">${Object.entries(rf.categories || {}).filter(([,v]) => v > 0).map(([k,v]) => `<span class="rs-rf-cat">${escapeHtml(rfLabels[k] || k)}: ${v}件</span>`).join('')}</div>
            </div>`;
        }

        container.innerHTML = html;
    } catch {
        container.innerHTML = '';
    }
}

// ==========================================
// Phase 30: 通知チェック
// ==========================================

/**
 * お気に入りクリニックの通知をチェック
 */
async function checkNotifications() {
    const banner = document.getElementById('notification-banner');
    if (!banner) return;

    try {
        const favIds = JSON.parse(localStorage.getItem('aura_favorites') || '[]');
        if (favIds.length === 0) {
            banner.style.display = 'none';
            return;
        }

        const data = await api(`/api/notifications?favorite_ids=${favIds.join(',')}`);
        const notifications = data.notifications || [];

        if (notifications.length === 0) {
            banner.style.display = 'none';
            return;
        }

        // お気に入りのバッジ更新
        const favBadge = document.querySelector('.bottom-nav-item[data-page="favorites"] span');
        if (favBadge && data.unread_count > 0) {
            favBadge.setAttribute('data-badge', data.unread_count);
        }

        const severityIcons = { warning: '!', caution: 'i', info: 'i' };

        banner.innerHTML = `
            <div class="notif-header">
                <span class="notif-title">お気に入りの更新情報</span>
                <button class="notif-close" onclick="this.closest('.notification-banner').style.display='none'">&times;</button>
            </div>
            <div class="notif-list">
                ${notifications.slice(0, 5).map(n => `
                    <div class="notif-item notif-item--${n.severity}" onclick="showClinicDetail('${escapeHtml(n.clinic_id)}')">
                        <span class="notif-icon">${severityIcons[n.severity] || 'ℹ️'}</span>
                        <div class="notif-content">
                            <span class="notif-clinic">${escapeHtml(n.clinic_name)}</span>
                            <span class="notif-msg">${escapeHtml(n.message)}</span>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
        banner.style.display = 'block';
    } catch {
        banner.style.display = 'none';
    }
}

// アプリ起動時に通知をチェック
requestIdleCallback(() => checkNotifications());

// ==========================================
// Phase 27: シェア機能
// ==========================================

/**
 * 施術リンクをクリップボードにコピー
 */
async function shareProcedure(id, name) {
    const url = `${window.location.origin}/procedures/${id}`;
    try {
        await navigator.clipboard.writeText(url);
        showToast(`「${name}」のリンクをコピーしました`);
    } catch {
        showToast('リンクのコピーに失敗しました');
    }
}

/**
 * クリニックリンクをクリップボードにコピー
 */
async function shareClinic(id, name) {
    const url = `${window.location.origin}/clinics/${id}`;
    try {
        await navigator.clipboard.writeText(url);
        showToast(`「${name}」のリンクをコピーしました`);
    } catch {
        showToast('リンクのコピーに失敗しました');
    }
}

/**
 * 医師リンクをクリップボードにコピー
 */
async function shareDoctor(id, name) {
    const url = `${window.location.origin}/doctors/${id}`;
    try {
        await navigator.clipboard.writeText(url);
        showToast(`「${name}」のリンクをコピーしました`);
    } catch {
        showToast('リンクのコピーに失敗しました');
    }
}

// ==========================================
// Phase 32: APIキャッシュ（パフォーマンス最適化）
// ==========================================

(() => {
    const cache = new Map();
    const CACHE_TTL = 60000; // 60秒

    const origApi = window.api || api;
    // キャッシュ対象: GET系のリスト取得（パラメータなしまたは少ないもの）
    const cacheablePatterns = [
        /^\/api\/procedures\/?$/,
        /^\/api\/procedures\/categories$/,
        /^\/api\/procedures\/stats$/,
        /^\/api\/clinics\/stats$/,
        /^\/api\/doctors\/stats$/,
        /^\/api\/analysis\//,
    ];

    // apiラッパーをグローバルに再定義せず、キャッシュはloadTimeline等の内部で利用
    window._apiCache = {
        get(url) {
            const entry = cache.get(url);
            if (entry && Date.now() - entry.ts < CACHE_TTL) return entry.data;
            return null;
        },
        set(url, data) {
            cache.set(url, { data, ts: Date.now() });
        },
        clear() {
            cache.clear();
        }
    };
})();

// ==========================================
// Phase 52: モバイル検索フィルタ トグル
// ==========================================

/**
 * クリニック検索フィルタの表示/非表示を切り替え
 */
function toggleSearchFilters() {
    const filters = document.getElementById('search-filters');
    const btn = document.getElementById('filter-toggle-btn');
    if (!filters) return;
    const isExpanded = filters.classList.toggle('expanded');
    btn.setAttribute('aria-expanded', isExpanded);
}

/**
 * ドクター検索フィルタの表示/非表示を切り替え
 */
function toggleDoctorFilters() {
    const filters = document.getElementById('doctor-search-filters');
    const btn = document.getElementById('doctor-filter-toggle-btn');
    if (!filters) return;
    const isExpanded = filters.classList.toggle('expanded');
    btn.setAttribute('aria-expanded', isExpanded);
}

// ==========================================
// Phase 59: データ品質ダッシュボード
// ==========================================

let dashboardLoaded = false;

/**
 * 管理者向けデータ品質ダッシュボードを描画
 * /api/db/data-quality からデータを取得し、概要カード・価格カバー率・グレード分布・口コミ品質・データ鮮度を表示
 */
async function renderDashboard() {
    const container = document.getElementById('dashboard-content');
    if (!container) return;

    // ローディング表示
    container.innerHTML = renderSkeletons(4);

    try {
        const data = await api('/api/db/data-quality');
        const ov = data.overview || {};
        const pc = data.price_coverage || {};
        const gd = data.grade_distribution || [];
        const rq = data.review_quality || {};
        const df = data.data_freshness || {};

        let html = '';

        // --- a. 概要カード ---
        const stats = [
            { label: 'クリニック', value: (ov.total_clinics || 0).toLocaleString() },
            { label: '医師', value: (ov.total_doctors || 0).toLocaleString() },
            { label: '口コミ', value: (ov.total_reviews || 0).toLocaleString() },
            { label: '施術', value: (ov.total_procedures || 0).toLocaleString() },
        ];
        html += '<div class="dashboard-stats">';
        stats.forEach(s => {
            html += `<div class="stat-card">
                <span class="stat-card-value">${escapeHtml(s.value)}</span>
                <span class="stat-card-label">${escapeHtml(s.label)}</span>
            </div>`;
        });
        html += '</div>';

        // --- b. 価格カバー率チャート ---
        const pcTotal = pc.total || {};
        html += `<div class="dashboard-section">
            <h3 class="dashboard-section-title">価格カバー率</h3>
            <p class="dashboard-section-sub">全体: ${escapeHtml(String(pcTotal.count || 0))} / ${escapeHtml(String(pcTotal.total || 0))} 件 (${escapeHtml(String(pcTotal.pct || 0))}%)</p>
            <div class="coverage-chart">`;
        (pc.by_category || []).forEach(cat => {
            const pct = cat.pct || 0;
            const barColor = pct >= 50 ? 'var(--accent-gold)' : '#ff9800';
            html += `<div class="coverage-row">
                <span class="coverage-label">${escapeHtml(cat.category)}</span>
                <div class="coverage-bar-bg">
                    <div class="coverage-bar" style="width:${pct}%; background:${barColor}"></div>
                </div>
                <span class="coverage-pct">${escapeHtml(String(pct))}%</span>
            </div>`;
        });
        html += '</div></div>';

        // --- c. グレード分布（ドーナツチャート） ---
        if (gd.length > 0) {
            const gradeColors = { A: '#10b981', B: '#3b82f6', C: '#f59e0b', D: '#f97316', E: '#94a3b8' };
            const total = gd.reduce((s, g) => s + g.count, 0);
            // conic-gradientの構築
            let gradientParts = [];
            let cumulative = 0;
            gd.forEach(g => {
                const pct = total > 0 ? (g.count / total * 100) : 0;
                const color = gradeColors[g.grade] || '#94a3b8';
                gradientParts.push(`${color} ${cumulative}% ${cumulative + pct}%`);
                cumulative += pct;
            });
            const gradient = gradientParts.join(', ');

            html += `<div class="dashboard-section">
                <h3 class="dashboard-section-title">クリニックグレード分布</h3>
                <div class="grade-donut-container">
                    <div class="grade-donut" style="background: conic-gradient(${gradient})">
                        <div class="grade-donut-center">
                            <span class="grade-donut-total">${total.toLocaleString()}</span>
                            <span class="grade-donut-label">クリニック</span>
                        </div>
                    </div>
                    <div class="grade-legend">`;
            gd.forEach(g => {
                const color = gradeColors[g.grade] || '#94a3b8';
                const pct = total > 0 ? Math.round(g.count / total * 100) : 0;
                html += `<div class="grade-legend-item">
                    <span class="grade-legend-dot" style="background:${color}"></span>
                    <span class="grade-legend-key">${escapeHtml(g.grade)}</span>
                    <span class="grade-legend-count">${g.count.toLocaleString()}</span>
                    <span class="grade-legend-pct">${pct}%</span>
                </div>`;
            });
            html += '</div></div></div>';
        }

        // --- d. 口コミ品質 ---
        const sd = rq.sentiment_distribution || {};
        html += `<div class="dashboard-section">
            <h3 class="dashboard-section-title">口コミ品質</h3>
            <div class="dashboard-review-stats">
                <div class="review-quality-metric">
                    <span class="review-quality-value">${escapeHtml(String(rq.avg_rating || 0))}</span>
                    <span class="review-quality-label">平均評価</span>
                </div>
                <div class="review-quality-metric">
                    <span class="review-quality-value">${(rq.total || 0).toLocaleString()}</span>
                    <span class="review-quality-label">口コミ総数</span>
                </div>
                <div class="review-quality-metric">
                    <span class="review-quality-value">${(rq.with_sentiment || 0).toLocaleString()}</span>
                    <span class="review-quality-label">感情分析済</span>
                </div>
            </div>`;
        if (sd.positive !== undefined) {
            html += `<div class="dashboard-sentiment-bar">
                <div class="dashboard-sent-pos" style="width:${sd.positive}%" title="ポジティブ ${sd.positive}%"></div>
                <div class="dashboard-sent-neu" style="width:${sd.neutral}%" title="ニュートラル ${sd.neutral}%"></div>
                <div class="dashboard-sent-neg" style="width:${sd.negative}%" title="ネガティブ ${sd.negative}%"></div>
            </div>
            <div class="dashboard-sentiment-legend">
                <span class="dsl-item"><span class="dsl-dot" style="background:#10b981"></span>ポジティブ ${escapeHtml(String(sd.positive))}%</span>
                <span class="dsl-item"><span class="dsl-dot" style="background:#a3a3a3"></span>ニュートラル ${escapeHtml(String(sd.neutral))}%</span>
                <span class="dsl-item"><span class="dsl-dot" style="background:#ef4444"></span>ネガティブ ${escapeHtml(String(sd.negative))}%</span>
            </div>`;
        }
        html += '</div>';

        // --- e. データ鮮度 ---
        html += `<div class="dashboard-section">
            <h3 class="dashboard-section-title">データ鮮度</h3>
            <div class="dashboard-freshness">
                <div class="freshness-item">
                    <span class="freshness-label">クリニック情報 最終更新</span>
                    <span class="freshness-date">${escapeHtml(df.last_clinic_update || '—')}</span>
                </div>
                <div class="freshness-item">
                    <span class="freshness-label">口コミデータ 最終更新</span>
                    <span class="freshness-date">${escapeHtml(df.last_review_update || '—')}</span>
                </div>
            </div>
        </div>`;

        container.innerHTML = html;
        dashboardLoaded = true;
    } catch (err) {
        console.warn('データ品質ダッシュボードの取得に失敗:', err);
        showError('dashboard-content', 'データ品質情報の読み込みに失敗しました', renderDashboard);
    }
}

// ==========================================
// 利用規約・プライバシーポリシー
// ==========================================

/**
 * 利用規約ページを描画する
 * 法的文書の内容はハードコード（API不要）
 */
function renderTerms() {
    const el = document.getElementById('terms-content');
    if (!el) return;
    el.innerHTML = `
        <div class="legal-last-updated">最終更新日: 2026年5月28日</div>

        <div class="legal-section">
            <h3 class="legal-section-title">第1条 サービスの概要</h3>
            <p>AURA（以下「本サービス」）は、美容医療に関する情報提供サービスです。</p>
            <p>本サービスは医療機関ではなく、医療行為を行うものではありません。本サービスが提供する情報は、利用者が美容医療について理解を深め、適切な判断を行うための参考情報です。</p>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">第2条 免責事項</h3>
            <ol class="legal-list">
                <li>本サービスは、医療行為の推薦、診断、または処方を一切行いません。</li>
                <li>施術の判断は、必ず担当の医師とご相談のうえ、ご自身の責任において行ってください。</li>
                <li>本サービスが提供する情報に基づいて利用者が行った判断や行動について、本サービスは一切の責任を負いません。</li>
                <li>本サービスは法律相談を提供するものではありません。法的な問題については、弁護士等の専門家にご相談ください。</li>
            </ol>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">第3条 データの性質と限界</h3>
            <p>本サービスが提供するデータには、以下の性質と限界があります。利用者はこれらを十分に理解したうえで、本サービスをご利用ください。</p>
            <ol class="legal-list">
                <li><strong>クリニックデータ</strong>: 厚生労働省 医療情報ネットおよびGoogle Maps Platform APIより取得した情報です。データの正確性は元データの更新状況に依存します。</li>
                <li><strong>価格データ</strong>: 掲載されている価格情報のうち、約86%は統計的手法による推定値です。実際の施術費用とは異なる場合があります。正確な費用は、必ず各クリニックに直接ご確認ください。</li>
                <li><strong>口コミ分析</strong>: 自然言語処理による自動分析の結果です。分析の精度には限界があり、誤判定の可能性があります。</li>
                <li><strong>AURAグレード</strong>: クリニックに関する情報の充実度を示す指標であり、医療の質や安全性を直接評価するものではありません。</li>
                <li><strong>医師信頼性スコア</strong>: 公開情報（学会所属、専門医資格、経験年数等）に基づく指標です。医師の技術や実績を直接評価するものではありません。スコアが低いことが、医師の質が低いことを意味するものではありません。</li>
            </ol>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">第4条 データの出典</h3>
            <p>本サービスで使用しているデータの出典は以下のとおりです。</p>
            <ul class="legal-list">
                <li>厚生労働省 医療情報ネット（2025年12月1日版）</li>
                <li>Google Maps Platform API</li>
                <li>各クリニック公式サイト（一部）</li>
            </ul>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">第5条 知的財産権</h3>
            <p>本サービスに掲載されているコンテンツ（テキスト、分析結果、デザイン、プログラム等）に関する知的財産権は、本サービスの運営者または正当な権利者に帰属します。</p>
            <p>利用者は、個人的な利用の範囲を超えて、本サービスのコンテンツを複製、改変、再配布することはできません。</p>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">第6条 禁止事項</h3>
            <p>利用者は、本サービスの利用にあたり、以下の行為を行ってはなりません。</p>
            <ol class="legal-list">
                <li>本サービスのデータを商業目的で無断利用する行為</li>
                <li>本サービスの運営を妨害する行為</li>
                <li>自動化ツール等を用いたデータの大量取得（スクレイピング）</li>
                <li>他の利用者または第三者の権利を侵害する行為</li>
                <li>法令または公序良俗に反する行為</li>
            </ol>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">第7条 サービスの変更・終了</h3>
            <p>本サービスの運営者は、事前の通知なく、本サービスの内容を変更し、または提供を終了することがあります。これにより利用者に生じた損害について、本サービスの運営者は一切の責任を負いません。</p>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">第8条 準拠法・管轄裁判所</h3>
            <p>本規約の解釈および適用は、日本法に準拠するものとします。</p>
            <p>本サービスに関して紛争が生じた場合には、東京地方裁判所を第一審の専属的合意管轄裁判所とします。</p>
        </div>
    `;
}

/**
 * プライバシーポリシーページを描画する
 * 法的文書の内容はハードコード（API不要）
 */
function renderPrivacy() {
    const el = document.getElementById('privacy-content');
    if (!el) return;
    el.innerHTML = `
        <div class="legal-last-updated">最終更新日: 2026年5月28日</div>

        <div class="legal-section">
            <h3 class="legal-section-title">1. 収集する情報</h3>
            <p>本サービスでは、以下の情報を取り扱います。</p>
            <table class="legal-table">
                <thead>
                    <tr>
                        <th>情報の種類</th>
                        <th>保存先</th>
                        <th>サーバー送信</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>お気に入りデータ</td>
                        <td>LocalStorage（お使いのブラウザ内）</td>
                        <td>送信しません</td>
                    </tr>
                    <tr>
                        <td>テーマ設定（ライト/ダークモード）</td>
                        <td>LocalStorage（お使いのブラウザ内）</td>
                        <td>送信しません</td>
                    </tr>
                    <tr>
                        <td>相談履歴（AIアドバイザー使用時）</td>
                        <td>サーバー</td>
                        <td>送信されます</td>
                    </tr>
                </tbody>
            </table>
            <p>なお、お気に入りデータおよびテーマ設定は、お使いのブラウザのLocalStorageに保存されます。サーバーへの送信は行いません。ブラウザのデータを消去すると、これらの情報も削除されます。</p>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">2. 利用目的</h3>
            <p>取得した情報は、以下の目的のみに利用します。</p>
            <ul class="legal-list">
                <li>本サービスの提供および機能の改善</li>
                <li>利用者の操作性向上（テーマ設定の保持等）</li>
                <li>AIアドバイザー機能における応答の生成</li>
            </ul>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">3. 第三者提供</h3>
            <p>本サービスでは、以下の外部サービスを利用しています。これらのサービスに対して、機能の提供に必要な範囲で情報が送信される場合があります。</p>
            <table class="legal-table">
                <thead>
                    <tr>
                        <th>サービス名</th>
                        <th>利用目的</th>
                        <th>送信される情報</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Google Maps Platform</td>
                        <td>地図表示・口コミデータの取得</td>
                        <td>位置情報（地図表示時）</td>
                    </tr>
                    <tr>
                        <td>Anthropic</td>
                        <td>AIアドバイザー機能</td>
                        <td>相談内容のテキスト</td>
                    </tr>
                </tbody>
            </table>
            <p>上記以外の第三者に対して、利用者の個人情報を提供することはありません。</p>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">4. Cookieについて</h3>
            <p>本サービスはCookieを使用しません。</p>
            <p>利用者の設定情報（テーマ設定、お気に入り等）は、すべてブラウザのLocalStorageに保存されます。LocalStorageはCookieとは異なり、サーバーへのリクエスト時に自動送信されることはありません。</p>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">5. データの削除</h3>
            <p>ブラウザの設定からLocalStorageのデータを消去することで、本サービスが保存したすべてのローカルデータを削除できます。</p>
            <p>AIアドバイザーの相談履歴については、サーバー上のデータ削除をご希望の場合は、下記のお問い合わせ先までご連絡ください。</p>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">6. お問い合わせ</h3>
            <p>本プライバシーポリシーに関するお問い合わせは、本サービス内のお問い合わせ機能をご利用ください。</p>
        </div>

        <div class="legal-section">
            <h3 class="legal-section-title">7. 改定</h3>
            <p>本プライバシーポリシーは、必要に応じて改定することがあります。改定後のプライバシーポリシーは、本ページに掲載した時点から効力を生じるものとします。</p>
        </div>
    `;
}


// ==========================================
// 人気の施術セクション
// ==========================================

/**
 * 人気施術カードを動的生成する
 * ハードコードされた施術データをビジュアルカードで表示
 */
function renderPopularProcedures() {
    const container = document.getElementById('popular-procedure-cards');
    if (!container) return;

    // 人気施術データ（ハードコード）
    const popular = [
        { name: '二重埋没法', category: 'eye', price: '7万〜15万円', satisfaction: 93, color: '#F8E8EA' },
        { name: 'ヒアルロン酸注射', category: 'nose', price: '3万〜10万円', satisfaction: 85, color: '#FAEEE5' },
        { name: '医療レーザー脱毛', category: 'hair_removal', price: '20万〜40万円', satisfaction: 88, color: '#F8E8EA' },
        { name: 'ボトックス注射', category: 'contour', price: '2万〜6万円', satisfaction: 82, color: '#E8F0E8' },
        { name: '糸ハイフ', category: 'anti_aging', price: '10万〜30万円', satisfaction: 78, color: '#EDE8F2' },
        { name: 'シミ取りレーザー', category: 'skin', price: '5千〜3万円', satisfaction: 90, color: '#E8EDF2' },
    ];

    container.innerHTML = popular.map(p => `
        <div class="popular-card" style="background: ${p.color}" onclick="navigateWithConcern('${escapeHtml(p.category)}')">
            <div class="popular-card-name">${escapeHtml(p.name)}</div>
            <div class="popular-card-price">相場 ${escapeHtml(p.price)}</div>
            <div class="popular-card-satisfaction">
                <div class="satisfaction-bar">
                    <div class="satisfaction-fill" style="width: ${p.satisfaction}%"></div>
                </div>
                <span>${p.satisfaction}%</span>
            </div>
        </div>
    `).join('');

    // 新規追加セクションのfade-in-sectionをobserverに登録
    document.querySelectorAll('.popular-procedures.fade-in-section:not(.visible)').forEach(el => fadeObserver.observe(el));
}


// ==========================================
// トラブル実態セクション
// ==========================================

/**
 * トラブル事例データ — 国民生活センター相談事例に基づく
 */
const TROUBLE_CASES = [
    {
        title: '「小顔リフト1本1万4千円」の広告で来院',
        reality: '実際は数十万円〜百万円単位の契約を提案された',
        category: '価格トラブル',
    },
    {
        title: '「今日契約すれば安くなる」と急かされて契約',
        reality: '解約を申し出たが返金を拒否された',
        category: '圧力販売',
    },
    {
        title: '「無料カウンセリング」のはずが',
        reality: '数百万円の高額コースを契約させられた',
        category: '契約トラブル',
    },
    {
        title: '「腫れない」「当日化粧できる」と説明されたが',
        reality: '術後に腫れが長引き、左右非対称になった',
        category: '健康被害',
    },
    {
        title: '「私も施術を受けた。大丈夫」とスタッフに説得',
        reality: '長時間説得され、圧を感じて契約してしまった',
        category: '圧力販売',
    },
];

/**
 * トラブルセクション全体をレンダリング
 * バーチャート + 事例カード
 */
function renderTroubleSection() {
    renderTroubleChart();
    renderTroubleCases();

    // fade-in-section のobserver再登録
    document.querySelectorAll('.trouble-section.fade-in-section:not(.visible)').forEach(el => fadeObserver.observe(el));
}

/**
 * 相談件数バーチャートをレンダリング
 * IntersectionObserverでアニメーション起動
 */
function renderTroubleChart() {
    const chartEl = document.getElementById('trouble-chart');
    if (!chartEl) return;

    const data = [
        { year: '2020', count: 2209 },
        { year: '2021', count: 2767 },
        { year: '2022', count: 3798 },
        { year: '2023', count: 6281 },
        { year: '2024', count: 10717 },
    ];
    const max = Math.max(...data.map(d => d.count));

    // 初期状態はheight:0、IntersectionObserverで伸ばす
    chartEl.innerHTML = data.map(d => {
        const pct = Math.round(d.count / max * 100);
        return `
            <div class="trouble-bar" style="height: 0%" data-target-height="${pct}%">
                <span class="trouble-bar-value">${d.count.toLocaleString()}</span>
                <span class="trouble-bar-label">${escapeHtml(d.year)}</span>
            </div>
        `;
    }).join('');

    // IntersectionObserverでアニメーション起動
    const chartObserver = new IntersectionObserver((entries) => {
        entries.forEach(e => {
            if (e.isIntersecting) {
                // 各バーを順番にアニメーション
                const bars = chartEl.querySelectorAll('.trouble-bar');
                bars.forEach((bar, i) => {
                    setTimeout(() => {
                        bar.style.height = bar.dataset.targetHeight;
                    }, i * 150);
                });
                chartObserver.unobserve(e.target);
            }
        });
    }, { threshold: 0.3 });

    chartObserver.observe(chartEl);
}

/**
 * トラブル事例カードをレンダリング
 */
function renderTroubleCases() {
    const casesEl = document.getElementById('trouble-cases');
    if (!casesEl) return;

    casesEl.innerHTML = TROUBLE_CASES.map(c => `
        <div class="trouble-card">
            <span class="trouble-card-category">${escapeHtml(c.category)}</span>
            <div class="trouble-card-title">${escapeHtml(c.title)}</div>
            <div class="trouble-card-reality">${escapeHtml(c.reality)}</div>
        </div>
    `).join('');
}


// ==========================================
// 症例写真検索
// ==========================================

let casePhotosInitialized = false;
let cpCurrentCategory = '';
let cpCurrentSource = '';
let cpCurrentPage = 1;
let _cpPhotosCache = [];

/** カテゴリ定義 */
const _CP_CATEGORIES = [
    { key: '', label: 'すべて' },
    { key: 'eyes', label: '目元' },
    { key: 'nose', label: '鼻' },
    { key: 'skin', label: '肌' },
    { key: 'jawline', label: '輪郭' },
    { key: 'body', label: '体' },
    { key: 'other', label: 'その他' },
];

/** ソース定義 */
const _CP_SOURCES = [
    { key: '', label: 'すべて' },
    { key: 'sbc', label: 'SBC' },
    { key: 'tcb', label: 'TCB' },
    { key: 'shinagawa', label: '品川' },
    { key: 'tribeau', label: 'トリビュー' },
];

/** カテゴリ表示名マッピング */
const _CP_CAT_LABELS = {
    eyes: '目元', nose: '鼻', skin: '肌', jawline: '輪郭',
    body: '体', other: 'その他',
};

/** ソース表示名マッピング */
const _CP_SOURCE_LABELS = {
    sbc: 'SBC湘南美容', tcb: 'TCB東京中央', shinagawa: '品川美容', tribeau: 'トリビュー',
};

/**
 * 症例写真検索UIを初期化
 * 統計データ取得 → フィルタ生成 → 初回検索
 */
async function initCasePhotos() {
    casePhotosInitialized = true;
    loadCasePhotoStats();
    renderCpCategoryFilters();
    renderCpSourceFilters();
    searchCasePhotos();
}

/**
 * 症例写真の統計情報を表示
 */
async function loadCasePhotoStats() {
    const el = document.getElementById('cp-stats');
    if (!el) return;
    try {
        const stats = await api('/api/case-photos/stats');
        if (!stats || stats.total === 0) {
            el.innerHTML = '';
            return;
        }
        const categoryHtml = (stats.by_category || []).map(c =>
            `<span class="cp-stat-chip">${escapeHtml(_CP_CAT_LABELS[c.category] || c.category)} <strong>${c.count.toLocaleString()}</strong></span>`
        ).join('');
        const sourceHtml = (stats.by_source || []).map(s =>
            `<span class="cp-stat-chip cp-stat-chip--source">${escapeHtml(_CP_SOURCE_LABELS[s.source] || s.source)} <strong>${s.count.toLocaleString()}</strong></span>`
        ).join('');
        el.innerHTML = `
            <div class="cp-stats-total">
                <span class="cp-stats-number">${stats.total.toLocaleString()}</span>
                <span class="cp-stats-label">件の症例写真</span>
            </div>
            <div class="cp-stats-chips">${categoryHtml}${sourceHtml}</div>
        `;
    } catch (err) {
        console.warn('症例写真統計の取得に失敗:', err);
    }
}

/**
 * カテゴリフィルタボタンを生成
 */
function renderCpCategoryFilters() {
    const el = document.getElementById('cp-category-filters');
    if (!el) return;
    el.innerHTML = _CP_CATEGORIES.map(c =>
        `<button class="filter-btn ${c.key === cpCurrentCategory ? 'active' : ''}"
                 aria-pressed="${c.key === cpCurrentCategory}"
                 onclick="filterCpCategory('${c.key}')">${escapeHtml(c.label)}</button>`
    ).join('');
}

/**
 * ソースフィルタボタンを生成
 */
function renderCpSourceFilters() {
    const el = document.getElementById('cp-source-filters');
    if (!el) return;
    el.innerHTML = '<span class="cp-source-label">ソース:</span>' +
        _CP_SOURCES.map(s =>
            `<button class="cp-source-btn ${s.key === cpCurrentSource ? 'active' : ''}"
                     aria-pressed="${s.key === cpCurrentSource}"
                     onclick="filterCpSource('${s.key}')">${escapeHtml(s.label)}</button>`
        ).join('');
}

/**
 * カテゴリフィルタ変更
 * @param {string} category - カテゴリキー
 */
function filterCpCategory(category) {
    cpCurrentCategory = category;
    cpCurrentPage = 1;
    renderCpCategoryFilters();
    searchCasePhotos();
}

/**
 * ソースフィルタ変更
 * @param {string} source - ソースキー
 */
function filterCpSource(source) {
    cpCurrentSource = source;
    cpCurrentPage = 1;
    renderCpSourceFilters();
    searchCasePhotos();
}

/**
 * 症例写真の検索・表示
 * @param {number} page - ページ番号
 */
async function searchCasePhotos(page = 1) {
    cpCurrentPage = page;
    const gridEl = document.getElementById('cp-grid');
    const pagerEl = document.getElementById('cp-pager');
    const countEl = document.getElementById('cp-result-count');
    if (!gridEl) return;

    // スケルトンUI表示
    gridEl.innerHTML = Array.from({ length: 8 }, () =>
        '<div class="cp-card cp-card--skeleton"><div class="cp-card-pair"><div class="skeleton-line" style="height:140px;border-radius:8px;"></div><div class="skeleton-line" style="height:140px;border-radius:8px;"></div></div><div class="skeleton-line" style="height:16px;margin-top:8px;width:70%;"></div><div class="skeleton-line skeleton-line--short" style="height:12px;margin-top:4px;"></div></div>'
    ).join('');

    const params = new URLSearchParams({ page, per_page: 20 });
    if (cpCurrentCategory) params.set('category', cpCurrentCategory);
    if (cpCurrentSource) params.set('source', cpCurrentSource);

    try {
        const data = await api(`/api/case-photos/?${params}`);
        const photos = data.case_photos || [];
        const total = data.total || 0;
        const totalPages = data.total_pages || 1;

        // 結果件数
        if (countEl) {
            countEl.textContent = total > 0 ? `${total.toLocaleString()}件の症例写真` : '';
        }

        if (photos.length === 0) {
            gridEl.innerHTML = `
                <div class="cp-empty">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48" style="opacity:0.3;">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>
                    </svg>
                    <p>該当する症例写真が見つかりませんでした</p>
                    <p class="cp-empty-sub">フィルタ条件を変更してお試しください</p>
                </div>`;
            if (pagerEl) pagerEl.innerHTML = '';
            return;
        }

        // グリッドレンダリング
        _cpPhotosCache = photos;
        gridEl.innerHTML = photos.map((ph, idx) => renderCpCard(ph, idx)).join('');

        // ページネーション
        if (pagerEl && totalPages > 1) {
            let btns = '';
            if (page > 1) btns += `<button class="pager-btn" onclick="searchCasePhotos(${page - 1})">前へ</button>`;
            for (let p = Math.max(1, page - 2); p <= Math.min(totalPages, page + 2); p++) {
                btns += `<button class="pager-btn ${p === page ? 'active' : ''}" onclick="searchCasePhotos(${p})">${p}</button>`;
            }
            if (page < totalPages) btns += `<button class="pager-btn" onclick="searchCasePhotos(${page + 1})">次へ</button>`;
            pagerEl.innerHTML = `<nav aria-label="症例写真ページネーション">${btns}</nav>`;
        } else if (pagerEl) {
            pagerEl.innerHTML = '';
        }

        // スクロールトップ（ページ変更時）
        if (page > 1) {
            document.getElementById('page-case-photos')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    } catch (err) {
        console.warn('症例写真の検索に失敗:', err);
        showError('cp-grid', '症例写真の読み込みに失敗しました', () => searchCasePhotos(cpCurrentPage));
    }
}

/**
 * 症例写真カードのHTMLを生成
 * @param {Object} photo - 症例写真データ
 * @param {number} idx - インデックス（アニメーション遅延用）
 * @returns {string} HTML文字列
 */
function renderCpCard(photo, idx) {
    const delay = Math.min(idx * 50, 400);
    const catLabel = _CP_CAT_LABELS[photo.category] || photo.category || '';
    const sourceLabel = _CP_SOURCE_LABELS[photo.source] || photo.source || '';
    const priceDisplay = photo.price ? escapeHtml(photo.price) : '';
    const procName = photo.procedure_name ? escapeHtml(photo.procedure_name) : '';
    const clinicName = photo.clinic_name ? escapeHtml(photo.clinic_name) : '';
    const doctorName = photo.doctor_name ? escapeHtml(photo.doctor_name) : '';

    return `
        <div class="cp-card" style="animation-delay: ${delay}ms" data-cp-idx="${idx}" onclick="openCpLightbox(_cpPhotosCache[${idx}])">
            <div class="cp-card-pair">
                <div class="cp-card-img">
                    <span class="cp-card-label">Before</span>
                    <img src="${escapeHtml(photo.before_image_url)}" alt="Before" loading="lazy" onerror="this.closest('.cp-card').style.display='none'">
                </div>
                ${photo.after_image_url ? `
                <div class="cp-card-img cp-card-img--after">
                    <span class="cp-card-label cp-card-label--after">After</span>
                    <img src="${escapeHtml(photo.after_image_url)}" alt="After" loading="lazy" onerror="this.style.display='none'">
                </div>` : ''}
            </div>
            <div class="cp-card-info">
                ${procName ? `<div class="cp-card-proc">${procName}</div>` : ''}
                <div class="cp-card-meta">
                    ${clinicName ? `<span class="cp-card-clinic">${clinicName}</span>` : ''}
                    ${doctorName ? `<span class="cp-card-doctor">${doctorName}</span>` : ''}
                </div>
                <div class="cp-card-bottom">
                    ${priceDisplay ? `<span class="cp-card-price">${priceDisplay}</span>` : ''}
                    <div class="cp-card-tags">
                        ${catLabel ? `<span class="cp-card-tag">${escapeHtml(catLabel)}</span>` : ''}
                        ${sourceLabel ? `<span class="cp-card-tag cp-card-tag--source">${escapeHtml(sourceLabel)}</span>` : ''}
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * ライトボックスを開いて症例写真を拡大表示
 * @param {Object|string} photoData - 症例写真データ（JSON文字列またはオブジェクト）
 */
function openCpLightbox(photoData) {
    const lightbox = document.getElementById('cp-lightbox');
    const body = document.getElementById('cp-lightbox-body');
    if (!lightbox || !body) return;

    let photo = photoData;
    if (typeof photoData === 'string') {
        try { photo = JSON.parse(photoData); } catch (e) { return; }
    }

    const catLabel = _CP_CAT_LABELS[photo.category] || photo.category || '';
    const sourceLabel = _CP_SOURCE_LABELS[photo.source] || photo.source || '';

    body.innerHTML = `
        <div class="cp-lb-images">
            <div class="cp-lb-img">
                <span class="cp-lb-label">Before</span>
                <img src="${escapeHtml(photo.before_image_url)}" alt="Before">
            </div>
            ${photo.after_image_url ? `
            <div class="cp-lb-img">
                <span class="cp-lb-label cp-lb-label--after">After</span>
                <img src="${escapeHtml(photo.after_image_url)}" alt="After">
            </div>` : ''}
        </div>
        <div class="cp-lb-details">
            ${photo.procedure_name ? `<h3 class="cp-lb-proc">${escapeHtml(photo.procedure_name)}</h3>` : ''}
            <div class="cp-lb-meta">
                ${photo.clinic_name ? `<span class="cp-lb-clinic">${escapeHtml(photo.clinic_name)}</span>` : ''}
                ${photo.doctor_name ? `<span class="cp-lb-doctor">${escapeHtml(photo.doctor_name)}</span>` : ''}
            </div>
            <div class="cp-lb-info">
                ${photo.price ? `<span class="cp-lb-price">${escapeHtml(photo.price)}</span>` : ''}
                ${catLabel ? `<span class="cp-lb-tag">${escapeHtml(catLabel)}</span>` : ''}
                ${sourceLabel ? `<span class="cp-lb-tag cp-lb-tag--source">${escapeHtml(sourceLabel)}</span>` : ''}
            </div>
            ${photo.source_url ? `<a href="${escapeHtml(photo.source_url)}" target="_blank" rel="noopener noreferrer" class="cp-lb-source-link">元サイトで詳細を見る →</a>` : ''}
        </div>
    `;

    lightbox.style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

/**
 * ライトボックスを閉じる
 */
function closeCpLightbox() {
    const lightbox = document.getElementById('cp-lightbox');
    if (!lightbox) return;
    lightbox.style.display = 'none';
    document.body.style.overflow = '';
}

// ライトボックスのイベントリスナー
document.addEventListener('DOMContentLoaded', () => {
    const closeBtn = document.getElementById('cp-lightbox-close');
    if (closeBtn) closeBtn.addEventListener('click', closeCpLightbox);

    const lightbox = document.getElementById('cp-lightbox');
    if (lightbox) {
        lightbox.addEventListener('click', (e) => {
            if (e.target === lightbox) closeCpLightbox();
        });
    }
});

// Escキーでライトボックスを閉じる
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const lightbox = document.getElementById('cp-lightbox');
        if (lightbox && lightbox.style.display !== 'none') {
            closeCpLightbox();
        }
    }
});

