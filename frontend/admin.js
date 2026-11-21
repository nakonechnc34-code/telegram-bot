/* ═══════════════════════════════════════════
   WOKKER ADMIN — FULLY FUNCTIONAL DASHBOARD
   ═══════════════════════════════════════════ */

// Global error guard
window.addEventListener('error', e => { e.preventDefault(); console.error('[global]', e.error); });

const TOKEN_KEY = 'wokker_admin_token';
const LOGIN_RE = /^[a-z]{3}\d{2}$/;
let ME = null;
let _cache = {};

// ═══ UTILS ═══
const $ = id => document.getElementById(id);
const esc = s => (s == null ? '' : String(s)).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }
function getFileUrl(url) {
    if (!url) return '';
    return url + '?token=' + getToken();
}

// ═══ CACHE ═══
let _cacheData = {};
async function cachedApi(path, body, ttl = 30000) {
    const key = path + (body ? JSON.stringify(body) : '');
    const now = Date.now();
    if (_cacheData[key] && now - _cacheData[key].time < ttl) return _cacheData[key].data;
    const data = await api(path, body);
    _cacheData[key] = { data, time: now };
    return data;
}
function clearCache() { _cacheData = {}; }

function toast(text, type) {
    const el = document.createElement('div');
    el.className = 'toast' + (type ? ' ' + type : '');
    el.textContent = text;
    $('toasts').appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; }, 2600);
    setTimeout(() => el.remove(), 3000);
}

function fmtDate(iso, withTime) {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        const pad = n => String(n).padStart(2, '0');
        const date = `${pad(d.getDate())}.${pad(d.getMonth()+1)}.${d.getFullYear()}`;
        if (!withTime) return date;
        return `${date} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    } catch (e) { return iso; }
}

// ═══ API ═══
async function api(path, body) {
    const payload = { webToken: getToken() };
    if (body && typeof body === 'object') Object.assign(payload, body);
    const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (res.status === 401) { clearToken(); showLogin(); throw new Error('unauthorized'); }
    if (res.status === 403) {
        let j = {};
        try { j = await res.json(); } catch (e) {}
        if (j.error === 'fired') { clearToken(); showLogin(); throw new Error('fired'); }
        throw new Error(j.error || 'forbidden');
    }
    if (!res.ok) {
        let msg = 'error';
        try { const j = await res.json(); msg = j.detail || j.error || msg; } catch (e) {}
        throw new Error(msg);
    }
    return res.json();
}

async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch('/api/admin/upload', {
            method: 'POST', headers: { 'X-Token': getToken() }, body: formData
        });
        if (!res.ok) { const err = await res.json(); throw new Error(err.error || 'Upload failed'); }
        return await res.json();
    } catch (e) { throw new Error('Ошибка сети при загрузке файла'); }
}

// ═══ MOBILE SIDEBAR ═══
const burger = () => document.getElementById('hamburger');
const overlay = () => document.getElementById('overlay');
function openSidebar() { 
    const sidebar = document.getElementById('sidebar');
    const overlayEl = overlay();
    if (sidebar) sidebar.classList.add('sidebar--open'); 
    if (overlayEl) {
        overlayEl.classList.add('overlay--show'); 
        document.body.style.overflow = 'hidden';
    }
}
function closeSidebar() { 
    const sidebar = document.getElementById('sidebar');
    const overlayEl = overlay();
    if (sidebar) sidebar.classList.remove('sidebar--open'); 
    if (overlayEl) {
        overlayEl.classList.remove('overlay--show'); 
        document.body.style.overflow = '';
    }
}

// ═══ PERMISSIONS ═══
function isSuperAdmin() { return !!(ME && ME.is_super_admin); }
function isHR() { return !!(ME && ME.is_hr); }
function canPublish() { return isSuperAdmin() || isHR(); }
function hasPerm(perm) {
    if (!ME) return false;
    if (ME.is_super_admin || ME.is_hr) return true;
    return !!(ME.permissions && ME.permissions[perm]);
}

// ═══ MODAL ═══
function openModal(title, bodyHtml, footerHtml, opts) {
    opts = opts || {};
    const titleEl = $('modal-title');
    if (titleEl) titleEl.textContent = title;
    const bodyEl = $('modal-body');
    if (bodyEl) bodyEl.innerHTML = bodyHtml;
    const footerEl = $('modal-footer');
    if (footerEl) footerEl.innerHTML = footerHtml || '';
    const boxEl = $('modal-box');
    if (boxEl) boxEl.className = 'modal' + (opts.wide ? ' wide' : '');
    const overlayEl = $('modal-overlay');
    if (overlayEl) overlayEl.classList.add('show');
}
function closeModal() {
    const overlayEl = $('modal-overlay');
    if (overlayEl) overlayEl.classList.remove('show');
}

// ═══ CHANGE PASSWORD ═══
// Event listener added in DOMContentLoaded block

// ═══ LOGIN ═══
function showLogin() {
    const appEl = $('app');
    const loginScreenEl = $('login-screen');
    if (appEl) appEl.style.display = 'none';
    if (loginScreenEl) loginScreenEl.style.display = 'flex';
    const errEl = $('login-error');
    if (errEl) errEl.textContent = '';
    const loginInput = $('login-login');
    const passInput = $('login-password');
    if (loginInput) loginInput.value = '';
    if (passInput) passInput.value = '';
    clearCache();
}
function showApp() { 
    const appEl = $('app');
    const loginScreenEl = $('login-screen');
    if (appEl) appEl.style.display = 'block';
    if (loginScreenEl) loginScreenEl.style.display = 'none';
}

$('login-login')?.addEventListener('input', e => {
    e.target.value = e.target.value.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 5);
});

async function doLogin() {
    console.log('[login] doLogin called');
    const loginInput = $('login-login');
    const passwordInput = $('login-password');
    if (!loginInput || !passwordInput) { console.error('Login elements not found'); return; }
    const login = loginInput.value.trim().toLowerCase();
    const password = passwordInput.value;
    const errEl = $('login-error');
    errEl.textContent = '';
    if (!LOGIN_RE.test(login)) { errEl.textContent = 'Логин: 3 латинские буквы + 2 цифры'; return; }
    if (!password) { errEl.textContent = 'Введите пароль'; return; }
    const btn = $('login-btn');
    btn.disabled = true; btn.textContent = 'Проверяем…';
    try {
        console.log('[login] Sending to /api/admin/login');
        const res = await fetch('/api/admin/login', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ login, password }),
        });
        console.log('[login] Response status:', res.status);
        if (res.status === 401) { errEl.textContent = 'Неверный логин или пароль'; return; }
        if (res.status === 403) { errEl.textContent = 'Аккаунт уволен или нет прав администратора'; return; }
        if (!res.ok) { errEl.textContent = 'Ошибка сервера'; return; }
        const data = await res.json();
        if (!data.token) { errEl.textContent = 'Ошибка'; return; }
        setToken(data.token); clearCache();
        console.log('[login] Success, token set');
        await checkAdminAndLoad();
    } catch (e) { console.error('[login] Error:', e); errEl.textContent = 'Сеть недоступна'; }
    finally { btn.disabled = false; btn.textContent = 'Войти'; }
}

// Event listeners moved to DOMContentLoaded block

async function checkAdminAndLoad() {
    try {
        const res = await api('/api/admin/me', {});
        ME = res.profile;
        const nameEl = $('admin-name');
        if (nameEl) nameEl.textContent = ME.full_name || '—';
        const loginEl = $('admin-login');
        if (loginEl) loginEl.textContent = '@' + (ME.login || '');
        const roleEl = $('admin-role');
        if (roleEl) {
            roleEl.textContent = ME.is_super_admin ? 'Супер-админ' : ME.is_hr ? 'HR' : 'Админ';
            roleEl.className = 'badge-role ' + (ME.is_super_admin ? 'super' : ME.is_hr ? 'hr' : 'regular');
        }
        const adminsNav = $('nav-admins');
        if (adminsNav) adminsNav.style.display = ME.is_super_admin ? 'block' : 'none';
        const avatarEl = $('topbar-avatar');
        if (avatarEl && ME.full_name) avatarEl.textContent = ME.full_name.charAt(0).toUpperCase();
        showApp();
        if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
            navigator.serviceWorker.controller.postMessage({ type: 'SET_TOKEN', token: getToken() });
        }
        navigate('dashboard');
        refreshCounters();
    } catch (e) { 
        showLogin(); 
        const errEl = $('login-error');
        if (errEl) errEl.textContent = 'Ошибка: ' + e.message; 
    }
}

// Logout event listener moved to DOMContentLoaded block

// ═══ NAVIGATION ═══
const PAGE_TITLES = {
    dashboard: 'Дашборд', users: 'Сотрудники', medbooks: 'Медкнижки',
    news: 'Новости', standards: 'Стандарты', certification: 'Сертификация', faq: 'FAQ',
    restaurants: 'Рестораны', positions: 'Должности', citizenships: 'Гражданства',
    'medbook-dirs': 'Справочники медкн.', questions: 'Вопросы',
    admins: 'Администраторы', reports: 'Отчёты', audit: 'История', sales: 'Товарооборот',
};

function navigate(page) {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('nav-item--active', item.dataset.page === page);
    });
    $('page-title').textContent = PAGE_TITLES[page] || page;
    $('page-content').innerHTML = '<div class="loading">Загрузка...</div>';
    const loader = PAGE_LOADERS[page];
    if (loader) {
        loader().then(() => refreshCounters()).catch(e => {
            console.error('load:', e);
            if (e.message !== 'unauthorized' && e.message !== 'fired') {
                $('page-content').innerHTML = '<div class="empty">Ошибка: ' + esc(e.message) + '</div>';
            }
        });
    }
}

// Navigation event listeners moved to DOMContentLoaded block

// ═══ REFRESH COUNTERS ═══
async function refreshCounters() {
    try {
        const q = await api('/api/admin/questions', {});
        const open = (q.questions || []).filter(x => !x.replied).length;
        const qEl = $('q-count');
        if (qEl) { if (open > 0) { qEl.textContent = open; qEl.style.display = 'inline-block'; } else qEl.style.display = 'none'; }
    } catch (e) {}
    try {
        const n = await api('/api/admin/news', {});
        const pending = (n.news || []).filter(x => x.status === 'pending').length;
        const nEl = $('news-pending-count');
        if (nEl) { if (pending > 0 && canPublish()) { nEl.textContent = pending; nEl.style.display = 'inline-block'; } else nEl.style.display = 'none'; }
    } catch (e) {}
    try {
        const s = await api('/api/admin/standards', {});
        const pending = (s.standards || []).filter(x => x.status === 'pending').length;
        const sEl = $('standards-pending-count');
        if (sEl) { if (pending > 0 && canPublish()) { sEl.textContent = pending; sEl.style.display = 'inline-block'; } else sEl.style.display = 'none'; }
    } catch (e) {}
}

// ═══ AVATAR GRADIENTS ═══
const GRADIENTS = [
    'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
    'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
    'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
    'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
];
function getAvatarGradient(index) { return GRADIENTS[index % GRADIENTS.length]; }

// ═══════════════════════════════════════════
// PAGE LOADERS
// ═══════════════════════════════════════════

// ═══ DASHBOARD ═══
async function loadDashboard() {
    $('page-content').innerHTML = `
        <div class="stats-grid">
            <div class="neu-card neu-card--stat">
                <div style="display:flex;align-items:center;justify-content:space-between;">
                    <div class="neu-card__icon-wrapper neu-card__icon-wrapper--purple">👥</div>
                    <div class="neu-card__trend neu-card__trend--up">↑ активны</div>
                </div>
                <div class="neu-card__value" id="stat-active"><div class="skeleton skeleton-stat"></div></div>
                <div class="neu-card__label">Активные сотрудники</div>
            </div>
            <div class="neu-card neu-card--stat">
                <div style="display:flex;align-items:center;justify-content:space-between;">
                    <div class="neu-card__icon-wrapper neu-card__icon-wrapper--blue">📝</div>
                    <div class="neu-card__trend neu-card__trend--warn">⏳ модерация</div>
                </div>
                <div class="neu-card__value" id="stat-pending"><div class="skeleton skeleton-stat"></div></div>
                <div class="neu-card__label">На модерации</div>
            </div>
            <div class="neu-card neu-card--stat">
                <div style="display:flex;align-items:center;justify-content:space-between;">
                    <div class="neu-card__icon-wrapper neu-card__icon-wrapper--pink">📖</div>
                    <div class="neu-card__trend neu-card__trend--down">!</div>
                </div>
                <div class="neu-card__value" id="stat-medbooks"><div class="skeleton skeleton-stat"></div></div>
                <div class="neu-card__label">Медкнижки требуют внимания</div>
            </div>
            <div class="neu-card neu-card--stat">
                <div style="display:flex;align-items:center;justify-content:space-between;">
                    <div class="neu-card__icon-wrapper neu-card__icon-wrapper--green">❓</div>
                    <div class="neu-card__trend neu-card__trend--warn">открытых</div>
                </div>
                <div class="neu-card__value" id="stat-questions"><div class="skeleton skeleton-stat"></div></div>
                <div class="neu-card__label">Вопросы от сотрудников</div>
            </div>
        </div>
        <div class="grid-2">
            <div class="neu-card">
                <div class="neu-card__header">
                    <div class="neu-card__header-title">Открытые вопросы</div>
                    <div class="neu-card__header-action" onclick="navigate('questions')">Все вопросы →</div>
                </div>
                <div id="dash-questions"><div class="loading">Загрузка...</div></div>
            </div>
            <div class="neu-card">
                <div class="neu-card__header">
                    <div class="neu-card__header-title">Новые сотрудники</div>
                    <div class="neu-card__header-action" onclick="navigate('users')">Все →</div>
                </div>
                <div id="dash-new-users"><div class="loading">Загрузка...</div></div>
            </div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/dashboard/summary', {}, 10000);
        const stats = data.stats || {};
        if ($('stat-active')) $('stat-active').textContent = stats.active || 0;
        if ($('stat-pending')) $('stat-pending').textContent = (stats.news_pending || 0) + (stats.standards_pending || 0);
        if ($('stat-medbooks')) $('stat-medbooks').textContent = stats.medbooks_alert || 0;
        if ($('stat-questions')) $('stat-questions').textContent = stats.questions_open || 0;
        // Реальные открытые вопросы
        const qsContainer = $('dash-questions');
        if (qsContainer) {
            const questions = (data.questions || []).slice(0, 5);
            qsContainer.innerHTML = questions.map(q => `
                <div class="activity__item">
                    <div class="activity__icon activity__icon--accent">❓</div>
                    <div class="activity__content">
                        <div class="activity__text"><strong>${esc(q.full_name || 'Сотрудник')}</strong><br>${esc(q.text || '—')}</div>
                        <div class="activity__time">${fmtDate(q.created_at, true)}</div>
                    </div>
                </div>`).join('') || '<div class="loading">Нет открытых вопросов</div>';
        }
        // Новые сотрудники
        const usersContainer = $('dash-new-users');
        if (usersContainer) {
            const users = (data.users || []).slice(0, 5);
            usersContainer.innerHTML = users.map((u, i) => `
                <div class="activity__item">
                    <div class="avatar" style="background:${getAvatarGradient(i)};width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;font-weight:700;flex-shrink:0;">${(u.full_name||'?').charAt(0)}</div>
                    <div class="activity__content">
                        <div class="activity__text">${esc(u.full_name||'—')}</div>
                        <div class="activity__time">${esc(u.position||'')} · ${fmtDate(u.created_at)}</div>
                    </div>
                </div>`).join('') || '<div class="loading">Нет новых сотрудников</div>';
        }
    } catch (e) { console.error('Dashboard error:', e); }
}

