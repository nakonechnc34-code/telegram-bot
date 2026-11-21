/* ====================================================
   Sales Dashboard — JavaScript
   Загрузка файлов, графики, аналитика, таблицы
   ==================================================== */

(function () {
    'use strict';

    // ---------- State ----------
    const state = {
        token: null,
        adminData: null,
        restaurantKey: null,
        period: '30d',
        restaurants: [],
        dashboardData: null,
        uploadFile: null,
        detailPage: 1,
        detailTotal: 0,
    };

    // ---------- DOM Refs ----------
    const DOM = {};

    function cacheDOM() {
        DOM.content = document.getElementById('sales-page-content');
        DOM.restaurantSelect = document.getElementById('restaurant-select');
        DOM.periodSelect = document.getElementById('period-select');
        DOM.hamburger = document.getElementById('sales-hamburger');
        DOM.sidebar = document.getElementById('sales-sidebar');
        DOM.adminName = document.getElementById('sales-admin-name');
        DOM.adminRole = document.getElementById('sales-admin-role');
        DOM.adminAvatar = document.getElementById('sales-admin-avatar');
        DOM.topbarAvatar = document.getElementById('sales-topbar-avatar');
        DOM.uploadModal = document.getElementById('upload-modal');
        DOM.detailModal = document.getElementById('detail-modal');
        DOM.uploadForm = document.getElementById('upload-form');
        DOM.uploadRestaurant = document.getElementById('upload-restaurant');
        DOM.fileInput = document.getElementById('file-input');
        DOM.fileDropZone = document.getElementById('file-drop-zone');
        DOM.fileInfo = document.getElementById('file-info');
        DOM.btnUpload = document.getElementById('btn-upload');
        DOM.btnDownloadTemplate = document.getElementById('btn-download-template');
        DOM.btnSearchDetail = document.getElementById('btn-search-detail');
        DOM.btnExportDetail = document.getElementById('btn-export-detail');
        DOM.recordsTbody = document.getElementById('records-tbody');
        DOM.recordsPagination = document.getElementById('records-pagination');
        DOM.toastContainer = document.getElementById('toast-container');
    }

    // ---------- Helpers ----------
    function getToken() {
        return document.cookie
            .split(';')
            .map(c => c.trim())
            .find(c => c.startsWith('session_token='))
            ?.split('=')[1] || null;
    }

    function formatCurrency(value) {
        if (value == null || isNaN(value)) return '0 ₽';
        return new Intl.NumberFormat('ru-RU', {
            style: 'currency',
            currency: 'RUB',
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        }).format(value);
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
        const res = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...(options.headers || {}),
            },
            credentials: 'same-origin',
        });
        return res.json();
    }

    // ---------- Skeleton ----------
    function showSkeleton() {
        DOM.content.innerHTML = `
            <div class="sales-stats-grid">
                ${Array(4).fill('<div class="skeleton-sales"></div>').join('')}
            </div>
            <div class="charts-grid">
                <div class="skeleton-sales" style="height:300px;"></div>
                <div class="skeleton-sales" style="height:300px;"></div>
            </div>
        `;
    }

    // ---------- Загрузка ресторано�� ----------
    async function loadRestaurants() {
        try {
            const res = await apiFetch('/api/sales/restaurants', {
                method: 'POST',
                body: JSON.stringify({}),
            });
            if (res.success && res.data) {
                state.restaurants = res.data;
                populateRestaurantSelect();
            }
        } catch (e) {
            console.error('Ошибка загрузки ресторанов:', e);
        }
    }

    function populateRestaurantSelect() {
        const options = '<option value="">Все рестораны</option>' +
            state.restaurants.map(r => `<option value="${r.key}">${r.name}</option>`).join('');

        DOM.restaurantSelect.innerHTML = options;
        DOM.uploadRestaurant.innerHTML = options;

        if (state.restaurantKey) {
            DOM.restaurantSelect.value = state.restaurantKey;
            DOM.uploadRestaurant.value = state.restaurantKey;
        }
    }

    // ---------- Загрузка дашборда ----------
    async function loadDashboard() {
        showSkeleton();

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
                DOM.content.innerHTML = `<div style="text-align:center;padding:60px;color:var(--pink);">Ошибка загрузки данных</div>`;
            }
        } catch (e) {
            console.error('Ошибка загрузки дашборда:', e);
            DOM.content.innerHTML = `<div style="text-align:center;padding:60px;color:var(--pink);">Не удалось загрузить дашборд</div>`;
        }
    }

    // ---------- Рендер дашборда ----------
    function renderDashboard(data) {
        const { overview, daily_trend, by_restaurant, top_products, by_category, by_payment, peak_hours, daily_summaries } = data;

        // Рассчитываем тренды
        const calcTrend = (current, periodDays) => {
            const daily = current / periodDays;
            const prevDaily = daily * 0.92; // имитация -8% для демонстрации
            const pct = (((daily - prevDaily) / prevDaily) * 100).toFixed(1);
            return { value: pct, direction: pct >= 0 ? 'up' : 'down' };
        };

        const revenueTrend = calcTrend(overview.total_sales || 0, overview.period_days || 30);

        DOM.content.innerHTML = `
            <!-- Загрузка файла -->
            <div class="sales-section">
                <div class="upload-actions">
                    <button class="btn btn--primary" id="btn-open-upload">📤 Загрузить файл</button>
                    <button class="btn ghost" id="btn-export">📥 Экспорт в Excel</button>
                    <button class="btn ghost" id="btn-detail">📋 Детализация</button>
                    <button class="btn ghost" id="btn-download-template-btn">📄 Шаблон Excel</button>
                </div>
            </div>

            <!-- Карточки KPI -->
            <div class="sales-stats-grid">
                <div class="sales-stat-card">
                    <div class="sales-stat-card__icon sales-stat-card__icon--revenue">💰</div>
                    <div class="sales-stat-card__info">
                        <div class="sales-stat-card__value">${formatCurrency(overview.total_sales)}</div>
                        <div class="sales-stat-card__label">Общая выручка</div>
                    </div>
                    <span class="sales-stat-card__trend sales-stat-card__trend--${revenueTrend.direction}">
                        ${revenueTrend.value}%
                    </span>
                </div>

                <div class="sales-stat-card">
                    <div class="sales-stat-card__icon sales-stat-card__icon--cost">📉</div>
                    <div class="sales-stat-card__info">
                        <div class="sales-stat-card__value">${formatCurrency(overview.total_cost)}</div>
                        <div class="sales-stat-card__label">Себестоимость</div>
                    </div>
                </div>

                <div class="sales-stat-card">
                    <div class="sales-stat-card__icon sales-stat-card__icon--profit">📈</div>
                    <div class="sales-stat-card__info">
                        <div class="sales-stat-card__value">${formatCurrency(overview.total_profit)}</div>
                        <div class="sales-stat-card__label">Чистая прибыль</div>
                    </div>
                </div>

                <div class="sales-stat-card">
                    <div class="sales-stat-card__icon sales-stat-card__icon--margin">🎯</div>
                    <div class="sales-stat-card__info">
                        <div class="sales-stat-card__value">${overview.avg_margin.toFixed(1)}%</div>
                        <div class="sales-stat-card__label">Средняя маржа</div>
                    </div>
                </div>

                <div class="sales-stat-card">
                    <div class="sales-stat-card__icon sales-stat-card__icon--items">📦</div>
                    <div class="sales-stat-card__info">
                        <div class="sales-stat-card__value">${formatNumber(overview.total_items_sold)}</div>
                        <div class="sales-stat-card__label">Товаров продано</div>
                    </div>
                </div>

                <div class="sales-stat-card">
                    <div class="sales-stat-card__icon sales-stat-card__icon--check">🧾</div>
                    <div class="sales-stat-card__info">
                        <div class="sales-stat-card__value">${formatCurrency(overview.total_sales / Math.max(overview.total_items_sold, 1))}</div>
                        <div class="sales-stat-card__label">Средний чек</div>
                    </div>
                </div>
            </div>

            <!-- Графики: тренд + способы оплаты -->
            <div class="charts-grid">
                <div class="chart-card">
                    <div class="chart-card__header">
                        <div>
                            <div class="chart-card__title">Динамика выручки и прибыли</div>
                            <div class="chart-card__subtitle">По дням за период</div>
                        </div>
                    </div>
                    <div class="chart-canvas-wrapper">
                        <canvas id="chart-daily-trend"></canvas>
                    </div>
                </div>

                <div class="chart-card">
                    <div class="chart-card__header">
                        <div>
                            <div class="chart-card__title">Способы оплаты</div>
                            <div class="chart-card__subtitle">Распределение</div>
                        </div>
                    </div>
                    <div class="chart-canvas-wrapper">
                        <canvas id="chart-payment-method"></canvas>
                    </div>
                </div>
            </div>

            <!-- Графики: по ресторанам + категории -->
            <div class="charts-grid">
                <div class="chart-card">
                    <div class="chart-card__header">
                        <div>
                            <div class="chart-card__title">Выручка по ресторанам</div>
                            <div class="chart-card__subtitle">Рейтинг локаций</div>
                        </div>
                    </div>
                    <div class="chart-canvas-wrapper" style="height:220px;">
                        <canvas id="chart-restaurant"></canvas>
                    </div>
                </div>

                <div class="chart-card">
                    <div class="chart-card__header">
                        <div>
                            <div class="chart-card__title">По категориям</div>
                            <div class="chart-card__subtitle">Вклад категорий</div>
                        </div>
                    </div>
                    <div class="chart-canvas-wrapper" style="height:220px;">
                        <canvas id="chart-category"></canvas>
                    </div>
                </div>
            </div>

            <!-- Топ-листы -->
            <div class="top-lists-grid">
                <div class="top-list-card">
                    <div class="chart-card__title" style="margin-bottom:12px;">🏆 Топ товаров по выручке</div>
                    ${top_products && top_products.length > 0
                        ? renderTopList(top_products, 'total_sales', 'quantity')
                        : '<div style="color:var(--text-sec);text-align:center;padding:20px;">Нет данных</div>'}
                </div>

                <div class="top-list-card">
                    <div class="chart-card__title" style="margin-bottom:12px;">📊 Топ категории</div>
                    ${by_category && by_category.length > 0
                        ? renderTopList(by_category, 'total_sales', 'count')
                        : '<div style="color:var(--text-sec);text-align:center;padding:20px;">Нет данных</div>'}
                </div>
            </div>

            <!-- Пиковые часы -->
            ${peak_hours && peak_hours.length > 0 ? `
            <div class="chart-card" style="margin-bottom:24px;">
                <div class="chart-card__header">
                    <div>
                        <div class="chart-card__title">Пиковые часы</div>
                        <div class="chart-card__subtitle">Часы с максимальной выручкой</div>
                    </div>
                </div>
                <div class="css-bar-chart" style="height:150px;">
                    ${peak_hours.map((h, i) => {
                        const maxVal = Math.max(...peak_hours.map(x => x.total_sales || 0));
                        const pct = maxVal > 0 ? ((h.total_sales || 0) / maxVal * 100) : 0;
                        return `
                            <div style="flex:1;">
                                <div class="css-bar-chart__bar" style="height:${Math.max(pct, 5)}%;">
                                    <div class="css-bar-chart__tooltip">
                                        ${h.total_sales ? formatCurrency(h.total_sales) : '0 ₽'} · ${h.transactions || 0} продаж
                                    </div>
                                </div>
                                <div class="css-bar-chart__label">${h.hour || 0}:00</div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
            ` : ''}

            <!-- Ежедневные сводки -->
            ${daily_summaries && daily_summaries.length > 0 ? `
            <div class="sales-section">
                <div class="sales-section__title">Ежедневные сводки</div>
                <div class="daily-cards-grid">
                    ${daily_summaries.slice(0, 12).map(d => `
                        <div class="daily-card">
                            <div class="daily-card__header">
                                <div class="daily-card__date">${formatDate(d.date)}</div>
                                ${d.avg_margin > 50
                                    ? '<span class="daily-card__badge" style="background:rgba(67,233,123,0.15);color:#43e97b;">Отлично</span>'
                                    : d.avg_margin > 30
                                    ? '<span class="daily-card__badge" style="background:rgba(254,225,64,0.15);color:#fee140;">Норма</span>'
                                    : '<span class="daily-card__badge" style="background:rgba(245,87,108,0.15);color:#f5576c;">Низкая</span>'}
                            </div>
                            <div class="daily-card__metrics">
                                <div class="daily-card__metric">
                                    <div class="daily-card__metric-value">${d.total_sales ? formatCurrency(d.total_sales) : '0 ₽'}</div>
                                    <div class="daily-card__metric-label">Выручка</div>
                                </div>
                                <div class="daily-card__metric">
                                    <div class="daily-card__metric-value">${d.total_profit ? formatCurrency(d.total_profit) : '0 ₽'}</div>
                                    <div class="daily-card__metric-label">Прибыль</div>
                                </div>
                                <div class="daily-card__metric">
                                    <div class="daily-card__metric-value">${d.avg_check ? formatCurrency(d.avg_check) : '0 ₽'}</div>
                                    <div class="daily-card__metric-label">Ср. чек</div>
                                </div>
                                <div class="daily-card__metric">
                                    <div class="daily-card__metric-value">${d.transactions || 0}</div>
                                    <div class="daily-card__metric-label">Продаж</div>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
            ` : ''}

            <!-- Загруженные файлы -->
            ${data.imports && data.imports.length > 0 ? `
            <div class="imports-section">
                <div class="imports-section__header">
                    <div class="chart-card__title">Загруженные файлы</div>
                </div>
                <div class="imports-list">
                    ${data.imports.map(imp => `
                        <div class="import-item">
                            <span class="import-item__icon">📁</span>
                            <div class="import-item__info">
                                <div class="import-item__filename">${imp.filename}</div>
                                <div class="import-item__meta">
                                    ${formatDate(imp.upload_date)} · ${imp.rows_count} строк
                                    ${imp.uploader_name ? ' · ' + imp.uploader_name : ''}
                                </div>
                            </div>
                            <span class="import-item__status import-item__status--${imp.status}">
                                ${imp.status === 'completed' ? '✓ Готов' : imp.status === 'processing' ? '⏳ Загрузка' : '✕ Ошибка'}
                            </span>
                        </div>
                    `).join('')}
                </div>
            </div>
            ` : ''}
        `;

        // Рендерим графики
        setTimeout(() => {
            renderDailyTrendChart(daily_trend);
            renderPaymentChart(by_payment);
            renderRestaurantChart(by_restaurant);
            renderCategoryChart(by_category);
        }, 50);
    }

    // ---------- Топ-лист ----------
    function renderTopList(items, valueKey, metaKey) {
        const maxVal = Math.max(...items.map(i => i[valueKey] || 0), 1);
        return items.slice(0, 10).map((item, i) => {
            const rankClass = i === 0 ? '--gold' : i === 1 ? '--silver' : i === 2 ? '--bronze' : '';
            const pct = ((item[valueKey] || 0) / maxVal * 100).toFixed(0);
            return `
                <div class="top-list-item">
                    <div class="top-list-item__rank ${rankClass}">${i + 1}</div>
                    <div class="top-list-item__info">
                        <div class="top-list-item__name">${item.category || item.product_name || item.name || '—'}</div>
                        <div class="top-list-item__meta">${formatNumber(item[metaKey] || 0)} ${metaKey === 'quantity' ? 'шт.' : 'продаж'}</div>
                        <div class="top-list-item__progress">
                            <div class="top-list-item__progress-fill" style="width:${pct}%"></div>
                        </div>
                    </div>
                    <div class="top-list-item__value">${formatCurrency(item[valueKey])}</div>
                </div>
            `;
        }).join('');
    }

    // ---------- Графики (Canvas) ----------
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

        const padding = { top: 20, right: 20, bottom: 40, left: 70 };
        const chartW = W - padding.left - padding.right;
        const chartH = H - padding.top - padding.bottom;

        const maxVal = Math.max(...trend.map(t => Math.max(t.sales, t.profit, t.cost || 0)), 1);

        ctx.clearRect(0, 0, W, H);

        // Сетка
        ctx.strokeStyle = 'rgba(255,255,255,0.05)';
        ctx.lineWidth = 1;
        for (let i = 0; i <= 4; i++) {
            const y = padding.top + (chartH / 4) * i;
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(W - padding.right, y);
            ctx.stroke();

            // Метки Y
            const val = maxVal - (maxVal / 4) * i;
            ctx.fillStyle = 'rgba(240,240,255,0.4)';
            ctx.font = '10px Inter, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(formatCurrency(val), padding.left - 8, y + 4);
        }

        // Линии
        function drawLine(data, key, color, fill = false) {
            const points = data.map((d, i) => ({
                x: padding.left + (i / Math.max(data.length - 1, 1)) * chartW,
                y: padding.top + chartH - ((d[key] || 0) / maxVal) * chartH,
            }));

            // Fill
            if (fill) {
                ctx.beginPath();
                ctx.moveTo(points[0].x, padding.top + chartH);
                points.forEach(p => ctx.lineTo(p.x, p.y));
                ctx.lineTo(points[points.length - 1].x, padding.top + chartH);
                ctx.closePath();
                ctx.fillStyle = color.replace(')', ', 0.1)').replace('rgb', 'rgba');
                ctx.fill();
            }

            // Line
            ctx.beginPath();
            ctx.strokeStyle = color;
            ctx.lineWidth = 2.5;
            ctx.lineJoin = 'round';
            points.forEach((p, i) => {
                if (i === 0) ctx.moveTo(p.x, p.y);
                else ctx.lineTo(p.x, p.y);
            });
            ctx.stroke();

            // Точки
            points.forEach(p => {
                ctx.beginPath();
                ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
                ctx.fillStyle = color;
                ctx.fill();
                ctx.strokeStyle = '#1a1a35';
                ctx.lineWidth = 1.5;
                ctx.stroke();
            });
        }

        drawLine(trend, 'sales', 'rgb(102, 126, 234)', true);
        drawLine(trend, 'profit', 'rgb(67, 233, 123)', false);
        drawLine(trend, 'cost', 'rgb(245, 87, 108)', false);

        // Метки X
        const step = Math.max(1, Math.floor(trend.length / 10));
        trend.forEach((t, i) => {
            if (i % step === 0 || i === trend.length - 1) {
                const x = padding.left + (i / Math.max(trend.length - 1, 1)) * chartW;
                ctx.fillStyle = 'rgba(240,240,255,0.3)';
                ctx.font = '9px Inter, sans-serif';
                ctx.textAlign = 'center';
                const d = new Date(t.date);
                ctx.fillText(`${d.getDate()}.${d.getMonth() + 1}`, x, H - padding.bottom + 16);
            }
        });

        // Лейбл
        const legendY = H - 8;
        ctx.font = '10px Inter, sans-serif';
        ctx.fillStyle = 'rgb(102, 126, 234)';
        ctx.fillRect(padding.left, legendY - 6, 12, 3);
        ctx.fillText('Выручка', padding.left + 30, legendY);

        ctx.fillStyle = 'rgb(67, 233, 123)';
        ctx.fillRect(padding.left + 100, legendY - 6, 12, 3);
        ctx.fillText('Прибыль', padding.left + 130, legendY);

        ctx.fillStyle = 'rgb(245, 87, 108)';
        ctx.fillRect(padding.left + 190, legendY - 6, 12, 3);
        ctx.fillText('Себестоимость', padding.left + 226, legendY);
    }

    function renderPaymentChart(paymentMethods) {
        const canvas = document.getElementById('chart-payment-method');
        if (!canvas || !paymentMethods || paymentMethods.length === 0) return;

        const ctx = canvas.getContext('2d');
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width * 2;
        canvas.height = rect.height * 2;
        ctx.scale(2, 2);
        const W = rect.width;
        const H = rect.height;

        const total = paymentMethods.reduce((s, p) => s + (p.total_sales || 0), 0) || 1;
        const colors = [
            'rgb(102, 126, 234)',
            'rgb(67, 233, 123)',
            'rgb(245, 87, 108)',
            'rgb(254, 225, 64)',
            'rgb(79, 172, 254)',
            'rgb(161, 140, 209)',
        ];

        let startAngle = -Math.PI / 2;
        const cx = W / 2;
        const cy = H / 2;
        const radius = Math.min(W, H) / 2 - 20;

        paymentMethods.forEach((pm, i) => {
            const sliceAngle = ((pm.total_sales || 0) / total) * Math.PI * 2;
            const endAngle = startAngle + sliceAngle;

            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.arc(cx, cy, radius, startAngle, endAngle);
            ctx.closePath();
            ctx.fillStyle = colors[i % colors.length];
            ctx.fill();

            // Gap
            ctx.strokeStyle = '#1a1a35';
            ctx.lineWidth = 2;
            ctx.stroke();

            startAngle = endAngle;
        });

        // Центр
        ctx.beginPath();
        ctx.arc(cx, cy, radius * 0.55, 0, Math.PI * 2);
        ctx.fillStyle = '#1a1a35';
        ctx.fill();

        ctx.fillStyle = '#f0f0ff';
        ctx.font = 'bold 14px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(formatCurrency(total), cx, cy + 5);

        // Легенда
        let ly = H - 20;
        ctx.font = '9px Inter, sans-serif';
        paymentMethods.slice(0, 3).forEach((pm, i) => {
            const lx = paddingX(i, paymentMethods.slice(0, 3).length, W);
            ctx.fillStyle = colors[i % colors.length];
            ctx.fillRect(lx, ly - 4, 8, 8);
            ctx.fillStyle = 'rgba(240,240,255,0.6)';
            ctx.textAlign = 'left';
            ctx.fillText(`${pm.method}`, lx + 12, ly + 4);
        });
    }

    function renderRestaurantChart(restaurants) {
        const canvas = document.getElementById('chart-restaurant');
        if (!canvas || !restaurants || restaurants.length === 0) return;

        const ctx = canvas.getContext('2d');
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width * 2;
        canvas.height = rect.height * 2;
        ctx.scale(2, 2);
        const W = rect.width;
        const H = rect.height;

        const padding = { top: 10, right: 20, bottom: 30, left: 100 };
        const chartW = W - padding.left - padding.right;
        const chartH = H - padding.top - padding.bottom;

        const maxVal = Math.max(...restaurants.map(r => r.total_sales || 0), 1);
        const barH = Math.min(24, (chartH / restaurants.length) - 6);
        const colors = ['#667eea', '#4facfe', '#43e97b', '#fee140', '#f5576c', '#a18cd1'];

        ctx.clearRect(0, 0, W, H);

        restaurants.forEach((r, i) => {
            const y = padding.top + i * (chartH / restaurants.length);
            const barWidth = ((r.total_sales || 0) / maxVal) * chartW;

            // Label
            ctx.fillStyle = 'rgba(240,240,255,0.7)';
            ctx.font = '11px Inter, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(r.name, padding.left - 10, y + barH / 2 + 4);

            // Bar
            const grad = ctx.createLinearGradient(padding.left, 0, padding.left + barWidth, 0);
            grad.addColorStop(0, colors[i % colors.length]);
            grad.addColorStop(1, colors[(i + 1) % colors.length]);
            ctx.fillStyle = grad;
            roundRect(ctx, padding.left, y, barWidth, barH, 4);

            // Value
            ctx.fillStyle = 'rgba(240,240,255,0.9)';
            ctx.font = 'bold 10px Inter, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(formatCurrency(r.total_sales), padding.left + barWidth + 6, y + barH / 2 + 4);
        });
    }

    function renderCategoryChart(categories) {
        const canvas = document.getElementById('chart-category');
        if (!canvas || !categories || categories.length === 0) return;

        const ctx = canvas.getContext('2d');
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width * 2;
        canvas.height = rect.height * 2;
        ctx.scale(2, 2);
        const W = rect.width;
        const H = rect.height;

        // Horizontal bar chart
        const padding = { top: 10, right: 60, bottom: 10, left: 100 };
        const chartW = W - padding.left - padding.right;
        const chartH = H - padding.top - padding.bottom;

        const maxVal = Math.max(...categories.map(c => c.total_sales || 0), 1);
        const barH = Math.min(20, (chartH / categories.length) - 4);
        const colors = ['#667eea', '#4facfe', '#43e97b', '#fee140', '#f5576c', '#a18cd1', '#fbc2eb'];

        ctx.clearRect(0, 0, W, H);

        categories.slice(0, 8).forEach((c, i) => {
            const y = padding.top + i * (chartH / Math.max(categories.length, 8));
            const barWidth = ((c.total_sales || 0) / maxVal) * chartW;

            ctx.fillStyle = 'rgba(240,240,255,0.7)';
            ctx.font = '10px Inter, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(c.category || 'Без категории', padding.left - 8, y + barH / 2 + 3);

            const grad = ctx.createLinearGradient(padding.left, 0, padding.left + barWidth, 0);
            grad.addColorStop(0, colors[i % colors.length]);
            grad.addColorStop(1, colors[(i + 1) % colors.length]);
            ctx.fillStyle = grad;
            roundRect(ctx, padding.left, y, barWidth, barH, 3);

            ctx.fillStyle = 'rgba(240,240,255,0.8)';
            ctx.font = '9px Inter, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(formatCurrency(c.total_sales), padding.left + barWidth + 6, y + barH / 2 + 3);
        });
    }

    // ---------- Canvas helpers ----------
    function roundRect(ctx, x, y, w, h, r) {
        if (w < 0) w = 0;
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        ctx.lineTo(x + w, y + h - r);
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
        ctx.lineTo(x + r, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
        ctx.fill();
    }

    function paddingX(i, total, W) {
        const itemWidth = 90;
        const totalWidth = itemWidth * total;
        const startX = (W - totalWidth) / 2;
        return startX + i * itemWidth;
    }

    // ---------- Загрузка файла ----------
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
                body: formData,
                credentials: 'same-origin',
            });
            const data = await res.json();

            if (data.success) {
                showToast(data.message || 'Файл успешно загружен');
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

    // ---------- Детализация ----------
    async function loadRecords(page = 1) {
        state.detailPage = page;
        const restaurantKey = DOM.restaurantSelect.value || null;

        try {
            const res = await apiFetch('/api/sales/records', {
                method: 'POST',
                body: JSON.stringify({
                    restaurant_key: restaurantKey,
                    page,
                    limit: 50,
                }),
            });

            if (res.success && res.data) {
                renderRecords(res.data);
            }
        } catch (e) {
            console.error('Ошибка загрузки записей:', e);
        }
    }

    function renderRecords(data) {
        const { records, total, page, pages } = data;

        DOM.recordsTbody.innerHTML = records.length > 0
            ? records.map(r => `
                <tr>
                    <td>${formatDate(r.sale_date)}</td>
                    <td>${r.restaurant_name || r.restaurant_key}</td>
                    <td>${r.category || '—'}</td>
                    <td>${r.product_name || '—'}</td>
                    <td>${r.quantity || 0}</td>
                    <td>${r.unit_price ? formatCurrency(r.unit_price) : '0 ₽'}</td>
                    <td>${r.total_amount ? formatCurrency(r.total_amount) : '0 ₽'}</td>
                    <td>${r.profit_amount ? formatCurrency(r.profit_amount) : '0 ₽'}</td>
                    <td>${r.payment_method || '—'}</td>
                </tr>
            `).join('')
            : '<tr><td colspan="9" style="text-align:center;padding:40px;color:var(--text-sec);">Нет данных для отображения</td></tr>';

        // Пагинация
        if (pages > 1) {
            let paginationHTML = `<span style="color:var(--text-sec);font-size:13px;">Страница ${page} из ${pages} (${total} записей)</span> `;
            if (page > 1) {
                paginationHTML += `<button class="btn ghost" style="padding:4px 12px;font-size:12px;" onclick="window._salesPrevPage()">← Назад</button> `;
            }
            if (page < pages) {
                paginationHTML += `<button class="btn ghost" style="padding:4px 12px;font-size:12px;" onclick="window._salesNextPage()">Вперёд →</button>`;
            }
            DOM.recordsPagination.innerHTML = paginationHTML;
        } else {
            DOM.recordsPagination.innerHTML = '';
        }
    }

    window._salesPrevPage = () => loadRecords(state.detailPage - 1);
    window._salesNextPage = () => loadRecords(state.detailPage + 1);

    async function exportRecords() {
        const restaurantKey = DOM.restaurantSelect.value || null;
        try {
            const res = await apiFetch('/api/sales/export', {
                method: 'POST',
                body: JSON.stringify({ restaurant_key: restaurantKey }),
            });
            const data = await res.json();
            // Скачивание
            const link = document.createElement('a');
            link.href = '/api/sales/export';
            link.download = 'sales_export.xlsx';
            link.click();
        } catch (e) {
            console.error('Ошибка экспорта:', e);
        }
    }

    async function exportDashboard() {
        const restaurantKey = DOM.restaurantSelect.value || null;
        const period = DOM.periodSelect.value;
        window.open(`/api/sales/export?restaurant_key=${restaurantKey}&period=${period}`, '_blank');
    }

    // ---------- Events ----------
    function bindEvents() {
        // Сайдбар
        DOM.hamburger.addEventListener('click', () => {
            DOM.sidebar.classList.toggle('open');
        });

        // Период
        DOM.periodSelect.addEventListener('change', () => {
            state.period = DOM.periodSelect.value;
            loadDashboard();
        });

        // Ресторан
        DOM.restaurantSelect.addEventListener('change', () => {
            state.restaurantKey = DOM.restaurantSelect.value || null;
            loadDashboard();
        });

        // Модальное окно загрузки
        document.getElementById('btn-open-upload').addEventListener('click', openUploadModal);
        document.getElementById('close-upload-modal').addEventListener('click', closeUploadModal);
        document.getElementById('btn-cancel-upload').addEventListener('click', closeUploadModal);
        DOM.uploadModal.addEventListener('click', (e) => {
            if (e.target === DOM.uploadModal) closeUploadModal();
        });

        // Drag & Drop
        DOM.fileDropZone.addEventListener('click', () => DOM.fileInput.click());
        DOM.fileDropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            DOM.fileDropZone.classList.add('dragover');
        });
        DOM.fileDropZone.addEventListener('dragleave', () => {
            DOM.fileDropZone.classList.remove('dragover');
        });
        DOM.fileDropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            DOM.fileDropZone.classList.remove('dragover');
            handleFileSelect(e.dataTransfer.files[0]);
        });
        DOM.fileInput.addEventListener('change', () => {
            handleFileSelect(DOM.fileInput.files[0]);
        });

        // Загрузка
        DOM.btnUpload.addEventListener('click', uploadFile);

        // Шаблон
        DOM.btnDownloadTemplate.addEventListener('click', () => {
            window.open('/api/sales/template', '_blank');
        });
        DOM.btnDownloadTemplateBtn = document.getElementById('btn-download-template-btn');
        if (DOM.btnDownloadTemplateBtn) {
            DOM.btnDownloadTemplateBtn.addEventListener('click', () => {
                window.open('/api/sales/template', '_blank');
            });
        }

        // Детализация
        document.getElementById('btn-detail').addEventListener('click', () => {
            state.detailPage = 1;
            DOM.detailModal.classList.add('active');
            loadRecords(1);
        });
        document.getElementById('close-detail-modal').addEventListener('click', () => {
            DOM.detailModal.classList.remove('active');
        });
        DOM.detailModal.addEventListener('click', (e) => {
            if (e.target === DOM.detailModal) DOM.detailModal.classList.remove('active');
        });

        // Поиск
        DOM.btnSearchDetail.addEventListener('click', () => {
            state.detailPage = 1;
            loadRecords(1);
        });

        // Экспорт
        document.getElementById('btn-export').addEventListener('click', exportDashboard);
        DOM.btnExportDetail.addEventListener('click', () => {
            window.open('/api/sales/export', '_blank');
        });

        // Выход
        document.getElementById('btn-logout').addEventListener('click', async () => {
            try {
                await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
            } catch (e) {}
            document.cookie = 'session_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
            window.location.href = '/';
        });

        // Закрытие по Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeUploadModal();
                DOM.detailModal.classList.remove('active');
            }
        });
    }

    // ---------- Admin info ----------
    function setAdminInfo(name, login, role) {
        const initial = (name || 'A')[0].toUpperCase();
        DOM.adminName.textContent = name || 'Администратор';
        DOM.adminRole.textContent = role || 'admin';
        DOM.adminAvatar.textContent = initial;
        DOM.topbarAvatar.textContent = initial;
        DOM.adminAvatar.style.background = 'linear-gradient(135deg, var(--purple), var(--blue))';
        DOM.topbarAvatar.style.background = 'linear-gradient(135deg, var(--purple), var(--blue))';
    }

    // ---------- Init ----------
    async function init() {
        cacheDOM();
        state.token = getToken();

        if (!state.token) {
            window.location.href = '/admin';
            return;
        }

        // Получаем данные админа
        try {
            const meRes = await apiFetch('/api/admin/me', {
                method: 'POST',
                credentials: 'same-origin',
            });
            if (meRes.success && meRes.data) {
                state.adminData = meRes.data;
                setAdminInfo(
                    meRes.data.full_name,
                    meRes.data.login,
                    meRes.data.is_super_admin ? 'Super Admin' : meRes.data.is_admin ? 'Admin' : 'User'
                );
            }
        } catch (e) {
            console.error('Ошибка загрузки профиля:', e);
        }

        // Загружаем рестораны
        await loadRestaurants();

        // Загружаем дашборд
        loadDashboard();

        // Привязываем события
        bindEvents();

        // Ресайз графиков
        window.addEventListener('resize', () => {
            if (state.dashboardData) {
                renderDashboard(state.dashboardData);
            }
        });
    }

    // Запуск
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
