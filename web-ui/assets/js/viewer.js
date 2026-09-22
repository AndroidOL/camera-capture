import { el, create } from './dom.js';
import { restartAnimation } from './anim.js';
import { epochOf, formatDuration, formatFileSize, preloadAround, timeLabel, timeShort } from './util.js';

/* 1x = 实时（1 真实秒 = 1 播放秒）；每帧停留时长按真实抓拍间隔 / 倍速 计算 */
const SPEEDS = [1, 2, 4, 8, 16, 32];
const BASE_GAP_MS = 1000;
const MAX_GAP_MS = 6000;
const MIN_DWELL_MS = 100;

/* 由 config.php 渲染到 <body data-*>，见 index.php */
function bodyData(key) {
    return document.body && document.body.dataset ? document.body.dataset[key] : undefined;
}

function configuredSpeedIndex() {
    const index = SPEEDS.indexOf(Number(bodyData('speed')));
    return index === -1 ? 0 : index;
}

function downloadsEnabled() {
    return bodyData('download') !== '0';
}

const state = {
    open: false,
    live: false,
    items: [],
    index: 0,
    title: '',
    onClose: null,
    playing: false,
    speedIndex: 0,
    timer: null,
};

export function isViewerOpen() {
    return state.open;
}

export function isViewerLive() {
    return state.open && state.live;
}

export function openViewer(options) {
    const settings = options || {};
    state.items = Array.isArray(settings.items) ? settings.items.slice() : [];
    if (!state.items.length) {
        return;
    }

    state.live = !!settings.live;
    state.title = settings.title || '';
    state.onClose = typeof settings.onClose === 'function' ? settings.onClose : null;
    state.index = Math.min(Math.max(0, Number(settings.index) || 0), state.items.length - 1);
    state.speedIndex = configuredSpeedIndex();
    state.playing = false;
    resetProgress();
    closeSpeedMenu();

    render(false);

    el.viewer.hidden = false;
    el.viewer.classList.toggle('is-maximized', !!settings.maximized);
    el.viewer.classList.add('is-open');
    restartAnimation(el.viewerShell);
    document.body.classList.add('no-scroll');

    state.open = true;

    if (!state.live) {
        preloadAround(state.items, state.index);
    }

    if (settings.autoplay && !state.live && state.items.length > 1) {
        play();
    } else {
        el.viewerClose.focus();
    }
}

export function closeViewer() {
    if (!state.open) {
        return;
    }
    stopTimer();
    closeSpeedMenu();
    state.playing = false;
    state.open = false;

    el.viewer.hidden = true;
    el.viewer.classList.remove('is-maximized', 'is-open');
    el.viewerImage.classList.remove('is-swapping');
    document.body.classList.remove('no-scroll');
    el.viewerImage.removeAttribute('src');

    const callback = state.onClose;
    state.onClose = null;
    state.items = [];
    state.live = false;
    state.title = '';

    if (callback) {
        callback();
    }
}

export function updateViewerItem(item) {
    if (!state.open || !state.live || !item) {
        return;
    }
    state.items = [item];
    state.index = 0;
    render(true);
}

/* ---------------------------------------------------------------- 播放节拍 */

function gapMsFor(index) {
    const current = state.items[index];
    if (!current) {
        return BASE_GAP_MS;
    }

    const currentEpoch = epochOf(current);
    if (currentEpoch === null) {
        return BASE_GAP_MS;
    }

    let reference = state.items[index + 1];
    if (!reference) {
        /* 最后一帧沿用与前一帧的间隔 */
        reference = state.items[index - 1];
    }
    if (!reference) {
        return BASE_GAP_MS;
    }

    const referenceEpoch = epochOf(reference);
    if (referenceEpoch === null) {
        return BASE_GAP_MS;
    }

    const gap = Math.abs(currentEpoch - referenceEpoch) * 1000;
    if (!isFinite(gap) || gap <= 0) {
        return BASE_GAP_MS;
    }
    return Math.min(gap, MAX_GAP_MS);
}

