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
        throw new Error(error.error || 'Запрос не выполнен');
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
byId('import-form').addEventListener('change', clearAttendancePreview);
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
        const result = await api('/api/timesheet/import_attendance/preview?' + params, {body: data});
        if (version !== previewVersion) return;
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
    historyVersion++;
    byId('attendance-history-rows').replaceChildren();
    byId('attendance-history-status').textContent = '';
    clearAttendancePreview();
    sessionStorage.removeItem('wokker_timesheet_token');
    token=null;loadVersion++;employeesData=[];loadedRange=null;table.replaceChildren();
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


const pageNames = ['Главная','Табель','Начисления','Отчёты','Согласование','Настройки','Панель загрузки'];
function showPage(index) {
    byId('page-title').textContent = pageNames[index];
    byId('home-panel').hidden = index !== 0;
    byId('timesheet-panel').hidden = index !== 1;
    byId('future-panel').hidden = index < 2 || index === 6;
    byId('upload-panel').hidden = index !== 6;
    if (index === 6 && token) loadAttendanceHistory();
    document.querySelectorAll('nav [data-page]').forEach(button => {
        if (Number(button.dataset.page) === index) button.setAttribute('aria-current','page');
        else button.removeAttribute('aria-current');
    });
}
document.querySelectorAll('[data-page]').forEach(button => {
    button.addEventListener('click', () => showPage(Number(button.dataset.page)));
});
showPage(0);
startTimesheet();
