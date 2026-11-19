/* ═══════════════════════════════════════════
   WOKKER ADMIN — BENTO EDITION JS
   ═══════════════════════════════════════════ */

const TOKEN_KEY = 'wokker_admin_token';
const LOGIN_RE = /^[a-z]{3}\d{2}$/;
let ME = null;
let _cache = {};

// ═══ Utils ═══
const $ = id => document.getElementById(id);
const esc = s => (s == null ? '' : String(s)).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

function getFileUrl(url) {
    if (!url) return '';
    return url + '?token=' + getToken();
}

// ═══ Cache ═══
async function cachedApi(path, body, ttl = 30000) {
    const key = path + (body ? JSON.stringify(body) : '');
    const now = Date.now();
    if (_cache[key] && now - _cache[key].time < ttl) return _cache[key].data;
    const data = await api(path, body);
    _cache[key] = { data, time: now };
    return data;
}
function clearCache() { _cache = {}; }

function cleanHTML(html) {
    if (!html) return '';
    let clean = String(html);
    clean = clean.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
    clean = clean.replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '');
    clean = clean.replace(/<iframe\b[^>]*>[\s\S]*?<\/iframe>/gi, '');
    clean = clean.replace(/href\s*=\s*["']?\s*javascript:/gi, 'href="#"');
    clean = clean.replace(/\s*(class|id)="[^"]*"/gi, '');
    return clean.trim();
}

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
    try {
        const j = await res.json();
        msg = j.detail || j.error || msg;
    } catch (e) {}
    throw new Error(msg);
  }
  const data = await res.json();
  if (data && (data.error === 'forbidden' || data.error === 'fired' || data.error === 'unauthorized')) {
    clearToken(); showLogin(); throw new Error(data.error);
  }
  return data;
}

async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch('/api/admin/upload', {
            method: 'POST',
            headers: { 'X-Token': getToken() },
            body: formData
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Upload failed');
        }
        return await res.json();
    } catch (e) {
        throw new Error('Ошибка сети при загрузке файла');
    }
}

// ═══ Mobile Sidebar ═══
const burger = document.getElementById('hamburger');
const overlay = document.getElementById('overlay');

function openSidebar() { document.getElementById('sidebar').classList.add('sidebar--open'); overlay.classList.add('overlay--show'); }
function closeSidebar() { document.getElementById('sidebar').classList.remove('sidebar--open'); overlay.classList.remove('overlay--show'); }

if (burger) burger.addEventListener('click', openSidebar);
if (overlay) overlay.addEventListener('click', closeSidebar);

// ═══ Permissions ═══
function isSuperAdmin() { return !!(ME && ME.is_super_admin); }
function isHR() { return !!(ME && ME.is_hr); }
function canPublish() { return isSuperAdmin() || isHR(); }
function hasPerm(perm) {
  if (!ME) return false;
  if (ME.is_super_admin || ME.is_hr) return true;
  return !!(ME.permissions && ME.permissions[perm]);
}

// ═══ Login ═══
function showLogin() {
  document.getElementById('app').style.display = 'none';
  document.getElementById('login-screen').style.display = 'flex';
  $('login-error').textContent = '';
  $('login-login').value = '';
  $('login-password').value = '';
  clearCache();
}

function showApp() {
  document.getElementById('app').style.display = 'block';
  document.getElementById('login-screen').style.display = 'none';
}

$('login-login').addEventListener('input', e => {
  e.target.value = e.target.value.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 5);
});

async function doLogin() {
  const login = $('login-login').value.trim().toLowerCase();
  const password = $('login-password').value;
  const errEl = $('login-error');
  errEl.textContent = '';
  if (!LOGIN_RE.test(login)) { errEl.textContent = 'Логин: 3 латинские буквы + 2 цифры'; return; }
  if (!password) { errEl.textContent = 'Введите пароль'; return; }
  const btn = $('login-btn');
  btn.disabled = true; btn.textContent = 'Проверяем…';
  try {
    const res = await fetch('/api/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login, password }),
    });
    if (res.status === 401) { errEl.textContent = 'Неверный логин или пароль'; return; }
    if (res.status === 403) { errEl.textContent = 'Аккаунт уволен или нет прав администратора'; return; }
    if (!res.ok) { errEl.textContent = 'Ошибка сервера'; return; }
    const data = await res.json();
    if (!data.token) { errEl.textContent = 'Ошибка'; return; }
    setToken(data.token);
    clearCache();
    await checkAdminAndLoad();
  } catch (e) {
    errEl.textContent = 'Сеть недоступна';
  } finally {
    btn.disabled = false; btn.textContent = 'Войти';
  }
}

