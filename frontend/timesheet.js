'use strict';

const byId = id => document.getElementById(id);
const dateInput = byId('date');
const table = byId('employees');
const editor = byId('editor');
const editForm = byId('edit-form');
const statusLine = byId('status');
const labels = { work: 'Работа', vacation: 'Отпуск', sick: 'Больничный', absent: 'Неявка' };
let token = sessionStorage.getItem('wokker_timesheet_token');
let selected;
let loadVersion = 0;



async function api(path, { body, method = 'POST', binary = false } = {}) {
    if (!token) throw new Error('Войдите в аккаунт, чтобы открыть табель');
    const headers = { Authorization: 'Bearer ' + token };
    if (typeof body === 'string') headers['Content-Type'] = 'application/json';
    const response = await fetch(path, { method, headers, body });
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        if (response.status === 403) throw new Error('Нет доступа к этой операции');
        if (response.status === 401) { clearSession(); throw new Error('Сессия завершилась. Войдите снова'); }
        const failure = new Error(error.error || 'Запрос не выполнен');
        failure.details = error;
        throw failure;
    }
    return binary ? response.blob() : response.json();
}

function fillRestaurants(select, restaurants) {
    select.add(new Option('По умолчанию', ''));
    for (const restaurant of restaurants) select.add(new Option(restaurant.name, restaurant.key));
}

function openEditor(employee, cell, date) {
    selected = { employee, date };
    byId('employee-name').textContent = employee.full_name;
    byId('edit-status').textContent = '';
    editForm.elements.status.value = cell.s || 'work';
    editForm.elements.hours.value = cell.h || 0;
    editForm.elements.start_time.value = cell.st || '';
    editForm.elements.end_time.value = cell.et || '';
    editForm.elements.restaurant_key.value = cell.rk || employee.main_restaurant_key || '';
    editor.showModal();
}

const period = byId('period');
const restaurantFilter = byId('restaurant-filter');
let employeesData = [];
let restaurantNames = new Map();
let loadedRange = null;
function iso(d){return d.toISOString().slice(0,10);}
function periodDates(){
    const anchor = new Date(dateInput.value+'T12:00:00Z');
    const start = new Date(anchor), end = new Date(anchor);
    if(period.value==='week'){
        start.setUTCDate(start.getUTCDate()-(start.getUTCDay()+6)%7);
        end.setTime(start.getTime());end.setUTCDate(end.getUTCDate()+6);
    }else{
        start.setUTCDate(1);end.setUTCMonth(end.getUTCMonth()+1,0);
    }
    const dates=[];
    for(const d=new Date(start);d<=end;d.setUTCDate(d.getUTCDate()+1))dates.push(iso(d));
    return dates;
}
function renderMatrix(){
    if(!loadedRange)return;
    const dates=loadedRange;
    const scroll=byId('matrix-scroll'), left=scroll.scrollLeft, top=scroll.scrollTop;
    table.replaceChildren();
    const head=byId('matrix-head');head.replaceChildren();
    const header=head.insertRow();
    function th(text,cls=''){const el=document.createElement('th');el.textContent=text;el.className=cls;header.append(el);}
    th('Сотрудник','employee-col');
    for(const date of dates){const d=new Date(date+'T12:00:00Z');th(date.slice(8)+'.'+date.slice(5,7)+' '+['Вс','Пн','Вт','Ср','Чт','Пт','Сб'][d.getUTCDay()],d.getUTCDay()%6===0?'weekend':'');}
    th('Часов');
    const groups=new Map();
    for(const employee of employeesData){
        const home=employee.main_restaurant_key||'';
        const keys=new Set([home]);
        for(const date of dates){const cell=employee.data_by_date?.[date];if(cell?.rk)keys.add(cell.rk);for(const key of Object.keys(employee.imported_by_date?.[date]||{}))keys.add(key);}
        for(const key of keys){
            if(restaurantFilter.value&&key!==restaurantFilter.value)continue;
            if(key&&!restaurantNames.has(key))continue;
            if(!groups.has(key))groups.set(key,[]);
            groups.get(key).push(employee);
        }
    }
    const totalRow=(name,hours)=>{const row=table.insertRow();row.className=hours===''?'group-row restaurant-row':'group-row total-row';const label=row.insertCell();label.className='employee-col';label.textContent=name;const blank=row.insertCell();blank.colSpan=dates.length;row.insertCell().textContent=hours===''?'':`${Math.floor(hours/60)}:${String(hours%60).padStart(2,'0')}`;};
    for(const [key,employees] of groups){
        totalRow(restaurantNames.get(key)||'Без ресторана','');
        let total=0;
        for(const employee of employees){
            const row=table.insertRow(),name=row.insertCell();name.className='employee-col';row.className='employee-row';
            const fullName=document.createElement('span');fullName.className='employee-name';fullName.textContent=employee.full_name;
            const position=document.createElement('span');position.className='employee-position';position.textContent=employee.position||'';name.append(fullName,position);
            let hours=0;
            for(const date of dates){
                const legacy=employee.data_by_date?.[date]||{};
                const imports=employee.imported_by_date?.[date]||{};
                const cell=imports[key]||(Object.keys(imports).length?{}:legacy);
                if(Object.keys(imports).length&&!imports[key]){row.insertCell().textContent='—';continue;}
                const actual=cell.rk||employee.main_restaurant_key||'';
                const td=row.insertCell();
                if(actual!==key){td.textContent='—';continue;}
                const button=document.createElement('button');button.type='button';button.className='cell-button';
                button.textContent=({vacation:'В',sick:'Б',absent:'Н'})[cell.s]??(cell.imported?`${Math.floor(cell.minutes/60)}:${String(cell.minutes%60).padStart(2,'0')}`:(cell.h||'—'));
                if(cell.s&&cell.s!=='work')button.classList.add('has-status');else if(Number(cell.h)>0)button.classList.add('has-hours');
                button.setAttribute('aria-label',employee.full_name+' '+date+' '+button.textContent);
                if(cell.imported){button.disabled=true;button.title='Из отчёта iiko';}else button.addEventListener('click',()=>openEditor(employee,cell,date));td.append(button);
                if(cell.s==='work')hours+=cell.imported?cell.minutes:Math.round((Number(cell.h)||0)*60);
            }
            const totalCell=row.insertCell();totalCell.className='hours-total';totalCell.textContent=`${Math.floor(hours/60)}:${String(hours%60).padStart(2,'0')}`;total+=hours;
        }
        totalRow('Итого по ресторану',total);
    }
    scroll.scrollLeft=left;scroll.scrollTop=top;
}
async function loadDay(){
    const version=++loadVersion;
    if(!dateInput.value)return;
    const dates=periodDates();
    const formatDate=d=>d.split('-').reverse().join('.');
    byId('period-title').textContent=formatDate(dates[0])+' — '+formatDate(dates[dates.length-1]);
    statusLine.textContent='Загрузка…';
    try{
        const {employees}=await api('/api/timesheet/matrix',{body:JSON.stringify({date_from:dates[0],date_to:dates[dates.length-1],period:period.value})});
        if(version!==loadVersion)return;
        employeesData=employees;loadedRange=dates;renderMatrix();
        statusLine.textContent=employees.length?'':'Нет доступных сотрудников';
    }catch(error){if(version===loadVersion){table.replaceChildren();loadedRange=null;statusLine.textContent=error.message;}}
}
dateInput.addEventListener('change',loadDay);
period.addEventListener('change',loadDay);
restaurantFilter.addEventListener('change',renderMatrix);
function shiftPeriod(delta){
    const d=new Date(dateInput.value+'T12:00:00Z');
    if(period.value==='week')d.setUTCDate(d.getUTCDate()+delta*7);
    else{d.setUTCDate(1);d.setUTCMonth(d.getUTCMonth()+delta);}
    dateInput.value=iso(d);loadDay();
}
byId('prev').addEventListener('click',()=>shiftPeriod(-1));
byId('next').addEventListener('click',()=>shiftPeriod(1));
byId('cancel').addEventListener('click', () => editor.close());
editForm.addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
        const values = Object.fromEntries(new FormData(editForm));
        await api('/api/timesheet/save_cell', {
            body: JSON.stringify({ ...values, user_id: selected.employee.user_id, work_date: selected.date })
        });
        editor.close();
        await loadDay();
    } catch (error) {
        byId('edit-status').textContent = error.message;
    } finally {
        button.disabled = false;
    }
});

