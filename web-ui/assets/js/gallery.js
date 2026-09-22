import { apiGet } from './api.js';
import { create, el, setStatus } from './dom.js';
import { animateScaleY, restartAnimation, stagger } from './anim.js';
import { setValue as setDateValue } from './datepicker.js';
import { openViewer } from './viewer.js';
import {
    bindImageFade,
    bindImageFallback,
    epochOf,
    formatDuration,
    formatFileSize,
    pad2,
    sequenceOf,
    timeLabel,
    timeShort,
} from './util.js';

const state = { level: 0, date: '', hour: '', slot: '', minute: '' };
let history = [];
let crumbSignature = null;
let statsContent = false;
let activityContent = false;
let levelBarAllowed = true;

export function getState() {
    return {
        level: state.level,
        date: state.date,
        hour: state.hour,
        slot: state.slot,
        minute: state.minute,
    };
}

export function resetToDate(date) {
    history = [];
    state.level = date ? 1 : 0;
    state.date = date || '';
    state.hour = '';
    state.slot = '';
    state.minute = '';
    render();
}

export function goBack() {
    if (!history.length) {
        return;
    }
    const previous = history.pop();
    state.level = previous.level;
    state.date = previous.date;
    state.hour = previous.hour;
    state.slot = previous.slot;
    state.minute = previous.minute;
    render();
}

export function updateChrome() {
    if (el.backButton) {
        el.backButton.hidden = history.length === 0;
    }
    crumbSignature = null;
    renderBreadcrumb();
}

export function setLevelBarVisible(visible) {
    levelBarAllowed = !!visible;
    applyLevelBar();
}

export function setMonitorCrumb(photo) {
    const nav = el.breadcrumb;
    if (!nav) {
        return;
    }
    const signature = 'monitor:' + (photo && photo.filename ? photo.filename : '');
    if (signature === crumbSignature) {
        return;
    }
    crumbSignature = signature;

    nav.textContent = '';
    const fragment = document.createDocumentFragment();
    fragment.appendChild(create('span', 'crumb-current crumb-live', '实时监控'));
    if (photo) {
        fragment.appendChild(create('span', 'crumb-sep', '›'));
        fragment.appendChild(create('span', 'crumb-current', timeLabel(photo)));
    }
    nav.appendChild(fragment);
    restartAnimation(nav);
}

export function initGallery() {
    if (el.backButton) {
        el.backButton.addEventListener('click', goBack);
    }
}

function applyLevelBar() {
    if (el.levelStats) {
        el.levelStats.hidden = !levelBarAllowed || !statsContent;
    }
    if (el.activityBar) {
        el.activityBar.hidden = !levelBarAllowed || !activityContent || state.level !== 1;
    }
}

function snapshot() {
    return { level: state.level, date: state.date, hour: state.hour, slot: state.slot, minute: state.minute };
}

function applyState(targetLevel, patch) {
    const next = patch || {};
    state.level = targetLevel;
    state.date = next.date !== undefined ? next.date : state.date;
    state.hour = targetLevel >= 2 && next.hour !== undefined ? next.hour : '';
    state.slot = targetLevel >= 3 && next.slot !== undefined ? next.slot : '';
    state.minute = targetLevel >= 4 && next.minute !== undefined ? next.minute : '';
}

function navigate(targetLevel, patch) {
    history.push(snapshot());
    applyState(targetLevel, patch);
    render();
}

function jumpTo(targetLevel, patch) {
    history = [];
    applyState(targetLevel, patch);
    render();
}

function render() {
    setStatus('');
    setDateValue(state.date);
    crumbSignature = null;
    updateChrome();

    el.gallery.hidden = false;
    clearLevelBar();

    if (state.level === 0) {
        el.gallery.textContent = '';
        el.gallery.className = 'grid';
        setStatus('请选择一个日期开始浏览。');
        return;
    }
    if (state.level === 1) {
        loadDaily();
    } else if (state.level === 2) {
        loadHourly();
    } else if (state.level === 3) {
        loadTenMinute();
    } else if (state.level === 4) {
        loadMinute();
    }
}

function clearLevelBar() {
    statsContent = false;
    activityContent = false;
    if (el.levelStats) {
        el.levelStats.textContent = '';
    }
    if (el.activityBar) {
        el.activityBar.textContent = '';
    }
    applyLevelBar();
}

