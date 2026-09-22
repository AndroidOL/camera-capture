import { setLoading } from './dom.js';

export class ApiError extends Error {
    constructor(message, status) {
        super(message);
        this.name = 'ApiError';
        this.status = status || 0;
    }
}

const CANCELLABLE = [
    'getDailySummary',
    'getHourlySummary',
    'getTenMinuteSummary',
    'getMinutePhotos',
    'getPhotoListForRange',
];

const inflight = new Map();

export async function apiGet(action, params, options) {
    const settings = options || {};
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

    const fetchOptions = {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        method: 'GET',
    };

    let controller = null;
    if (CANCELLABLE.indexOf(action) !== -1 && typeof AbortController !== 'undefined') {
        const previous = inflight.get(action);
        if (previous) {
            try {
                previous.abort();
            } catch (error) {
                /* already settled */
            }
        }
        controller = new AbortController();
        inflight.set(action, controller);
        fetchOptions.signal = controller.signal;
    }

    if (!settings.silent) {
        setLoading(true);
    }

    try {
        const response = await fetch('api.php?' + query.toString(), fetchOptions);
        let payload = null;
        try {
            payload = await response.json();
        } catch (error) {
            payload = null;
        }

        if (response.status === 401) {
            window.location.href = 'login.php?error=session_timeout';
            throw new ApiError('会话已超时，请重新登录。', 401);
        }
        if (!response.ok) {
            const message = payload && payload.error ? payload.error : '请求失败（HTTP ' + response.status + '）';
            throw new ApiError(message, response.status);
        }
        if (payload && payload.error) {
            throw new ApiError(payload.error, response.status);
        }
        return payload;
    } catch (error) {
        if (error && error.name === 'AbortError') {
            return null;
        }
        if (error instanceof ApiError) {
            throw error;
        }
        throw new ApiError('网络请求失败，请检查网络连接。', 0);
    } finally {
        if (!settings.silent) {
            setLoading(false);
        }
        if (controller && inflight.get(action) === controller) {
            inflight.delete(action);
        }
    }
}