let historyVersion = 0;
let deletingAttendance = false;
async function deleteAttendance(record, button) {
    if (deletingAttendance || !token) return;
    const restaurant = restaurantNames.get(record.restaurant_key) || record.restaurant_key;
    if (!window.confirm('Удалить отчёт №' + record.id + '?\nРесторан: ' + restaurant +
        '\nПериод: ' + record.date_from + ' — ' + record.date_to +
        '\nБудут удалены только записи этого отчёта для указанного ресторана. Недельный и месячный табели обновятся. Расчёт начислений может измениться.')) return;
    deletingAttendance = true;
    button.disabled = true;
    const status = byId('attendance-history-status');
    status.textContent = 'Удаление отчёта…';
    try {
        await api('/api/timesheet/import_attendance/delete', {
            body: JSON.stringify({import_id: record.id, restaurant_key: record.restaurant_key})
        });
        await loadAttendanceHistory();
        await loadDay();
    } catch (error) {
        status.textContent = error.message + ' Обновите историю перед повторной попыткой.';
    } finally {
        deletingAttendance = false;
        button.disabled = false;
    }
}
async function loadAttendanceHistory() {
    const version = ++historyVersion;
    const status = byId('attendance-history-status');
    const rows = byId('attendance-history-rows');
    rows.replaceChildren();
    status.textContent = 'Загрузка истории…';
    try {
        const result = await api('/api/timesheet/import_attendance/history', {method: 'GET'});
        if (version !== historyVersion) return;
        const fragment = document.createDocumentFragment();
        for (const record of result.records) {
            const row = document.createElement('tr');
            const minutes = Number(record.total_minutes);
            const values = ['№' + record.id, record.created_at,
                restaurantNames.get(record.restaurant_key) || record.restaurant_key,
                record.date_from + ' — ' + record.date_to, record.record_count,
                Math.floor(minutes / 60) + ' ч ' + (minutes % 60) + ' мин'];
            for (const value of values) {
                const cell = document.createElement('td');
                cell.textContent = value;
                row.append(cell);
            }
            const actions = document.createElement('td');
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.textContent = 'Удалить';
            remove.setAttribute('aria-label', 'Удалить отчёт №' + record.id + ' — ' + (restaurantNames.get(record.restaurant_key) || record.restaurant_key));
            remove.addEventListener('click', () => deleteAttendance(record, remove));
            actions.append(remove);
            row.append(actions);
            fragment.append(row);
        }
        rows.replaceChildren(fragment);
        status.textContent = result.records.length ? 'Последние записи: ' + result.records.length : 'Нет загруженных отчётов';
    } catch (error) {
        if (version === historyVersion) status.textContent = error.message;
    }
}
byId('refresh-attendance-history').addEventListener('click', loadAttendanceHistory);
let attendanceMapping = {employees: Object.create(null), restaurants: Object.create(null)};
function renderAttendanceMatching(matching) {
    const fields = byId('matching-fields');
    fields.replaceChildren();
    byId('attendance-matching').hidden = !matching || !(matching.employees.length || matching.restaurants.length);
    if (!matching) return;
    for (const [kind, sources] of Object.entries(matching)) {
        for (const source of sources) {
            const label = document.createElement('label');
            label.textContent = (kind === 'employees' ? 'Табельный номер ' : 'Ресторан ') + source + ' → ';
            const control = document.createElement(kind === 'employees' ? 'input' : 'select');
            if (kind === 'employees') {
                control.placeholder = 'Номер из админ-панели';
                control.maxLength = 50;
            } else {
                control.add(new Option('Выберите ресторан', ''));
                for (const [key, name] of restaurantNames) if (key) control.add(new Option(name, name));
            }
            control.value = attendanceMapping[kind][source] || '';
            control.addEventListener('change', () => {
                if (control.value.trim()) attendanceMapping[kind][source] = control.value.trim();
                else delete attendanceMapping[kind][source];
                clearAttendancePreview();
            });
            label.append(control);
            fields.append(label, document.createElement('br'));
        }
    }
}
let previewVersion = 0;
let verifiedAttendance = null;
let stagingAttendance = false;
function clearAttendancePreview() {
    previewVersion++;
    verifiedAttendance = null;
    byId('confirm-attendance').disabled = true;
    byId('attendance-preview').hidden = true;
    byId('preview-rows').replaceChildren();
    byId('preview-summary').textContent = '';
    byId('upload-status').textContent = '';
}
byId('import-form').addEventListener('change', () => {
    attendanceMapping = {employees: Object.create(null), restaurants: Object.create(null)};
    renderAttendanceMatching(null);
    clearAttendancePreview();
});
byId('import-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (stagingAttendance) return;
    clearAttendancePreview();
    const version = previewVersion;
    const button = event.submitter;
    button.disabled = true;
    byId('upload-status').textContent = 'Проверка файла…';
    try {
        const data = new FormData(event.currentTarget);
        const params = new URLSearchParams({restaurant_key: data.get('restaurant_key')});
        data.delete('restaurant_key');
        if (Object.values(attendanceMapping).some(entries => Object.keys(entries).length)) data.append('mapping', JSON.stringify(attendanceMapping));
        const result = await api('/api/timesheet/import_attendance/preview?' + params, {body: data});
        if (version !== previewVersion) return;
        renderAttendanceMatching(result.matching);
        const records = result.records;
        if (result.ok && records.length) {
            verifiedAttendance = {data, params, version};
            byId('confirm-attendance').disabled = false;
        }
        const duration = n => Math.floor(n / 60) + ' ч ' + (n % 60) + ' мин';
        byId('preview-summary').textContent = [
            'Сотрудников: ' + new Set(records.map(r => r.personnel_number)).size,
            'Ресторанов: ' + new Set(records.map(r => r.restaurant_key)).size,
            'Интервалов: ' + records.reduce((n,r) => n + r.shifts.length, 0),
            'Итого: ' + (result.total_minutes === null ? 'не рассчитано' : duration(result.total_minutes))
        ].join(' · ');
        const fragment = document.createDocumentFragment();
        for (const record of records) {
            const row = document.createElement('tr');
            for (const value of [record.personnel_number, record.date, restaurantNames.get(record.restaurant_key) || record.restaurant_key,
                record.shifts.join(', ') || labels[record.status] || record.status, duration(record.minutes)]) {
                const cell = document.createElement('td');
                cell.textContent = value;
                row.append(cell);
            }
            fragment.append(row);
        }
        byId('preview-rows').replaceChildren(fragment);
        byId('attendance-preview').hidden = false;
        byId('upload-status').textContent = [result.ok ? 'Проверка завершена. Данные не сохранены.' : 'Ошибок: ' + result.error_count, ...result.errors].join('\n');
    } catch (error) {
        if (version === previewVersion) byId('upload-status').textContent = error.message;
    } finally {
        button.disabled = false;
    }
});

