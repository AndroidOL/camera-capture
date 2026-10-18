import { apiGet } from './api.js';
import { el, setStatus } from './dom.js';
import { ensureAdminLoaded, initAdmin, resetAdminState } from './admin.js';
import { observeReveal, prefersReducedMotion, replayReveal, restartAnimation } from './anim.js';
import { close as closeDatePicker, initDatePicker, setBounds as setDateBounds } from './datepicker.js';
import {
    getHistory as getGalleryHistory,
    getState,
    initGallery,
    resetGalleryState,
    resetToDate,
    restoreGalleryState,
    setLevelBarVisible,
    showGallerySkeletons,
    updateChrome,
} from './gallery.js';
import { initMonitor, isMonitoring, stopMonitoring } from './monitor.js';
import { startSlideshow } from './slideshow.js';
import { initTheme, applyAccent, applyTheme } from './theme.js';
import { closeViewer, initViewer, isViewerOpen } from './viewer.js';

const VIEWS = ['gallery', 'ops'];

let segThumbFrame = null;
let appearanceTimer = null;
let authenticated = document.body.dataset.authenticated === '1';
let appStarted = false;
let booting = false;
let appGeneration = 0;
let currentView = 'gallery';
let historySeeded = false;

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

function requestSegThumb() {
    if (segThumbFrame !== null) {
        return;
    }
    segThumbFrame = window.requestAnimationFrame(() => {
        segThumbFrame = null;
        syncSegThumb();
    });
}

function setAppearanceOpen(open) {
    if (!el.appearancePop || !el.appearanceTrigger) {
        return;
    }

    if (appearanceTimer !== null) {
        window.clearTimeout(appearanceTimer);
        appearanceTimer = null;
    }

    if (open) {
        el.appearancePop.hidden = false;
        el.appearancePop.classList.remove('is-closing');
    } else if (!el.appearancePop.hidden) {
        if (prefersReducedMotion()) {
            el.appearancePop.hidden = true;
            el.appearancePop.classList.remove('is-closing');
        } else {
            el.appearancePop.classList.add('is-closing');
            appearanceTimer = window.setTimeout(() => {
                appearanceTimer = null;
                el.appearancePop.hidden = true;
                el.appearancePop.classList.remove('is-closing');
            }, 150);
        }
    }

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
    requestSegThumb();
}

function historyStateFor(view) {
    return {
        view: view,
        gallery: getState(),
        galleryHistory: getGalleryHistory(),
    };
}

/**
 * 切换「相册 / 运维」视图。
 * options.fromHistory —— 由 popstate 驱动，不写入历史
 * options.replace     —— 用 replaceState 而不是 pushState（首屏）
 */
export function showView(view, options) {
    const settings = options || {};
    const target = VIEWS.indexOf(view) === -1 ? 'gallery' : view;
    const changed = target !== currentView;
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

    currentView = target;

    if (target === 'ops') {
        closeDatePicker();
        ensureAdminLoaded();
        replayReveal(sections.ops);
    }

    markSegment(target);

    if (!settings.fromHistory && (changed || settings.replace)) {
        if (settings.replace) {
            window.history.replaceState(historyStateFor(target), '', '#' + target);
        } else {
            window.history.pushState(historyStateFor(target), '', '#' + target);
            historySeeded = true;
        }
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
    /* 一个请求拿全上下界，首屏少一次网络往返 */
    try {
        const data = await apiGet('getDateBounds', {}, { silent: true, timeout: 8000, retries: 1 });
        if (data) {
            return {
                earliest: data.earliestDate || null,
                latest: data.latestDate || null,
            };
        }
    } catch (error) {
        /* 落到下面的兼容分支 */
    }

    const results = await Promise.all([
        apiGet('getEarliestDate', {}, { silent: true, timeout: 8000 }).catch(() => null),
        apiGet('getLatestDate', {}, { silent: true, timeout: 8000 }).catch(() => null),
    ]);

    return {
        earliest: results[0] ? results[0].earliestDate : null,
        latest: results[1] ? results[1].latestDate : null,
    };
}

/* ==========================================================================
   History API：视图切换、日期/层级钻取都留在页面内
   ========================================================================== */

document.addEventListener('gallery:state', (event) => {
    if (!authenticated || !appStarted || currentView !== 'gallery') {
        return;
    }

    const detail = event.detail || {};
    const state = {
        view: 'gallery',
        gallery: detail.state || getState(),
        galleryHistory: detail.history || getGalleryHistory(),
    };

    if (!historySeeded) {
        window.history.replaceState(state, '', '#gallery');
        historySeeded = true;
        return;
    }
    window.history.pushState(state, '', '#gallery');
});

window.addEventListener('popstate', (event) => {
    if (!authenticated) {
        /* 登出后历史里仍可能残留旧视图 state；保持在登录浮层，不恢复任何数据 */
        window.history.replaceState({ view: 'auth' }, '', 'index.php');
        return;
    }
    if (!appStarted) {
        return;
    }

    const state = event.state;
    if (!state || VIEWS.indexOf(state.view) === -1) {
        return;
    }

    showView(state.view, { fromHistory: true });
    if (state.view === 'gallery' && state.gallery) {
        restoreGalleryState({ state: state.gallery, history: state.galleryHistory });
    }
});

/* ==========================================================================
   登录 / 登出（AJAX，不触发整页刷新）
   ========================================================================== */

function setAuthError(message) {
    if (!el.authError) {
        return;
    }
    if (message) {
        el.authError.textContent = message;
        el.authError.hidden = false;
    } else {
        el.authError.textContent = '';
        el.authError.hidden = true;
    }
}

function updateCsrfTokens(token) {
    if (!token) {
        return;
    }
    const inputs = document.querySelectorAll('input[name="csrf_token"]');
    for (let i = 0; i < inputs.length; i++) {
        inputs[i].value = token;
    }
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) {
        meta.setAttribute('content', token);
    }
}

