import { apiGet } from './api.js';
import { create, el } from './dom.js';

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

const state = {
    value: '',
    focus: '',
    viewYear: 0,
    viewMonth: 0,
    earliest: null,
    latest: null,
    available: null,
    open: false,
};

let onChange = null;
let availabilityRequested = false;

function pad(value) {
    return value < 10 ? '0' + value : String(value);
}

function iso(year, month, day) {
    return year + '-' + pad(month) + '-' + pad(day);
}

function todayIso() {
    const now = new Date();
    return iso(now.getFullYear(), now.getMonth() + 1, now.getDate());
}

function daysInMonth(year, month) {
    return new Date(year, month, 0).getDate();
}

function parts(date) {
    return [Number(date.slice(0, 4)), Number(date.slice(5, 7)), Number(date.slice(8, 10))];
}

function monthKey(date) {
    return date.slice(0, 7);
}

function isDisabled(date) {
    if (state.earliest && date < state.earliest) {
        return true;
    }
    if (state.latest && date > state.latest) {
        return true;
    }
    if (state.available && !state.available.has(date)) {
        return true;
    }
    return false;
}

export function getValue() {
    return state.value;
}

export function setValue(date) {
    state.value = date || '';
    if (state.value) {
        state.focus = state.value;
    }
    renderValue();
    if (state.open) {
        renderGrid();
    }
}

export function setBounds(earliest, latest) {
    state.earliest = earliest || null;
    state.latest = latest || null;
    if (state.open) {
        renderGrid();
    }
}

export function close() {
    if (!state.open) {
        return;
    }
    state.open = false;
    el.dpPopover.hidden = true;
    el.dpTrigger.setAttribute('aria-expanded', 'false');
}

function renderValue() {
    el.dpValue.textContent = state.value || '未选择';
    el.dpValue.classList.toggle('is-empty', !state.value);
}

function choose(date) {
    if (isDisabled(date)) {
        return;
    }
    setValue(date);
    close();
    if (onChange) {
        onChange(date);
    }
}

function shiftMonth(delta) {
    let year = state.viewYear;
    let month = state.viewMonth + delta;
    while (month < 1) {
        month += 12;
        year -= 1;
    }
    while (month > 12) {
        month -= 12;
        year += 1;
    }
    if (state.earliest && (year + '-' + pad(month)) < monthKey(state.earliest)) {
        return;
    }
    if (state.latest && (year + '-' + pad(month)) > monthKey(state.latest)) {
        return;
    }
    state.viewYear = year;
    state.viewMonth = month;
    renderGrid();
}

function renderGrid() {
    const year = state.viewYear;
    const month = state.viewMonth;
    el.dpTitle.textContent = year + ' 年 ' + month + ' 月';

    const firstWeekday = new Date(year, month - 1, 1).getDay();
    const total = daysInMonth(year, month);
    const today = todayIso();

    el.dpPrev.disabled = !!(state.earliest && year + '-' + pad(month) <= monthKey(state.earliest));
    el.dpNext.disabled = !!(state.latest && year + '-' + pad(month) >= monthKey(state.latest));

    el.dpGrid.textContent = '';
    const fragment = document.createDocumentFragment();

    for (let i = 0; i < firstWeekday; i++) {
        fragment.appendChild(create('span', 'dp-cell dp-blank'));
    }

    for (let day = 1; day <= total; day++) {
        const date = iso(year, month, day);
        const cell = create('button', 'dp-cell');
        cell.type = 'button';
        cell.textContent = String(day);
        cell.dataset.date = date;

        if (isDisabled(date)) {
            cell.disabled = true;
            cell.classList.add('is-disabled');
        }
        if (date === state.value) {
            cell.classList.add('is-selected');
            cell.setAttribute('aria-selected', 'true');
        }
        if (date === today) {
            cell.classList.add('is-today');
        }
        cell.tabIndex = date === (state.focus || state.value) ? 0 : -1;
        if (cell.tabIndex === 0) {
            cell.classList.add('is-focus');
        }

        cell.addEventListener('click', () => choose(date));
        fragment.appendChild(cell);
    }

    el.dpGrid.appendChild(fragment);
}

