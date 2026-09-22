function byId(id) {
    return document.getElementById(id);
}

export const el = {
    viewNav: byId('viewNav'),
    segThumb: byId('segThumb'),
    viewGallery: byId('view-gallery'),
    viewOps: byId('view-ops'),
    themeLabel: byId('themeLabel'),
    appearanceTrigger: byId('appearanceTrigger'),
    appearancePop: byId('appearancePop'),

    datePicker: byId('datePicker'),
    dpTrigger: byId('dpTrigger'),
    dpValue: byId('dpValue'),
    dpPopover: byId('dpPopover'),
    dpPrev: byId('dpPrev'),
    dpNext: byId('dpNext'),
    dpTitle: byId('dpTitle'),
    dpWeekdays: byId('dpWeekdays'),
    dpGrid: byId('dpGrid'),
    dpLatest: byId('dpLatest'),
    dpClose: byId('dpClose'),

    backButton: byId('backButton'),
    slideshowButton: byId('slideshowButton'),
    monitorStartButton: byId('monitorStartButton'),
    monitorStopButton: byId('monitorStopButton'),
    breadcrumb: byId('breadcrumb'),
    levelStats: byId('levelStats'),
    activityBar: byId('activityBar'),
    status: byId('status'),
    loading: byId('loading'),

    gallery: byId('gallery'),
    monitor: byId('monitor'),
    monitorImage: byId('monitorImage'),
    monitorMaximize: byId('monitorMaximize'),
    monitorFilename: byId('monitorFilename'),
    monitorFilesize: byId('monitorFilesize'),
    monitorTime: byId('monitorTime'),

    viewer: byId('viewer'),
    viewerShell: byId('viewerShell'),
    viewerStage: byId('viewerStage'),
    viewerImage: byId('viewerImage'),
    viewerProgress: byId('viewerProgress'),
    viewerMaximize: byId('viewerMaximize'),
    viewerClose: byId('viewerClose'),
    viewerCounter: byId('viewerCounter'),
    viewerTitle: byId('viewerTitle'),
    viewerFilename: byId('viewerFilename'),
    viewerFilesize: byId('viewerFilesize'),
    viewerTime: byId('viewerTime'),
    viewerInterval: byId('viewerInterval'),
    viewerDownload: byId('viewerDownload'),
    viewerPrev: byId('viewerPrev'),
    viewerNext: byId('viewerNext'),
    viewerPlay: byId('viewerPlay'),
    viewerPlayLabel: byId('viewerPlayLabel'),
    viewerSpeed: byId('viewerSpeed'),
    viewerSpeedTrigger: byId('viewerSpeedTrigger'),
    viewerSpeedValue: byId('viewerSpeedValue'),
    viewerSpeedMenu: byId('viewerSpeedMenu'),
    viewerTimelineWrap: byId('viewerTimelineWrap'),
    viewerTimeline: byId('viewerTimeline'),
    viewerTimelineFrom: byId('viewerTimelineFrom'),
    viewerTimelineLabel: byId('viewerTimelineLabel'),
    viewerTimelineTo: byId('viewerTimelineTo'),

    opsPill: byId('opsPill'),
    opsUpdated: byId('opsUpdated'),
    opsRefresh: byId('opsRefresh'),
    opsStats: byId('opsStats'),
    opsWarnings: byId('opsWarnings'),
    opsService: byId('opsService'),
    opsStorageSecurity: byId('opsStorageSecurity'),
    opsChart: byId('opsChart'),
    opsChartPeak: byId('opsChartPeak'),
    opsChartTitle: byId('opsChartTitle'),
};

let loadingCount = 0;

export function setLoading(active) {
    loadingCount = Math.max(0, loadingCount + (active ? 1 : -1));
    if (el.loading) {
        el.loading.hidden = loadingCount === 0;
    }
}

export function setStatus(message, isError) {
    if (!el.status) {
        return;
    }
    if (!message) {
        el.status.hidden = true;
        el.status.textContent = '';
        el.status.classList.remove('is-error');
        return;
    }
    el.status.textContent = message;
    el.status.hidden = false;
    el.status.classList.toggle('is-error', !!isError);
}

export function create(tag, className, text) {
    const node = document.createElement(tag);
    if (className) {
        node.className = className;
    }
    if (text !== undefined && text !== null) {
        node.textContent = text;
    }
    return node;
}
