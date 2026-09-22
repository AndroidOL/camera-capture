# PROJECT_MEMORY — web-ui 照片查看器

> 本文件是 `web-ui` 的**技术记忆**：记录它是什么、数据契约、代码地图、HTTP 接口、安全模型与运维方式。
> 目的：任何人（包括未来的自己）在改动前先读这里，就能在几分钟内恢复全部上下文。
> 面向读者的叙述性文章见同目录 `README.md`；抓拍端见上级目录 `capture.py`；延时视频合成见 `merge/`。

---

## 1. 这是什么

- `web-ui` 是「按秒/按画面变化抓拍」系统的**私有网页控制台**，由两件事组成：**浏览已拍好的照片**（主功能）与**只读运维面板**（查看采集服务/磁盘/库统计，不做任何写操作）。
- 界面为**暗色优先 · 影像优先**的设计系统：照片占据视觉主导，chrome 尽量克制。
- 密码只以 **bcrypt 哈希**（`password_hash`）保存，**明文密码分支已完全移除**。**仓库内不含任何默认密码**：`password_hash` 默认为空，此时登录被彻底禁止（`Auth::attempt()` 直接返回 `false`），所以克隆下来不会「默认就能进」。部署时请自行设置：环境变量 `GALLERY_PASSWORD_HASH`，或**文件方式 `GALLERY_PASSWORD_HASH_FILE`**（容器/密钥场景推荐，可绕开 compose 对 `.env` 的 `$` 插值问题——见 §11）。
- 仓库根目录有 `.gitignore`，已经把照片库（`captures/` 等）、日志、缓存与 `health.json` 排除在外——开源时务必确认这些私有产物没有被提交。
- 静态资源带版本号（`Asset::url()` → `?v=<mtime>`），改动 JS/CSS 后浏览器不会再用到旧文件。
- 照片由 `capture.py` 写入，本质是延时摄影素材（一天可能几万张，且相邻帧高度相似）。
- **隐私是硬前提**：库里的每一张图都是个人生活影像。因此本项目的设计原则是
  **默认拒绝**（未登录不可见任何字节）、**最小暴露**（不依赖公网 CDN、不裸奔目录）、**不落缓存到共享层**。

---

## 2. 数据契约（最关键，改代码前必读）

抓拍端 `capture.py` 的落盘布局与文件名格式是 web-ui 的唯一事实来源：

```
<captures_dir>/
└── YYYY-MM/                      # 年-月
    └── DD/                       # 日（两位）
        └── capture_YYYYMMDD_HHMMSS_ffffff.jpg
```

- 例：`2025-09/03/capture_20250903_120000_123456.jpg`
- 时间信息**只存在于文件名**，没有数据库、没有 sidecar、没有 EXIF 依赖。
- 文件名定宽 → **字典序 == 时间序**（这是排序、取首/末张、分组的全部依据）。
- 匹配正则（`PhotoLibrary::FILE_PATTERN`，微秒段可选、扩展名大小写不敏感）：
  `/^capture_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?:_(\d+))?\.(jpe?g)$/i`

### 时间层级与「代表图」语义

| 层级 | 展示内容 | 每个格子的代表图 | 排序 |
|---|---|---|---|
| L1 日期 | 该日各小时 | 该小时**最早**一张 | 小时**倒序**（23→0） |
| L2 小时 | 6 个「10 分钟段」 | 该段内**最早**一张 | 段**倒序**（50-59→00-09） |
| L3 10 分钟段 | 该段内每分钟 | 该分钟**最早**一张 | 分钟**倒序**（9→0） |
| L4 分钟 | 该分钟全部照片 | — | **最新在前**（倒序） |
| 轮播 | 当前上下文全部照片 | — | **正序**（时间顺序播放） |

> 上一版（`gallery_api.php` + 内联 JS）的排序约定被**逐条保留**，仅内部实现重写。
> 若将来修改排序，请同步更新此表——这是前端文案（"该小时首张"）与用户预期的来源。

---

## 3. 代码地图

```
web-ui/
├── config.php            # 唯一需要人工编辑的配置（返回数组；可被环境变量覆盖）
├── index.php             # 主页面骨架：鉴权 → 输出 HTML 外壳（无内联样式/脚本）
├── login.php             # 登录页 + 登录处理（限流 + CSRF + 密码校验）
├── logout.php            # 登出（仅 POST + CSRF 校验）
├── api.php               # JSON 接口唯一入口（鉴权 → 限流 → 路由）
├── image.php             # 鉴权图片通道（原图 / 缩略图 / 下载）
├── .htaccess             # Apache 加固（禁目录列表、封 captures/ 与 src/）
│
├── src/                  # 后端：命名空间 Gallery\，bootstrap 内含轻量自动加载
│   ├── bootstrap.php     # 自动加载 + 载入配置 + 错误处理 + 启动会话（所有入口第一行 require）
│   ├── Config.php        # 默认值 ← config.php ← 环境变量(GALLERY_*) 三级合并
│   ├── PhotoLibrary.php  # 领域核心：目录扫描/索引/校验/层级查询/路径解析
│   ├── Media.php         # 图片 URL 生成（proxy / direct 两种模式）
│   ├── Thumbnailer.php   # GD 缩略图生成 + 磁盘缓存（GD 缺失时优雅降级）
│   ├── OpsMonitor.php    # 运维数据：服务健康(health.json) + 磁盘占用 + 库统计
│   ├── Support/Asset.php # 静态资源版本号（?v=mtime），避免浏览器用旧 JS/CSS
│   ├── Api/
│   │   ├── Router.php            # action 白名单 → 控制器方法 → 统一 JSON/错误
│   │   └── GalleryController.php # 各 action 的参数校验与响应组装
│   ├── Security/
│   │   ├── Auth.php      # 会话启动、登录校验、超时、登出、IP 绑定
│   │   ├── Csrf.php      # CSRF token 生成/校验/表单字段
│   │   └── Headers.php   # 安全响应头 + CSP（含每请求 nonce）
│   └── Support/
│       ├── Response.php  # JSON 输出
│       ├── FileCache.php # 文件缓存（索引/最新照片）
│       └── RateLimiter.php # 基于 flock 的滑动窗口限流
│
└── assets/               # 前端：原生 ES Modules，**无构建步骤**
    ├── css/base.css      # 设计令牌（暗色优先）、reset、按钮/表单/分段控件/骨架屏
    ├── css/app.css       # 外壳：顶栏、工具栏、面包屑、网格瓦片、查看器、监控区
    ├── css/admin.css     # 运维面板：统计卡、磁盘仪表、每日柱状图、入场揭示
    ├── css/login.css     # 登录页样式
    └── js/
        ├── app.js        # 入口：装配模块、视图路由(相册/运维)、日期上下界
        ├── dom.js        # DOM 引用集合 + loading/status 控制 + create() 构建器
        ├── theme.js      # 明暗主题：写 localStorage + cookie（服务端据此渲染）
        ├── anim.js       # 动效工具：错峰/数字滚动/宽度高度动画/滚动揭示/减弱动效
        ├── util.js       # 体积/时间/时长格式化、文件名解析、图片淡入、占位图、预加载
        ├── api.js        # fetch 封装（可取消、401 跳登录、可选静默）
        ├── datepicker.js # 自建日历（无照片日期不可选、键盘导航、月份边界）
        ├── viewer.js     # 统一查看器：翻页/时间轴/自动播放/快捷键/间距/live
        ├── gallery.js    # 层级导航状态机 + 面包屑 + 瓦片 + 层级统计 + 24h 活动条
        ├── admin.js      # 运维面板渲染（统计卡/服务/存储/安全/图表）
        ├── slideshow.js  # 照片轮播（复用 viewer，自动播放）
        ├── monitor.js    # 实时监控：自适应轮询 + 启停 + 大图联动 + 面包屑
        └── login.js      # 登录页交互（主题/显示密码/大写锁定提示）
```

