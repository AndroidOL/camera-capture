import { apiGet, isCancelled } from './api.js';
import { create, el } from './dom.js';
import { animateWidth, countUp } from './anim.js';
import { formatFileSize } from './util.js';

const REQUEST_TIMEOUT = 15000;
const AUTO_RETRY_DELAY = 2500;

let loaded = false;
let loading = false;
let sequence = 0;
let lastData = null;
let retryTimer = null;

export function initAdmin() {
    if (el.opsRefresh) {
        el.opsRefresh.addEventListener('click', () => {
            loadAdmin(true);
        });
    }

    document.addEventListener('click', (event) => {
        const retry = event.target && event.target.closest ? event.target.closest('[data-ops-retry]') : null;
        if (retry) {
            loadAdmin(true);
        }
    });

    window.addEventListener('online', () => {
        if (!loaded && !loading) {
            loadAdmin(false);
        }
    });
}

export function ensureAdminLoaded() {
    if (!loaded && !loading) {
        loadAdmin(false);
    }
}

export function reloadAdmin() {
    loaded = false;
    lastData = null;
    loadAdmin(false);
}

/**
 * 登出时清空运维数据与模块状态，避免旧会话信息残留在 DOM 中。
 * 递增 sequence 可让仍在途的请求结果被直接丢弃。
 */
export function resetAdminState() {
    sequence++;
    loaded = false;
    loading = false;
    lastData = null;

    if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
        retryTimer = null;
    }

    if (el.opsStats) {
        el.opsStats.textContent = '';
        el.opsStats.setAttribute('aria-busy', 'false');
    }
    if (el.opsWarnings) {
        el.opsWarnings.textContent = '';
        el.opsWarnings.hidden = true;
    }
    if (el.opsService) {
        el.opsService.textContent = '';
    }
    if (el.opsStorageSecurity) {
        el.opsStorageSecurity.textContent = '';
    }
    if (el.opsChart) {
        el.opsChart.textContent = '';
    }
    if (el.opsChartPeak) {
        el.opsChartPeak.textContent = '';
    }
    if (el.opsUpdated) {
        el.opsUpdated.textContent = '';
        el.opsUpdated.title = '';
    }
    if (el.opsPill) {
        el.opsPill.className = 'pill pill-mute';
        el.opsPill.textContent = '读取中';
    }
    if (el.opsRefresh) {
        el.opsRefresh.disabled = false;
        el.opsRefresh.classList.remove('is-busy');
    }
}

async function loadAdmin(refresh) {
    if (loading) {
        return;
    }

    loading = true;
    const token = ++sequence;
    const firstLoad = !lastData;

    if (firstLoad) {
        showSkeletons();
    }
    setBusy(true, firstLoad ? '读取中' : '更新中');

    if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
        retryTimer = null;
    }

    try {
        const data = await apiGet(
            'getOpsOverview',
            refresh ? { refresh: 1 } : {},
            {
                silent: true,
                timeout: REQUEST_TIMEOUT,
                dedupe: true,
                retries: 0,
            }
        );

        if (!data || token !== sequence) {
            return;
        }

        lastData = data;
        loaded = true;
        renderAll(data);
    } catch (error) {
        if (token !== sequence || isCancelled(error)) {
            return;
        }

        if (lastData) {
            showInlineError(error.message);
            renderPill(lastData.service, lastData.storage);
        } else {
            renderFailure(error.message);
        }

        /* 首次进入就失败时自动再试一次，避免瞬时网络抖动让面板一直空着 */
        if (firstLoad) {
            retryTimer = window.setTimeout(() => {
                retryTimer = null;
                if (!loaded && !loading) {
                    loadAdmin(false);
                }
            }, AUTO_RETRY_DELAY);
        }
    } finally {
        if (token === sequence) {
            loading = false;
            setBusy(false);
        }
    }
}

function setBusy(active, label) {
    if (el.opsRefresh) {
        el.opsRefresh.disabled = active;
        el.opsRefresh.classList.toggle('is-busy', active);
    }
    if (el.opsStats) {
        el.opsStats.setAttribute('aria-busy', active ? 'true' : 'false');
    }
    if (active && label && el.opsPill) {
        el.opsPill.className = 'pill pill-mute';
        el.opsPill.textContent = label;
    }
}

function renderAll(data) {
    const service = data.service || {};
    const storage = data.storage || {};
    const security = data.security || {};
    const library = data.library || {};

    renderPill(service, storage);
    renderStats(library, storage);
    renderService(service);
    renderStorageSecurity(storage, security);
    renderWarnings(data.warnings);
    renderChart(library.recent_days, library.window_days);

    if (el.opsUpdated) {
        const seconds = data.generated_at || library.computed_at;
        const at = seconds
            ? new Date(seconds * 1000).toLocaleTimeString('zh-CN', { hour12: false })
            : '';
        let text = at ? '统计于 ' + at : '';
        if (data.from_cache) {
            text += text ? ' · 缓存' : '缓存数据';
        }
        el.opsUpdated.textContent = text;
        el.opsUpdated.title = data.degraded ? '部分数据不可用，已降级展示' : '';
    }
}

