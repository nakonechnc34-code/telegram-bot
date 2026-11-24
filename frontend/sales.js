(function () {
    'use strict';

    const state = {
        token: null,
        restaurantKey: null,
        period: '1d',
        restaurants: [],
        dashboardData: null,
        uploadFile: null,
        detailPage: 1,
        view: 'overview',
        dashboardRequest: 0,
        selectedRestaurants: null,
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
        DOM.sidebar = document.getElementById('sales-sidebar');
        DOM.sidebarClose = document.getElementById('sales-sidebar-close');
        DOM.sidebarBackdrop = document.getElementById('sales-sidebar-backdrop');
        DOM.menuToggle = document.getElementById('menu-toggle');
        DOM.workspace = document.querySelector('.workspace');
    }

    function getToken() { return sessionStorage.getItem('wokker_sales_token') || null; }
    function showSalesLogin(message='') {
        sessionStorage.removeItem('wokker_sales_token');
        state.token = null;
        setSalesMenuOpen(false, false);
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
        if (period !== 'custom') dashboardDateRange();
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
                body: JSON.stringify({ restaurant_key: restaurantKey, restaurant_keys: state.selectedRestaurants, period, date_from: DOM.dateFrom.value, date_to: DOM.dateTo.value }),
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


    function renderHourlyComparison(){
        const now=new Date(), today=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
        const priorDate=new Date(today+'T12:00:00Z');priorDate.setUTCDate(priorDate.getUTCDate()-7);
        const hour=Number(new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Moscow',hour:'2-digit',hourCycle:'h23'}).format(now));
        DOM.content.innerHTML='<section class="panel sales-hourly-report"><h2>Сравнение ежечастно</h2><p>Накопленный ТО до выбранного часа (МСК). Сравниваются одинаковые часы обеих дат.</p><div class="hourly-report-filters"><label>Предыдущая дата <input class="form-input" type="date" id="hourly-prior" value="'+priorDate.toISOString().slice(0,10)+'"></label><label>Текущая дата <input class="form-input" type="date" id="hourly-current" value="'+today+'"></label><label>До времени <select class="form-input" id="hourly-cutoff">'+Array.from({length:25},(_,h)=>'<option value="'+h+'" '+(h===hour?'selected':'')+'>'+String(h).padStart(2,'0')+':00</option>').join('')+'</select></label><button class="btn btn-primary" id="hourly-refresh">Сформировать</button></div><div id="hourly-result" aria-live="polite"></div></section>';
        const result=document.getElementById('hourly-result');
        let request=0;
        async function load(){
            const id=++request;
            const current=document.getElementById('hourly-current').value,previous=document.getElementById('hourly-prior').value,cutoff=Number(document.getElementById('hourly-cutoff').value);
            if(!current||!previous||current===previous){result.textContent='Выберите две разные даты';return;}
            result.textContent='Загрузка…';
            try{
                const res=await apiFetch('/api/sales/hourly-comparison',{method:'POST',body:JSON.stringify({current,previous,cutoff})});
                if(id!==request||!result.isConnected)return;
                const rows=res.data||[];
                const value=(x,k)=>x==null?null:x[k];
                const cell=v=>v==null?'—':money(v);
                const change=(a,b)=>a==null||b==null?null:a-b;
                const percent=(a,b)=>a==null||b==null||b===0?null:(a/b-1)*100;
                const tone=d=>d>0?'hourly-up':d<0?'hourly-down':'';
                const delta=(a,b)=>{const d=change(a,b),p=percent(a,b);return '<td class="'+tone(d)+'">'+(d==null?'—':(d>0?'+':'')+money(d))+'</td><td class="'+tone(p)+'">'+(p==null?'—':(p>0?'+':'')+p.toFixed(1).replace('.',',')+'%')+'</td>';};
                const sum=(side,items=rows)=>items.length&&items.every(r=>r[side]!=null)?Object.fromEntries(['hall','delivery','total'].map(k=>[k,items.reduce((a,r)=>a+r[side][k],0)])):null;
                const groups=new Map();
                for(const r of rows){
                    const key=r.territory_manager_id??'unassigned';
                    if(!groups.has(key))groups.set(key,{name:r.territory_manager_name||(r.territory_manager_id==null?'Без территории':'ТУ #'+r.territory_manager_id),items:[]});
                    groups.get(key).items.push(r);
                }
                const company={name:'Компания (доступные рестораны)',current:sum('current'),previous:sum('previous')};
                const heading='<thead><tr><th>Канал продаж</th><th>'+esc(formatDate(previous))+'</th><th>'+esc(formatDate(current))+'</th><th>Разница, ₽</th><th>Динамика, %</th></tr></thead>';
                const lines=r=>['hall','delivery','total'].map(k=>'<tr class="'+(k==='total'?'hourly-total':'')+'"><th>'+({hall:'Зал',delivery:'Доставка',total:'Общий ТО'}[k])+'</th><td>'+cell(value(r.previous,k))+'</td><td>'+cell(value(r.current,k))+'</td>'+delta(value(r.current,k),value(r.previous,k))+'</tr>').join('');
                const block=(r,kind='')=>'<tr class="hourly-restaurant-heading '+kind+'"><th colspan="5">'+esc(r.name)+'</th></tr>'+lines(r);
                const mobileCard=(r,kind='')=>'<article class="hourly-mobile-card '+kind+'"><h4>'+esc(r.name)+'</h4><table>'+heading+'<tbody>'+lines(r)+'</tbody></table></article>';
                result.innerHTML='<div class="hourly-company-top"><h3>Итог компании</h3><div class="hourly-table-scroll"><table class="hourly-report-table">'+heading+'<tbody>'+lines(company)+'</tbody></table></div><div class="hourly-mobile-results">'+mobileCard(company,'hourly-company')+'</div></div><div class="hourly-report-filters hourly-analysis-controls"><label>Рестораны<select class="form-input" id="hourly-direction"><option value="all">Все</option><option value="up">Рост</option><option value="down">Падение</option></select></label><label>Сортировка<select class="form-input" id="hourly-sort"><option value="name">По названию</option><option value="up">Наибольший рост, %</option><option value="down">Наибольшее падение, %</option></select></label></div><div id="hourly-groups"></div><p class="section-note">— нет данных или базы сравнения. Общий ТО включает нераспределённые каналы. Итоги по всем доступным ресторанам территории и компании, независимо от фильтра; при неполных данных итог не рассчитывается.</p>';
                const direction=result.querySelector('#hourly-direction'),sort=result.querySelector('#hourly-sort'),target=result.querySelector('#hourly-groups');
                const metric=r=>percent(value(r.current,'total'),value(r.previous,'total'));
                const renderGroups=()=>{
                    const collapsed=new Set(Array.from(target.querySelectorAll('details:not([open])')).map(d=>d.dataset.group));
                    target.innerHTML=Array.from(groups.entries()).sort((a,b)=>a[1].name.localeCompare(b[1].name,'ru')).map(([key,g])=>{
                        const items=g.items.filter(r=>{const d=change(value(r.current,'total'),value(r.previous,'total'));return direction.value==='all'||(direction.value==='up'?d>0:d<0);}).sort((a,b)=>{
                            if(sort.value==='name')return a.name.localeCompare(b.name,'ru');
                            const x=metric(a),y=metric(b);if(x==null||y==null)return x==null?(y==null?0:1):-1;
                            return sort.value==='up'?y-x:x-y;
                        });
                        if(!items.length)return '';
                        const summary={name:'Итого: '+g.name,current:sum('current',g.items),previous:sum('previous',g.items)};
                        return '<details class="hourly-territory-details" data-group="'+esc(String(key))+'" '+(collapsed.has(String(key))?'':'open')+'><summary>Территория: '+esc(g.name)+' · '+items.length+' / '+g.items.length+'</summary><div class="hourly-table-scroll"><table class="hourly-report-table">'+heading+'<tbody>'+items.map(r=>block(r)).join('')+block(summary,'hourly-summary')+'</tbody></table></div><div class="hourly-mobile-results">'+items.map(r=>mobileCard(r)).join('')+mobileCard(summary,'hourly-summary')+'</div></details>';
                    }).join('')||'<p>Нет ресторанов по выбранному фильтру</p>';
                };
                direction.addEventListener('change',renderGroups);sort.addEventListener('change',renderGroups);renderGroups();
            }catch(e){if(id===request&&result.isConnected)result.textContent='Ошибка: '+e.message;}
        }
        document.getElementById('hourly-refresh').addEventListener('click',load);
        load();
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

    function dashboardDateRange() {
        const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
        if(DOM.periodSelect.value==='custom')return;
        const count={'1d':1,'7d':7,'30d':30,'90d':90,'365d':365}[DOM.periodSelect.value]||1;
        const start=new Date(today+'T12:00:00Z');
        start.setUTCDate(start.getUTCDate()-count+1);
        DOM.dateFrom.value=start.toISOString().slice(0,10);
        DOM.dateTo.value=today;
    }

    function renderDashboard(data) {
        const {overview:o, daily_trend:trend=[], by_restaurant:restaurants=[], by_order_type:orderTypes=[], previous_total_sales:previousSales=0, imports=[]} = data;
        const turnoverChart=data.turnover_chart||{points:[],granularity:'day',previous_has_data:false};
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
            renderHourlyComparison();
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
            const growthClass=(current,previous)=>{const n=growth(current,previous);return n===null?'':n<0?'negative':'positive';};
            const total=o.total_sales||0;
            const previous=previousSales||0;
            const signedChange = (current,prior) => {
                const n=growth(current,prior);
                return '<span class="sales-change '+growthClass(current,prior)+'">'+(n===null?'Нет базы':(n>0?'↑ ':n<0?'↓ ':'→ ')+Math.abs(n).toFixed(1)+'%')+'</span>';
            };
            const prior=o.previous_metrics||{};
            const comparison=(current,previous,format,share=false)=>{
                const dates=prior.date_from&&prior.date_to?formatDate(prior.date_from)+(prior.date_from===prior.date_to?'':' — '+formatDate(prior.date_to)):'Аналогичный период';
                let delta='';
                if(current!=null&&previous!=null){
                    if(share){const d=current-previous;delta='<span class="sales-kpi-delta '+(d>0?'up':d<0?'down':'')+'">'+(d>0?'+':'')+d.toFixed(1)+' п.п.</span>';}
                    else if(previous>0){const d=(current/previous-1)*100;delta='<span class="sales-kpi-delta '+(d>0?'up':d<0?'down':'')+'">'+(d>0?'+':'')+d.toFixed(1)+'%</span>';}
                }
                return '<div class="sales-kpi-comparison"><small>'+esc(dates)+'</small><div><b>'+(previous==null?'Нет данных':format(previous))+'</b>'+delta+'</div></div>';
            };
            const kpi=(icon,title,value,subtitle,change)=>'<article class="sales-v2-kpi"><div class="sales-v2-kpi-heading"><span class="sales-v2-icon" aria-hidden="true">'+icon+'</span><span>'+title+'</span></div><strong>'+value+'</strong><div class="sales-v2-kpi-footer"><span>'+subtitle+'</span></div>'+change+'</article>';
            const deliveryShare=total>0?100*orderTypes.filter(r=>r.type==='Доставка').reduce((n,r)=>n+Number(r.sales||0),0)/total:null;

            const availableDates=DOM.dateFrom.value&&DOM.dateTo.value?formatDate(DOM.dateFrom.value)+' — '+formatDate(DOM.dateTo.value):(trend.length?formatDate(trend[0].date)+' — '+formatDate(trend[trend.length-1].date):'Нет загруженных данных');
            const selectedRestaurants=state.selectedRestaurants===null?state.restaurants.map(r=>r.key):state.selectedRestaurants;
            const options=state.restaurants.map(r=>'<label class="rest-restaurant-option"><input type="checkbox" class="rest-restaurant-check" value="'+esc(r.key)+'" '+(selectedRestaurants.includes(r.key)?'checked':'')+'><span>'+esc(r.name)+'</span></label>').join('');
            DOM.content.innerHTML=
                '<div class="sales-v2-dashboard">'+
                '<div class="sales-v2-heading"><div><div class="sales-v2-eyebrow">WOKKER SALES <span class="sales-v3-slash">/</span> КОМАНДНЫЙ ЦЕНТР</div><h2>Пульс продаж<span class="sales-v3-heading-period"> · обзор</span></h2><p>Контроль товарооборота, динамики и эффективности ресторанов · '+esc(availableDates)+'</p></div><div class="sales-v2-status"><span class="sales-v2-status-dot"></span> Источник: iiko</div></div>'+ 
                '<div class="sales-v2-toolbar"><div class="sales-v2-presets">'+[['1d','Сегодня'],['7d','7 дней'],['30d','30 дней'],['90d','90 дней'],['365d','Год']].map(p=>'<button type="button" class="rest-period '+(DOM.periodSelect.value===p[0]?'selected':'')+'" data-rest-period="'+p[0]+'">'+p[1]+'</button>').join('')+'</div><div class="sales-v2-date-range"><label>С даты <input type="date" id="sales-inline-date-from" value="'+esc(DOM.dateFrom.value||'')+'"></label><label>По дату <input type="date" id="sales-inline-date-to" value="'+esc(DOM.dateTo.value||'')+'"></label></div></div>'+
                '<div class="sales-v2-kpis sales-v4-kpis sales-compact-kpis">'+
                  kpi('₽','Продажи',money(total),'к предыдущему периоду',comparison(total,prior.total_sales,money))+
                  kpi('▤','Средний чек',o.avg_check==null?'—':money(o.avg_check),o.sales_per_guest==null?'На гостя: нет данных':'На гостя: '+money(o.sales_per_guest),comparison(o.avg_check,prior.avg_check,money))+
                  kpi('▣','Чеки',o.checks==null?'—':formatNumber(o.checks),o.guests==null?'Гости: нет данных':'Гости: '+formatNumber(o.guests),comparison(o.checks,prior.checks,formatNumber))+
                  kpi('%','Скидки',o.discounts==null?'—':money(o.discounts),o.discounts==null?'Нет данных в отчёте':'За выбранный период',comparison(o.discounts,prior.discounts,money))+
                  kpi('%','Доля доставки',total>0?(100*orderTypes.filter(r=>r.type==='Доставка').reduce((n,r)=>n+Number(r.sales||0),0)/total).toFixed(1)+'%':'—','За выбранный период',comparison(deliveryShare,prior.delivery_share,v=>v.toFixed(1)+'%',true))+
                '</div>'+
                '<div class="sales-chart-filter-layout">'+
                '<section class="sales-v2-panel sales-leading-chart"><div class="sales-v2-panel-head"><div><div class="sales-v2-eyebrow">ТОВАРООБОРОТ</div><h3>'+(turnoverChart.granularity==='hour'?'Почасовой ТО':'ТО по дням')+'</h3></div><span class="sales-v2-muted">'+esc(availableDates)+'</span></div>'+
                '<div class="sales-chart-switches"><label><input type="checkbox" data-sales-chart-series="total" checked> Общий ТО</label><label><input type="checkbox" data-sales-chart-series="hall"> Зал</label><label><input type="checkbox" data-sales-chart-series="delivery"> Доставка</label><label><input type="checkbox" data-sales-chart-series="previous" '+(turnoverChart.previous_has_data?'':'disabled')+'> '+esc(turnoverChart.comparison_label||'Аналогичный период')+'</label></div>'+
                '<div class="rest-graph-area sales-leading-chart-area"><canvas id="sales-turnover-chart" role="img" aria-label="График товарооборота"></canvas></div>'+
                '<p class="sales-v2-muted">Для сравнения используются фактически загруженные данные iiko. Зал и доставка определяются настройками типов заказов.</p></section>'+
                '<section class="sales-v2-panel sales-v2-restaurant-panel"><div class="sales-v2-panel-head"><div><div class="sales-v2-eyebrow">ФИЛЬТР</div><h3>Рестораны</h3></div></div><p class="sales-v2-muted">Выбрано '+selectedRestaurants.length+' из '+state.restaurants.length+'</p><input id="rest-search" type="search" placeholder="Найти ресторан…" aria-label="Поиск по ресторанам"><div class="rest-restaurant-list"><label class="rest-restaurant-option"><input type="checkbox" id="rest-all" '+(selectedRestaurants.length===state.restaurants.length?'checked':'')+'> Все рестораны</label>'+options+'</div></section>'+
                '</div></div>';
            DOM.content.querySelectorAll('[data-rest-period]').forEach(button=>button.addEventListener('click',()=>{DOM.periodSelect.value=button.dataset.restPeriod;DOM.periodSelect.dispatchEvent(new Event('change'));}));
            const inlineFrom=document.getElementById('sales-inline-date-from');
            const inlineTo=document.getElementById('sales-inline-date-to');
            const applyInlineDates=()=>{
                if(!inlineFrom.value||!inlineTo.value)return;
                if(inlineFrom.value>inlineTo.value){showToast('Дата начала должна быть не позднее даты окончания','error');return;}
                DOM.dateFrom.value=inlineFrom.value;
                DOM.dateTo.value=inlineTo.value;
                DOM.periodSelect.value='custom';
                DOM.periodSelect.dispatchEvent(new Event('change'));
            };
            inlineFrom.addEventListener('change',applyInlineDates);
            inlineTo.addEventListener('change',applyInlineDates);
            const search=document.getElementById('rest-search');
            search.addEventListener('input',()=>{const term=search.value.toLocaleLowerCase('ru');DOM.content.querySelectorAll('.rest-restaurant-check').forEach(input=>{input.closest('label').hidden=!input.closest('label').textContent.toLocaleLowerCase('ru').includes(term);});});
            document.getElementById('rest-all').addEventListener('change',e=>{state.selectedRestaurants=e.target.checked?null:[];DOM.restaurantSelect.value='';loadDashboard();});
            DOM.content.querySelectorAll('.rest-restaurant-check').forEach(input=>input.addEventListener('change',()=>{const keys=Array.from(DOM.content.querySelectorAll('.rest-restaurant-check:checked')).map(el=>el.value);state.selectedRestaurants=keys.length===state.restaurants.length?null:keys;DOM.restaurantSelect.value='';loadDashboard();}));
            const chartControls=Array.from(DOM.content.querySelectorAll('[data-sales-chart-series]'));
            const drawLeadingChart=()=>renderTurnoverChart(turnoverChart,chartControls.filter(el=>el.checked).map(el=>el.dataset.salesChartSeries));
            chartControls.forEach(el=>el.addEventListener('change',drawLeadingChart));
            requestAnimationFrame(drawLeadingChart);
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

    function renderTurnoverChart(chart, selected) {
        const canvas=document.getElementById('sales-turnover-chart');
        if(!canvas)return;
        const points=chart.points||[], parent=canvas.parentElement;
        const bounds=parent.getBoundingClientRect();
        if(!bounds.width||!bounds.height)return;
        const ratio=window.devicePixelRatio||1, W=bounds.width, H=bounds.height;
        canvas.width=Math.round(W*ratio);canvas.height=Math.round(H*ratio);
        canvas.style.width=W+'px';canvas.style.height=H+'px';
        const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);
        const series={
            total:{color:'#c92c35',value:p=>Number(p.total||0)},
            hall:{color:'#2563eb',value:p=>Number(p.hall||0)},
            delivery:{color:'#0d9488',value:p=>Number(p.delivery||0)},
        };
        const channels=selected.filter(key=>Object.prototype.hasOwnProperty.call(series,key));
        const visible=[...channels];
        if(selected.includes('previous')&&chart.previous_has_data){
            channels.forEach(key=>{
                const priorKey='previous_'+key;
                series[priorKey]={color:series[key].color,value:p=>Number((p.previous||{})[key]||0),previous:true};
                visible.push(priorKey);
            });
        }
        const hasData=(p,key)=>series[key].previous?p.previous_has_data!==false:p.has_data!==false;
        const pad={left:65,right:20,top:20,bottom:44}, width=Math.max(1,W-pad.left-pad.right), height=Math.max(1,H-pad.top-pad.bottom);
        const amounts=points.flatMap(p=>visible.filter(key=>hasData(p,key)).map(key=>series[key].value(p)));
        const max=Math.max(1,...amounts);
        ctx.clearRect(0,0,W,H);ctx.font='11px sans-serif';
        for(let i=0;i<=4;i++){
            const y=pad.top+height*i/4;
            ctx.strokeStyle='#e5e7eb';ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(W-pad.right,y);ctx.stroke();
            ctx.fillStyle='#6b7280';ctx.textAlign='right';ctx.fillText(formatNumber(max*(4-i)/4),pad.left-8,y+4);
        }
        visible.forEach(key=>{
            const item=series[key];ctx.strokeStyle=item.color;ctx.lineWidth=2.5;
            ctx.setLineDash(item.previous?[6,4]:[]);
            ctx.beginPath();let drawing=false;
            points.forEach((p,i)=>{
                if(!hasData(p,key)){drawing=false;return;}
                const x=pad.left+(points.length===1?width/2:width*i/(points.length-1));
                const y=pad.top+height*(1-item.value(p)/max);
                if(!drawing)ctx.moveTo(x,y);else ctx.lineTo(x,y);
                drawing=true;
            });
            ctx.stroke();ctx.setLineDash([]);
            if(points.length===1||points.filter(p=>hasData(p,key)).length===1){
                points.forEach((p,i)=>{
                    if(!hasData(p,key))return;
                    const x=pad.left+(points.length===1?width/2:width*i/(points.length-1));
                    const y=pad.top+height*(1-item.value(p)/max);
                    ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fillStyle=item.color;ctx.fill();
                });
            }
        });
        ctx.fillStyle='#6b7280';ctx.textAlign='center';ctx.font='10px sans-serif';
        const step=Math.max(1,Math.ceil(points.length/7));
        points.forEach((p,i)=>{
            if(i%step!==0&&i!==points.length-1)return;
            const x=pad.left+(points.length===1?width/2:width*i/(points.length-1));
            const label=chart.granularity==='day'?String(p.label||'').slice(8,10)+'.'+String(p.label||'').slice(5,7):p.label;
            ctx.fillText(label,x,H-13);
        });
        if(!visible.length){ctx.textAlign='center';ctx.fillStyle='#6b7280';ctx.fillText('Выберите показатель',W/2,H/2);}
        else if(!points.some(p=>visible.some(key=>hasData(p,key)))){ctx.textAlign='center';ctx.fillStyle='#6b7280';ctx.fillText('Нет данных за выбранный период',W/2,H/2);}
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

    function setSalesMenuOpen(open, restoreFocus = true) {
        const wasOpen = DOM.sidebar.classList.contains('open');
        DOM.sidebar.classList.toggle('open', open);
        DOM.menuToggle.setAttribute('aria-expanded', String(open));
        DOM.workspace.inert = open;
        if (open) DOM.sidebarClose.focus();
        else if (wasOpen && restoreFocus) DOM.menuToggle.focus();
    }

    function bindEvents() {
        const navLinks = document.querySelectorAll('.side-nav [data-view]:not([hidden])');
        navLinks.forEach(button => button.addEventListener('click', () => {
            state.view = button.dataset.view;
            ++state.recordsRequest;
            ++state.productsRequest;
            navLinks.forEach(link => {
                const active = link === button;
                link.classList.toggle('active', active);
                if (active) link.setAttribute('aria-current', 'page');
                else link.removeAttribute('aria-current');
            });
            document.getElementById('view-title').textContent = button.textContent.trim();
            setSalesMenuOpen(false);
            if(state.view==='settings') renderDashboard(state.dashboardData||{overview:{},daily_trend:[],by_restaurant:[],imports:[]});
            else if(state.dashboardData) renderDashboard(state.dashboardData); else loadDashboard();
        }));

        DOM.menuToggle.addEventListener('click', () => setSalesMenuOpen(true));
        DOM.sidebarClose.addEventListener('click', () => setSalesMenuOpen(false));
        DOM.sidebarBackdrop.addEventListener('click', () => setSalesMenuOpen(false));
        window.matchMedia('(max-width: 850px)').addEventListener('change', () => setSalesMenuOpen(false, false));

        const mobileFilterToggle=document.getElementById('sales-mobile-filter-toggle');
        const salesTopbar=document.querySelector('.topbar');
        const setMobileFiltersOpen=open=>{
            salesTopbar.classList.toggle('mobile-filters-open',open);
            mobileFilterToggle.setAttribute('aria-expanded',String(open));
        };
        mobileFilterToggle.addEventListener('click',()=>setMobileFiltersOpen(!salesTopbar.classList.contains('mobile-filters-open')));
        document.addEventListener('keydown', event => {
            if (event.key !== 'Escape') return;
            if (DOM.sidebar.classList.contains('open')) setSalesMenuOpen(false);
            else setMobileFiltersOpen(false);
        });

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