function renderBreadcrumb() {
    const nav = el.breadcrumb;
    if (!nav) {
        return;
    }

    const parts = [];
    /* 日期已在左侧选择器显示，这里只画「下钻路径」，避免同一日期重复出现 */
    if (state.date && state.level >= 2) {
        parts.push({
            text: '全天',
            isCurrent: false,
            onClick: () => jumpTo(1, { date: state.date }),
        });
    }

    if (state.hour) {
        if (parts.length) {
            parts.push({ separator: true });
        }
        parts.push({
            text: state.hour + ' 点',
            isCurrent: state.level <= 2,
            onClick: () => jumpTo(2, { date: state.date, hour: state.hour }),
        });
    }

    const slot = state.slot === '' ? NaN : Number(state.slot);
    if (!isNaN(slot) && slot >= 0 && slot <= 5) {
        if (parts.length) {
            parts.push({ separator: true });
        }
        const start = slot * 10;
        parts.push({
            text: String(start).padStart(2, '0') + '-' + String(start + 9).padStart(2, '0') + ' 分',
            isCurrent: state.level <= 3,
            onClick: () => jumpTo(3, { date: state.date, hour: state.hour, slot: state.slot }),
        });
    }

    if (state.minute) {
        if (parts.length) {
            parts.push({ separator: true });
        }
        parts.push({ text: state.minute + ' 分', isCurrent: true });
    }

    const signature = JSON.stringify(parts.map((part) => (part.separator ? '>' : part.text)));
    if (signature === crumbSignature) {
        return;
    }
    crumbSignature = signature;

    nav.textContent = '';
    const fragment = document.createDocumentFragment();
    parts.forEach((part) => {
        if (part.separator) {
            fragment.appendChild(create('span', 'crumb-sep', '›'));
            return;
        }
        if (part.isCurrent || !part.onClick) {
            fragment.appendChild(create('span', 'crumb-current', part.text));
            return;
        }
        const button = create('button', 'crumb', part.text);
        button.type = 'button';
        button.addEventListener('click', part.onClick);
        fragment.appendChild(button);
    });
    nav.appendChild(fragment);
}

function renderStats(items, exactFiles, scope) {
    if (!items || !items.length) {
        return;
    }

    let files = typeof exactFiles === 'number' ? exactFiles : 0;
    let minItem = null;
    let maxItem = null;
    let minEpoch = null;
    let maxEpoch = null;

    items.forEach((item) => {
        if (typeof exactFiles !== 'number') {
            files += typeof item.count === 'number' ? item.count : 1;
        }
        const epoch = epochOf(item);
        if (epoch === null) {
            return;
        }
        if (minEpoch === null || epoch < minEpoch) {
            minEpoch = epoch;
            minItem = item;
        }
        if (maxEpoch === null || epoch > maxEpoch) {
            maxEpoch = epoch;
            maxItem = item;
        }
    });

    const parts = [];
    if (scope) {
        parts.push(scope);
    }
    parts.push(files + ' 张');
    if (minItem !== null && maxItem !== null) {
        parts.push(timeShort(minItem) + ' → ' + timeShort(maxItem));
        if (maxEpoch > minEpoch) {
            parts.push('跨度 ' + formatDuration(maxEpoch - minEpoch));
        }
    }

    el.levelStats.textContent = parts.join(' · ');
    statsContent = true;
    applyLevelBar();
}

function renderActivity(items) {
    if (state.level !== 1 || !items || !items.length || !el.activityBar) {
        return;
    }

    const counts = new Array(24);
    for (let i = 0; i < 24; i++) {
        counts[i] = 0;
    }
    let max = 0;
    items.forEach((item) => {
        const hour = Number(item.hour);
        if (isNaN(hour) || hour < 0 || hour > 23) {
            return;
        }
        counts[hour] = typeof item.count === 'number' ? item.count : 1;
        if (counts[hour] > max) {
            max = counts[hour];
        }
    });

    el.activityBar.textContent = '';
    const fragment = document.createDocumentFragment();

    for (let hour = 0; hour < 24; hour++) {
        const value = counts[hour];
        const column = create('button', value > 0 ? 'act-col' : 'act-col is-empty');
        column.type = 'button';
        column.title = pad2(hour) + ':00 · ' + value + ' 张';

        const track = create('span', 'act-track');
        const bar = create('span', 'act-bar');
        track.appendChild(bar);
        column.appendChild(track);

        const label = create('span', 'act-hour', hour % 6 === 0 ? pad2(hour) : '');
        column.appendChild(label);

        if (value > 0) {
            column.addEventListener('click', () => navigate(2, { date: state.date, hour: pad2(hour) }));
            const fraction = max > 0 ? value / max : 0;
            animateScaleY(bar, Math.max(0.1, fraction));
        } else {
            animateScaleY(bar, 0.06);
        }

        fragment.appendChild(column);
    }

    el.activityBar.appendChild(fragment);
    activityContent = true;
    applyLevelBar();
}