function showSkeletons() {
    if (el.opsStats) {
        el.opsStats.textContent = '';
        for (let i = 0; i < 4; i++) {
            el.opsStats.appendChild(create('div', 'skeleton stat-skeleton'));
        }
    }
    if (el.opsService) {
        el.opsService.textContent = '';
        el.opsService.appendChild(create('div', 'skeleton panel-skeleton'));
    }
    if (el.opsStorageSecurity) {
        el.opsStorageSecurity.textContent = '';
        el.opsStorageSecurity.appendChild(create('div', 'skeleton panel-skeleton'));
    }
    if (el.opsChart) {
        el.opsChart.textContent = '';
        el.opsChart.appendChild(create('div', 'skeleton panel-skeleton'));
    }
    if (el.opsWarnings) {
        el.opsWarnings.hidden = true;
        el.opsWarnings.textContent = '';
    }
    if (el.opsPill) {
        el.opsPill.className = 'pill pill-mute';
        el.opsPill.textContent = '读取中';
    }
}

function renderFailure(message) {
    if (!el.opsStats) {
        return;
    }
    el.opsStats.textContent = '';

    const card = create('div', 'card panel ops-error');
    card.appendChild(create('p', 'ops-error-title', '加载运维数据失败'));
    card.appendChild(create('p', 'empty-note', message || '请稍后重试。'));

    const retry = create('button', 'btn btn-accent', '重新加载');
    retry.type = 'button';
    retry.dataset.opsRetry = '1';
    card.appendChild(retry);

    el.opsStats.appendChild(card);

    if (el.opsService) {
        el.opsService.textContent = '';
    }
    if (el.opsStorageSecurity) {
        el.opsStorageSecurity.textContent = '';
    }
    if (el.opsChart) {
        el.opsChart.textContent = '';
    }

    if (el.opsPill) {
        el.opsPill.className = 'pill pill-danger';
        el.opsPill.textContent = '读取失败';
    }
    if (el.opsUpdated) {
        el.opsUpdated.textContent = '';
    }
}

function showInlineError(message) {
    if (!el.opsWarnings) {
        return;
    }
    el.opsWarnings.textContent = '';

    const row = create('div', 'warn-row warn-row-error');
    row.appendChild(create('span', 'warn-dot'));
    row.appendChild(create('span', 'warn-text', '刷新失败：' + (message || '未知错误') + '（当前展示上一次成功结果）'));

    const retry = create('button', 'btn btn-ghost btn-sm', '重试');
    retry.type = 'button';
    retry.dataset.opsRetry = '1';
    row.appendChild(retry);

    el.opsWarnings.appendChild(row);
    el.opsWarnings.hidden = false;
}

function buildStat(label, unit, hint, index) {
    const card = create('div', 'card stat-card');
    card.style.setProperty('--i', String(index));
    card.appendChild(create('span', 'stat-label', label));

    const value = create('span', 'stat-value');
    const number = create('span');
    value.appendChild(number);
    if (unit) {
        value.appendChild(create('span', 'stat-unit', unit));
    }
    card.appendChild(value);

    if (hint) {
        card.appendChild(create('span', 'stat-hint', hint));
    }

    return { card: card, number: number };
}

function renderStats(library, storage) {
    if (!el.opsStats) {
        return;
    }
    el.opsStats.textContent = '';

    const totalFiles = buildStat(
        '照片总数',
        '张',
        (library.months || 0) + ' 个月 · ' + (library.dates || 0) + ' 天有照片',
        0
    );
    el.opsStats.appendChild(totalFiles.card);
    countUp(totalFiles.number, library.total_files || 0, {});

    const span = library.earliest && library.latest ? library.earliest + ' → ' + library.latest : '—';
    const totalSize = buildStat('库总体积', null, span, 1);
    el.opsStats.appendChild(totalSize.card);
    countUp(totalSize.number, library.total_bytes || 0, {
        format: (value) => formatFileSize(value),
    });

    const dateStat = buildStat('覆盖天数', '天', (library.months || 0) + ' 个月份目录', 2);
    el.opsStats.appendChild(dateStat.card);
    countUp(dateStat.number, library.dates || 0, {});

    const diskStat = buildStat('磁盘使用率', '%', (storage.warn_percent || 85) + '% 触发清理告警', 3);
    el.opsStats.appendChild(diskStat.card);
    if (storage.used_percent === null || storage.used_percent === undefined) {
        diskStat.number.textContent = '—';
    } else {
        countUp(diskStat.number, storage.used_percent, { decimals: 1 });
    }
}