---

## 4. 请求流程

```
浏览器
  ├─ 未登录访问 index.php ──► 302 login.php?error=unauthorized
  ├─ login.php  (GET 表单带 CSRF) ──► POST ──► 限流检查 ──► 密码校验 ──► session_regenerate_id ──► 302 index.php
  ├─ index.php  渲染外壳（<script type="module" src="assets/js/app.js">）
  ├─ app.js     ① 读取 CSRF/主题 ② getEarliestDate + getLatestDate 设日期上下界 ③ 默认定位到最新日期
  ├─ api.php?action=...  ← 每次翻层调用一次，返回 JSON（含 image_url / preview_image_url）
  └─ image.php?p=...     ← <img> 标签请求，会话鉴权后流式返回照片字节
```

要点：**页面、接口、图片三条路径都独立鉴权**。图片不再由 Web 服务器直接静态提供（见 §8）。

---

## 5. HTTP 接口契约

单一入口：`GET api.php?action=<action>`，全部返回 `application/json; charset=utf-8`。

### 统一 photo 对象

除层级标识字段外，所有图片对象结构一致：

```json
{
  "filename": "capture_20250903_120000_123456.jpg",
  "filesize": 9027,
  "time": "2025-09-03 12:00:00",
  "epoch": 1756900800,
  "image_url": "image.php?p=2025-09%2F03%2Fcapture_20250903_120000_123456.jpg",
  "preview_image_url": "…&thumb=1",
  "download_url": "…&download=1"
}
```

- `time` 供显示；`epoch`（秒）供前端调度，避免时区解析歧义（文件名是**服务器本地时间**）。
  - ⚠️ **展示一律用 `time` / 文件名派生值**，不要用 `epoch` 还原成时钟字符串：`epoch` 由服务器时区算出，而浏览器时区可能不同（见 `timezone` 配置）。
- 网格列表用 `preview_image_url`（缩略图）；查看器/轮播用 `image_url`（原图）。
- 层级汇总项的 `photo` 上还带一个 **`count`**：该时段内的实际照片数（小时 / 10 分钟段 / 分钟）。
  网格字幕与「层级统计」都基于它；`0` 不会出现在结果里（无照片的时段直接不返回）。

### action 一览

| action | 参数 | 返回 |
|---|---|---|
| `getEarliestDate` | — | `{earliestDate: "YYYY-MM-DD"\|null}` |
| `getLatestDate` | — | `{latestDate: "YYYY-MM-DD"\|null}` |
| `getAvailableDates` | — | `{availableDates: ["YYYY-MM-DD", …]}`（有 5 分钟缓存） |
| `getLatestPhoto` | — | `{latest_photo: photo\|null}`（监控轮询用） |
| `getDailySummary` | `date` | `{date, hourly_previews:[{hour, …photo}]}` |
| `getHourlySummary` | `date`, `hour` | `{date, hour, ten_minute_previews:[{interval_slot, label, …photo}]}` |
| `getTenMinuteSummary` | `date`, `hour`, `interval_slot`(0-5) | `{date, hour, interval_slot, minute_previews:[{minute, …photo}]}` |
| `getMinutePhotos` | `date`, `hour`, `minute` | `{date, hour, minute, photos:[…]}`（倒序） |
| `getPhotoListForRange` | `date`[, `hour`][, `interval_slot`][, `minute`] | `{date, hour, interval_slot, minute, photos:[…], total_photos_in_range}`（正序） |
| `getOpsOverview` | [`refresh=1`] | `{service, storage, library}`（运维面板，见下） |

- 参数非法/缺失 → `400 {"error":"中文说明"}`；未登录 → `401`；限流 → `429`（带 `Retry-After`）。
- `getPhotoListForRange` 参数按粒度递进：只给 `date` = 全天；`+hour` = 该小时；`+interval_slot` = 该 10 分钟段；`+minute` = 该分钟。

### 与上一版的差异（重要）

| 旧 | 新 | 说明 |
|---|---|---|
| `gallery_api.php` | `api.php` + `src/Api/*` | action 名与参数**保持兼容**，仅文件/分层改变 |
| `getLatestMeta` | 已移除 | 旧前端未使用；`getLatestPhoto` 已由文件缓存承担相同开销 |
| `/captures/...` 直链 | `image.php?p=...` | 图片改为鉴权通道（隐私修复） |
| `preview_image_url` 指向 `/tmp/...` | `image.php?...&thumb=1` | 修复旧版缩略图 URL 必然失效的 bug |

---

### 运维面板（`getOpsOverview`）

**只读，不提供任何写操作。** 三块数据来源：

1. **`service`** —— 读取 `health_file`，即 `capture.py` 每 `HEARTBEAT_INTERVAL_SECONDS`(300s) 写出的 `health.json`：

   ```json
   {"boot_id":"1760000000-4213","ts":1760000000.12,"interval":2.0,"read_failures":0,
    "imwrite_failures":0,"disk_cleanup_batches":1,
    "last_saved":"/opt/camera/captures/2025-09/04/capture_20250904_204500_000001.jpg",
    "fourcc":"YUYV"}
   ```

   - `state`：`ts` 距今 ≤ `health_stale_seconds` → `running`；超时 → `stale`；文件缺失/不可读 → `available:false`。各字段独立降级为 `null`，不会因为健康文件残缺而报错。
   - **只回传 `last_saved` 的 basename**，再由文件名解析出 `last_saved_at` —— 避免把服务器绝对路径暴露到前端。

