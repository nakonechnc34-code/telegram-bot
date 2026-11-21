/* ═══════════════════════════════════════════
   WOKKER ADMIN — NEUMORPHIC DASHBOARD (FULL CRUD)
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
  return res.json();
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

function openSidebar() { document.getElementById('sidebar').classList.add('sidebar--open'); overlay.classList.add('overlay--show'); document.body.style.overflow = 'hidden'; }
function closeSidebar() { document.getElementById('sidebar').classList.remove('sidebar--open'); overlay.classList.remove('overlay--show'); document.body.style.overflow = ''; }

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

// ═══ Modal ═══
function openModal(title, bodyHtml, footerHtml, opts) {
  opts = opts || {};
  $('modal-title').textContent = title;
  $('modal-body').innerHTML = bodyHtml;
  $('modal-footer').innerHTML = footerHtml || '';
  $('modal-box').className = 'modal' + (opts.wide ? ' wide' : '');
  $('modal-overlay').classList.add('show');
}
function closeModal() { $('modal-overlay').classList.remove('show'); }
$('modal-close')?.addEventListener('click', closeModal);
$('modal-overlay')?.addEventListener('click', e => { if (e.target === $('modal-overlay')) closeModal(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && $('modal-overlay')?.classList.contains('show')) closeModal();
});

// ═══ Change Password ═══
$('change-password-btn')?.addEventListener('click', () => {
  openModal('Сменить пароль', `
    <div class="form-group"><label>Текущий пароль</label><input class="form-input" id="cp-old" type="password"></div>
    <div class="form-group"><label>Новый пароль</label><input class="form-input" id="cp-new" type="password"><div class="form-hint">Минимум 8 символов</div></div>
    <div class="form-group"><label>Повторите</label><input class="form-input" id="cp-new2" type="password"></div>
    <div class="form-hint error" id="cp-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="cp-save">Сохранить</button>`);
  $('cp-save')?.addEventListener('click', async () => {
    const errEl = $('cp-error');
    errEl.textContent = '';
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

// ═══ Login ═══
function showLogin() {
  $('app').style.display = 'none';
  $('login-screen').style.display = 'flex';
  $('login-error').textContent = '';
  $('login-login').value = '';
  $('login-password').value = '';
  clearCache();
}

function showApp() {
  $('app').style.display = 'block';
  $('login-screen').style.display = 'none';
}

$('login-login')?.addEventListener('input', e => {
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

$('login-btn')?.addEventListener('click', doLogin);
$('login-password')?.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
$('login-login')?.addEventListener('keydown', e => { if (e.key === 'Enter') $('login-password')?.focus(); });

async function checkAdminAndLoad() {
  try {
    const res = await api('/api/admin/me', {});
    ME = res.profile;
    $('admin-name').textContent = ME.full_name || '—';
    $('admin-login').textContent = '@' + (ME.login || '');
    $('admin-role').textContent = ME.is_super_admin ? 'Супер-админ' : ME.is_hr ? 'HR' : 'Админ';
    $('admin-role').className = 'badge-role ' + (ME.is_super_admin ? 'super' : ME.is_hr ? 'hr' : 'regular');
    $('nav-admins').style.display = ME.is_super_admin ? 'block' : 'none';
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
  dashboard: 'Дашборд', users: 'Сотрудники', medbooks: 'Медкнижки',
  news: 'Новости', standards: 'Стандарты', certification: 'Сертификация', faq: 'FAQ',
  restaurants: 'Рестораны', positions: 'Должности', questions: 'Вопросы',
  admins: 'Администраторы', reports: 'Отчёты', audit: 'История',
};

function navigate(page) {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('nav-item--active', item.dataset.page === page);
  });
  $('page-title').textContent = PAGE_TITLES[page] || page;
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

// ═══ Refresh Counters ═══
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

// ═══ Avatar Gradients ═══
const GRADIENTS = [
  'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
  'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
  'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
  'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
];

function getAvatarGradient(index) {
  return GRADIENTS[index % GRADIENTS.length];
}

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
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/dashboard/summary', {}, 10000);
    const stats = data.stats || {};
    if ($('stat-active')) $('stat-active').textContent = stats.active || 0;
    if ($('stat-pending')) $('stat-pending').textContent = (stats.news_pending || 0) + (stats.standards_pending || 0);
    if ($('stat-medbooks')) $('stat-medbooks').textContent = stats.medbooks_alert || 0;
    if ($('stat-questions')) $('stat-questions').textContent = stats.questions_open || 0;

    // Реальные открытые вопросы
    if ($('dash-questions')) {
      const questions = (data.questions || []).slice(0, 5);
      $('dash-questions').innerHTML = questions.map(q => `
        <div class="activity__item">
          <div class="activity__icon activity__icon--accent">❓</div>
          <div class="activity__content">
            <div class="activity__text"><strong>${esc(q.full_name || 'Сотрудник')}</strong><br>${esc(q.text || '—')}</div>
            <div class="activity__time">${fmtDate(q.created_at, true)}</div>
          </div>
        </div>
      `).join('') || '<div class="loading">Нет открытых вопросов</div>';
    }

    // Новые сотрудники
    if ($('dash-new-users')) {
      const users = (data.users || []).slice(0, 5);
      $('dash-new-users').innerHTML = users.map((u, i) => `
        <div class="activity__item">
          <div class="avatar" style="background:${getAvatarGradient(i)};width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;font-weight:700;flex-shrink:0;">${(u.full_name||'?').charAt(0)}</div>
          <div class="activity__content">
            <div class="activity__text">${esc(u.full_name||'—')}</div>
            <div class="activity__time">${esc(u.position||'')} · ${fmtDate(u.created_at)}</div>
          </div>
        </div>
      `).join('') || '<div class="loading">Нет новых сотрудников</div>';
    }
  } catch (e) { console.error('Dashboard error:', e); }
}

// ═══ USERS (FULL CRUD) ═══
async function loadUsers() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Сотрудники</div>
        <div style="display:flex;gap:8px;">
          <button class="btn btn--primary" onclick="openAddUser()">+ Добавить</button>
        </div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Сотрудник</th><th>Позиция</th><th>Ресторан</th><th>Статус</th><th>Действия</th></tr></thead>
          <tbody id="users-table"><tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/users', { search: '', fired: false });
    const users = data.users || [];
    const tbody = $('users-table');
    tbody.innerHTML = users.map((u, i) => `
      <tr>
        <td><div class="name-cell"><div class="avatar" style="background:${getAvatarGradient(i)}">${(u.full_name||'?').charAt(0).toUpperCase()}</div>${esc(u.full_name||'—')}</div></td>
        <td>${esc(u.position||'—')}</td>
        <td>${esc(u.restaurant_name||'—')}</td>
        <td><span class="tag ${u.is_fired ? 'tag--amber' : 'tag--green'}">${u.is_fired ? 'Уволен' : 'Активен'}</span></td>
        <td style="display:flex;gap:4px;">
          ${!u.is_fired && hasPerm('users_edit') ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="openEditUser(${u.user_id})">✏️</button>` : ''}
          ${!u.is_fired && !u.is_super_admin && hasPerm('users_fire') ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="fireUser(${u.user_id},'${esc(u.full_name||'')}')" ${u.is_admin && !isSuperAdmin() ? 'disabled' : ''}>🔥</button>` : ''}
          ${u.is_fired && hasPerm('users_fire') ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--green);" onclick="restoreUser(${u.user_id})">♻️</button>` : ''}
        </td>
      </tr>
    `).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Нет сотрудников</td></tr>';
  } catch (e) {
    $('users-table').innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function openAddUser() {
  // Получаем рестораны для select
  let restaurants = [];
  try {
    const rData = await api('/api/admin/restaurants', {});
    restaurants = rData.restaurants || [];
  } catch(e) {}
  openModal('Добавить сотрудника', `
    <div class="form-group"><label>ФИО</label><input class="form-input" id="user-full-name"></div>
    <div class="form-group"><label>Пароль</label><input class="form-input" id="user-password" type="password"></div>
    <div class="form-group"><label>Телефон</label><input class="form-input" id="user-phone"></div>
    <div class="form-group"><label>Должность</label><input class="form-input" id="user-position"></div>
    <div class="form-group"><label>Ресторан</label><select class="form-input" id="user-restaurant">${restaurants.map(r => `<option value="${esc(r.key)}">${esc(r.name)}</option>`).join('')}</select></div>
    <div class="form-hint" id="user-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="user-save">Создать</button>`);
  $('user-save').addEventListener('click', async () => {
    const errEl = $('user-error');
    errEl.textContent = '';
    const fn = $('user-full-name').value.trim();
    const pw = $('user-password').value;
    if (!fn || !pw) { errEl.textContent = 'Заполните ФИО и пароль'; return; }
    try {
      await api('/api/admin/user/create', {
        full_name: fn, password: pw, phone: $('user-phone').value.trim(),
        position: $('user-position').value.trim(), restaurant_key: $('user-restaurant').value
      });
      toast('Сотрудник создан', 'success'); closeModal(); navigate('users');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function openEditUser(uid) {
  let user, restaurants;
  try {
    const uData = await api('/api/admin/user/get', { user_id: uid });
    user = uData.user;
    const rData = await api('/api/admin/restaurants', {});
    restaurants = rData.restaurants || [];
  } catch (e) { toast('Ошибка: ' + e.message, 'error'); return; }
  openModal('Редактировать: ' + (user.full_name||''), `
    <div class="form-group"><label>ФИО</label><input class="form-input" id="ed-full-name" value="${esc(user.full_name||'')}"></div>
    <div class="form-group"><label>Телефон</label><input class="form-input" id="ed-phone" value="${esc(user.phone||'')}"></div>
    <div class="form-group"><label>Должность</label><input class="form-input" id="ed-position" value="${esc(user.position||'')}"></div>
    <div class="form-group"><label>Ресторан</label><select class="form-input" id="ed-restaurant">${restaurants.map(r => `<option value="${esc(r.key)}" ${r.key === user.restaurant_key ? 'selected' : ''}>${esc(r.name)}</option>`).join('')}</select></div>
    <div class="form-group"><label>Новый пароль (оставьте пустым если не нужно менять)</label><input class="form-input" id="ed-password" type="password"></div>
    <div class="form-hint" id="ed-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="ed-save">Сохранить</button>`);
  $('ed-save').addEventListener('click', async () => {
    const errEl = $('ed-error');
    errEl.textContent = '';
    const updates = {};
    const fn = $('ed-full-name').value.trim();
    if (fn) updates.full_name = fn;
    const phone = $('ed-phone').value.trim();
    if (phone) updates.phone = phone;
    const pos = $('ed-position').value.trim();
    if (pos) updates.position = pos;
    updates.restaurant_key = $('ed-restaurant').value;
    const pw = $('ed-password').value;
    if (pw) updates.password = pw;
    try {
      await api('/api/admin/user/update', { user_id: uid, updates });
      toast('Сохранено', 'success'); closeModal(); navigate('users');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function fireUser(uid, name) {
  if (!confirm(`Уволить ${name}?`)) return;
  try {
    await api('/api/admin/user/fire', { user_id: uid });
    toast('Сотрудник уволен', 'success'); navigate('users');
  } catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

async function restoreUser(uid) {
  if (!confirm('Восстановить сотрудника?')) return;
  try {
    await api('/api/admin/user/restore', { user_id: uid });
    toast('Сотрудник восстановлен', 'success'); navigate('users');
  } catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══ MEDBOOKS ═══
async function loadMedbooks() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Медкнижки</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Сотрудник</th><th>Позиция</th><th>Ресторан</th><th>Статус</th><th>Действия</th></tr></thead>
          <tbody id="medbooks-table"><tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/medbooks', {});
    const users = data.users || [];
    const tbody = $('medbooks-table');
    tbody.innerHTML = users.map((u, i) => {
      const statusTag = u.medbook_status === 'ok' ? 'tag--green' : u.medbook_status === 'expiring' ? 'tag--amber' : 'tag--pink';
      const statusText = u.medbook_status === 'ok' ? 'OK' : u.medbook_status === 'expiring' ? 'Истекает' : 'Не заполнена';
      return `
        <tr>
          <td><div class="name-cell"><div class="avatar" style="background:${getAvatarGradient(i)}">${(u.full_name||'?').charAt(0).toUpperCase()}</div>${esc(u.full_name||'—')}</div></td>
          <td>${esc(u.position||'—')}</td>
          <td>${esc(u.restaurant_name||'—')}</td>
          <td><span class="tag ${statusTag}">${statusText}</span></td>
          <td><button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="openEditMedbook(${u.user_id})">✏️</button></td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Нет сотрудников</td></tr>';
  } catch (e) {
    $('medbooks-table').innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function openEditMedbook(uid) {
  let user, medbook, doctors = [], tests = [], vaccines = [];
  try {
    const d = await api('/api/admin/medbook/get', { user_id: uid });
    user = d.user; medbook = d.medbook || {}; doctors = d.doctors || []; tests = d.tests || []; vaccines = d.vaccines || [];
  } catch (e) { toast('Ошибка: ' + e.message, 'error'); return; }
  openModal('Медкнижка: ' + (user.full_name||''), `
    <div style="margin-bottom:16px;"><strong>${esc(user.full_name||'—')}</strong> — ${esc(user.position||'')}</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;">
      <div>
        <h4 style="margin-bottom:8px;color:var(--purple);">Врачи</h4>
        ${doctors.map(d => `<div class="form-group"><label>${esc(d.name)}</label><input class="form-input med-date" data-type="doctor" data-id="${d.id}" value="${(medbook.doctors||{})[d.id]||''}" placeholder="ДД.ММ.ГГГГ"></div>`).join('')}
      </div>
      <div>
        <h4 style="margin-bottom:8px;color:var(--blue);">Анализы</h4>
        ${tests.map(t => `<div class="form-group"><label>${esc(t.name)}</label><input class="form-input med-date" data-type="test" data-id="${t.id}" value="${(medbook.tests||{})[t.id]||''}" placeholder="ДД.ММ.ГГГГ"></div>`).join('')}
      </div>
      <div>
        <h4 style="margin-bottom:8px;color:var(--green);">Прививки</h4>
        ${vaccines.map(v => `<div class="form-group"><label>${esc(v.name)}</label><input class="form-input med-date" data-type="vaccine" data-id="${v.id}" value="${(medbook.vaccines||{})[v.id]||''}" placeholder="ДД.ММ.ГГГГ"></div>`).join('')}
      </div>
    </div>
    <div class="form-hint" id="med-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="med-save">Сохранить</button>`);
  $('med-save').addEventListener('click', async () => {
    const errEl = $('med-error');
    errEl.textContent = '';
    const mb = { doctors: {}, tests: {}, vaccines: {} };
    document.querySelectorAll('.med-date').forEach(inp => {
      const type = inp.dataset.type, id = inp.dataset.id, val = inp.value.trim();
      if (val) { if (!mb[type]) mb[type] = {}; mb[type][id] = val; }
    });
    try {
      await api('/api/admin/medbook/save', { user_id: uid, medbook: mb });
      toast('Медкнижка сохранена', 'success'); closeModal(); navigate('medbooks');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

// ═══ NEWS (FULL CRUD) ═══
async function loadNews() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Новости</div>
        ${hasPerm('news_write') || hasPerm('news_suggest') ? `<button class="btn btn--primary" onclick="openAddNews()">+ Создать</button>` : ''}
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Тип</th><th>Заголовок</th><th>Автор</th><th>Дата</th><th>Статус</th><th>Действия</th></tr></thead>
          <tbody id="news-table"><tr><td colspan="6" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/news', {});
    const news = data.news || [];
    const tbody = $('news-table');
    tbody.innerHTML = news.map(n => {
      const levelTag = n.level === 'announcement' ? 'tag--purple' : n.level === 'event' ? 'tag--green' : 'tag--blue';
      const statusTag = n.status === 'published' ? 'tag--green' : n.status === 'scheduled' ? 'tag--amber' : 'tag--amber';
      const statusText = n.status === 'published' ? 'Опубликована' : n.status === 'scheduled' ? 'Запланирована' : 'На модерации';
      let actions = '';
      if (n.status === 'pending' && canPublish()) {
        actions += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--green);" onclick="approveNews(${n.id})">✓</button>`;
        actions += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="rejectNews(${n.id})">✕</button>`;
      }
      if (hasPerm('news_edit')) {
        actions += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="deleteNews(${n.id})">🗑️</button>`;
      }
      return `
        <tr>
          <td><span class="tag ${levelTag}">${n.level||'normal'}</span></td>
          <td style="font-weight:600;color:var(--text);max-width:300px;overflow:hidden;text-overflow:ellipsis;">${esc(n.title||'—')}</td>
          <td>${esc(n.proposed_by||'—')}</td>
          <td style="color:var(--text-terc);">${fmtDate(n.created_at)}</td>
          <td><span class="tag ${statusTag}">${statusText}</span></td>
          <td style="display:flex;gap:4px;">${actions}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--text-terc);padding:40px;">Нет новостей</td></tr>';
  } catch (e) {
    $('news-table').innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function openAddNews() {
  openModal('Создать новость', `
    <div class="form-group"><label>Заголовок</label><input class="form-input" id="news-title" maxlength="200"></div>
    <div class="form-group"><label>Текст</label><textarea class="form-textarea" id="news-body" rows="6"></textarea></div>
    <div class="form-group"><label>Уровень</label><select class="form-input" id="news-level"><option value="normal">Обычная</option><option value="announcement">Объявление</option><option value="event">Событие</option></select></div>
    <div class="form-group"><label>Intent</label><select class="form-input" id="news-intent"><option value="suggest">Предложить</option><option value="publish" ${canPublish()?'selected':''}>Опубликовать</option></select></div>
    <div class="form-hint" id="news-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="news-save">Создать</button>`);
  $('news-save').addEventListener('click', async () => {
    const errEl = $('news-error');
    errEl.textContent = '';
    const title = $('news-title').value.trim();
    const body = $('news-body').value.trim();
    if (!title || !body) { errEl.textContent = 'Заполните заголовок и текст'; return; }
    try {
      await api('/api/admin/news/add', {
        title, body,
        level: $('news-level').value,
        intent: $('news-intent').value,
      });
      toast('Новость создана', 'success'); closeModal(); navigate('news');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function approveNews(id) {
  try { await api('/api/admin/news/approve', { id }); toast('Одобрено', 'success'); navigate('news'); }
  catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

async function rejectNews(id) {
  if (!confirm('Отклонить новость?')) return;
  try { await api('/api/admin/news/reject', { id }); toast('Отклонено', 'success'); navigate('news'); }
  catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

async function deleteNews(id) {
  if (!confirm('Удалить новость?')) return;
  try { await api('/api/admin/news/delete', { id }); toast('Удалено', 'success'); navigate('news'); }
  catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══ STANDARDS (FULL CRUD) ═══
async function loadStandards() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Стандарты</div>
        ${hasPerm('standards_edit') ? `<button class="btn btn--primary" onclick="openAddStandard()">+ Добавить</button>` : ''}
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Заголовок</th><th>Группа</th><th>Статус</th><th>Действия</th></tr></thead>
          <tbody id="standards-table"><tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/standards', {});
    const standards = data.standards || [];
    const tbody = $('standards-table');
    tbody.innerHTML = standards.map(s => {
      const statusTag = s.status === 'published' ? 'tag--green' : 'tag--amber';
      const statusText = s.status === 'published' ? 'Опубликован' : 'На модерации';
      let actions = '';
      if (s.status === 'pending' && canPublish()) {
        actions += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--green);" onclick="approveStandard(${s.id})">✓</button>`;
        actions += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="rejectStandard(${s.id})">✕</button>`;
      }
      if (hasPerm('standards_edit')) {
        actions += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="deleteStandard(${s.id})">🗑️</button>`;
      }
      return `
        <tr>
          <td style="font-weight:600;color:var(--text);">${esc(s.title||'—')}</td>
          <td><span class="tag tag--purple">${esc(s.group_name||'Общее')}</span></td>
          <td><span class="tag ${statusTag}">${statusText}</span></td>
          <td style="display:flex;gap:4px;">${actions}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Нет стандартов</td></tr>';
  } catch (e) {
    $('standards-table').innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function openAddStandard() {
  openModal('Добавить стандарт', `
    <div class="form-group"><label>Заголовок</label><input class="form-input" id="std-title"></div>
    <div class="form-group"><label>Текст</label><textarea class="form-textarea" id="std-body" rows="6"></textarea></div>
    <div class="form-group"><label>Группа</label><select class="form-input" id="std-group"><option>Пищевая Безопасность</option><option>Касса</option><option>Горячий цех</option><option>Холодный цех</option><option>Общее</option></select></div>
    <div class="form-hint" id="std-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="std-save">Создать</button>`);
  $('std-save').addEventListener('click', async () => {
    const errEl = $('std-error');
    errEl.textContent = '';
    const title = $('std-title').value.trim();
    const body = $('std-body').value.trim();
    if (!title || !body) { errEl.textContent = 'Заполните все поля'; return; }
    try {
      await api('/api/admin/standard/add', { title, body, group_name: $('std-group').value });
      toast('Стандарт создан', 'success'); closeModal(); navigate('standards');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function approveStandard(id) {
  try { await api('/api/admin/standard/approve', { id }); toast('Одобрено', 'success'); navigate('standards'); }
  catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

async function rejectStandard(id) {
  if (!confirm('Отклонить стандарт?')) return;
  try { await api('/api/admin/standard/reject', { id }); toast('Отклонено', 'success'); navigate('standards'); }
  catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

async function deleteStandard(id) {
  if (!confirm('Удалить стандарт?')) return;
  try { await api('/api/admin/standard/delete', { id }); toast('Удалено', 'success'); navigate('standards'); }
  catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══ FAQ (FULL CRUD) ═══
async function loadFaq() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">FAQ</div>
        ${hasPerm('faq_edit') ? `<button class="btn btn--primary" onclick="openAddFaq()">+ Добавить</button>` : ''}
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Вопрос</th><th>Категория</th><th>Ответ</th><th>Действия</th></tr></thead>
          <tbody id="faq-table"><tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/faq', {});
    const items = data.faq || [];
    const tbody = $('faq-table');
    tbody.innerHTML = items.map(f => `
      <tr>
        <td style="font-weight:600;color:var(--text);max-width:200px;" title="${esc(f.question||'—')}">${esc(f.question||'—')}</td>
        <td><span class="tag tag--blue">${esc(f.category||'—')}</span></td>
        <td style="color:var(--text-sec);max-width:200px;" title="${esc(f.answer||'—')}">${esc(f.answer||'—')}</td>
        <td style="display:flex;gap:4px;">
          ${hasPerm('faq_edit') ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="editFaq(${f.id},'${esc(f.question||'')}','${esc(f.answer||'')}')">✏️</button>` : ''}
          ${hasPerm('faq_edit') ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="deleteFaq(${f.id})">🗑️</button>` : ''}
        </td>
      </tr>
    `).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Нет вопросов</td></tr>';
  } catch (e) {
    $('faq-table').innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function openAddFaq() {
  openModal('Добавить FAQ', `
    <div class="form-group"><label>Вопрос</label><input class="form-input" id="faq-question" maxlength="500"></div>
    <div class="form-group"><label>Ответ</label><textarea class="form-textarea" id="faq-answer" rows="4" maxlength="2000"></textarea></div>
    <div class="form-hint" id="faq-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="faq-save">Добавить</button>`);
  $('faq-save').addEventListener('click', async () => {
    const errEl = $('faq-error');
    errEl.textContent = '';
    const q = $('faq-question').value.trim();
    const a = $('faq-answer').value.trim();
    if (!q || !a) { errEl.textContent = 'Заполните все поля'; return; }
    try {
      await api('/api/admin/faq/add', { question: q, answer: a });
      toast('Добавлено', 'success'); closeModal(); navigate('faq');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function editFaq(id, question, answer) {
  openModal('Редактировать FAQ', `
    <div class="form-group"><label>Вопрос</label><input class="form-input" id="ed-faq-question" value="${esc(question)}" maxlength="500"></div>
    <div class="form-group"><label>Ответ</label><textarea class="form-textarea" id="ed-faq-answer" rows="4" maxlength="2000">${esc(answer)}</textarea></div>
    <div class="form-hint" id="ed-faq-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="ed-faq-save">Сохранить</button>`);
  $('ed-faq-save').addEventListener('click', async () => {
    const errEl = $('ed-faq-error');
    errEl.textContent = '';
    const q = $('ed-faq-question').value.trim();
    const a = $('ed-faq-answer').value.trim();
    if (!q || !a) { errEl.textContent = 'Заполните все поля'; return; }
    try {
      await api('/api/admin/faq/update', { id, field: 'question', value: q });
      await api('/api/admin/faq/update', { id, field: 'answer', value: a });
      toast('Сохранено', 'success'); closeModal(); navigate('faq');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function deleteFaq(id) {
  if (!confirm('Удалить FAQ?')) return;
  try { await api('/api/admin/faq/delete', { id }); toast('Удалено', 'success'); navigate('faq'); }
  catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══ RESTAURANTS (FULL CRUD) ═══
async function loadRestaurants() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Рестораны</div>
        ${hasPerm('restaurant_create') ? `<button class="btn btn--primary" onclick="openAddRestaurant()">+ Добавить</button>` : ''}
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Название</th><th>Адрес</th><th>ТУ</th><th>Статус</th><th>Действия</th></tr></thead>
          <tbody id="restaurants-table"><tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/restaurants', {});
    const restaurants = data.restaurants || [];
    const tuCandidates = data.tu_candidates || [];
    const tbody = $('restaurants-table');
    tbody.innerHTML = restaurants.map((r, i) => {
      const statusTag = r.force_status === 'open' ? 'tag--green' : 'tag--amber';
      const statusText = r.force_status === 'open' ? 'Открыт' : (r.force_status || 'Открыт');
      let actions = '';
      if (hasPerm('restaurant_edit')) {
        actions += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="editRestaurant('${esc(r.key)}')">✏️</button>`;
      }
      if (hasPerm('restaurant_edit')) {
        actions += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--amber);" onclick="changeRestaurantStatus('${esc(r.key)}','${esc(r.force_status||'open')}')">🔄</button>`;
      }
      if (hasPerm('restaurant_tu')) {
        actions += `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="assignTU('${esc(r.key)}')">👤</button>`;
      }
      return `
        <tr>
          <td style="font-weight:600;color:var(--text);">${esc(r.name||'—')}</td>
          <td>${esc(r.address||'—')}</td>
          <td>${esc(r.territory_manager_name||'—')}</td>
          <td><span class="tag ${statusTag}">${statusText}</span></td>
          <td style="display:flex;gap:4px;">${actions}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Нет ресторанов</td></tr>';
  } catch (e) {
    $('restaurants-table').innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function openAddRestaurant() {
  openModal('Добавить ресторан', `
    <div class="form-group"><label>Ключ (лат, без пробелов)</label><input class="form-input" id="rest-key" maxlength="50"></div>
    <div class="form-group"><label>Название</label><input class="form-input" id="rest-name" maxlength="100"></div>
    <div class="form-group"><label>Адрес</label><input class="form-input" id="rest-address"></div>
    <div class="form-group"><label>Телефон</label><input class="form-input" id="rest-phone"></div>
    <div class="form-hint" id="rest-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="rest-save">Создать</button>`);
  $('rest-save').addEventListener('click', async () => {
    const errEl = $('rest-error');
    errEl.textContent = '';
    const key = $('rest-key').value.trim().toLowerCase().replace(/\s/g, '_');
    const name = $('rest-name').value.trim();
    if (!key || !name) { errEl.textContent = 'Заполните ключ и название'; return; }
    try {
      await api('/api/admin/restaurant/add', { key, name, address: $('rest-address').value, phone: $('rest-phone').value });
      toast('Ресторан создан', 'success'); closeModal(); navigate('restaurants');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function editRestaurant(key) {
  let r;
  try {
    const data = await api('/api/admin/restaurants', {});
    r = (data.restaurants || []).find(x => x.key === key);
  } catch (e) { return; }
  if (!r) return;
  openModal('Редактировать: ' + r.name, `
    <div class="form-group"><label>Название</label><input class="form-input" id="ed-rest-name" value="${esc(r.name)}"></div>
    <div class="form-group"><label>Адрес</label><input class="form-input" id="ed-rest-address" value="${esc(r.address||'')}"></div>
    <div class="form-group"><label>Телефон</label><input class="form-input" id="ed-rest-phone" value="${esc(r.phone||'')}"></div>
    <div class="form-hint" id="ed-rest-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="ed-rest-save">Сохранить</button>`);
  $('ed-rest-save').addEventListener('click', async () => {
    const errEl = $('ed-rest-error');
    errEl.textContent = '';
    try {
      await api('/api/admin/restaurant/update', { key, updates: {
        name: $('ed-rest-name').value.trim(),
        address: $('ed-rest-address').value.trim(),
        phone: $('ed-rest-phone').value.trim(),
      }});
      toast('Сохранено', 'success'); closeModal(); navigate('restaurants');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function assignTU(key) {
  let tuCandidates;
  try {
    const data = await api('/api/admin/restaurants', {});
    tuCandidates = data.tu_candidates || [];
  } catch (e) { return; }
  openModal('Назначить ТУ', `
    <div class="form-group"><label>Территориальный менеджер</label><select class="form-input" id="tu-select"><option value="">— Не назначен —</option>${tuCandidates.map(t => `<option value="${t.user_id}">${esc(t.full_name)}</option>`).join('')}</select></div>
    <div class="form-hint" id="tu-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="tu-save">Назначить</button>`);
  $('tu-save').addEventListener('click', async () => {
    const errEl = $('tu-error');
    errEl.textContent = '';
    const tu = $('tu-select').value;
    try {
      await api('/api/admin/restaurant/tu', { key, territory_manager_id: tu || null });
      toast('ТУ назначен', 'success'); closeModal(); navigate('restaurants');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function changeRestaurantStatus(key, currentStatus) {
  const newStatus = currentStatus === 'open' ? 'closed' : 'open';
  if (!confirm(`Переключить статус на ${newStatus === 'open' ? 'Открыт' : 'Закрыт'}?`)) return;
  try {
    await api('/api/admin/restaurant/status', { key, status: newStatus });
    toast('Статус обновлён', 'success'); navigate('restaurants');
  } catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══ CERTIFICATION (FULL CRUD) ═══
async function loadCertification() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Сертификация</div>
        ${hasPerm('certification_edit') ? `<button class="btn btn--primary" onclick="openAddCert()">+ Добавить вопрос</button>` : ''}
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Вопрос</th><th>Правильный ответ</th><th>Действия</th></tr></thead>
          <tbody id="cert-table"><tr><td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/certification', {});
    const questions = data.questions || [];
    const tbody = $('cert-table');
    tbody.innerHTML = questions.map(q => {
      const correct = {a:'A',b:'B',c:'C',d:'D'};
      return `
        <tr>
          <td style="color:var(--text);max-width:400px;">${esc(q.question||'—')}</td>
          <td><span class="tag tag--green">${correct[q.correct_option?.toLowerCase()]||'—'}</span></td>
          <td>${hasPerm('certification_edit') ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="deleteCert(${q.id})">🗑️</button>` : ''}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;">Нет вопросов</td></tr>';
  } catch (e) {
    $('cert-table').innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function openAddCert() {
  openModal('Добавить вопрос сертификации', `
    <div class="form-group"><label>Вопрос</label><textarea class="form-textarea" id="cert-question" rows="3"></textarea></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
      <div class="form-group"><label>Вариант A</label><input class="form-input" id="cert-a"></div>
      <div class="form-group"><label>Вариант B</label><input class="form-input" id="cert-b"></div>
      <div class="form-group"><label>Вариант C</label><input class="form-input" id="cert-c"></div>
      <div class="form-group"><label>Вариант D</label><input class="form-input" id="cert-d"></div>
    </div>
    <div class="form-group"><label>Правильный ответ</label><select class="form-input" id="cert-correct"><option value="a">A</option><option value="b">B</option><option value="c">C</option><option value="d">D</option></select></div>
    <div class="form-hint" id="cert-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="cert-save">Добавить</button>`);
  $('cert-save').addEventListener('click', async () => {
    const errEl = $('cert-error');
    errEl.textContent = '';
    const q = $('cert-question').value.trim();
    const a = $('cert-a').value.trim(), b = $('cert-b').value.trim(), c = $('cert-c').value.trim(), d = $('cert-d').value.trim();
    if (!q || !a || !b || !c || !d) { errEl.textContent = 'Заполните все поля'; return; }
    try {
      await api('/api/admin/certification/add', { question: q, option_a: a, option_b: b, option_c: c, option_d: d, correct_option: $('cert-correct').value });
      toast('Добавлено', 'success'); closeModal(); navigate('certification');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function deleteCert(id) {
  if (!confirm('Удалить вопрос?')) return;
  try { await api('/api/admin/certification/delete', { id }); toast('Удалено', 'success'); navigate('certification'); }
  catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══ POSITIONS (FULL CRUD) ═══
async function loadPositions() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Должности</div>
        ${hasPerm('positions_edit') ? `<button class="btn btn--primary" onclick="openAddPosition()">+ Добавить</button>` : ''}
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Название</th><th>Ставка</th><th>Статус</th><th>Действия</th></tr></thead>
          <tbody id="positions-table"><tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/positions', {});
    const positions = data.positions || [];
    const tbody = $('positions-table');
    tbody.innerHTML = positions.map(p => `
      <tr>
        <td style="font-weight:600;color:var(--text);">${esc(p.name||'—')}</td>
        <td>${p.rate!=null ? '₽'+p.rate : '—'}</td>
        <td><span class="tag ${p.is_archived ? 'tag--amber' : 'tag--green'}">${p.is_archived ? 'Архив' : 'Активна'}</span></td>
        <td>${hasPerm('positions_edit') && !p.is_archived ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="archivePosition(${p.id})">🗑️</button>` : ''}</td>
      </tr>
    `).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Нет должностей</td></tr>';
  } catch (e) {
    $('positions-table').innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function openAddPosition() {
  openModal('Добавить должность', `
    <div class="form-group"><label>Название</label><input class="form-input" id="pos-name" maxlength="100"></div>
    <div class="form-hint" id="pos-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="pos-save">Добавить</button>`);
  $('pos-save').addEventListener('click', async () => {
    const errEl = $('pos-error');
    errEl.textContent = '';
    const name = $('pos-name').value.trim();
    if (!name) { errEl.textContent = 'Введите название'; return; }
    try {
      await api('/api/admin/position/add', { name });
      toast('Добавлено', 'success'); closeModal(); navigate('positions');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function archivePosition(id) {
  if (!confirm('Архивировать должность?')) return;
  try { await api('/api/admin/position/archive', { id }); toast('Архивировано', 'success'); navigate('positions'); }
  catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══ QUESTIONS (ANSWER) ═══
async function loadQuestions() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Вопросы от сотрудников</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>От</th><th>Вопрос</th><th>Дата</th><th>Статус</th><th>Действия</th></tr></thead>
          <tbody id="questions-table"><tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/questions', {});
    const questions = data.questions || [];
    const tbody = $('questions-table');
    tbody.innerHTML = questions.map(q => {
      const statusTag = q.replied ? 'tag--green' : 'tag--amber';
      const statusText = q.replied ? 'Ответен' : 'Ожидает';
      let actions = '';
      if (!q.replied && hasPerm('questions_reply')) {
        actions += `<button class="btn btn--primary" style="padding:4px 8px;font-size:11px;" onclick="replyQuestion(${q.id})">Ответить</button>`;
      }
      return `
        <tr>
          <td>${esc(q.full_name||'—')}</td>
          <td style="color:var(--text);">${esc(q.text||'—')}</td>
          <td style="color:var(--text-terc);">${fmtDate(q.created_at)}</td>
          <td><span class="tag ${statusTag}">${statusText}</span></td>
          <td>${actions}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Нет вопросов</td></tr>';
  } catch (e) {
    $('questions-table').innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function replyQuestion(qid) {
  openModal('Ответить на вопрос', `
    <div class="form-group"><label>Ваш ответ</label><textarea class="form-textarea" id="reply-text" rows="4" maxlength="2000"></textarea></div>
    <div class="form-hint" id="reply-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="reply-save">Отправить</button>`);
  $('reply-save').addEventListener('click', async () => {
    const errEl = $('reply-error');
    errEl.textContent = '';
    const text = $('reply-text').value.trim();
    if (!text) { errEl.textContent = 'Введите ответ'; return; }
    try {
      await api('/api/admin/question/reply', { id: qid, text });
      toast('Ответ отправлен', 'success'); closeModal(); navigate('questions');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

// ═══ ADMINS (PERMISSIONS) ═══
async function loadAdmins() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Администраторы</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Логин</th><th>Имя</th><th>Позиция</th><th>Роль</th><th>Действия</th></tr></thead>
          <tbody id="admins-table"><tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/admins', {});
    const admins = data.admins || [];
    const tbody = $('admins-table');
    tbody.innerHTML = admins.map(a => {
      const role = a.is_super_admin ? 'tag--purple' : 'tag--blue';
      const roleText = a.is_super_admin ? 'Супер-админ' : 'Админ';
      let actions = '';
      if (isSuperAdmin() && !a.is_super_admin) {
        actions += `<button class="btn btn--primary" style="padding:4px 8px;font-size:11px;" onclick="openSetPerms(${a.user_id},'${esc(a.login||'')}')">🔑 Права</button>`;
      }
      return `
        <tr>
          <td style="font-weight:600;">${esc(a.login||'—')}</td>
          <td>${esc(a.full_name||'—')}</td>
          <td>${esc(a.position||'—')}</td>
          <td><span class="tag ${role}">${roleText}</span></td>
          <td>${actions}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Нет админов</td></tr>';
  } catch (e) {
    $('admins-table').innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function openSetPerms(uid, login) {
  openModal('Управление правами: ' + login, `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px;" id="perm-checkboxes">
      ${['users_create','users_edit','users_fire','medbook_edit','restaurant_create','restaurant_edit','restaurant_tu','news_write','news_edit','faq_edit','positions_edit','questions_reply','certification_edit'].map(p => `
        <label style="display:flex;align-items:center;gap:8px;padding:8px;background:var(--bg-card);border-radius:8px;cursor:pointer;">
          <input type="checkbox" value="${p}"> <span style="font-size:13px;">${p.replace(/_/g,' ')}</span>
        </label>
      `).join('')}
    </div>
    <div class="form-hint" id="perms-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="perms-save">Сохранить</button>`);
  $('perms-save').addEventListener('click', async () => {
    const errEl = $('perms-error');
    errEl.textContent = '';
    const permissions = {};
    $('perm-checkboxes').querySelectorAll('input:checked').forEach(cb => { permissions[cb.value] = true; });
    try {
      await api('/api/admin/set-permissions', { user_id: uid, permissions });
      toast('Права обновлены', 'success'); closeModal(); navigate('admins');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

// ═══ REPORTS ═══
async function loadReports() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header"><div class="neu-card__header-title">Отчёты по персоналу</div></div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Всего</th><th>Активных</th><th>Уволено</th><th>Новые (7д)</th><th>Вопросы</th><th>Новости на модерации</th><th>Стандарты на модерации</th></tr></thead>
          <tbody id="reports-body"><tr><td colspan="7" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/reports', {});
    const r = data.report || {};
    $('reports-body').innerHTML = `
      <tr>
        <td style="font-weight:700;font-size:18px;">${r.total||0}</td>
        <td style="font-weight:700;color:var(--green);font-size:18px;">${r.active||0}</td>
        <td style="font-weight:700;color:var(--amber);font-size:18px;">${r.fired||0}</td>
        <td>${r.new7||0}</td>
        <td>${r.questions_open||0}</td>
        <td>${r.news_pending||0}</td>
        <td>${r.standards_pending||0}</td>
      </tr>
    `;
  } catch (e) {
    $('reports-body').innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ AUDIT ═══
async function loadAudit() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header"><div class="neu-card__header-title">История действий</div></div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Дата</th><th>Админ</th><th>Действие</th><th>Объект</th></tr></thead>
          <tbody id="audit-table"><tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/audit', {});
    const logs = data.audit || [];
    const tbody = $('audit-table');
    tbody.innerHTML = logs.slice(0, 50).map(a => `
      <tr>
        <td style="color:var(--text-terc);font-size:12px;">${fmtDate(a.created_at, true)}</td>
        <td>${esc(a.admin_full_name||'—')}</td>
        <td><span class="tag tag--purple">${esc(a.action||'—')}</span></td>
        <td style="color:var(--text-sec);">${esc(a.details||'—')}</td>
      </tr>
    `).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Нет записей</td></tr>';
  } catch (e) {
    $('audit-table').innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ CITIZENSHIPS ═══
async function loadCitizenships() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Гражданства</div>
        ${hasPerm('citizenships_edit') ? `<button class="btn btn--primary" onclick="openAddCitizenship()">+ Добавить</button>` : ''}
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Название</th><th>Действия</th></tr></thead>
          <tbody id="citizenships-table"><tr><td colspan="2" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await cachedApi('/api/admin/citizenships', {});
    const items = data.citizenships || [];
    const tbody = $('citizenships-table');
    tbody.innerHTML = items.map(c => `
      <tr>
        <td style="font-weight:600;color:var(--text);">${esc(c.name||'—')}</td>
        <td>
          ${hasPerm('citizenships_edit') ? `<button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="deleteCitizenship(${c.id})">🗑️</button>` : ''}
        </td>
      </tr>
    `).join('') || '<tr><td colspan="2" style="text-align:center;color:var(--text-terc);padding:40px;">Нет записей</td></tr>';
  } catch (e) {
    $('citizenships-table').innerHTML = `<tr><td colspan="2" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function openAddCitizenship() {
  openModal('Добавить гражданство', `
    <div class="form-group"><label>Название</label><input class="form-input" id="cit-name" maxlength="50"></div>
    <div class="form-hint" id="cit-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="cit-save">Добавить</button>`);
  $('cit-save').addEventListener('click', async () => {
    const errEl = $('cit-error');
    errEl.textContent = '';
    const name = $('cit-name').value.trim();
    if (!name) { errEl.textContent = 'Введите название'; return; }
    try {
      await api('/api/admin/citizenship/add', { name });
      toast('Добавлено', 'success'); closeModal(); navigate('citizenships');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function deleteCitizenship(id) {
  if (!confirm('Удалить гражданство?')) return;
  try { await api('/api/admin/citizenship/delete', { id }); toast('Удалено', 'success'); navigate('citizenships'); }
  catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══ MEDBOOK DIRECTORIES ═══
async function loadMedbookDirs() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Справочники медкнижки</div>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:16px;">
        <button class="btn btn--primary" onclick="openAddMedDir('doctor')">+ Врач</button>
        <button class="btn btn--primary" style="background:var(--blue);" onclick="openAddMedDir('test')">+ Анализ</button>
        <button class="btn btn--primary" style="background:var(--green);" onclick="openAddMedDir('vaccine')">+ Вакцина</button>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead><tr><th>Тип</th><th>Название</th><th>Срок (мес)</th><th>Обяз.</th><th>Действия</th></tr></thead>
          <tbody id="medbook-dirs-table"><tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;"><div class="loading">Загрузка...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
  try {
    const data = await api('/api/admin/medbooks', {});
    const doctors = data.doctors || [];
    const tests = data.tests || [];
    const vaccines = data.vaccines || [];
    const allItems = [
      ...doctors.map(d => ({...d, type: 'doctor', typeLabel: 'Врач'})),
      ...tests.map(t => ({...t, type: 'test', typeLabel: 'Анализ'})),
      ...vaccines.map(v => ({...v, type: 'vaccine', typeLabel: 'Вакцина'})),
    ];
    const tbody = $('medbook-dirs-table');
    const typeColors = { doctor: 'var(--purple)', test: 'var(--blue)', vaccine: 'var(--green)' };
    tbody.innerHTML = allItems.map((item, i) => `
      <tr>
        <td><span class="tag" style="background:${typeColors[item.type]||'var(--text-terc)'}20;color:${typeColors[item.type]||'var(--text-terc)'};">${item.typeLabel}</span></td>
        <td style="font-weight:600;color:var(--text);">${esc(item.name||'—')}</td>
        <td>${item.validity_months||'—'}</td>
        <td>${item.required ? '<span class="tag tag--green">Да</span>' : '<span class="tag tag--amber">Нет</span>'}</td>
        <td>
          <button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;" onclick="editMedDirItem(${item.id},'${esc(item.type)}','${esc(item.name)}',${item.validity_months||0},${item.required})">✏️</button>
          <button class="btn btn--ghost" style="padding:4px 8px;font-size:11px;color:var(--pink);" onclick="deleteMedDirItem('${esc(item.type)}',${item.id})">🗑️</button>
        </td>
      </tr>
    `).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Нет записей</td></tr>';
  } catch (e) {
    $('medbook-dirs-table').innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

async function openAddMedDir(type) {
  const typeLabels = { doctor: 'Врач', test: 'Анализ', vaccine: 'Вакцина' };
  openModal(`Добавить ${typeLabels[type]}`, `
    <div class="form-group"><label>Название</label><input class="form-input" id="med-dir-name" maxlength="100"></div>
    <div class="form-group"><label>Срок действия (месяцев)</label><input class="form-input" id="med-dir-months" type="number" value="12" min="1" max="120"></div>
    <label style="display:flex;align-items:center;gap:8px;margin-bottom:16px;cursor:pointer;">
      <input type="checkbox" id="med-dir-required" checked> <span style="font-size:13px;">Обязательный</span>
    </label>
    <div class="form-hint" id="med-dir-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="med-dir-save">Добавить</button>`);
  $('med-dir-save').addEventListener('click', async () => {
    const errEl = $('med-dir-error');
    errEl.textContent = '';
    const name = $('med-dir-name').value.trim();
    const months = parseInt($('med-dir-months').value) || 12;
    const required = $('med-dir-required').checked;
    if (!name) { errEl.textContent = 'Введите название'; return; }
    try {
      await api('/api/admin/medbook/reference/add', { type, name, validity_months: months, required });
      toast('Добавлено', 'success'); closeModal(); navigate('medbook-dirs');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function editMedDirItem(id, type, name, months, required) {
  const typeLabels = { doctor: 'Врач', test: 'Анализ', vaccine: 'Вакцина' };
  openModal(`Редактировать ${typeLabels[type]}`, `
    <div class="form-group"><label>Название</label><input class="form-input" id="ed-med-dir-name" value="${esc(name)}" maxlength="100"></div>
    <div class="form-group"><label>Срок действия (месяцев)</label><input class="form-input" id="ed-med-dir-months" type="number" value="${months}" min="1" max="120"></div>
    <label style="display:flex;align-items:center;gap:8px;margin-bottom:16px;cursor:pointer;">
      <input type="checkbox" id="ed-med-dir-required" ${required ? 'checked' : ''}> <span style="font-size:13px;">Обязательный</span>
    </label>
    <div class="form-hint" id="ed-med-dir-error"></div>
  `, `<button class="btn btn--ghost" onclick="closeModal()">Отмена</button><button class="btn btn--primary" id="ed-med-dir-save">Сохранить</button>`);
  $('ed-med-dir-save').addEventListener('click', async () => {
    const errEl = $('ed-med-dir-error');
    errEl.textContent = '';
    const name = $('ed-med-dir-name').value.trim();
    const months = parseInt($('ed-med-dir-months').value) || 12;
    const required = $('ed-med-dir-required').checked;
    if (!name) { errEl.textContent = 'Введите название'; return; }
    try {
      await api('/api/admin/medbook/reference/update', { type, id, name, validity_months: months, required });
      toast('Сохранено', 'success'); closeModal(); navigate('medbook-dirs');
    } catch (e) { errEl.textContent = 'Ошибка: ' + e.message; }
  });
}

async function deleteMedDirItem(type, id) {
  if (!confirm('Удалить запись?')) return;
  try { await api('/api/admin/medbook/reference/delete', { type, id }); toast('Удалено', 'success'); navigate('medbook-dirs'); }
  catch (e) { toast('Ошибка: ' + e.message, 'error'); }
}

// ═══ Page Loaders Registry ═══
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
};

// ═══ Init ═══
if (getToken()) {
  checkAdminAndLoad();
} else {
  showLogin();
}