function kvRow(key, value, valueClass) {
    const row = create('div', 'kv-row');
    row.appendChild(create('span', 'kv-key', key));
    const val = create(
        'span',
        'kv-val',
        value === null || value === undefined || value === '' ? '—' : String(value)
    );
    if (valueClass) {
        val.classList.add(valueClass);
    }
    row.appendChild(val);
    return row;
}

function renderService(service) {
    if (!el.opsService) {
        return;
    }
    el.opsService.textContent = '';

    if (!service.available) {
        el.opsService.appendChild(
            create('p', 'empty-note', '未找到采集服务的健康文件：' + (service.health_file || '—'))
        );
        el.opsService.appendChild(kvRow('健康文件', service.health_file));
        return;
    }

    const stateText = service.state === 'running' ? '运行中' : service.state === 'stale' ? '心跳已过期' : '未知';
    el.opsService.appendChild(kvRow('状态', stateText));
    if (service.age_seconds !== null && service.age_seconds !== undefined) {
        el.opsService.appendChild(kvRow('最近心跳', service.age_seconds + ' 秒前'));
    }
    if (service.interval !== null && service.interval !== undefined) {
        el.opsService.appendChild(kvRow('抓拍间隔', service.interval + ' 秒'));
    }
    if (service.fourcc) {
        el.opsService.appendChild(kvRow('FOURCC', service.fourcc));
    }
    if (service.read_failures !== null && service.read_failures !== undefined) {
        el.opsService.appendChild(kvRow('连续读帧失败', service.read_failures));
    }
    if (service.imwrite_failures !== null && service.imwrite_failures !== undefined) {
        el.opsService.appendChild(kvRow('连续写盘失败', service.imwrite_failures));
    }
    if (service.disk_cleanup_batches !== null && service.disk_cleanup_batches !== undefined) {
        el.opsService.appendChild(kvRow('磁盘清理批次', service.disk_cleanup_batches));
    }
    if (service.last_saved) {
        el.opsService.appendChild(kvRow('最近保存', service.last_saved));
    }
    if (service.last_saved_at) {
        el.opsService.appendChild(kvRow('拍摄时间', service.last_saved_at));
    }
    if (service.boot_id) {
        el.opsService.appendChild(kvRow('运行实例', service.boot_id));
    }
    el.opsService.appendChild(kvRow('健康文件', service.health_file));
}

function renderStorageSecurity(storage, security) {
    const wrap = el.opsStorageSecurity;
    if (!wrap) {
        return;
    }
    wrap.textContent = '';

    const stack = create('div', 'panel-stack');

    if (storage.used_percent === null || storage.used_percent === undefined) {
        stack.appendChild(create('p', 'empty-note', '无法读取磁盘占用信息。'));
    } else {
        const meter = create('div', 'meter');

        const track = create('div', 'meter-track');
        const fill = create('div', 'meter-fill');
        if (storage.status === 'warning') {
            fill.classList.add('is-warn');
        }
        track.appendChild(fill);
        meter.appendChild(track);

        const legend = create('div', 'meter-legend');
        legend.appendChild(
            create(
                'span',
                null,
                '已用 ' +
                    formatFileSize(storage.used_bytes) +
                    ' / ' +
                    formatFileSize(storage.total_bytes)
            )
        );
        legend.appendChild(create('span', null, storage.used_percent + '%'));
        meter.appendChild(legend);

        stack.appendChild(meter);
        animateWidth(fill, storage.used_percent);
    }

    /* ---- 存储 ---- */
    stack.appendChild(create('p', 'panel-subtitle', '存储'));

    const storageKv = create('div', 'kv');

    /* 目录不存在/不可读时直接在行上标出来，Docker 场景一眼能看出卷没挂上 */
    let dirSuffix = '';
    let dirClass = '';
    if (storage.path_exists === false) {
        dirSuffix = ' · 不存在';
        dirClass = 'is-warn';
    } else if (storage.path_readable === false) {
        dirSuffix = ' · 不可读';
        dirClass = 'is-warn';
    }
    storageKv.appendChild(kvRow('照片库', (storage.path || '—') + dirSuffix, dirClass));
    storageKv.appendChild(
        kvRow(
            '可用空间',
            storage.free_bytes === null || storage.free_bytes === undefined
                ? '—'
                : formatFileSize(storage.free_bytes)
        )
    );
    storageKv.appendChild(kvRow('告警阈值', (storage.warn_percent || 85) + '%'));
    stack.appendChild(storageKv);

    /* ---- 安全 ---- */
    stack.appendChild(create('p', 'panel-subtitle', '安全'));

    const securityKv = create('div', 'kv');

    let passwordLabel = '未设置';
    if (security.password_mode === 'hash') {
        passwordLabel = 'bcrypt 哈希';
    } else if (security.password_mode === 'plaintext') {
        passwordLabel = '明文（已停用，请改用哈希）';
    }
    securityKv.appendChild(kvRow('密码', passwordLabel));
    securityKv.appendChild(kvRow('HTTPS', security.https ? '已启用' : '未启用'));
    securityKv.appendChild(
        kvRow(
            '会话 Cookie',
            security.cookie_secure ? 'Secure · HttpOnly · SameSite' : 'HttpOnly · SameSite'
        )
    );
    securityKv.appendChild(kvRow('Cookie 前缀', security.cookie_prefix || '—'));
    securityKv.appendChild(kvRow('图片通道', security.image_mode === 'proxy' ? '鉴权代理' : '直链'));
    securityKv.appendChild(kvRow('代理信任', security.trust_proxy ? '已开启 trust_proxy' : '关闭'));
    securityKv.appendChild(kvRow('robots.txt', security.robots_blocked ? '已禁止抓取' : '缺失'));
    stack.appendChild(securityKv);

    wrap.appendChild(stack);
}