2. **`storage`** —— `disk_total_space`/`disk_free_space`（作用于 `captures_dir`）算出 `used_percent`；`status` = `ok` / `warning`(≥`disk_warn_percent`) / `unknown`。

3. **`library`** — 由 `PhotoLibrary::libraryStats()` 聚合：月数、有照片天数、总张数、总体积、最早/最晚日期、`by_month`、`recent_days`。
   - **按「日」缓存并以日目录 mtime 失效**（`FileCache` 的 `stats` 命名空间）：只有内容变动的那一天才需要重新 `stat` 每个文件；冷启动之后，稳态开销仅是列目录 + 读缓存。这是应对「一天数万张」的关键设计。
   - `recent_days` 是**连续窗口**（以 `latest` 为终点回溯 `stats_recent_days` 天，缺失的日子补 `files: 0`），不是"有数据的那几天"——图表因此是真正的时间轴，能看出某天完全没抓拍。
   - **前端呈现**：31 天若挤成一排竖柱会过密，因此改成 **3 列 × 横向日行**（每行 `日期 · 进度条 · 张数`，条宽 = 该日张数 / 峰值），按行优先填充分布即自然的时间顺序；标题与峰值（`共 N 张 · 峰值 M 张（日期）`）从 `window_days` / 数据实时算出，不写死天数。窄屏自动降为 2 列 / 1 列。
   - 面板「刷新」按钮传 `refresh=1` 跳过缓存重算（有独立限流）。

---

## 6. 图片传输（`image.php`）

```
image.php?p=<相对路径>          # 原图
image.php?p=<相对路径>&thumb=1   # 缩略图（GD 生成，磁盘缓存）
image.php?p=<相对路径>&download=1 # 附件下载（Content-Disposition: attachment）
```

- `p` 形如 `2025-09/03/capture_..._000001.jpg`；经**严格正则 + realpath 前缀校验**双重防护（§8）。
- 响应头：`Content-Type: image/jpeg`、`Cache-Control: private, max-age=86400`、`ETag`、`Last-Modified`，支持 `If-None-Match → 304`。
- 缩略图缓存在 `<cache_dir>/thumbs/<sha256(路径|mtime|尺寸|质量)>.jpg`；源文件更新后自动重算。
- 两种模式（`image_mode`）：

| 模式 | 行为 | 适用 |
|---|---|---|
| `proxy`（默认） | 所有字节经 `image.php`，PHP 内鉴权 | 隐私优先，**推荐** |
| `direct` | 由 Web 服务器直接提供 `<web_path>/<rel>` | 追求极致静态性能；**必须**自行在 Web 服务器层对该目录做鉴权 |

---

## 7. 配置

编辑 `config.php`（返回数组），或使用同名大写环境变量覆盖（环境变量优先级最高，便于 systemd/容器）。

| key | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| `password_hash_file` | `GALLERY_PASSWORD_HASH_FILE` | `null` | **推荐（容器/密钥）**。指向一个只含一行 `password_hash()` 结果的文件（会 `trim` 换行）。**优先级最高**，且绕过 compose 对 `.env` 的 `$` 插值问题；文件不存在/为空时自动回退到 `password_hash` |
| `password_hash` | `GALLERY_PASSWORD_HASH` | `''`（留空＝禁止登录） | `password_hash()` 结果；**切勿把真实哈希提交到公开仓库**。三者（`password_hash_file` / `password_hash` / `password`）全空＝禁止登录 |
| `password` | `GALLERY_PASSWORD` | （空） | **已停用**：明文登录不再被采纳（保留键位只为让运维面板提示迁移），请只用 `password_hash` / `password_hash_file` |
| `captures_dir` | `GALLERY_CAPTURES_DIR` | `<web-ui>/captures` | 照片库根目录。**proxy 与 direct 两种模式共用的唯一图片来源**（proxy 由 `image.php` 从这里读并鉴权输出；direct 由 Web 服务器把它映射成 `web_path`）。capture.py 的默认输出目录是 `/opt/camera/capture`，部署时通常要显式指过去 |
| `image_mode` | `GALLERY_IMAGE_MODE` | `proxy` | `proxy` / `direct` |
| `web_path` | `GALLERY_WEB_PATH` | `/captures` | 仅 `direct` 模式使用 |
| `cache_dir` | `GALLERY_CACHE_DIR` | `<sys_temp>/photo_gallery_cache` | 缓存/限流/缩略图根目录 |
| `cache_ttl` | `GALLERY_CACHE_TTL` | `3600` | 默认缓存 TTL（秒） |
| `thumb_max_dimension` | `GALLERY_THUMB_MAX_DIMENSION` | `420` | 缩略图最长边（px） |
| `thumb_quality` | `GALLERY_THUMB_QUALITY` | `78` | 缩略图 JPEG 质量 |
| `session_name` | `GALLERY_SESSION_NAME` | `PhotoGallerySession` | 会话 Cookie 名 |
| `session_idle_timeout` | `GALLERY_SESSION_IDLE_TIMEOUT` | `1800` | 空闲超时（秒） |
| `session_absolute_timeout` | `GALLERY_SESSION_ABSOLUTE_TIMEOUT` | `43200` | 绝对超时（秒） |
| `bind_session_to_ip` | `GALLERY_BIND_SESSION_TO_IP` | `false` | 绑定 IP（移动网络下可能误伤，默认关） |
| `api_rate_limit` | `GALLERY_API_RATE_LIMIT` | `240` | 每 IP 每窗口 API 次数 |
| `api_rate_window` | `GALLERY_API_RATE_WINDOW` | `60` | API 限流窗口（秒） |
| `login_max_attempts` | `GALLERY_LOGIN_MAX_ATTEMPTS` | `5` | 登录失败次数上限 |
| `login_lockout_seconds` | `GALLERY_LOGIN_LOCKOUT_SECONDS` | `300` | 登录锁定时长（秒） |
| `health_file` | `GALLERY_HEALTH_FILE` | `/opt/camera/logs/health.json` | 采集服务的健康快照文件（只读） |
| `health_stale_seconds` | `GALLERY_HEALTH_STALE_SECONDS` | `900` | 心跳超过此秒数即判定为「心跳已过期」 |
| `disk_warn_percent` | `GALLERY_DISK_WARN_PERCENT` | `85` | 磁盘占用告警阈值（%） |
| `stats_recent_days` | `GALLERY_STATS_RECENT_DAYS` | `31` | 运维面板图表展示的最近天数（也是 `recent_days` 连续窗口长度） |
| `stats_cache_ttl` | `GALLERY_STATS_CACHE_TTL` | `3600` | 每日统计缓存 TTL（秒） |
| `trust_proxy` | `GALLERY_TRUST_PROXY` | `false` | 是否信任 `X-Forwarded-Proto`（仅在自建反代后开启） |
| `ops_refresh_rate_limit` | `GALLERY_OPS_REFRESH_RATE_LIMIT` | `6` | 每 IP 每分钟 `getOpsOverview&refresh=1` 的次数上限 |
| `default_view` | `GALLERY_DEFAULT_VIEW` | `gallery` | 打开页面默认标签：`gallery` / `ops`（URL hash 优先） |
| `slideshow_speed` | `GALLERY_SLIDESHOW_SPEED` | `1` | 查看器/轮播初始倍速，取值 `1/2/4/8/16/32` |
| `download_enabled` | `GALLERY_DOWNLOAD_ENABLED` | `true` | 是否显示「下载图片」；关掉后 `image.php` 也只返回 `inline` 而非 `attachment` |
| `theme_mode` | `GALLERY_THEME_MODE` | `dark` | 默认外观模式（仅对未选择过的新访客生效）：`dark` / `light` |
| `theme_accent` | `GALLERY_THEME_ACCENT` | `blue` | 默认配色：`blue`/`teal`/`violet`/`amber`/`rose`/`green` |
| `monitor_initial_interval` | `GALLERY_MONITOR_INITIAL_INTERVAL` | `1500` | 实时监控初始轮询间隔（ms） |
| `monitor_min_interval` | `GALLERY_MONITOR_MIN_INTERVAL` | `1000` | 监控轮询下限（ms） |
| `monitor_max_interval` | `GALLERY_MONITOR_MAX_INTERVAL` | `8000` | 监控轮询上限（ms，慢设备可调大） |
| `timezone` | `GALLERY_TIMEZONE` | `null` | 采集设备时区（如 `Asia/Shanghai`）；用于 `epoch` 等派生时间 |

