(function () {
    'use strict';

    const state = {
        token: null,
        restaurantKey: null,
        period: '30d',
        restaurants: [],
        dashboardData: null,
        uploadFile: null,
        detailPage: 1,
    };

    const DOM = {};

    function cacheDOM() {
        DOM.content = document.getElementById('sales-page-content');
        DOM.restaurantSelect = document.getElementById('restaurant-select');
        DOM.periodSelect = document.getElementById('period-select');
        DOM.adminAvatar = document.getElementById('sales-topbar-avatar');
        DOM.uploadModal = document.getElementById('upload-modal');
        DOM.detailModal = document.getElementById('detail-modal');
        DOM.uploadRestaurant = document.getElementById('upload-restaurant');
        DOM.fileInput = document.getElementById('file-input');
        DOM.fileDropZone = document.getElementById('file-drop-zone');
        DOM.fileInfo = document.getElementById('file-info');
        DOM.btnUpload = document.getElementById('btn-upload');
        DOM.btnDownloadTemplate = document.getElementById('btn-download-template');
        DOM.btnSearchDetail = document.getElementById('btn-search-detail');
        DOM.recordsTbody = document.getElementById('records-tbody');
        DOM.recordsPagination = document.getElementById('records-pagination');
        DOM.toastContainer = document.getElementById('toast-container');
    }

    function getToken() { return localStorage.getItem('wokker_admin_token') || null; }

    function formatCurrency(value) {
        if (value == null || isNaN(value)) return '0 ₽';
        return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(value);
    }

    function formatNumber(value) {
        if (value == null || isNaN(value)) return '0';
        return new Intl.NumberFormat('ru-RU').format(value);
    }

    function formatDate(dateStr) {
        if (!dateStr) return '—';
        const d = new Date(dateStr);
        return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
    }

    function showToast(message, type = 'success') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        DOM.toastContainer.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    async function apiFetch(url, options = {}) {
        const token = getToken() || '';
        const res = await fetch(url, {
            ...options,
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token, ...(options.headers || {}) },
        });
        if (res.status === 401) { window.location.href = '/'; throw new Error('unauthorized'); }
        if (!res.ok) { let msg = 'error'; try { const j = await res.json(); msg = j.error || msg; } catch (e) {} throw new Error(msg); }
        return res.json();
    }

    async function loadRestaurants() {
        try {
            const res = await apiFetch('/api/sales/restaurants', { method: 'POST', body: JSON.stringify({}) });
            if (res.success && res.data) {
                state.restaurants = res.data;
                const options = '<option value="">Все рестораны</option>' + state.restaurants.map(r => `<option value="${r.key}">${r.name}</option>`).join('');
                DOM.restaurantSelect.innerHTML = options;
                DOM.uploadRestaurant.innerHTML = options;
            }
        } catch (e) { console.error(e); }
    }

    async function loadDashboard() {
        DOM.content.innerHTML = '<div class="loading">Загрузка...</div>';
        const restaurantKey = DOM.restaurantSelect.value || null;
        const period = DOM.periodSelect.value;

        try {
            const res = await apiFetch('/api/sales/dashboard', {
                method: 'POST',
                body: JSON.stringify({ restaurant_key: restaurantKey, period }),
            });

            if (res.success && res.data) {
                state.dashboardData = res.data;
                renderDashboard(res.data);
            } else {
                DOM.content.innerHTML = '<div class="loading">Ошибка загрузки данных</div>';
            }
        } catch (e) {
            DOM.content.innerHTML = `<div class="loading">Ошибка: ${e.message}</div>`;
        }
    }

    function renderDashboard(data) {
        const { overview, daily_trend, by_restaurant, by_category, by_payment } = data;

        // Считаем средний чек
        const avgCheck = overview.total_sales / Math.max(overview.total_items_sold, 1);

        // Генерируем Топ ресторанов (прогресс-бары справа)
        const maxRestSales = Math.max(...by_restaurant.map(r => r.total_sales || 0), 1);
        const topRestHtml = by_restaurant.slice(0, 5).map((r, i) => {
            const pct = ((r.total_sales || 0) / maxRestSales * 100).toFixed(0);
            const colors = ['blue', 'green', 'yellow', 'red'];
            return `
                <div class="top-list-item">
                    <div class="tl-header">
                        <span>${r.name}</span>
                        <span class="tl-value">${formatCurrency(r.total_sales)}</span>
                    </div>
                    <div class="tl-bar-bg">
                        <div class="tl-bar-fill ${colors[i % colors.length]}" style="width: ${pct}%"></div>
                    </div>
                </div>
            `;
        }).join('');

        DOM.content.innerHTML = `
            <!-- ROW 1: Карточки -->
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-header">Общая выручка <span>💰</span></div>
                    <div class="stat-value">${formatCurrency(overview.total_sales)}</div>
                    <div><span class="stat-trend up">+10%</span> с прошлого периода</div>
                </div>
                <div class="stat-card">
                    <div class="stat-header">Себестоимость <span>📉</span></div>
                    <div class="stat-value">${formatCurrency(overview.total_cost)}</div>
                    <div><span class="stat-trend down">-5%</span> с прошлого периода</div>
                </div>
                <div class="stat-card">
                    <div class="stat-header">Чистая прибыль <span>📈</span></div>
                    <div class="stat-value">${formatCurrency(overview.total_profit)}</div>
                    <div><span class="stat-trend up">+15%</span> с прошлого периода</div>
                </div>
                <div class="stat-card">
                    <div class="stat-header">Средний чек <span>🧾</span></div>
                    <div class="stat-value">${formatCurrency(avgCheck)}</div>
                    <div><span class="stat-trend neutral">0%</span> без изменений</div>
                </div>
            </div>

            <!-- ROW 2: График и Топ ресторанов -->
            <div class="main-row">
                <div class="chart-card">
                    <div class="chart-header">
                        <div class="chart-title">Динамика выручки и прибыли</div>
                    </div>
                    <div class="chart-canvas-wrapper">
                        <canvas id="chart-daily-trend"></canvas>
                    </div>
                </div>

                <div class="chart-card">
                    <div class="chart-header">
                        <div class="chart-title">Топ ресторанов</div>
                    </div>
                    <div class="top-list">
                        ${topRestHtml || '<div class="loading">Нет данных</div>'}
                    </div>
                </div>
            </div>
        `;

        // Рисуем график
        setTimeout(() => renderDailyTrendChart(daily_trend), 50);
    }

    function renderDailyTrendChart(trend) {
        const canvas = document.getElementById('chart-daily-trend');
        if (!canvas || !trend || trend.length === 0) return;

        const ctx = canvas.getContext('2d');
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width * 2;
        canvas.height = rect.height * 2;
        ctx.scale(2, 2);
        const W = rect.width;
        const H = rect.height;

        const padding = { top: 20, right: 20, bottom: 40, left: 60 };
        const chartW = W - padding.left - padding.right;
        const chartH = H - padding.top - padding.bottom;

        const maxVal = Math.max(...trend.map(t => Math.max(t.sales, t.profit)), 1);

        ctx.clearRect(0, 0, W, H);

        // Сетка
        ctx.strokeStyle = '#E5E7EB';
        ctx.lineWidth = 1;
        for (let i = 0; i <= 4; i++) {
            const y = padding.top + (chartH / 4) * i;
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(W - padding.right, y);
            ctx.stroke();

            const val = maxVal - (maxVal / 4) * i;
            ctx.fillStyle = '#6B7280';
            ctx.font = '11px Inter, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(formatNumber(val), padding.left - 10, y + 4);
        }

        // Рисуем столбцы (Выручка)
        const barWidth = Math.max(4, (chartW / trend.length) * 0.4);
        
        trend.forEach((t, i) => {
            const x = padding.left + (i / Math.max(trend.length - 1, 1)) * chartW;
            
            // Sales Bar
            const hSales = ((t.sales || 0) / maxVal) * chartH;
            const ySales = padding.top + chartH - hSales;
            
            ctx.fillStyle = '#0066FF';
            ctx.beginPath();
            ctx.roundRect(x - barWidth, ySales, barWidth, hSales, [4, 4, 0, 0]);
            ctx.fill();
        });

        // Метки X (Даты)
        const step = Math.max(1, Math.floor(trend.length / 7));
        trend.forEach((t, i) => {
            if (i % step === 0 || i === trend.length - 1) {
                const x = padding.left + (i / Math.max(trend.length - 1, 1)) * chartW;
                ctx.fillStyle = '#6B7280';
                ctx.font = '11px Inter, sans-serif';
                ctx.textAlign = 'center';
                const d = new Date(t.date);
                ctx.fillText(`${d.getDate()}.${d.getMonth() + 1}`, x, H - padding.bottom + 20);
            }
        });
    }

    // Загрузка файла
    function openUploadModal() {
        state.uploadFile = null;
        DOM.fileInfo.textContent = '';
        DOM.fileInput.value = '';
        DOM.btnUpload.disabled = true;
        DOM.uploadModal.classList.add('active');
    }

    function closeUploadModal() {
        DOM.uploadModal.classList.remove('active');
        state.uploadFile = null;
    }

    function handleFileSelect(file) {
        if (!file) return;
        state.uploadFile = file;
        DOM.fileInfo.textContent = `✅ ${file.name} (${(file.size / 1024).toFixed(1)} КБ)`;
        DOM.btnUpload.disabled = !DOM.uploadRestaurant.value;
    }

    async function uploadFile() {
        if (!state.uploadFile || !DOM.uploadRestaurant.value) return;
        const formData = new FormData();
        formData.append('file', state.uploadFile);
        formData.append('restaurant_key', DOM.uploadRestaurant.value);
        
        DOM.btnUpload.disabled = true;
        DOM.btnUpload.textContent = 'Загрузка…';

        try {
            const res = await fetch('/api/sales/upload', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + (getToken() || '') },
                body: formData,
            });
            const data = await res.json();
            if (data.success) {
                showToast('Файл успешно загружен');
                closeUploadModal();
                loadDashboard();
            } else {
                showToast(data.error || 'Ошибка загрузки', 'error');
            }
        } catch (e) {
            showToast('Ошибка сети: ' + e.message, 'error');
        } finally {
            DOM.btnUpload.disabled = false;
            DOM.btnUpload.textContent = 'Загрузить';
        }
    }

    // Детализация
    async function loadRecords(page = 1) {
        state.detailPage = page;
        try {
            const res = await apiFetch('/api/sales/records', {
                method: 'POST',
                body: JSON.stringify({ restaurant_key: DOM.restaurantSelect.value || null, page, limit: 50 }),
            });
            if (res.success && res.data) renderRecords(res.data);
        } catch (e) { console.error(e); }
    }

    function renderRecords(data) {
        const { records, total, page, pages } = data;
        DOM.recordsTbody.innerHTML = records.length > 0
            ? records.map(r => `
                <tr>
                    <td>${formatDate(r.sale_date)}</td>
                    <td>${r.restaurant_name || r.restaurant_key}</td>
                    <td>${r.product_name || '—'}</td>
                    <td>${r.quantity || 0}</td>
                    <td>${formatCurrency(r.total_amount)}</td>
                    <td>${formatCurrency(r.profit_amount)}</td>
                </tr>
            `).join('')
            : '<tr><td colspan="6" class="text-center">Нет данных</td></tr>';

        if (pages > 1) {
            let html = `<span style="font-size:13px;color:#6B7280;">Стр. ${page} из ${pages}</span> `;
            if (page > 1) html += `<button class="btn btn-secondary" onclick="window._salesPrevPage()">← Назад</button> `;
            if (page < pages) html += `<button class="btn btn-secondary" onclick="window._salesNextPage()">Вперёд →</button>`;
            DOM.recordsPagination.innerHTML = html;
        } else {
            DOM.recordsPagination.innerHTML = '';
        }
    }

    window._salesPrevPage = () => loadRecords(state.detailPage - 1);
    window._salesNextPage = () => loadRecords(state.detailPage + 1);

    // Init
    function bindEvents() {
        DOM.periodSelect.addEventListener('change', loadDashboard);
        DOM.restaurantSelect.addEventListener('change', loadDashboard);
        document.getElementById('btn-open-upload').addEventListener('click', openUploadModal);
        document.getElementById('close-upload-modal').addEventListener('click', closeUploadModal);
        document.getElementById('btn-cancel-upload').addEventListener('click', closeUploadModal);
        
        DOM.uploadModal.addEventListener('click', (e) => { if (e.target === DOM.uploadModal) closeUploadModal(); });
        DOM.fileDropZone.addEventListener('click', () => DOM.fileInput.click());
        DOM.fileDropZone.addEventListener('dragover', (e) => { e.preventDefault(); DOM.fileDropZone.classList.add('dragover'); });
        DOM.fileDropZone.addEventListener('dragleave', () => DOM.fileDropZone.classList.remove('dragover'));
        DOM.fileDropZone.addEventListener('drop', (e) => { e.preventDefault(); DOM.fileDropZone.classList.remove('dragover'); handleFileSelect(e.dataTransfer.files[0]); });
        DOM.fileInput.addEventListener('change', () => handleFileSelect(DOM.fileInput.files[0]));
        
        DOM.uploadRestaurant.addEventListener('change', () => { DOM.btnUpload.disabled = !DOM.uploadRestaurant.value || !state.uploadFile; });
        DOM.btnUpload.addEventListener('click', uploadFile);
        
        DOM.btnDownloadTemplate.addEventListener('click', () => window.open('/api/sales/template?webToken=' + encodeURIComponent(getToken() || ''), '_blank'));

        document.getElementById('btn-detail').addEventListener('click', () => {
            state.detailPage = 1;
            DOM.detailModal.classList.add('active');
            loadRecords(1);
        });
        document.getElementById('close-detail-modal').addEventListener('click', () => DOM.detailModal.classList.remove('active'));
        DOM.detailModal.addEventListener('click', (e) => { if (e.target === DOM.detailModal) DOM.detailModal.classList.remove('active'); });
        DOM.btnSearchDetail.addEventListener('click', () => loadRecords(1));
        document.getElementById('btn-export').addEventListener('click', () => {
            window.open(`/api/sales/export?restaurant_key=${DOM.restaurantSelect.value || ''}&webToken=${encodeURIComponent(getToken() || '')}`, '_blank');
        });
    }

    async function init() {
        cacheDOM();
        state.token = getToken();
        if (!state.token) { window.location.href = '/'; return; }

        try {
            const meRes = await apiFetch('/api/admin/me', { method: 'POST' });
            if (meRes.profile) DOM.adminAvatar.textContent = (meRes.profile.full_name || 'A').charAt(0).toUpperCase();
        } catch (e) {}

        await loadRestaurants();
        loadDashboard();
        bindEvents();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