function renderWarnings(warnings) {
    if (!el.opsWarnings) {
        return;
    }
    el.opsWarnings.textContent = '';

    const list = Array.isArray(warnings) ? warnings : [];
    if (!list.length) {
        el.opsWarnings.hidden = true;
        return;
    }

    list.forEach((text) => {
        const row = create('div', 'warn-row');
        row.appendChild(create('span', 'warn-dot'));
        row.appendChild(create('span', 'warn-text', text));
        el.opsWarnings.appendChild(row);
    });
    el.opsWarnings.hidden = false;
}

function renderChart(recentDays, windowDays) {
    if (!el.opsChart) {
        return;
    }
    el.opsChart.textContent = '';

    if (el.opsChartTitle) {
        const days = windowDays || (recentDays ? recentDays.length : 0);
        el.opsChartTitle.textContent = '近 ' + days + ' 天每日张数';
    }

    if (!recentDays || !recentDays.length) {
        el.opsChart.appendChild(create('p', 'empty-note', '暂无每日统计数据。'));
        if (el.opsChartPeak) {
            el.opsChartPeak.textContent = '';
        }
        return;
    }

    let max = 0;
    let totalFiles = 0;
    let peakDate = '';
    for (let i = 0; i < recentDays.length; i++) {
        const files = recentDays[i].files;
        totalFiles += files;
        if (files > max) {
            max = files;
            peakDate = recentDays[i].date;
        }
    }

    if (el.opsChartPeak) {
        el.opsChartPeak.textContent =
            max > 0
                ? '共 ' + totalFiles + ' 张 · 峰值 ' + max + ' 张（' + peakDate.slice(5) + '）'
                : '该区间无照片';
    }

    const grid = create('div', 'chart-days');
    recentDays.forEach((day) => {
        const row = create('div', 'drow' + (day.files > 0 ? '' : ' is-empty'));
        row.title = day.date + '：' + day.files + ' 张 · ' + formatFileSize(day.bytes);

        row.appendChild(create('span', 'drow-date', day.date.slice(5).replace('-', '/')));

        const track = create('span', 'drow-track');
        const bar = create('span', 'drow-bar');
        track.appendChild(bar);
        row.appendChild(track);

        row.appendChild(create('span', 'drow-count', String(day.files)));
        grid.appendChild(row);

        const percent = max > 0 ? (day.files / max) * 100 : 0;
        animateWidth(bar, day.files > 0 ? Math.max(4, percent) : 0);
    });
    el.opsChart.appendChild(grid);
}

function renderPill(service, storage) {
    if (!el.opsPill) {
        return;
    }
    service = service || {};
    storage = storage || {};
    el.opsPill.className = 'pill';

    if (storage.status === 'warning') {
        el.opsPill.classList.add('pill-warn');
        el.opsPill.textContent = '磁盘告警';
        return;
    }

    if (!service.available) {
        el.opsPill.classList.add('pill-mute');
        el.opsPill.textContent = '未接入采集服务';
        return;
    }

    if (service.state === 'running') {
        el.opsPill.classList.add('pill-ok', 'pill-live');
        el.opsPill.textContent = '采集运行中';
        return;
    }

    if (service.state === 'stale') {
        el.opsPill.classList.add('pill-warn');
        el.opsPill.textContent = '心跳过期';
        return;
    }

    el.opsPill.classList.add('pill-mute');
    el.opsPill.textContent = '状态未知';
}