生成密码哈希（仓库里没有任何默认密码，必须自己设一个）：

```bash
php -r "echo password_hash('你的强密码', PASSWORD_DEFAULT), PHP_EOL;"

# 推荐：用环境变量注入，密码不落盘也不进 git
export GALLERY_PASSWORD_HASH='$2y$...'
# 或写进 systemd unit： Environment="GALLERY_PASSWORD_HASH=$2y$..."

# Docker 等场景推荐用「文件」而非环境变量：
#   bcrypt 里的 `$` 会被 compose 对 .env 的插值吞掉（$2y$12$abc → $$2y$$12），
#   表现为「密码正确却登不进去」。挂成 secret / 读文件则完全不经过插值。
mkdir -p secrets
php -r "echo password_hash('你的强密码', PASSWORD_DEFAULT), PHP_EOL;" > secrets/password_hash.txt
# 再设 GALLERY_PASSWORD_HASH_FILE=/run/secrets/gallery_password_hash

# 也可以直接填写 config.php 的 password_hash（但别把真实哈希提交到公开仓库）
```

> 监控轮询最密约 1 次/秒（60 次/分），远低于默认 240/分 的上限；若调低 `api_rate_limit` 请同步放宽。

---

## 8. 安全模型（隐私优先）

这是本项目与普通相册最不同之处——**默认认为"能拿到 URL 就能看图"是不可接受的**。

1. **全链路鉴权**：`index.php` / `api.php` / `image.php` 三者都在输出任何内容前检查会话；未通过一律拒绝。
2. **会话加固**：`HttpOnly` + `SameSite=Lax` + HTTPS 下自动 `Secure`；`use_strict_mode`；`use_only_cookies`；登录成功 `session_regenerate_id(true)`；空闲/绝对双超时。
3. **密码策略**：只使用 `password_hash`/`password_verify`（bcrypt，`PASSWORD_DEFAULT`）；**明文登录分支已移除**（`Auth::attempt()` 只认哈希，`Config::hasPassword()` 只看哈希）；`hash_equals` 用于 CSRF token 抗时序比较。
4. **登录限流**：按 IP 滑动窗口计数，超限锁定；成功登录清零计数。抵御暴力破解。
5. **CSRF**：登出等所有状态变更走 POST + CSRF token（`hash_equals` 校验）；token 来自会话，随会话失效。
6. **安全响应头**（`Headers::apply`）：
   - 全站：`X-Content-Type-Options`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、`Cross-Origin-Opener-Policy`、`Cross-Origin-Resource-Policy`、`Permissions-Policy`、HTTPS 下 `HSTS`。
   - 页面/接口：`Cache-Control: no-store`（私有数据绝不进浏览器缓存/中间缓存）+ 严格 CSP。
   - CSP：`default-src 'self'`，无任何第三方源；`script-src 'self'`（已无任何内联脚本）；HTTPS 下附加 `upgrade-insecure-requests`。
7. **路径穿越防护**：`PhotoLibrary::resolve()` 先用白名单正则约束形状（`YYYY-MM/DD/capture_<安全字符>.jpg`），再 `realpath` 并校验前缀必须位于库根目录之下，最后 `is_file`。三层任一不满足即 404。
8. **图片不复用公有缓存**：`private, max-age` 仅允许浏览器本地缓存，代理/CDN 不得缓存。
9. **零外部依赖**：移除 CDN（原 flatpickr）后，页面不产生任何第三方请求——既收紧 CSP，也避免向第三方泄露访问行为。
10. **不被搜索引擎收录**：`X-Robots-Tag: noindex, nofollow, noarchive, nosnippet` + 页面 `noindex` meta + `robots.txt`（`Disallow: /`）。
11. **Cookie 收敛**：会话 Cookie 强制 `path=/`、`domain=`（host-only），HTTPS 下自动加 `__Host-` 前缀（杜绝子域写入/覆盖）。
12. **反代头默认不信任**：`X-Forwarded-Proto` 仅在 `trust_proxy` 打开时才被采纳，避免伪造头影响 Secure/HSTS 判定。
13. **媒体内容校验**：`image.php` 除路径校验外，再用 `finfo` 确认 MIME 为 `image/jpeg`，否则 415。
14. **昂贵操作单独限流**：`getOpsOverview&refresh=1`（全量重算统计）按 IP 限流（默认 6 次/分）。
15. **安全态势可见**：运维面板「安全」卡直接列出密码存储方式 / HTTPS / Cookie 属性 / 图片通道 / robots 状态，并在顶部横幅列出待修项（明文密码、未启用 HTTPS、direct 模式等）。

