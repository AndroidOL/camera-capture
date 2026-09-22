export function formatFileSize(bytes) {
    if (bytes === null || bytes === undefined || bytes === '' || isNaN(bytes)) {
        return 'N/A';
    }
    const size = Number(bytes);
    if (size <= 0) {
        return 'N/A';
    }
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = size;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
        value /= 1024;
        index += 1;
    }
    return value.toFixed(index === 0 ? 0 : 2) + ' ' + units[index];
}

export function pad2(value) {
    const text = String(value);
    return text.length >= 2 ? text : '0' + text;
}

export function parseFilenameTime(filename) {
    const match = /^capture_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/.exec(filename || '');
    if (!match) {
        return null;
    }
    return {
        year: match[1],
        month: match[2],
        day: match[3],
        hour: match[4],
        minute: match[5],
        second: match[6],
        clock: match[4] + ':' + match[5] + ':' + match[6],
        display: match[1] + '-' + match[2] + '-' + match[3] + ' ' + match[4] + ':' + match[5] + ':' + match[6],
    };
}

export function timeLabel(photo) {
    if (photo && photo.time) {
        return photo.time;
    }
    const parsed = parseFilenameTime(photo ? photo.filename : '');
    return parsed ? parsed.display : 'N/A';
}

export function timeShort(photo) {
    const parsed = parseFilenameTime(photo ? photo.filename : '');
    return parsed ? parsed.clock : 'N/A';
}

export function sequenceOf(photo) {
    const match = /^capture_\d{8}_\d{6}_(\d+)/.exec(photo ? photo.filename : '');
    return match ? match[1] : '';
}

export function epochOf(photo) {
    if (photo && typeof photo.epoch === 'number' && photo.epoch > 0) {
        return photo.epoch;
    }
    const parsed = parseFilenameTime(photo ? photo.filename : '');
    if (!parsed) {
        return null;
    }
    const date = new Date(
        Number(parsed.year),
        Number(parsed.month) - 1,
        Number(parsed.day),
        Number(parsed.hour),
        Number(parsed.minute),
        Number(parsed.second)
    );
    return Math.floor(date.getTime() / 1000);
}

const PLACEHOLDER =
    'data:image/svg+xml,' +
    encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="120">' +
            '<rect width="100%" height="100%" fill="#e5e7eb"/>' +
            '<text x="50%" y="50%" fill="#6b7280" font-family="sans-serif" font-size="14" ' +
            'text-anchor="middle" dominant-baseline="middle">加载失败</text></svg>'
    );

export function bindImageFallback(image) {
    if (!image) {
        return;
    }
    image.addEventListener('error', function handler() {
        if (image.src !== PLACEHOLDER) {
            image.src = PLACEHOLDER;
        }
    });
}

export function formatDuration(seconds) {
    if (seconds === null || seconds === undefined || isNaN(seconds)) {
        return 'N/A';
    }
    const total = Math.max(0, Math.round(Number(seconds)));
    if (total < 60) {
        return total + ' 秒';
    }
    const minutes = Math.floor(total / 60);
    if (minutes < 60) {
        return minutes + ' 分 ' + (total % 60) + ' 秒';
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
        return hours + ' 时 ' + (minutes % 60) + ' 分';
    }
    return Math.floor(hours / 24) + ' 天 ' + (hours % 24) + ' 时';
}

export function bindImageFade(image) {
    if (!image) {
        return;
    }
    const mark = () => image.classList.add('is-loaded');
    image.addEventListener('load', mark);
    if (image.complete && image.naturalWidth > 0) {
        mark();
    }
}

export function setImageSrc(image, src) {
    if (!image) {
        return;
    }
    image.classList.remove('is-loaded');
    image.src = src;
    if (image.complete && image.naturalWidth > 0) {
        requestAnimationFrame(() => image.classList.add('is-loaded'));
    }
}

const preloadCache = new Map();

export function preloadImage(url) {
    if (!url) {
        return Promise.resolve(url);
    }
    if (preloadCache.has(url)) {
        return preloadCache.get(url);
    }
    const promise = new Promise((resolve) => {
        const image = new Image();
        image.onload = () => resolve(url);
        image.onerror = () => resolve(url);
        image.src = url;
    });
    preloadCache.set(url, promise);
    return promise;
}

export function preloadAround(items, index) {
    const targets = [index - 1, index + 1];
    targets.forEach((position) => {
        if (position >= 0 && position < items.length) {
            preloadImage(items[position].image_url);
        }
    });
}

export function clearPreloadCache() {
    preloadCache.clear();
}
