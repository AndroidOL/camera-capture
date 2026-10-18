import { apiGet } from './api.js';
import { el, setStatus } from './dom.js';
import { setMonitorCrumb } from './gallery.js';
import { bindImageFade, bindImageFallback, epochOf, formatFileSize, setImageSrc, timeLabel } from './util.js';
import { closeViewer, isViewerLive, openViewer, updateViewerItem } from './viewer.js';

const FORWARD_FACTOR = 0.8;
const BACKOFF_FACTOR = 1.25;
const OFFSET_MS = 150;
const RETRY_NO_NEW_PHOTO_MS = 4000;
const RETRY_NO_PHOTO_MS = 8000;
const REQUEST_TIMEOUT_MS = 5000;

/* 轮询边界可被 config.php 覆盖（index.php 渲染到 <body data-monitor-*>） */
const limits = { min: 1000, max: 8000, initial: 1500 };

const state = {
    active: false,
    timer: null,
    controller: null,
    photo: null,
    intervalMs: limits.initial,
    statusText: '',
    failures: 0,
};

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

    /* 页面不可见时停止轮询：省电、省请求，也避免后台标签页堆积定时器 */
    document.addEventListener('visibilitychange', () => {
        if (!state.active) {
            return;
        }
        if (document.hidden) {
            clearTimer();
            abortInFlight();
        } else {
            poll();
        }
    });

    window.addEventListener('offline', () => {
        if (state.active) {
            clearTimer();
            setMonitorStatus('网络已断开，等待恢复…');
        }
    });

    window.addEventListener('online', () => {
        if (state.active) {
            setMonitorStatus('网络已恢复，正在重连…');
            poll();
        }
    });
}

export function startMonitoring() {
    if (state.active) {
        return;
    }
    state.active = true;
    state.intervalMs = limits.initial;
    state.photo = null;
    state.failures = 0;

    clearMonitorImage();
    el.monitorFilename.textContent = '—';
    el.monitorFilesize.textContent = '—';
    el.monitorTime.textContent = '—';

    notify();
    setMonitorStatus('实时监控已启动。', true);
    setMonitorCrumb(null);
    poll();
}

export function stopMonitoring() {
    if (!state.active) {
        return;
    }
    state.active = false;
    clearTimer();
    abortInFlight();
    state.photo = null;
    clearMonitorImage();

    if (isViewerLive()) {
        closeViewer();
    }

    notify();
    setMonitorStatus('实时监控已停止。', true);
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

function abortInFlight() {
    if (state.controller) {
        try {
            state.controller.abort();
        } catch (error) {
            /* already settled */
        }
        state.controller = null;
    }
}

function setMonitorStatus(message, force) {
    if (!force && message === state.statusText) {
        return;
    }
    state.statusText = message;
    setStatus(message);
}

function scheduleNext(delayMs) {
    clearTimer();
    if (!state.active || document.hidden) {
        return;
    }
    state.timer = setTimeout(poll, Math.max(limits.min, delayMs));
}

async function poll() {
    if (!state.active || document.hidden) {
        return;
    }

    abortInFlight();
    const controller = new AbortController();
    state.controller = controller;

    let photo = null;
    let failed = false;
    try {
        const data = await apiGet(
            'getLatestPhoto',
            {},
            {
                silent: true,
                timeout: REQUEST_TIMEOUT_MS,
                signal: controller.signal,
            }
        );
        if (data && data.latest_photo) {
            photo = data.latest_photo;
        }
    } catch (error) {
        if (error && error.aborted) {
            return;
        }
        failed = true;
    } finally {
        if (state.controller === controller) {
            state.controller = null;
        }
    }

    if (!state.active) {
        return;
    }

    if (!photo) {
        state.failures += failed ? 1 : 0;
        setMonitorStatus(
            failed
                ? '获取最新照片失败，稍后自动重试…'
                : '暂无照片可监控，等待采集端写入…'
        );
        scheduleNext(failed ? Math.min(limits.max * 2, RETRY_NO_PHOTO_MS * state.failures) : RETRY_NO_PHOTO_MS);
        return;
    }

    state.failures = 0;
    const isNew = !state.photo || photo.filename !== state.photo.filename;

    if (isNew) {
        state.intervalMs = Math.max(limits.min, Math.round(state.intervalMs * FORWARD_FACTOR));
        state.photo = photo;
        applyPhoto(photo);
        setMonitorStatus('实时监控中…');

        /* 用最新一张的拍摄时间预测下一次抓拍；预测已过期时退回最小间隔 */
        const epoch = epochOf(photo);
        if (epoch) {
            const target = epoch * 1000 + state.intervalMs + OFFSET_MS;
            scheduleNext(Math.min(limits.max, Math.max(limits.min, target - Date.now())));
        } else {
            scheduleNext(RETRY_NO_NEW_PHOTO_MS);
        }
    } else {
        /* 没有新照片时按退避间隔轮询，而不是每秒空转一次 */
        state.intervalMs = Math.min(limits.max, Math.round(state.intervalMs * BACKOFF_FACTOR));
        setMonitorStatus('等待新照片…');
        scheduleNext(state.intervalMs);
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