function dwellMsFor(index, speed) {
    return Math.max(MIN_DWELL_MS, Math.round(gapMsFor(index) / speed));
}

function currentDwellMs() {
    return dwellMsFor(state.index, SPEEDS[state.speedIndex]);
}

function dwellText(ms) {
    return ms < 1000 ? ms + ' ms' : (ms / 1000).toFixed(1) + ' 秒';
}

function stopTimer() {
    if (state.timer !== null) {
        clearTimeout(state.timer);
        state.timer = null;
    }
}

function play() {
    if (state.live || state.items.length <= 1) {
        return;
    }
    state.playing = true;
    updatePlayUi();
    scheduleNext();
}

function pause() {
    state.playing = false;
    stopTimer();
    updatePlayUi();
    resetProgress();
    renderTimeline(state.items[state.index]);
}

function togglePlay() {
    if (state.playing) {
        pause();
    } else {
        play();
    }
}

function scheduleNext() {
    stopTimer();
    if (!state.playing || state.live || state.items.length <= 1) {
        return;
    }
    const duration = currentDwellMs();
    runProgress(duration);
    state.timer = setTimeout(() => {
        if (!state.playing) {
            return;
        }
        if (state.index >= state.items.length - 1) {
            jumpTo(0);
        } else {
            navigate(1);
        }
    }, duration);
}

function runProgress(duration) {
    const bar = el.viewerProgress ? el.viewerProgress.firstElementChild : null;
    if (!bar) {
        return;
    }
    bar.style.transition = 'none';
    bar.style.width = '0%';
    void bar.offsetWidth;
    bar.style.transition = 'width ' + duration + 'ms linear';
    bar.style.width = '100%';
}

function resetProgress() {
    const bar = el.viewerProgress ? el.viewerProgress.firstElementChild : null;
    if (!bar) {
        return;
    }
    bar.style.transition = 'none';
    bar.style.width = '0%';
}

function updatePlayUi() {
    const single = state.live || state.items.length <= 1;
    el.viewerPlay.hidden = single;
    el.viewerSpeed.hidden = single;
    if (el.viewerProgress) {
        el.viewerProgress.hidden = single;
    }
    if (el.viewerStage) {
        el.viewerStage.classList.toggle('has-progress', !single);
    }
    if (single) {
        closeSpeedMenu();
        return;
    }

    el.viewerPlay.classList.toggle('is-playing', state.playing);
    el.viewerPlayLabel.textContent = state.playing ? '暂停' : '播放';
    el.viewerPlay.setAttribute('aria-label', state.playing ? '暂停' : '播放');

    if (el.viewerSpeedValue) {
        el.viewerSpeedValue.textContent = SPEEDS[state.speedIndex] + 'x';
    }
}

/* ------------------------------------------------------------- 倍速菜单 */

function buildSpeedMenu() {
    if (!el.viewerSpeedMenu) {
        return;
    }
    el.viewerSpeedMenu.textContent = '';

    const fragment = document.createDocumentFragment();
    for (let i = 0; i < SPEEDS.length; i++) {
        const speed = SPEEDS[i];
        const item = create('button', 'speed-item' + (i === state.speedIndex ? ' is-active' : ''));
        item.type = 'button';
        item.setAttribute('role', 'menuitemradio');
        item.setAttribute('aria-checked', i === state.speedIndex ? 'true' : 'false');
        item.dataset.speed = String(i);
        item.appendChild(create('span', 'speed-item-value', speed + 'x'));
        item.appendChild(
            create(
                'span',
                'speed-item-hint',
                '每帧 ' + dwellText(dwellMsFor(state.index, speed)) + (speed === 1 ? ' · 实时' : '')
            )
        );
        fragment.appendChild(item);
    }
    el.viewerSpeedMenu.appendChild(fragment);
}

function openSpeedMenu() {
    if (!el.viewerSpeedMenu) {
        return;
    }
    buildSpeedMenu();
    el.viewerSpeedMenu.hidden = false;
    el.viewerSpeedTrigger.setAttribute('aria-expanded', 'true');
}