### 部署加固清单

- **务必启用 HTTPS**（否则密码与会话 Cookie 明文传输）。
- Apache：保留 `.htaccess`（已封 `captures/`、`src/`、点文件与敏感扩展名）。**若改用 `direct` 模式，必须删除其中封 `captures/` 的 RewriteRule**，并改用 Web 服务器层鉴权。
- nginx 等价配置示例：

  ```nginx
  location ~ ^/(captures|src)/ { deny all; }
  location ~ /\. { deny all; }
  location ~* \.(md|log|ini|yml|yaml|sql|bak|json|lock)$ { deny all; }
  ```
- 照片库目录权限收紧到 Web 服务用户只读（`capture.py` 写入用户可写）。

---

## 9. 前端架构

- **原生 ES Modules，无构建步骤**：`<script type="module" src="assets/js/app.js">`；模块间用 `import`/`export` 组织，改完刷新即可，无需编译。
- **模块职责**：`app.js` 只做装配；`gallery.js` 持有导航状态机；`viewer.js` 是可复用的弹层；`monitor.js` 独立管理轮询；`slideshow.js` 仅负责取数并调用 `viewer`。
- **导航状态机**：`{level(0-4), date, hour, slot, minute}` + 历史栈 `history[]`。
  - 点击卡片 `navigate()` 入栈；`goBack()` 出栈；点击面包屑 `jumpTo()` **清空历史**（"跳到某一层"而非"回退"）。
  - 面包屑由状态推导，层级 ≥ 目标层的片段自动变为可点链接。
- **统一查看器（`viewer.js`）**：取代旧版的「大图弹层 + 轮播弹层」两套重复实现。三种用法：
  - 网格点击 → `openViewer({items, index, title})`
  - 照片轮播 → `openViewer({items, index:0, title})`
  - 监控最大化 → `openViewer({items:[photo], live:true, maximized:true})`，`updateViewerItem()` 随轮询刷新
  - 支持 ←/→ 翻页、Esc 关闭、点击遮罩关闭、最大化切换、相邻图预加载、打开时聚焦关闭按钮。
- **监控自适应轮询**（`monitor.js`）：探测到新图 → 间隔 ×0.8（下限 1s）；无新图 → ×1.25（上限 8s）；并用 `epoch` 预测下一张时间 + 150ms 偏移排程。无需预先知道抓拍间隔。
- **主题（无闪烁）**：`<html data-theme>` 由**服务端**依据 `gallery_theme` cookie 直接渲染，所以首帧就是正确主题，不存在「刷新先黑一下再变亮」。顶栏是一个**带文字的按钮**（`☾ 深色` / `☀ 浅色`，标签由服务端渲染、JS 切换时同步），不用认图标也能找到。`theme.js` 只负责切换时同时写 `localStorage` + cookie，并在二者不一致时同步；`getTheme()` 永远读真实的 `dataset.theme`（修掉了「首次点击看似无效」的 bug）。因不再需要内联脚本，CSP 收敛为 `script-src 'self'`。
- **日期选择**：自建日历弹层（`datepicker.js`）——原生 `<input type="date">` 无法禁用任意日期。**只有确实有照片的日期可选**（集合来自 `getAvailableDates`），其余置灰划掉；含上下界与月份边界钳制、`←→↑↓ / Home / End / PgUp / PgDn / Enter / Esc` 键盘导航、点击外部关闭。取不到可用日期时退化为仅按上下界限制，不阻塞使用。
- **工具条（单一 sticky 行）**：`[日期选择器] [下钻面包屑] …… [层级统计] [返回/轮播/监控]`。
  - **日期只出现一次**（选择器里），面包屑只画「下钻路径」且首项是 `全天` 而不是重复日期——这是刻意的去重设计。
  - 层级统计与旧的 `status` 文案合并成一行（`N 个小时 · X 张 · 起止 · 跨度`），因此不再有"同一条信息说两遍"的问题；`status` 现在只用于**错误与监控状态**。
- **查看器**：相邻图预加载；底部**时间轴**（拖动即跨分钟/小时跳转，两端只显示时刻，不重复日期）；**自动播放**（播放/暂停、到底自动循环、顶部进度条）；`距上一张 +MM:SS`；快捷键 `←/→`、空格、`Home/End`、`Esc`。
  - **播放节奏 = 贴合真实抓拍间隔**：`每帧停留 = clamp(与相邻帧的真实间隔, ≤6s) ÷ 倍速`，下限 100ms。因此 **1x 就是"实时"**（1 个真实秒 = 1 个播放秒），间隔长的帧自然停留更久 —— 这才是"变化抓拍"素材该有的节奏，而不是一律等速。所有展示一律取文件名派生时间，不做时区换算。
  - **倍速档位** `1x/2x/4x/8x/16x/32x`，用**弹出菜单**呈现（`⚡ 当前倍速 ▾` → 每档都标注"每帧 X 秒"，例如 1x 显示"每帧 6.0 秒 · 实时"）；播放时时间轴标签会追加当前每帧时长（如 `12:00:14 · 3/9 · 0.8s`）。
  - **布局要点**：`.viewer-shell` 固定 `height:96vh`，`.viewer-stage` 为 `flex:1 1 auto; min-height:0`，图片 `max-height:100%` —— 这样图片永远**恰好放进舞台**，不会溢出。进度条放在舞台的 `padding-top` 留白带里（`has-progress` 类），与图片**不重叠**。