byId('confirm-attendance').addEventListener('click', async () => {
    const verified = verifiedAttendance;
    if (!verified || stagingAttendance || verified.version !== previewVersion) return;
    stagingAttendance = true;
    verifiedAttendance = null;
    const form = byId('import-form');
    const controls = [...form.querySelectorAll('input, select, button')];
    const previous = controls.map(control => control.disabled);
    controls.forEach(control => control.disabled = true);
    byId('confirm-attendance').disabled = true;
    byId('upload-status').textContent = 'Сохранение отчёта…';
    try {
        const result = await api('/api/timesheet/import_attendance/stage?' + verified.params, {body: verified.data});
        if (verified.version !== previewVersion) return;
        byId('upload-status').textContent = result.ok
            ? 'Отчёт №' + result.import_id + ' сохранён. Записей: ' + result.success_count + '. Данные будут учтены при расчёте начислений.'
            : (result.errors || ['Отчёт не сохранён']).join('\n');
        if (result.ok) { await loadAttendanceHistory(); await loadDay(); }
    } catch (error) {
        if (verified.version === previewVersion) byId('upload-status').textContent = error.message + ' Проверьте историю загрузок перед повторной отправкой.';
    } finally {
        stagingAttendance = false;
        controls.forEach((control, i) => control.disabled = previous[i]);
    }
});