function open() {
    state.open = true;
    el.dpPopover.hidden = false;
    el.dpTrigger.setAttribute('aria-expanded', 'true');

    const base = state.value || state.latest || todayIso();
    const parsed = parts(base);
    state.viewYear = parsed[0];
    state.viewMonth = parsed[1];
    state.focus = state.value || base;

    renderGrid();
    loadAvailability();

    const node = el.dpGrid.querySelector('.is-focus');
    if (node) {
        node.focus();
    }
}

function toggle() {
    if (state.open) {
        close();
    } else {
        open();
    }
}

function loadAvailability() {
    if (availabilityRequested) {
        return;
    }
    availabilityRequested = true;

    apiGet('getAvailableDates', {}, { silent: true })
        .then((data) => {
            if (data && Array.isArray(data.availableDates)) {
                const set = new Set();
                for (let i = 0; i < data.availableDates.length; i++) {
                    set.add(data.availableDates[i]);
                }
                state.available = set;
                if (state.open) {
                    renderGrid();
                }
            }
        })
        .catch(() => {
            /* 取不到可用日期时只按上下界限制，不阻塞选择 */
        });
}

function moveFocus(target) {
    const base = state.focus || state.value;
    if (!base) {
        return;
    }
    const parsed = parts(base);
    const shifted = new Date(parsed[0], parsed[1] - 1, parsed[2] + target);
    state.focus = iso(shifted.getFullYear(), shifted.getMonth() + 1, shifted.getDate());
    state.viewYear = shifted.getFullYear();
    state.viewMonth = shifted.getMonth() + 1;
    renderGrid();
    const node = el.dpGrid.querySelector('.is-focus');
    if (node) {
        node.focus();
    }
}

function onGridKeydown(event) {
    const base = state.focus || state.value;
    if (!base) {
        return;
    }

    switch (event.key) {
        case 'ArrowLeft':
            event.preventDefault();
            moveFocus(-1);
            break;
        case 'ArrowRight':
            event.preventDefault();
            moveFocus(1);
            break;
        case 'ArrowUp':
            event.preventDefault();
            moveFocus(-7);
            break;
        case 'ArrowDown':
            event.preventDefault();
            moveFocus(7);
            break;
        case 'Home':
            event.preventDefault();
            chooseFirstOfMonth();
            break;
        case 'End':
            event.preventDefault();
            chooseLastOfMonth();
            break;
        case 'PageUp':
            event.preventDefault();
            shiftMonth(-1);
            break;
        case 'PageDown':
            event.preventDefault();
            shiftMonth(1);
            break;
        case 'Enter':
        case ' ':
            event.preventDefault();
            choose(base);
            break;
        default:
            break;
    }
}

function chooseFirstOfMonth() {
    jumpToDay(1);
}

function chooseLastOfMonth() {
    jumpToDay(daysInMonth(state.viewYear, state.viewMonth));
}

function jumpToDay(day) {
    const date = iso(state.viewYear, state.viewMonth, day);
    state.focus = date;
    renderGrid();
    const node = el.dpGrid.querySelector('.is-focus');
    if (node) {
        node.focus();
    }
}

export function initDatePicker(options) {
    onChange = options && typeof options.onChange === 'function' ? options.onChange : null;
    if (!el.datePicker) {
        return;
    }

    el.dpWeekdays.textContent = '';
    for (let i = 0; i < WEEKDAYS.length; i++) {
        el.dpWeekdays.appendChild(create('span', null, WEEKDAYS[i]));
    }

    el.dpTrigger.addEventListener('click', toggle);
    el.dpPrev.addEventListener('click', () => shiftMonth(-1));
    el.dpNext.addEventListener('click', () => shiftMonth(1));
    el.dpClose.addEventListener('click', close);
    el.dpLatest.addEventListener('click', () => {
        if (state.latest) {
            choose(state.latest);
        }
    });
    el.dpGrid.addEventListener('keydown', onGridKeydown);

    document.addEventListener('click', (event) => {
        if (!state.open) {
            return;
        }
        if (!el.datePicker.contains(event.target)) {
            close();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (state.open && event.key === 'Escape') {
            close();
            el.dpTrigger.focus();
        }
    });

    renderValue();
}
