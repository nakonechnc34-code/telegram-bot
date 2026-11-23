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
        recordsRequest: 0,
    };

    const DOM = {};

    function cacheDOM() {
        DOM.content = document.getElementById('sales-page-content');
        DOM.restaurantSelect = document.getElementById('restaurant-select');
        DOM.periodSelect = document.getElementById('period-select');
        DOM.dateFrom = document.getElementById('sales-date-from');
        DOM.dateTo = document.getElementById('sales-date-to');
        DOM.comparisonDate = document.getElementById('comparison-date');
        DOM.comparisonHour = document.getElementById('comparison-hour');
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

    function getToken() { return sessionStorage.getItem('wokker_sales_token') || null; }
    function showSalesLogin(message='') {
        sessionStorage.removeItem('wokker_sales_token');
        state.token = null;
        document.getElementById('sales-app-shell').hidden = true;
        document.getElementById('sales-login-screen').hidden = false;
        document.getElementById('sales-login-error').textContent = message;
    }
    function showSalesApp() {
        document.getElementById('sales-login-screen').hidden = true;
        document.getElementById('sales-app-shell').hidden = false;
    }
    async function submitSalesLogin(event) {
        event.preventDefault();
        const login = document.getElementById('sales-login-name').value.trim();
        const password = document.getElementById('sales-login-password').value;
        const errorEl = document.getElementById('sales-login-error');
        errorEl.textContent = '';
        try {
            const response = await fetch('/api/sales/login', {
                method:'POST', headers:{'Content-Type':'application/json'},
                body:JSON.stringify({login,password})
            });
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.error || 'Ошибка входа');
            sessionStorage.setItem('wokker_sales_token', result.token);
            document.getElementById('sales-login-password').value = '';
            await startSales();
        } catch (error) { errorEl.textContent = error.message; }
    }
    async function salesLogout() {
        try { await apiFetch('/api/sales/logout', {method:'POST',body:'{}'}); } catch (_) {}
        showSalesLogin();
    }
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
        if (res.status === 401 || res.status === 403) { showSalesLogin('Сессия завершена или право доступа отозвано'); throw new Error('unauthorized'); }
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
        if (period === 'custom' && (!DOM.dateFrom.value || !DOM.dateTo.value)) {
            DOM.content.innerHTML = '<div class="loading">Выберите начало и конец периода</div>';
            return;
        }
        if (period === 'custom' && DOM.dateFrom.value > DOM.dateTo.value) {
            DOM.content.innerHTML = '<div class="loading">Дата начала должна быть не позднее даты окончания</div>';
            return;
        }

        try {
            const res = await apiFetch('/api/sales/dashboard', {
                method: 'POST',
                body: JSON.stringify({ restaurant_key: restaurantKey, period, date_from: DOM.dateFrom.value, date_to: DOM.dateTo.value, comparison_date: DOM.comparisonDate.value, comparison_hour: Number(DOM.comparisonHour.value) }),
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
        return rows.map((r,i) => '<tr><td>'+(i+1)+'</td><td><strong>'+esc(r.name)+'</strong></td><td>'+money(r.total_sales)+'</td></tr>').join('');
    }
    function importRows(rows) {
        return rows.map(imp => '<tr><td><strong>'+esc(imp.filename)+'</strong></td><td>'+
            esc(state.restaurants.find(r=>r.key===imp.restaurant_key)?.name||imp.restaurant_key)+
            '</td><td>'+formatNumber(imp.rows_count)+'</td><td>'+formatDate(imp.upload_date)+
            '</td><td><span class="status-pill '+(imp.status==='completed'?'':'pending')+'">'+
            esc(imp.status==='completed'?'Загружен':imp.status==='replaced'?'Заменён':imp.status==='error'?'Ошибка':imp.status)+
            '</span></td><td><button type="button" class="btn btn-secondary sales-delete-import" data-import-id="'+
            Number(imp.id)+'" aria-label="Удалить отчёт '+esc(imp.filename)+'"'+
            (imp.can_delete === false ? ' disabled title="В отчёте есть рестораны вне вашей территории. Удаление доступно супер-администратору."' : '')+
            '>'+(imp.can_delete === false ? 'Нет прав на удаление' : 'Удалить')+'</button></td></tr>').join('');
    }

    async function deleteImport(importId) {
        const imp = (state.dashboardData?.imports || []).find(item => item.id === importId);
        if (!imp) return;
        if (imp.can_delete === false) {
            showToast('Отчёт содержит рестораны вне вашей территории. Обратитесь к супер-администратору.', 'error');
            return;
        }
        if (!window.confirm('Удалить отчёт «'+imp.filename+'»? Связанные с ним данные продаж будут удалены из аналитики. Действие нельзя отменить.')) return;
        const button = DOM.content.querySelector('.sales-delete-import[data-import-id="'+importId+'"]');
        if (button) button.disabled = true;
        try {
            const result = await apiFetch('/api/sales/imports/delete', {
                method: 'POST', body: JSON.stringify({import_id: importId})
            });
            showToast('Отчёт удалён. Удалено строк продаж: '+formatNumber(result.deleted_records));
            await loadDashboard();
        } catch (error) {
            if (button) button.disabled = false;
            showToast('Не удалось удалить отчёт: '+error.message, 'error');
        }
    }

    function renderDashboard(data) {
        const {overview:o, daily_trend:trend=[], by_restaurant:restaurants=[], hourly_revenue:hourly=[], hourly_by_order_type:hourlyTypes=[], by_order_type:orderTypes=[], previous_total_sales:previousSales=0, same_weekday_comparison:weekCompare=null, imports=[]} = data;
        const view=state.view;
        const intro = (title,subtitle,tag='ДАННЫЕ ИЗ ОТЧЁТОВ') => '<div class="intro"><div><h2>'+title+'</h2><p>'+subtitle+'</p></div><span class="eyebrow-tag">'+tag+'</span></div>';
        const table=(title,heads,rows,empty='Нет данных за выбранный период')=>'<section class="table-wrap"><div class="table-title">'+title+'</div><table class="table"><thead><tr>'+heads.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+(rows||'<tr><td colspan="'+heads.length+'" class="text-center">'+empty+'</td></tr>')+'</tbody></table></section>';
        if(view==='settings') {
            DOM.content.innerHTML=intro('Настройки типов заказа','Управляйте распределением продаж по каналам. Изменения применяются к аналитике.')+'<section class="panel sales-workflow-card"><div class="sales-workflow-icon" aria-hidden="true">⚙</div><div><h3>Классификация заказов</h3><p class="section-note">Назначьте каждому способу оплаты тип заказа: Зал, Доставка или Не распределено.</p></div></section><section class="panel"><div class="loading">Загрузка настроек…</div></section>';
            loadOrderTypeSettings();
        } else if(view==='restaurants') {
            DOM.content.innerHTML=intro('ТО ресторанов','Сравнение ресторанов по товарообороту.')+
            table('Рейтинг ресторанов',['№','Ресторан','ТО'],restRows(restaurants));
        } else if(view==='reports') {
            // Reports are calculated automatically from the same authorized,
            // date-filtered dataset as the dashboard; no extra upload needed.
            const change=(current,previous)=>previous>0?((current-previous)*100/previous).toFixed(1)+'%':'—';
            const compareHours=weekCompare?.hours||[];
            const reportList=[
                ['Динамика выручки по дням', ['Дата','ТО'], trend.map(t=>'<tr><td>'+formatDate(t.date)+'</td><td>'+money(t.sales)+'</td></tr>').join('')],
                ['Товарооборот по ресторанам', ['Ресторан','ТО'], restaurants.map(r=>'<tr><td>'+esc(r.name)+'</td><td>'+money(r.total_sales)+'</td></tr>').join('')],
                ['Типы заказов: сравнение периодов', ['Тип','Текущий ТО','Предыдущий ТО','Изменение'],orderTypes.map(t=>'<tr><td>'+esc(t.typ)+'</td><td>'+money(t.sales)+'</td><td>'+money(t.previous_sales)+'</td><td>'+change(t.sales,t.previous_sales)+'</td></tr>').join('')],
                ['Почасовая выручка', ['Час','ТО','Чеки'],hourly.map(h=>'<tr><td>'+String(h.hour).padStart(2,'0')+':00</td><td>'+money(h.sales)+'</td><td>'+formatNumber(h.checks)+'</td></tr>').join('')],
                ['Зал и доставка по часам', ['Час','Зал','Доставка','Не распределено'],hourlyTypes.map(h=>'<tr><td>'+String(h.hour).padStart(2,'0')+':00</td><td>'+money(h['Зал'])+'</td><td>'+money(h['Доставка'])+'</td><td>'+money(h['Не распределено'])+'</td></tr>').join('')]
            ];
            if(weekCompare) reportList.push(['Сравнение с тем же днём прошлой недели', ['Час','Выбранный день','Неделю назад','Изменение'],
                compareHours.map(h=>'<tr><td>'+String(h.hour).padStart(2,'0')+':00</td><td>'+money(h.current)+'</td><td>'+money(h.previous)+'</td><td>'+(weekCompare.has_current&&weekCompare.has_previous?change(h.current,h.previous):'—')+'</td></tr>').join('')]);
            DOM.content.innerHTML=intro('Автоматические отчёты','Формируются из загруженных данных iiko с учётом выбранного ресторана и периода.','АВТОМАТИЧЕСКИ')+ '<div class="sales-section-stats"><div><span>Товарооборот за период</span><strong>'+money(o.total_sales||0)+'</strong></div><div><span>Отчётных таблиц</span><strong>'+reportList.length+'</strong></div><div><span>Ресторанов в отчёте</span><strong>'+restaurants.length+'</strong></div></div>'+
                '<section class="panel"><h3>Отчётность без ручной подготовки</h3><p class="section-note">Выберите период и ресторан в верхней панели. Все таблицы пересчитываются автоматически. Для выгрузки используйте кнопку «Экспорт».</p></section>'+
                reportList.map(item=>table(item[0],item[1],item[2])).join('');
        } else if(view==='imports') {
            DOM.content.innerHTML=intro('Импорт iiko','Загружайте XLSX/CSV из iiko и контролируйте историю обработки.')+ '<div class="sales-section-stats"><div><span>Загрузок в истории</span><strong>'+imports.length+'</strong></div><div><span>Форматы</span><strong>XLSX / CSV</strong></div><div><span>Повторная загрузка</span><strong>Замена данных</strong></div></div>'+
            '<section class="panel sales-import-hero"><div class="sales-import-hero-mark" aria-hidden="true">⇧</div><h3>Новый отчёт</h3><p class="section-note">Выберите ресторан и загрузите файл до 10 МБ. Данные за совпадающие даты и рестораны будут заменены, а не сложены.</p><button class="btn btn-primary" id="import-from-panel">＋ Загрузить файл iiko</button></section>'+
            table('История загрузок',['Файл','Ресторан','Строк','Дата','Статус','Действия'],importRows(imports),'Загрузок пока нет');
            document.getElementById('import-from-panel').addEventListener('click',openUploadModal);
            DOM.content.querySelectorAll('.sales-delete-import').forEach(button => button.addEventListener('click', () => deleteImport(Number(button.dataset.importId))));
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
            const growth=(current,previous)=>previous>0?((current-previous)*100/previous):null;
            const growthLabel=(current,previous)=>{const n=growth(current,previous);return n===null?'—':(n>0?'+':'')+n.toFixed(1)+'%';};
            const growthClass=(current,previous)=>{const n=growth(current,previous);return n===null?'':n<0?'negative':'positive';};
            const total=o.total_sales||0;
            const previous=previousSales||0;
            const week=weekCompare||{};
            const currentWeek=Object.values(week.current||{}).reduce((v,n)=>v+Number(n||0),0);
            const previousWeek=Object.values(week.previous||{}).reduce((v,n)=>v+Number(n||0),0);

            const currentDate = DOM.comparisonDate.value || new Date().toISOString().slice(0,10);
            const cutoff = DOM.comparisonHour.value || '24';
            const isCompared = !!(week.has_current && week.has_previous);
            const signedChange = (current,prior) => {
                const n=growth(current,prior);
                return '<span class="sales-change '+growthClass(current,prior)+'">'+(n===null?'Нет базы':(n>0?'↑ ':n<0?'↓ ':'→ ')+Math.abs(n).toFixed(1)+'%')+'</span>';
            };
            const kpi=(icon,title,value,subtitle,change)=>'<article class="sales-v2-kpi"><div class="sales-v2-kpi-heading"><span class="sales-v2-icon">'+icon+'</span><span>'+title+'</span></div><strong>'+value+'</strong><div class="sales-v2-kpi-footer">'+(change||'')+'<span>'+subtitle+'</span></div></article>';
            const availableDates=trend.length?formatDate(trend[0].date)+' — '+formatDate(trend[trend.length-1].date):'Нет загруженных данных';
            const totalHours=hourly.reduce((sum,h)=>sum+Number(h.sales||0),0);
            const topRestaurants=restaurants.filter(r=>Number(r.total_sales)>0).slice(0,8);
            const maxRestaurant=Math.max(1,...topRestaurants.map(r=>Number(r.total_sales||0)));
            const maxChannel=Math.max(1,...orderTypes.map(r=>Number(r.sales||0)));
            const rankedRestaurants=topRestaurants.map((r,i)=>'<div class="sales-v2-rank"><span class="sales-v2-rank-number">'+String(i+1).padStart(2,'0')+'</span><div class="sales-v2-rank-body"><div class="sales-v2-rank-top"><span>'+esc(r.name)+'</span><strong>'+money(r.total_sales)+'</strong></div><div class="sales-v2-meter"><span style="width:'+Math.max(2,Number(r.total_sales||0)/maxRestaurant*100).toFixed(1)+'%"></span></div></div></div>').join('');
            const channels=orderTypes.map(r=>'<div class="sales-v2-rank"><div class="sales-v2-rank-body"><div class="sales-v2-rank-top"><span>'+esc(r.type||r.typ)+'</span><strong>'+money(r.sales)+'</strong></div><div class="sales-v2-meter channel"><span style="width:'+Math.max(2,Number(r.sales||0)/maxChannel*100).toFixed(1)+'%"></span></div></div></div>').join('');
            const hourRows=hourly.map(h=>'<tr><td>'+String(h.hour).padStart(2,'0')+':00</td><td>'+money(h.sales)+'</td></tr>').join('');
            const comparedHours=(week.hours||[]).map(h=>'<tr><td>'+String(h.hour).padStart(2,'0')+':00</td><td>'+money(h.current)+'</td><td>'+money(h.previous)+'</td><td>'+signedChange(h.current,h.previous)+'</td></tr>').join('');
            const options=state.restaurants.map(r=>'<label class="rest-restaurant-option"><input type="checkbox" class="rest-restaurant-check" value="'+esc(r.key)+'" '+(!DOM.restaurantSelect.value||DOM.restaurantSelect.value===r.key?'checked':'')+'><span>'+esc(r.name)+'</span></label>').join('');
            DOM.content.innerHTML=
                '<div class="sales-v2-dashboard">'+
                '<div class="sales-v2-heading"><div><div class="sales-v2-eyebrow">АНАЛИТИКА / ОБЗОР</div><h2>Показатели продаж</h2><p>Актуальная аналитика по загруженным отчётам iiko · '+esc(availableDates)+'</p></div><div class="sales-v2-status"><span class="sales-v2-status-dot"></span> Данные из iiko</div></div>'+
                '<div class="sales-v2-toolbar"><div class="sales-v2-presets">'+[['1d','Сегодня'],['7d','7 дней'],['30d','30 дней'],['90d','90 дней'],['365d','Год'],['custom','Свой период']].map(p=>'<button type="button" class="rest-period '+(DOM.periodSelect.value===p[0]?'selected':'')+'" data-rest-period="'+p[0]+'">'+p[1]+'</button>').join('')+'</div><span class="sales-v2-toolbar-hint">Период и ресторан можно изменить в верхней панели</span></div>'+
                '<div class="sales-v2-kpis">'+
                  kpi('₽','Товарооборот',money(total),'к предыдущему периоду',signedChange(total,previous))+
                  kpi('↗','Предыдущий период',money(previous),'сопоставимый период','')+
                  kpi('◷','Выручка по часам',money(totalHours),'по загруженным часам','')+
                  kpi('⌁','Рестораны с продажами',formatNumber(restaurants.filter(r=>Number(r.total_sales)>0).length),'за выбранный период','')+
                '</div>'+
                '<div class="sales-v2-layout"><div class="sales-v2-main">'+
                  '<section class="sales-v2-panel sales-v2-trend"><div class="sales-v2-panel-head"><div><div class="sales-v2-eyebrow">ДИНАМИКА</div><h3>Выручка по дням</h3></div><span class="sales-v2-muted">'+esc(availableDates)+'</span></div>'+(trend.length?'<div class="rest-graph-area"><canvas id="chart-daily-trend" aria-label="Динамика выручки"></canvas></div>':'<div class="empty-state">Нет данных. Загрузите отчёт iiko.</div>')+'<div class="sales-v2-legend"><span><i></i> Выручка за период</span><span>Предыдущий период: '+money(previous)+'</span></div></section>'+
                  '<section class="sales-v2-panel"><div class="sales-v2-panel-head"><div><div class="sales-v2-eyebrow">СРАВНЕНИЕ</div><h3>Этот день / прошлая неделя</h3></div><span class="sales-v2-muted">Срез до '+esc(String(week.cutoff_hour??cutoff).padStart(2,'0'))+':00</span></div>'+
                    '<div class="sales-v2-compare-grid"><div><span>Выбранный день</span><strong>'+(isCompared?money(currentWeek):'—')+'</strong></div><div><span>Неделю назад</span><strong>'+(isCompared?money(previousWeek):'—')+'</strong></div><div><span>Динамика</span><strong>'+(isCompared?signedChange(currentWeek,previousWeek):'Нет данных')+'</strong></div></div>'+
                    '<p class="sales-v2-muted">День сравнения: '+esc(formatDate(currentDate))+'. Выберите дату и час в верхней панели.</p>'+
                    '<div class="sales-v2-table-scroll"><table class="sales-v2-table"><thead><tr><th>Час</th><th>Текущий день</th><th>Неделю назад</th><th>Изменение</th></tr></thead><tbody>'+(isCompared&&comparedHours?comparedHours:'<tr><td colspan="4">Недостаточно данных для сравнения</td></tr>')+'</tbody></table></div></section>'+
                  '<section class="sales-v2-panel"><div class="sales-v2-panel-head"><div><div class="sales-v2-eyebrow">ПОЧАСОВАЯ АНАЛИТИКА</div><h3>Выручка по часам</h3></div></div><div class="sales-v2-table-scroll"><table class="sales-v2-table"><thead><tr><th>Час</th><th>Товарооборот</th></tr></thead><tbody>'+(hourRows||'<tr><td colspan="2">Нет почасовых данных</td></tr>')+'</tbody></table></div></section>'+
                '</div><aside class="sales-v2-aside">'+
                  '<section class="sales-v2-panel"><div class="sales-v2-panel-head"><div><div class="sales-v2-eyebrow">РЕЙТИНГ</div><h3>Рестораны по ТО</h3></div></div><div class="sales-v2-ranking">'+(rankedRestaurants||'<p>Нет данных</p>')+'</div></section>'+
                  '<section class="sales-v2-panel"><div class="sales-v2-panel-head"><div><div class="sales-v2-eyebrow">СТРУКТУРА ПРОДАЖ</div><h3>Каналы продаж</h3></div></div><div class="sales-v2-ranking">'+(channels||'<p>Нет данных</p>')+'</div></section>'+
                  '<section class="sales-v2-panel sales-v2-restaurant-panel"><div class="sales-v2-panel-head"><div><div class="sales-v2-eyebrow">ФИЛЬТР</div><h3>Рестораны</h3></div></div><p class="sales-v2-muted">Выберите один ресторан или все доступные</p><input id="rest-search" type="search" placeholder="Найти ресторан…" aria-label="Поиск по ресторанам"><div class="rest-restaurant-list"><label class="rest-restaurant-option"><input type="checkbox" id="rest-all" '+(!DOM.restaurantSelect.value?'checked':'')+'> Все рестораны</label>'+options+'</div></section>'+
                '</aside></div></div>';
            DOM.content.querySelectorAll('[data-rest-period]').forEach(button=>button.addEventListener('click',()=>{DOM.periodSelect.value=button.dataset.restPeriod;DOM.periodSelect.dispatchEvent(new Event('change'));}));
            const search=document.getElementById('rest-search');
            search.addEventListener('input',()=>{const term=search.value.toLocaleLowerCase('ru');DOM.content.querySelectorAll('.rest-restaurant-check').forEach(input=>{input.closest('label').hidden=!input.closest('label').textContent.toLocaleLowerCase('ru').includes(term);});});
            document.getElementById('rest-all').addEventListener('change',()=>{DOM.restaurantSelect.value='';loadDashboard();});
            DOM.content.querySelectorAll('.rest-restaurant-check').forEach(input=>input.addEventListener('change',()=>{DOM.restaurantSelect.value=input.value;loadDashboard();}));
            requestAnimationFrame(()=>renderDailyTrendChart(trend));
        }
    }

    async function loadOrderTypeSettings() {
        try {
            const res=await apiFetch('/api/sales/order-type-settings',{method:'POST',body:JSON.stringify({action:'get'})});
            if(state.view!=='settings')return;
            const d=res.data||{}, mapping=d.mapping||{}, methods=d.methods||[];
            DOM.content.innerHTML='<div class="intro"><div><h2>Типы заказов</h2><p>Каждый способ оплаты из отчёта iiko относится к Залу, Доставке или нераспределённым. Изменения применяются к ранее загруженным данным.</p></div></div>'+
                '<section class="panel"><h3>Распределение способов оплаты</h3><p class="section-note">Неизвестные способы оплаты остаются нераспределёнными, пока администратор не назначит тип.</p>'+
                '<div class="table-wrap"><table class="table"><thead><tr><th>Способ оплаты iiko</th><th>Тип заказа</th></tr></thead><tbody>'+
                methods.map((m,i)=>'<tr><td>'+esc(m)+'</td><td><select class="form-input order-type-select" data-method="'+esc(m)+'" '+(d.can_edit?'':'disabled')+'>'+
                    ['Зал','Доставка','Не распределено'].map(t=>'<option value="'+t+'" '+((mapping[m]||'Не распределено')===t?'selected':'')+'>'+t+'</option>').join('')+'</select></td></tr>').join('')+
                '</tbody></table></div>'+(d.can_edit?'<button class="btn btn-primary" id="save-order-types">Сохранить настройки</button>':'<p class="section-note">Редактирование доступно администратору сети.</p>')+'</section>';
            if(d.can_edit)document.getElementById('save-order-types').addEventListener('click',async()=>{
                const updated={};
                document.querySelectorAll('.order-type-select').forEach(select=>{updated[select.dataset.method]=select.value;});
                const btn=document.getElementById('save-order-types');btn.disabled=true;
                try{
                    await apiFetch('/api/sales/order-type-settings',{method:'POST',body:JSON.stringify({action:'save',mapping:updated})});
                    state.dashboardData=null;
                    showToast('Настройки типов заказа сохранены');
                }catch(e){showToast('Ошибка сохранения: '+e.message,'error');}
                finally{btn.disabled=false;}
            });
        }catch(e){if(state.view==='settings')DOM.content.innerHTML='<section class="panel"><div class="empty-state">Не удалось загрузить настройки: '+esc(e.message)+'</div></section>';}
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
        const requestId=++state.recordsRequest;
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
            if(state.view!=='records'||requestId!==state.recordsRequest)return;
            const d=res.data||{}, rows=d.records||[];
            target.innerHTML='<div class="table-wrap"><table class="table"><thead><tr><th>Дата</th><th>Ресторан</th><th>Товар</th><th>Категория</th><th>Количество</th><th>Выручка</th><th>Прибыль</th></tr></thead><tbody>'+
                (rows.map(r=>'<tr><td>'+formatDate(r.sale_date)+'</td><td>'+esc(r.restaurant_name||r.restaurant_key)+'</td><td>'+esc(r.product_name||'—')+'</td><td>'+esc(r.category||'—')+'</td><td>'+formatNumber(r.quantity)+'</td><td>'+money(r.total_amount)+'</td><td>'+money(r.profit_amount)+'</td></tr>').join('')||'<tr><td colspan="7" class="text-center">По выбранным фильтрам записей нет</td></tr>')+'</tbody></table></div>';
            const pager=document.getElementById('inline-pagination');pager.replaceChildren();
            const info=document.createElement('span');info.textContent='Записей: '+formatNumber(d.total||0)+' · Страница '+page+' из '+(d.pages||1);pager.appendChild(info);
            if(page>1){const prev=document.createElement('button');prev.className='btn btn-secondary';prev.textContent='← Назад';prev.addEventListener('click',()=>loadInlineRecords(page-1));pager.appendChild(prev);}
            if(page<(d.pages||1)){const next=document.createElement('button');next.className='btn btn-secondary';next.textContent='Далее →';next.addEventListener('click',()=>loadInlineRecords(page+1));pager.appendChild(next);}
        }catch(e){if(state.view==='records'&&requestId===state.recordsRequest)target.innerHTML='<div class="empty-state"><strong>Ошибка загрузки</strong>'+esc(e.message)+'</div>';}
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
            ++state.recordsRequest;
            ++state.productsRequest;
            document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b===button));
            document.getElementById('view-title').textContent=button.textContent.trim();
            document.getElementById('sales-sidebar').classList.remove('open');
            if(state.view==='settings') renderDashboard(state.dashboardData||{overview:{},daily_trend:[],by_restaurant:[],imports:[]});
            else if(state.dashboardData) renderDashboard(state.dashboardData); else loadDashboard();
        }));
        document.getElementById('menu-toggle').addEventListener('click',()=>document.getElementById('sales-sidebar').classList.toggle('open'));

        function updateDateControls() {
            const custom = DOM.periodSelect.value === 'custom';
            document.getElementById('custom-from-field').hidden = !custom;
            document.getElementById('custom-to-field').hidden = !custom;
            loadDashboard();
        }
        DOM.periodSelect.addEventListener('change', updateDateControls);
        DOM.dateFrom.addEventListener('change', () => { if (DOM.periodSelect.value === 'custom') loadDashboard(); });
        DOM.dateTo.addEventListener('change', () => { if (DOM.periodSelect.value === 'custom') loadDashboard(); });
        DOM.restaurantSelect.addEventListener('change', loadDashboard);
        DOM.comparisonDate.addEventListener('change', loadDashboard);
        DOM.comparisonHour.addEventListener('change', loadDashboard);

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
                        period: DOM.periodSelect.value,
                        date_from: DOM.dateFrom.value,
                        date_to: DOM.dateTo.value
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

    async function startSales() {
        state.token = getToken();
        if (!state.token) { showSalesLogin(); return; }
        try {
            const meRes = await apiFetch('/api/sales/me', {method:'POST',body:'{}'});
            DOM.adminAvatar.textContent = (meRes.full_name || 'W').charAt(0).toUpperCase();
        } catch (_) { showSalesLogin('Войдите по логину и паролю'); return; }
        showSalesApp();
        const moscow = new Date(new Date().toLocaleString('en-US', {timeZone:'Europe/Moscow'}));
        const pad=n=>String(n).padStart(2,'0');
        DOM.comparisonDate.value=moscow.getFullYear()+'-'+pad(moscow.getMonth()+1)+'-'+pad(moscow.getDate());
        DOM.comparisonHour.innerHTML=Array.from({length:25},(_,hour)=>'<option value="'+hour+'">До '+pad(hour)+':00</option>').join('');
        DOM.comparisonHour.value=String(moscow.getHours());
        await loadRestaurants();
        loadDashboard();
        if (!state.eventsBound) {
            bindEvents();
            state.eventsBound = true;
            window.addEventListener('resize', () => {
                if (state.dashboardData) renderDashboard(state.dashboardData);
            });
        }
    }

    async function init() {
        cacheDOM();
        document.getElementById('sales-login-form').addEventListener('submit',submitSalesLogin);
        document.getElementById('sales-logout').addEventListener('click',salesLogout);
        if (!getToken()) { showSalesLogin(); return; }
        await startSales();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