// ═══════════════════════════════════════════
// TASK 1: ПОЛНОЦЕННЫЕ ПОЛЬЗОВАТЕЛИ
// ═══════════════════════════════════════════
async function loadUsers() {
    const canCreate = hasPerm('users_create');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header">
                <div class="neu-card__header-title">Сотрудники</div>
                <div style="display:flex;gap:8px;">
                    <input class="form-input" id="users-search" placeholder="🔍 Поиск по ФИО, логину..." style="width:240px;">
                    ${canCreate ? '<button class="btn btn--primary" onclick="openAddUser()">+ Добавить</button>' : ''}
                </div>
            </div>
            <div class="subtabs" style="margin-bottom:16px;">
                <button class="subtab active" data-tab="active">Активные</button>
                <button class="subtab" data-tab="fired">Уволенные</button>
            </div>
            <div class="table-wrap">
                <table class="t">
                    <thead><tr><th>Логин</th><th>ФИО</th><th>Должность</th><th>Ресторан</th><th>Медкнижка</th><th>Статус</th><th>Действия</th></tr></thead>
                    <tbody id="users-table"><tr><td colspan="7" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
                </table>
            </div>
        </div>`;

    let currentTab = 'active';
    let currentSearch = '';

    document.querySelectorAll('[data-tab]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('[data-tab]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTab = btn.dataset.tab;
            loadUsersTable();
        });
    });

    const searchInput = $('users-search');
    let timer = null;
    searchInput.addEventListener('input', () => {
        currentSearch = searchInput.value;
        clearTimeout(timer);
        timer = setTimeout(loadUsersTable, 250);
    });

    await loadUsersTable();

    async function loadUsersTable() {
        try {
            const data = await cachedApi('/api/admin/users', { search: currentSearch, fired: currentTab === 'fired' });
            const users = data.users || [];
            const tbody = $('users-table');
            tbody.innerHTML = users.map((u, i) => {
                const mbStatus = u.medbook_status || 'invalid';
                let mbTag = '';
                if (u.is_admin) mbTag = '<span class="tag">—</span>';
                else if (mbStatus === 'ok') mbTag = '<span class="tag tag--green">ОК</span>';
                else if (mbStatus === 'expiring') mbTag = '<span class="tag tag--amber">Скоро</span>';
                else mbTag = '<span class="tag tag--pink">Ошибка</span>';
                if (currentTab === 'fired') {
                    return `<tr>
                        <td>${u.login ? esc(u.login) : '<span class="tag">нет</span>'}</td>
                        <td><div class="name-cell"><div class="avatar" style="background:${getAvatarGradient(i)}">${(u.full_name||'?').charAt(0).toUpperCase()}</div>${esc(u.full_name||'—')}</div></td>
                        <td>${esc(u.position||'—')}</td>
                        <td>${esc(u.restaurant_name||'—')}</td>
                        <td colspan="2"></td>
                        <td>${hasPerm('users_fire') ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--green);" onclick="restoreUser(${u.user_id})">♻️</button>` : ''}</td>
                    </tr>`;
                }
                const ptTag = u.payment_type === 'fixed' ? '<span class="tag" style="font-size:10px;padding:2px 6px;">Оклад</span>' : '<span class="tag" style="font-size:10px;padding:2px 6px;">Почасовка</span>';
                return `<tr>
                    <td>${u.login ? esc(u.login) : '<span class="tag">нет</span>'}</td>
                    <td><div class="name-cell"><div class="avatar" style="background:${getAvatarGradient(i)}">${(u.full_name||'?').charAt(0).toUpperCase()}</div>
                        <div>${esc(u.full_name||'—')}<br>${u.personnel_number ? '<span class="tag" style="font-size:9px;">Таб. №'+esc(u.personnel_number)+'</span>' : ''} ${ptTag}</div>
                    </div></td>
                    <td>${esc(u.position||'—')}</td>
                    <td>${esc(u.restaurant_name||'—')}</td>
                    <td>${mbTag}</td>
                    <td><span class="tag ${u.is_fired ? 'tag--amber' : 'tag--green'}">${u.is_fired ? 'Уволен' : 'Активен'}</span></td>
                    <td style="display:flex;gap:4px;">
                        ${!u.is_fired && hasPerm('users_edit') ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="openEditUser(${u.user_id})">✏️</button>` : ''}
                        ${!u.is_fired && !u.is_super_admin && hasPerm('users_fire') ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="fireUser(${u.user_id},'${esc(u.full_name||'')}')" ${u.is_admin && !isSuperAdmin() ? 'disabled' : ''}>🔥</button>` : ''}
                    </td>
                </tr>`;
            }).join('') || '<tr><td colspan="7" style="text-align:center;color:var(--text-terc);padding:40px;">Нет сотрудников</td></tr>';
        } catch (e) {
            $('users-table').innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
        }
    }
}

// Таблица: клик по строке = редактировать
document.addEventListener('click', e => {
    const tr = e.target.closest('tr[data-edit]');
    if (tr) openEditUser(parseInt(tr.dataset.edit));
});

async function openAddUser() {
    let restaurants = [], positions = [], citizens = [];
    try {
        const r = await api('/api/admin/restaurants', {}); restaurants = r.restaurants || [];
        const p = await api('/api/admin/positions', {}); positions = p.positions.filter(x => !x.is_archived) || [];
        const c = await api('/api/admin/citizenships', {}); citizens = c.citizenships || [];
    } catch(e) {}

    openModal('Добавить сотрудника', `
        <div class="form-group"><label>ФИО</label><input class="form-input" id="user-full-name" placeholder="Иванов Иван Иванович">
            <div class="form-hint" id="login-preview" style="display:none;">Логин: <strong id="lp-val"></strong></div>
        </div>
        <div class="form-group"><label>Пароль</label><input class="form-input" id="user-password" type="password"></div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>Телефон</label><input class="form-input" id="user-phone"></div>
            <div class="form-group"><label>Дата рождения</label><input class="form-input" id="user-birth" placeholder="ДД.ММ.ГГГГ"></div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>Должность</label><select class="form-input" id="user-position">${positions.map(p=>`<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('')}</select></div>
            <div class="form-group"><label>Ресторан</label><select class="form-input" id="user-restaurant"><option value="">—</option>${restaurants.map(r=>`<option value="${esc(r.key)}">${esc(r.name)}</option>`).join('')}</select></div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>Гражданство</label><select class="form-input" id="user-citizen">${citizens.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></div>
            <div class="form-group"><label>Дата трудоустройства</label><input class="form-input" id="user-hire" type="date"></div>
        </div>
        <div class="form-group"><label>Табельный номер</label><input class="form-input" id="user-persnum" placeholder="Например: 1024"></div>
        <div class="form-group"><label>Тип оплаты</label><select class="form-input" id="user-payment"><option value="hourly">Почасовая</option><option value="fixed">Фиксированный оклад</option></select></div>
        <div class="form-hint" id="user-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="user-save">Создать</button>`);

    // Авто-логин из фамилии
    $('user-full-name').addEventListener('input', () => {
        const name = $('user-full-name').value.trim();
        const pp = $('login-preview');
        if (!name) { pp.style.display = 'none'; return; }
        pp.style.display = 'block';
        const translit = {"а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya"};
        const parts = name.split(/\s+/);
        const surname = (parts[0]||'').toLowerCase();
        let letters = '';
        for (const ch of surname) { if (letters.length >= 3) break; const t = translit[ch]; if (t) letters += t; }
        while (letters.length < 3) letters += 'abcdefghijklmnopqrstuvwxyz'[Math.floor(Math.random()*26)];
        $('lp-val').textContent = letters.slice(0,3) + Math.floor(Math.random()*90+10);
    });

    $('user-save').addEventListener('click', async () => {
        const errEl = $('user-error'); errEl.textContent = '';
        const fn = $('user-full-name').value.trim();
        const pw = $('user-password').value;
        if (!fn || !pw) { errEl.textContent = 'Заполните ФИО и пароль'; return; }
        try {
            await api('/api/admin/user/create', {
                full_name: fn, password: pw, phone: $('user-phone').value.trim(),
                birth_date: $('user-birth').value.trim(), position: $('user-position').value,
                restaurant_key: $('user-restaurant').value, citizenship_id: $('user-citizen').value,
                hire_date: $('user-hire').value, personnel_number: $('user-persnum').value.trim(),
                payment_type: $('user-payment').value
            });
            toast('Сотрудник создан', 'success'); closeModal(); loadUsers();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function openEditUser(uid) {
    let user, restaurants, positions, citizens;
    try {
        const uData = await api('/api/admin/user/get', { user_id: uid }); user = uData.user;
        const r = await api('/api/admin/restaurants', {}); restaurants = r.restaurants || [];
        const p = await api('/api/admin/positions', {}); positions = p.positions || [];
        const c = await api('/api/admin/citizenships', {}); citizens = c.citizenships || [];
    } catch (e) { toast('Ошибка: ' + e.message, 'error'); return; }

    openModal('Редактировать: ' + (user.full_name||''), `
        <div class="form-group"><label>Логин</label><input class="form-input" value="${esc(user.login||'')}" readonly></div>
        <div class="form-group"><label>ФИО</label><input class="form-input" id="ed-full-name" value="${esc(user.full_name||'')}"></div>
        <div class="form-group"><label>Новый пароль (оставьте пустым если не нужно менять)</label><input class="form-input" id="ed-password" type="password"></div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>Телефон</label><input class="form-input" id="ed-phone" value="${esc(user.phone||'')}"></div>
            <div class="form-group"><label>Дата рождения</label><input class="form-input" id="ed-birth" value="${esc(user.birth_date||'')}"></div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>Должность</label><select class="form-input" id="ed-position">${positions.filter(p=>!p.is_archived).map(p=>`<option value="${esc(p.name)}" ${p.name===user.position?'selected':''}>${esc(p.name)}</option>`).join('')}</select></div>
            <div class="form-group"><label>Ресторан</label><select class="form-input" id="ed-restaurant">${restaurants.map(r=>`<option value="${esc(r.key)}" ${r.key===user.restaurant_key?'selected':''}>${esc(r.name)}</option>`).join('')}</select></div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>Гражданство</label><select class="form-input" id="ed-citizen">${citizens.map(c=>`<option value="${c.id}" ${c.id===user.citizenship_id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></div>
            <div class="form-group"><label>Дата трудоустройства</label><input class="form-input" id="ed-hire" type="date" value="${esc(user.hire_date||'')}"></div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>Табельный номер</label><input class="form-input" id="ed-persnum" value="${esc(user.personnel_number||'')}"></div>
            <div class="form-group"><label>Тип оплаты</label><select class="form-input" id="ed-payment"><option value="hourly" ${user.payment_type==='hourly'?'selected':''}>Почасовая</option><option value="fixed" ${user.payment_type==='fixed'?'selected':''}>Фиксированный оклад</option></select></div>
        </div>
        ${isSuperAdmin() && !user.is_super_admin ? `<div class="form-group"><label><input type="checkbox" id="ed-isadmin" ${user.is_admin?'checked':''}> Права администратора</label></div>` : ''}
        <div class="form-hint" id="ed-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="ed-save">Сохранить</button>`);

    $('ed-save').addEventListener('click', async () => {
        const errEl = $('ed-error'); errEl.textContent = '';
        const updates = {
            full_name: $('ed-full-name').value.trim(),
            phone: $('ed-phone').value.trim(), birth_date: $('ed-birth').value.trim(),
            position: $('ed-position').value, restaurant_key: $('ed-restaurant').value,
            citizenship_id: $('ed-citizen').value, hire_date: $('ed-hire').value,
            personnel_number: $('ed-persnum').value.trim(), payment_type: $('ed-payment').value,
        };
        const pw = $('ed-password').value; if (pw) updates.password = pw;
        if (isSuperAdmin() && !user.is_super_admin) updates.is_admin = $('ed-isadmin').checked;
        try {
            await api('/api/admin/user/update', { user_id: uid, updates });
            toast('Сохранено', 'success'); closeModal(); loadUsers();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function fireUser(uid, name) {
    if (!confirm(`Уволить ${name}?`)) return;
    try { await api('/api/admin/user/fire', { user_id: uid }); toast('Сотрудник уволен', 'success'); loadUsers(); }
    catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

async function restoreUser(uid) {
    if (!confirm('Восстановить сотрудника?')) return;
    try { await api('/api/admin/user/restore', { user_id: uid }); toast('Сотрудник восстановлен', 'success'); loadUsers(); }
    catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══════════════════════════════════════════
// TASK 3: МЕДСПРАВОЧНИКИ (до и во время medbooks)
// ═══════════════════════════════════════════
let _medTab = 'staff';
async function loadMedbooks() {
    const data = await cachedApi('/api/admin/medbooks', {});
    _medTab = _medTab || 'staff';
    const canEdit = hasPerm('medbook_edit');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="subtabs" style="margin-bottom:16px;">
                <button class="subtab ${_medTab==='staff'?'active':''}" data-mt="staff">Сотрудники</button>
                <button class="subtab ${_medTab==='doctors'?'active':''}" data-mt="doctors">Врачи</button>
                <button class="subtab ${_medTab==='tests'?'active':''}" data-mt="tests">Анализы</button>
                <button class="subtab ${_medTab==='vaccines'?'active':''}" data-mt="vaccines">Прививки</button>
            </div>
            <div id="med-content"></div>
        </div>`;

    document.querySelectorAll('[data-mt]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('[data-mt]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            _medTab = btn.dataset.mt;
            renderMedContent(data);
        });
    });

    renderMedContent(data);

    function renderMedContent(d) {
        if (_medTab === 'staff') {
            const users = d.users || [];
            const ok = users.filter(u => u.medbook_status === 'ok').length;
            const exp = users.filter(u => u.medbook_status === 'expiring').length;
            const inv = users.filter(u => u.medbook_status === 'invalid').length;
            $('med-content').innerHTML = `
                <div class="stats-grid" style="margin-bottom:24px;">
                    <div class="neu-card neu-card--stat"><div class="neu-card__label">Действительны</div><div class="neu-card__value" style="color:var(--green);">${ok}</div></div>
                    <div class="neu-card neu-card--stat"><div class="neu-card__label">Скоро истекают</div><div class="neu-card__value" style="color:var(--amber);">${exp}</div></div>
                    <div class="neu-card neu-card--stat"><div class="neu-card__label">Недействительны</div><div class="neu-card__value" style="color:var(--pink);">${inv}</div></div>
                </div>
                <div class="table-wrap">
                    <table class="t"><thead><tr><th>ФИО</th><th>Должность</th><th>Ресторан</th><th>Статус</th><th>Действия</th></tr></thead>
                    <tbody>${users.map((u,i) => {
                        const st = u.medbook_status==='ok'?'tag--green':u.medbook_status==='expiring'?'tag--amber':'tag--pink';
                        const tx = u.medbook_status==='ok'?'OK':u.medbook_status==='expiring'?'Истекает':'Не заполнена';
                        return `<tr>
                            <td><div class="name-cell"><div class="avatar" style="background:${getAvatarGradient(i)}">${(u.full_name||'?').charAt(0).toUpperCase()}</div>${esc(u.full_name||'—')}</div></td>
                            <td>${esc(u.position||'—')}</td><td>${esc(u.restaurant_name||'—')}</td>
                            <td><span class="tag ${st}">${tx}</span></td>
                            <td>${canEdit ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="openEditMedbook(${u.user_id})">✏️</button>` : ''}</td>
                        </tr>`;
                    }).join('') || '<tr><td colspan="5" style="text-align:center;padding:40px;">Нет сотрудников</td></tr>'}</tbody></table></div>`;
        } else {
            const typeMap = { doctors: 'doctor', tests: 'test', vaccines: 'vaccine' };
            const typeLabel = { doctors: 'Врач', tests: 'Анализ', vaccines: 'Вакцина' };
            const list = d[_medTab] || [];
            const canManage = hasPerm('medbook_doctors_manage') || hasPerm('medbook_tests_manage') || hasPerm('medbook_vaccines_manage');
            const type = typeMap[_medTab];
            $('med-content').innerHTML = `
                <div style="margin-bottom:12px;">
                    ${canManage ? `<button class="btn btn--primary" onclick="openAddMedDir('${type}')">+ Добавить ${typeLabel[_medTab].toLowerCase()}</button>` : ''}
                </div>
                <div class="table-wrap">
                    <table class="t"><thead><tr><th>Название</th><th>Срок (мес)</th><th>Обяз.</th><th>Действия</th></tr></thead>
                    <tbody>${list.map(item => `<tr>
                        <td style="font-weight:600;">${esc(item.name)}</td><td>${item.validity_months||'—'}</td>
                        <td>${item.required ? '<span class="tag tag--green">Да</span>' : '<span class="tag tag--amber">Нет</span>'}</td>
                        <td>${canManage ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="editMedDirItem(${item.id},'${type}','${esc(item.name)}',${item.validity_months||0},${item.required})">✏️</button>
                            <button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="deleteMedDirItem('${type}',${item.id})">🗑️</button>` : ''}</td>
                    </tr>`).join('') || '<tr><td colspan="4" style="text-align:center;padding:40px;">Пусто</td></tr>'}</tbody></table></div>`;
        }
    }
}

// Medbook editor
async function openEditMedbook(uid) {
    if (!hasPerm('medbook_edit')) { toast('Нет права', 'error'); return; }
    let user, medbook, doctors = [], tests = [], vaccines = [];
    try {
        const d = await api('/api/admin/medbook/get', { user_id: uid });
        user = d.user; medbook = d.medbook || {}; doctors = d.doctors || []; tests = d.tests || []; vaccines = d.vaccines || [];
    } catch (e) { toast('Ошибка: ' + e.message, 'error'); return; }

    const renderSection = (list, source) => list.map(item => {
        const dateStr = (medbook[source] && medbook[source][item.id]) || '';
        return `<div class="form-group"><label>${esc(item.name)}${item.required ? ' *' : ''}</label>
            <input class="form-input med-date" data-src="${source}" data-id="${item.id}" value="${esc(dateStr)}" placeholder="ДД.ММ.ГГГГ">
            <div class="form-hint med-status" data-msrc="${source}" data-mid="${item.id}"></div></div>`;
    }).join('');

    openModal('Медкнижка: ' + (user.full_name||''), `
        <div style="margin-bottom:16px;"><strong>${esc(user.full_name||'—')}</strong> — ${esc(user.position||'')}</div>
        <div class="form-hint">Формат даты: ДД.ММ.ГГГГ</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-top:12px;">
            <div><h4 style="margin-bottom:8px;color:var(--purple);">Врачи</h4>${renderSection(doctors, 'doctors')}</div>
            <div><h4 style="margin-bottom:8px;color:var(--blue);">Анализы</h4>${renderSection(tests, 'tests')}</div>
            <div><h4 style="margin-bottom:8px;color:var(--green);">Прививки</h4>${renderSection(vaccines, 'vaccines')}</div>
        </div>
        <div class="form-hint error" id="med-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="med-save">Сохранить</button>`);

    $('med-save').addEventListener('click', async () => {
        const errEl = $('med-error'); errEl.textContent = '';
        const mb = { doctors: {}, tests: {}, vaccines: {} };
        document.querySelectorAll('.med-date').forEach(inp => {
            const src = inp.dataset.src, id = inp.dataset.id, val = inp.value.trim();
            if (val) { if (!mb[src]) mb[src] = {}; mb[src][id] = val; }
        });
        try {
            await api('/api/admin/medbook/save', { user_id: uid, medbook: mb });
            toast('Медкнижка сохранена', 'success'); closeModal(); loadMedbooks();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

// Medbook dirs CRUD
async function loadMedbookDirs() {
    const data = await api('/api/admin/medbooks', {});
    const doctors = data.doctors || [], tests = data.tests || [], vaccines = data.vaccines || [];
    const all = [...doctors.map(d=>({...d,type:'doctor',tl:'Врач'})),...tests.map(t=>({...t,type:'test',tl:'Анализ'})),...vaccines.map(v=>({...v,type:'vaccine',tl:'Вакцина'}))];
    const typeColors = { doctor:'var(--purple)', test:'var(--blue)', vaccine:'var(--green)' };
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header">
                <div class="neu-card__header-title">Справочники медкнижки</div>
                <div style="display:flex;gap:8px;">
                    <button class="btn btn--primary" onclick="openAddMedDir('doctor')">+ Врач</button>
                    <button class="btn btn--primary" style="background:var(--blue);" onclick="openAddMedDir('test')">+ Анализ</button>
                    <button class="btn btn--primary" style="background:var(--green);" onclick="openAddMedDir('vaccine')">+ Вакцина</button>
                </div>
            </div>
            <div class="table-wrap">
                <table class="t"><thead><tr><th>Тип</th><th>Название</th><th>Срок (мес)</th><th>Обяз.</th><th>Действия</th></tr></thead>
                <tbody id="meddirs-tbody">${all.map(item => `<tr>
                    <td><span class="tag" style="background:${typeColors[item.type]}20;color:${typeColors[item.type]};">${item.tl}</span></td>
                    <td style="font-weight:600;">${esc(item.name)}</td><td>${item.validity_months||'—'}</td>
                    <td>${item.required ? '<span class="tag tag--green">Да</span>' : '<span class="tag tag--amber">Нет</span>'}</td>
                    <td>
                        <button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="editMedDirItem(${item.id},'${esc(item.type)}','${esc(item.name)}',${item.validity_months||0},${item.required})">✏️</button>
                        <button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="deleteMedDirItem('${esc(item.type)}',${item.id})">🗑️</button>
                    </td>
                </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;padding:40px;">Нет записей</td></tr>'}</tbody></table>
            </div>
        </div>`;
}

async function openAddMedDir(type) {
    const labels = { doctor:'Врач', test:'Анализ', vaccine:'Вакцина' };
    openModal(`Добавить ${labels[type]}`, `
        <div class="form-group"><label>Название</label><input class="form-input" id="med-dir-name" maxlength="100"></div>
        <div class="form-group"><label>Срок действия (месяцев)</label><input class="form-input" id="med-dir-months" type="number" value="12" min="1" max="120"></div>
        <label style="display:flex;align-items:center;gap:8px;margin-bottom:16px;cursor:pointer;"><input type="checkbox" id="med-dir-required" checked> <span>Обязательный</span></label>
        <div class="form-hint" id="med-dir-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="med-dir-save">Добавить</button>`);
    $('med-dir-save').addEventListener('click', async () => {
        const errEl = $('med-dir-error'); errEl.textContent = '';
        const name = $('med-dir-name').value.trim();
        if (!name) { errEl.textContent = 'Введите название'; return; }
        try {
            await api('/api/admin/medbook/reference/add', { type, name, validity_months: parseInt($('med-dir-months').value)||12, required: $('med-dir-required').checked });
            toast('Добавлено', 'success'); closeModal(); loadMedbookDirs();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function editMedDirItem(id, type, name, months, required) {
    const labels = { doctor:'Врач', test:'Анализ', vaccine:'Вакцина' };
    openModal(`Редактировать ${labels[type]}`, `
        <div class="form-group"><label>Название</label><input class="form-input" id="ed-med-dir-name" value="${esc(name)}" maxlength="100"></div>
        <div class="form-group"><label>Срок (месяцев)</label><input class="form-input" id="ed-med-dir-months" type="number" value="${months}" min="1" max="120"></div>
        <label style="display:flex;align-items:center;gap:8px;margin-bottom:16px;cursor:pointer;"><input type="checkbox" id="ed-med-dir-required" ${required?'checked':''}> <span>Обязательный</span></label>
        <div class="form-hint" id="ed-med-dir-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="ed-med-dir-save">Сохранить</button>`);
    $('ed-med-dir-save').addEventListener('click', async () => {
        const errEl = $('ed-med-dir-error'); errEl.textContent = '';
        const name = $('ed-med-dir-name').value.trim();
        if (!name) { errEl.textContent = 'Введите название'; return; }
        try {
            await api('/api/admin/medbook/reference/update', { type, id, name, validity_months: parseInt($('ed-med-dir-months').value)||12, required: $('ed-med-dir-required').checked });
            toast('Сохранено', 'success'); closeModal(); loadMedbookDirs();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function deleteMedDirItem(type, id) {
    if (!confirm('Удалить?')) return;
    try { await api('/api/admin/medbook/reference/delete', { type, id }); toast('Удалено', 'success'); loadMedbookDirs(); }
    catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══════════════════════════════════════════
// TASK 2: НОВОСТИ/СТАНДАРТЫ С МОДЕРАЦИЕЙ + ФАЙЛЫ + EDIT
// ═══════════════════════════════════════════
let _uploadedNewsImageUrl = '';
let _uploadedStandardImageUrl = '';
let _uploadedStandardFileUrl = '';
let _uploadedStandardFileName = '';
let _tableHeaders = [];
let _tableRows = [];
const STANDARD_GROUPS = ['Пищевая Безопасность', 'Касса', 'Горячий цех', 'Холодный цех', 'Общее'];

// Clean HTML from scripts/styles
function cleanHTML(html) {
    if (!html) return '';
    let clean = String(html);
    clean = clean.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
    clean = clean.replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '');
    clean = clean.replace(/<iframe\b[^>]*>[\s\S]*?<\/iframe>/gi, '');
    clean = clean.replace(/<object\b[^>]*>[\s\S]*?<\/object>/gi, '');
    clean = clean.replace(/<embed\b[^>]*\/?>/gi, '');
    clean = clean.replace(/<form\b[^>]*>[\s\S]*?<\/form>/gi, '');
    clean = clean.replace(/\s+on\w+\s*=\s*"[^"]*"/gi, '');
    clean = clean.replace(/\s+on\w+\s*=\s*'[^']*'/gi, '');
    clean = clean.replace(/\s+on\w+\s*=\s*[^\s>]+/gi, '');
    clean = clean.replace(/href\s*=\s*["']?\s*javascript:[^"'\s>]*/gi, 'href="#"');
    clean = clean.replace(/src\s*=\s*["']?\s*javascript:[^"'\s>]*/gi, '');
    clean = clean.replace(/<meta[^>]*>/gi, '');
    clean = clean.replace(/<link[^>]*>/gi, '');
    clean = clean.replace(/\s*(class|id)="[^"]*"/gi, '');
    clean = clean.replace(/font-size\s*:\s*[^;"]+;?/gi, '');
    clean = clean.replace(/line-height\s*:\s*[^;"]+;?/gi, '');
    clean = clean.replace(/<p><br><\/p>/gi, '');
    clean = clean.replace(/<p>&nbsp;<\/p>/gi, '');
    return clean.trim();
}

async function loadNews() {
    const data = await cachedApi('/api/admin/news', {});
    const all = data.news || [];
    const pending = all.filter(n => n.status === 'pending');
    const others = all.filter(n => n.status !== 'pending');
    const canCreate = hasPerm('news_write') || hasPerm('news_suggest') || canPublish();
    const canEdit = hasPerm('news_edit');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header">
                <div class="neu-card__header-title">Новости</div>
                ${canCreate ? '<button class="btn btn--primary" onclick="openAddNews()">+ Создать</button>' : ''}
            </div>
            ${canPublish() && pending.length ? `
                <div style="background:rgba(254,225,64,0.08);border:1px solid rgba(254,225,64,0.2);border-radius:12px;padding:16px;margin-bottom:24px;">
                    <strong style="color:var(--amber);">На модерации: ${pending.length}</strong>
                    <div style="display:flex;flex-direction:column;gap:8px;margin-top:12px;">
                        ${pending.map(n => `
                            <div style="display:flex;gap:8px;align-items:center;padding:8px;background:var(--bg-card);border-radius:8px;">
                                <div style="flex:1;"><strong>${esc(n.title)}</strong><br><span style="font-size:12px;color:var(--text-terc);">${esc(n.proposed_by||'')} · ${fmtDate(n.created_at)}</span></div>
                                <button class="btn btn--ghost" style="padding:4px 12px;font-size:11px;color:var(--green);" onclick="approveNews(${n.id})">✓</button>
                                <button class="btn btn--ghost" style="padding:4px 12px;font-size:11px;color:var(--pink);" onclick="rejectNews(${n.id})">✕</button>
                            </div>`).join('')}
                    </div>
                </div>` : ''}
            <div class="table-wrap">
                <table class="t"><thead><tr><th>Фото</th><th>Заголовок</th><th>Автор</th><th>Дата</th><th>Статус</th><th>Действия</th></tr></thead>
                <tbody id="news-table">${others.map(n => {
                    const st = n.status==='published'?'tag--green':n.status==='scheduled'?'tag--blue':'tag--amber';
                    const tx = n.status==='published'?'Опубликована':n.status==='scheduled'?'Запланирована':'На модерации';
                    let acts = '';
                    if (n.status==='pending' && canPublish()) acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--green);" onclick="approveNews(${n.id})">✓</button>`;
                    if (n.status==='pending' && canPublish()) acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="rejectNews(${n.id})">✕</button>`;
                    if (canEdit) acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="openNewsEdit(${n.id},others)">✏️</button>`;
                    if (canEdit && n.status !== 'pending') acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="deleteNews(${n.id})">🗑️</button>`;
                    return `<tr><td style="text-align:center;">${n.image_url ? `<img src="${getFileUrl(n.image_url)}" style="width:48px;height:48px;object-fit:cover;border-radius:12px;">` : '<span style="color:var(--text-terc);">—</span>'}</td>
                        <td style="font-weight:600;">${esc(n.title||'—')}</td><td>${esc(n.proposed_by||'—')}</td><td style="color:var(--text-terc);">${fmtDate(n.created_at)}</td><td><span class="tag ${st}">${tx}</span></td><td>${acts}</td></tr>`;
                }).join('') || '<tr><td colspan="6" style="text-align:center;padding:40px;">Нет новостей</td></tr>'}</tbody></table>
            </div>
        </div>`;
}

async function openAddNews() {
    const canPublishFlag = canPublish();
    _uploadedNewsImageUrl = '';
    openModal(canPublishFlag ? 'Новая новость' : 'Предложить новость', `
        <div class="form-group">
            <label>Фотография (опционально)</label>
            <input type="file" id="n-image-file" accept="image/*" style="display:none;">
            <button type="button" class="btn btn--ghost" id="n-image-btn" style="width:100%;padding:20px;border-style:dashed;border-radius:14px;">Прикрепить фото</button>
            <div id="n-image-preview-box" style="display:none;margin-top:12px;text-align:center;">
                <img id="n-image-preview" style="max-width:100%;max-height:150px;border-radius:12px;object-fit:contain;">
            </div>
        </div>
        <div class="form-group"><label>Заголовок</label><input class="form-input" id="n-title" maxlength="100"></div>
        <div class="form-group"><label>Текст</label><textarea class="form-textarea" id="n-body" rows="6"></textarea></div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>Уровень</label><select class="form-input" id="n-level"><option value="normal">Обычная</option><option value="announcement">Объявление</option><option value="event">Событие</option></select></div>
            <div class="form-group"><label>Действие</label><select class="form-input" id="n-intent">${canPublishFlag ? '<option value="publish">Опубликовать</option><option value="schedule">Отложить</option>' : ''}<option value="suggest">Предложить</option></select></div>
        </div>
        <div class="form-group" id="n-sched-time" style="display:none;"><label>Дата и время</label><input class="form-input" type="datetime-local" id="n-publish-at"></div>
        <div class="form-hint" id="news-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="create-news-btn">${canPublishFlag ? 'Создать' : 'Предложить'}</button>`);

    // Image upload handler
    $('n-image-btn').addEventListener('click', () => $('n-image-file').click());
    $('n-image-file').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 15*1024*1024) { toast('Файл слишком большой (макс 15MB)', 'error'); return; }
        const btn = $('n-image-btn');
        btn.textContent = 'Загрузка...';
        btn.disabled = true;
        try {
            const res = await uploadFile(file);
            _uploadedNewsImageUrl = res.url;
            $('n-image-preview').src = getFileUrl(res.url);
            $('n-image-preview-box').style.display = 'block';
            btn.textContent = 'Фото загружено';
            btn.style.borderColor = 'var(--green)';
        } catch (err) {
            toast(err.message, 'error');
            btn.textContent = 'Прикрепить фото';
        } finally { btn.disabled = false; }
    });

    $('n-intent').addEventListener('change', e => {
        $('n-sched-time').style.display = e.target.value === 'schedule' ? 'block' : 'none';
    });

    $('create-news-btn').addEventListener('click', async () => {
        const errEl = $('news-error'); errEl.textContent = '';
        const title = $('n-title').value.trim(), body = $('n-body').value.trim();
        if (!title || !body) { errEl.textContent = 'Заполните заголовок и текст'; return; }
        const bodyReq = {
            title, body, level: $('n-level').value, intent: $('n-intent').value,
            image_url: _uploadedNewsImageUrl
        };
        if (bodyReq.intent === 'schedule') {
            const dt = $('n-publish-at').value;
            if (!dt) { errEl.textContent = 'Укажите дату'; return; }
            bodyReq.publish_at = new Date(dt).toISOString();
        }
        try {
            const res = await api('/api/admin/news/add', bodyReq);
            toast('Новость создана', 'success'); closeModal(); loadNews();
        } catch (e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}

async function openNewsEdit(id, others) {
    if (!hasPerm('news_edit')) { toast('Нет права', 'error'); return; }
    let newsData;
    try { newsData = await cachedApi('/api/admin/news', {}); } catch(e) { return; }
    const n = (newsData.news||[]).find(x => x.id === id);
    if (!n) return;

    _uploadedNewsImageUrl = n.image_url || '';
    openModal('Редактировать новость', `
        <div class="form-group">
            <label>Фотография</label>
            <input type="file" id="n-image-file-edit" accept="image/*" style="display:none;">
            <button type="button" class="btn btn--ghost" id="n-image-btn-edit" style="width:100%;padding:20px;border-style:dashed;border-radius:14px;">${n.image_url ? 'Заменить фото' : 'Прикрепить фото'}</button>
            <div id="n-image-preview-box-edit" style="display:${n.image_url?'block':'none'};margin-top:12px;text-align:center;">
                <img id="n-image-preview-edit" src="${getFileUrl(n.image_url)}" style="max-width:100%;max-height:150px;border-radius:12px;object-fit:contain;">
            </div>
        </div>
        <div class="form-group"><label>Заголовок</label><input class="form-input" id="edit-n-title" value="${esc(n.title)}"></div>
        <div class="form-group"><label>Текст</label><textarea class="form-textarea" id="edit-n-body" rows="6">${esc(n.body)}</textarea></div>
        <div class="form-group"><label>Уровень</label><select class="form-input" id="edit-n-level"><option value="normal" ${n.level==='normal'?'selected':''}>Обычная</option><option value="announcement" ${n.level==='announcement'?'selected':''}>Объявление</option><option value="event" ${n.level==='event'?'selected':''}>Событие</option></select></div>
        <div class="form-hint" id="edit-news-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="save-news-btn">Сохранить</button>`);

    // Image upload
    $('n-image-btn-edit').addEventListener('click', () => $('n-image-file-edit').click());
    $('n-image-file-edit').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 15*1024*1024) { toast('Файл слишком большой (макс 15MB)', 'error'); return; }
        const btn = $('n-image-btn-edit');
        btn.textContent = 'Загрузка...';
        btn.disabled = true;
        try {
            const res = await uploadFile(file);
            _uploadedNewsImageUrl = res.url;
            $('n-image-preview-edit').src = getFileUrl(res.url);
            $('n-image-preview-box-edit').style.display = 'block';
            btn.textContent = 'Фото загружено';
        } catch (err) {
            toast(err.message, 'error');
            btn.textContent = 'Заменить фото';
        } finally { btn.disabled = false; }
    });

    $('save-news-btn').addEventListener('click', async () => {
        const errEl = $('edit-news-error'); errEl.textContent = '';
        try {
            await api('/api/admin/news/update', {
                id,
                title: $('edit-n-title').value.trim(),
                body: $('edit-n-body').value.trim(),
                level: $('edit-n-level').value,
                image_url: _uploadedNewsImageUrl
            });
            toast('Сохранено', 'success'); closeModal(); loadNews();
        } catch (e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}

async function approveNews(id) { try { await api('/api/admin/news/approve', { id }); toast('Одобрено', 'success'); loadNews(); } catch(e) { toast('Ошибка: '+e.message, 'error'); } }
async function rejectNews(id) { try { await api('/api/admin/news/reject', { id }); toast('Отклонено', 'success'); loadNews(); } catch(e) { toast('Ошибка: '+e.message, 'error'); } }
async function deleteNews(id) { if(!confirm('Удалить?')) return; try { await api('/api/admin/news/delete', { id }); toast('Удалено', 'success'); loadNews(); } catch(e) { toast('Ошибка: '+e.message, 'error'); } }

// ═══ STANDARDS ═══
async function loadStandards() {
    const data = await cachedApi('/api/admin/standards', {});
    const all = data.standards || [];
    const pending = all.filter(s => s.status === 'pending');
    const others = all.filter(s => s.status !== 'pending');
    const canCreate = hasPerm('standards_edit') || canPublish();
    const canEdit = hasPerm('standards_edit');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header">
                <div class="neu-card__header-title">Стандарты</div>
                ${canCreate ? '<button class="btn btn--primary" onclick="openAddStandard()">+ Добавить</button>' : ''}
            </div>
            ${canPublish() && pending.length ? `
                <div style="background:rgba(254,225,64,0.08);border:1px solid rgba(254,225,64,0.2);border-radius:12px;padding:16px;margin-bottom:24px;">
                    <strong style="color:var(--amber);">На согласовании: ${pending.length}</strong>
                    <div style="display:flex;flex-direction:column;gap:8px;margin-top:12px;">
                        ${pending.map(s => `
                            <div style="display:flex;gap:8px;align-items:center;padding:8px;background:var(--bg-card);border-radius:8px;">
                                <div style="flex:1;"><strong>${esc(s.title)}</strong> <span class="tag tag--purple">${esc(s.group_name||'')}</span><br><span style="font-size:12px;color:var(--text-terc);">${esc(s.proposed_by||'')} · ${fmtDate(s.created_at)}</span></div>
                                <button class="btn btn--ghost" style="padding:4px 12px;font-size:11px;color:var(--green);" onclick="approveStandard(${s.id})">✓</button>
                                <button class="btn btn--ghost" style="padding:4px 12px;font-size:11px;color:var(--pink);" onclick="rejectStandard(${s.id})">✕</button>
                            </div>`).join('')}
                    </div>
                </div>` : ''}
            <div class="table-wrap">
                <table class="t"><thead><tr><th>Фото</th><th>Номер</th><th>Группа</th><th>Заголовок</th><th>Файл</th><th>Статус</th><th>Действия</th></tr></thead>
                <tbody id="standards-table">${others.map(s => {
                    const st = s.status==='published'?'tag--green':'tag--amber';
                    const tx = s.status==='published'?'Опубликован':'На модерации';
                    let acts = '';
                    if (s.status==='pending' && canPublish()) acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--green);" onclick="approveStandard(${s.id})">✓</button>`;
                    if (s.status==='pending' && canPublish()) acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="rejectStandard(${s.id})">✕</button>`;
                    if (canEdit) acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="openStdEdit(${s.id})">✏️</button>`;
                    if (canEdit && s.status !== 'pending') acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="deleteStandard(${s.id})">🗑️</button>`;
                    return `<tr><td style="text-align:center;">${s.image_url ? `<img src="${getFileUrl(s.image_url)}" style="width:48px;height:48px;object-fit:cover;border-radius:12px;">` : '<span style="color:var(--text-terc);">—</span>'}</td>
                        <td><span class="tag">${esc(s.number||'—')}</span></td><td><span class="tag tag--purple">${esc(s.group_name||'Общее')}</span></td>
                        <td style="font-weight:600;">${esc(s.title||'—')}</td><td>${s.file_url ? 'Да' : '—'}</td>
                        <td><span class="tag ${st}">${tx}</span></td><td>${acts}</td></tr>`;
                }).join('') || '<tr><td colspan="7" style="text-align:center;padding:40px;">Нет стандартов</td></tr>'}</tbody></table>
            </div>
        </div>`;
}

function renderTableEditor(headers, rows) {
    let headerHtml = headers.map((h, i) => `<th style="padding:4px;"><input class="form-input" style="padding:8px;border-radius:8px;font-size:13px;text-align:center;" value="${esc(h)}" onchange="updateTableHeaders()" data-col="${i}"></th>`).join('');
    let rowsHtml = rows.map((row, rIdx) => `<tr>${headers.map((_, cIdx) => `<td style="padding:4px;"><input class="form-input" style="padding:8px;border-radius:8px;font-size:13px;" value="${esc(row[cIdx]||'')}" onchange="updateTableCell(${rIdx},${cIdx})"></td>`).join('')}<td style="padding:4px;"><button type="button" class="btn btn--ghost" style="font-size:10px;padding:4px;" onclick="removeTableRow(${rIdx})">Удал.</button></td></tr>`).join('');
    return `<div style="overflow-x:auto;padding-bottom:8px;"><table style="width:100%;border-collapse:collapse;min-width:600px;"><thead><tr>${headerHtml}<th></th></tr></thead><tbody id="table-editor-rows">${rowsHtml}</tbody></table></div>
        <div style="display:flex;gap:8px;margin-top:16px;"><button type="button" class="btn btn--ghost" style="font-size:11px;" onclick="addTableRow()">Добавить строку</button></div>`;
}
window.updateTableHeaders = function() {
    const newHeaders = Array.from(document.querySelectorAll('#std-table-area thead input')).map(i => i.value);
    _tableHeaders = newHeaders;
    _tableRows = _tableRows.map(r => { const newR = []; for(let i=0;i<newHeaders.length;i++) newR.push(r[i]||''); return newR; });
    document.getElementById('table-editor-container').innerHTML = renderTableEditor(_tableHeaders, _tableRows);
};
window.updateTableCell = function(rIdx, cIdx) {
    const inputs = document.querySelectorAll(`#table-editor-rows tr:nth-child(${rIdx+1}) input`);
    _tableRows[rIdx][cIdx] = inputs[cIdx].value;
};
window.addTableRow = function() { _tableRows.push(Array(_tableHeaders.length).fill('')); document.getElementById('table-editor-container').innerHTML = renderTableEditor(_tableHeaders, _tableRows); };
window.removeTableRow = function(rIdx) { _tableRows.splice(rIdx, 1); document.getElementById('table-editor-container').innerHTML = renderTableEditor(_tableHeaders, _tableRows); };

function switchContentTypeUI(type) {
    $('std-text-area').style.display = type === 'table' ? 'none' : 'block';
    $('std-table-area').style.display = type === 'table' ? 'block' : 'none';
    if (type === 'table' && !_tableHeaders.length) {
        _tableHeaders = ['Колонка 1', 'Колонка 2', 'Колонка 3'];
        _tableRows = [['', '', '']];
        $('table-editor-container').innerHTML = renderTableEditor(_tableHeaders, _tableRows);
    }
}

function renderFilePreviewUI() {
    const box = $('std-file-preview-box');
    if (!box) return;
    if (_uploadedStandardFileUrl) {
        box.style.display = 'flex';
        $('std-file-name').textContent = _uploadedStandardFileName || 'Файл';
        $('std-file-status').textContent = 'Готов к сохранению';
        $('std-file-btn').style.display = 'none';
    } else {
        box.style.display = 'none';
        $('std-file-btn').style.display = 'block';
    }
}

async function openAddStandard() {
    _uploadedStandardImageUrl = '';
    _uploadedStandardFileUrl = '';
    _uploadedStandardFileName = '';
    _tableHeaders = [];
    _tableRows = [];
    const groupOpts = STANDARD_GROUPS.map(g => `<option value="${g}">${g}</option>`).join('');
    openModal('Новый стандарт', `
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group">
                <label>Обложка (фото)</label>
                <input type="file" id="std-image-file" accept="image/*" style="display:none;">
                <button type="button" class="btn btn--ghost" id="std-image-btn" style="width:100%;padding:16px;border-style:dashed;border-radius:14px;">Прикрепить фото</button>
                <div id="std-image-preview-box" style="display:none;margin-top:12px;text-align:center;">
                    <img id="std-image-preview" style="max-width:100%;max-height:100px;border-radius:12px;object-fit:contain;">
                </div>
            </div>
            <div class="form-group">
                <label>Документ (PDF, Word, Excel)</label>
                <input type="file" id="std-file-file" accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv" style="display:none;">
                <button type="button" class="btn btn--ghost" id="std-file-btn" style="width:100%;padding:16px;border-style:dashed;border-radius:14px;">Прикрепить файл</button>
                <div id="std-file-preview-box" style="display:none;margin-top:12px;padding:12px;background:var(--bg-card);border-radius:12px;align-items:center;gap:12px;">
                    <div style="flex:1;min-width:0;"><div id="std-file-name" style="font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"></div><div id="std-file-status" style="font-size:12px;color:var(--text-terc);"></div></div>
                    <button type="button" class="btn btn--ghost" style="font-size:10px;padding:4px;" onclick="_uploadedStandardFileUrl='';_uploadedStandardFileName='';renderFilePreviewUI();">Удал.</button>
                </div>
            </div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>Номер стандарта</label><input class="form-input" id="std-number" placeholder="СТ-001"></div>
            <div class="form-group"><label>Группа</label><select class="form-input" id="std-group">${groupOpts}</select></div>
        </div>
        <div class="form-group"><label>Заголовок</label><input class="form-input" id="std-title" maxlength="150"></div>
        <div class="form-group"><label>Тип контента</label><select class="form-input" id="std-content-type" onchange="switchContentTypeUI(this.value)"><option value="text">Текст</option><option value="table">Таблица</option></select></div>
        <div id="std-text-area">
            <div class="form-group"><label>Текст стандарта</label><div contenteditable="true" id="std-body" class="rich-editor" style="min-height:150px;padding:12px;background:var(--bg);border:1px solid rgba(0,0,0,0.1);border-radius:10px;outline:none;"></div></div>
        </div>
        <div id="std-table-area" style="display:none;margin-bottom:24px;">
            <div class="form-group" style="background:rgba(67,233,123,0.08);padding:16px;border-radius:12px;border:1px dashed var(--green);">
                <label style="color:#1B7A36;">Вставить таблицу из Excel/Word (Ctrl+V)</label>
                <textarea class="form-textarea" id="paste-table-area" placeholder="Скопируйте таблицу из Excel и вставьте сюда..." style="min-height:80px;font-size:13px;background:#fff;margin-bottom:0;"></textarea>
                <div class="form-hint" style="color:#1B7A36;opacity:0.8;">После вставки таблица появится ниже. Вы сможете её отредактировать.</div>
            </div>
            <label style="display:block;font-size:12px;font-weight:700;color:var(--text-terc);margin-bottom:8px;text-transform:uppercase;">Ручная настройка</label>
            <div id="table-editor-container"></div>
        </div>
        <div class="form-hint" id="std-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="create-std-btn">Создать</button>`);

    // Paste table
    $('paste-table-area').addEventListener('paste', (e) => {
        setTimeout(() => {
            const text = e.target.value;
            if (text.trim()) {
                const rows = text.trim().split('\n').map(line => line.split('\t'));
                if (rows.length) {
                    _tableHeaders = rows[0];
                    _tableRows = rows.slice(1).map(r => { const newR = []; for(let i=0;i<_tableHeaders.length;i++) newR.push(r[i]||''); return newR; });
                    $('table-editor-container').innerHTML = renderTableEditor(_tableHeaders, _tableRows);
                    $('paste-table-area').value = '';
                    $('paste-table-area').placeholder = 'Таблица вставлена. Отредактируйте ниже.';
                }
            }
        }, 100);
    });

    // Image upload
    $('std-image-btn').addEventListener('click', () => $('std-image-file').click());
    $('std-image-file').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 15*1024*1024) { toast('Файл слишком большой (макс 15MB)', 'error'); return; }
        const btn = $('std-image-btn');
        btn.textContent = 'Загрузка...';
        btn.disabled = true;
        try {
            const res = await uploadFile(file);
            _uploadedStandardImageUrl = res.url;
            $('std-image-preview').src = getFileUrl(res.url);
            $('std-image-preview-box').style.display = 'block';
            btn.textContent = 'Фото загружено';
            btn.style.borderColor = 'var(--green)';
        } catch (err) { toast(err.message, 'error'); btn.textContent = 'Прикрепить фото'; } finally { btn.disabled = false; }
    });

    // File upload
    $('std-file-btn').addEventListener('click', () => $('std-file-file').click());
    $('std-file-file').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 15*1024*1024) { toast('Файл слишком большой (макс 15MB)', 'error'); return; }
        const btn = $('std-file-btn');
        btn.textContent = 'Загрузка...';
        btn.disabled = true;
        try {
            const res = await uploadFile(file);
            _uploadedStandardFileUrl = res.url;
            _uploadedStandardFileName = res.name;
            renderFilePreviewUI();
        } catch (err) { toast(err.message, 'error'); } finally { btn.disabled = false; btn.textContent = 'Прикрепить файл'; }
    });

    $('create-std-btn').addEventListener('click', async () => {
        const errEl = $('std-error'); errEl.textContent = '';
        const type = $('std-content-type').value;
        const body = {
            number: $('std-number').value.trim(), group_name: $('std-group').value,
            title: $('std-title').value.trim(), image_url: _uploadedStandardImageUrl,
            file_url: _uploadedStandardFileUrl, file_name: _uploadedStandardFileName,
            content_type: type, content_data: type === 'table' ? { headers: _tableHeaders, rows: _tableRows } : null
        };
        if (type === 'text') {
            body.body = cleanHTML($('std-body').innerHTML);
            if (!body.body || body.body === '<br>') { errEl.textContent = 'Заполните текст стандарта'; return; }
        } else {
            body.body = 'Таблица';
            if (!_tableHeaders.length || !_tableRows.length) { errEl.textContent = 'Заполните таблицу'; return; }
        }
        if (!body.title) { errEl.textContent = 'Заполните заголовок'; return; }
        try {
            await api('/api/admin/standard/add', body);
            toast('Стандарт создан', 'success'); closeModal(); loadStandards();
        } catch (e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}

async function openStdEdit(id) {
    if (!hasPerm('standards_edit')) { toast('Нет права', 'error'); return; }
    let stdData, n;
    try {
        stdData = await cachedApi('/api/admin/standards', {});
        n = (stdData.standards||[]).find(x => x.id === id);
    } catch(e) { return; }
    if (!n) return;

    _uploadedStandardImageUrl = n.image_url || '';
    _uploadedStandardFileUrl = n.file_url || '';
    _uploadedStandardFileName = n.file_name || '';
    _tableHeaders = [];
    _tableRows = [];

    const isTable = n.content_type === 'table' && n.content_data;
    if (isTable) {
        _tableHeaders = n.content_data.headers || [];
        _tableRows = n.content_data.rows || [];
    }

    const groupOpts = STANDARD_GROUPS.map(g => `<option value="${g}" ${n.group_name===g?'selected':''}>${g}</option>`).join('');
    openModal('Редактировать стандарт', `
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group">
                <label>Обложка (фото)</label>
                <input type="file" id="std-image-file-edit" accept="image/*" style="display:none;">
                <button type="button" class="btn btn--ghost" id="std-image-btn-edit" style="width:100%;padding:16px;border-style:dashed;border-radius:14px;">${n.image_url ? 'Заменить фото' : 'Прикрепить фото'}</button>
                <div id="std-image-preview-box-edit" style="display:${n.image_url?'block':'none'};margin-top:12px;text-align:center;">
                    <img id="std-image-preview-edit" src="${getFileUrl(n.image_url)}" style="max-width:100%;max-height:100px;border-radius:12px;object-fit:contain;">
                </div>
            </div>
            <div class="form-group">
                <label>Документ (PDF, Word, Excel)</label>
                <input type="file" id="std-file-file-edit" accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv" style="display:none;">
                <button type="button" class="btn btn--ghost" id="std-file-btn-edit" style="width:100%;padding:16px;border-style:dashed;border-radius:14px;${n.file_url?'display:none;':''}">Прикрепить файл</button>
                <div id="std-file-preview-box-edit" style="display:${n.file_url?'flex':'none'};margin-top:12px;padding:12px;background:var(--bg-card);border-radius:12px;align-items:center;gap:12px;">
                    <div style="flex:1;min-width:0;"><div style="font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(n.file_name||'Документ')}</div><div style="font-size:12px;color:var(--text-terc);">Готов к сохранению</div></div>
                    <button type="button" class="btn btn--ghost" style="font-size:10px;padding:4px;" onclick="_uploadedStandardFileUrl='';_uploadedStandardFileName='';$('#std-file-btn-edit').show();$('#std-file-preview-box-edit').hide();">Удал.</button>
                </div>
            </div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>Номер</label><input class="form-input" id="edit-std-number" value="${esc(n.number||'')}"></div>
            <div class="form-group"><label>Группа</label><select class="form-input" id="edit-std-group">${groupOpts}</select></div>
        </div>
        <div class="form-group"><label>Заголовок</label><input class="form-input" id="edit-std-title" value="${esc(n.title)}"></div>
        <div class="form-group"><label>Тип контента</label><select class="form-input" id="edit-std-content-type" onchange="switchContentTypeUI(this.value)"><option value="text" ${!isTable?'selected':''}>Текст</option><option value="table" ${isTable?'selected':''}>Таблица</option></select></div>
        <div id="std-text-area-edit" style="display:${isTable?'none':'block'};">
            <div class="form-group"><label>Текст стандарта</label><div contenteditable="true" id="edit-std-body" style="min-height:150px;padding:12px;background:var(--bg);border:1px solid rgba(0,0,0,0.1);border-radius:10px;outline:none;">${!isTable?cleanHTML(n.body||''):'')}</div></div>
        </div>
        <div id="std-table-area-edit" style="display:${isTable?'block':'none'};margin-bottom:24px;">
            <div class="form-group" style="background:rgba(67,233,123,0.08);padding:16px;border-radius:12px;border:1px dashed var(--green);">
                <label style="color:#1B7A36;">Вставить таблицу заново из Excel/Word (Ctrl+V)</label>
                <textarea class="form-textarea" id="paste-table-area-edit" placeholder="Скопируйте таблицу из Excel и вставьте сюда..." style="min-height:80px;font-size:13px;background:#fff;margin-bottom:0;"></textarea>
                <div class="form-hint" style="color:#1B7A36;opacity:0.8;">Вставка перезапишет текущую таблицу ниже.</div>
            </div>
            <label style="display:block;font-size:12px;font-weight:700;color:var(--text-terc);margin-bottom:8px;text-transform:uppercase;">Ручная настройка</label>
            <div id="table-editor-container-edit"></div>
        </div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="save-std-btn">Сохранить</button>`);

    // Table editor
    if (isTable) {
        $('table-editor-container-edit').innerHTML = renderTableEditor(_tableHeaders, _tableRows);
    }

    // Paste handler
    $('paste-table-area-edit').addEventListener('paste', (e) => {
        setTimeout(() => {
            const text = e.target.value;
            if (text.trim()) {
                const rows = text.trim().split('\n').map(line => line.split('\t'));
                if (rows.length) {
                    _tableHeaders = rows[0];
                    _tableRows = rows.slice(1).map(r => { const newR = []; for(let i=0;i<_tableHeaders.length;i++) newR.push(r[i]||''); return newR; });
                    $('table-editor-container-edit').innerHTML = renderTableEditor(_tableHeaders, _tableRows);
                }
            }
        }, 100);
    });

    // Image upload
    $('std-image-btn-edit').addEventListener('click', () => $('std-image-file-edit').click());
    $('std-image-file-edit').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 15*1024*1024) { toast('Файл слишком большой (макс 15MB)', 'error'); return; }
        const btn = $('std-image-btn-edit');
        btn.textContent = 'Загрузка...';
        btn.disabled = true;
        try {
            const res = await uploadFile(file);
            _uploadedStandardImageUrl = res.url;
            $('std-image-preview-edit').src = getFileUrl(res.url);
            $('std-image-preview-box-edit').style.display = 'block';
            btn.textContent = 'Фото загружено';
        } catch (err) { toast(err.message, 'error'); btn.textContent = 'Заменить фото'; } finally { btn.disabled = false; }
    });

    // File upload
    $('std-file-btn-edit').addEventListener('click', () => $('std-file-file-edit').click());
    $('std-file-file-edit').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 15*1024*1024) { toast('Файл слишком большой (макс 15MB)', 'error'); return; }
        const btn = $('std-file-btn-edit');
        btn.textContent = 'Загрузка...';
        btn.disabled = true;
        try {
            const res = await uploadFile(file);
            _uploadedStandardFileUrl = res.url;
            _uploadedStandardFileName = res.name;
            $('std-file-btn-edit').style.display = 'none';
            $('std-file-preview-box-edit').style.display = 'flex';
        } catch (err) { toast(err.message, 'error'); } finally { btn.disabled = false; btn.textContent = 'Прикрепить файл'; }
    });

    $('save-std-btn').addEventListener('click', async () => {
        const type = $('edit-std-content-type').value;
        const body = {
            id, number: $('edit-std-number').value.trim(), group_name: $('edit-std-group').value,
            title: $('edit-std-title').value.trim(), image_url: _uploadedStandardImageUrl,
            file_url: _uploadedStandardFileUrl, file_name: _uploadedStandardFileName,
            content_type: type, content_data: type === 'table' ? { headers: _tableHeaders, rows: _tableRows } : null
        };
        if (type === 'text') { body.body = cleanHTML($('edit-std-body').innerHTML); } else { body.body = 'Таблица'; }
        try {
            await api('/api/admin/standard/update', body);
            toast('Сохранено', 'success'); closeModal(); loadStandards();
        } catch (e) { toast('Ошибка: '+e.message, 'error'); }
    });
}

async function approveStandard(id) { try { await api('/api/admin/standard/approve', { id }); toast('Одобрено', 'success'); loadStandards(); } catch(e) { toast('Ошибка: '+e.message, 'error'); } }
async function rejectStandard(id) { try { await api('/api/admin/standard/reject', { id }); toast('Отклонено', 'success'); loadStandards(); } catch(e) { toast('Ошибка: '+e.message, 'error'); } }
async function deleteStandard(id) { if(!confirm('Удалить?')) return; try { await api('/api/admin/standard/delete', { id }); toast('Удалено', 'success'); loadStandards(); } catch(e) { toast('Ошибка: '+e.message, 'error'); } }

// ═══ FAQ ═══
async function loadFaq() {
    const canEdit = hasPerm('faq_edit');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header">
                <div class="neu-card__header-title">FAQ</div>
                ${canEdit ? '<button class="btn btn--primary" onclick="openAddFaq()">+ Добавить</button>' : ''}
            </div>
            <div class="table-wrap"><table class="t"><thead><tr><th>Вопрос</th><th>Ответ</th><th>Действия</th></tr></thead>
            <tbody id="faq-table"></tbody></table></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/faq', {});
        $('faq-table').innerHTML = (data.faq||[]).map(f => `
            <tr><td style="font-weight:600;">${esc(f.question)}</td><td>${esc(f.answer)}</td>
            <td>${canEdit ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="editFaq(${f.id},'${esc(f.question)}','${esc(f.answer)}')">✏️</button>
                <button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="deleteFaq(${f.id})">🗑️</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="3" style="text-align:center;padding:40px;">Пусто</td></tr>';
    } catch(e) {}
}
async function openAddFaq() {
    openModal('Добавить FAQ', `
        <div class="form-group"><label>Вопрос</label><input class="form-input" id="faq-question" maxlength="500"></div>
        <div class="form-group"><label>Ответ</label><textarea class="form-textarea" id="faq-answer" rows="4" maxlength="2000"></textarea></div>
        <div class="form-hint" id="faq-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="faq-save">Добавить</button>`);
    $('faq-save').addEventListener('click', async () => {
        const errEl = $('faq-error'); errEl.textContent = '';
        const q = $('faq-question').value.trim(), a = $('faq-answer').value.trim();
        if (!q || !a) { errEl.textContent = 'Заполните все поля'; return; }
        try { await api('/api/admin/faq/add', { question:q, answer:a }); toast('Добавлено', 'success'); closeModal(); loadFaq(); }
        catch(e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}
async function editFaq(id, q, a) {
    openModal('Редактировать FAQ', `
        <div class="form-group"><label>Вопрос</label><input class="form-input" id="ed-faq-q" value="${esc(q)}" maxlength="500"></div>
        <div class="form-group"><label>Ответ</label><textarea class="form-textarea" id="ed-faq-a" rows="4" maxlength="2000">${esc(a)}</textarea></div>
        <div class="form-hint" id="ed-faq-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="ed-faq-save">Сохранить</button>`);
    $('ed-faq-save').addEventListener('click', async () => {
        const errEl = $('ed-faq-error'); errEl.textContent = '';
        const q = $('ed-faq-q').value.trim(), a = $('ed-faq-a').value.trim();
        if (!q || !a) { errEl.textContent = 'Заполните все поля'; return; }
        try { await api('/api/admin/faq/update', { id, field:'question', value:q }); await api('/api/admin/faq/update', { id, field:'answer', value:a }); toast('Сохранено', 'success'); closeModal(); loadFaq(); }
        catch(e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}
async function deleteFaq(id) { if(!confirm('Удалить?')) return; try { await api('/api/admin/faq/delete', { id }); toast('Удалено', 'success'); loadFaq(); } catch(e) { toast('Ошибка: '+e.message, 'error'); } }

// ═══ RESTAURANTS ═══
async function loadRestaurants() {
    const canCreate = hasPerm('restaurant_create');
    const canEdit = hasPerm('restaurant_edit');
    const canTU = hasPerm('restaurant_tu');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header">
                <div class="neu-card__header-title">Рестораны</div>
                ${canCreate ? '<button class="btn btn--primary" onclick="openAddRestaurant()">+ Добавить</button>' : ''}
            </div>
            <div class="table-wrap"><table class="t"><thead><tr><th>Название</th><th>Адрес</th><th>ТУ</th><th>Статус</th><th>Действия</th></tr></thead><tbody id="rest-table"></tbody></table></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/restaurants', {});
        const restaurants = data.restaurants || [];
        const tuCandidates = data.tu_candidates || [];
        $('rest-table').innerHTML = restaurants.map(r => {
            const st = r.force_status==='open'?'tag--green':'tag--amber';
            const tx = r.force_status==='open'?'Открыт':'Закрыт';
            let acts = '';
            if (canEdit) acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="editRestaurant('${esc(r.key)}')">✏️</button>`;
            if (canTU) acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="assignTU('${esc(r.key)}',${JSON.stringify(tuCandidates).replace(/"/g,'&quot;')})">👤</button>`;
            return `<tr><td style="font-weight:600;">${esc(r.name)}</td><td>${esc(r.address)}</td><td>${esc(r.territory_manager_name||'—')}</td><td><span class="tag ${st}">${tx}</span></td><td>${acts}</td></tr>`;
        }).join('') || '<tr><td colspan="5" style="text-align:center;padding:40px;">Нет ресторанов</td></tr>';
    } catch(e) {}
}
async function openAddRestaurant() {
    openModal('Добавить ресторан', `
        <div class="form-group"><label>Ключ (лат, без пробелов)</label><input class="form-input" id="rest-key" maxlength="50"></div>
        <div class="form-group"><label>Название</label><input class="form-input" id="rest-name" maxlength="100"></div>
        <div class="form-group"><label>Адрес</label><input class="form-input" id="rest-address"></div>
        <div class="form-group"><label>Телефон</label><input class="form-input" id="rest-phone"></div>
        <div class="form-hint" id="rest-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="rest-save">Создать</button>`);
    $('rest-key').addEventListener('input', e => { e.target.value = e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''); });
    $('rest-save').addEventListener('click', async () => {
        const errEl = $('rest-error'); errEl.textContent = '';
        const key = $('rest-key').value.trim().toLowerCase().replace(/\s/g,'_');
        const name = $('rest-name').value.trim();
        if (!key || !name) { errEl.textContent = 'Заполните ключ и название'; return; }
        try { await api('/api/admin/restaurant/add', { key, name, address:$('rest-address').value, phone:$('rest-phone').value }); toast('Создан', 'success'); closeModal(); loadRestaurants(); }
        catch(e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}
async function editRestaurant(key) {
    let r;
    try { const data = await api('/api/admin/restaurants', {}); r = (data.restaurants||[]).find(x=>x.key===key); } catch(e) { return; }
    if (!r) return;
    openModal('Редактировать: '+r.name, `
        <div class="form-group"><label>Название</label><input class="form-input" id="ed-rest-name" value="${esc(r.name)}"></div>
        <div class="form-group"><label>Адрес</label><input class="form-input" id="ed-rest-address" value="${esc(r.address||'')}"></div>
        <div class="form-group"><label>Телефон</label><input class="form-input" id="ed-rest-phone" value="${esc(r.phone||'')}"></div>
        <div class="form-hint" id="ed-rest-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="ed-rest-save">Сохранить</button>`);
    $('ed-rest-save').addEventListener('click', async () => {
        const errEl = $('ed-rest-error'); errEl.textContent = '';
        try { await api('/api/admin/restaurant/update', { key, updates:{ name:$('ed-rest-name').value.trim(), address:$('ed-rest-address').value.trim(), phone:$('ed-rest-phone').value.trim() }}); toast('Сохранено', 'success'); closeModal(); loadRestaurants(); }
        catch(e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}
async function assignTU(key, tuCandidates) {
    openModal('Назначить ТУ', `
        <div class="form-group"><label>Территориальный менеджер</label><select class="form-input" id="tu-select"><option value="">— Не назначен —</option>${(tuCandidates||[]).map(t=>`<option value="${t.user_id}">${esc(t.full_name)}</option>`).join('')}</select></div>
        <div class="form-hint" id="tu-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="tu-save">Назначить</button>`);
    $('tu-save').addEventListener('click', async () => {
        const errEl = $('tu-error'); errEl.textContent = '';
        try { await api('/api/admin/restaurant/tu', { key, territory_manager_id: $('tu-select').value || null }); toast('ТУ назначен', 'success'); closeModal(); loadRestaurants(); }
        catch(e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}

// ═══ CERTIFICATION ═══
async function loadCertification() {
    const canEdit = hasPerm('certification_edit');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header"><div class="neu-card__header-title">Сертификация</div>${canEdit ? '<button class="btn btn--primary" onclick="openAddCert()">+ Добавить вопрос</button>' : ''}</div>
            <div class="table-wrap"><table class="t"><thead><tr><th>Вопрос</th><th>Правильный ответ</th><th>Действия</th></tr></thead><tbody id="cert-table"></tbody></table></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/certification', {});
        const questions = data.questions || [];
        const correctLabels = {a:'A',b:'B',c:'C',d:'D'};
        $('cert-table').innerHTML = questions.map(q => {
            let acts = '';
            if (canEdit) acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="deleteCert(${q.id})">🗑️</button>`;
            return `<tr><td>${esc(q.question)}</td><td><span class="tag tag--green">${correctLabels[q.correct_option?.toLowerCase()]||'—'}</span></td><td>${acts}</td></tr>`;
        }).join('') || '<tr><td colspan="3" style="text-align:center;padding:40px;">Пусто</td></tr>';
    } catch(e) {}
}
async function openAddCert() {
    openModal('Добавить вопрос', `
        <div class="form-group"><label>Вопрос</label><textarea class="form-textarea" id="cert-question" rows="3"></textarea></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>Вариант A</label><input class="form-input" id="cert-a"></div>
            <div class="form-group"><label>Вариант B</label><input class="form-input" id="cert-b"></div>
            <div class="form-group"><label>Вариант C</label><input class="form-input" id="cert-c"></div>
            <div class="form-group"><label>Вариант D</label><input class="form-input" id="cert-d"></div>
        </div>
        <div class="form-group"><label>Правильный</label><select class="form-input" id="cert-correct"><option value="a">A</option><option value="b">B</option><option value="c">C</option><option value="d">D</option></select></div>
        <div class="form-hint" id="cert-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="cert-save">Добавить</button>`);
    $('cert-save').addEventListener('click', async () => {
        const errEl = $('cert-error'); errEl.textContent = '';
        const q=$('cert-question').value.trim(), a=$('cert-a').value.trim(), b=$('cert-b').value.trim(), c=$('cert-c').value.trim(), d=$('cert-d').value.trim();
        if (!q||!a||!b||!c||!d) { errEl.textContent = 'Заполните все поля'; return; }
        try { await api('/api/admin/certification/add', { question:q, option_a:a, option_b:b, option_c:c, option_d:d, correct_option:$('cert-correct').value }); toast('Добавлено', 'success'); closeModal(); loadCertification(); }
        catch(e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}
async function deleteCert(id) { if(!confirm('Удалить?')) return; try { await api('/api/admin/certification/delete', { id }); toast('Удалено', 'success'); loadCertification(); } catch(e) { toast('Ошибка: '+e.message, 'error'); } }

// ═══ POSITIONS ═══
async function loadPositions() {
    const canEdit = hasPerm('positions_edit');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header"><div class="neu-card__header-title">Должности</div>${canEdit ? '<button class="btn btn--primary" onclick="openAddPosition()">+ Добавить</button>' : ''}</div>
            <div class="table-wrap"><table class="t"><thead><tr><th>Название</th><th>Ставка</th><th>Статус</th><th>Действия</th></tr></thead><tbody id="positions-table"></tbody></table></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/positions', {});
        $('positions-table').innerHTML = (data.positions||[]).map(p => {
            let acts = '';
            if (canEdit && !p.is_archived) acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="archivePosition(${p.id})">🗑️</button>`;
            return `<tr><td style="font-weight:600;">${esc(p.name)}</td><td>${p.rate!=null?'₽'+p.rate:'—'}</td><td><span class="tag ${p.is_archived?'tag--amber':'tag--green'}">${p.is_archived?'Архив':'Активна'}</span></td><td>${acts}</td></tr>`;
        }).join('') || '<tr><td colspan="4" style="text-align:center;padding:40px;">Пусто</td></tr>';
    } catch(e) {}
}
async function openAddPosition() {
    openModal('Добавить должность', `
        <div class="form-group"><label>Название</label><input class="form-input" id="pos-name" maxlength="100"></div>
        <div class="form-hint" id="pos-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="pos-save">Добавить</button>`);
    $('pos-save').addEventListener('click', async () => {
        const errEl = $('pos-error'); errEl.textContent = '';
        const name = $('pos-name').value.trim();
        if (!name) { errEl.textContent = 'Введите название'; return; }
        try { await api('/api/admin/position/add', { name }); toast('Добавлено', 'success'); closeModal(); loadPositions(); }
        catch(e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}
async function archivePosition(id) { if(!confirm('Архивировать?')) return; try { await api('/api/admin/position/archive', { id }); toast('Архив', 'success'); loadPositions(); } catch(e) { toast('Ошибка: '+e.message, 'error'); } }

// ═══ QUESTIONS ═══
async function loadQuestions() {
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header"><div class="neu-card__header-title">Вопросы от сотрудников</div></div>
            <div class="table-wrap"><table class="t"><thead><tr><th>От</th><th>Вопрос</th><th>Дата</th><th>Статус</th><th>Действия</th></tr></thead><tbody id="questions-table"></tbody></table></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/questions', {});
        const questions = data.questions || [];
        const canReply = hasPerm('questions_reply');
        $('questions-table').innerHTML = questions.map(q => {
            let acts = '';
            if (!q.replied && canReply) acts += `<button class="btn btn--primary" style="padding:4px 8px;font-size:11px;" onclick="replyQuestion(${q.id})">Ответить</button>`;
            return `<tr><td>${esc(q.full_name||'—')}</td><td>${esc(q.text||'—')}</td><td style="color:var(--text-terc);">${fmtDate(q.created_at)}</td><td><span class="tag ${q.replied?'tag--green':'tag--amber'}">${q.replied?'Ответен':'Ожидает'}</span></td><td>${acts}</td></tr>`;
        }).join('') || '<tr><td colspan="5" style="text-align:center;padding:40px;">Пусто</td></tr>';
    } catch(e) {}
}
async function replyQuestion(qid) {
    openModal('Ответить на вопрос', `
        <div class="form-group"><label>Ваш ответ</label><textarea class="form-textarea" id="reply-text" rows="4" maxlength="2000"></textarea></div>
        <div class="form-hint" id="reply-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="reply-save">Отправить</button>`);
    $('reply-save').addEventListener('click', async () => {
        const errEl = $('reply-error'); errEl.textContent = '';
        const text = $('reply-text').value.trim();
        if (!text) { errEl.textContent = 'Введите ответ'; return; }
        try { await api('/api/admin/question/reply', { id:qid, text }); toast('Ответ отправлен', 'success'); closeModal(); loadQuestions(); }
        catch(e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}

// ═══ ADMINS ═══
async function loadAdmins() {
    if (!isSuperAdmin()) { $('page-content').innerHTML = '<div class="empty">Только для супер-админа</div>'; return; }
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header"><div class="neu-card__header-title">Администраторы</div></div>
            <div class="table-wrap"><table class="t"><thead><tr><th>Логин</th><th>Имя</th><th>Роль</th><th>Действия</th></tr></thead><tbody id="admins-table"></tbody></table></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/admins', {});
        const admins = data.admins || [];
        $('admins-table').innerHTML = admins.map(a => {
            const role = a.is_super_admin ? 'tag--purple' : 'tag--blue';
            const tx = a.is_super_admin ? 'Супер-админ' : 'Админ';
            let acts = '';
            if (isSuperAdmin() && !a.is_super_admin) acts += `<button class="btn btn--primary" style="padding:4px 8px;font-size:11px;" onclick="openSetPerms(${a.user_id})">🔑 Права</button>`;
            return `<tr><td style="font-weight:600;">${esc(a.login)}</td><td>${esc(a.full_name)}</td><td><span class="tag ${role}">${tx}</span></td><td>${acts}</td></tr>`;
        }).join('') || '<tr><td colspan="4" style="text-align:center;padding:40px;">Пусто</td></tr>';
    } catch(e) {}
}

// ═══════════════════════════════════════════
// TASK 1 (продолжение): ПРАВА АДМИНОВ
// ═══════════════════════════════════════════
async function openSetPerms(uid) {
    let login, existingPerms = {};
    try {
        const data = await api('/api/admin/admins', {});
        const a = (data.admins||[]).find(x => x.user_id === uid);
        if (!a) { toast('Не найден', 'error'); return; }
        login = a.login; existingPerms = a.permissions || {};
    } catch(e) { return; }

    const permsList = [
        { key:'users_create', label:'Добавлять сотрудников' },
        { key:'users_edit', label:'Редактировать сотрудников' },
        { key:'users_fire', label:'Увольнять сотрудников' },
        { key:'citizenships_edit', label:'Управлять гражданствами' },
        { key:'medbook_edit', label:'Заполнять медкнижки' },
        { key:'restaurant_create', label:'Добавлять рестораны' },
        { key:'restaurant_edit', label:'Редактировать рестораны' },
        { key:'restaurant_tu', label:'Менять ТУ у ресторанов' },
        { key:'news_write', label:'Писать новости' },
        { key:'news_edit', label:'Редактировать новости' },
        { key:'news_suggest', label:'Предлагать новости' },
        { key:'faq_edit', label:'Редактировать FAQ' },
        { key:'positions_edit', label:'Управлять должностями' },
        { key:'questions_reply', label:'Отвечать на вопросы' },
        { key:'certification_edit', label:'Управлять сертификацией' },
    ];

    openModal(`Права: ${login}`, `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px;" id="perm-grid">
            ${permsList.map(p => `<label style="display:flex;align-items:center;gap:8px;padding:8px;background:var(--bg-card);border-radius:8px;cursor:pointer;"><input type="checkbox" value="${p.key}" ${existingPerms[p.key]?'checked':''}> ${p.label}</label>`).join('')}
        </div>
        <div class="form-hint" id="perms-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="perms-save">Сохранить</button>`);

    $('perms-save').addEventListener('click', async () => {
        const errEl = $('perms-error'); errEl.textContent = '';
        const permissions = {};
        $('perm-grid').querySelectorAll('input:checked').forEach(cb => { permissions[cb.value] = true; });
        try {
            await api('/api/admin/set-permissions', { user_id: uid, permissions });
            toast('Права обновлены', 'success'); closeModal(); loadAdmins();
        } catch(e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}

// ═══ REPORTS ═══
async function loadReports() {
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header"><div class="neu-card__header-title">Отчёты по персоналу</div></div>
            <div class="table-wrap"><table class="t"><thead><tr><th>Всего</th><th>Активных</th><th>Уволено</th><th>Новые (7д)</th><th>Вопросы</th><th>Новости на модерации</th><th>Стандарты на модерации</th></tr></thead>
            <tbody id="reports-body"><tr><td colspan="7" style="text-align:center;padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody></table></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/reports', {});
        const r = data.report || {};
        $('reports-body').innerHTML = `<tr>
            <td style="font-weight:700;font-size:18px;">${r.total||0}</td>
            <td style="font-weight:700;color:var(--green);font-size:18px;">${r.active||0}</td>
            <td style="font-weight:700;color:var(--amber);font-size:18px;">${r.fired||0}</td>
            <td>${r.new7||0}</td><td>${r.questions_open||0}</td><td>${r.news_pending||0}</td><td>${r.standards_pending||0}</td>
        </tr>`;
    } catch(e) { $('reports-body').innerHTML = `<tr><td colspan="7" style="text-align:center;padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`; }
}

// ═══ AUDIT ═══
async function loadAudit() {
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header"><div class="neu-card__header-title">История действий</div></div>
            <div class="table-wrap"><table class="t"><thead><tr><th>Дата</th><th>Админ</th><th>Действие</th><th>Объект</th></tr></thead><tbody id="audit-table"></tbody></table></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/audit', {});
        const logs = (data.audit || []).slice(0, 100);
        $('audit-table').innerHTML = logs.map(a => `
            <tr><td style="color:var(--text-terc);font-size:12px;">${fmtDate(a.created_at, true)}</td><td>${esc(a.admin_full_name||'—')}</td><td><span class="tag tag--purple">${esc(a.action||'—')}</span></td><td style="color:var(--text-sec);">${esc(a.details||'—')}</td></tr>`).join('') || '<tr><td colspan="4" style="text-align:center;padding:40px;">Пусто</td></tr>';
    } catch(e) { $('audit-table').innerHTML = `<tr><td colspan="4" style="text-align:center;padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`; }
}

// ═══════════════════════════════════════════
// TASK 1 (продолжение): ГРАЖДАНСТВА
// ═══════════════════════════════════════════
async function loadCitizenships() {
    const canEdit = hasPerm('citizenships_edit');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header">
                <div class="neu-card__header-title">Гражданства</div>
                ${canEdit ? '<button class="btn btn--primary" onclick="openAddCitizenship()">+ Добавить</button>' : ''}
            </div>
            <div class="table-wrap"><table class="t"><thead><tr><th>Название</th><th>Действия</th></tr></thead><tbody id="cits-table"></tbody></table></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/citizenships', {});
        $('cits-table').innerHTML = (data.citizenships||[]).map(c => {
            let acts = '';
            if (canEdit) acts += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="deleteCitizenship(${c.id})">🗑️</button>`;
            return `<tr><td style="font-weight:600;">${esc(c.name)}</td><td>${acts}</td></tr>`;
        }).join('') || '<tr><td colspan="2" style="text-align:center;padding:40px;">Пусто</td></tr>';
    } catch(e) {}
}
async function openAddCitizenship() {
    openModal('Добавить гражданство', `
        <div class="form-group"><label>Название</label><input class="form-input" id="cit-name" maxlength="50"></div>
        <div class="form-hint" id="cit-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="cit-save">Добавить</button>`);
    $('cit-save').addEventListener('click', async () => {
        const errEl = $('cit-error'); errEl.textContent = '';
        const name = $('cit-name').value.trim();
        if (!name) { errEl.textContent = 'Введите название'; return; }
        try { await api('/api/admin/citizenship/add', { name }); toast('Добавлено', 'success'); closeModal(); loadCitizenships(); }
        catch(e) { errEl.textContent = 'Ошибка: '+e.message; }
    });
}
async function deleteCitizenship(id) { if(!confirm('Удалить?')) return; try { await api('/api/admin/citizenship/delete', { id }); toast('Удалено', 'success'); loadCitizenships(); } catch(e) { toast('Ошибка: '+e.message, 'error'); } }

// ═══ SALES ═══
async function loadSales() {
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header"><div class="neu-card__header-title">Товарооборот</div></div>
            <div class="empty" style="padding:60px;">Функционал в разработке</div>
        </div>`;
}

// ═══════════════════════════════════════════
// PAGE LOADERS REGISTRY
// ═══════════════════════════════════════════
const PAGE_LOADERS = {
    dashboard: loadDashboard,
    users: loadUsers,
    medbooks: loadMedbooks,
    news: loadNews,
    standards: loadStandards,
    certification: loadCertification,
    faq: loadFaq,
    restaurants: loadRestaurants,
    positions: loadPositions,
    citizenships: loadCitizenships,
    'medbook-dirs': loadMedbookDirs,
    questions: loadQuestions,
    admins: loadAdmins,
    reports: loadReports,
    audit: loadAudit,
    sales: loadSales,
};

// ═══ INIT (DOMContentLoaded) ═══
document.addEventListener('DOMContentLoaded', () => {
    // Modal events
    $('modal-close')?.addEventListener('click', closeModal);
    $('modal-overlay')?.addEventListener('click', e => { if (e.target === $('modal-overlay')) closeModal(); });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && $('modal-overlay')?.classList.contains('show')) closeModal();
    });

    // Change password
    $('change-password-btn')?.addEventListener('click', () => {
        openModal('Сменить пароль', `
            <div class="form-group"><label>Текущий пароль</label><input class="form-input" id="cp-old" type="password"></div>
            <div class="form-group"><label>Новый пароль</label><input class="form-input" id="cp-new" type="password"><div class="form-hint">Минимум 8 символов</div></div>
            <div class="form-group"><label>Повторите</label><input class="form-input" id="cp-new2" type="password"></div>
            <div class="form-hint error" id="cp-error"></div>
        `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="cp-save">Сохранить</button>`);
        $('cp-save')?.addEventListener('click', async () => {
            const errEl = $('cp-error'); errEl.textContent = '';
            if (!$('cp-old')?.value) { errEl.textContent = 'Введите текущий пароль'; return; }
            if (!$('cp-new')?.value || $('cp-new').value.length < 8) { errEl.textContent = 'Новый минимум 8 символов'; return; }
            if ($('cp-new').value !== $('cp-new2')?.value) { errEl.textContent = 'Пароли не совпадают'; return; }
            try {
                await api('/api/admin/change-password', { old_password: $('cp-old').value, new_password: $('cp-new').value });
                toast('Пароль изменён', 'success'); closeModal();
            } catch (e) {
                if (e.message === 'wrong_password') errEl.textContent = 'Текущий пароль неверный';
                else if (e.message === 'password_too_short') errEl.textContent = 'Минимум 8 символов';
                else errEl.textContent = 'Ошибка: ' + e.message;
            }
        });
    });

    // Login events
    $('login-login')?.addEventListener('input', e => {
        e.target.value = e.target.value.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 5);
    });
    $('login-btn')?.addEventListener('click', doLogin);
    $('login-password')?.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
    $('login-login')?.addEventListener('keydown', e => { if (e.key === 'Enter') $('login-password')?.focus(); });

    // Sidebar events
    const burgerEl = burger();
    const overlayEl = overlay();
    if (burgerEl) burgerEl.addEventListener('click', openSidebar);
    if (overlayEl) overlayEl.addEventListener('click', closeSidebar);

    // Navigation
    document.querySelectorAll('.nav-item').forEach(item => {
        if (item) item.addEventListener('click', e => { e.preventDefault(); closeSidebar(); navigate(item.dataset.page); });
    });

    // Logout
    $('logout-btn')?.addEventListener('click', async () => {
        if (!confirm('Выйти?')) return;
        try { await api('/api/auth/logout', {}); } catch (e) {}
        clearToken(); ME = null; closeSidebar(); clearCache(); showLogin();
    });

    // Mobile sidebar overlay
    const mobileOverlay = document.getElementById('overlay');
    if (mobileOverlay) {
        mobileOverlay.addEventListener('click', closeSidebar);
    }

    // ═══ INITIALIZE ═══
    try {
        if (getToken()) { checkAdminAndLoad(); } else { showLogin(); }
    } catch (e) {
        console.error('[INIT] Failed:', e);
    }
});
