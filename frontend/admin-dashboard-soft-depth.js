/* WOKKER Control — dashboard presentation only. Existing API and permissions remain unchanged. */
(function () {
  'use strict';
  const dashboardMarkup = () => `
    <section class="sd-dashboard" aria-label="Обзор системы">
      <header class="sd-intro">
        <div><div class="sd-eyebrow">WOKKER CONTROL · ОБЗОР</div>
          <h3>Всё важное — на одном экране</h3>
          <p>Сотрудники, документы и задачи, требующие внимания.</p></div>
        <button class="sd-refresh" type="button" id="sd-refresh">↻ Обновить</button>
      </header>
      <div class="sd-metrics" aria-label="Ключевые показатели">
        <article class="sd-metric"><div class="sd-metric__head"><span class="sd-metric__label">Активные сотрудники</span><span class="sd-metric__icon" aria-hidden="true">♙</span></div><strong class="sd-metric__value" id="stat-active">—</strong></article>
        <article class="sd-metric sd-metric--accent"><div class="sd-metric__head"><span class="sd-metric__label">На модерации</span><span class="sd-metric__icon" aria-hidden="true">◷</span></div><strong class="sd-metric__value" id="stat-pending">—</strong></article>
        <article class="sd-metric"><div class="sd-metric__head"><span class="sd-metric__label">Медкнижки: требуют внимания</span><span class="sd-metric__icon" aria-hidden="true">▤</span></div><strong class="sd-metric__value" id="stat-medbooks">—</strong></article>
        <article class="sd-metric"><div class="sd-metric__head"><span class="sd-metric__label">Открытые вопросы</span><span class="sd-metric__icon" aria-hidden="true">?</span></div><strong class="sd-metric__value" id="stat-questions">—</strong></article>
      </div>
      <div id="sd-error" role="alert" hidden></div>
      <div class="sd-panels">
        <section class="sd-panel" aria-label="Открытые вопросы">
          <div class="sd-panel__head"><h4>Открытые вопросы</h4><button class="sd-link" type="button" data-sd-page="questions">Все вопросы →</button></div>
          <div id="dash-questions" aria-live="polite"><div class="sd-empty">Загрузка…</div></div>
        </section>
        <section class="sd-panel" aria-label="Новые сотрудники">
          <div class="sd-panel__head"><h4>Новые сотрудники</h4><button class="sd-link" type="button" data-sd-page="users">Все сотрудники →</button></div>
          <div id="dash-new-users" aria-live="polite"><div class="sd-empty">Загрузка…</div></div>
        </section>
      </div>
    </section>`;
  function row(title, detail, marker) {
    return '<div class="sd-row"><div class="sd-row__mark" aria-hidden="true">' + esc(marker) +
      '</div><div class="sd-row__body"><div class="sd-row__title">' + esc(title) +
      '</div><div class="sd-row__detail">' + esc(detail) + '</div></div></div>';
  }
  window.loadDashboard = async function loadSoftDepthDashboard() {
    const root = $('page-content');
    root.innerHTML = dashboardMarkup();
    const current = root.querySelector('.sd-dashboard');
    current.querySelector('#sd-refresh').addEventListener('click', () => { clearCache(); navigate('dashboard'); });
    current.querySelectorAll('[data-sd-page]').forEach(button => {
      button.addEventListener('click', () => navigate(button.dataset.sdPage));
    });
    try {
      const data = await cachedApi('/api/admin/dashboard/summary', {}, 10000);
      if (!current.isConnected) return;
      const stats = data.stats || {};
      const values = {
        'stat-active': stats.active || 0,
        'stat-pending': (stats.news_pending || 0) + (stats.standards_pending || 0),
        'stat-medbooks': stats.medbooks_alert || 0,
        'stat-questions': stats.questions_open || 0
      };
      for (const [id, value] of Object.entries(values)) {
        const el = current.querySelector('#' + id);
        if (el) el.textContent = String(value);
      }
      const questions = (data.questions || []).slice(0, 5);
      const users = (data.users || []).slice(0, 5);
      current.querySelector('#dash-questions').innerHTML = questions.length
        ? questions.map(q => row(q.full_name || 'Сотрудник', (q.text || '—') + ' · ' + fmtDate(q.created_at, true), '?')).join('')
        : '<div class="sd-empty">Открытых вопросов нет</div>';
      current.querySelector('#dash-new-users').innerHTML = users.length
        ? users.map(u => row(u.full_name || '—', (u.position || 'Должность не указана') + ' · ' + fmtDate(u.created_at), (u.full_name || '?').charAt(0))).join('')
        : '<div class="sd-empty">Новых сотрудников нет</div>';
    } catch (e) {
      if (!current.isConnected || e.message === 'unauthorized' || e.message === 'fired') return;
      const error = current.querySelector('#sd-error');
      error.hidden = false;
      error.className = 'sd-error';
      error.textContent = 'Не удалось загрузить показатели. Попробуйте обновить страницу.';
      current.querySelector('#dash-questions').innerHTML = '<div class="sd-empty">Данные недоступны</div>';
      current.querySelector('#dash-new-users').innerHTML = '<div class="sd-empty">Данные недоступны</div>';
      console.error('Soft Depth dashboard:', e);
    }
  };
})();
