/* ═══════════════════════════════════════════
   WOKKER ADMIN — NEUMORPHIC DASHBOARD
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
  const data = await res.json();
  if (data && (data.error === 'forbidden' || data.error === 'fired' || data.error === 'unauthorized')) {
    clearToken(); showLogin(); throw new Error(data.error);
  }
  return data;
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
          <div class="neu-card__trend neu-card__trend--up">↑ +3</div>
        </div>
        <div class="neu-card__value" id="stat-active">
          <div class="skeleton skeleton-stat"></div>
        </div>
        <div class="neu-card__label">Активные сотрудники</div>
      </div>

      <div class="neu-card neu-card--stat">
        <div style="display:flex;align-items:center;justify-content:space-between;">
          <div class="neu-card__icon-wrapper neu-card__icon-wrapper--blue">📝</div>
          <div class="neu-card__trend neu-card__trend--warn">⏳</div>
        </div>
        <div class="neu-card__value" id="stat-pending">
          <div class="skeleton skeleton-stat"></div>
        </div>
        <div class="neu-card__label">На модерации</div>
      </div>

      <div class="neu-card neu-card--stat">
        <div style="display:flex;align-items:center;justify-content:space-between;">
          <div class="neu-card__icon-wrapper neu-card__icon-wrapper--pink">📖</div>
          <div class="neu-card__trend neu-card__trend--down">!</div>
        </div>
        <div class="neu-card__value" id="stat-medbooks">
          <div class="skeleton skeleton-stat"></div>
        </div>
        <div class="neu-card__label">Медкнижки требуют внимания</div>
      </div>

      <div class="neu-card neu-card--stat">
        <div style="display:flex;align-items:center;justify-content:space-between;">
          <div class="neu-card__icon-wrapper neu-card__icon-wrapper--green">❓</div>
          <div class="neu-card__trend neu-card__trend--warn">открытых</div>
        </div>
        <div class="neu-card__value" id="stat-questions">
          <div class="skeleton skeleton-stat"></div>
        </div>
        <div class="neu-card__label">Вопросы от сотрудников</div>
      </div>
    </div>

    <div class="grid-2">
      <div class="neu-card">
        <div class="neu-card__header">
          <div class="neu-card__header-title">Последняя активность</div>
          <div class="neu-card__header-action" onclick="navigate('news')">Все события →</div>
        </div>
        <div class="activity" id="dash-activity">
          <div class="activity__item">
            <div class="activity__icon activity__icon--green">👤</div>
            <div class="activity__content">
              <div class="activity__text"><strong>HR</strong> создала сотрудника</div>
              <div class="activity__time">только что</div>
            </div>
          </div>
          <div class="activity__item">
            <div class="activity__icon activity__icon--accent">📰</div>
            <div class="activity__content">
              <div class="activity__text"><strong>Смирнов В.</strong> предложил новость</div>
              <div class="activity__time">1 час назад</div>
            </div>
          </div>
          <div class="activity__item">
            <div class="activity__icon activity__icon--blue">📋</div>
            <div class="activity__content">
              <div class="activity__text"><strong>Табель</strong> обновлён</div>
              <div class="activity__time">2 часа назад</div>
            </div>
          </div>
        </div>
      </div>

      <div class="neu-card">
        <div class="neu-card__header">
          <div class="neu-card__header-title">Новые сотрудники</div>
          <div class="neu-card__header-action" onclick="navigate('users')">Все →</div>
        </div>
        <div id="dash-new-users">
          <div class="loading">Загрузка...</div>
        </div>
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
    if ($('dash-new-users')) {
      const users = (data.users || []).slice(0, 5);
      $('dash-new-users').innerHTML = users.map((u, i) => {
        return `
          <div class="activity__item">
            <div class="avatar" style="background:${getAvatarGradient(i)};width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;font-weight:700;flex-shrink:0;">
              ${(u.full_name||'?').charAt(0)}
            </div>
            <div class="activity__content">
              <div class="activity__text">${esc(u.full_name||'—')}</div>
              <div class="activity__time">${esc(u.position||'')}</div>
            </div>
          </div>
        `;
      }).join('') || '<div class="loading">Нет новых</div>';
    }
  } catch (e) {
    console.error('Dashboard error:', e);
  }
}

// ═══ USERS ═══
async function loadUsers() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Сотрудники</div>
        <span style="font-size:12px;color:var(--text-terc);font-weight:700;" id="users-count">Загрузка...</span>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>Сотрудник</th>
              <th>Позиция</th>
              <th>Ресторан</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody id="users-table">
            <tr>
              <td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  try {
    const data = await cachedApi('/api/admin/users', { search: '', fired: false });
    const users = data.users || [];
    $('users-count').textContent = users.length + ' сотрудников';
    const tbody = $('users-table');
    tbody.innerHTML = users.map((u, i) => {
      const grad = getAvatarGradient(i);
      return `
        <tr>
          <td>
            <div class="name-cell">
              <div class="avatar" style="background:${grad}">
                ${(u.full_name||'?').charAt(0).toUpperCase()}
              </div>
              ${esc(u.full_name||'—')}
            </div>
          </td>
          <td>${esc(u.position||'—')}</td>
          <td>${esc(u.restaurant_name||'—')}</td>
          <td>
            <span class="tag ${u.is_fired ? 'tag--amber' : 'tag--green'}">
              ${u.is_fired ? 'Уволен' : 'Активен'}
            </span>
          </td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Нет сотрудников</td></tr>';
  } catch (e) {
    $('users-table').innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ MEDBOOKS ═══
async function loadMedbooks() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Медкнижки</div>
        <span style="font-size:12px;color:var(--text-terc);font-weight:700;" id="mb-count">Загрузка...</span>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>Сотрудник</th>
              <th>Позиция</th>
              <th>Ресторан</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody id="medbooks-table">
            <tr>
              <td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  try {
    const data = await cachedApi('/api/admin/medbooks', {});
    const users = data.users || [];
    $('mb-count').textContent = users.length + ' сотрудников';
    const tbody = $('medbooks-table');
    tbody.innerHTML = users.map((u, i) => {
      const grad = getAvatarGradient(i);
      const statusTag = u.medbook_status === 'ok' ? 'tag--green' : u.medbook_status === 'expiring' ? 'tag--amber' : 'tag--pink';
      const statusText = u.medbook_status === 'ok' ? 'OK' : u.medbook_status === 'expiring' ? 'Истекает' : 'Не заполнена';
      return `
        <tr>
          <td>
            <div class="name-cell">
              <div class="avatar" style="background:${grad}">
                ${(u.full_name||'?').charAt(0).toUpperCase()}
              </div>
              ${esc(u.full_name||'—')}
            </div>
          </td>
          <td>${esc(u.position||'—')}</td>
          <td>${esc(u.restaurant_name||'—')}</td>
          <td>
            <span class="tag ${statusTag}">${statusText}</span>
          </td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Нет сотрудников</td></tr>';
  } catch (e) {
    $('medbooks-table').innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ NEWS ═══
async function loadNews() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Новости</div>
        <span style="font-size:12px;color:var(--text-terc);font-weight:700;" id="news-count">Загрузка...</span>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>Тип</th>
              <th>Заголовок</th>
              <th>Автор</th>
              <th>Дата</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody id="news-table">
            <tr>
              <td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  try {
    const data = await cachedApi('/api/admin/news', {});
    const news = data.news || [];
    $('news-count').textContent = news.length + ' новостей';
    const tbody = $('news-table');
    tbody.innerHTML = news.map(n => {
      const levelTag = n.level === 'announcement' ? 'tag--purple' : n.level === 'event' ? 'tag--green' : 'tag--blue';
      const statusTag = n.status === 'published' ? 'tag--green' : 'tag--amber';
      const statusText = n.status === 'published' ? 'Опубликована' : n.status === 'scheduled' ? 'Запланирована' : 'На модерации';
      return `
        <tr>
          <td><span class="tag ${levelTag}">${n.level || 'normal'}</span></td>
          <td style="font-weight:600;color:var(--text);">${esc(n.title||'—')}</td>
          <td>${esc(n.proposed_by||'—')}</td>
          <td style="color:var(--text-terc);">${fmtDate(n.created_at)}</td>
          <td><span class="tag ${statusTag}">${statusText}</span></td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Нет новостей</td></tr>';
  } catch (e) {
    $('news-table').innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ STANDARDS ═══
async function loadStandards() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Стандарты</div>
        <span style="font-size:12px;color:var(--text-terc);font-weight:700;" id="std-count">Загрузка...</span>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>Заголовок</th>
              <th>Группа</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody id="standards-table">
            <tr>
              <td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  try {
    const data = await cachedApi('/api/admin/standards', {});
    const standards = data.standards || [];
    $('std-count').textContent = standards.length + ' стандартов';
    const tbody = $('standards-table');
    tbody.innerHTML = standards.map(s => {
      const statusTag = s.status === 'published' ? 'tag--green' : 'tag--amber';
      const statusText = s.status === 'published' ? 'Опубликован' : 'На модерации';
      return `
        <tr>
          <td style="font-weight:600;color:var(--text);">${esc(s.title||'—')}</td>
          <td><span class="tag tag--purple">${esc(s.group_name||'Общее')}</span></td>
          <td><span class="tag ${statusTag}">${statusText}</span></td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;">Нет стандартов</td></tr>';
  } catch (e) {
    $('standards-table').innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ FAQ ═══
async function loadFaq() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">FAQ</div>
        <span style="font-size:12px;color:var(--text-terc);font-weight:700;" id="faq-count">Загрузка...</span>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>Вопрос</th>
              <th>Категория</th>
              <th>Ответ</th>
            </tr>
          </thead>
          <tbody id="faq-table">
            <tr>
              <td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  try {
    const data = await cachedApi('/api/admin/faq', {});
    const items = data.faq || [];
    $('faq-count').textContent = items.length + ' вопросов';
    const tbody = $('faq-table');
    tbody.innerHTML = items.map(f => `
      <tr>
        <td style="font-weight:600;color:var(--text);">${esc(f.question||'—')}</td>
        <td><span class="tag tag--blue">${esc(f.category||'—')}</span></td>
        <td style="color:var(--text-sec);">${esc(f.answer||'—')}</td>
      </tr>
    `).join('') || '<tr><td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;">Нет вопросов</td></tr>';
  } catch (e) {
    $('faq-table').innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ RESTAURANTS ═══
async function loadRestaurants() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Рестораны</div>
        <span style="font-size:12px;color:var(--text-terc);font-weight:700;" id="rest-count">Загрузка...</span>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>Название</th>
              <th>Адрес</th>
              <th>ТУ</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody id="restaurants-table">
            <tr>
              <td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  try {
    const data = await cachedApi('/api/admin/restaurants', {});
    const restaurants = data.restaurants || [];
    $('rest-count').textContent = restaurants.length + ' ресторанов';
    const tbody = $('restaurants-table');
    tbody.innerHTML = restaurants.map(r => {
      const statusTag = r.force_status === 'open' ? 'tag--green' : 'tag--amber';
      const statusText = r.force_status === 'open' ? 'Открыт' : r.force_status || 'Открыт';
      return `
        <tr>
          <td style="font-weight:600;color:var(--text);">${esc(r.name||'—')}</td>
          <td class="restaurant">${esc(r.address||'—')}</td>
          <td>${esc(r.territory_manager_name||'—')}</td>
          <td><span class="tag ${statusTag}">${statusText}</span></td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Нет ресторанов</td></tr>';
  } catch (e) {
    $('restaurants-table').innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ CERTIFICATION ═══
async function loadCertification() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Сертификация</div>
        <span style="font-size:12px;color:var(--text-terc);font-weight:700;" id="cert-count">Загрузка...</span>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>Вопрос</th>
              <th>Правильный ответ</th>
            </tr>
          </thead>
          <tbody id="cert-table">
            <tr>
              <td colspan="2" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  try {
    const data = await cachedApi('/api/admin/certification', {});
    const questions = data.questions || [];
    $('cert-count').textContent = questions.length + ' вопросов';
    const tbody = $('cert-table');
    tbody.innerHTML = questions.map(q => {
      const correct = {a:'A',b:'B',c:'C',d:'D'};
      return `
        <tr>
          <td style="color:var(--text);">${esc(q.question||'—')}</td>
          <td><span class="tag tag--green">${correct[q.correct_option?.toLowerCase()]||'—'}</span></td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="2" style="text-align:center;color:var(--text-terc);padding:40px;">Нет вопросов</td></tr>';
  } catch (e) {
    $('cert-table').innerHTML = `<tr><td colspan="2" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ POSITIONS ═══
async function loadPositions() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Должности</div>
        <span style="font-size:12px;color:var(--text-terc);font-weight:700;" id="pos-count">Загрузка...</span>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>Название</th>
              <th>Ставка</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody id="positions-table">
            <tr>
              <td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  try {
    const data = await cachedApi('/api/admin/positions', {});
    const positions = data.positions || [];
    $('pos-count').textContent = positions.length + ' должностей';
    const tbody = $('positions-table');
    tbody.innerHTML = positions.map(p => {
      const statusTag = p.is_archived ? 'tag--amber' : 'tag--green';
      const statusText = p.is_archived ? 'Архив' : 'Активна';
      return `
        <tr>
          <td style="font-weight:600;color:var(--text);">${esc(p.name||'—')}</td>
          <td>${p.rate!=null ? '₽'+p.rate : '—'}</td>
          <td><span class="tag ${statusTag}">${statusText}</span></td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;">Нет должностей</td></tr>';
  } catch (e) {
    $('positions-table').innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ QUESTIONS ═══
async function loadQuestions() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Вопросы от сотрудников</div>
        <span style="font-size:12px;color:var(--text-terc);font-weight:700;" id="q-count-page">Загрузка...</span>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>От</th>
              <th>Вопрос</th>
              <th>Дата</th>
              <th>Ответ</th>
            </tr>
          </thead>
          <tbody id="questions-table">
            <tr>
              <td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  try {
    const data = await cachedApi('/api/admin/questions', {});
    const questions = data.questions || [];
    $('q-count-page').textContent = questions.length + ' вопросов';
    const tbody = $('questions-table');
    tbody.innerHTML = questions.map(q => {
      const statusTag = q.replied ? 'tag--green' : 'tag--amber';
      const statusText = q.replied ? 'Ответен' : 'Ожидает';
      return `
        <tr>
          <td>${esc(q.full_name||'—')}</td>
          <td style="color:var(--text);">${esc(q.text||'—')}</td>
          <td style="color:var(--text-terc);">${fmtDate(q.created_at)}</td>
          <td><span class="tag ${statusTag}">${statusText}</span></td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Нет вопросов</td></tr>';
  } catch (e) {
    $('questions-table').innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ ADMINS ═══
async function loadAdmins() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Администраторы</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>Логин</th>
              <th>Имя</th>
              <th>Позиция</th>
              <th>Роль</th>
            </tr>
          </thead>
          <tbody id="admins-table">
            <tr>
              <td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
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
      return `
        <tr>
          <td style="font-weight:600;">${esc(a.login||'—')}</td>
          <td>${esc(a.full_name||'—')}</td>
          <td>${esc(a.position||'—')}</td>
          <td><span class="tag ${role}">${roleText}</span></td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Нет админов</td></tr>';
  } catch (e) {
    $('admins-table').innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
}

// ═══ REPORTS ═══
async function loadReports() {
  $('page-content').innerHTML = `
    <div class="neu-card">
      <div class="neu-card__header">
        <div class="neu-card__header-title">Отчёты по персоналу</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>Всего</th>
              <th>Активных</th>
              <th>Уволено</th>
              <th>Новые (7д)</th>
              <th>Вопросы</th>
              <th>Новости на модерации</th>
              <th>Стандарты на модерации</th>
            </tr>
          </thead>
          <tbody id="reports-body">
            <tr>
              <td colspan="7" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
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
      <div class="neu-card__header">
        <div class="neu-card__header-title">История действий</div>
      </div>
      <div class="table-wrap">
        <table class="t">
          <thead>
            <tr>
              <th>Дата</th>
              <th>Админ</th>
              <th>Действие</th>
              <th>Объект</th>
            </tr>
          </thead>
          <tbody id="audit-table">
            <tr>
              <td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">
                <div class="loading">Загрузка...</div>
              </td>
            </tr>
          </tbody>
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
        <td style="color:var(--text-secondary);">${esc(a.details||'—')}</td>
      </tr>
    `).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Нет записей</td></tr>';
  } catch (e) {
    $('audit-table').innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-terc);padding:40px;">Ошибка: ${esc(e.message)}</td></tr>`;
  }
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
