/* ═══════════════════════════════════════════
   WOKKER ADMIN — FULLY FUNCTIONAL DASHBOARD
   ═══════════════════════════════════════════ */

window.addEventListener('error', e => { e.preventDefault(); console.error('[global]', e.error); });

const TOKEN_KEY = 'wokker_admin_token';
const LOGIN_RE = /^[a-z]{3}\d{2}$/;
let ME = null;
let _cache = {};
let _adminPermsMap = {};

const $ = id => document.getElementById(id);
const esc = s => (s == null ? '' : String(s)).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }
function getFileUrl(url) {
    if (!url) return '';
    if (/^https?:\/\//i.test(url) || url.startsWith('data:')) return url;
    const cleanPath = url.startsWith('/') ? url : '/' + url;
    return cleanPath + (cleanPath.includes('?') ? '&' : '?') + 'webToken=' + encodeURIComponent(getToken());
}

let _cacheData = {};
async function cachedApi(path, body, ttl = 30000) {
    const key = path + (body ? JSON.stringify(body) : '');
    const now = Date.now();
    if (_cacheData[key] && now - _cacheData[key].time < ttl) return _cacheData[key].data;
    const data = await api(path, body);
    _cacheData[key] = { data, time: now };
    return data;
}
function clearCache() { _cacheData = {}; _cache = {}; }

function toast(text, type) {
    const container = $('toasts');
    if (!container) return;
    const el = document.createElement('div');
    el.className = 'toast' + (type ? ' ' + type : '');
    el.textContent = text;
    container.appendChild(el);
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

async function api(path, body) {
    const res = await fetch(path, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + getToken(),
        },
        body: JSON.stringify(body || {}),
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
            method: 'POST',
            headers: { 'X-Token': getToken() },
            body: formData,
        });
        if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.error || 'Upload failed'); }
        return await res.json();
    } catch (e) { throw new Error(e.message || 'Ошибка сети при загрузке файла'); }
}

function openSidebar() {
    const sidebar = $('sidebar'); const overlayEl = $('overlay');
    if (sidebar) sidebar.classList.add('sidebar--open');
    if (overlayEl) { overlayEl.classList.add('sidebar-overlay--show'); document.body.style.overflow = 'hidden'; }
}
function closeSidebar() {
    const sidebar = $('sidebar'); const overlayEl = $('overlay');
    if (sidebar) sidebar.classList.remove('sidebar--open');
    if (overlayEl) { overlayEl.classList.remove('sidebar-overlay--show'); document.body.style.overflow = ''; }
}

function isSuperAdmin() { return !!(ME && ME.is_super_admin); }
function isHR() {
    if (!ME) return false;
    if (ME.is_hr) return true;
    return String(ME.position || '').trim().toUpperCase() === 'HR';
}
function canPublish() { return isSuperAdmin() || isHR(); }
function hasPerm(perm) {
    if (!ME) return false;
    if (ME.is_super_admin || isHR()) return true;
    return !!(ME.permissions && ME.permissions[perm]);
}

function openModal(title, bodyHtml, footerHtml, opts) {
    opts = opts || {};
    const titleEl = $('modal-title'); if (titleEl) titleEl.textContent = title;
    const bodyEl = $('modal-body'); if (bodyEl) bodyEl.innerHTML = bodyHtml;
    const footerEl = $('modal-footer'); if (footerEl) footerEl.innerHTML = footerHtml || '';
    const boxEl = $('modal-box'); if (boxEl) boxEl.className = 'modal' + (opts.wide ? ' wide' : '');
    const overlayEl = $('modal-overlay'); if (overlayEl) overlayEl.classList.add('show');
}
function closeModal() {
    const overlayEl = $('modal-overlay'); if (overlayEl) overlayEl.classList.remove('show');
}

function showLogin() {
    const appEl = $('app'); const loginScreenEl = $('login-screen');
    if (appEl) appEl.style.display = 'none';
    if (loginScreenEl) loginScreenEl.style.display = 'flex';
    const errEl = $('login-error'); if (errEl) errEl.textContent = '';
    const loginInput = $('login-login'); const passInput = $('login-password');
    if (loginInput) loginInput.value = ''; if (passInput) passInput.value = '';
    clearCache();
}
function showApp() {
    const appEl = $('app'); const loginScreenEl = $('login-screen');
    if (appEl) appEl.style.display = 'block';
    if (loginScreenEl) loginScreenEl.style.display = 'none';
}

async function doLogin() {
    const loginInput = $('login-login'); const passwordInput = $('login-password');
    if (!loginInput || !passwordInput) return;
    const login = loginInput.value.trim().toLowerCase(); const password = passwordInput.value;
    const errEl = $('login-error'); errEl.textContent = '';
    if (!LOGIN_RE.test(login)) { errEl.textContent = 'Логин: 3 латинские буквы + 2 цифры'; return; }
    if (!password) { errEl.textContent = 'Введите пароль'; return; }
    const btn = $('login-btn'); btn.disabled = true; btn.textContent = 'Проверяем…';
    try {
        const res = await fetch('/api/admin/login', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ login, password }),
        });
        if (res.status === 401) { errEl.textContent = 'Неверный логин или пароль'; return; }
        if (res.status === 403) { errEl.textContent = 'Аккаунт уволен или нет прав администратора'; return; }
        if (!res.ok) { errEl.textContent = 'Ошибка сервера'; return; }
        const data = await res.json();
        if (!data.token) { errEl.textContent = 'Ошибка'; return; }
        setToken(data.token); clearCache();
        await checkAdminAndLoad();
    } catch (e) { errEl.textContent = 'Сеть недоступна'; }
    finally { btn.disabled = false; btn.textContent = 'Войти'; }
}

async function checkAdminAndLoad() {
    try {
        const res = await api('/api/admin/me', {});
        ME = res.profile;
        const nameEl = $('admin-name'); if (nameEl) nameEl.textContent = ME.full_name || '—';
        const loginEl = $('admin-login'); if (loginEl) loginEl.textContent = '@' + (ME.login || '');
        const roleEl = $('admin-role');
        if (roleEl) {
            roleEl.textContent = ME.is_super_admin ? 'Супер-админ' : isHR() ? 'HR' : 'Админ';
            roleEl.className = 'badge-role ' + (ME.is_super_admin ? 'super' : isHR() ? 'hr' : 'regular');
        }
        const adminsNav = $('nav-admins'); if (adminsNav) adminsNav.style.display = ME.is_super_admin ? 'flex' : 'none';
        const avatarEl = $('topbar-avatar'); if (avatarEl && ME.full_name) avatarEl.textContent = ME.full_name.charAt(0).toUpperCase();
        showApp();
        if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
            navigator.serviceWorker.controller.postMessage({ type: 'SET_TOKEN', token: getToken() });
        }
        navigate('dashboard');
        refreshCounters();
    } catch (e) {
        showLogin();
        const errEl = $('login-error'); if (errEl) errEl.textContent = 'Ошибка: ' + e.message;
    }
}

