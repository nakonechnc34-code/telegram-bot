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
        view: 'overview',
        dashboardRequest: 0,
        productsRequest: 0,
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
    const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

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

    async function apiFetch(url, options = {}, responseType = "json") {
        const token = getToken() || '';
        const res = await fetch(url, {
            ...options,
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token, ...(options.headers || {}) },
        });
        if (res.status === 401) { window.location.href = '/'; throw new Error('unauthorized'); }
        if (!res.ok) { let msg = 'error'; try { const j = await res.json(); msg = j.error || msg; } catch (e) {} throw new Error(msg); }
        return responseType === "blob" ? res.blob() : res.json();
    }

    async function loadRestaurants() {
        try {
            const res = await apiFetch('/api/sales/restaurants', { method: 'POST', body: JSON.stringify({}) });
            if (res.success && res.data) {
                state.restaurants = res.data;
                const options = '<option value="">Все рестораны</option>' + state.restaurants.map(r => `<option value="${esc(r.key)}">${esc(r.name)}</option>`).join('');
                DOM.restaurantSelect.innerHTML = options;
                DOM.uploadRestaurant.innerHTML = '<option value="">Выберите ресторан</option>' + state.restaurants.map(r => `<option value="${esc(r.key)}">${esc(r.name)}</option>`).join('');
            }
        } catch (e) { console.error(e); }
    }

    async function loadDashboard() {
        DOM.content.innerHTML = '<div class="loading">Загрузка аналитики…</div>';
        const requestId = ++state.dashboardRequest;
        const restaurantKey = DOM.restaurantSelect.value || null;
        const period = DOM.periodSelect.value;

        try {
            const res = await apiFetch('/api/sales/dashboard', {
                method: 'POST',
                body: JSON.stringify({ restaurant_key: restaurantKey, period }),
            });

            if (requestId !== state.dashboardRequest) return;
            if (res.success && res.data) {
                state.dashboardData = res.data;
                renderDashboard(res.data);
            } else {
                DOM.content.innerHTML = '<div class="loading">Ошибка загрузки данных</div>';
            }
        } catch (e) {
            if (requestId === state.dashboardRequest) DOM.content.innerHTML = `<div class="loading">Ошибка: ${esc(e.message)} <button class="btn btn-secondary" id="retry-sales">Повторить</button></div>`;
            document.getElementById('retry-sales')?.addEventListener('click',loadDashboard);
        }
    }

    const money = formatCurrency;
    function restRows(rows) {
        return rows.map((r,i) => '<tr><td>' + (i+1) + '</td><td><strong>' + esc(r.name) + '</strong></td><td>' + money(r.total_sales) + '</td><td>' + money(r.profit) + '</td><td>' + (r.total_sales > 0 ? (100*r.profit/r.total_sales).toFixed(1)+'%' : '—') + '</td></tr>').join('');
    }
    function importRows(rows) {
        return rows.map(imp => '<tr><td><strong>'+esc(imp.filename)+'</strong></td><td>'+esc(state.restaurants.find(r=>r.key===imp.restaurant_key)?.name||imp.restaurant_key)+'</td><td>'+formatNumber(imp.rows_count)+'</td><td>'+formatDate(imp.upload_date)+'</td><td><span class="status-pill '+(imp.status==='completed'?'':'pending')+'">'+esc(imp.status==='completed'?'Загружен':imp.status)+'</span></td></tr>').join('');
    }
    function renderDashboard(data) {
        const {overview:o, daily_trend:trend=[], by_restaurant:restaurants=[], imports=[]} = data;
        const view=state.view;
        const intro = (title,subtitle,tag='ДАННЫЕ ИЗ ОТЧЁТОВ') => '<div class="intro"><div><h2>'+title+'</h2><p>'+subtitle+'</p></div><span class="eyebrow-tag">'+tag+'</span></div>';
        const table=(title,heads,rows,empty='Нет данных за выбранный период')=>'<section class="table-wrap"><div class="table-title">'+title+'</div><table class="table"><thead><tr>'+heads.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+(rows||'<tr><td colspan="'+heads.length+'" class="text-center">'+empty+'</td></tr>')+'</tbody></table></section>';
        if(view==='restaurants') {
            DOM.content.innerHTML=intro('Результаты ресторанов','Сравнение доступных ресторанов по выручке, прибыли и доле прибыли.')+
            table('Рейтинг ресторанов',['№','Ресторан','Выручка','Прибыль по отчёту','Доля прибыли'],restRows(restaurants));
        } else if(view==='imports') {
            DOM.content.innerHTML=intro('Загрузка и история','Импортируйте XLSX/CSV из iiko и отслеживайте последние загрузки.')+
            '<section class="panel"><h3>Новый отчёт</h3><p class="section-note">Выберите ресторан и загрузите файл до 10 МБ. Данные будут добавлены в аналитику.</p><button class="btn btn-primary" id="import-from-panel">＋ Загрузить файл iiko</button></section>'+
            table('История загрузок',['Файл','Ресторан','Строк','Дата','Статус'],importRows(imports),'Загрузок пока нет');
            document.getElementById('import-from-panel').addEventListener('click',openUploadModal);
        } else if(view==='products') {
            DOM.content.innerHTML=intro('Товарная аналитика','Рейтинг блюд и категорий по данным загруженных отчётов.')+
            '<section class="panel"><div class="loading">Загрузка товаров…</div></section>';
            loadProducts();
        } else if(view==='records') {
            DOM.content.innerHTML=intro('Детализация продаж','Журнал продаж с поиском по товарам, категориям и датам.')+
            '<section class="panel"><div class="detail-filters"><input type="text" class="form-input" placeholder="Название товара" id="inline-product"><input type="text" class="form-input" placeholder="Категория" id="inline-category"><input type="date" class="form-input" id="inline-from"><input type="date" class="form-input" id="inline-to"><button class="btn btn-primary" id="inline-search">Найти</button></div><div id="inline-results" aria-live="polite"><div class="loading">Загрузка записей…</div></div><div class="pagination" id="inline-pagination"></div></section>';
            document.getElementById('inline-search').addEventListener('click',()=>loadInlineRecords(1));
            loadInlineRecords(1);
        } else {
            const avg=o.total_items_sold>0?money(o.total_sales/o.total_items_sold):'—';
            const cards=[['Выручка',money(o.total_sales),'За выбранный период'],['Себестоимость',money(o.total_cost),'По загруженным отчётам'],['Прибыль по отчёту',money(o.total_profit),'Не равна чистой прибыли'],['На единицу / чек*',avg,'*В зависимости от типа отчёта']];
            const max=Math.max(1,...restaurants.map(r=>r.total_sales||0));
            const bars=restaurants.slice(0,6).map((r,i)=>'<div class="progress-item"><div class="pi-header"><span>'+esc(r.name)+'</span><span>'+money(r.total_sales)+'</span></div><div class="pi-bar-bg"><div class="pi-bar-fill '+['','green','yellow','red'][i%4]+'" style="width:'+Math.max(0,Math.min(100,100*r.total_sales/max))+'%"></div></div></div>').join('');
            DOM.content.innerHTML=intro('Продажи под контролем','Ключевые показатели сети на основе загруженных отчётов.')+
            '<section class="kpi-grid">'+cards.map(c=>'<div class="kpi-card"><div class="kpi-label">'+c[0]+'</div><div class="kpi-value">'+c[1]+'</div><div class="kpi-trend">'+c[2]+'</div></div>').join('')+'</section>'+
            '<div class="charts-row"><section class="chart-card"><div class="chart-header"><span class="chart-title">Динамика выручки</span><span class="chart-note">По дням</span></div>'+(trend.length?'<div class="chart-canvas-wrapper"><canvas id="chart-daily-trend" aria-label="График выручки"></canvas></div>':'<div class="empty-state"><strong>Пока нет данных</strong>Загрузите отчёт iiko для построения графика</div>')+'</section>'+
            '<section class="chart-card"><div class="chart-header"><span class="chart-title">Лидеры по выручке</span><span class="chart-note">Рестораны</span></div><div class="progress-list">'+(bars||'<div class="empty-state">Нет данных</div>')+'</div></section></div>'+
            table('Последние загрузки',['Файл','Ресторан','Строк','Дата','Статус'],importRows(imports.slice(0,5)),'Загрузок пока нет');
            requestAnimationFrame(()=>renderDailyTrendChart(trend));
        }
    }

    async function loadProducts() {
        const requestId=++state.productsRequest;
        try {
            const result=await apiFetch('/api/sales/products',{method:'POST',body:JSON.stringify({restaurant_key:DOM.restaurantSelect.value||null,period:DOM.periodSelect.value})});
            if(requestId!==state.productsRequest||state.view!=='products')return;
            const data=result.data||{}, products=data.products||[], categories=data.categories||[];
            const row=(r,i)=>'<tr><td>'+(i+1)+'</td><td><strong>'+esc(r.name)+'</strong></td><td>'+esc(r.category||'—')+'</td><td>'+formatNumber(r.quantity)+'</td><td>'+money(r.sales)+'</td><td>'+money(r.profit)+'</td></tr>';
            const categoryRow=(r,i)=>'<tr><td>'+(i+1)+'</td><td><strong>'+esc(r.name)+'</strong></td><td>'+formatNumber(r.quantity)+'</td><td>'+money(r.sales)+'</td><td>'+money(r.profit)+'</td></tr>';
            DOM.content.innerHTML='<div class="intro"><div><h2>Продажи по товарам</h2><p>Топ-100 товаров и топ-50 категорий по выручке за выбранный период.</p></div></div>'+
                '<section class="table-wrap"><div class="table-title">Рейтинг товаров</div><table class="table"><thead><tr><th>№</th><th>Товар</th><th>Категория</th><th>Количество</th><th>Выручка</th><th>Прибыль по отчёту</th></tr></thead><tbody>'+(products.map(row).join('')||'<tr><td colspan="6" class="text-center">Товарных данных нет. Загрузите отчёт с названиями товаров.</td></tr>')+'</tbody></table></section>'+
                '<section class="table-wrap"><div class="table-title">Категории</div><table class="table"><thead><tr><th>№</th><th>Категория</th><th>Количество</th><th>Выручка</th><th>Прибыль по отчёту</th></tr></thead><tbody>'+(categories.map(categoryRow).join('')||'<tr><td colspan="5" class="text-center">Нет категорий</td></tr>')+'</tbody></table></section>';
        }catch(e){if(requestId===state.productsRequest&&state.view==='products')DOM.content.innerHTML='<section class="panel"><div class="empty-state"><strong>Не удалось загрузить товары</strong>'+esc(e.message)+'</div><button class="btn btn-secondary" id="retry-products">Повторить</button></section>',document.getElementById('retry-products').addEventListener('click',loadProducts);}
    }

    async function loadInlineRecords(page=1) {
        if(state.view!=='records')return;
        state.detailPage=page;
        const target=document.getElementById('inline-results');
        target.innerHTML='<div class="loading">Загрузка…</div>';
        try{
            const res=await apiFetch('/api/sales/records',{method:'POST',body:JSON.stringify({
                restaurant_key:DOM.restaurantSelect.value||null,page,limit:50,
                product_name:document.getElementById('inline-product').value.trim()||null,
                category:document.getElementById('inline-category').value.trim()||null,
                date_from:document.getElementById('inline-from').value||null,
                date_to:document.getElementById('inline-to').value||null
            })});
            if(state.view!=='records')return;
            const d=res.data||{}, rows=d.records||[];
            target.innerHTML='<div class="table-wrap"><table class="table"><thead><tr><th>Дата</th><th>Ресторан</th><th>Товар</th><th>Категория</th><th>Количество</th><th>Выручка</th><th>Прибыль</th></tr></thead><tbody>'+
                (rows.map(r=>'<tr><td>'+formatDate(r.sale_date)+'</td><td>'+esc(r.restaurant_name||r.restaurant_key)+'</td><td>'+esc(r.product_name||'—')+'</td><td>'+esc(r.category||'—')+'</td><td>'+formatNumber(r.quantity)+'</td><td>'+money(r.total_amount)+'</td><td>'+money(r.profit_amount)+'</td></tr>').join('')||'<tr><td colspan="7" class="text-center">По выбранным фильтрам записей нет</td></tr>')+'</tbody></table></div>';
            const pager=document.getElementById('inline-pagination');pager.replaceChildren();
            const info=document.createElement('span');info.textContent='Записей: '+formatNumber(d.total||0)+' · Страница '+page+' из '+(d.pages||1);pager.appendChild(info);
            if(page>1){const prev=document.createElement('button');prev.className='btn btn-secondary';prev.textContent='← Назад';prev.addEventListener('click',()=>loadInlineRecords(page-1));pager.appendChild(prev);}
            if(page<(d.pages||1)){const next=document.createElement('button');next.className='btn btn-secondary';next.textContent='Далее →';next.addEventListener('click',()=>loadInlineRecords(page+1));pager.appendChild(next);}
        }catch(e){target.innerHTML='<div class="empty-state"><strong>Ошибка загрузки</strong>'+esc(e.message)+'</div>';}
    }

    function renderDailyTrendChart(trend) {
        const canvas = document.getElementById('chart-daily-trend');
        if (!canvas || !trend || trend.length === 0) return;

        const container = canvas.parentElement;
        const rect = container.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;

        const dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = rect.height + 'px';

        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        const W = rect.width;
        const H = rect.height;

        const padding = { top: 20, right: 20, bottom: 40, left: 60 };
        const chartW = W - padding.left - padding.right;
        const chartH = H - padding.top - padding.bottom;

        const maxVal = Math.max(...trend.map(t => t.sales || 0), 1);

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

        // Столбцы
        const barWidth = Math.max(4, (chartW / trend.length) * 0.5);
        trend.forEach((t, i) => {
            const x = padding.left + (i / Math.max(trend.length - 1, 1)) * chartW;
            const h = ((t.sales || 0) / maxVal) * chartH;
            const y = padding.top + chartH - h;

            ctx.fillStyle = '#c92c35';
            ctx.beginPath();
            if (ctx.roundRect) {
                ctx.roundRect(x - barWidth / 2, y, barWidth, h, [4, 4, 0, 0]);
            } else {
                ctx.rect(x - barWidth / 2, y, barWidth, h);
            }
            ctx.fill();
        });

        // Подписи дат
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

    // --- MODALS ---
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
        if (!/\.(xlsx|csv)$/i.test(file.name) || file.size > 10 * 1024 * 1024) {
            state.uploadFile = null;
            DOM.btnUpload.disabled = true;
            showToast('Допустимы файлы XLSX/CSV до 10 МБ', 'error');
            return;
        }
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

    async function loadRecords(page = 1) {
        state.detailPage = page;
        try {
            const res = await apiFetch('/api/sales/records', {
                method: 'POST',
                body: JSON.stringify({
                    restaurant_key: DOM.restaurantSelect.value || null, page, limit: 50,
                    product_name: document.getElementById('detail-search-product').value.trim() || null,
                    category: document.getElementById('detail-search-category').value.trim() || null,
                    date_from: document.getElementById('detail-date-from').value || null,
                    date_to: document.getElementById('detail-date-to').value || null,
                }),
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
                    <td>${esc(r.restaurant_name || r.restaurant_key)}</td>
                    <td>${esc(r.product_name || '—')}</td>
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

    function bindEvents() {
        document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{
            state.view=button.dataset.view;
            document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b===button));
            document.getElementById('view-title').textContent=button.textContent.trim();
            document.getElementById('sales-sidebar').classList.remove('open');
            if(state.dashboardData) renderDashboard(state.dashboardData); else loadDashboard();
        }));
        document.getElementById('menu-toggle').addEventListener('click',()=>document.getElementById('sales-sidebar').classList.toggle('open'));

        DOM.periodSelect.addEventListener('change', loadDashboard);
        DOM.restaurantSelect.addEventListener('change', loadDashboard);

        // Одна кнопка загрузки отчёта iiko
        document.getElementById('btn-import-iiko').addEventListener('click', openUploadModal);

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
        document.getElementById('btn-export').addEventListener('click', async () => {
            try {
                const file = await apiFetch('/api/sales/export', {
                    method: 'POST',
                    body: JSON.stringify({
                        restaurant_key: DOM.restaurantSelect.value,
                        period: DOM.periodSelect.value
                    })
                }, 'blob');
                const url = URL.createObjectURL(file);
                const link = document.createElement('a');
                link.href = url;
                link.download = 'sales.xlsx';
                link.click();
                setTimeout(() => URL.revokeObjectURL(url), 1000);
            } catch (error) {
                showToast(error.message, 'error');
            }
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

        window.addEventListener('resize', () => {
            if (state.dashboardData) renderDashboard(state.dashboardData);
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
