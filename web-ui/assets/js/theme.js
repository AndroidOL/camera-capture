const ONE_YEAR = 31536000;

const MODE_KEY = 'galleryTheme';
const MODE_COOKIE = 'gallery_theme';
const ACCENT_KEY = 'galleryAccent';
const ACCENT_COOKIE = 'gallery_accent';

const ACCENTS = ['blue', 'teal', 'violet', 'amber', 'rose', 'green'];
const MODES = ['dark', 'light'];

function readCookie(name) {
    const match = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : '';
}

function writeCookie(name, value) {
    try {
        const secure = window.location.protocol === 'https:' ? ';Secure' : '';
        document.cookie =
            name + '=' + encodeURIComponent(value) + ';path=/;max-age=' + ONE_YEAR + ';SameSite=Lax' + secure;
    } catch (error) {
        /* cookie unavailable */
    }
}

function readStorage(key) {
    try {
        return localStorage.getItem(key) || '';
    } catch (error) {
        return '';
    }
}

function writeStorage(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (error) {
        /* storage unavailable */
    }
}

export function getTheme() {
    return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

export function getAccent() {
    const value = document.documentElement.dataset.accent || '';
    return ACCENTS.indexOf(value) === -1 ? 'blue' : value;
}

function syncModeUi(mode) {
    const buttons = document.querySelectorAll('[data-mode-option]');
    for (let i = 0; i < buttons.length; i++) {
        const active = buttons[i].getAttribute('data-mode-option') === mode;
        buttons[i].classList.toggle('is-active', active);
        buttons[i].setAttribute('aria-pressed', active ? 'true' : 'false');
    }
}

function syncAccentUi(accent) {
    const buttons = document.querySelectorAll('[data-accent-option]');
    for (let i = 0; i < buttons.length; i++) {
        const active = buttons[i].getAttribute('data-accent-option') === accent;
        buttons[i].classList.toggle('is-active', active);
        buttons[i].setAttribute('aria-pressed', active ? 'true' : 'false');
    }
}

export function applyTheme(mode) {
    const value = mode === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.theme = value;

    /* 同步浏览器 UI（地址栏/状态栏）与"首帧配色"，避免刷新闪一下 */
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) {
        themeColor.setAttribute('content', value === 'light' ? '#f5f6f9' : '#07080b');
    }
    const scheme = document.querySelector('meta[name="color-scheme"]');
    if (scheme) {
        scheme.setAttribute('content', value);
    }

    syncModeUi(value);
    writeStorage(MODE_KEY, value);
    writeCookie(MODE_COOKIE, value);
    document.dispatchEvent(new CustomEvent('themechange', { detail: value }));
    return value;
}

export function applyAccent(accent) {
    const value = ACCENTS.indexOf(accent) === -1 ? 'blue' : accent;
    document.documentElement.dataset.accent = value;
    syncAccentUi(value);
    writeStorage(ACCENT_KEY, value);
    writeCookie(ACCENT_COOKIE, value);
    document.dispatchEvent(new CustomEvent('accentchange', { detail: value }));
    return value;
}

/**
 * cookie 是**唯一权威来源** —— 服务端也按它渲染，所以：
 *   1. 正常情况：cookie 与 <html> 上的值一致 → 这里什么都不改（绝不产生闪烁）。
 *   2. 异常情况：被扩展/内嵌预览等外部脚本改写了 <html> 的值 → 按 cookie 纠正回来，
 *      这样"刷新后丢失深色模式"不会发生。
 *
 * 关键：只把 **cookie 里的值** 写回 cookie/localStorage，**绝不把 DOM 上的值当权威**。
 * （曾经的写法是"把 <html> 上的值镜像进 cookie"，一旦加载早期被改写成 light，
 *   就会把用户选择的 dark 永久覆盖掉 —— 那才是刷新丢主题的真凶。）
 */
export function initTheme() {
    const cookieMode = readCookie(MODE_COOKIE);
    const cookieAccent = readCookie(ACCENT_COOKIE);

    const mode = MODES.indexOf(cookieMode) !== -1 ? cookieMode : getTheme();
    const accent = ACCENTS.indexOf(cookieAccent) !== -1 ? cookieAccent : getAccent();

    if (mode !== getTheme()) {
        applyTheme(mode);
    } else {
        writeStorage(MODE_KEY, mode);
        writeCookie(MODE_COOKIE, mode);
    }

    if (accent !== getAccent()) {
        applyAccent(accent);
    } else {
        writeStorage(ACCENT_KEY, accent);
        writeCookie(ACCENT_COOKIE, accent);
    }

    syncModeUi(mode);
    syncAccentUi(accent);
}

export function toggleTheme() {
    const next = getTheme() === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    return next;
}