const PAGE_TITLES = {
    dashboard: 'Дашборд', users: 'Сотрудники', medbooks: 'Медкнижки',
    news: 'Новости', standards: 'Стандарты', certification: 'Сертификация', faq: 'FAQ',
    restaurants: 'Рестораны', positions: 'Должности', citizenships: 'Гражданства',
    questions: 'Вопросы',
    admins: 'Администраторы', reports: 'Отчёты', audit: 'История'
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

const GRADIENTS = [
    'linear-gradient(135deg, #4318FF 0%, #3311DB 100%)',
    'linear-gradient(135deg, #3965FF 0%, #00d2ff 100%)',
    'linear-gradient(135deg, #FFB547 0%, #FF7A00 100%)',
    'linear-gradient(135deg, #05CD99 0%, #12B76A 100%)',
    'linear-gradient(135deg, #EE5D50 0%, #F04438 100%)',
];
function getAvatarGradient(index) { return GRADIENTS[index % GRADIENTS.length]; }

// ═══════════════════════════════════════════
// DASHBOARD
// ═══════════════════════════════════════════
async function loadDashboard() {
    $('page-content').innerHTML = `
        <div class="stats-grid">
            <div class="neu-card neu-card--stat purple">
                <div class="neu-card__icon-wrapper">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
                </div>
                <div class="neu-card__value" id="stat-active"><div class="skeleton skeleton-stat"></div></div>
                <div class="neu-card__label">Активные сотрудники</div>
            </div>
            <div class="neu-card neu-card--stat yellow">
                <div class="neu-card__icon-wrapper">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                </div>
                <div class="neu-card__value" id="stat-pending"><div class="skeleton skeleton-stat"></div></div>
                <div class="neu-card__label">На модерации</div>
            </div>
            <div class="neu-card neu-card--stat blue">
                <div class="neu-card__icon-wrapper">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>
                </div>
                <div class="neu-card__value" id="stat-medbooks"><div class="skeleton skeleton-stat"></div></div>
                <div class="neu-card__label">Медкнижки</div>
            </div>
            <div class="neu-card neu-card--stat green">
                <div class="neu-card__icon-wrapper">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
                </div>
                <div class="neu-card__value" id="stat-questions"><div class="skeleton skeleton-stat"></div></div>
                <div class="neu-card__label">Вопросы</div>
            </div>
        </div>
        <div class="grid-2">
            <div class="neu-card">
                <div class="neu-card__header">
                    <div class="neu-card__header-title">Открытые вопросы</div>
                    <div class="neu-card__header-action" onclick="navigate('questions')">Смотреть все</div>
                </div>
                <div id="dash-questions"><div class="loading">Загрузка...</div></div>
            </div>
            <div class="neu-card">
                <div class="neu-card__header">
                    <div class="neu-card__header-title">Новые сотрудники</div>
                    <div class="neu-card__header-action" onclick="navigate('users')">Смотреть все</div>
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

        const qsContainer = $('dash-questions');
        if (qsContainer) {
            const questions = (data.questions || []).slice(0, 5);
            qsContainer.innerHTML = questions.map(q => `
                <div style="display:flex; gap:16px; padding:16px 0; border-bottom:1px solid var(--border);">
                    <div style="flex:1;">
                        <div style="font-size:15px; font-weight:800; color:var(--text-main); margin-bottom:4px;">${esc(q.full_name || 'Сотрудник')}</div>
                        <div style="font-size:14px; color:var(--text-sec); font-weight:500;">${esc(q.text || '—')}</div>
                        <div style="font-size:12px; color:var(--text-sec); margin-top:8px;">${fmtDate(q.created_at, true)}</div>
                    </div>
                </div>`).join('') || '<div class="loading">Нет открытых вопросов</div>';
        }
        const usersContainer = $('dash-new-users');
        if (usersContainer) {
            const users = (data.users || []).slice(0, 5);
            usersContainer.innerHTML = users.map((u, i) => `
                <div style="display:flex; gap:16px; padding:16px 0; border-bottom:1px solid var(--border); align-items:center;">
                    <div class="avatar" style="background:${getAvatarGradient(i)}; width:40px; height:40px; border-radius:50%; display:flex; align-items:center; justify-content:center; color:#fff; font-weight:800; font-size:16px;">${(u.full_name||'?').charAt(0)}</div>
                    <div style="flex:1;">
                        <div style="font-size:15px; font-weight:800; color:var(--text-main);">${esc(u.full_name||'—')}</div>
                        <div style="font-size:13px; color:var(--text-sec); font-weight:500;">${esc(u.position||'')} · ${fmtDate(u.created_at)}</div>
                    </div>
                </div>`).join('') || '<div class="loading">Нет новых сотрудников</div>';
        }
    } catch (e) { console.error('Dashboard error:', e); }
}

// ═══════════════════════════════════════════
// USERS
// ═══════════════════════════════════════════
async function loadUsers() {
    const canCreate = hasPerm('users_create');

    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header" style="display:flex; justify-content:space-between; align-items:flex-end; border-bottom:none; margin-bottom:20px; padding-bottom:0; flex-wrap:wrap; gap:16px;">
                <div class="subtabs" style="margin-bottom:0; border:none; padding:0; background:transparent;">
                    <button class="subtab active" data-tab="active">Активные</button>
                    <button class="subtab" data-tab="fired">Уволенные</button>
                </div>
                <div style="display:flex;gap:12px;">
                    <input class="form-input" id="users-search" placeholder="Поиск по ФИО, логину..." style="width:280px; border-radius:30px; padding:12px 20px;">
                    ${canCreate ? '<button class="btn btn--primary" onclick="openAddUser()">Добавить</button>' : ''}
                </div>
            </div>
            <div class="table-wrap">
                <table class="t">
                    <thead>
                        <tr>
                            <th>Логин</th>
                            <th>Сотрудник</th>
                            <th>Должность</th>
                            <th>Ресторан</th>
                            <th>Статус</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody id="users-table"><tr><td colspan="6" style="text-align:center;color:var(--text-sec);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
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
            const data = await cachedApi('/api/admin/users', { search: currentSearch, fired: currentTab === 'fired' }, 5000);
            const users = data.users || [];
            const tbody = $('users-table');

            tbody.innerHTML = users.map((u, i) => {
                if (currentTab === 'fired') {
                    return `<tr>
                        <td>${u.login ? esc(u.login) : '<span class="tag">нет</span>'}</td>
                        <td><div class="name-cell"><div class="avatar" style="background:${getAvatarGradient(i)}">${(u.full_name||'?').charAt(0).toUpperCase()}</div>${esc(u.full_name||'—')}</div></td>
                        <td>${esc(u.position||'—')}</td>
                        <td>${esc(u.restaurant_name||'—')}</td>
                        <td><span class="tag tag--amber">Уволен</span></td>
                        <td>
                            <div style="display:flex; gap:8px; white-space:nowrap;">
                                ${hasPerm('users_fire') ? `<button class="btn btn--sm btn--outline-success" onclick="restoreUser(${u.user_id})">Восстановить</button>` : ''}
                            </div>
                        </td>
                    </tr>`;
                }

                return `<tr>
                    <td>${u.login ? esc(u.login) : '<span class="tag">нет</span>'}</td>
                    <td>
                        <div class="name-cell">
                            <div class="avatar" style="background:${getAvatarGradient(i)}">${(u.full_name||'?').charAt(0).toUpperCase()}</div>
                            <div>
                                <div style="font-weight:800; color:var(--text-main);">${esc(u.full_name||'—')}</div>
                                <div style="font-size:12px; color:var(--text-sec); margin-top:2px;">
                                    ${u.personnel_number ? 'Таб: '+esc(u.personnel_number) : ''} 
                                    ${u.payment_type === 'fixed' ? ' • Оклад' : ' • Почасовка'}
                                </div>
                            </div>
                        </div>
                    </td>
                    <td>${esc(u.position||'—')}</td>
                    <td>${esc(u.restaurant_name||'—')}</td>
                    <td><span class="tag ${u.is_fired ? 'tag--amber' : 'tag--green'}">${u.is_fired ? 'Уволен' : 'Активен'}</span></td>
                    <td>
                        <div style="display:flex; gap:8px; white-space:nowrap;">
                            ${!u.is_fired && hasPerm('users_edit') ? `<button class="btn btn--sm btn--outline" onclick="openEditUser(${u.user_id})">Изменить</button>` : ''}
                            ${!u.is_fired && !u.is_super_admin && hasPerm('users_fire') ? `<button class="btn btn--sm btn--outline-danger" onclick="fireUser(${u.user_id},'${esc(u.full_name||'')}')" ${u.is_admin && !isSuperAdmin() ? 'disabled' : ''}>Уволить</button>` : ''}
                        </div>
                    </td>
                </tr>`;
            }).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--text-sec);padding:40px;">Нет сотрудников</td></tr>';
        } catch (e) {
            $('users-table').innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-sec);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
        }
    }
}

async function openAddUser() {
    let restaurants = [], positions = [], citizens = [];
    try {
        const r = await api('/api/admin/restaurants', {}); restaurants = r.restaurants || [];
        const p = await api('/api/admin/positions', {}); positions = (p.positions || []).filter(x => !x.is_archived);
        const c = await api('/api/admin/citizenships', {}); citizens = c.citizenships || [];
    } catch (e) {}

    openModal('Добавить сотрудника', `
        <div class="form-group"><label>ФИО</label><input class="form-input" id="user-full-name" placeholder="Иванов Иван Иванович"></div>
        <div class="form-group"><label>Пароль</label><input class="form-input" id="user-password" type="password"></div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Телефон</label><input class="form-input" id="user-phone"></div>
            <div class="form-group"><label>Дата рождения</label><input class="form-input" id="user-birth" placeholder="ДД.ММ.ГГГГ"></div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Должность</label><select class="form-select" id="user-position">${positions.map(p=>`<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('')}</select></div>
            <div class="form-group"><label>Ресторан</label><select class="form-select" id="user-restaurant"><option value="">—</option>${restaurants.map(r=>`<option value="${esc(r.key)}">${esc(r.name)}</option>`).join('')}</select></div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Гражданство</label><select class="form-select" id="user-citizen">${citizens.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></div>
            <div class="form-group"><label>Дата трудоустройства</label><input class="form-input" id="user-hire" type="date"></div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Табельный номер</label><input class="form-input" id="user-persnum" placeholder="Например: 1024"></div>
            <div class="form-group"><label>Тип оплаты</label><select class="form-select" id="user-payment"><option value="hourly">Почасовая</option><option value="fixed">Фиксированный оклад</option></select></div>
        </div>
        <div class="form-hint" id="user-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="user-save">Создать</button>`);

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
            clearCache();
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
        <div class="form-group"><label>Новый пароль (оставьте пустым, если не нужно менять)</label><input class="form-input" id="ed-password" type="password"></div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Телефон</label><input class="form-input" id="ed-phone" value="${esc(user.phone||'')}"></div>
            <div class="form-group"><label>Дата рождения</label><input class="form-input" id="ed-birth" value="${esc(user.birth_date||'')}"></div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Должность</label><select class="form-select" id="ed-position">${positions.filter(p=>!p.is_archived).map(p=>`<option value="${esc(p.name)}" ${p.name===user.position?'selected':''}>${esc(p.name)}</option>`).join('')}</select></div>
            <div class="form-group"><label>Ресторан</label><select class="form-select" id="ed-restaurant">${restaurants.map(r=>`<option value="${esc(r.key)}" ${r.key===user.restaurant_key?'selected':''}>${esc(r.name)}</option>`).join('')}</select></div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Гражданство</label><select class="form-select" id="ed-citizen">${citizens.map(c=>`<option value="${c.id}" ${c.id===user.citizenship_id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></div>
            <div class="form-group"><label>Дата трудоустройства</label><input class="form-input" id="ed-hire" type="date" value="${esc(user.hire_date||'')}"></div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Табельный номер</label><input class="form-input" id="ed-persnum" value="${esc(user.personnel_number||'')}"></div>
            <div class="form-group"><label>Тип оплаты</label><select class="form-select" id="ed-payment"><option value="hourly" ${user.payment_type==='hourly'?'selected':''}>Почасовая</option><option value="fixed" ${user.payment_type==='fixed'?'selected':''}>Фиксированный оклад</option></select></div>
        </div>
        ${isSuperAdmin() && !user.is_super_admin ? `<div class="form-group"><label style="display:flex;align-items:center;gap:8px;"><input type="checkbox" id="ed-isadmin" ${user.is_admin?'checked':''}> Права администратора</label></div>` : ''}
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
            clearCache();
            toast('Сохранено', 'success'); closeModal(); loadUsers();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function fireUser(uid, name) {
    if (!confirm(`Уволить ${name}?`)) return;
    try { await api('/api/admin/user/fire', { user_id: uid }); clearCache(); toast('Сотрудник уволен', 'success'); loadUsers(); }
    catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

async function restoreUser(uid) {
    if (!confirm('Восстановить сотрудника?')) return;
    try { await api('/api/admin/user/restore', { user_id: uid }); clearCache(); toast('Сотрудник восстановлен', 'success'); loadUsers(); }
    catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══════════════════════════════════════════
// MEDBOOKS
// ═══════════════════════════════════════════
let _medTab = 'staff';
async function loadMedbooks() {
    const data = await cachedApi('/api/admin/medbooks', {});
    _medTab = _medTab || 'staff';
    const canEdit = hasPerm('medbook_edit');

    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header" style="display:flex; justify-content:space-between; align-items:flex-end; border-bottom:none; margin-bottom:20px; padding-bottom:0;">
                <div class="subtabs" style="margin-bottom:0; border:none; padding:0; background:transparent;">
                    <button class="subtab ${_medTab==='staff'?'active':''}" data-mt="staff">Сотрудники</button>
                    <button class="subtab ${_medTab==='doctors'?'active':''}" data-mt="doctors">Врачи</button>
                    <button class="subtab ${_medTab==='tests'?'active':''}" data-mt="tests">Анализы</button>
                    <button class="subtab ${_medTab==='vaccines'?'active':''}" data-mt="vaccines">Прививки</button>
                </div>
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
                    <div class="neu-card neu-card--stat green"><div class="neu-card__label">Действительны</div><div class="neu-card__value" style="color:var(--green);">${ok}</div></div>
                    <div class="neu-card neu-card--stat yellow"><div class="neu-card__label">Скоро истекают</div><div class="neu-card__value" style="color:var(--yellow);">${exp}</div></div>
                    <div class="neu-card neu-card--stat pink"><div class="neu-card__label">Недействительны</div><div class="neu-card__value" style="color:var(--red);">${inv}</div></div>
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
                            <td>${canEdit ? `<button class="btn btn--sm btn--outline" onclick="openEditMedbook(${u.user_id})">Изменить</button>` : ''}</td>
                        </tr>`;
                    }).join('') || '<tr><td colspan="5" style="text-align:center;padding:40px;">Нет сотрудников</td></tr>'}</tbody></table></div>`;
        } else {
            const typeMap = { doctors: 'doctor', tests: 'test', vaccines: 'vaccine' };
            const typeLabel = { doctors: 'Врач', tests: 'Анализ', vaccines: 'Вакцина' };
            const list = d[_medTab] || [];
            const canManage = hasPerm('medbook_doctors_manage') || hasPerm('medbook_tests_manage') || hasPerm('medbook_vaccines_manage');
            const type = typeMap[_medTab];
            $('med-content').innerHTML = `
                <div style="margin-bottom:16px;">
                    ${canManage ? `<button class="btn btn--primary" onclick="openAddMedDir('${type}')">Добавить ${typeLabel[_medTab].toLowerCase()}</button>` : ''}
                </div>
                <div class="table-wrap">
                    <table class="t"><thead><tr><th>Название</th><th>Срок (мес)</th><th>Обяз.</th><th>Действия</th></tr></thead>
                    <tbody>${list.map(item => `<tr>
                        <td style="font-weight:600;">${esc(item.name)}</td><td>${item.validity_months||'—'}</td>
                        <td>${item.required ? '<span class="tag tag--green">Да</span>' : '<span class="tag tag--amber">Нет</span>'}</td>
                        <td>
                            <div style="display:flex; gap:8px; white-space:nowrap;">
                                ${canManage ? `<button class="btn btn--sm btn--outline" onclick="editMedDirItem(${item.id},'${type}','${esc(item.name)}',${item.validity_months||0},${item.required})">Изменить</button>
                                <button class="btn btn--sm btn--outline-danger" onclick="deleteMedDirItem('${type}',${item.id})">Удалить</button>` : ''}
                            </div>
                        </td>
                    </tr>`).join('') || '<tr><td colspan="4" style="text-align:center;padding:40px;">Пусто</td></tr>'}</tbody></table></div>`;
        }
    }
}

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
        <div style="margin-bottom:20px; font-size:15px;"><strong>${esc(user.full_name||'—')}</strong> — ${esc(user.position||'')}</div>
        <div class="form-hint" style="margin-bottom:12px; color:var(--primary);">Формат даты: ДД.ММ.ГГГГ</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;">
            <div><h4 style="margin-bottom:12px;color:var(--primary); font-size:14px;">Врачи</h4>${renderSection(doctors, 'doctors')}</div>
            <div><h4 style="margin-bottom:12px;color:var(--blue); font-size:14px;">Анализы</h4>${renderSection(tests, 'tests')}</div>
            <div><h4 style="margin-bottom:12px;color:var(--green); font-size:14px;">Прививки</h4>${renderSection(vaccines, 'vaccines')}</div>
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
            clearCache();
            toast('Медкнижка сохранена', 'success'); closeModal(); loadMedbooks();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function openAddMedDir(type) {
    const labels = { doctor:'Врача', test:'Анализ', vaccine:'Вакцину' };
    openModal(`Добавить ${labels[type]}`, `
        <div class="form-group"><label>Название</label><input class="form-input" id="med-dir-name" maxlength="100"></div>
        <div class="form-group"><label>Срок действия (месяцев)</label><input class="form-input" id="med-dir-months" type="number" value="12" min="1" max="120"></div>
        <label style="display:flex;align-items:center;gap:8px;margin-bottom:16px;cursor:pointer;"><input type="checkbox" id="med-dir-required" checked> <span>Обязательный</span></label>
        <div class="form-hint" id="med-dir-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="med-dir-save">Сохранить</button>`);
    $('med-dir-save').addEventListener('click', async () => {
        const errEl = $('med-dir-error'); errEl.textContent = '';
        const name = $('med-dir-name').value.trim();
        if (!name) { errEl.textContent = 'Введите название'; return; }
        try {
            await api('/api/admin/medbook/reference/add', { type, name, validity_months: parseInt($('med-dir-months').value)||12, required: $('med-dir-required').checked });
            clearCache();
            toast('Добавлено', 'success'); closeModal(); loadMedbooks();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function editMedDirItem(id, type, name, months, required) {
    const labels = { doctor:'Врача', test:'Анализ', vaccine:'Вакцину' };
    openModal(`Редактировать ${labels[type]}`, `
        <div class="form-group"><label>Название</label><input class="form-input" id="ed-med-dir-name" value="${esc(name)}" maxlength="100"></div>
        <div class="form-group"><label>Срок (месяцев)</label><input class="form-input" id="ed-med-dir-months" type="number" value="${months}" min="1" max="120"></div>
        <label style="display:flex;align-items:center;gap:8px;margin-bottom:16px;cursor:pointer;"><input type="checkbox" id="ed-med-dir-required" ${required?'checked':''}> <span>Обязательный</span></label>
        <div class="form-hint" id="ed-med-dir-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="ed-med-dir-save">Сохранить</button>`);
    $('ed-med-dir-save').addEventListener('click', async () => {
        const errEl = $('ed-med-dir-error'); errEl.textContent = '';
        const nameVal = $('ed-med-dir-name').value.trim();
        if (!nameVal) { errEl.textContent = 'Введите название'; return; }
        try {
            await api('/api/admin/medbook/reference/update', { type, id, name: nameVal, validity_months: parseInt($('ed-med-dir-months').value)||12, required: $('ed-med-dir-required').checked });
            clearCache();
            toast('Сохранено', 'success'); closeModal(); loadMedbooks();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function deleteMedDirItem(type, id) {
    if (!confirm('Удалить?')) return;
    try { await api('/api/admin/medbook/reference/delete', { type, id }); clearCache(); toast('Удалено', 'success'); loadMedbooks(); }
    catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══════════════════════════════════════════
// NEWS & STANDARDS HELPERS
// ═══════════════════════════════════════════
let _uploadedNewsImageUrl = '';
let _uploadedStandardImageUrl = '';
let _uploadedStandardFileUrl = '';
let _uploadedStandardFileName = '';
let _tableHeaders = [];
let _tableRows = [];
const STANDARD_GROUPS = ['Пищевая Безопасность', 'Касса', 'Горячий цех', 'Холодный цех', 'Общее'];

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

function parsePastedTableData(rawText, htmlData) {
    if (htmlData && htmlData.includes('<table')) {
        try {
            const doc = new DOMParser().parseFromString(htmlData, 'text/html');
            const trs = Array.from(doc.querySelectorAll('tr'));
            const parsed = trs.map(tr => Array.from(tr.querySelectorAll('th, td')).map(c => (c.textContent || '').trim()));
            if (parsed.length > 0 && parsed[0].length > 0) {
                const maxCols = Math.max(...parsed.map(r => r.length));
                const headers = parsed[0].map((h, i) => h || `Колонка ${i + 1}`);
                while (headers.length < maxCols) headers.push(`Колонка ${headers.length + 1}`);
                const rows = parsed.slice(1).map(r => {
                    const row = [];
                    for (let i = 0; i < maxCols; i++) row.push(r[i] || '');
                    return row;
                });
                return { headers, rows: rows.length ? rows : [Array(maxCols).fill('')] };
            }
        } catch (e) {}
    }

    const lines = String(rawText || '').split(/\r?\n/).map(l => l.trimEnd()).filter(l => l.trim().length > 0);
    if (!lines.length) return null;
    const delim = lines[0].includes('\t') ? '\t' : (lines[0].includes(';') ? ';' : null);
    if (!delim) return null;

    const matrix = lines.map(l => l.split(delim).map(cell => cell.trim()));
    const maxCols = Math.max(...matrix.map(r => r.length));
    if (maxCols < 2) return null;

    const headers = matrix[0].map((h, i) => h || `Колонка ${i + 1}`);
    while (headers.length < maxCols) headers.push(`Колонка ${headers.length + 1}`);
    const rows = matrix.slice(1).map(r => {
        const row = [];
        for (let i = 0; i < maxCols; i++) row.push(r[i] || '');
        return row;
    });
    return { headers, rows: rows.length ? rows : [Array(maxCols).fill('')] };
}

function bindTablePasteHandler() {
    const pasteArea = $('paste-table-area');
    if (!pasteArea) return;
    const applyParsed = (rawText, htmlData) => {
        const result = parsePastedTableData(rawText, htmlData);
        if (!result) return false;
        _tableHeaders = result.headers;
        _tableRows = result.rows;
        const container = $('table-editor-container');
        if (container) container.innerHTML = renderTableEditor(_tableHeaders, _tableRows);
        toast('Таблица распознана и загружена в редактор', 'success');
        return true;
    };

    pasteArea.addEventListener('paste', e => {
        const text = e.clipboardData?.getData('text/plain') || '';
        const html = e.clipboardData?.getData('text/html') || '';
        if (applyParsed(text, html)) {
            setTimeout(() => { pasteArea.value = ''; }, 0);
        }
    });

    pasteArea.addEventListener('input', () => {
        if (!pasteArea.value.trim()) return;
        const result = parsePastedTableData(pasteArea.value, '');
        if (result) {
            _tableHeaders = result.headers;
            _tableRows = result.rows;
            const container = $('table-editor-container');
            if (container) container.innerHTML = renderTableEditor(_tableHeaders, _tableRows);
        }
    });
}

// ═══════════════════════════════════════════
// NEWS
// ═══════════════════════════════════════════
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
                ${canCreate ? '<button class="btn btn--primary" onclick="openAddNews()">Создать</button>' : ''}
            </div>
            ${canPublish() && pending.length ? `
                <div style="background:var(--yellow-bg); border:1px solid #fde68a; border-radius:8px; padding:16px; margin-bottom:24px;">
                    <strong style="color:var(--yellow); font-size:14px;">На модерации: ${pending.length}</strong>
                    <div style="display:flex;flex-direction:column;gap:8px;margin-top:12px;">
                        ${pending.map(n => `
                            <div style="display:flex;gap:12px;align-items:center;padding:12px;background:#fff;border:1px solid #fde68a;border-radius:6px;box-shadow:var(--shadow-sm);">
                                <div style="flex:1;"><strong style="font-size:14px;">${esc(n.title)}</strong><br><span style="font-size:12px;color:var(--text-sec);">${esc(n.proposed_by||'')} · ${fmtDate(n.created_at)}</span></div>
                                <button class="btn btn--sm btn--outline-success" onclick="approveNews(${n.id})">Принять</button>
                                <button class="btn btn--sm btn--outline-danger" onclick="rejectNews(${n.id})">Отклонить</button>
                            </div>`).join('')}
                    </div>
                </div>` : ''}
            <div class="table-wrap">
                <table class="t"><thead><tr><th>Фото</th><th>Заголовок</th><th>Автор</th><th>Дата</th><th>Статус</th><th>Действия</th></tr></thead>
                <tbody id="news-table">${others.map(n => {
                    const st = n.status==='published'?'tag--green':n.status==='scheduled'?'tag--blue':'tag--amber';
                    const tx = n.status==='published'?'Опубликована':n.status==='scheduled'?'Запланирована':'На модерации';
                    let acts = '';
                    if (n.status==='pending' && canPublish()) acts += `<button class="btn btn--sm btn--outline-success" onclick="approveNews(${n.id})">Принять</button>`;
                    if (n.status==='pending' && canPublish()) acts += `<button class="btn btn--sm btn--outline-danger" style="margin-left:8px;" onclick="rejectNews(${n.id})">Отклонить</button>`;
                    if (canEdit) acts += `<button class="btn btn--sm btn--outline" style="margin-left:8px;" onclick="openNewsEdit(${n.id})">Изменить</button>`;
                    if (canEdit && n.status !== 'pending') acts += `<button class="btn btn--sm btn--outline-danger" style="margin-left:8px;" onclick="deleteNews(${n.id})">Удалить</button>`;
                    return `<tr><td style="text-align:center;">${n.image_url ? `<img src="${getFileUrl(n.image_url)}" style="width:48px;height:48px;object-fit:cover;border-radius:6px;box-shadow:var(--shadow-sm);">` : '<span style="color:var(--text-sec);">—</span>'}</td>
                        <td style="font-weight:600;">${esc(n.title||'—')}</td><td>${esc(n.proposed_by||'—')}</td><td style="color:var(--text-sec);">${fmtDate(n.created_at)}</td><td><span class="tag ${st}">${tx}</span></td><td>${acts}</td></tr>`;
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
            <button type="button" class="btn btn--ghost" id="n-image-btn" style="width:100%;padding:24px;border:2px dashed var(--border);border-radius:8px;">Прикрепить фото</button>
            <div id="n-image-preview-box" style="display:none;margin-top:16px;text-align:center;">
                <img id="n-image-preview" style="max-width:100%;max-height:150px;border-radius:8px;object-fit:contain;box-shadow:var(--shadow-sm);">
            </div>
        </div>
        <div class="form-group"><label>Заголовок</label><input class="form-input" id="n-title" maxlength="100"></div>
        <div class="form-group"><label>Текст</label><textarea class="form-textarea" id="n-body" rows="6"></textarea></div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Уровень</label><select class="form-select" id="n-level"><option value="normal">Обычная</option><option value="announcement">Объявление</option><option value="event">Событие</option></select></div>
            <div class="form-group"><label>Действие</label><select class="form-select" id="n-intent">${canPublishFlag ? '<option value="publish">Опубликовать</option><option value="schedule">Отложить</option>' : ''}<option value="suggest">Предложить</option></select></div>
        </div>
        <div class="form-group" id="n-sched-time" style="display:none;"><label>Дата и время</label><input class="form-input" type="datetime-local" id="n-publish-at"></div>
        <div class="form-hint" id="news-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="create-news-btn">${canPublishFlag ? 'Создать' : 'Предложить'}</button>`);

    $('n-image-btn').addEventListener('click', () => $('n-image-file').click());
    $('n-image-file').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 15 * 1024 * 1024) { toast('Файл слишком большой (макс 15MB)', 'error'); return; }
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
            btn.style.color = 'var(--green)';
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
            await api('/api/admin/news/add', bodyReq);
            clearCache();
            toast('Новость создана', 'success'); closeModal(); loadNews();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function openNewsEdit(id) {
    if (!hasPerm('news_edit')) { toast('Нет права', 'error'); return; }
    let newsData;
    try { newsData = await cachedApi('/api/admin/news', {}); } catch (e) { return; }
    const n = (newsData.news || []).find(x => x.id === id);
    if (!n) return;

    _uploadedNewsImageUrl = n.image_url || '';
    openModal('Редактировать новость', `
        <div class="form-group">
            <label>Фотография</label>
            <input type="file" id="n-image-file-edit" accept="image/*" style="display:none;">
            <button type="button" class="btn btn--ghost" id="n-image-btn-edit" style="width:100%;padding:24px;border:2px dashed var(--border);border-radius:8px;">${n.image_url ? 'Заменить фото' : 'Прикрепить фото'}</button>
            <div id="n-image-preview-box-edit" style="display:${n.image_url ? 'block' : 'none'};margin-top:16px;text-align:center;">
                <img id="n-image-preview-edit" src="${getFileUrl(n.image_url)}" style="max-width:100%;max-height:150px;border-radius:8px;object-fit:contain;box-shadow:var(--shadow-sm);">
            </div>
        </div>
        <div class="form-group"><label>Заголовок</label><input class="form-input" id="edit-n-title" value="${esc(n.title)}"></div>
        <div class="form-group"><label>Текст</label><textarea class="form-textarea" id="edit-n-body" rows="6">${esc(n.body)}</textarea></div>
        <div class="form-group"><label>Уровень</label><select class="form-select" id="edit-n-level"><option value="normal" ${n.level==='normal'?'selected':''}>Обычная</option><option value="announcement" ${n.level==='announcement'?'selected':''}>Объявление</option><option value="event" ${n.level==='event'?'selected':''}>Событие</option></select></div>
        <div class="form-hint" id="edit-news-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="save-news-btn">Сохранить</button>`);

    $('n-image-btn-edit').addEventListener('click', () => $('n-image-file-edit').click());
    $('n-image-file-edit').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 15 * 1024 * 1024) { toast('Файл слишком большой (макс 15MB)', 'error'); return; }
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
            clearCache();
            toast('Сохранено', 'success'); closeModal(); loadNews();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function approveNews(id) { try { await api('/api/admin/news/approve', { id }); clearCache(); toast('Одобрено', 'success'); loadNews(); } catch (e) { toast('Ошибка: ' + e.message, 'error'); } }
async function rejectNews(id) { try { await api('/api/admin/news/reject', { id }); clearCache(); toast('Отклонено', 'success'); loadNews(); } catch (e) { toast('Ошибка: ' + e.message, 'error'); } }
async function deleteNews(id) { if (!confirm('Удалить?')) return; try { await api('/api/admin/news/delete', { id }); clearCache(); toast('Удалено', 'success'); loadNews(); } catch (e) { toast('Ошибка: ' + e.message, 'error'); } }

// ═══════════════════════════════════════════
// STANDARDS
// ═══════════════════════════════════════════
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
                ${canCreate ? '<button class="btn btn--primary" onclick="openAddStandard()">Создать</button>' : ''}
            </div>
            ${canPublish() && pending.length ? `
                <div style="background:var(--yellow-bg); border:1px solid #fde68a; border-radius:8px; padding:16px; margin-bottom:24px;">
                    <strong style="color:var(--yellow); font-size:14px;">На согласовании: ${pending.length}</strong>
                    <div style="display:flex;flex-direction:column;gap:8px;margin-top:12px;">
                        ${pending.map(s => `
                            <div style="display:flex;gap:12px;align-items:center;padding:12px;background:#fff;border:1px solid #fde68a;border-radius:6px;box-shadow:var(--shadow-sm);">
                                <div style="flex:1;"><strong style="font-size:14px;">${esc(s.title)}</strong> <span class="tag tag--purple">${esc(s.group_name||'')}</span><br><span style="font-size:12px;color:var(--text-sec);">${esc(s.proposed_by||'')} · ${fmtDate(s.created_at)}</span></div>
                                <button class="btn btn--sm btn--outline-success" onclick="approveStandard(${s.id})">Принять</button>
                                <button class="btn btn--sm btn--outline-danger" onclick="rejectStandard(${s.id})">Отклонить</button>
                            </div>`).join('')}
                    </div>
                </div>` : ''}
            <div class="table-wrap">
                <table class="t"><thead><tr><th>Фото</th><th>Номер</th><th>Группа</th><th>Заголовок</th><th>Файл</th><th>Статус</th><th>Действия</th></tr></thead>
                <tbody id="standards-table">${others.map(s => {
                    const st = s.status==='published'?'tag--green':'tag--amber';
                    const tx = s.status==='published'?'Опубликован':'На модерации';
                    let acts = '';
                    if (s.status==='pending' && canPublish()) acts += `<button class="btn btn--sm btn--outline-success" onclick="approveStandard(${s.id})">Принять</button>`;
                    if (s.status==='pending' && canPublish()) acts += `<button class="btn btn--sm btn--outline-danger" style="margin-left:8px;" onclick="rejectStandard(${s.id})">Отклонить</button>`;
                    if (canEdit) acts += `<button class="btn btn--sm btn--outline" style="margin-left:8px;" onclick="openStdEdit(${s.id})">Изменить</button>`;
                    if (canEdit && s.status !== 'pending') acts += `<button class="btn btn--sm btn--outline-danger" style="margin-left:8px;" onclick="deleteStandard(${s.id})">Удалить</button>`;
                    return `<tr><td style="text-align:center;">${s.image_url ? `<img src="${getFileUrl(s.image_url)}" style="width:48px;height:48px;object-fit:cover;border-radius:6px;box-shadow:var(--shadow-sm);">` : '<span style="color:var(--text-sec);">—</span>'}</td>
                        <td><span class="tag">${esc(s.number||'—')}</span></td><td><span class="tag tag--purple">${esc(s.group_name||'Общее')}</span></td>
                        <td style="font-weight:600;">${esc(s.title||'—')}</td><td>${s.file_url ? 'Да' : '—'}</td>
                        <td><span class="tag ${st}">${tx}</span></td><td>${acts}</td></tr>`;
                }).join('') || '<tr><td colspan="7" style="text-align:center;padding:40px;">Нет стандартов</td></tr>'}</tbody></table>
            </div>
        </div>`;
}

function renderTableEditor(headers, rows) {
    const headerHtml = headers.map((h, i) =>
        `<th style="padding:4px;"><input class="form-input" style="padding:8px;border-radius:6px;font-size:13px;text-align:center;" value="${esc(h)}" onchange="updateTableHeaders()" data-col="${i}"></th>`
    ).join('');
    const rowsHtml = rows.map((row, rIdx) =>
        `<tr>${headers.map((_, cIdx) =>
            `<td style="padding:4px;"><input class="form-input" style="padding:8px;border-radius:6px;font-size:13px;" value="${esc(row[cIdx]||'')}" onchange="updateTableCell(${rIdx},${cIdx})"></td>`
        ).join('')}<td style="padding:4px;"><button type="button" class="btn btn--sm btn--outline-danger" onclick="removeTableRow(${rIdx})">Удал.</button></td></tr>`
    ).join('');
    return `<div style="overflow-x:auto;padding-bottom:8px;">
        <table style="width:100%;border-collapse:collapse;min-width:600px;">
            <thead><tr>${headerHtml}<th></th></tr></thead>
            <tbody id="table-editor-rows">${rowsHtml}</tbody>
        </table>
    </div>
    <div style="display:flex;gap:8px;margin-top:16px;">
        <button type="button" class="btn btn--outline" style="font-size:12px;" onclick="addTableRow()">Добавить строку</button>
    </div>`;
}

window.updateTableHeaders = function () {
    const inputs = Array.from(document.querySelectorAll('#table-editor-container thead input'));
    _tableHeaders = inputs.map(i => i.value);
    _tableRows = _tableRows.map(r => {
        const newR = [];
        for (let i = 0; i < _tableHeaders.length; i++) newR.push(r[i] || '');
        return newR;
    });
    const container = document.getElementById('table-editor-container');
    if (container) container.innerHTML = renderTableEditor(_tableHeaders, _tableRows);
};
window.updateTableCell = function (rIdx, cIdx) {
    const inputs = document.querySelectorAll(`#table-editor-rows tr:nth-child(${rIdx+1}) input`);
    if (inputs[cIdx]) _tableRows[rIdx][cIdx] = inputs[cIdx].value;
};
window.addTableRow = function () {
    _tableRows.push(Array(_tableHeaders.length).fill(''));
    const container = document.getElementById('table-editor-container');
    if (container) container.innerHTML = renderTableEditor(_tableHeaders, _tableRows);
};
window.removeTableRow = function (rIdx) {
    _tableRows.splice(rIdx, 1);
    const container = document.getElementById('table-editor-container');
    if (container) container.innerHTML = renderTableEditor(_tableHeaders, _tableRows);
};

function switchContentTypeUI(type) {
    const textArea = $('std-text-area');
    const tableArea = $('std-table-area');
    if (textArea) textArea.style.display = type === 'table' ? 'none' : 'block';
    if (tableArea) tableArea.style.display = type === 'table' ? 'block' : 'none';
    if (type === 'table' && !_tableHeaders.length) {
        _tableHeaders = ['Колонка 1', 'Колонка 2', 'Колонка 3'];
        _tableRows = [['', '', '']];
        const container = $('table-editor-container');
        if (container) container.innerHTML = renderTableEditor(_tableHeaders, _tableRows);
    }
}

function renderFilePreviewUI() {
    const box = $('std-file-preview-box');
    const btn = $('std-file-btn');
    if (!box) return;
    if (_uploadedStandardFileUrl) {
        box.style.display = 'flex';
        if ($('std-file-name')) $('std-file-name').textContent = _uploadedStandardFileName || 'Файл';
        if ($('std-file-status')) $('std-file-status').textContent = 'Готов к сохранению';
        if (btn) btn.style.display = 'none';
    } else {
        box.style.display = 'none';
        if (btn) btn.style.display = 'block';
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
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group">
                <label>Обложка (фото)</label>
                <input type="file" id="std-image-file" accept="image/*" style="display:none;">
                <button type="button" class="btn btn--ghost" id="std-image-btn" style="width:100%;padding:16px;border:2px dashed var(--border);border-radius:8px;">Прикрепить фото</button>
                <div id="std-image-preview-box" style="display:none;margin-top:12px;text-align:center;">
                    <img id="std-image-preview" style="max-width:100%;max-height:100px;border-radius:8px;object-fit:contain;box-shadow:var(--shadow-sm);">
                </div>
            </div>
            <div class="form-group">
                <label>Документ (PDF, Word, Excel)</label>
                <input type="file" id="std-file-file" accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv" style="display:none;">
                <button type="button" class="btn btn--ghost" id="std-file-btn" style="width:100%;padding:16px;border:2px dashed var(--border);border-radius:8px;">Прикрепить файл</button>
                <div id="std-file-preview-box" style="display:none;margin-top:12px;padding:12px;background:var(--bg-hover);border:1px solid var(--border);border-radius:8px;align-items:center;gap:12px;box-shadow:var(--shadow-sm);">
                    <div style="flex:1;min-width:0;">
                        <div id="std-file-name" style="font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"></div>
                        <div id="std-file-status" style="font-size:12px;color:var(--text-sec);"></div>
                    </div>
                    <button type="button" class="btn btn--sm btn--outline-danger" onclick="_uploadedStandardFileUrl='';_uploadedStandardFileName='';renderFilePreviewUI();">Удал.</button>
                </div>
            </div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Номер стандарта</label><input class="form-input" id="std-number" placeholder="СТ-001"></div>
            <div class="form-group"><label>Группа</label><select class="form-select" id="std-group">${groupOpts}</select></div>
        </div>
        <div class="form-group"><label>Заголовок</label><input class="form-input" id="std-title" maxlength="150"></div>
        <div class="form-group"><label>Тип контента</label><select class="form-select" id="std-content-type" onchange="switchContentTypeUI(this.value)"><option value="text">Текст</option><option value="table">Таблица</option></select></div>
        <div id="std-text-area">
            <div class="form-group"><label>Текст стандарта</label><div contenteditable="true" id="std-body" class="rich-editor"></div></div>
        </div>
        <div id="std-table-area" style="display:none;margin-bottom:24px;">
            <div class="form-group" style="background:var(--green-bg);padding:16px;border-radius:8px;border:1px dashed #6ee7b7;">
                <label style="color:var(--green);">Вставить таблицу из Excel/Word (Ctrl+V)</label>
                <textarea class="form-textarea" id="paste-table-area" placeholder="Скопируйте таблицу из Excel и вставьте сюда..." style="min-height:80px;font-size:13px;background:#fff;margin-bottom:0;"></textarea>
                <div class="form-hint" style="color:var(--green);opacity:0.8;">После вставки таблица появится ниже. Вы сможете её отредактировать.</div>
            </div>
            <label style="display:block;font-size:12px;font-weight:700;color:var(--text-sec);margin-bottom:8px;text-transform:uppercase;">Ручная настройка</label>
            <div id="table-editor-container"></div>
        </div>
        <div class="form-hint" id="std-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="std-save">Создать</button>`);

    bindTablePasteHandler();

    $('std-image-btn').addEventListener('click', () => $('std-image-file').click());
    $('std-image-file').addEventListener('change', async (e) => {
        const f = e.target.files[0]; if (!f) return;
        const btn = $('std-image-btn'); btn.disabled = true; btn.textContent = 'Загрузка...';
        try {
            const res = await uploadFile(f);
            _uploadedStandardImageUrl = res.url;
            $('std-image-preview').src = getFileUrl(res.url);
            $('std-image-preview-box').style.display = 'block';
            btn.textContent = 'Фото загружено';
        } catch (err) { toast(err.message, 'error'); btn.textContent = 'Прикрепить фото'; }
        finally { btn.disabled = false; }
    });

    $('std-file-btn').addEventListener('click', () => $('std-file-file').click());
    $('std-file-file').addEventListener('change', async (e) => {
        const f = e.target.files[0]; if (!f) return;
        const btn = $('std-file-btn'); btn.disabled = true; btn.textContent = 'Загрузка...';
        try {
            const res = await uploadFile(f);
            _uploadedStandardFileUrl = res.url;
            _uploadedStandardFileName = res.name || f.name;
            renderFilePreviewUI();
        } catch (err) { toast(err.message, 'error'); btn.textContent = 'Прикрепить файл'; }
        finally { btn.disabled = false; }
    });

    $('std-save').addEventListener('click', async () => {
        const errEl = $('std-error'); errEl.textContent = '';
        try {
            const contentType = $('std-content-type').value;
            const cleanedBody = cleanHTML($('std-body').innerHTML);
            const plainText = ($('std-body').innerText || '').trim();
            const hasTableData = contentType === 'table' && _tableHeaders.length > 0;
            const payload = {
                number: $('std-number').value.trim(),
                title: $('std-title').value.trim(),
                body: cleanedBody || (hasTableData ? `<p>${esc($('std-title').value.trim())}</p>` : ''),
                image_url: _uploadedStandardImageUrl,
                group_name: $('std-group').value,
                content_type: contentType,
                content_data: contentType === 'table' ? { headers: _tableHeaders, rows: _tableRows } : null,
                file_url: _uploadedStandardFileUrl,
                file_name: _uploadedStandardFileName,
            };
            if (!payload.title || (!plainText && !hasTableData && !_uploadedStandardFileUrl)) {
                errEl.textContent = 'Заполните заголовок и содержание стандарта';
                return;
            }
            await api('/api/admin/standard/add', payload);
            clearCache();
            toast('Стандарт создан', 'success');
            closeModal();
            loadStandards();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function openStdEdit(sid) {
    if (!hasPerm('standards_edit')) { toast('Нет права', 'error'); return; }
    let std;
    try {
        const data = await cachedApi('/api/admin/standards', {});
        std = (data.standards || []).find(x => x.id === sid);
        if (!std) { toast('Стандарт не найден', 'error'); return; }
    } catch (e) { toast('Ошибка: ' + e.message, 'error'); return; }

    _uploadedStandardImageUrl = std.image_url || '';
    _uploadedStandardFileUrl = std.file_url || '';
    _uploadedStandardFileName = std.file_name || '';
    _tableHeaders = (std.content_data && std.content_data.headers) || [];
    _tableRows = (std.content_data && std.content_data.rows) || [];

    const groupOpts = STANDARD_GROUPS.map(g => `<option value="${g}" ${g === std.group_name ? 'selected' : ''}>${g}</option>`).join('');

    openModal('Редактировать стандарт', `
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group">
                <label>Обложка</label>
                <input type="file" id="std-image-file" accept="image/*" style="display:none;">
                <button type="button" class="btn btn--ghost" id="std-image-btn" style="width:100%;padding:16px;border:2px dashed var(--border);border-radius:8px;">${std.image_url ? 'Заменить фото' : 'Прикрепить фото'}</button>
                <div id="std-image-preview-box" style="display:${std.image_url ? 'block' : 'none'};margin-top:12px;text-align:center;">
                    <img id="std-image-preview" src="${getFileUrl(std.image_url)}" style="max-width:100%;max-height:100px;border-radius:8px;box-shadow:var(--shadow-sm);">
                </div>
            </div>
            <div class="form-group">
                <label>Документ</label>
                <input type="file" id="std-file-file" accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv" style="display:none;">
                <button type="button" class="btn btn--ghost" id="std-file-btn" style="width:100%;padding:16px;border:2px dashed var(--border);border-radius:8px;${std.file_url ? 'display:none;' : ''}">Прикрепить файл</button>
                <div id="std-file-preview-box" style="display:${std.file_url ? 'flex' : 'none'};margin-top:12px;padding:12px;background:var(--bg-hover);border:1px solid var(--border);border-radius:8px;align-items:center;gap:12px;box-shadow:var(--shadow-sm);">
                    <div style="flex:1;min-width:0;">
                        <div id="std-file-name" style="font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(std.file_name || 'Файл')}</div>
                        <div id="std-file-status" style="font-size:12px;color:var(--text-sec);">Готов к сохранению</div>
                    </div>
                    <button type="button" class="btn btn--sm btn--outline-danger" onclick="_uploadedStandardFileUrl='';_uploadedStandardFileName='';renderFilePreviewUI();">Удал.</button>
                </div>
            </div>
        </div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Номер</label><input class="form-input" id="std-number" value="${esc(std.number || '')}"></div>
            <div class="form-group"><label>Группа</label><select class="form-select" id="std-group">${groupOpts}</select></div>
        </div>
        <div class="form-group"><label>Заголовок</label><input class="form-input" id="std-title" value="${esc(std.title || '')}"></div>
        <div class="form-group"><label>Тип контента</label><select class="form-select" id="std-content-type" onchange="switchContentTypeUI(this.value)"><option value="text" ${std.content_type !== 'table' ? 'selected' : ''}>Текст</option><option value="table" ${std.content_type === 'table' ? 'selected' : ''}>Таблица</option></select></div>
        <div id="std-text-area" style="display:${std.content_type === 'table' ? 'none' : 'block'};">
            <div class="form-group"><label>Текст</label><div contenteditable="true" id="std-body" class="rich-editor">${cleanHTML(std.body || '')}</div></div>
        </div>
        <div id="std-table-area" style="display:${std.content_type === 'table' ? 'block' : 'none'};margin-bottom:24px;">
            <div class="form-group" style="background:var(--green-bg);padding:16px;border-radius:8px;border:1px dashed #6ee7b7;">
                <label style="color:var(--green);">Вставить таблицу из Excel (Ctrl+V)</label>
                <textarea class="form-textarea" id="paste-table-area" style="min-height:80px;font-size:13px;background:#fff;margin-bottom:0;"></textarea>
            </div>
            <div id="table-editor-container"></div>
        </div>
        <div class="form-hint" id="std-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="std-save">Сохранить</button>`);

    if (std.content_type === 'table' && _tableHeaders.length) {
        $('table-editor-container').innerHTML = renderTableEditor(_tableHeaders, _tableRows);
    }
    bindTablePasteHandler();

    $('std-image-btn').addEventListener('click', () => $('std-image-file').click());
    $('std-image-file').addEventListener('change', async (e) => {
        const f = e.target.files[0]; if (!f) return;
        const btn = $('std-image-btn'); btn.disabled = true; btn.textContent = 'Загрузка...';
        try {
            const res = await uploadFile(f);
            _uploadedStandardImageUrl = res.url;
            $('std-image-preview').src = getFileUrl(res.url);
            $('std-image-preview-box').style.display = 'block';
            btn.textContent = 'Фото загружено';
        } catch (err) { toast(err.message, 'error'); btn.textContent = 'Прикрепить фото'; }
        finally { btn.disabled = false; }
    });

    $('std-file-btn').addEventListener('click', () => $('std-file-file').click());
    $('std-file-file').addEventListener('change', async (e) => {
        const f = e.target.files[0]; if (!f) return;
        const btn = $('std-file-btn'); btn.disabled = true; btn.textContent = 'Загрузка...';
        try {
            const res = await uploadFile(f);
            _uploadedStandardFileUrl = res.url;
            _uploadedStandardFileName = res.name || f.name;
            renderFilePreviewUI();
        } catch (err) { toast(err.message, 'error'); btn.textContent = 'Прикрепить файл'; }
        finally { btn.disabled = false; }
    });

    $('std-save').addEventListener('click', async () => {
        const errEl = $('std-error'); errEl.textContent = '';
        try {
            const contentType = $('std-content-type').value;
            const cleanedBody = cleanHTML($('std-body').innerHTML);
            const plainText = ($('std-body').innerText || '').trim();
            const hasTableData = contentType === 'table' && _tableHeaders.length > 0;
            const payload = {
                id: sid,
                number: $('std-number').value.trim(),
                title: $('std-title').value.trim(),
                body: cleanedBody || (hasTableData ? `<p>${esc($('std-title').value.trim())}</p>` : ''),
                image_url: _uploadedStandardImageUrl,
                group_name: $('std-group').value,
                content_type: contentType,
                content_data: contentType === 'table' ? { headers: _tableHeaders, rows: _tableRows } : null,
                file_url: _uploadedStandardFileUrl,
                file_name: _uploadedStandardFileName,
            };
            if (!payload.title || (!plainText && !hasTableData && !_uploadedStandardFileUrl)) {
                errEl.textContent = 'Заполните заголовок и содержание стандарта';
                return;
            }
            await api('/api/admin/standard/update', payload);
            clearCache();
            toast('Сохранено', 'success');
            closeModal();
            loadStandards();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function approveStandard(id) { try { await api('/api/admin/standard/approve', { id }); clearCache(); toast('Одобрено', 'success'); loadStandards(); } catch (e) { toast('Ошибка: ' + e.message, 'error'); } }
async function rejectStandard(id) { try { await api('/api/admin/standard/reject', { id }); clearCache(); toast('Отклонено', 'success'); loadStandards(); } catch (e) { toast('Ошибка: ' + e.message, 'error'); } }
async function deleteStandard(id) { if (!confirm('Удалить стандарт?')) return; try { await api('/api/admin/standard/delete', { id }); clearCache(); toast('Удалено', 'success'); loadStandards(); } catch (e) { toast('Ошибка: ' + e.message, 'error'); } }

// ═══════════════════════════════════════════
// CERTIFICATION
// ═══════════════════════════════════════════
async function loadCertification() {
    const canEdit = hasPerm('certification_edit');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header">
                <div class="neu-card__header-title">Вопросы сертификации</div>
                ${canEdit ? '<button class="btn btn--primary" onclick="openAddCertQuestion()">Создать</button>' : ''}
            </div>
            <div id="cert-list"><div class="loading">Загрузка...</div></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/certification', {});
        const questions = data.questions || [];
        $('cert-list').innerHTML = questions.map(q => `
            <div class="neu-card" style="margin-bottom:16px; box-shadow: none; border: 1px solid var(--border);">
                <div style="display:flex;justify-content:space-between;gap:16px;">
                    <div style="flex:1;">
                        <div style="font-weight:700;margin-bottom:8px; font-size:15px;">${esc(q.question)}</div>
                        <div style="font-size:13px;color:var(--text-sec); line-height:1.6;">
                            A) ${esc(q.option_a)}<br>
                            B) ${esc(q.option_b)}<br>
                            C) ${esc(q.option_c)}<br>
                            D) ${esc(q.option_d)}
                        </div>
                        <div style="margin-top:12px;"><span class="tag tag--green">Правильный: ${esc((q.correct_option || '').toUpperCase())}</span></div>
                    </div>
                    ${canEdit ? `<button class="btn btn--sm btn--outline-danger" style="align-self:flex-start;" onclick="deleteCertQuestion(${q.id})">Удалить</button>` : ''}
                </div>
            </div>
        `).join('') || '<div class="empty">Нет вопросов</div>';
    } catch (e) { $('cert-list').innerHTML = `<div class="empty">Ошибка: ${esc(e.message)}</div>`; }
}

function openAddCertQuestion() {
    openModal('Новый вопрос', `
        <div class="form-group"><label>Вопрос</label><textarea class="form-textarea" id="cq-question"></textarea></div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>A</label><input class="form-input" id="cq-a"></div>
            <div class="form-group"><label>B</label><input class="form-input" id="cq-b"></div>
            <div class="form-group"><label>C</label><input class="form-input" id="cq-c"></div>
            <div class="form-group"><label>D</label><input class="form-input" id="cq-d"></div>
        </div>
        <div class="form-group"><label>Правильный ответ</label><select class="form-select" id="cq-correct"><option value="a">A</option><option value="b">B</option><option value="c">C</option><option value="d">D</option></select></div>
        <div class="form-hint" id="cq-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="cq-save">Сохранить</button>`);
    $('cq-save').addEventListener('click', async () => {
        const errEl = $('cq-error'); errEl.textContent = '';
        try {
            await api('/api/admin/certification/add', {
                question: $('cq-question').value.trim(),
                option_a: $('cq-a').value.trim(),
                option_b: $('cq-b').value.trim(),
                option_c: $('cq-c').value.trim(),
                option_d: $('cq-d').value.trim(),
                correct_option: $('cq-correct').value,
            });
            clearCache();
            toast('Добавлено', 'success'); closeModal(); loadCertification();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function deleteCertQuestion(id) {
    if (!confirm('Удалить вопрос?')) return;
    try { await api('/api/admin/certification/delete', { id }); clearCache(); toast('Удалено', 'success'); loadCertification(); }
    catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══════════════════════════════════════════
// FAQ
// ═══════════════════════════════════════════
async function loadFAQ() {
    const canEdit = hasPerm('faq_edit');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header">
                <div class="neu-card__header-title">FAQ</div>
                ${canEdit ? '<button class="btn btn--primary" onclick="openAddFaq()">Создать</button>' : ''}
            </div>
            <div id="faq-list"><div class="loading">Загрузка...</div></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/faq', {});
        const faq = data.faq || [];
        $('faq-list').innerHTML = faq.map(f => `
            <div class="neu-card" style="margin-bottom:16px; box-shadow: none; border: 1px solid var(--border);">
                <div style="display:flex;justify-content:space-between;gap:16px;">
                    <div style="flex:1;">
                        <div style="font-weight:700;margin-bottom:8px; font-size:15px;">${esc(f.question)}</div>
                        <div style="font-size:13px;color:var(--text-sec);white-space:pre-wrap;">${esc(f.answer)}</div>
                    </div>
                    ${canEdit ? `<button class="btn btn--sm btn--outline-danger" style="align-self:flex-start;" onclick="deleteFaq(${f.id})">Удалить</button>` : ''}
                </div>
            </div>
        `).join('') || '<div class="empty">Нет записей</div>';
    } catch (e) { $('faq-list').innerHTML = `<div class="empty">Ошибка: ${esc(e.message)}</div>`; }
}

function openAddFaq() {
    openModal('Новый FAQ', `
        <div class="form-group"><label>Вопрос</label><input class="form-input" id="faq-q"></div>
        <div class="form-group"><label>Ответ</label><textarea class="form-textarea" id="faq-a" rows="5"></textarea></div>
        <div class="form-hint" id="faq-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="faq-save">Сохранить</button>`);
    $('faq-save').addEventListener('click', async () => {
        const errEl = $('faq-error'); errEl.textContent = '';
        try {
            await api('/api/admin/faq/add', { question: $('faq-q').value.trim(), answer: $('faq-a').value.trim() });
            clearCache();
            toast('Добавлено', 'success'); closeModal(); loadFAQ();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function deleteFaq(id) {
    if (!confirm('Удалить?')) return;
    try { await api('/api/admin/faq/delete', { id }); clearCache(); toast('Удалено', 'success'); loadFAQ(); }
    catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══════════════════════════════════════════
// POSITIONS
// ═══════════════════════════════════════════
async function loadPositions() {
    const canEdit = hasPerm('positions_edit');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header">
                <div class="neu-card__header-title">Должности</div>
                ${canEdit ? '<button class="btn btn--primary" onclick="openAddPosition()">Создать</button>' : ''}
            </div>
            <div id="pos-list"><div class="loading">Загрузка...</div></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/positions', {});
        const positions = data.positions || [];
        $('pos-list').innerHTML = `<div class="table-wrap"><table class="t"><thead><tr><th>Должность</th><th>Статус</th><th>Действия</th></tr></thead><tbody>
        ${positions.map(p => `<tr>
            <td style="font-weight:600;">${esc(p.name)}</td>
            <td>${p.is_archived ? '<span class="tag tag--amber">В архиве</span>' : '<span class="tag tag--green">Активна</span>'}</td>
            <td>
                <div style="display:flex; gap:8px; white-space:nowrap;">
                    ${canEdit && !p.is_archived ? `<button class="btn btn--sm btn--outline" onclick="archivePosition(${p.id})">В архив</button>` : ''}
                </div>
            </td>
        </tr>`).join('')}
        </tbody></table></div>`;
    } catch (e) { $('pos-list').innerHTML = `<div class="empty">Ошибка: ${esc(e.message)}</div>`; }
}

function openAddPosition() {
    openModal('Новая должность', `
        <div class="form-group"><label>Название</label><input class="form-input" id="pos-name"></div>
        <div class="form-hint" id="pos-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="pos-save">Сохранить</button>`);
    $('pos-save').addEventListener('click', async () => {
        const errEl = $('pos-error'); errEl.textContent = '';
        try {
            await api('/api/admin/position/add', { name: $('pos-name').value.trim() });
            clearCache();
            toast('Добавлено', 'success'); closeModal(); loadPositions();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function archivePosition(id) {
    if (!confirm('Отправить в архив?')) return;
    try { await api('/api/admin/position/archive', { id }); clearCache(); toast('В архиве', 'success'); loadPositions(); }
    catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══════════════════════════════════════════
// CITIZENSHIPS
// ═══════════════════════════════════════════
async function loadCitizenships() {
    const canEdit = hasPerm('citizenships_edit');
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header">
                <div class="neu-card__header-title">Гражданства</div>
                ${canEdit ? '<button class="btn btn--primary" onclick="openAddCitizenship()">Создать</button>' : ''}
            </div>
            <div id="cit-list"><div class="loading">Загрузка...</div></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/citizenships', {});
        const list = data.citizenships || [];
        $('cit-list').innerHTML = `<div class="table-wrap"><table class="t"><thead><tr><th>Название</th><th>Действия</th></tr></thead><tbody>
        ${list.map(c => `<tr>
            <td style="font-weight:600;">${esc(c.name)}</td>
            <td>
                <div style="display:flex; gap:8px; white-space:nowrap;">
                    ${canEdit ? `<button class="btn btn--sm btn--outline-danger" onclick="deleteCitizenship(${c.id})">Удалить</button>` : ''}
                </div>
            </td>
        </tr>`).join('')}
        </tbody></table></div>`;
    } catch (e) { $('cit-list').innerHTML = `<div class="empty">Ошибка: ${esc(e.message)}</div>`; }
}

function openAddCitizenship() {
    openModal('Новое гражданство', `
        <div class="form-group"><label>Название</label><input class="form-input" id="cit-name"></div>
        <div class="form-hint" id="cit-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="cit-save">Сохранить</button>`);
    $('cit-save').addEventListener('click', async () => {
        const errEl = $('cit-error'); errEl.textContent = '';
        try {
            await api('/api/admin/citizenship/add', { name: $('cit-name').value.trim() });
            clearCache();
            toast('Добавлено', 'success'); closeModal(); loadCitizenships();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function deleteCitizenship(id) {
    if (!confirm('Удалить?')) return;
    try { await api('/api/admin/citizenship/delete', { id }); clearCache(); toast('Удалено', 'success'); loadCitizenships(); }
    catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══════════════════════════════════════════
// RESTAURANTS
// ═══════════════════════════════════════════
async function loadRestaurants() {
    try {
        const data = await api('/api/admin/restaurants', {});
        const rests = data.restaurants || [];
        const tus = data.tu_candidates || [];
        window._restaurants = rests;
        window._tuCandidates = tus;
        const canEdit = hasPerm('restaurant_edit');
        const canCreate = hasPerm('restaurant_create');
        const canTU = hasPerm('restaurant_tu');
        $('page-content').innerHTML = `
            <div class="neu-card">
                <div class="neu-card__header">
                    <div class="neu-card__header-title">Рестораны</div>
                    ${canCreate ? '<button class="btn btn--primary" onclick="openAddRestaurant()">Создать</button>' : ''}
                </div>
                <div class="table-wrap">
                    <table class="t"><thead><tr><th>Название</th><th>Ключ</th><th>Адрес</th><th>ТУ</th><th>Статус</th><th>Действия</th></tr></thead>
                    <tbody>
                    ${rests.map(r => `<tr>
                        <td style="font-weight:600;">${esc(r.name)}</td>
                        <td><span class="tag">${esc(r.key)}</span></td>
                        <td>${esc(r.address || '—')}</td>
                        <td>${esc(r.territory_manager_name || '—')}</td>
                        <td>${r.force_status === 'closed' ? '<span class="tag tag--pink">Закрыт</span>' : '<span class="tag tag--green">Открыт</span>'}</td>
                        <td>
                            <div style="display:flex; gap:8px; white-space:nowrap;">
                                ${canEdit ? `<button class="btn btn--sm btn--outline" onclick="openEditRestaurant('${esc(r.key)}')">Изменить</button>` : ''}
                                ${canTU ? `<button class="btn btn--sm btn--outline" onclick="openTURestaurant('${esc(r.key)}',${r.territory_manager_id || 'null'})">ТУ</button>` : ''}
                                ${canEdit ? `<button class="btn btn--sm btn--outline-danger" onclick="toggleRestaurantStatus('${esc(r.key)}','${r.force_status || 'open'}')">${r.force_status === 'closed' ? 'Открыть' : 'Закрыть'}</button>` : ''}
                            </div>
                        </td>
                    </tr>`).join('') || '<tr><td colspan="6" style="text-align:center;padding:40px;">Нет ресторанов</td></tr>'}
                    </tbody></table>
                </div>
            </div>`;
    } catch (e) { $('page-content').innerHTML = `<div class="empty">Ошибка: ${esc(e.message)}</div>`; }
}

function openAddRestaurant() {
    openModal('Новый ресторан', `
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Ключ (латиница)</label><input class="form-input" id="rest-key" placeholder="restaurant_1"></div>
            <div class="form-group"><label>Название</label><input class="form-input" id="rest-name"></div>
        </div>
        <div class="form-group"><label>Адрес</label><input class="form-input" id="rest-address"></div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Телефон</label><input class="form-input" id="rest-phone"></div>
            <div class="form-group"><label>Часы работы</label><input class="form-input" id="rest-hours"></div>
        </div>
        <div class="form-group"><label>Организация</label><input class="form-input" id="rest-org"></div>
        <div class="form-hint" id="rest-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="rest-save">Создать</button>`);
    $('rest-save').addEventListener('click', async () => {
        const errEl = $('rest-error'); errEl.textContent = '';
        try {
            await api('/api/admin/restaurant/add', {
                key: $('rest-key').value.trim(),
                name: $('rest-name').value.trim(),
                address: $('rest-address').value.trim(),
                phone: $('rest-phone').value.trim(),
                hours: $('rest-hours').value.trim(),
                org: $('rest-org').value.trim(),
            });
            clearCache();
            toast('Создан', 'success'); closeModal(); loadRestaurants();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

function openEditRestaurant(key) {
    const r = (window._restaurants || []).find(x => x.key === key);
    if (!r) return;
    openModal('Редактировать: ' + (r.name || key), `
        <div class="form-group"><label>Название</label><input class="form-input" id="er-name" value="${esc(r.name || '')}"></div>
        <div class="form-group"><label>Адрес</label><input class="form-input" id="er-address" value="${esc(r.address || '')}"></div>
        <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div class="form-group"><label>Телефон</label><input class="form-input" id="er-phone" value="${esc(r.phone || '')}"></div>
            <div class="form-group"><label>Часы</label><input class="form-input" id="er-hours" value="${esc(r.hours || '')}"></div>
        </div>
        <div class="form-group"><label>Организация</label><input class="form-input" id="er-org" value="${esc(r.org || '')}"></div>
        <div class="form-hint" id="er-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="er-save">Сохранить</button>`);
    $('er-save').addEventListener('click', async () => {
        const errEl = $('er-error'); errEl.textContent = '';
        try {
            await api('/api/admin/restaurant/update', {
                key,
                updates: {
                    name: $('er-name').value.trim(),
                    address: $('er-address').value.trim(),
                    phone: $('er-phone').value.trim(),
                    hours: $('er-hours').value.trim(),
                    org: $('er-org').value.trim(),
                }
            });
            clearCache();
            toast('Сохранено', 'success'); closeModal(); loadRestaurants();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

function openTURestaurant(key, currentTu) {
    const tus = window._tuCandidates || [];
    const opts = '<option value="">— Не назначен —</option>' + tus.map(t =>
        `<option value="${t.user_id}" ${t.user_id === currentTu ? 'selected' : ''}>${esc(t.full_name)}</option>`
    ).join('');
    openModal('Территориальный управляющий', `
        <div class="form-group"><label>ТУ</label><select class="form-select" id="tu-select">${opts}</select></div>
        <div class="form-hint" id="tu-error"></div>
    `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="tu-save">Сохранить</button>`);
    $('tu-save').addEventListener('click', async () => {
        const errEl = $('tu-error'); errEl.textContent = '';
        try {
            const val = $('tu-select').value;
            await api('/api/admin/restaurant/tu', { key, territory_manager_id: val ? parseInt(val) : null });
            clearCache();
            toast('Сохранено', 'success'); closeModal(); loadRestaurants();
        } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
    });
}

async function toggleRestaurantStatus(key, currentStatus) {
    const newStatus = currentStatus === 'closed' ? 'open' : 'closed';
    try {
        await api('/api/admin/restaurant/status', { key, status: newStatus });
        clearCache();
        toast('Статус обновлён', 'success');
        loadRestaurants();
    } catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══════════════════════════════════════════
// QUESTIONS
// ═══════════════════════════════════════════
async function loadQuestions() {
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header"><div class="neu-card__header-title">Вопросы от сотрудников</div></div>
            <div id="q-list"><div class="loading">Загрузка...</div></div>
        </div>`;
    try {
        const data = await cachedApi('/api/admin/questions', {});
        const list = data.questions || [];
        $('q-list').innerHTML = list.map(q => `
            <div class="neu-card" style="margin-bottom:16px; box-shadow: none; border: 1px solid var(--border);">
                <div style="display:flex;justify-content:space-between;gap:16px;">
                    <div style="flex:1;">
                        <div style="font-weight:700;margin-bottom:8px; font-size:15px;">${esc(q.full_name || 'Сотрудник')}</div>
                        <div style="font-size:14px;color:var(--text-sec);white-space:pre-wrap;">${esc(q.text)}</div>
                        <div style="font-size:12px;color:var(--text-sec);margin-top:8px;">${fmtDate(q.created_at, true)}</div>
                    </div>
                    <div>${q.replied ? '<span class="tag tag--green">Отвечен</span>' : '<span class="tag tag--amber">Ожидает</span>'}</div>
                </div>
            </div>
        `).join('') || '<div class="empty">Нет вопросов</div>';
    } catch (e) { $('q-list').innerHTML = `<div class="empty">Ошибка: ${esc(e.message)}</div>`; }
}

// ═══════════════════════════════════════════
// ADMINS
// ═══════════════════════════════════════════
async function loadAdmins() {
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header"><div class="neu-card__header-title">Администраторы</div></div>
            <div id="admins-list"><div class="loading">Загрузка...</div></div>
        </div>`;
    try {
        const data = await api('/api/admin/admins', {});
        const admins = data.admins || [];
        _adminPermsMap = {};
        $('admins-list').innerHTML = `<div class="table-wrap"><table class="t"><thead><tr><th>ФИО</th><th>Логин</th><th>Роль</th><th>Действия</th></tr></thead><tbody>
        ${admins.map(a => {
            let acts = '';
            if (isSuperAdmin() && !a.is_super_admin) {
                let parsedPerms = {};
                try {
                    parsedPerms = typeof a.permissions === 'string' ? JSON.parse(a.permissions || '{}') : (a.permissions || {});
                } catch (e) {}
                _adminPermsMap[a.user_id] = {
                    name: a.full_name || '',
                    permissions: parsedPerms,
                };
                acts = `<button class="btn btn--sm btn--outline" onclick="openEditPermissions(${a.user_id})">Права</button>`;
            }
            return `<tr>
                <td style="font-weight:600;">${esc(a.full_name || '—')}</td>
                <td>@${esc(a.login || '')}</td>
                <td>${a.is_super_admin ? '<span class="tag tag--purple">Суперадмин</span>' : '<span class="tag tag--blue">Админ</span>'}</td>
                <td>
                    <div style="display:flex; gap:8px; white-space:nowrap;">
                        ${acts}
                    </div>
                </td>
            </tr>`;
        }).join('')}
        </tbody></table></div>`;
    } catch (e) { $('admins-list').innerHTML = `<div class="empty">Ошибка: ${esc(e.message)}</div>`; }
}

async function openEditPermissions(uid) {
    const meta = _adminPermsMap[uid] || { name: '', permissions: {} };
    const name = meta.name;
    const activePerms = meta.permissions || {};

    let permsList = [];
    try {
        const data = await api('/api/admin/permissions-list', {});
        permsList = data.permissions || [];
    } catch (e) { toast('Ошибка загрузки списка прав', 'error'); return; }

    let html = `<div class="form-group">
        <label style="margin-bottom:16px; display:block; font-size:15px;">Права для: <strong>${esc(name)}</strong></label>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">`;

    permsList.forEach(p => {
        const checked = activePerms[p.key] ? 'checked' : '';
        html += `<label style="display:flex;align-items:flex-start;gap:8px;font-size:13px;cursor:pointer;line-height:1.3;padding:8px; border:1px solid var(--border); border-radius:6px; background:#f8fafc;">
            <input type="checkbox" class="perm-checkbox" value="${esc(p.key)}" ${checked} style="margin-top:2px;">
            <span>${esc(p.label)}</span>
        </label>`;
    });

    html += `</div></div><div class="form-hint error" id="perm-error"></div>`;

    openModal('Настройка прав администратора', html, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="perm-save">Сохранить</button>`);

    $('perm-save').addEventListener('click', async () => {
        const errEl = $('perm-error'); errEl.textContent = '';
        const newPerms = {};
        document.querySelectorAll('.perm-checkbox:checked').forEach(cb => {
            newPerms[cb.value] = true;
        });

        try {
            await api('/api/admin/set-permissions', { user_id: uid, permissions: newPerms });
            clearCache();
            toast('Права обновлены', 'success');
            closeModal();
            loadAdmins();
        } catch (e) {
            errEl.textContent = 'Ошибка: ' + e.message;
        }
    });
}

// ═══════════════════════════════════════════
// REPORTS
// ═══════════════════════════════════════════
async function loadReports() {
    $('page-content').innerHTML = '<div class="loading">Загрузка...</div>';
    try {
        const data = await api('/api/admin/reports', {});
        const r = data.report || {};
        $('page-content').innerHTML = `
            <div class="stats-grid">
                <div class="neu-card neu-card--stat purple"><div class="neu-card__label">Активные сотрудники</div><div class="neu-card__value">${r.active || 0}</div></div>
                <div class="neu-card neu-card--stat yellow"><div class="neu-card__label">На модерации</div><div class="neu-card__value">${(r.news_pending || 0) + (r.standards_pending || 0)}</div></div>
                <div class="neu-card neu-card--stat blue"><div class="neu-card__label">Медкнижки</div><div class="neu-card__value">${r.medbooks_alert || 0}</div></div>
                <div class="neu-card neu-card--stat green"><div class="neu-card__label">Вопросы</div><div class="neu-card__value">${r.questions_open || 0}</div></div>
            </div>`;
    } catch (e) {
        $('page-content').innerHTML = `<div class="empty">Ошибка: ${esc(e.message)}</div>`;
    }
}

// ═══════════════════════════════════════════
// AUDIT
// ═══════════════════════════════════════════
async function loadAudit() {
    $('page-content').innerHTML = `
        <div class="neu-card">
            <div class="neu-card__header"><div class="neu-card__header-title">История действий</div></div>
            <div id="audit-list"><div class="loading">Загрузка...</div></div>
        </div>`;
    try {
        const data = await api('/api/admin/audit', {});
        const list = data.audit || [];
        $('audit-list').innerHTML = `<div class="table-wrap"><table class="t"><thead><tr><th>Дата</th><th>Действие</th><th>Объект</th><th>Детали</th></tr></thead><tbody>
        ${list.map(a => `<tr>
            <td style="white-space:nowrap; color:var(--text-sec); font-size:12px;">${fmtDate(a.created_at, true)}</td>
            <td style="font-weight:600;">${esc(a.action || '—')}</td>
            <td><span class="tag">${esc((a.target_type || '') + ' ' + (a.target_id || ''))}</span></td>
            <td style="font-size:13px;color:var(--text-sec);">${esc(a.details || '')}</td>
        </tr>`).join('')}
        </tbody></table></div>`;
    } catch (e) { $('audit-list').innerHTML = `<div class="empty">Ошибка: ${esc(e.message)}</div>`; }
}

// ═══════════════════════════════════════════
// PAGE LOADERS
// ═══════════════════════════════════════════
const PAGE_LOADERS = {
    dashboard: loadDashboard,
    users: loadUsers,
    medbooks: loadMedbooks,
    news: loadNews,
    standards: loadStandards,
    certification: loadCertification,
    faq: loadFAQ,
    restaurants: loadRestaurants,
    positions: loadPositions,
    citizenships: loadCitizenships,
    questions: loadQuestions,
    admins: loadAdmins,
    reports: loadReports,
    audit: loadAudit,
};

// ═══════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
    // Login
    $('login-btn')?.addEventListener('click', doLogin);
    $('login-password')?.addEventListener('keypress', e => { if (e.key === 'Enter') doLogin(); });
    $('login-login')?.addEventListener('input', e => {
        e.target.value = e.target.value.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 5);
    });

    // Logout
    $('logout-btn')?.addEventListener('click', async () => {
        try { await api('/api/auth/logout', { webToken: getToken() }); } catch (e) {}
        clearToken(); clearCache(); showLogin();
    });

    // Change password
    $('change-password-btn')?.addEventListener('click', () => {
        openModal('Сменить пароль', `
            <div class="form-group"><label>Текущий пароль</label><input class="form-input" id="cp-old" type="password"></div>
            <div class="form-group"><label>Новый пароль</label><input class="form-input" id="cp-new" type="password"></div>
            <div class="form-hint" id="cp-error"></div>
        `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="cp-save">Сохранить</button>`);
        $('cp-save').addEventListener('click', async () => {
            const errEl = $('cp-error'); errEl.textContent = '';
            try {
                await api('/api/admin/change-password', { old_password: $('cp-old').value, new_password: $('cp-new').value });
                toast('Пароль изменён', 'success'); closeModal();
            } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
        });
    });

    // Nav
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            navigate(item.dataset.page);
            closeSidebar();
        });
    });

    // Sidebar
    $('hamburger')?.addEventListener('click', openSidebar);
    $('overlay')?.addEventListener('click', closeSidebar);

    // Modal close
    $('modal-close')?.addEventListener('click', closeModal);
    $('modal-overlay')?.addEventListener('click', e => { if (e.target === $('modal-overlay')) closeModal(); });

    // Auto-init
    if (getToken()) {
        checkAdminAndLoad();
    } else {
        showLogin();
    }
});
