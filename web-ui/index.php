<?php
use Gallery\Config;
use Gallery\Security\Auth;
use Gallery\Security\Csrf;
use Gallery\Security\Headers;
use Gallery\Support\Asset;
use Gallery\Support\Theme;

require __DIR__ . '/src/bootstrap.php';

Headers::apply('page');

/* 未登录不再整页跳转：渲染同一套壳层 + 登录浮层，登录/登出全部走 AJAX。
   页面本身不含任何照片数据；api.php / image.php 仍然独立鉴权。 */
$authenticated = Auth::isAuthenticated();

/* 会话可能因空闲/绝对超时被 Auth::isAuthenticated() 销毁；
   此时重新建立会话，保证登录浮层拿到的 CSRF token 是有效且可持久化的。 */
if (!$authenticated && session_status() !== PHP_SESSION_ACTIVE) {
    Auth::startSession();
}

$csrfToken = Csrf::token();

$authMessage = '';
if (!$authenticated) {
    if (isset($_GET['error'])) {
        if ($_GET['error'] === 'session_timeout') {
            $authMessage = '会话已超时，请重新登录。';
        } elseif ($_GET['error'] === 'unauthorized') {
            $authMessage = '您需要登录才能访问。';
        }
    }
    if ($authMessage === '' && isset($_GET['logged_out'])) {
        $authMessage = '已退出登录。';
    }
    if ($authMessage === '' && !Config::hasPassword()) {
        $authMessage = '尚未配置访问密码，请先设置 GALLERY_PASSWORD_HASH 或 config.php 的 password_hash。';
    }
}

$theme = Theme::mode();
$accent = Theme::accent();
$accents = Theme::accents();
$themeLabel = $theme === 'light' ? '浅色' : '深色';

$initialView = Config::get('default_view') === 'ops' ? 'ops' : 'gallery';
$slideshowSpeed = Config::getInt('slideshow_speed', 1);
$downloadEnabled = Config::getBool('download_enabled', true);
$monitorInitial = Config::getInt('monitor_initial_interval', 1500);
$monitorMin = Config::getInt('monitor_min_interval', 1000);
$monitorMax = Config::getInt('monitor_max_interval', 8000);
?>
<!DOCTYPE html>
<html lang="zh-CN" data-theme="<?= $theme ?>" data-accent="<?= htmlspecialchars($accent, ENT_QUOTES, 'UTF-8') ?>">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <meta name="robots" content="noindex, nofollow">
    <meta name="color-scheme" content="<?= $theme === 'light' ? 'light' : 'dark' ?>">
    <meta name="csrf-token" content="<?= htmlspecialchars($csrfToken, ENT_QUOTES, 'UTF-8') ?>">
    <meta name="theme-color" content="<?= $theme === 'light' ? '#f6f7f9' : '#0a0b0f' ?>">
    <title>照片查看器</title>
    <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect width='24' height='24' rx='6' fill='%236a9dff'/%3E%3Cpath d='M9 6l-1 1.5H6A1.5 1.5 0 0 0 4.5 9v6A1.5 1.5 0 0 0 6 16.5h12a1.5 1.5 0 0 0 1.5-1.5V9A1.5 1.5 0 0 0 18 7.5h-2L15 6H9Zm3 8.5a2.75 2.75 0 1 1 0-5.5 2.75 2.75 0 0 1 0 5.5Z' fill='%2305070c'/%3E%3C/svg%3E">
    <link rel="modulepreload" href="<?= Asset::url('assets/js/app.js') ?>">
    <link rel="stylesheet" href="<?= Asset::url('assets/css/base.css') ?>">
    <link rel="stylesheet" href="<?= Asset::url('assets/css/app.css') ?>">
    <link rel="stylesheet" href="<?= Asset::url('assets/css/admin.css') ?>">