function closeSpeedMenu() {
    if (!el.viewerSpeedMenu || el.viewerSpeedMenu.hidden) {
        return;
    }
    el.viewerSpeedMenu.hidden = true;
    if (el.viewerSpeedTrigger) {
        el.viewerSpeedTrigger.setAttribute('aria-expanded', 'false');
    }
}

function toggleSpeedMenu() {
    if (el.viewerSpeedMenu && !el.viewerSpeedMenu.hidden) {
        closeSpeedMenu();
    } else {
        openSpeedMenu();
    }
}

function isSpeedMenuOpen() {
    return !!(el.viewerSpeedMenu && !el.viewerSpeedMenu.hidden);
}

/* ---------------------------------------------------------------- 导航 */

function navigate(direction) {
    if (state.live) {
        return;
    }
    const next = state.index + direction;
    if (next < 0 || next >= state.items.length) {
        return;
    }
    state.index = next;
    render(true);
    preloadAround(state.items, state.index);
    if (state.playing) {
        scheduleNext();
    }
}

function jumpTo(index) {
    if (state.live) {
        return;
    }
    const target = Math.min(Math.max(0, index), state.items.length - 1);
    if (target === state.index) {
        return;
    }
    state.index = target;
    render(true);
    preloadAround(state.items, state.index);
    if (state.playing) {
        scheduleNext();
    }
}

function toggleMaximize() {
    const maximized = el.viewer.classList.toggle('is-maximized');
    el.viewerMaximize.title = maximized ? '还原' : '最大化';
    el.viewerMaximize.setAttribute('aria-label', maximized ? '还原' : '最大化');
}

function swapImage(url) {
    const image = el.viewerImage;
    image.classList.add('is-swapping');

    let settled = false;
    const finish = () => {
        if (settled) {
            return;
        }
        settled = true;
        image.removeEventListener('load', finish);
        image.classList.remove('is-swapping');
    };

    image.addEventListener('load', finish);
    image.src = url;
    window.setTimeout(finish, 260);
}

/* ---------------------------------------------------------------- 渲染 */

function renderInterval(item) {
    if (!el.viewerInterval) {
        return;
    }
    if (state.live) {
        el.viewerInterval.textContent = '—';
        return;
    }
    if (state.index === 0) {
        el.viewerInterval.textContent = state.items.length > 1 ? '首张' : '—';
        return;
    }
    const current = epochOf(item);
    const previous = epochOf(state.items[state.index - 1]);
    if (current === null || previous === null) {
        el.viewerInterval.textContent = '—';
        return;
    }
    el.viewerInterval.textContent = '+' + formatDuration(Math.abs(current - previous));
}

function renderTimeline(item) {
    const multiple = !state.live && state.items.length > 1;
    el.viewerTimelineWrap.hidden = !multiple;
    if (!multiple || !item) {
        return;
    }

    el.viewerTimeline.min = '0';
    el.viewerTimeline.max = String(state.items.length - 1);
    el.viewerTimeline.value = String(state.index);

    el.viewerTimelineFrom.textContent = timeShort(state.items[0]);
    el.viewerTimelineTo.textContent = timeShort(state.items[state.items.length - 1]);

    let label = timeShort(item) + ' · ' + (state.index + 1) + '/' + state.items.length;
    if (state.playing) {
        label += ' · ' + (currentDwellMs() / 1000).toFixed(1) + 's';
    }
    el.viewerTimelineLabel.textContent = label;
}

function render(animate) {
    const item = state.items[state.index];
    if (!item) {
        closeViewer();
        return;
    }

    if (animate) {
        swapImage(item.image_url);
    } else {
        el.viewerImage.classList.remove('is-swapping');
        el.viewerImage.src = item.image_url;
    }

    el.viewerImage.alt = item.filename || '';
    el.viewerFilename.textContent = item.filename || '—';
    el.viewerFilesize.textContent = formatFileSize(item.filesize);
    el.viewerTime.textContent = timeLabel(item);

    el.viewerDownload.href = item.download_url || item.image_url;
    el.viewerDownload.setAttribute('download', item.filename || 'photo.jpg');
    el.viewerDownload.hidden = !downloadsEnabled();

    el.viewerTitle.hidden = !state.title;
    el.viewerTitle.textContent = state.title;

    const single = state.live || state.items.length <= 1;
    el.viewerCounter.hidden = single;
    el.viewerPrev.hidden = single;
    el.viewerNext.hidden = single;

    if (!single) {
        el.viewerCounter.textContent = state.index + 1 + ' / ' + state.items.length;
        el.viewerPrev.disabled = state.index === 0;
        el.viewerNext.disabled = state.index === state.items.length - 1;
    }

    renderInterval(item);
    renderTimeline(item);
    updatePlayUi();
}