function setAuthBusy(active, label) {
    if (el.authSubmit) {
        el.authSubmit.disabled = active;
        el.authSubmit.textContent = active ? label || '登录中…' : '登 录';
    }
    if (el.authPassword) {
        el.authPassword.disabled = active;
    }
}

let authCooldownTimer = null;

function clearAuthCooldown() {
    if (authCooldownTimer !== null) {
        window.clearInterval(authCooldownTimer);
        authCooldownTimer = null;
    }
}

/**
 * 服务端返回 429 + retry_after 时，在登录浮层内做倒计时冷却，
 * 避免用户连续点击继续撞限流。
 */
function startAuthCooldown(seconds, message) {
    clearAuthCooldown();
    let remaining = Math.max(1, Math.ceil(Number(seconds) || 60));
    const base = message || '尝试次数过多，请稍后再试。';

    const render = () => {
        setAuthBusy(true, '请 ' + remaining + ' 秒后重试');
        const suffix = base.indexOf('秒后再试') === -1 ? '（' + remaining + ' 秒后可重试）' : '';
        setAuthError(base + suffix);
    };

    render();
    authCooldownTimer = window.setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
            window.clearInterval(authCooldownTimer);
            authCooldownTimer = null;
            setAuthBusy(false);
            setAuthError(base);
            return;
        }
        render();
    }, 1000);
}

function showAuthOverlay(message, subText) {
    if (!el.authOverlay) {
        return;
    }
    el.authOverlay.hidden = false;
    document.body.classList.add('auth-open');
    if (el.appRoot) {
        el.appRoot.setAttribute('aria-hidden', 'true');
        el.appRoot.setAttribute('inert', '');
    }
    if (el.authSub) {
        el.authSub.textContent = subText || '请输入访问密码';
    }
    setAuthError(message || '');
    window.setTimeout(() => {
        if (el.authPassword && !el.authPassword.disabled) {
            el.authPassword.focus();
        }
    }, 60);
}

function hideAuthOverlay() {
    if (el.authOverlay) {
        el.authOverlay.hidden = true;
    }
    document.body.classList.remove('auth-open');
    if (el.appRoot) {
        el.appRoot.setAttribute('aria-hidden', 'false');
        el.appRoot.removeAttribute('inert');
    }
    setAuthError('');
}

