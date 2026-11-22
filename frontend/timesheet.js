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
    editForm.elements.restaurant_key.value = cell.rk || '';
    editor.showModal();
}

async function loadDay() {
    const version = ++loadVersion;
    const date = dateInput.value;
    table.replaceChildren();
    if (!date) return;
    statusLine.textContent = 'Загрузка…';
    try {
        const { employees } = await api('/api/timesheet/matrix', {
            body: JSON.stringify({ date_from: date, date_to: date })
        });
        if (version !== loadVersion) return;
        const day = String(Number(date.slice(-2)));
        for (const employee of employees) {
            const cell = employee.data?.[day] || {};
            const row = table.insertRow();
            for (const value of [employee.full_name, employee.restaurant_name, labels[cell.s], cell.h,
                [cell.st, cell.et].filter(Boolean).join(' – ')]) {
                row.insertCell().textContent = value ?? '—';
            }
            const button = document.createElement('button');
            button.textContent = 'Изменить';
            button.addEventListener('click', () => openEditor(employee, cell, date));
            row.insertCell().append(button);
        }
        statusLine.textContent = employees.length ? '' : 'За эту дату нет доступных сотрудников';
    } catch (error) {
        if (version === loadVersion) statusLine.textContent = error.message;
    }
}

dateInput.addEventListener('change', loadDay);
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
        const params = new URLSearchParams({ date_from: dateInput.value, date_to: dateInput.value });
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
    fillRestaurants(byId('edit-restaurant'), restaurants);
    fillRestaurants(byId('import-restaurant'), restaurants);
}).catch(error => { statusLine.textContent = error.message; });
loadDay();
