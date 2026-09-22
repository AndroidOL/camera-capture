import { apiGet } from './api.js';
import { el, setStatus } from './dom.js';
import { setMonitorCrumb } from './gallery.js';
import { bindImageFade, bindImageFallback, epochOf, formatFileSize, setImageSrc, timeLabel } from './util.js';
import { closeViewer, isViewerLive, openViewer, updateViewerItem } from './viewer.js';

const FORWARD_FACTOR = 0.8;
const BACKOFF_FACTOR = 1.25;
const OFFSET_MS = 150;
const RETRY_NO_NEW_PHOTO_MS = 3000;
const RETRY_NO_PHOTO_MS = 10000;

/* 轮询边界可被 config.php 覆盖（index.php 渲染到 <body data-monitor-*>） */
const limits = { min: 1000, max: 8000, initial: 1500 };

const state = { active: false, timer: null, photo: null, intervalMs: limits.initial };
let onChange = null;

export function isMonitoring() {
    return state.active;
}

export function initMonitor(options) {
    onChange = options && typeof options.onChange === 'function' ? options.onChange : null;

    const body = document.body;
    if (body && body.dataset) {
        const min = Number(body.dataset.monitorMin);
        const max = Number(body.dataset.monitorMax);
        const initial = Number(body.dataset.monitorInitial);
        if (isFinite(min) && min >= 100) {
            limits.min = min;
        }
        if (isFinite(max) && max >= 100) {
            limits.max = Math.max(max, limits.min);
        }
        if (isFinite(initial) && initial >= 100) {
            limits.initial = Math.min(Math.max(initial, limits.min), limits.max);
        }
    }

    bindImageFade(el.monitorImage);
    bindImageFallback(el.monitorImage);
    el.monitorStartButton.addEventListener('click', () => startMonitoring());
    el.monitorStopButton.addEventListener('click', () => stopMonitoring());
    el.monitorMaximize.addEventListener('click', openLiveViewer);
}

export function startMonitoring() {
    if (state.active) {
        return;
    }
    state.active = true;
    state.intervalMs = limits.initial;
    state.photo = null;

    clearMonitorImage();
    el.monitorFilename.textContent = '—';
    el.monitorFilesize.textContent = '—';
    el.monitorTime.textContent = '—';

    notify();
    setStatus('实时监控已启动。');
    setMonitorCrumb(null);
    poll();
}

export function stopMonitoring() {
    if (!state.active) {
        return;
    }
    state.active = false;
    clearTimer();
    state.photo = null;
    clearMonitorImage();

    if (isViewerLive()) {
        closeViewer();
    }

    notify();
    setStatus('实时监控已停止。');
}

function clearMonitorImage() {
    el.monitorImage.removeAttribute('src');
    el.monitorImage.classList.remove('is-loaded');
}

function notify() {
    if (onChange) {
        onChange(state.active);
    }
}

function clearTimer() {
    if (state.timer !== null) {
        clearTimeout(state.timer);
        state.timer = null;
    }
}

function scheduleNext(delayMs) {
    clearTimer();
    if (!state.active) {
        return;
    }
    state.timer = setTimeout(poll, delayMs);
}

async function poll() {
    if (!state.active) {
        return;
    }

    let photo = null;
    let failed = false;
    try {
        const data = await apiGet('getLatestPhoto', {}, { silent: true });
        if (data && data.latest_photo) {
            photo = data.latest_photo;
        }
    } catch (error) {
        failed = true;
    }

    if (!state.active) {
        return;
    }

    if (!photo) {
        setStatus(failed ? '获取最新照片失败，稍后重试。' : '暂无照片可监控，稍后重试。');
        scheduleNext(RETRY_NO_PHOTO_MS);
        return;
    }

    const isNew = !state.photo || photo.filename !== state.photo.filename;
    if (isNew) {
        state.intervalMs = Math.max(limits.min, Math.round(state.intervalMs * FORWARD_FACTOR));
        state.photo = photo;
        applyPhoto(photo);
    } else {
        state.intervalMs = Math.min(limits.max, Math.round(state.intervalMs * BACKOFF_FACTOR));
    }

    const epoch = epochOf(photo);
    if (epoch) {
        const target = epoch * 1000 + state.intervalMs + OFFSET_MS;
        scheduleNext(Math.max(limits.min, target - Date.now()));
    } else {
        scheduleNext(RETRY_NO_NEW_PHOTO_MS);
    }
}

function applyPhoto(photo) {
    setImageSrc(el.monitorImage, photo.image_url);
    el.monitorImage.alt = photo.filename;
    el.monitorFilename.textContent = photo.filename;
    el.monitorFilesize.textContent = formatFileSize(photo.filesize);
    el.monitorTime.textContent = timeLabel(photo);
    setMonitorCrumb(photo);

    if (isViewerLive()) {
        updateViewerItem(photo);
    }
}

function openLiveViewer() {
    if (!state.photo) {
        setStatus('暂无可放大的照片。', true);
        return;
    }
    openViewer({ items: [state.photo], index: 0, live: true, title: '实时监控', maximized: true });
}