async function authRequest(url, formData) {
    if (typeof fetch !== 'function') {
        throw new Error('当前浏览器不支持 AJAX 请求。');
    }

    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const timer = controller
        ? window.setTimeout(() => {
              try {
                  controller.abort();
              } catch (error) {
                  /* ignore */
              }
          }, 15000)
        : null;

    try {
        const response = await fetch(url, {
            method: 'POST',
            body: formData,
            credentials: 'same-origin',
            headers: {
                Accept: 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            signal: controller ? controller.signal : undefined,
        });

        let payload = null;
        try {
            payload = await response.json();
        } catch (error) {
            payload = null;
        }

        if (!response.ok) {
            const requestError = new Error(
                payload && payload.error ? payload.error : '请求失败（HTTP ' + response.status + '）'
            );
            requestError.status = response.status;
            if (payload && payload.retry_after) {
                requestError.retryAfter = Number(payload.retry_after);
            }
            if (payload && payload.remaining !== undefined) {
                requestError.remaining = Number(payload.remaining);
            }
            throw requestError;
        }
        return payload || {};
    } catch (error) {
        if (error && error.name === 'AbortError') {
            throw new Error('请求超时，请重试。');
        }
        throw error;
    } finally {
        if (timer !== null) {
            window.clearTimeout(timer);
        }
    }
}

function resetAppData() {
    if (isMonitoring()) {
        stopMonitoring();
    }
    if (isViewerOpen()) {
        closeViewer();
    }

    resetGalleryState();
    resetAdminState();

    appGeneration++;
    appStarted = false;
    booting = false;
    historySeeded = false;
    authenticated = false;
    currentView = 'gallery';
    document.body.dataset.authenticated = '0';
}

function resetAuthForm() {
    clearAuthCooldown();
    if (el.authPassword) {
        el.authPassword.value = '';
        el.authPassword.setAttribute('type', 'password');
        el.authPassword.disabled = false;
    }
    if (el.authToggle) {
        el.authToggle.textContent = '显示';
    }
    setAuthBusy(false);
}

function resetAppForLogout() {
    resetAppData();
    resetAuthForm();
    showAuthOverlay('', '已退出登录，请重新输入密码。');
    window.history.replaceState({ view: 'auth' }, '', 'index.php');
}

let handlingUnauthorized = false;

/**
 * 会话超时：清空旧数据，取一个新的 CSRF token，然后原地显示登录浮层。
 * 只有取 token 失败时才回退到整页加载。
 */
async function handleUnauthorized(message) {
    if (handlingUnauthorized || !authenticated) {
        return;
    }
    handlingUnauthorized = true;
    resetAppData();

    try {
        const response = await fetch('login.php', {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
                Accept: 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
        });
        let payload = null;
        try {
            payload = await response.json();
        } catch (error) {
            payload = null;
        }
        if (!response.ok || !payload || !payload.csrf_token) {
            throw new Error('无法获取新的会话令牌。');
        }
        updateCsrfTokens(payload.csrf_token);
        resetAuthForm();
        showAuthOverlay(message || '会话已超时，请重新登录。');
        window.history.replaceState({ view: 'auth' }, '', 'index.php');
    } catch (error) {
        window.location.replace('index.php?error=session_timeout');
    } finally {
        handlingUnauthorized = false;
    }
}

document.addEventListener('gallery:unauthorized', (event) => {
    const detail = event.detail || {};
    handleUnauthorized(detail.message);
});

function initAuth() {
    if (!el.authForm || typeof fetch !== 'function') {
        return;
    }

    el.authForm.addEventListener('submit', async (event) => {
        event.preventDefault();

        const password = el.authPassword ? el.authPassword.value : '';
        if (!password) {
            setAuthError('请输入密码。');
            if (el.authPassword) {
                el.authPassword.focus();
            }
            return;
        }

        setAuthBusy(true);
        setAuthError('');

        try {
            const data = await authRequest('login.php', new FormData(el.authForm));
            if (!data.ok) {
                throw new Error(data.error || '登录失败，请重试。');
            }

            updateCsrfTokens(data.csrf_token);
            authenticated = true;
            document.body.dataset.authenticated = '1';
            clearAuthCooldown();
            if (el.authPassword) {
                el.authPassword.value = '';
            }
            hideAuthOverlay();

            try {
                await startApp();
            } catch (error) {
                authenticated = false;
                document.body.dataset.authenticated = '0';
                showAuthOverlay('登录成功，但页面初始化失败：' + error.message);
            }
        } catch (error) {
            if (error.status === 429 && error.retryAfter) {
                startAuthCooldown(error.retryAfter, error.message);
            } else {
                setAuthError(error.message);
            }
            if (error.status === 403) {
                /* 会话已失效导致 CSRF 校验失败：重新加载壳层以获取新 token */
                window.setTimeout(() => window.location.replace('index.php'), 1500);
            }
        } finally {
            if (authCooldownTimer === null) {
                setAuthBusy(false);
            }
        }
    });

    if (el.logoutForm) {
        el.logoutForm.addEventListener('submit', async (event) => {
            event.preventDefault();

            if (el.logoutButton) {
                el.logoutButton.disabled = true;
            }

            try {
                const data = await authRequest('logout.php', new FormData(el.logoutForm));
                updateCsrfTokens(data.csrf_token);
                resetAppForLogout();
            } catch (error) {
                setStatus('退出登录失败：' + error.message, true);
                if (error.status === 403) {
                    window.setTimeout(() => window.location.replace('index.php'), 1500);
                }
            } finally {
                if (el.logoutButton) {
                    el.logoutButton.disabled = false;
                }
            }
        });
    }

    if (el.authToggle && el.authPassword) {
        el.authToggle.addEventListener('click', () => {
            const isPassword = el.authPassword.getAttribute('type') === 'password';
            el.authPassword.setAttribute('type', isPassword ? 'text' : 'password');
            el.authToggle.textContent = isPassword ? '隐藏' : '显示';
        });
    }

    if (el.authCaps && el.authPassword) {
        const updateCaps = (event) => {
            const locked = event.getModifierState && event.getModifierState('CapsLock');
            el.authCaps.hidden = !locked;
        };
        el.authPassword.addEventListener('keydown', updateCaps);
        el.authPassword.addEventListener('keyup', updateCaps);
        el.authPassword.addEventListener('focus', updateCaps);
        el.authPassword.addEventListener('blur', () => {
            el.authCaps.hidden = true;
        });
    }
}

/* ==========================================================================
   已登录数据启动
   ========================================================================== */

async function startApp() {
    if (appStarted || booting) {
        return;
    }

    booting = true;
    appStarted = true;
    historySeeded = false;
    const generation = ++appGeneration;

    try {
        const hash = (window.location.hash || '').replace('#', '');
        const configured = document.body && document.body.dataset ? document.body.dataset.view : '';
        const fallback = VIEWS.indexOf(configured) === -1 ? 'gallery' : configured;
        const initial = VIEWS.indexOf(hash) === -1 ? fallback : hash;

        showView(initial, { replace: true });

        /* 登录/重新登录后先恢复骨架，避免等待 bounds 时出现空白网格 */
        if (currentView === 'gallery') {
            showGallerySkeletons(6, false);
        }

        el.dpTrigger.disabled = false;
        el.slideshowButton.disabled = false;
        el.monitorStartButton.disabled = false;

        const bounds = await loadDateBounds();

        /* 等待期间可能已登出/重新登录：过期的一轮初始化必须直接放弃 */
        if (generation !== appGeneration || !authenticated) {
            return;
        }

        setDateBounds(bounds.earliest, bounds.latest);

        if (!bounds.latest) {
            el.gallery.textContent = '';
            el.gallery.className = 'grid';
            el.dpTrigger.disabled = true;
            el.slideshowButton.disabled = true;
            el.monitorStartButton.disabled = true;
            setStatus('照片库中还没有照片。请确认 captures_dir / GALLERY_CAPTURES_DIR 指向了正确的目录（Docker 请检查卷映射）。');
            window.history.replaceState(historyStateFor(currentView), '', '#' + currentView);
            historySeeded = true;
            return;
        }

        resetToDate(bounds.latest);
        requestSegThumb();

        window.history.replaceState(historyStateFor(currentView), '', '#' + currentView);
        historySeeded = true;
    } finally {
        booting = false;
    }
}

/* ==========================================================================
   初始化
   ========================================================================== */

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
        window.addEventListener('resize', requestSegThumb, { passive: true });

        if (typeof ResizeObserver !== 'undefined') {
            new ResizeObserver(requestSegThumb).observe(el.viewNav);
        }
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
    initAuth();

    if (authenticated) {
        await startApp();
    } else {
        const message = el.authError && !el.authError.hidden ? el.authError.textContent : '';
        showAuthOverlay(message);
    }
}

init().catch((error) => {
    if (el.gallery) {
        el.gallery.textContent = '';
        el.gallery.className = 'grid';
    }
    setStatus('页面初始化失败：' + (error && error.message ? error.message : '未知错误') + '，请刷新重试。', true);
});
