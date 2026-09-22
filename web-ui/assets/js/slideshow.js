import { apiGet } from './api.js';
import { setStatus } from './dom.js';
import { openViewer } from './viewer.js';

export async function startSlideshow(nav) {
    if (!nav || !nav.date) {
        setStatus('请先选择一个日期以开始照片轮播。', true);
        return;
    }

    const params = { date: nav.date };
    if (nav.level >= 2 && nav.hour) {
        params.hour = nav.hour;
    }
    if (nav.level >= 3 && nav.slot !== '' && nav.slot !== null && nav.slot !== undefined) {
        params.interval_slot = nav.slot;
    }
    if (nav.level >= 4 && nav.minute) {
        params.minute = nav.minute;
    }

    setStatus('正在加载轮播照片…');

    let data;
    try {
        data = await apiGet('getPhotoListForRange', params);
    } catch (error) {
        setStatus(error.message, true);
        return;
    }
    if (!data) {
        return;
    }

    const photos = data.photos || [];
    if (!photos.length) {
        setStatus('此范围内没有可轮播的照片。', true);
        return;
    }

    setStatus('照片轮播中，共 ' + photos.length + ' 张。');
    openViewer({ items: photos, index: 0, title: '照片轮播 · ' + photos.length + ' 张', autoplay: true });
}