$('login-btn').addEventListener('click', doLogin);
$('login-password').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
$('login-login').addEventListener('keydown', e => { if (e.key === 'Enter') $('login-password').focus(); });

async function checkAdminAndLoad() {
  try {
    const res = await api('/api/admin/me', {});
    ME = res.profile;
    $('admin-name').textContent = ME.full_name || '—';
    $('admin-login').textContent = '@' + (ME.login || '');
    $('admin-role').textContent = ME.is_super_admin ? 'Супер-админ' : ME.is_hr ? 'HR' : 'Админ';
    showApp();
    if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
        navigator.serviceWorker.controller.postMessage({ type: 'SET_TOKEN', token: getToken() });
    }
    navigate('dashboard');
    refreshCounters();
  } catch (e) {
    showLogin();
    $('login-error').textContent = 'Ошибка: ' + e.message;
  }
}

$('logout-btn')?.addEventListener('click', async () => {
  if (!confirm('Выйти?')) return;
  try { await api('/api/auth/logout', {}); } catch (e) {}
  clearToken(); ME = null; closeSidebar(); clearCache(); showLogin();
});

// ═══ Navigation ═══
const PAGE_TITLES = {
  dashboard: 'Дашборд', users: 'Сотрудники', timesheet: 'Табель', medbooks: 'Медкнижки',
  payments: 'Выплаты', news: 'Новости', standards: 'Стандарты', academy: 'Академия', faq: 'FAQ',
  restaurants: 'Рестораны', settings: 'Настройки',
};

function navigate(page) {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('nav-item--active', item.dataset.page === page);
  });
  $('page-title').textContent = PAGE_TITLES[page] || page;
  $('page-date').textContent = new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
  $('page-content').innerHTML = '<div class="loading">Загрузка...</div>';
  
  const loader = PAGE_LOADERS[page];
  if (loader) {
    loader()
      .then(() => refreshCounters())
      .catch(e => {
        console.error('load:', e);
        if (e.message !== 'unauthorized' && e.message !== 'fired') {
          $('page-content').innerHTML = '<div class="empty">Ошибка: ' + esc(e.message) + '</div>';
        }
      });
  }
}

document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', e => {
    e.preventDefault();
    closeSidebar();
    navigate(item.dataset.page);
  });
});

// ═══ Page Loaders ═══
const PAGE_LOADERS = {
  dashboard: loadDashboard,
  users: loadUsers,
  timesheet: () => { $('page-content').innerHTML = '<div class="b-card b-card--wide"><div class="b-card__label">Табель</div><div class="b-card__meta">Раздел в разработке</div></div>'; },
  medbooks: loadMedbooks,
  payments: () => { $('page-content').innerHTML = '<div class="b-card b-card--wide"><div class="b-card__label">Выплаты</div><div class="b-card__meta">Раздел в разработке</div></div>'; },
  news: loadNews,
  standards: loadStandards,
  academy: () => { $('page-content').innerHTML = '<div class="b-card b-card--wide"><div class="b-card__label">Академия</div><div class="b-card__meta">Раздел в разработке</div></div>'; },
  faq: loadFaq,
  restaurants: loadRestaurants,
  settings: loadSettings,
};

