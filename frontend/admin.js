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
    <!-- Stat Cards Row -->
    <div class="b-card b-card--stat stat--green">
      <div class="b-card__label">
        <div class="b-card__icon b-card__icon--green">👥</div>
        Сотрудники
      </div>
      <div class="b-card__value b-card__value--green" id="stat-active">
        <div class="skeleton" style="height:28px;width:50px;border-radius:8px;background:rgba(255,255,255,0.05);"></div>
      </div>
      <div class="b-card__meta">
        <span class="b-card__trend b-card__trend--up">↑ +3</span>
        <span>за неделю</span>
      </div>
    </div>
    
    <div class="b-card b-card--stat stat--amber">
      <div class="b-card__label">
        <div class="b-card__icon b-card__icon--amber">📝</div>
        На модерации
      </div>
      <div class="b-card__value b-card__value--amber" id="stat-pending">
        <div class="skeleton" style="height:28px;width:50px;border-radius:8px;background:rgba(255,255,255,0.05);"></div>
      </div>
      <div class="b-card__meta">
        <span class="b-card__trend b-card__trend--warn">⏳</span>
        <span>Ожидают проверки</span>
      </div>
    </div>
    
    <div class="b-card b-card--stat stat--purple">
      <div class="b-card__label">
        <div class="b-card__icon b-card__icon--purple">📖</div>
        Медкнижки
      </div>
      <div class="b-card__value b-card__value--purple" id="stat-medbooks">
        <div class="skeleton" style="height:28px;width:50px;border-radius:8px;background:rgba(255,255,255,0.05);"></div>
      </div>
      <div class="b-card__meta">
        <span class="b-card__trend b-card__trend--down">!</span>
        <span>Требуют внимания</span>
      </div>
    </div>
    
    <div class="b-card b-card--stat stat--blue">
      <div class="b-card__label">
        <div class="b-card__icon b-card__icon--blue">💰</div>
        К выплате
      </div>
      <div class="b-card__value b-card__value--blue" id="stat-payments">₽0</div>
      <div class="b-card__meta">
        <span class="b-card__trend b-card__trend--up">↑</span>
        <span>Текущий период</span>
      </div>
    </div>

    <!-- Activity + New Hires -->
    <div class="b-card b-card--wide">
      <div class="b-card__header">
        <div class="b-card__header-title">Последняя активность</div>
        <div class="b-card__header-action" onclick="navigate('news')">Все события →</div>
      </div>
      <div class="activity" id="dash-activity">
        <div class="activity__item">
          <div class="activity__icon activity__icon--green">👤</div>
          <div class="activity__content">
            <div class="activity__text"><strong>HR</strong> создала сотрудника — <strong>Иванов А.</strong></div>
            <div class="activity__time">14 мин назад</div>
          </div>
        </div>
        <div class="activity__item">
          <div class="activity__icon activity__icon--accent">📰</div>
          <div class="activity__content">
            <div class="activity__text"><strong>Смирнов В.</strong> предложил новость — <strong>Новые стандарты подачи</strong></div>
            <div class="activity__time">1 час назад</div>
          </div>
        </div>
        <div class="activity__item">
          <div class="activity__icon activity__icon--blue">📋</div>
          <div class="activity__content">
            <div class="activity__text"><strong>Табель за ноябрь</strong> подписан — <strong>4 ресторана</strong></div>
            <div class="activity__time">2 часа назад</div>
          </div>
        </div>
        <div class="activity__item">
          <div class="activity__icon activity__icon--purple">🎓</div>
          <div class="activity__content">
            <div class="activity__text"><strong>Петрова М.</strong> прошла сертификацию — <strong>Санитария</strong></div>
            <div class="activity__time">3 часа назад</div>
          </div>
        </div>
      </div>
    </div>

    <div class="b-card b-card--tall">
      <div class="b-card__header">
        <div class="b-card__header-title">Новые сотрудники</div>
        <div class="b-card__header-action" onclick="navigate('users')">Все сотрудники →</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Имя</th><th>Статус</th></tr></thead>
          <tbody id="dash-users-table">
            <tr>
              <td><div class="name-cell"><div class="avatar" style="background:linear-gradient(135deg,#ef4444,#f97316)">И</div>Иванов А.</div></td>
              <td><span class="tag tag--green">Активен</span></td>
            </tr>
            <tr>
              <td><div class="name-cell"><div class="avatar" style="background:linear-gradient(135deg,#3b82f6,#22c55e)">П</div>Петрова М.</div></td>
              <td><span class="tag tag--green">Активен</span></td>
            </tr>
            <tr>
              <td><div class="name-cell"><div class="avatar" style="background:linear-gradient(135deg,#a855f7,#3b82f6)">К</div>Козлов Д.</div></td>
              <td><span class="tag tag--amber">Испыт.</span></td>
            </tr>
            <tr>
              <td><div class="name-cell"><div class="avatar" style="background:linear-gradient(135deg,#ec4899,#a855f7)">С</div>Сидорова Е.</div></td>
              <td><span class="tag tag--green">Активен</span></td>
            </tr>
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
      <div class="b-card__header">
        <div class="b-card__header-title">Сотрудники</div>
        <span style="font-size:12px;color:var(--text-tertiary);font-weight:600;" id="users-count">Загрузка...</span>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Сотрудник</th><th>Позиция</th><th>Ресторан</th><th>Статус</th></tr></thead>
          <tbody id="users-table">
            <tr><td colspan="4" style="text-align:center;color:var(--text-tertiary);padding:40px;">
              <div class="loading">Загрузка...</div>
            </td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  try {
    const data = await cachedApi('/api/admin/users', { search: '', fired: false });
    const users = data.users || [];
    const tbody = $('users-table');
    if ($('users-count')) $('users-count').textContent = users.length + ' сотрудников';
    tbody.innerHTML = users.map(u => {
      const gradients = [
        'linear-gradient(135deg,#ef4444,#f97316)',
        'linear-gradient(135deg,#3b82f6,#22c55e)',
        'linear-gradient(135deg,#a855f7,#3b82f6)',
        'linear-gradient(135deg,#ec4899,#a855f7)',
        'linear-gradient(135deg,#06b6d4,#3b82f6)',
      ];
      const grad = gradients[Math.abs(hashCode(u.full_name || '')) % gradients.length];
      return `
        <tr>
          <td><div class="name-cell"><div class="avatar" style="background:${grad}">${(u.full_name || '?').charAt(0).toUpperCase()}</div>${esc(u.full_name || '—')}</div></td>
          <td class="position">${esc(u.position || '—')}</td>
          <td class="restaurant">${esc(u.restaurant_name || '—')}</td>
          <td><span class="tag ${u.is_fired ? 'tag--amber' : 'tag--green'}">${u.is_fired ? 'Уволен' : 'Активен'}</span></td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-tertiary);padding:40px;">Нет сотрудников</td></tr>';
  } catch (e) {
    $('users-table').innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-tertiary);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

function hashCode(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash |= 0;
  }
  return hash;
}

// ═══ Medbooks ═══
async function loadMedbooks() {
  $('page-content').innerHTML = `
    <div class="b-card b-card--wide">
      <div class="b-card__header">
        <div class="b-card__header-title">Медкнижки</div>
        <div class="b-card__header-action">Экспорт →</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Сотрудник</th><th>Позиция</th><th>Ресторан</th><th>Статус</th></tr></thead>
          <tbody id="medbooks-table">
            <tr>
              <td><div class="name-cell"><div class="avatar" style="background:linear-gradient(135deg,#ef4444,#f97316)">И</div>Иванова М.</div></td>
              <td class="position">Повар</td>
              <td class="restaurant">Wokker Центральный</td>
              <td><span class="tag tag--amber">Истекает через 12 дней</span></td>
            </tr>
            <tr>
              <td><div class="name-cell"><div class="avatar" style="background:linear-gradient(135deg,#3b82f6,#22c55e)">П</div>Петров С.</div></td>
              <td class="position">Официант</td>
              <td class="restaurant">Wokker Северный</td>
              <td><span class="tag tag--green">OK</span></td>
            </tr>
            <tr>
              <td><div class="name-cell"><div class="avatar" style="background:linear-gradient(135deg,#a855f7,#3b82f6)">С</div>Сидорова А.</div></td>
              <td class="position">Кассир</td>
              <td class="restaurant">Wokker Центральный</td>
              <td><span class="tag tag--blue">Заполняется</span></td>
            </tr>
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
      <div class="b-card__header">
        <div class="b-card__header-title">Новости</div>
        <div class="b-card__header-action">+ Создать →</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Тип</th><th>Заголовок</th><th>Автор</th><th>Дата</th><th></th></tr></thead>
          <tbody id="news-table">
            <tr>
              <td><span class="tag tag--blue">Новость</span></td>
              <td style="font-weight:600;color:var(--text);">Новые стандарты подачи блюд</td>
              <td>Смирнов В.</td>
              <td style="color:var(--text-tertiary);">18.11.2026</td>
              <td><button class="btn btn--ghost" style="padding:6px 14px;font-size:12px;">✓ Принять</button></td>
            </tr>
            <tr>
              <td><span class="tag tag--purple">Объявление</span></td>
              <td style="font-weight:600;color:var(--text);">Изменения в графике декабря</td>
              <td>HR-отдел</td>
              <td style="color:var(--text-tertiary);">17.11.2026</td>
              <td><button class="btn btn--ghost" style="padding:6px 14px;font-size:12px;">✓ Принять</button></td>
            </tr>
            <tr>
              <td><span class="tag tag--green">Событие</span></td>
              <td style="font-weight:600;color:var(--text);">Корпоратив по итогам года</td>
              <td>Администрация</td>
              <td style="color:var(--text-tertiary);">15.11.2026</td>
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
      <div class="b-card__header">
        <div class="b-card__header-title">Стандарты</div>
        <div class="b-card__header-action">+ Добавить →</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Заголовок</th><th>Группа</th><th>Статус</th></tr></thead>
          <tbody id="standards-table">
            <tr>
              <td style="font-weight:600;color:var(--text);">Пищевая безопасность</td>
              <td><span class="tag tag--purple">Общее</span></td>
              <td><span class="tag tag--green">Опубликован</span></td>
            </tr>
            <tr>
              <td style="font-weight:600;color:var(--text);">Работа на кассе</td>
              <td><span class="tag tag--blue">Касса</span></td>
              <td><span class="tag tag--green">Опубликован</span></td>
            </tr>
            <tr>
              <td style="font-weight:600;color:var(--text);">Сервис гостей</td>
              <td><span class="tag tag--purple">Общее</span></td>
              <td><span class="tag tag--green">Опубликован</span></td>
            </tr>
            <tr>
              <td style="font-weight:600;color:var(--text);">Приготовлениеwok-блюд</td>
              <td><span class="tag tag--amber">Кухня</span></td>
              <td><span class="tag tag--amber">Черновик</span></td>
            </tr>
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
      <div class="b-card__header">
        <div class="b-card__header-title">FAQ</div>
        <div class="b-card__header-action">+ Добавить →</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Вопрос</th><th>Категория</th><th>Ответ</th></tr></thead>
          <tbody id="faq-table">
            <tr>
              <td style="font-weight:600;color:var(--text);">Как заполнить медкнижку?</td>
              <td><span class="tag tag--blue">Медкнижки</span></td>
              <td style="color:var(--text-secondary);">Перейдите в раздел медкнижек...</td>
            </tr>
            <tr>
              <td style="font-weight:600;color:var(--text);">Как поставить табель?</td>
              <td><span class="tag tag--purple">Табель</span></td>
              <td style="color:var(--text-secondary);">Откройте табель за нужный месяц...</td>
            </tr>
            <tr>
              <td style="font-weight:600;color:var(--text);">Как отправить заявку на выплату?</td>
              <td><span class="tag tag--green">Выплаты</span></td>
              <td style="color:var(--text-secondary);">Перейдите в раздел выплат...</td>
            </tr>
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
      <div class="b-card__header">
        <div class="b-card__header-title">Рестораны</div>
        <div class="b-card__header-action">+ Добавить →</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Название</th><th>Адрес</th><th>Статус</th></tr></thead>
          <tbody id="restaurants-table">
            <tr>
              <td style="font-weight:600;color:var(--text);">Wokker Центральный</td>
              <td class="restaurant">ул. Ленина, 1</td>
              <td><span class="tag tag--green">Открыт</span></td>
            </tr>
            <tr>
              <td style="font-weight:600;color:var(--text);">Wokker Северный</td>
              <td class="restaurant">пр. Мира, 15</td>
              <td><span class="tag tag--green">Открыт</span></td>
            </tr>
            <tr>
              <td style="font-weight:600;color:var(--text);">Wokker Южный</td>
              <td class="restaurant">ул. Гагарина, 42</td>
              <td><span class="tag tag--amber">Ремонт</span></td>
            </tr>
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

// ═══ Card mouse tracking for glow effect ═══
document.addEventListener('mousemove', e => {
  const cards = document.querySelectorAll('.b-card');
  cards.forEach(card => {
    const rect = card.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;
    card.style.setProperty('--mx', x + '%');
    card.style.setProperty('--my', y + '%');
  });
});