/* ---------------------------------------------------------------- 初始化 */

export function initViewer() {
    el.viewerClose.addEventListener('click', closeViewer);
    el.viewerPrev.addEventListener('click', () => navigate(-1));
    el.viewerNext.addEventListener('click', () => navigate(1));
    el.viewerMaximize.addEventListener('click', toggleMaximize);
    el.viewerPlay.addEventListener('click', togglePlay);

    el.viewerSpeedTrigger.addEventListener('click', (event) => {
        event.stopPropagation();
        toggleSpeedMenu();
    });

    el.viewerSpeedMenu.addEventListener('click', (event) => {
        const item = event.target.closest ? event.target.closest('.speed-item') : null;
        if (!item) {
            return;
        }
        const index = Number(item.dataset.speed);
        if (isNaN(index) || index < 0 || index >= SPEEDS.length) {
            return;
        }
        state.speedIndex = index;
        closeSpeedMenu();
        updatePlayUi();
        if (state.playing) {
            scheduleNext();
        }
    });

    el.viewerTimeline.addEventListener('input', () => {
        const index = Number(el.viewerTimeline.value);
        if (Number.isNaN(index)) {
            return;
        }
        state.index = Math.min(Math.max(0, index), state.items.length - 1);
        const item = state.items[state.index];
        if (item) {
            el.viewerImage.src = item.image_url;
            el.viewerImage.alt = item.filename || '';
            el.viewerFilename.textContent = item.filename || '—';
            el.viewerFilesize.textContent = formatFileSize(item.filesize);
            el.viewerTime.textContent = timeLabel(item);
            el.viewerDownload.href = item.download_url || item.image_url;
            el.viewerDownload.setAttribute('download', item.filename || 'photo.jpg');
            el.viewerCounter.textContent = state.index + 1 + ' / ' + state.items.length;
            el.viewerPrev.disabled = state.index === 0;
            el.viewerNext.disabled = state.index === state.items.length - 1;
            renderInterval(item);
            renderTimeline(item);
        }
    });

    el.viewerTimeline.addEventListener('change', () => {
        preloadAround(state.items, state.index);
        if (state.playing) {
            scheduleNext();
        }
    });

    el.viewer.addEventListener('click', (event) => {
        if (event.target === el.viewer) {
            closeViewer();
        }
    });

    document.addEventListener('click', (event) => {
        if (!state.open || !isSpeedMenuOpen()) {
            return;
        }
        if (el.viewerSpeed && !el.viewerSpeed.contains(event.target)) {
            closeSpeedMenu();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (!state.open) {
            return;
        }

        const tag = event.target && event.target.tagName ? event.target.tagName.toLowerCase() : '';
        const typing = tag === 'input' || tag === 'textarea';

        if (event.key === 'Escape') {
            if (isSpeedMenuOpen()) {
                closeSpeedMenu();
                return;
            }
            closeViewer();
        } else if (event.key === 'ArrowLeft') {
            navigate(-1);
        } else if (event.key === 'ArrowRight') {
            navigate(1);
        } else if (event.key === ' ' && !typing) {
            if (!state.live && state.items.length > 1) {
                event.preventDefault();
                togglePlay();
            }
        } else if (event.key === 'Home' && !typing) {
            event.preventDefault();
            jumpTo(0);
        } else if (event.key === 'End' && !typing) {
            event.preventDefault();
            jumpTo(state.items.length - 1);
        }
    });
}