- **层级统计 + 活动条**：每次进入层级都计算一行统计（`张数 · 起止时刻 · 跨度`）；L1 额外渲染 **24 小时活动条**（柱高用 `scaleY` 表达该小时张数占比，点击直接跳进该小时）。
- **监控**：画面与底部元信息**同宽对齐**（宽度约束放在 `.monitor` 容器上）；舞台用 `aspect-ratio: 16/9` 精确贴合画面，**四边无黑边**（底色用 `--surface-2` 而非纯黑）；监控期间面包屑切换为 `实时监控 › 最新照片时间`；最大化后打开 live 查看器，新照片到达会**实时替换**（`updateViewerItem`）。
- **视图路由**：`app.js` 用 `#gallery` / `#ops` 两个 hash 切换 `#view-gallery` / `#view-ops`，切换时 `restartAnimation()` 重放 `.view` 入场动画；分段控件 `.seg` 内含一个由 JS 定位的滑动 `.seg-thumb` 指示器。
- **服务端配置 → 前端的通道**：`index.php` 把前端需要的配置渲染成 `<body data-view / data-speed / data-download / data-monitor-*>`，JS 统一读 `document.body.dataset`。用 data 属性而不是内联 `<script>`，是因为 CSP 收紧为 `script-src 'self'`（内联脚本会被直接拦截）。**以后新增前端配置项请沿用这个通道**：`Config` 加键 → `index.php` 渲染 data 属性 → JS 读，改配置无需动 JS。
- **动效约定**（统一收在 `anim.js`）：
  - `.tile` 借 `--i` 做**错峰入场**（`animation-delay: calc(var(--i) * 26ms)`）；`stagger()` 写 `--i`（上限 24，避免大网格总延迟过长）。
  - 图片用 `opacity:0 → .is-loaded` 做**淡入 + 轻微缩放**（`bindImageFade` / `setImageSrc`）。
  - 弹层：`.overlay.is-open` 淡入 + `.viewer-shell` 的 `shellIn`（缩放/位移 + 弹簧缓动）；打开时 `restartAnimation()` 确保可重复播放。
  - 查看器换图：`.is-swapping` 先瞬时降到 `opacity:0`（该状态内 `transition:none`），加载完成后再淡入——单个 `<img>` 也能做出干净的交叉过渡。
  - 运维面板：数字**滚动**（`countUp`）、磁盘条与柱状图**从 0 生长**（`animateWidth`/`animateHeight`）、面板进入视口时**揭示**（`observeReveal` + `.reveal`）。
  - **全局尊重 `prefers-reduced-motion: reduce`**：动画/过渡降为近乎零时长，并跳过错峰与滚动揭示。
- **设计系统（暗色优先）**：颜色/圆角/阴影/缓动全部集中在 `base.css` 的 `:root`（暗色即默认）与 `[data-theme='light']`。新增组件请复用令牌，不要在组件里写死颜色。照片瓦片统一 `aspect-ratio: 16/9`（素材恒为 1920×1080），标签用底部渐变 scrim 叠在图上，实现「影像优先」。
- **外观系统（模式 × 配色，两个正交维度）**：
  - `data-theme`（`dark`/`light`）与 `data-accent`（`blue`/`teal`/`violet`/`amber`/`rose`/`green`）都渲染在 `<html>` 上，**由服务端按 cookie 决定**（`Support\Theme`：cookie 优先，`config.php` 的 `theme_mode`/`theme_accent` 兜底）。因此首帧就是正确外观。
  - **防闪关键 1**：`<head>` 里服务端渲染 `<meta name="color-scheme" content="dark|light">`。只把 `color-scheme` 写在 CSS 里太晚 —— 浏览器会在 CSS 生效前按**操作系统**偏好先画一帧，于是"刷新黑一下/白一下"。有 meta 后首帧画布就是对的。
  - **防闪关键 2**：`theme.js` 的 `initTheme()` **只做镜像**（写 localStorage + cookie + 同步按钮态），**绝不改写**服务端渲染出来的值。客户端一旦"再改一次"，就会看到加载后主题跳变 —— 这是刷新闪主题的根因，请务必保持。
  - 配色是"只覆盖 accent 令牌"的覆盖层：`[data-accent=x]` 给暗色值，`[data-theme='light'][data-accent=x]` 给浅色值，所以换配色不影响深浅模式，反之亦然。
  - 新增带 accent 背景的组件，前景色请用 `var(--on-accent)`，**不要写死** `#05070c`（浅色模式下 accent 变深，写死会不可读）。

---

## 10. 性能设计

| 手段 | 位置 | 收益 |
|---|---|---|
| **单次目录扫描建索引** | `PhotoLibrary::loadDayIndex()` | 旧版按小时/段做几十次 `glob()`；现改为 `opendir` 一次，内存中按 `HHMMSS` 分组 |
| **存在性早退检查** | `hasPhoto()` | `readdir` 命中即返回，不必列完几千文件 |
| **请求内索引缓存** | `$dayIndex` 数组 | 同请求多次查询同一日不重复扫盘 |
| **跨请求文件缓存** | `FileCache` | 最新照片按「日目录 mtime」失效；可用日期 5 分钟 TTL |
| **缩略图磁盘缓存** | `Thumbnailer` | 网格加载 ~420px 小图而非 1920px 原图，并支持 304 |
| **`session_write_close()` 早释放** | `api.php` / `image.php` | 否则 PHP 会话锁会让并发的图片请求串行化 |
| **前端相邻图预加载** | `util.js` | 翻页/轮播切换无明显等待 |

---

## 11. 部署