byId('export').addEventListener('click', async () => {
    if (!dateInput.reportValidity()) return;
    try {
        const dates=periodDates();
        const params = new URLSearchParams({ date_from: dates[0], date_to: dates[dates.length-1] });
        const file = await api('/api/timesheet/export_excel?' + params, { method: 'GET', binary: true });
        const url = URL.createObjectURL(file);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'timesheet-' + dateInput.value + '.xlsx';
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
        statusLine.textContent = error.message;
    }
});

const today = new Date();
dateInput.value = [today.getFullYear(), String(today.getMonth() + 1).padStart(2, '0'),
    String(today.getDate()).padStart(2, '0')].join('-');
for (const [key, label] of Object.entries(labels)) editForm.elements.status.add(new Option(label, key));
function clearSession(){
    resetMatchingRegistry();
    resetRates();
    resetRounding();
    historyVersion++;
    byId('attendance-history-rows').replaceChildren();
    byId('attendance-history-status').textContent = '';
    clearAttendancePreview();
    sessionStorage.removeItem('wokker_timesheet_token');
    token=null;accrualVersion++;accrualRows=[];byId('accruals-rows').replaceChildren();byId('accruals-total').textContent='';loadVersion++;employeesData=[];loadedRange=null;table.replaceChildren();
    if(editor.open)editor.close();
    document.querySelector('aside').hidden=true;
    document.querySelector('main').hidden=true;
    byId('login-panel').hidden=false;
}
async function startTimesheet(){
    if(!token){clearSession();return;}
    try {
        const {restaurants}=await api('/api/timesheet/restaurants');
        restaurantFilter.replaceChildren(new Option('Все рестораны',''));
        byId('edit-restaurant').replaceChildren();
        byId('import-restaurant').replaceChildren();
        restaurantNames=new Map(restaurants.map(r=>[r.key,r.name]));
        for(const r of restaurants)restaurantFilter.add(new Option(r.name,r.key));
        fillRestaurants(byId('edit-restaurant'),restaurants);
        fillRestaurants(byId('import-restaurant'),restaurants);
        byId('login-panel').hidden=true;
        document.querySelector('aside').hidden=false;
        document.querySelector('main').hidden=false;
        await loadDay();
    }catch(error){clearSession();byId('login-error').textContent=error.message;}
}
byId('login-form').addEventListener('submit',async event=>{
    event.preventDefault();
    const button=event.submitter;button.disabled=true;
    try{
        const response=await fetch('/api/timesheet/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||'Ошибка входа');
        token=result.token;sessionStorage.setItem('wokker_timesheet_token',token);
        byId('login-form').reset();byId('login-error').textContent='';
        await startTimesheet();
    }catch(error){byId('login-error').textContent=error.message;}finally{button.disabled=false;}
});
byId('logout').addEventListener('click',async()=>{
    try{await api('/api/timesheet/logout');}finally{clearSession();location.reload();}
});


let accrualRows = [], accrualVersion = 0;
const rub = new Intl.NumberFormat('ru-RU', {style:'currency',currency:'RUB'});
function accrualHours(hours) {
    const minutes = Math.round(Number(hours)*60);
    return Math.floor(minutes/60)+':'+String(minutes%60).padStart(2,'0');
}
function renderAccruals() {
    const restaurant = byId('accruals-restaurant').value;
    const search = byId('accruals-search').value.trim().toLocaleLowerCase('ru');
    const rows = accrualRows.filter(r => (!restaurant || r.restaurant_name===restaurant) &&
        String(r.full_name||'').toLocaleLowerCase('ru').includes(search));
    const tbody = byId('accruals-rows');
    tbody.replaceChildren();
    for (const r of rows) {
        const tr = document.createElement('tr');
        for (const value of [r.full_name,r.position,r.restaurant_name,accrualHours(r.total_hours),
            (rub.format(r.rate)+(r.payment_type==='fixed'?' · Оклад':'')),rub.format(r.total_salary)]) {
            const td=document.createElement('td');td.textContent=value??'—';tr.append(td);
        }
        tbody.append(tr);
    }
    byId('accruals-total').textContent='Итого: '+rub.format(rows.reduce((sum,r)=>sum+Number(r.total_salary),0));
}
async function loadAccruals() {
    const version=++accrualVersion;
    accrualRows=[];renderAccruals();
    byId('accruals-status').textContent='Загрузка…';
    try {
        const result=await api('/api/timesheet/accruals',{body:JSON.stringify({
            date_from:byId('accruals-from').value,date_to:byId('accruals-to').value})});
        if(version!==accrualVersion || !token)return;
        accrualRows=result.report;
        const select=byId('accruals-restaurant'), previous=select.value;
        select.replaceChildren(new Option('Все рестораны',''));
        for(const name of [...new Set(accrualRows.map(r=>r.restaurant_name).filter(Boolean))].sort())select.add(new Option(name,name));
        if([...select.options].some(o=>o.value===previous))select.value=previous;
        renderAccruals();
        byId('accruals-status').textContent=result.legacy_partial_months?.length
            ? 'Внимание: отчёт неполный. Для исторических табелей выберите полный месяц: '+result.legacy_partial_months.join(', ')
            : (accrualRows.length?'':'Нет данных за период');
    } catch(error) {
        if(version===accrualVersion)byId('accruals-status').textContent=error.message;
    }
}
byId('accruals-form').addEventListener('submit',e=>{e.preventDefault();loadAccruals();});
byId('accruals-search').addEventListener('input',renderAccruals);
byId('accruals-restaurant').addEventListener('change',renderAccruals);
function openAccruals(){
    if(!byId('accruals-from').value){
        const today=new Date();
        const localDate=d=>d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
        byId('accruals-from').value=localDate(new Date(today.getFullYear(),today.getMonth(),1));
        byId('accruals-to').value=localDate(today);
    }
    loadAccruals();
}

async function exportAccrualPeriod(from,to,status) {
    status.textContent='';
    if(!from || !to || from>to){status.textContent='Укажите корректный период';return;}
    try {
        const file=await api('/api/timesheet/export_excel?'+new URLSearchParams({date_from:from,date_to:to}),{method:'GET',binary:true});
        const url=URL.createObjectURL(file), link=document.createElement('a');
        link.href=url;link.download='accruals-'+from+'-'+to+'.xlsx';link.click();
        setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){status.textContent=error.message;}
}
byId('accruals-export').addEventListener('click',()=>exportAccrualPeriod(byId('accruals-from').value,byId('accruals-to').value,byId('accruals-status')));
byId('reports-form').addEventListener('submit',e=>{
    e.preventDefault();const data=new FormData(e.currentTarget);
    exportAccrualPeriod(data.get('date_from'),data.get('date_to'),byId('reports-status'));
});
function openReports(){
    const form=byId('reports-form');
    if(!form.elements.date_from.value){
        const d=dateInput.value;
        form.elements.date_from.value=d.slice(0,7)+'-01';form.elements.date_to.value=d;
    }
}

const pageNames = ['Главная','Табель','Начисления','Отчёты','Согласование','Настройки','Панель загрузки','Ставки сотрудников'];

const approvalLabels = {draft:'Черновик',pending:'На согласовании',approved:'Утверждён',returned:'Возвращён на доработку'};
let approvalVersion = 0;
async function loadApproval(){
    const version=++approvalVersion, key=byId('approval-restaurant').value, month=byId('approval-month').value;
    const status=byId('approval-status'), actions=byId('approval-actions'), history=byId('approval-history');
    actions.replaceChildren();history.replaceChildren();status.textContent='Загрузка…';
    if(!key||!month){status.textContent='Выберите ресторан и месяц';return;}
    const payload={restaurant_key:key,month_start:month+'-01'};
    try{
        const data=await api('/api/timesheet/approval/status',{body:JSON.stringify(payload)});
        if(version!==approvalVersion)return;
        status.textContent=approvalLabels[data.status]||data.status;
        for(const h of data.history){
            const line=document.createElement('p');
            line.textContent=[h.created_at,h.actor_name,approvalLabels[h.previous_status]+' → '+approvalLabels[h.new_status],h.comment].filter(Boolean).join(' · ');
            history.append(line);
        }
        const options=[];
        if(['draft','returned'].includes(data.status))options.push(['submit','Отправить на согласование']);
        if(data.can_review&&data.status==='pending')options.push(['approve','Утвердить'],['return','Вернуть на доработку']);
        if(data.can_review&&data.status==='approved')options.push(['reopen','Открыть повторно']);
        for(const [action,label] of options){
            const button=document.createElement('button');button.type='button';button.textContent=label;
            button.addEventListener('click',async()=>{
                const comment=byId('approval-comment').value.trim();
                if(['return','reopen'].includes(action)&&!comment){status.textContent='Укажите причину';return;}
                if(action==='approve'&&!window.confirm('Утвердить табель за '+month+'? Начисления будут зафиксированы.'))return;
                for(const b of actions.querySelectorAll('button'))b.disabled=true;
                try{
                    await api('/api/timesheet/approval/transition',{body:JSON.stringify({...payload,action,comment,revision:data.revision})});
                    if(version===approvalVersion){byId('approval-comment').value='';await loadApproval();}
                }catch(e){
                    if(version!==approvalVersion)return;
                    for(const b of actions.querySelectorAll('button'))b.disabled=false;
                    actions.querySelector('[data-missing-rates-link]')?.remove();
                    if(e.details?.error==='missing_hourly_rates'){
                        const names=(e.details.employees||[]).map(employee=>employee.full_name).join(', ');
                        status.textContent='Утверждение невозможно: не назначена почасовая ставка. '+names;
                        const link=document.createElement('button');
                        link.type='button';link.dataset.missingRatesLink='true';
                        link.textContent='Перейти к ставкам сотрудников';
                        link.addEventListener('click',()=>document.querySelector('nav [data-page="7"]').click());
                        actions.append(link);
                    }else status.textContent=e.message;
                }
            });
            actions.append(button);
        }
    }catch(e){if(version===approvalVersion)status.textContent=e.message;}
}
function openApproval(){
    const select=byId('approval-restaurant'), previous=select.value;
    select.replaceChildren(new Option('Выберите ресторан',''));
    for(const [key,name] of restaurantNames)if(key)select.add(new Option(name,key));
    select.value=previous;
    if(!byId('approval-month').value)byId('approval-month').value=iso(new Date()).slice(0,7);
    loadApproval();
}
byId('approval-form').addEventListener('submit',e=>{e.preventDefault();loadApproval();});
for(const id of ['approval-restaurant','approval-month'])byId(id).addEventListener('change',()=>{byId('approval-comment').value='';loadApproval();});

let roundingVersion = 0, roundingRevision = null;
function resetRounding(){
    roundingVersion++;
    roundingRevision=null;
    byId('rounding-form').hidden=true;
    byId('rounding-form').querySelector('button').disabled=true;
    byId('rounding-history').hidden=true;
    byId('rounding-rows').replaceChildren();
    byId('rounding-status').textContent='';
}
function renderRounding(data){
    roundingRevision=data.revision;
    byId('rounding-step').value=String(data.step_minutes);
    const rows=byId('rounding-rows');
    rows.replaceChildren();
    for(const item of data.history){
        const row=rows.insertRow();
        for(const value of [item.created_at,item.actor_id,item.previous_step,item.new_step]){
            row.insertCell().textContent=value??'—';
        }
    }
    byId('rounding-form').hidden=false;
    byId('rounding-form').querySelector('button').disabled=false;
    byId('rounding-history').hidden=false;
}
async function loadRounding(){
    resetRounding();
    const version=roundingVersion;
    byId('rounding-status').textContent='Загрузка…';
    try{
        const data=await api('/api/timesheet/rounding',{method:'GET'});
        if(version!==roundingVersion||!token)return;
        renderRounding(data);
        byId('rounding-status').textContent='';
    }catch(e){if(version===roundingVersion)byId('rounding-status').textContent=e.message;}
}
byId('rounding-form').addEventListener('submit',async e=>{
    e.preventDefault();
    if(roundingRevision===null)return;
    const version=roundingVersion, button=e.currentTarget.querySelector('button');
    button.disabled=true;
    try{
        const data=await api('/api/timesheet/rounding',{body:JSON.stringify({step_minutes:Number(byId('rounding-step').value),revision:roundingRevision})});
        if(version!==roundingVersion||!token)return;
        renderRounding(data);
        byId('rounding-status').textContent='Настройки сохранены';
    }catch(error){
        if(version!==roundingVersion)return;
        await loadRounding();
        if(roundingVersion===version+1)byId('rounding-status').textContent=error.message;
    }
});
let ratesVersion=0, ratesData=null;
function resetRates(){
    for(const dialog of document.querySelectorAll('dialog[data-rate-dialog]'))if(dialog.open)dialog.close();
    ratesVersion++;ratesData=null;
    for(const id of ['rates-rows','rate-request-rows','rate-history-rows'])byId(id).replaceChildren();
    byId('rates-status').textContent='';
    byId('rates-search').value='';
    byId('rates-restaurant').replaceChildren(new Option('Все рестораны',''));
}
function rateDialog(title, fields){
    return new Promise(resolve=>{
        const dialog=document.createElement('dialog');
        const form=document.createElement('form');form.method='dialog';
        const heading=document.createElement('h2');heading.textContent=title;form.append(heading);
        const inputs={};
        for(const field of fields){
            const label=document.createElement('label');label.textContent=field.label;
            const input=document.createElement(field.multiline?'textarea':'input');
            input.required=!!field.required;input.value=field.value||'';
            if(field.multiline)input.maxLength=2000;
            else{input.type='number';input.min='0';input.max='9999999999.99';input.step='0.01';input.inputMode='decimal';}
            label.append(input);form.append(label);inputs[field.key]=input;
        }
        const actions=document.createElement('div');actions.className='toolbar';
        const cancel=document.createElement('button');cancel.type='button';cancel.textContent='Отмена';
        const submit=document.createElement('button');submit.type='submit';submit.textContent='Подтвердить';
        actions.append(cancel,submit);form.append(actions);dialog.append(form);document.body.append(dialog);
        let result=null;
        cancel.addEventListener('click',()=>dialog.close());
        form.addEventListener('submit',event=>{
            event.preventDefault();result=Object.fromEntries(Object.entries(inputs).map(([key,input])=>[key,input.value.trim()]));dialog.close();
        });
        dialog.addEventListener('close',()=>{dialog.remove();resolve(result);},{once:true});
        dialog.dataset.rateDialog='true';dialog.showModal();
    });
}
function rateButton(cell,label,action){
    const b=document.createElement('button');b.type='button';b.textContent=label;
    b.addEventListener('click',async()=>{
        const version=ratesVersion;b.disabled=true;
        try{await action();if(version===ratesVersion&&token)await loadRates();}
        catch(e){if(version===ratesVersion)byId('rates-status').textContent=e.message;}
        finally{b.disabled=false;}
    });cell.append(b);
}
function labelRateCells(row,labels){Array.from(row.cells).forEach((cell,i)=>{cell.dataset.label=labels[i];});}
function renderRateEmployees(){
    const rows=byId('rates-rows');rows.replaceChildren();
    if(!ratesData)return;
    const search=byId('rates-search').value.trim().toLowerCase(), restaurant=byId('rates-restaurant').value;
    for(const e of ratesData.employees){
        if(restaurant&&e.restaurant_key!==restaurant)continue;
        if(search&&!String(e.full_name).toLowerCase().includes(search))continue;
        const row=rows.insertRow();
        for(const value of [e.full_name+(e.payment_type==='fixed'?' · Оклад':''),e.restaurant_name,e.rate])row.insertCell().textContent=value??'—';
        const actions=row.insertCell();
        labelRateCells(row,['Сотрудник','Ресторан','Ставка, ₽/ч','Действие']);
        if(ratesData.can_manage)rateButton(actions,'Изменить',async()=>{
            const values=await rateDialog('Изменение ставки — '+e.full_name,[{key:'rate',label:'Новая ставка, ₽/ч',value:e.rate,required:true}]);
            if(!values||!token||byId('rates-panel').hidden)return;
            const rate=values.rate;
            await api('/api/timesheet/individual-rate',{body:JSON.stringify({user_id:e.user_id,hourly_rate:rate.trim().replace(',','.')})});
        });
        if(ratesData.can_request)rateButton(actions,'Запросить',async()=>{
            const values=await rateDialog('Запрос изменения — '+e.full_name,[{key:'rate',label:'Предлагаемая ставка, ₽/ч',value:e.rate,required:true},{key:'reason',label:'Причина изменения',multiline:true,required:true}]);
            if(!values||!token||byId('rates-panel').hidden)return;
            const {rate,reason}=values;
            await api('/api/timesheet/rate-requests',{body:JSON.stringify({user_id:e.user_id,proposed_rate:rate.trim().replace(',','.'),reason})});
        });
    }
}
async function loadRates(){
    const version=++ratesVersion;ratesData=null;
    for(const id of ['rates-rows','rate-request-rows','rate-history-rows'])byId(id).replaceChildren();
    byId('rates-status').textContent='Загрузка…';
    try{
        const [data,requests,history]=await Promise.all([
            api('/api/timesheet/rate-employees',{method:'GET'}),
            api('/api/timesheet/rate-requests',{method:'GET'}),
            api('/api/timesheet/rate-history',{method:'GET'})]);
        if(version!==ratesVersion||!token)return;
        ratesData=data;
        const select=byId('rates-restaurant'),previous=select.value;
        select.replaceChildren(new Option('Все рестораны',''));
        for(const [key,name] of restaurantNames)if(key)select.add(new Option(name,key));
        select.value=previous;renderRateEmployees();
        for(const q of requests.requests){
            const row=byId('rate-request-rows').insertRow();
            for(const value of [q.full_name,q.proposed_rate,q.reason,({pending:'На рассмотрении',approved:'Согласовано',rejected:'Отклонено'})[q.status]||q.status])row.insertCell().textContent=value??'—';
            const actions=row.insertCell();
            labelRateCells(row,['Сотрудник','Новая ставка','Причина','Статус','Решение']);
            if(data.can_manage&&q.status==='pending')for(const [decision,label] of [['approved','Согласовать'],['rejected','Отклонить']]){
                rateButton(actions,label,async()=>{
                    const values=await rateDialog(label+' — '+q.full_name,[{key:'comment',label:decision==='rejected'?'Причина отклонения':'Комментарий (необязательно)',multiline:true,required:decision==='rejected'}]);
                    if(!values||!token||byId('rates-panel').hidden)return;
                    const comment=values.comment;
                    await api('/api/timesheet/rate-requests/'+encodeURIComponent(q.id)+'/decision',{body:JSON.stringify({decision,comment})});
                });
            }
        }
        for(const h of history.history){
            const row=byId('rate-history-rows').insertRow();
            for(const value of [h.full_name,h.previous_rate,h.new_rate,h.created_at,h.actor_id])row.insertCell().textContent=value??'—';
            labelRateCells(row,['Сотрудник','Было','Стало','Дата','Автор']);
        }
        byId('rates-status').textContent='';
    }catch(e){if(version===ratesVersion)byId('rates-status').textContent=e.message;}
}
byId('rates-search').addEventListener('input',renderRateEmployees);
byId('rates-restaurant').addEventListener('change',renderRateEmployees);
byId('rates-refresh').addEventListener('click',loadRates);
function showPage(index) {
    byId('page-title').textContent = pageNames[index];
    byId('home-panel').hidden = index !== 0;
    byId('timesheet-panel').hidden = index !== 1;
    byId('future-panel').hidden = index !== 5;
    byId('rates-panel').hidden = index !== 7;
    if(index===7&&token)loadRates();else resetRates();
    if(index===5 && token)loadRounding();else resetRounding();
    byId('approval-panel').hidden = index !== 4;
    if(index === 4 && token) openApproval();
    else approvalVersion++;
    byId('reports-panel').hidden = index !== 3;
    if(index === 3) openReports();
    byId('accruals-panel').hidden = index !== 2;
    if(index === 2 && token) openAccruals();
    byId('upload-panel').hidden = index !== 6;
    if (index === 6 && token) { loadAttendanceHistory(); loadMatchingRegistry(); }
    document.querySelectorAll('nav [data-page]').forEach(button => {
        if (Number(button.dataset.page) === index) button.setAttribute('aria-current','page');
        else button.removeAttribute('aria-current');
    });
}
document.querySelectorAll('[data-page]').forEach(button => {
    button.addEventListener('click', () => showPage(Number(button.dataset.page)));
});

let registryVersion = 0;
let registryBusy = false;
function resetMatchingRegistry() {
    registryVersion++;
    registryDirectory = {employees: [], restaurants: []};
    byId('registry-form').elements.target.replaceChildren();
    byId('matching-registry').hidden = true;
    byId('registry-form').reset();
    byId('registry-rows').replaceChildren();
    byId('registry-history').replaceChildren();
    byId('registry-status').textContent = '';
}
let registryDirectory = {employees: [], restaurants: []};
function updateRegistryChoices(selected = '') {
    const form = byId('registry-form');
    const kind = form.elements.kind.value;
    const search = byId('registry-search').value.trim().toLocaleLowerCase('ru');
    const target = form.elements.target;
    target.replaceChildren(new Option('Выберите значение', ''));
    for (const item of registryDirectory[kind]) {
        const label = kind === 'employees' ? [item.full_name, item.personnel_number, 'ID '+item.id].filter(Boolean).join(' — ') : item.name;
        if (!search || label.toLocaleLowerCase('ru').includes(search) || item.id === selected)
            target.add(new Option(label, item.id));
    }
    target.value = selected;
}
function renderMatchingRegistry(data) {
    registryDirectory = {employees: data.employees || [], restaurants: data.restaurants || []};
    updateRegistryChoices();
    const form = byId('registry-form');
    const rows = byId('registry-rows');
    rows.replaceChildren();
    const kindLabel = kind => kind === 'employees' ? 'Сотрудник' : 'Ресторан';
    for (const entry of data.entries) {
        const row = rows.insertRow();
        for (const value of [kindLabel(entry.kind), entry.source, entry.target, entry.stale ? 'Устарело — требуется замена' : 'Активно'])
            row.insertCell().textContent = value;
        const actions = row.insertCell();
        const edit = document.createElement('button');
        edit.type = 'button'; edit.textContent = 'Изменить';
        edit.onclick = () => {
            form.elements.kind.value = entry.kind;
            form.elements.source.value = entry.source;
            byId('registry-search').value = '';
            updateRegistryChoices(entry.target);
            form.elements.target.focus();
        };
        const remove = document.createElement('button');
        remove.type = 'button'; remove.textContent = 'Удалить';
        remove.onclick = () => {
            if (window.confirm('Удалить соответствие: ' + entry.source + '?'))
                changeMatchingRegistry('DELETE', {kind: entry.kind, source: entry.source});
        };
        actions.append(edit, remove);
    }
    const history = byId('registry-history');
    history.replaceChildren();
    for (const entry of data.history) {
        const row = history.insertRow();
        for (const value of [kindLabel(entry.kind), entry.source, entry.previous_target,
            entry.new_target, entry.actor_id, entry.created_at])
            row.insertCell().textContent = value ?? '—';
    }
}
async function loadMatchingRegistry() {
    const version = ++registryVersion;
    try {
        const data = await api('/api/timesheet/matching', {method: 'GET'});
        if (version !== registryVersion || !token) return;
        renderMatchingRegistry(data);
        byId('matching-registry').hidden = false;
        byId('registry-status').textContent = '';
    } catch (error) {
        if (version === registryVersion) resetMatchingRegistry();
    }
}
async function changeMatchingRegistry(method, values) {
    if (registryBusy || !token || byId('matching-registry').hidden) return;
    registryBusy = true;
    const version = ++registryVersion;
    const status = byId('registry-status');
    try {
        const data = await api('/api/timesheet/matching', {method, body: JSON.stringify(values)});
        if (version !== registryVersion || !token) return;
        renderMatchingRegistry(data);
        byId('registry-form').reset();
        updateRegistryChoices();
        clearAttendancePreview();
        status.textContent = 'Изменения сохранены';
    } catch (error) {
        if (version === registryVersion) status.textContent = error.message;
    } finally { registryBusy = false; }
}
byId('registry-search').addEventListener('input', () => updateRegistryChoices());
byId('registry-form').elements.kind.addEventListener('change', () => {
    byId('registry-search').value = '';
    updateRegistryChoices();
});
byId('registry-refresh').addEventListener('click', loadMatchingRegistry);
byId('registry-form').addEventListener('submit', event => {
    event.preventDefault();
    changeMatchingRegistry('POST', Object.fromEntries(new FormData(event.currentTarget)));
});

showPage(0);
startTimesheet();