// ═══ Dashboard ═══
async function loadDashboard() {
  $('page-content').innerHTML = `
    <div class="b-card b-card--stat">
      <div class="b-card__label">Активных</div>
      <div class="b-card__value b-card__value--green" id="stat-active"><div class="skeleton" style="height:32px;width:60%;border-radius:8px;background:rgba(255,255,255,0.05);"></div></div>
      <div class="b-card__meta"><span class="b-card__dot b-card__dot--up"></span> +3 за неделю</div>
    </div>
    <div class="b-card b-card--stat">
      <div class="b-card__label">На модерации</div>
      <div class="b-card__value b-card__value--amber" id="stat-pending"><div class="skeleton" style="height:32px;width:60%;border-radius:8px;background:rgba(255,255,255,0.05);"></div></div>
      <div class="b-card__meta"><span class="b-card__dot b-card__dot--warn"></span> Ожидают проверки</div>
    </div>
    <div class="b-card b-card--stat">
      <div class="b-card__label">Медкнижки</div>
      <div class="b-card__value b-card__value--accent" id="stat-medbooks"><div class="skeleton" style="height:32px;width:60%;border-radius:8px;background:rgba(255,255,255,0.05);"></div></div>
      <div class="b-card__meta"><span class="b-card__dot b-card__dot--down"></span> Требуют внимания</div>
    </div>
    <div class="b-card b-card--stat">
      <div class="b-card__label">К выплате</div>
      <div class="b-card__value b-card__value--blue" id="stat-payments">₽0</div>
      <div class="b-card__meta"><span class="b-card__dot b-card__dot--up"></span> Текущий период</div>
    </div>
    <div class="b-card b-card--wide">
      <div class="b-card__label" style="margin-bottom:16px;">Последняя активность</div>
      <div class="activity" id="dash-activity">
        <div class="activity__item"><div class="activity__icon activity__icon--green">👤</div><div><div class="activity__text"><strong>HR</strong> создала сотрудника — <strong>Иванов А.</strong></div><div class="activity__time">14 мин назад</div></div></div>
        <div class="activity__item"><div class="activity__icon activity__icon--accent">📰</div><div><div class="activity__text"><strong>Смирнов В.</strong> предложил новость</div><div class="activity__time">1 час назад</div></div></div>
        <div class="activity__item"><div class="activity__icon activity__icon--blue">📋</div><div><div class="activity__text"><strong>Табель за октябрь</strong> подписан — 4 ресторана</div><div class="activity__time">2 часа назад</div></div></div>
      </div>
    </div>
    <div class="b-card b-card--tall">
      <div class="b-card__label" style="margin-bottom:16px;">Новые сотрудники</div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Имя</th><th>Статус</th></tr></thead>
          <tbody id="dash-users-table">
            <tr><td><div class="name"><div class="avatar" style="background:linear-gradient(135deg,#ff4444,#ff6b35)">И</div>Иванов А.</div></td><td><span class="tag tag--green">Активен</span></td></tr>
            <tr><td><div class="name"><div class="avatar" style="background:linear-gradient(135deg,#3b82f6,#22c55e)">П</div>Петрова М.</div></td><td><span class="tag tag--green">Активен</span></td></tr>
            <tr><td><div class="name"><div class="avatar" style="background:linear-gradient(135deg,#a855f7,#3b82f6)">К</div>Козлов Д.</div></td><td><span class="tag tag--amber">Испыт.</span></td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
  
  try {
    const data = await cachedApi('/api/admin/dashboard/summary', {}, 10000);
    const stats = data.stats || {};
    if ($('stat-active')) $('stat-active').textContent = stats.active || 0;
    if ($('stat-pending')) $('stat-pending').textContent = (stats.news_pending || 0) + (stats.standards_pending || 0);
    if ($('stat-medbooks')) $('stat-medbooks').textContent = stats.medbooks_alert || 0;
  } catch (e) {
    console.error('Dashboard error:', e);
  }
}

// ═══ Users ═══
async function loadUsers() {
  $('page-content').innerHTML = `
    <div class="b-card b-card--wide">
      <div class="b-card__label" style="margin-bottom:16px;">Сотрудники</div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Сотрудник</th><th>Позиция</th><th>Ресторан</th><th>Статус</th></tr></thead>
          <tbody id="users-table">
            <tr><td colspan="4" style="text-align:center;color:var(--text-muted);">Загрузка...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
  
  try {
    const data = await cachedApi('/api/admin/users', { search: '', fired: false });
    const users = data.users || [];
    const tbody = $('users-table');
    tbody.innerHTML = users.map(u => `
      <tr>
        <td><div class="name"><div class="avatar" style="background:linear-gradient(135deg,#3b82f6,#a855f7)">${(u.full_name || '?').charAt(0)}</div>${esc(u.full_name)}</div></td>
        <td>${esc(u.position || '—')}</td>
        <td>${esc(u.restaurant_name || '—')}</td>
        <td><span class="tag ${u.is_fired ? 'tag--amber' : 'tag--green'}">${u.is_fired ? 'Уволен' : 'Активен'}</span></td>
      </tr>
    `).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">Нет сотрудников</td></tr>';
  } catch (e) {
    $('users-table').innerHTML = `<tr><td colspan="4" class="empty">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ Medbooks ═══
async function loadMedbooks() {
  $('page-content').innerHTML = `
    <div class="b-card b-card--wide">
      <div class="b-card__label" style="margin-bottom:16px;">Медкнижки</div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Сотрудник</th><th>Позиция</th><th>Статус</th></tr></thead>
          <tbody>
            <tr><td><div class="name">Иванова М.</div></td><td>Повар</td><td><span class="tag tag--amber">Истекает через 12 дней</span></td></tr>
            <tr><td><div class="name">Петров С.</div></td><td>Официант</td><td><span class="tag tag--green">OK</span></td></tr>
            <tr><td><div class="name">Сидорова А.</div></td><td>Кассир</td><td><span class="tag tag--blue">Заполняется</span></td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
}

// ═══ News ═══
async function loadNews() {
  $('page-content').innerHTML = `
    <div class="b-card b-card--wide">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <div class="b-card__label" style="margin:0;">Новости</div>
        <span style="font-size:11px;color:var(--text-muted);font-weight:600;">5 элементов</span>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Тип</th><th>Заголовок</th><th>Автор</th><th>Дата</th><th></th></tr></thead>
          <tbody>
            <tr>
              <td><span class="tag tag--blue">Новость</span></td>
              <td style="color:var(--text);font-weight:600;">Новые стандарты подачи блюд</td>
              <td>Смирнов В.</td>
              <td>18.11.2026</td>
              <td><button class="btn btn--ghost" style="padding:6px 14px;font-size:12px;">✓ Принять</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
}

// ═══ Standards ═══
async function loadStandards() {
  $('page-content').innerHTML = `
    <div class="b-card b-card--wide">
      <div class="b-card__label" style="margin-bottom:16px;">Стандарты</div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Заголовок</th><th>Группа</th><th>Статус</th></tr></thead>
          <tbody>
            <tr><td style="color:var(--text);font-weight:600;">Пищевая безопасность</td><td>Общее</td><td><span class="tag tag--green">Опубликован</span></td></tr>
            <tr><td style="color:var(--text);font-weight:600;">Работа на кассе</td><td>Касса</td><td><span class="tag tag--green">Опубликован</span></td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
}

// ═══ FAQ ═══
async function loadFaq() {
  $('page-content').innerHTML = `
    <div class="b-card b-card--wide">
      <div class="b-card__label" style="margin-bottom:16px;">FAQ</div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Вопрос</th><th>Категория</th></tr></thead>
          <tbody>
            <tr><td style="color:var(--text);font-weight:600;">Как заполнить медкнижку?</td><td>Медкнижки</td></tr>
            <tr><td style="color:var(--text);font-weight:600;">Как поставить табель?</td><td>Табель</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
}

// ═══ Restaurants ═══
async function loadRestaurants() {
  $('page-content').innerHTML = `
    <div class="b-card b-card--wide">
      <div class="b-card__label" style="margin-bottom:16px;">Рестораны</div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Название</th><th>Адрес</th><th>Статус</th></tr></thead>
          <tbody>
            <tr><td style="color:var(--text);font-weight:600;">Wokker Центральный</td><td>ул. Ленина, 1</td><td><span class="tag tag--green">Открыт</span></td></tr>
            <tr><td style="color:var(--text);font-weight:600;">Wokker Северный</td><td>пр. Мира, 15</td><td><span class="tag tag--green">Открыт</span></td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
}

// ═══ Settings ═══
async function loadSettings() {
  $('page-content').innerHTML = `
    <div class="b-card b-card--wide">
      <div class="b-card__label" style="margin-bottom:16px;">Настройки</div>
      <div style="color:var(--text-dim);font-size:14px;line-height:1.6;">
        <p>Здесь будут настройки системы, управления сотрудниками и интеграции.</p>
      </div>
    </div>
  `;
}

// ═══ Counters ═══
async function refreshCounters() {
  try {
    const n = await cachedApi('/api/admin/news', {});
    const pending = (n.news || []).filter(x => x.status === 'pending').length;
    const nEl = $('news-pending-count');
    if (nEl) { if (pending > 0 && canPublish()) { nEl.textContent = pending; nEl.style.display = 'inline-block'; } else nEl.style.display = 'none'; }
  } catch (e) {}
}

// ═══ Init ═══
if (getToken()) {
  checkAdminAndLoad();
} else {
  showLogin();
}