- **依赖**：PHP 7.4+（7.3 亦可用；本地以 8.4 验证）、`gd`、`json`、`session`、`fileinfo`。**无需** Composer / npm / 构建。
- **Web 根目录**：指向 `web-ui/`；`captures_dir` 可指向外部真实库（`GALLERY_CAPTURES_DIR`）。
- **首次配置**：**没有默认密码**——`Config::passwordHash()` 的取值优先级为 `password_hash_file` → `password_hash`，两者都为空则**任何人都无法登录**（明文 `password` 已停用、不参与认证）。至少设置一项；确认 `GALLERY_CAPTURES_DIR` 与权限；启用 HTTPS。
- **Docker（php-fpm + nginx，卷映射）**：仓库里已备好一整套（与 `web-ui/` 同级）：
  - `docker-compose.yml`：`php`（`phpdockerio/php:8.4-fpm`，`PHP_FPM_LISTEN=/var/run/php/php-fpm.sock`）+ `nginx`（`nginx:stable`，`${GALLERY_HTTP_PORT:-28080}:80`），共享 `php-socket` 卷，`camera-net` 桥接网络。
  - `nginx/default.conf`：`root /var/www/html`、`try_files … /index.php?$query_string`、`fastcgi_pass unix:/var/run/php/php-fpm.sock`；额外封掉 `config.php`、`^/src/`、敏感扩展名与点文件，并对 `^/assets/.*\.(js|css)$` 加 `Cache-Control: no-cache`。
  - `.env.example`：**列出全部可覆盖变量**（32 个 `GALLERY_*` + 主机路径 + 端口），复制为 `.env` 按需修改；每个变量在 compose 里都写成 `${VAR:-默认值}`。
  - `secrets/password_hash.txt.example` + compose 的 `secrets:` 段：密码哈希以**文件**挂进容器（`GALLERY_PASSWORD_HASH_FILE=/run/secrets/gallery_password_hash`）。
  - 容器内的挂载点名不是固定的，所以**必须显式配置**，不要依赖默认值：

    ```yaml
    environment:
      - GALLERY_PASSWORD_HASH_FILE=/run/secrets/gallery_password_hash  # 见下方"为什么用文件"
      - GALLERY_CAPTURES_DIR=${GALLERY_CAPTURES_DIR:-/var/www/capture} # 容器内挂载点，名字随意
      - GALLERY_HEALTH_FILE=${GALLERY_HEALTH_FILE:-/var/www/status.json}
      - GALLERY_IMAGE_MODE=${GALLERY_IMAGE_MODE:-proxy}                # 默认；图片经 image.php 鉴权输出
      - GALLERY_CACHE_DIR=${GALLERY_CACHE_DIR:-/tmp/gallery-cache}     # 代码目录 :ro，缓存必须另指可写路径
    volumes:
      - ${GALLERY_CAPTURE_HOST_DIR:-/opt/camera/capture}:/var/www/capture:ro   # 只读（本 UI 绝不写照片库）
      - ${GALLERY_STATUS_HOST_FILE:-/opt/camera/status.json}:/var/www/status.json:ro
    ```

  - 挂载点叫什么都可以（`/data/captures`、`/mnt/photos`…），只要与 `GALLERY_CAPTURES_DIR` 一致。`image_mode=proxy` 时它是**唯一需要的路径配置**。
  - **为什么密码走文件而不是环境变量**：compose 会对 `.env` 做变量插值，bcrypt 哈希里的 `$` 会被吞掉——`$2y$12$abc…` 会被解析成残缺的 `$$2y$$12`（尾部丢失），表现为「密码明明对却登不进去」。`secrets` 直接挂文件、不经过任何插值，因此安全。生成方式：`mkdir -p secrets && php -r "echo password_hash('你的强密码', PASSWORD_DEFAULT), PHP_EOL;" > secrets/password_hash.txt`（真实文件已 gitignore，只提交 `.example`）。
  - **代码目录挂 `:ro`**：本 UI 不写代码目录，因此缩略图/统计缓存**必须**由 `GALLERY_CACHE_DIR` 指向容器内可写路径（默认 `/tmp/gallery-cache`）。
  - 卷没挂上或路径写错时，**运维面板会直接报**「照片库目录不存在：<路径>」并把「照片库」一行标黄，而不是只显示"没有照片"让人猜。
  - **nginx 必须让浏览器重新校验静态资源**：ES module 之间是**裸导入**（`import './theme.js'`），无法像 `app.js?v=` 那样逐个带版本号，升级后浏览器可能仍在用旧模块（表现为"改了没生效"）。`nginx/default.conf` 里已加：

    ```nginx
    location ~* ^/assets/.*\.(js|css)$ {
        add_header Cache-Control "no-cache";   # 强制协商缓存；有 ETag，未变仍是 304
    }
    ```

  - 页面/接口响应已带 `Cache-Control: no-store`，不要在 nginx 层给 `index.php` / `api.php` / `image.php` 加缓存。
- 与抓拍/合成端解耦：本 UI **只读**，绝不写入照片库；`merge/ffmpeg-script.sh` 也独立消费同一目录。

---

## 12. 本地开发与验证

```bash
# 直接以 web-ui 为根启动（PHP 内置服务器；生产请用 Apache/nginx）
cd web-ui
GALLERY_CAPTURES_DIR=/path/to/real/or/demo/captures \
  php -S 127.0.0.1:8099 -t .

# 打开 http://127.0.0.1:8099/login.php
```

- 无热重载/打包：改 CSS/JS 后刷新即可（注意浏览器缓存，可强制刷新）。
- 页面**不得新增内联 `<script>`/`style`**：CSP 是 `script-src 'self'`，没有 nonce 兜底，内联脚本会被直接拦截（这也是主题改为服务端渲染的原因）。
- 语法自检：`php -l <file>`（对 `src/**` 与根目录各入口逐一执行）。
- 已完成的验证基线：22 个 PHP 文件 `php -l` 全部通过；`dom.js` 引用的 71 个 id 与 `index.php` 完全一致；curl 端到端 29/29 通过（鉴权/401、各 action 数据、`count`、`recent_days` 连续 31 天补 0、`getOpsOverview` 安全字段 + 聚合 warnings、图片字节一致、缩略图、下载头、缓存头、CSP/`X-Robots-Tag`/robots.txt、三类穿越拦截、登出 CSRF、`password_hash` 登录且旧明文被拒、资源版本号、**主题服务端渲染**：`data-theme`+`data-accent`+`color-scheme` meta 随 cookie 变化、非法配色回退 `blue`、外观面板 6 配色 × 2 模式、旧 `#themeToggle` 已移除）；**12 组「深浅 × 配色」令牌**用 `getComputedStyle` 逐组核对（暗色 `--bg #07080b`、浅色 `#f5f6f9`，`--on-accent` 各自正确）；**配置项逐个实测**（`GALLERY_DEFAULT_VIEW=ops`/`SLIDESHOW_SPEED=8`/`DOWNLOAD_ENABLED=false`/`MONITOR_MAX_INTERVAL=20000` 重启后，data 属性、默认落运维页、无下载按钮、查看器起始 8x、`&download=1` 变 `inline` 均符合预期）；浏览器逐项实测零 console 报错。

---

## 13. 与旧版差异摘要

