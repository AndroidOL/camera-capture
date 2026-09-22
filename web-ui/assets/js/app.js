import { apiGet } from './api.js';
import { el, setStatus } from './dom.js';
import { ensureAdminLoaded, initAdmin } from './admin.js';
import { observeReveal, restartAnimation } from './anim.js';
import { close as closeDatePicker, initDatePicker, setBounds as setDateBounds } from './datepicker.js';
import { getState, initGallery, resetToDate, setLevelBarVisible, updateChrome } from './gallery.js';
import { initMonitor } from './monitor.js';
import { startSlideshow } from './slideshow.js';
import { initTheme, applyAccent, applyTheme } from './theme.js';
import { initViewer } from './viewer.js';

const VIEWS = ['gallery', 'ops'];

function viewSections() {
    return { gallery: el.viewGallery, ops: el.viewOps };
}

function syncSegThumb() {
    if (!el.viewNav || !el.segThumb) {
        return;
    }
    const active = el.viewNav.querySelector('.seg-btn[aria-selected="true"]');
    if (!active) {
        return;
    }
    el.segThumb.style.width = active.offsetWidth + 'px';
    el.segThumb.style.transform = 'translateX(' + (active.offsetLeft - 3) + 'px)';
}

function setAppearanceOpen(open) {
    if (!el.appearancePop || !el.appearanceTrigger) {
        return;
    }
    el.appearancePop.hidden = !open;
    el.appearanceTrigger.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function closeAppearance() {
    if (el.appearancePop && !el.appearancePop.hidden) {
        setAppearanceOpen(false);
    }
}

function markSegment(view) {
    if (!el.viewNav) {
        return;
    }
    const buttons = el.viewNav.querySelectorAll('.seg-btn');
    for (let i = 0; i < buttons.length; i++) {
        buttons[i].setAttribute('aria-selected', buttons[i].dataset.view === view ? 'true' : 'false');
    }
    syncSegThumb();
}

export function showView(view) {
    const target = VIEWS.indexOf(view) === -1 ? 'gallery' : view;
    const sections = viewSections();

    VIEWS.forEach((name) => {
        const section = sections[name];
        if (!section) {
            return;
        }
        const active = name === target;
        section.hidden = !active;
        if (active) {
            restartAnimation(section);
        }
    });

    if (target === 'ops') {
        closeDatePicker();
        ensureAdminLoaded();
    }

    markSegment(target);

    if (window.location.hash !== '#' + target) {
        window.history.replaceState(null, '', '#' + target);
    }
}

function setMonitoringUi(active) {
    el.monitor.hidden = !active;
    el.gallery.hidden = active;
    el.monitorStartButton.hidden = active;
    el.monitorStopButton.hidden = !active;
    el.dpTrigger.disabled = active;
    el.slideshowButton.disabled = active;
    setLevelBarVisible(!active);

    if (active) {
        el.backButton.hidden = true;
    } else {
        updateChrome();
    }
}

async function loadDateBounds() {
    let earliest = null;
    let latest = null;

    try {
        const data = await apiGet('getEarliestDate', {}, { silent: true });
        if (data) {
            earliest = data.earliestDate;
        }
    } catch (error) {
        earliest = null;
    }

    try {
        const data = await apiGet('getLatestDate', {}, { silent: true });
        if (data) {
            latest = data.latestDate;
        }
    } catch (error) {
        latest = null;
    }

    return { earliest: earliest, latest: latest };
}

async function init() {
    initTheme();
    initViewer();
    initGallery();
    initMonitor({ onChange: setMonitoringUi });
    initAdmin();

    initDatePicker({
        onChange: (date) => {
            resetToDate(date);
        },
    });

    if (el.viewNav) {
        el.viewNav.addEventListener('click', (event) => {
            const button = event.target.closest ? event.target.closest('.seg-btn') : null;
            if (button && button.dataset.view) {
                showView(button.dataset.view);
            }
        });
        window.addEventListener('resize', syncSegThumb);
    }

    if (el.appearanceTrigger && el.appearancePop) {
        el.appearanceTrigger.addEventListener('click', (event) => {
            event.stopPropagation();
            setAppearanceOpen(el.appearancePop.hidden);
        });

        el.appearancePop.addEventListener('click', (event) => {
            const target = event.target;
            const accentOption = target.closest ? target.closest('[data-accent-option]') : null;
            if (accentOption) {
                applyAccent(accentOption.getAttribute('data-accent-option'));
                return;
            }
            const modeOption = target.closest ? target.closest('[data-mode-option]') : null;
            if (modeOption) {
                const mode = applyTheme(modeOption.getAttribute('data-mode-option'));
                if (el.themeLabel) {
                    el.themeLabel.textContent = mode === 'light' ? '浅色' : '深色';
                }
            }
        });

        document.addEventListener('click', (event) => {
            if (!el.appearancePop.hidden && !el.appearancePop.contains(event.target)) {
                closeAppearance();
            }
        });

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                closeAppearance();
            }
        });
    }

    if (el.slideshowButton) {
        el.slideshowButton.addEventListener('click', () => startSlideshow(getState()));
    }

    observeReveal(document);

    /* URL hash 优先（保持可分享），否则用 config.php 的 default_view */
    const hash = (window.location.hash || '').replace('#', '');
    const configured = document.body && document.body.dataset ? document.body.dataset.view : '';
    const fallback = VIEWS.indexOf(configured) === -1 ? 'gallery' : configured;
    showView(VIEWS.indexOf(hash) === -1 ? fallback : hash);

    const bounds = await loadDateBounds();

    setDateBounds(bounds.earliest, bounds.latest);

    if (!bounds.latest) {
        el.dpTrigger.disabled = true;
        el.slideshowButton.disabled = true;
        el.monitorStartButton.disabled = true;
        setStatus('照片库中还没有照片。请确认 captures_dir / GALLERY_CAPTURES_DIR 指向了正确的目录（Docker 请检查卷映射）。');
        return;
    }

    resetToDate(bounds.latest);
    syncSegThumb();
}

init();
