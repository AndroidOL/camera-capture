import { setLoading } from './dom.js';

export class ApiError extends Error {
    constructor(message, status, code) {
        super(message);
        this.name = 'ApiError';
        this.status = status || 0;
        this.code = code || '';
    }
}

/* 同一 action 的新请求会取消旧请求（层级切换时避免旧响应覆盖新内容） */
const CANCELLABLE = [
    'getDailySummary',
    'getHourlySummary',
    'getTenMinuteSummary',
    'getMinutePhotos',
    'getPhotoListForRange',
];

const DEFAULT_TIMEOUT = 12000;
const RETRY_DELAY = 320;

const inflight = new Map();
const deduped = new Map();

function isAbortError(error) {
    return !!error && error.name === 'AbortError';
}

function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isRetryable(error) {
    if (!error || error.aborted || error.superseded) {
        return false;
    }
    return error.status === 0 || error.status === 408 || error.status >= 500;
}

function buildUrl(action, params) {
    const query = new URLSearchParams();
    query.set('action', action);

    if (params) {
        Object.keys(params).forEach((key) => {
            const value = params[key];
            if (value !== undefined && value !== null && value !== '') {
                query.set(key, String(value));
            }
        });
    }
    return query.toString();
}

/**
 * GET 封装。
 *
 * options:
 *   silent   —— 不显示全局加载条
 *   timeout  —— 毫秒；默认 12s，0 表示不限制
 *   retries  —— 网络错误/超时/5xx 的重试次数（默认 0）
 *   dedupe   —— 相同查询在飞行中时复用同一个 Promise
 *   signal   —— 外部 AbortSignal（如监控停止时取消在途请求）
 */
export async function apiGet(action, params, options) {
    const settings = options || {};
    const key = buildUrl(action, params);

    if (settings.dedupe && deduped.has(key)) {
        return deduped.get(key);
    }

    const promise = run(action, key, settings);

    if (settings.dedupe) {
        deduped.set(key, promise);
        const cleanup = () => {
            if (deduped.get(key) === promise) {
                deduped.delete(key);
            }
        };
        promise.then(cleanup, cleanup);
    }

    return promise;
}

async function run(action, key, settings) {
    const retries = Math.max(0, Number(settings.retries) || 0);
    const showLoading = !settings.silent;

    if (showLoading) {
        setLoading(true);
    }

    try {
        let lastError = null;

        for (let attempt = 0; attempt <= retries; attempt++) {
            if (attempt > 0) {
                await delay(RETRY_DELAY * attempt);
            }
            try {
                return await attemptOnce(action, key, settings);
            } catch (error) {
                lastError = error;
                if (error && (error.superseded || error.aborted)) {
                    return null;
                }
                if (!isRetryable(error) || attempt >= retries) {
                    throw error;
                }
            }
        }

        throw lastError || new ApiError('请求失败，请稍后重试。', 0, 'unknown');
    } finally {
        if (showLoading) {
            setLoading(false);
        }
    }
}

async function attemptOnce(action, key, settings) {
    const timeout = settings.timeout === undefined ? DEFAULT_TIMEOUT : Number(settings.timeout);
    const canCancel = CANCELLABLE.indexOf(action) !== -1;
    const hasAbort = typeof AbortController !== 'undefined';

    let controller = null;
    let record = null;
    let timer = null;
    let timedOut = false;
    let externallyAborted = false;

    if (hasAbort && (canCancel || timeout > 0 || settings.signal)) {
        controller = new AbortController();
    }

    if (canCancel && controller) {
        const previous = inflight.get(action);
        if (previous) {
            previous.superseded = true;
            try {
                previous.controller.abort();
            } catch (error) {
                /* already settled */
            }
        }
        record = { controller: controller, superseded: false };
        inflight.set(action, record);
    }

    if (controller && settings.signal) {
        if (settings.signal.aborted) {
            externallyAborted = true;
            controller.abort();
        } else {
            settings.signal.addEventListener(
                'abort',
                () => {
                    externallyAborted = true;
                    try {
                        controller.abort();
                    } catch (error) {
                        /* ignore */
                    }
                },
                { once: true }
            );
        }
    }

    if (controller && timeout > 0) {
        timer = window.setTimeout(() => {
            timedOut = true;
            try {
                controller.abort();
            } catch (error) {
                /* ignore */
            }
        }, timeout);
    }

    const fetchOptions = {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        method: 'GET',
    };
    if (controller) {
        fetchOptions.signal = controller.signal;
    }

    try {
        const response = await fetch('api.php?' + key, fetchOptions);

        let payload = null;
        try {
            payload = await response.json();
        } catch (error) {
            payload = null;
        }

        if (response.status === 401) {
            /* 优先交给页面内处理器切换到登录浮层（无刷新）。
               若页面没有处理器，1.2 秒后回退到壳层加载。 */
            document.dispatchEvent(
                new CustomEvent('gallery:unauthorized', {
                    detail: { message: '会话已超时，请重新登录。' },
                })
            );
            window.setTimeout(() => {
                if (document.body.dataset.authenticated !== '0') {
                    window.location.replace('index.php?error=session_timeout');
                }
            }, 1200);

            throw new ApiError('会话已超时，请重新登录。', 401, 'unauthorized');
        }
        if (!response.ok) {
            const message = payload && payload.error ? payload.error : '请求失败（HTTP ' + response.status + '）';
            throw new ApiError(message, response.status, 'http');
        }
        if (payload && payload.error) {
            throw new ApiError(payload.error, response.status, 'payload');
        }
        return payload;
    } catch (error) {
        if (isAbortError(error)) {
            if (record && record.superseded) {
                const cancelled = new ApiError('请求已取消。', 0, 'superseded');
                cancelled.superseded = true;
                throw cancelled;
            }
            if (timedOut) {
                throw new ApiError('请求超时（' + Math.round(timeout / 1000) + ' 秒），请稍后重试。', 408, 'timeout');
            }
            if (externallyAborted) {
                const cancelled = new ApiError('请求已取消。', 0, 'aborted');
                cancelled.aborted = true;
                throw cancelled;
            }
            const cancelled = new ApiError('请求已取消。', 0, 'aborted');
            cancelled.aborted = true;
            throw cancelled;
        }
        if (error instanceof ApiError) {
            throw error;
        }
        throw new ApiError('网络请求失败，请检查网络连接。', 0, 'network');
    } finally {
        if (timer !== null) {
            window.clearTimeout(timer);
        }
        if (record && inflight.get(action) === record) {
            inflight.delete(action);
        }
    }
}

export function isCancelled(error) {
    return !!error && (error.aborted === true || error.superseded === true);
}