</head>
<body
    data-authenticated="<?= $authenticated ? '1' : '0' ?>"
    data-view="<?= htmlspecialchars($initialView, ENT_QUOTES, 'UTF-8') ?>"
    data-speed="<?= (int) $slideshowSpeed ?>"
    data-download="<?= $downloadEnabled ? '1' : '0' ?>"
    data-monitor-initial="<?= (int) $monitorInitial ?>"
    data-monitor-min="<?= (int) $monitorMin ?>"
    data-monitor-max="<?= (int) $monitorMax ?>">
    <div class="app" id="appRoot" aria-hidden="<?= $authenticated ? 'false' : 'true' ?>"<?= $authenticated ? '' : ' inert' ?>>
        <header class="topbar">
            <div class="brand">
                <span class="brand-mark" aria-hidden="true">
                    <svg viewBox="0 0 24 24"><path d="M9 2 7.2 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3.2L15 2H9Zm3 15a5 5 0 1 1 0-10 5 5 0 0 1 0 10Z"/></svg>
                </span>
                <span class="brand-name">照片查看器</span>
            </div>

            <div class="seg" id="viewNav" role="tablist" aria-label="视图切换">
                <span class="seg-thumb" id="segThumb" aria-hidden="true"></span>
                <button type="button" class="seg-btn" role="tab" data-view="gallery" aria-selected="true">相册</button>
                <button type="button" class="seg-btn" role="tab" data-view="ops" aria-selected="false">运维</button>
            </div>

            <span class="spacer"></span>

            <div class="topbar-actions">
                <div class="appearance">
                    <button type="button" id="appearanceTrigger" class="btn btn-ghost appearance-trigger" aria-haspopup="dialog" aria-expanded="false" title="外观：主题与配色">
                        <span class="accent-dot" aria-hidden="true"></span>
                        <span class="theme-label" id="themeLabel"><?= $themeLabel ?></span>
                    </button>

                    <div class="appearance-pop" id="appearancePop" role="dialog" aria-label="外观设置" hidden>
                        <p class="appearance-title">模式</p>
                        <div class="mode-row">
                            <button type="button" class="mode-option<?= $theme === 'light' ? ' is-active' : '' ?>" data-mode-option="light">浅色</button>
                            <button type="button" class="mode-option<?= $theme === 'dark' ? ' is-active' : '' ?>" data-mode-option="dark">深色</button>
                        </div>

                        <p class="appearance-title">配色</p>
                        <div class="accent-row">
                            <?php foreach ($accents as $accentId => $accentLabel): ?>
                                <button type="button" class="accent-option<?= $accentId === $accent ? ' is-active' : '' ?>" data-accent-option="<?= htmlspecialchars($accentId, ENT_QUOTES, 'UTF-8') ?>" title="<?= htmlspecialchars($accentLabel, ENT_QUOTES, 'UTF-8') ?>" aria-label="配色：<?= htmlspecialchars($accentLabel, ENT_QUOTES, 'UTF-8') ?>">
                                    <span class="accent-swatch" aria-hidden="true"></span>
                                </button>
                            <?php endforeach; ?>
                        </div>
                    </div>
                </div>

                <form id="logoutForm" method="post" action="logout.php" class="logout-form">
                    <?= Csrf::field() ?>
                    <button type="submit" id="logoutButton" class="btn btn-ghost">登出</button>
                </form>
            </div>
        </header>

        <main class="views">
            <section id="view-gallery" class="view">
                <div class="toolbar">
                    <div class="datepicker" id="datePicker">
                        <button type="button" class="dp-trigger" id="dpTrigger" aria-haspopup="dialog" aria-expanded="false">
                            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 2v2H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2V2h-2v2H9V2H7Zm12 7v10H5V9h14Z"/></svg>
                            <span id="dpValue">未选择</span>
                        </button>
                        <div class="dp-popover" id="dpPopover" hidden role="dialog" aria-label="选择日期">
                            <div class="dp-head">
                                <button type="button" class="icon-button dp-nav" id="dpPrev" aria-label="上个月">‹</button>
                                <span class="dp-title" id="dpTitle"></span>
                                <button type="button" class="icon-button dp-nav" id="dpNext" aria-label="下个月">›</button>
                            </div>
                            <div class="dp-weekdays" id="dpWeekdays" aria-hidden="true"></div>
                            <div class="dp-grid" id="dpGrid" role="grid"></div>
                            <div class="dp-foot">
                                <button type="button" class="btn btn-ghost" id="dpLatest">跳到最新</button>
                                <span class="spacer"></span>
                                <button type="button" class="btn btn-ghost" id="dpClose">关闭</button>
                            </div>
                        </div>
                    </div>

                    <nav id="breadcrumb" class="breadcrumb" aria-label="当前位置"></nav>

                    <div class="toolbar-right">
                        <p id="levelStats" class="level-stats" hidden></p>

                        <div class="toolbar-actions">
                            <button type="button" id="backButton" class="btn btn-ghost" hidden>返回</button>
                            <button type="button" id="slideshowButton" class="btn">轮播</button>
                            <button type="button" id="monitorStartButton" class="btn btn-accent">实时监控</button>
                            <button type="button" id="monitorStopButton" class="btn btn-danger" hidden>停止监控</button>
                        </div>
                    </div>
                </div>

                <div id="activityBar" class="activity" hidden aria-label="当日各小时照片分布"></div>

                <p id="status" class="status" role="status" aria-live="polite" hidden></p>
                <p id="loading" class="loading" role="alert" aria-busy="true" hidden><span class="spinner"></span>正在加载…</p>

                <section id="gallery" class="grid" aria-live="polite">
                    <!-- 首帧占位：JS 启动前也有稳定的网格结构，避免白屏跳动 -->
                    <div class="tile-skeleton skeleton" aria-hidden="true"></div>
                    <div class="tile-skeleton skeleton" aria-hidden="true"></div>
                    <div class="tile-skeleton skeleton" aria-hidden="true"></div>
                    <div class="tile-skeleton skeleton" aria-hidden="true"></div>
                    <div class="tile-skeleton skeleton" aria-hidden="true"></div>
                    <div class="tile-skeleton skeleton" aria-hidden="true"></div>
                </section>

                <section id="monitor" class="monitor" hidden>
                    <div class="monitor-stage">
                        <img id="monitorImage" alt="实时照片">
                        <div class="viewer-actions">
                            <button type="button" id="monitorMaximize" class="image-button" title="最大化" aria-label="最大化">
                                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3h7v2H5v5H3V3m18 0v7h-2V5h-5V3h7M3 21v-7h2v5h5v2H3m18-7v7h-7v-2h5v-5h2"/></svg>
                            </button>
                        </div>
                    </div>
                    <dl class="meta monitor-meta">
                        <div><dt>文件名称</dt><dd id="monitorFilename">—</dd></div>
                        <div><dt>文件大小</dt><dd id="monitorFilesize">—</dd></div>
                        <div><dt>拍摄时间</dt><dd id="monitorTime">—</dd></div>
                    </dl>
                </section>
            </section>

            <section id="view-ops" class="view" hidden>
                <div class="ops">
                    <div class="ops-head">
                        <h2 class="ops-title">运维面板</h2>
                        <span id="opsPill" class="pill pill-mute">读取中</span>
                        <span class="spacer"></span>
                        <span id="opsUpdated" class="ops-updated"></span>
                        <button type="button" id="opsRefresh" class="btn btn-ghost">
                            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5V2L8 6l4 4V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7Z"/></svg>
                            刷新
                        </button>
                    </div>

                    <div id="opsWarnings" class="ops-warnings" hidden></div>
                    <div id="opsStats" class="stat-grid" aria-busy="true">
                        <div class="skeleton stat-skeleton" aria-hidden="true"></div>
                        <div class="skeleton stat-skeleton" aria-hidden="true"></div>
                        <div class="skeleton stat-skeleton" aria-hidden="true"></div>
                        <div class="skeleton stat-skeleton" aria-hidden="true"></div>
                    </div>

                    <div class="panel-grid">
                        <section class="card panel reveal">
                            <div class="panel-head"><h3 class="panel-title">采集服务</h3></div>
                            <div id="opsService" class="kv"><div class="skeleton panel-skeleton" aria-hidden="true"></div></div>
                        </section>

                        <section class="card panel reveal">
                            <div class="panel-head"><h3 class="panel-title">存储与安全</h3></div>
                            <div id="opsStorageSecurity" class="panel-stack"><div class="skeleton panel-skeleton" aria-hidden="true"></div></div>
                        </section>

                        <section class="card panel reveal panel-wide">
                            <div class="panel-head">
                                <h3 class="panel-title" id="opsChartTitle">每日张数</h3>
                                <span class="spacer"></span>
                                <span id="opsChartPeak" class="panel-hint"></span>
                            </div>
                            <div id="opsChart" class="chart"><div class="skeleton panel-skeleton" aria-hidden="true"></div></div>
                        </section>
                    </div>
                </div>
            </section>
        </main>
    </div>

    <noscript>
        <p class="status is-error noscript-note">此页面需要启用 JavaScript 才能浏览照片与查看运维数据。</p>
    </noscript>

    <div id="authOverlay" class="auth-overlay" role="dialog" aria-modal="true" aria-label="登录" <?= $authenticated ? 'hidden' : '' ?>>
        <div class="auth-card">
            <div class="auth-brand">
                <span class="brand-mark auth-mark" aria-hidden="true">
                    <svg viewBox="0 0 24 24"><path d="M9 2 7.2 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3.2L15 2H9Zm3 15a5 5 0 1 1 0-10 5 5 0 0 1 0 10Z"/></svg>
                </span>
                <div>
                    <h1 class="auth-title">照片查看器</h1>
                    <p class="auth-sub" id="authSub">请输入访问密码</p>
                </div>
            </div>

            <form id="authForm" method="post" action="login.php" autocomplete="off" novalidate>
                <?= Csrf::field() ?>
                <label class="auth-label" for="authPassword">密码</label>
                <div class="auth-field">
                    <input type="password" id="authPassword" name="password" required autocomplete="current-password">
                    <button type="button" id="authToggle" class="auth-toggle" aria-label="显示或隐藏密码">显示</button>
                </div>
                <p id="authCaps" class="auth-caps" hidden>注意：大写锁定已开启</p>
                <p id="authError" class="auth-error" role="alert" <?= $authMessage === '' ? 'hidden' : '' ?>><?= htmlspecialchars($authMessage, ENT_QUOTES, 'UTF-8') ?></p>
                <button type="submit" id="authSubmit" class="btn btn-accent btn-block">登 录</button>
            </form>

            <footer class="auth-footer">© <?= date('Y') ?> 相机系统</footer>
        </div>
    </div>

    <div id="viewer" class="overlay" hidden role="dialog" aria-modal="true" aria-label="图片查看">
        <div id="viewerShell" class="viewer-shell">
            <div id="viewerStage" class="viewer-stage">
                <div class="viewer-progress" id="viewerProgress" aria-hidden="true"><span></span></div>
                <img id="viewerImage" class="viewer-image" alt="">
                <div class="viewer-actions">
                    <button type="button" id="viewerMaximize" class="image-button" title="最大化" aria-label="最大化">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3h7v2H5v5H3V3m18 0v7h-2V5h-5V3h7M3 21v-7h2v5h5v2H3m18-7v7h-7v-2h5v-5h2"/></svg>
                    </button>
                    <button type="button" id="viewerClose" class="image-button" title="关闭" aria-label="关闭">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
                    </button>
                </div>
                <p id="viewerCounter" class="viewer-counter" hidden></p>
            </div>

            <div class="viewer-info">
                <p id="viewerTitle" class="viewer-title" hidden></p>
                <dl class="meta">
                    <div><dt>文件名称</dt><dd id="viewerFilename">—</dd></div>
                    <div><dt>文件大小</dt><dd id="viewerFilesize">—</dd></div>
                    <div><dt>拍摄时间</dt><dd id="viewerTime">—</dd></div>
                    <div><dt>距上一张</dt><dd id="viewerInterval">—</dd></div>
                </dl>

                <div class="viewer-timeline" id="viewerTimelineWrap" hidden>
                    <div class="tl-head">
                        <span id="viewerTimelineFrom" class="tl-edge">—</span>
                        <span id="viewerTimelineLabel" class="tl-current">—</span>
                        <span id="viewerTimelineTo" class="tl-edge">—</span>
                    </div>
                    <input type="range" id="viewerTimeline" class="tl-range" min="0" max="0" step="1" value="0" aria-label="时间轴">
                </div>

                <div class="viewer-controls">
                    <a id="viewerDownload" class="btn btn-accent" href="#" download>下载图片</a>
                    <div class="viewer-nav">
                        <button type="button" class="btn" id="viewerPlay" hidden>
                            <svg class="icon-play" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7L8 5Z"/></svg>
                            <svg class="icon-pause" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7V5Zm6 0h4v14h-4V5Z"/></svg>
                            <span id="viewerPlayLabel">播放</span>
                        </button>
                        <div class="speed-control" id="viewerSpeed" hidden>
                            <button type="button" class="speed-trigger" id="viewerSpeedTrigger" aria-haspopup="menu" aria-expanded="false" title="播放速度">
                                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2 4.5 13.5H11l-1 8.5 8.5-11.5H12l1-8.5Z"/></svg>
                                <span id="viewerSpeedValue">4x</span>
                                <svg class="speed-caret" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5H7Z"/></svg>
                            </button>
                            <div class="speed-menu" id="viewerSpeedMenu" hidden role="menu" aria-label="播放速度"></div>
                        </div>
                        <button type="button" id="viewerPrev" class="btn" title="上一张（←）">‹</button>
                        <button type="button" id="viewerNext" class="btn" title="下一张（→）">›</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script type="module" src="<?= Asset::url('assets/js/app.js') ?>"></script>
</body>
</html>