function renderSkeletons(count, isPhotos) {
    el.gallery.textContent = '';
    el.gallery.className = 'grid' + (isPhotos ? ' grid-photos' : '');
    const fragment = document.createDocumentFragment();
    for (let i = 0; i < count; i++) {
        fragment.appendChild(create('div', 'tile-skeleton skeleton'));
    }
    el.gallery.appendChild(fragment);
}

function renderTiles(items, isPhotos, describe, onSelect) {
    el.gallery.textContent = '';
    el.gallery.className = 'grid' + (isPhotos ? ' grid-photos' : '');

    if (!items || !items.length) {
        setStatus('当前层级没有找到照片。');
        return;
    }

    const fragment = document.createDocumentFragment();
    items.forEach((item, index) => {
        const meta = describe(item);

        const tile = create('button', 'tile');
        tile.type = 'button';

        const image = document.createElement('img');
        image.loading = 'lazy';
        image.decoding = 'async';
        image.alt = meta.label;
        bindImageFade(image);
        bindImageFallback(image);
        image.src = item.preview_image_url || item.image_url;

        const scrim = create('div', 'tile-scrim');
        scrim.appendChild(create('span', 'tile-label', meta.label));
        scrim.appendChild(create('span', 'tile-sub', meta.sub));

        tile.appendChild(image);
        tile.appendChild(scrim);
        tile.addEventListener('click', () => onSelect(item, index));
        fragment.appendChild(tile);
    });

    el.gallery.appendChild(fragment);
    stagger(el.gallery, '.tile', 26);
    restartAnimation(el.gallery);
}

function showError(message) {
    el.gallery.textContent = '';
    el.gallery.className = 'grid';
    clearLevelBar();
    setStatus(message, true);
}

async function loadDaily() {
    const date = state.date;
    renderSkeletons(6, false);

    let data;
    try {
        data = await apiGet('getDailySummary', { date });
    } catch (error) {
        showError(error.message);
        return;
    }
    if (!data) {
        return;
    }

    const items = data.hourly_previews || [];
    renderTiles(
        items,
        false,
        (item) => ({ label: item.hour + ':00', sub: formatFileSize(item.filesize) + ' · ' + item.count + ' 张' }),
        (item) => navigate(2, { date: date, hour: item.hour })
    );
    renderStats(items, undefined, items.length + ' 个小时');
    renderActivity(items);
}

async function loadHourly() {
    const date = state.date;
    const hour = state.hour;
    renderSkeletons(6, false);

    let data;
    try {
        data = await apiGet('getHourlySummary', { date, hour });
    } catch (error) {
        showError(error.message);
        return;
    }
    if (!data) {
        return;
    }

    const items = data.ten_minute_previews || [];
    renderTiles(
        items,
        false,
        (item) => ({ label: item.label, sub: formatFileSize(item.filesize) + ' · ' + item.count + ' 张' }),
        (item) => navigate(3, { date: date, hour: hour, slot: item.interval_slot })
    );
    renderStats(items, undefined, items.length + ' 个时段');
}

async function loadTenMinute() {
    const date = state.date;
    const hour = state.hour;
    const slot = state.slot;
    renderSkeletons(6, false);

    let data;
    try {
        data = await apiGet('getTenMinuteSummary', { date, hour, interval_slot: slot });
    } catch (error) {
        showError(error.message);
        return;
    }
    if (!data) {
        return;
    }

    const items = data.minute_previews || [];
    renderTiles(
        items,
        false,
        (item) => ({ label: hour + ':' + item.minute, sub: formatFileSize(item.filesize) + ' · ' + item.count + ' 张' }),
        (item) => navigate(4, { date: date, hour: hour, slot: slot, minute: item.minute })
    );
    renderStats(items, undefined, items.length + ' 个分钟');
}

async function loadMinute() {
    const date = state.date;
    const hour = state.hour;
    const minute = state.minute;
    renderSkeletons(4, true);

    let data;
    try {
        data = await apiGet('getMinutePhotos', { date, hour, minute });
    } catch (error) {
        showError(error.message);
        return;
    }
    if (!data) {
        return;
    }

    const photos = data.photos || [];
    const title = date + ' ' + hour + ':' + minute;
    /* 网格保持「最新在前」；查看器/轮播按时间正序，播放方向才符合延时摄影直觉 */
    const playlist = photos.slice().reverse();
    renderTiles(
        photos,
        true,
        (item) => {
            const sequence = sequenceOf(item);
            return {
                label: timeShort(item) + (sequence ? ' · ' + sequence : ''),
                sub: formatFileSize(item.filesize),
            };
        },
        (item) => {
            const target = playlist.indexOf(item);
            openViewer({ items: playlist, index: target < 0 ? 0 : target, title: title });
        }
    );
    renderStats(photos, photos.length, null);
}
