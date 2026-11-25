'use strict';

const byId = id => document.getElementById(id);
const dateInput = byId('date');
const table = byId('employees');
const editor = byId('editor');
const editForm = byId('edit-form');
const statusLine = byId('status');
const labels = { work: 'Работа', vacation: 'Отпуск', sick: 'Больничный', absent: 'Неявка' };
const staffToken = localStorage.getItem('wokker_staff_token');
const adminToken = localStorage.getItem('wokker_admin_token');
const fromAdmin = new URLSearchParams(location.search).get('from') === 'admin';
const token = fromAdmin ? adminToken || staffToken : staffToken || adminToken;
let selected;
let loadVersion = 0;

if (fromAdmin) {
    byId('back').href = '/admin';
    byId('back').textContent = 'В админку';
}

async function api(path, { body, method = 'POST', binary = false } = {}) {
    if (!token) throw new Error('Войдите в аккаунт, чтобы открыть табель');
    const headers = { Authorization: 'Bearer ' + token };
    if (typeof body === 'string') headers['Content-Type'] = 'application/json';
    const response = await fetch(path, { method, headers, body });
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        if (response.status === 403) throw new Error('Нет доступа к этой операции');
        if (response.status === 401) throw new Error('Сессия завершилась. Войдите снова');
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
        for(const date of dates){const cell=employee.data_by_date?.[date];if(cell?.rk)keys.add(cell.rk);}
        for(const key of keys){
            if(restaurantFilter.value&&key!==restaurantFilter.value)continue;
            if(key&&!restaurantNames.has(key))continue;
            if(!groups.has(key))groups.set(key,[]);
            groups.get(key).push(employee);
        }
    }
    const totalRow=(name,hours)=>{const row=table.insertRow();row.className='group-row';const label=row.insertCell();label.className='employee-col';label.textContent=name;const blank=row.insertCell();blank.colSpan=dates.length;row.insertCell().textContent=hours===''?'':String(Math.round(hours*100)/100);};
    for(const [key,employees] of groups){
        totalRow(restaurantNames.get(key)||'Без ресторана','');
        let total=0;
        for(const employee of employees){
            const row=table.insertRow(),name=row.insertCell();name.className='employee-col';name.textContent=employee.full_name+' · '+(employee.position||'');
            let hours=0;
            for(const date of dates){
                const cell=employee.data_by_date?.[date]||{};
                const actual=cell.rk||employee.main_restaurant_key||'';
                const td=row.insertCell();
                if(actual!==key){td.textContent='—';continue;}
                const button=document.createElement('button');button.type='button';button.className='cell-button';
                button.textContent=({vacation:'В',sick:'Б',absent:'Н'})[cell.s]??(cell.h||'—');
                button.setAttribute('aria-label',employee.full_name+' '+date+' '+button.textContent);
                button.addEventListener('click',()=>openEditor(employee,cell,date));td.append(button);
                if(cell.s==='work')hours+=Number(cell.h)||0;
            }
            row.insertCell().textContent=String(Math.round(hours*100)/100);total+=hours;
        }
        totalRow('Итого по ресторану',total);
    }
    scroll.scrollLeft=left;scroll.scrollTop=top;
}
async function loadDay(){
    const version=++loadVersion;
    if(!dateInput.value)return;
    const dates=periodDates();
    byId('period-title').textContent=dates[0]+' — '+dates[dates.length-1];
    statusLine.textContent='Загрузка…';
    try{
        const {employees}=await api('/api/timesheet/matrix',{body:JSON.stringify({date_from:dates[0],date_to:dates[dates.length-1]})});
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

byId('import-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
        const data = new FormData(event.currentTarget);
        const params = new URLSearchParams({ restaurant_key: data.get('restaurant_key') });
        data.delete('restaurant_key');
        const result = await api('/api/timesheet/import_attendance?' + params, { body: data });
        await loadDay();
        statusLine.textContent = ['Импортировано записей: ' + result.success_count, ...result.errors].join('\n');
    } catch (error) {
        statusLine.textContent = error.message;
    } finally {
        button.disabled = false;
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
api('/api/timesheet/restaurants').then(({ restaurants }) => {
    restaurantNames=new Map(restaurants.map(r=>[r.key,r.name]));
    for(const r of restaurants)restaurantFilter.add(new Option(r.name,r.key));
    fillRestaurants(byId('edit-restaurant'), restaurants);
    fillRestaurants(byId('import-restaurant'), restaurants);
    return loadDay();
}).catch(error => { statusLine.textContent = error.message; });

const pageNames = ['Главная','Табель','Начисления','Отчёты','Согласование','Настройки'];
function showPage(index) {
    byId('page-title').textContent = pageNames[index];
    byId('home-panel').hidden = index !== 0;
    byId('timesheet-panel').hidden = index !== 1;
    byId('future-panel').hidden = index < 2;
    document.querySelectorAll('nav [data-page]').forEach(button => {
        if (Number(button.dataset.page) === index) button.setAttribute('aria-current','page');
        else button.removeAttribute('aria-current');
    });
}
document.querySelectorAll('[data-page]').forEach(button => {
    button.addEventListener('click', () => showPage(Number(button.dataset.page)));
});
showPage(0);