- `index.php`：由 **~2000 行单文件**（含 ~1100 行内联 CSS + ~1100 行内联 JS）→ **骨架 HTML + 独立 `assets/`**，并全面移除外链 CDN。
- 后端：`gallery_api.php` 单体 → `api.php` + `src/`（Config / PhotoLibrary / Media / Thumbnailer / Api / Security / Support）分层。
- 隐私：新增**鉴权图片通道 `image.php`**（旧版可就已知 URL 直接取图）；移除第三方 CDN 请求。
- 交互：日期选择由 flatpickr（CDN）改为**原生 `<input type="date">`**；新增 min/max 上下界与选择后校验。
- 结构：两个重复的弹层合并为**统一 viewer**；面包屑/返回逻辑收敛进 `gallery.js` 状态机。
- 修复：旧版缩略图 URL 指向 `/tmp` 必然 404 的 bug；旧版 `index.php` 中大量死代码与未使用 endpoint（`getLatestMeta`）。
- 缓存/限流：`glob` 扫描 → 单次扫描 + 文件缓存；新增登录限流与 API 限流。
- 视觉：由「浅色工具风」整体重做为**暗色优先 · 影像优先**的设计系统（令牌集中、瓦片 16:9 + scrim 标签 + hover 抬升 + 骨架屏）；登录页同步重做。
- 动效：新增 `anim.js` —— 错峰入场、图片淡入、弹层缩放淡入、换图过渡、数字滚动、仪表/柱状生长、滚动揭示，并全局尊重 `prefers-reduced-motion`。
- 新增**只读运维面板**（顶栏「运维」页签）：采集服务健康、磁盘仪表、照片库统计与近 14 天柱状图；对应新 action `getOpsOverview` 与 `health_file` 等新配置项。
- 交互补齐：自建日历（禁用无照片日期）、查看器时间轴 + 自动播放 + 快捷键 + 拍摄间距、层级统计与 24 小时活动条、监控同宽/面包屑/最大化实时刷新。
- 主题：改为**服务端按 cookie 渲染 `data-theme` / `data-accent`**，并在 `<head>` 服务端渲染 `<meta name="color-scheme">`，彻底消除刷新闪烁；客户端只做镜像、不再改写服务端值。新增 **6 套配色**（深浅各一套，含 `--on-accent`），顶栏改为「外观」面板（模式 + 配色）。顺带移除了唯一需要 nonce 的内联脚本，CSP 收紧为 `script-src 'self'`。
- 安全加固：`X-Robots-Tag` + `noindex` + `robots.txt`、host-only / `__Host-` cookie、`trust_proxy` 门控、图片 MIME 校验、统计刷新限流、运维「安全」卡与告警横幅。
- 修复：时间轴/时长类展示曾用浏览器本地时区还原 `epoch`，当服务器与浏览器时区不一致时会整体偏移（已改为文件名派生值）；以及监控画面因漏绑淡入回调而恒为不可见的 bug。
- 认证：**移除明文密码**，改为 `password_hash`（bcrypt）；开源前进一步**清空仓库内的默认密码**（`config.php` 的 `password_hash` 为空）并新增根目录 `.gitignore`，使克隆后的默认状态是「无法登录」而不是「有个已知密码」。
- 体验：工具条重做为**单行**（日期只出现一次、统计并入同行、去掉重复的 status 文案）；查看器补齐 `1x/2x/4x` 速度分段、时间轴只显示时刻、进度条移入独立留白带（不再压住图片）；修复查看器图片高于舞台导致溢出的布局 bug。
- 工程：静态资源加 `?v=mtime`，杜绝浏览器沿用旧 JS/CSS 造成的"改了没生效"错觉。
- 配置：`config.php` 重写为**完整模板**——补齐了此前「能用但没文档」的十几个键（缓存/缩略图/限流/会话/时区等），并把 `captures_dir` 说明白：**它就是 proxy 与 direct 共用的唯一图片目录**（proxy 下由 `image.php` 读取，无需其他配置）。另新增 6 个可自定义项：`default_view`、`slideshow_speed`、`download_enabled`、`monitor_initial_interval`、`monitor_min_interval`、`monitor_max_interval`，经 `<body data-*>` 传给前端。
- 播放节奏：改为**贴合真实抓拍间隔**（`每帧 = clamp(真实间隔, ≤6s) ÷ 倍速`，1x 即"实时"），倍速档位扩到 `1x…32x` 六个并用弹出菜单展示每帧时长。
- 运维面板：**存储与安全合并为一张卡**（行数精简到最关键的 4 条），三张卡等高；「近 14 天每日张数」重做为**连续 14 天时间轴**（含 0 张的日子用虚线槽表示），柱顶显示张数、末日必标注、右上角显示峰值。
- 主题：顶栏改为**带文字的按钮**（`☾ 深色` / `☀ 浅色`），不再只靠图标暗示。
- 监控：舞台用 `aspect-ratio: 16/9` + `--surface-2` 底色，**消除画面四周的黑边**。
- 运维面板：图表窗口 `14 → 31` 天并改为 **3 列横向日行**（含 0 张的日子保留空槽）；「存储与安全」卡补齐行数，并按 `存储` / `安全` 两个小标题分组（共 10 行 + 磁盘仪表）。面板网格改为两列 + 图表整行通栏（`.panel-wide`）。
- 外观：顶栏改为**「外观」弹出面板**（模式：浅色/深色 + 配色：6 色**单行 6 列网格**），取代原来的纯图标切换；配色与深浅互不影响。
- 修复：**「深色模式下刷新丢失深色模式」** —— 根因是 `initTheme()` 曾把 `<html>` 上的值镜像回 cookie，一旦加载早期被外部脚本（扩展/内嵌预览）改成 `light`，就会把用户的 `dark` 永久覆盖。现改为 **cookie 是唯一权威**：服务端按 cookie 渲染，客户端只在 cookie 与 DOM 不一致时按 cookie 纠正 DOM，绝不反向写。已用 `curl -H 'Cookie: gallery_theme=dark'` 验证 `data-theme="dark"` + `color-scheme: dark` 随 cookie 变化。
- 部署：新增与 `web-ui/` 同级的 **`docker-compose.yml` + `nginx/default.conf` + `.env.example` + `secrets/` 模板**，覆盖全部 `GALLERY_*` 变量（`${VAR:-默认值}` 形式）；并新增配置 `password_hash_file`（容器用 secret 挂载，避免 compose 吞掉 bcrypt 里的 `$`）。

---

## 14. 已知限制与后续想法

- **日期选择**：自建日历已实现「无照片日期不可选」；可用日期集合来自 `getAvailableDates`（5 分钟缓存），超大库首次打开日历时该列表会略慢。
- **缩略图**：未处理 EXIF 旋转；若抓拍设备存在旋转场景需补充。
- **时间轴**：使用 range 滑块而非缩略图胶片 —— 任意数据量下都轻量，但没有缩略图预览。
- **时区**：展示已走文件名（正确）；若要让 `epoch` 本身也准确（例如将来做跨时区调度），请设置 `timezone` 配置。
- **缓存位置**：默认在系统临时目录，重启即清空——对缩略图可接受，对索引缓存仅偶尔多一次扫描。
- **鉴权模型**：单密码 + 会话（无多用户）。若未来要多用户/只读分享链接，建议引入带签名的临时 URL，而非放开 `captures/` 直链。
- **大库扩展**：若单日照片量级远超当前假设（数万张），可考虑为日索引加持久化缓存（以目录 mtime 失效）。
