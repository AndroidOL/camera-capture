<?php
/**
 * Web UI configuration.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * HOW THIS FILE WORKS
 * ─────────────────────────────────────────────────────────────────────────────
 * Return an associative array. Any key you omit falls back to the default in
 * src/Config.php, so delete lines you don't care about.
 *
 * Every key can ALSO be supplied as an environment variable named
 * GALLERY_<UPPERCASE_KEY>, and the environment always wins. That is the
 * recommended way to inject secrets (and handy for systemd / Docker):
 *     GALLERY_PASSWORD_HASH, GALLERY_CAPTURES_DIR, GALLERY_IMAGE_MODE, ...
 *
 * NOTE: a value of `null` means "not set" (the default is used). To point at a
 * real directory you must give an actual string.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * SECURITY
 * ─────────────────────────────────────────────────────────────────────────────
 * Every capture is private data. Only a password *hash* is supported; the
 * legacy plaintext password has been removed and must stay that way.
 *
 * There is deliberately NO default password: while `password_hash` is empty the
 * UI denies all access (logging in is impossible), so a fresh clone is never
 * accidentally open to the world.
 */

return [
    // =========================================================================
    // 1. 访问密码（登录前必须配置）
    // =========================================================================
    // 推荐：不要把密钥写进这个文件（也就不会进 git），改用环境变量：
    //     GALLERY_PASSWORD_HASH='$2y$...'
    // 例如写进 systemd unit：Environment="GALLERY_PASSWORD_HASH=$2y$..."
    //
    // 也可以直接把哈希填在下面 —— 但**绝不要**把真实哈希提交到公开仓库：
    //     php -r "echo password_hash('你的强密码', PASSWORD_DEFAULT), PHP_EOL;"
    'password_hash' => '',

    // 或者：从一个**文件**读取哈希（推荐在 Docker / secrets 场景用）。
    // 文件内容就是那一行纯哈希，末尾换行可有可无。
    //     'password_hash_file' => '/run/secrets/gallery_password_hash',
    // 为什么它更可靠：bcrypt 哈希里的 `$` 在 .env / docker compose 的变量插值
    // 里会被当成变量引用而吞掉，写进 .env 往往变成残缺值 → 密码对也登不进去。
    // 文件方式不经过任何插值，最安全。该项优先于上面的 password_hash。
    'password_hash_file' => null,

    // =========================================================================
    // 2. 照片目录与传输方式（proxy / direct 共用同一个目录）
    // =========================================================================
    // 目录结构：<captures_dir>/YYYY-MM/DD/capture_YYYYMMDD_HHMMSS_ffffff.jpg
    //
    // 这是**唯一的图片来源**，两种传输模式都用它：
    //   - proxy  模式：image.php 从这里读文件、鉴权后流式输出
    //   - direct 模式：Web 服务器把这个目录映射成一个 URL 前缀（web_path）
    //
    // 留 null = 默认 <web-ui>/captures。
    // capture.py 的默认输出目录是 /opt/camera/capture（见项目根 config.yaml），
    // 部署时通常要显式指过去，例如：
    //     'captures_dir' => '/opt/camera/capture',
    // 或 GALLERY_CAPTURES_DIR=/opt/camera/capture
    'captures_dir' => null,

    // 图片如何送到浏览器：
    //   'proxy'  —— 走 image.php，图片始终受登录保护（默认，推荐）
    //               除了 captures_dir 之外不需要任何额外配置
    //   'direct' —— Web 服务器直接对外提供该目录（更快、更省 PHP）
    //               但**必须**自己在 Web 服务器层做鉴权，
    //               否则任何人拿到 URL 就能看到照片。
    //               同时要把 web_path 设为对应的 URL 前缀。
    'image_mode' => 'proxy',

    // 仅 'direct' 模式使用：captures_dir 对外暴露的 URL 前缀。
    // 例：captures_dir = /opt/camera/capture，站点把它映射到 https://host/captures
    //     → 填 '/captures'
    'web_path' => '/captures',

    // =========================================================================
    // 3. 缩略图与缓存
    // =========================================================================
    // 缩略图 / 统计缓存目录。留 null = <系统临时目录>/photo_gallery_cache。
    // 注意：临时目录可能被系统清理（重启后缩略图会重建，不影响原图）。
    'cache_dir' => null,

    // 文件缓存的默认有效期（秒）。目录索引、可用日期、每日统计等都用它。
    'cache_ttl' => 3600,

    // 缩略图最长边（像素）与 JPEG 质量。图省流量就调小/调低。
    'thumb_max_dimension' => 420,
    'thumb_quality' => 78,

    // =========================================================================
    // 4. 会话与登录
    // =========================================================================
    // 会话 Cookie 名（HTTPS 下会自动加 __Host- 前缀）。
    'session_name' => 'PhotoGallerySession',

    // 空闲 / 绝对超时（秒）。0 = 不限制。
    'session_idle_timeout' => 1800,
    'session_absolute_timeout' => 43200,

    // 把会话绑定到客户端 IP（更严格，但换网络/移动网络会导致掉线）。
    'bind_session_to_ip' => false,

    // 登录失败限流：window 内超过 attempts 次即锁定 lockout 秒。
    'login_max_attempts' => 5,
    'login_lockout_seconds' => 300,

    // =========================================================================
    // 5. 接口限流
    // =========================================================================
    // 普通 API：每 IP 每 `api_rate_window` 秒最多 `api_rate_limit` 次。
    // 监控轮询最密约 1 次/秒（60 次/分），远低于默认上限；
    // 若调低请同步放宽，否则实时监控会被自己限流。
    'api_rate_limit' => 240,
    'api_rate_window' => 60,

    // 运维面板「刷新」按钮（会全量重算统计）的限流：每 IP 每分钟次数。
    'ops_refresh_rate_limit' => 6,

    // =========================================================================
    // 6. 前端默认行为
    // =========================================================================
    // 打开页面时的默认标签：'gallery'（相册）或 'ops'（运维）。
    'default_view' => 'gallery',

    // 轮播 / 查看器的初始倍速。可选：1、2、4、8、16、32。
    // （1x 表示"实时"：每帧停留时间 = 真实抓拍间隔 ÷ 倍速）
    'slideshow_speed' => 1,

    // 是否显示「下载图片」按钮（同时也就不再返回 attachment 响应头）。
    // 说明：这只影响便利性/界面，无法阻止用户截图或另存已显示的图片。
    'download_enabled' => true,

    // 默认外观。只对「还没自己选过」的新访客生效；用户切换后以浏览器 cookie
    // 为准（服务端据此渲染，所以不会闪主题）。
    //   theme_mode   —— 'dark'（默认，深色）或 'light'（浅色）
    //   theme_accent —— 配色方案：blue / teal / violet / amber / rose / green
    //                   深浅两种模式各有一套，互不影响。
    'theme_mode' => 'dark',
    'theme_accent' => 'blue',

    // =========================================================================
    // 7. 实时监控
    // =========================================================================
    // 自适应轮询的毫秒边界：发现新照片就加快、没有新照片就放慢。
    // 慢设备（如树莓派 + USB 摄像头）可以把 initial 调大一些。
    'monitor_initial_interval' => 1500,
    'monitor_min_interval' => 1000,
    'monitor_max_interval' => 8000,

    // =========================================================================
    // 8. 运维面板（只读）
    // =========================================================================
    // capture.py 写出的健康快照文件（其 LOG_DIR/health.json）。
    // 留 null = /opt/camera/logs/health.json。
    'health_file' => null,

    // 心跳超过这个秒数就判定为「心跳已过期」。
    'health_stale_seconds' => 900,

    // 磁盘占用超过这个百分比就在面板上告警。
    'disk_warn_percent' => 85,

    // 每日张数图表的窗口长度（天）与统计缓存 TTL（秒）。
    'stats_recent_days' => 31,
    'stats_cache_ttl' => 3600,

    // =========================================================================
    // 9. 安全 / 环境
    // =========================================================================
    // 只有在你自己控制的反向代理后面，才把 X-Forwarded-Proto 当真。
    'trust_proxy' => false,

    // 界面显示的时间来自文件名（capture.py 用的是本机时区）。
    // 把它设成采集设备的时区，派生时间才会准，例如 'Asia/Shanghai'。
    // 留 null = 沿用 PHP 默认时区。
    'timezone' => null,
];
