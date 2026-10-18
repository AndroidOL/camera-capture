"""
嵌入式相机采集服务（v3.0.0，长期运行版）。

设计目标
--------
- 无 GUI：本服务不创建窗口、不调用 imshow/waitKey，因此不存在“窗口失焦导致采集中断”。
  摄像头只通过 OpenCV V4L2 后端访问，由 systemd 管理生命周期。
- 图像完整：统一将 V4L2 返回的 YUYV 原始帧转换为 BGR，并按配置分辨率做尺寸校验；
  无法确认格式的帧直接丢弃，不保存可能错位/撕裂的图像。
- 长期稳定：相机定期释放重连、内存监控、周期性 gc、健康快照、systemd watchdog、
  分级退避、原子写 health.json。
- 可维护：配置加载、相机控制、帧处理、存储、磁盘清理、健康监控彼此分离。

兼容性
------
- 保留原有 CLI：start / stop / status / foreground。
- 保留 --use-config / --config / --pidfile / --logdir / --loglevel。
- 保留原有目录结构、文件命名、相似度算法和时间表语义。
- 未启用 --use-config 时继续使用内置默认值，行为与 v2.0.1 保持一致，
  但新增了默认每日相机重连、内存监控和健康指标。
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import logging.handlers
import os
import random
import resource
import shutil
import signal
import socket
import sys
import time
import traceback
from collections import deque
from datetime import datetime, time as dt_time, timedelta
from threading import Event

import cv2
import numpy as np

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


# ---------------------------------------------------------------------------
# Script information
# ---------------------------------------------------------------------------

SCRIPT_VERSION = "3.0.0"
SCRIPT_NAME = os.path.basename(__file__)


# ---------------------------------------------------------------------------
# Built-in defaults (used when --use-config is not supplied)
# ---------------------------------------------------------------------------

BASE_APP_DIR = "/opt/camera/"
LOG_DIR = os.path.join(BASE_APP_DIR, "logs")
PID_FILE_PATH = f"/var/run/{SCRIPT_NAME.replace('.py', '.pid')}"
IMAGE_SAVE_BASE_DIR = "/opt/camera/captures"

LOG_LEVEL_CONFIG = "INFO"
LOG_FILE_NAME = "image_capture"
LOG_ROTATE_WHEN = "midnight"
LOG_ROTATE_INTERVAL = 1
LOG_ROTATE_BACKUP_COUNT = 30

# 设备路径优先使用稳定的 by-id 路径；不要依赖 /dev/videoN 编号。
DEFAULT_CAMERA_DEVICE_PATH = (
    "/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._UGREEN_Camera_2K_SN0001-video-index0"
)
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
# 该相机挂在 USB 2.0 (480M) 总线上。YUYV 1080p 的原始带宽接近上限，
# 长时间运行会出现偶发横向撕裂（frame tearing）。MJPG 由相机内部压缩，
# 带宽低得多，OpenCV 解码后仍是完整 BGR 帧；实测 1920x1080@30 无撕裂。
REQUESTED_FOURCC = "MJPG"
JPEG_SAVE_QUALITY = 90

# 分时采集策略（内置默认，和 config.yaml 的 capture_schedule 对齐）：
#   00:00-05:00  10s  深夜，降低无意义抓拍和磁盘占用
#   05:00-09:00   5s  起床/早间活动
#   09:00-11:30   2s  白天活动高峰
#   11:30-14:00   5s  午休/低活动
#   14:00-21:30   2s  下午到晚间活动高峰
#   21:30-23:00   5s  准备休息
#   23:00-24:00  10s  深夜
CAPTURE_SCHEDULE_CONFIG = [
    {"end_time_exclusive": dt_time(5, 0), "interval_seconds": 10},
    {"end_time_exclusive": dt_time(9, 0), "interval_seconds": 5},
    {"end_time_exclusive": dt_time(11, 30), "interval_seconds": 2},
    {"end_time_exclusive": dt_time(14, 0), "interval_seconds": 5},
    {"end_time_exclusive": dt_time(21, 30), "interval_seconds": 2},
    {"end_time_exclusive": dt_time(23, 0), "interval_seconds": 5},
]
DEFAULT_INTERVAL_LATE_NIGHT = 10

PARAMETER_SET_RETRIES = 3
PARAMETER_SET_DELAY_SECONDS = 0.5
CAMERA_INIT_FAILURE_MAX_CONSECUTIVE = 5
CAMERA_INIT_RETRY_DELAY_SECONDS = 15
CAMERA_INIT_LONG_BACKOFF_SECONDS = 300
CAMERA_CHECK_DEV_NODE = True

MAX_CONSECUTIVE_READ_FAILURES = 10
READ_FAILURE_LONG_BACKOFF_SECONDS = 60
FRAME_READ_ERROR_RETRY_DELAY_SECONDS = 5
LOG_EVERY_N_READ_FAILURES = 5

MAX_CONSECUTIVE_IMWRITE_FAILURES = 5
IMWRITE_FAILURE_BACKOFF_SECONDS = 60

ENABLE_TIMESTAMP = True
TIMESTAMP_FORMAT = "%Y/%m/%d %H:%M:%S"

IMAGE_STORAGE_MONITOR_PATH = IMAGE_SAVE_BASE_DIR
IMAGE_STORAGE_MAX_USAGE_PERCENT = 85
IMAGE_STORAGE_CLEANUP_BATCH_DAYS = 1
DISK_CHECK_INTERVAL_SECONDS = 14400
HEARTBEAT_INTERVAL_SECONDS = 300

MIN_JPEG_SAVE_SIZE_BYTES = 0
IMAGE_SAVE_FALLBACK_DIR: str | None = None

# --- 新增的长期运行参数（均可通过 YAML 覆盖） ---
FRAME_FLUSH_GRABS = 4                 # 每次 read 前丢弃的旧帧数量
CAMERA_OPEN_TIMEOUT_MSEC = 5000       # OpenCV 支持时生效
CAMERA_READ_TIMEOUT_MSEC = 5000       # 防止 USB 读帧永久阻塞
CAMERA_RECYCLE_SECONDS = 86400        # 每 24h 释放并重连一次；0=禁用
MEMORY_WARN_MB = 600                  # 软告警阈值
MEMORY_LIMIT_MB = 800                 # 触发相机回收/强 gc 的阈值
GC_INTERVAL_SECONDS = 3600            # 周期性 gc 间隔
HEALTH_DUMP_INTERVAL_SECONDS = 60     # health.json 写入间隔
PROTECT_RECENT_DAYS = 1               # 磁盘清理时至少保留最近 N 天

# 相似度比较参数（差分 + 形态学 + 轮廓面积比例）
DEFAULT_CONTOUR_PIXEL_THRESHOLD = 25
DEFAULT_CONTOUR_KERNEL_SIZE = (5, 5)
DEFAULT_CONTOUR_DILATION_ITERATIONS = 2
DEFAULT_CONTOUR_MIN_AREA_FILTER = 50.0
SIMILARITY_THRESHOLD_PERCENT_INT = 100  # 100 = 1.0%
SIMILARITY_MAX_WIDTH = 640
CONTOUR_KERNEL = np.ones(DEFAULT_CONTOUR_KERNEL_SIZE, np.uint8)


# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

logger: logging.Logger | None = None
shutdown_event = Event()
reload_event = Event()
CONFIG_PATH = "/opt/camera/config.yaml"
CONFIG_ENABLED = False


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def get_fourcc_str(fourcc_int: int) -> str:
    """将 OpenCV 的四字符码整数转换为可读字符串。"""
    if not fourcc_int:
        return "N/A (0)"
    try:
        return "".join(chr((fourcc_int >> (8 * i)) & 0xFF) for i in range(4)).strip()
    except Exception:
        return f"Unknown ({hex(fourcc_int)})"


def get_rss_mb() -> tuple[float, float]:
    """返回 (当前 RSS, 峰值 RSS)，单位 MB。

    优先读取 /proc/self/status；非 Linux 平台回退到 resource。
    """
    rss_mb = 0.0
    peak_mb = 0.0
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    rss_mb = float(line.split()[1]) / 1024.0
                elif line.startswith("VmHWM:"):
                    peak_mb = float(line.split()[1]) / 1024.0
    except Exception:
        pass

    if rss_mb <= 0.0:
        try:
            usage = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            # macOS: bytes；Linux: KiB
            if sys.platform == "darwin":
                rss_mb = usage / (1024.0 * 1024.0)
                peak_mb = rss_mb
            else:
                rss_mb = usage / 1024.0
                peak_mb = rss_mb
        except Exception:
            pass

    return rss_mb, max(peak_mb, rss_mb)


def _safe_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# systemd watchdog / sd_notify
# ---------------------------------------------------------------------------

class Watchdog:
    """轻量 sd_notify + systemd watchdog 客户端。

    - 手工运行（无 NOTIFY_SOCKET）时所有操作都是 no-op。
    - systemd 使用 Type=notify + WatchdogSec 时，本类负责发送 READY=1 和 WATCHDOG=1。
    - wait() 会把长等待切片，避免长时间退避期间被 systemd 判定为失联。
    """

    def __init__(self) -> None:
        self.socket_path = os.environ.get("NOTIFY_SOCKET") or ""
        usec = os.environ.get("WATCHDOG_USEC")
        self.interval = (_safe_int(usec, 0) / 1_000_000.0) if usec else 0.0
        self.last_ping = 0.0

    def _notify(self, state: str) -> None:
        if not self.socket_path:
            return
        address = self.socket_path
        if address.startswith("@"):
            address = "\0" + address[1:]
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.connect(address)
                sock.sendall(state.encode("utf-8"))
        except Exception:
            # 通知失败不能影响采集主流程
            pass

    def ready(self) -> None:
        self._notify("READY=1")
        self.ping(force=True)

    def ping(self, force: bool = False) -> None:
        if not self.socket_path:
            return
        now = time.monotonic()
        if force or (self.interval > 0 and now - self.last_ping >= self.interval / 2.0):
            self._notify("WATCHDOG=1")
            self.last_ping = now

    def wait(self, seconds: float) -> None:
        """可被 SIGTERM 打断的等待，同时保持 watchdog 心跳。"""
        remaining = max(0.0, float(seconds))
        deadline = time.monotonic() + remaining
        while not shutdown_event.is_set():
            left = deadline - time.monotonic()
            if left <= 0:
                break
            chunk = min(left, 1.0 if self.interval > 0 else 5.0)
            if shutdown_event.wait(chunk):
                break
            self.ping()

    def stopping(self) -> None:
        self._notify("STOPPING=1")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging_system(
    log_dir: str,
    log_file_prefix: str,
    level_str: str,
    when: str,
    interval: int,
    backup_count: int,
) -> logging.Logger:
    """初始化控制台 + 轮转文件的日志系统。"""
    global logger
    numeric_level = getattr(logging, level_str.upper(), logging.INFO)

    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as exc:
            print(f"CRITICAL: Failed to create log directory {log_dir}: {exc}", file=sys.stderr)
            sys.exit(1)

    logger = logging.getLogger(SCRIPT_NAME)
    logger.setLevel(numeric_level)
    logger.propagate = False
    logging.raiseExceptions = False

    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] [%(process)d] [%(threadName)s] "
        "[%(name)s:%(funcName)s:%(lineno)d] %(message)s"
    )

    log_filepath = os.path.join(log_dir, f"{log_file_prefix}.log")
    try:
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_filepath,
            when=when,
            interval=interval,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as exc:
        print(f"WARNING: Failed to initialize file logger at {log_filepath}: {exc}", file=sys.stderr)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.info("[LOG] 初始化完成，级别: %s，文件: %s", level_str, log_filepath)
    return logger


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

class ServiceState:
    """服务运行期可变状态；不包含配置。"""

    def __init__(self) -> None:
        self.consecutive_imwrite_failures = 0
        self.consecutive_read_failures = 0
        self.last_significant_frame: np.ndarray | None = None
        self.total_disk_cleanup_batches = 0
        self.last_heartbeat_monotonic = 0.0
        self.last_health_dump_monotonic = 0.0
        self.last_saved_filepath: str | None = None
        self.processing_times_ms: deque[float] = deque(maxlen=120)

        self.effective_fourcc = "NOT_SET_INITIALLY"
        self.boot_id = f"{int(time.time())}-{random.randint(1000, 9999)}"
        self.started_monotonic = time.monotonic()

        self.applied_camera_device: str | None = None
        self.applied_width: int | None = None
        self.applied_height: int | None = None
        self.applied_requested_fourcc: str | None = None

        # 长期运行统计
        self.frames_total = 0
        self.frames_saved = 0
        self.frames_skipped = 0
        self.camera_reopens = 0
        self.camera_init_failures = 0
        self.gc_collections = 0
        self.frame_resizes = 0
        self.memory_pressure_events = 0
        self.last_rss_mb = 0.0
        self.peak_rss_mb = 0.0
        self.last_disk_percent = -1.0
        self.last_memory_warn_monotonic = 0.0
        self.last_gc_monotonic = time.monotonic()


# ---------------------------------------------------------------------------
# YAML configuration
# ---------------------------------------------------------------------------

def load_and_apply_yaml_config(config_path: str, runtime_reload: bool = False) -> None:
    """加载 YAML 并覆盖内置参数；未启用或加载失败时保持当前值。"""
    global DEFAULT_CAMERA_DEVICE_PATH, DEFAULT_WIDTH, DEFAULT_HEIGHT, REQUESTED_FOURCC
    global JPEG_SAVE_QUALITY, IMAGE_SAVE_BASE_DIR, LOG_DIR, PID_FILE_PATH
    global CAPTURE_SCHEDULE_CONFIG, DEFAULT_INTERVAL_LATE_NIGHT
    global IMAGE_STORAGE_MONITOR_PATH, IMAGE_STORAGE_MAX_USAGE_PERCENT
    global DISK_CHECK_INTERVAL_SECONDS, IMAGE_STORAGE_CLEANUP_BATCH_DAYS
    global SIMILARITY_THRESHOLD_PERCENT_INT, MIN_JPEG_SAVE_SIZE_BYTES
    global IMAGE_SAVE_FALLBACK_DIR, LOG_LEVEL_CONFIG
    global LOG_ROTATE_WHEN, LOG_ROTATE_INTERVAL, LOG_ROTATE_BACKUP_COUNT
    global BASE_APP_DIR, LOG_FILE_NAME, MAX_CONSECUTIVE_IMWRITE_FAILURES
    global ENABLE_TIMESTAMP, TIMESTAMP_FORMAT
    global PARAMETER_SET_RETRIES, PARAMETER_SET_DELAY_SECONDS
    global CAMERA_INIT_FAILURE_MAX_CONSECUTIVE, CAMERA_INIT_RETRY_DELAY_SECONDS
    global CAMERA_INIT_LONG_BACKOFF_SECONDS, CAMERA_CHECK_DEV_NODE
    global MAX_CONSECUTIVE_READ_FAILURES, READ_FAILURE_LONG_BACKOFF_SECONDS
    global FRAME_READ_ERROR_RETRY_DELAY_SECONDS
    global FRAME_FLUSH_GRABS, CAMERA_OPEN_TIMEOUT_MSEC, CAMERA_READ_TIMEOUT_MSEC
    global CAMERA_RECYCLE_SECONDS, MEMORY_WARN_MB, MEMORY_LIMIT_MB
    global GC_INTERVAL_SECONDS, HEALTH_DUMP_INTERVAL_SECONDS, PROTECT_RECENT_DAYS

    if yaml is None:
        if logger:
            logger.warning("未安装 PyYAML，跳过外部配置加载。")
        return

    try:
        if not os.path.isfile(config_path):
            if logger:
                logger.info("未找到配置文件 %s，继续使用内置配置。", config_path)
            return

        with open(config_path, "r", encoding="utf-8") as fh:
            raw_cfg = yaml.safe_load(fh) or {}

        flat = raw_cfg if isinstance(raw_cfg, dict) else {}
        nested = raw_cfg if isinstance(raw_cfg, dict) else {}

        def _resolve(text):
            if not isinstance(text, str):
                return text
            try:
                base = str(nested.get("paths", {}).get("base_app_dir", BASE_APP_DIR))
                image_raw = str(
                    nested.get("paths", {}).get("image_save_base_dir", IMAGE_SAVE_BASE_DIR)
                )
                # 先解析 image_save_base_dir 里的 {base_app_dir}，再解析 monitor_path
                # 里的 {image_save_base_dir}，避免留下未展开的占位符。
                image_base = image_raw.format(base_app_dir=base)
                return text.format(base_app_dir=base, image_save_base_dir=image_base)
            except Exception:
                return text

        # --- paths ---
        paths_cfg = nested.get("paths", {}) if isinstance(nested.get("paths"), dict) else {}
        base_val = _resolve(paths_cfg.get("base_app_dir", BASE_APP_DIR))
        image_base_val = _resolve(paths_cfg.get("image_save_base_dir", IMAGE_SAVE_BASE_DIR))
        fallback_val = _resolve(paths_cfg.get("image_save_fallback_dir", IMAGE_SAVE_FALLBACK_DIR or ""))
        log_dir_val = _resolve(paths_cfg.get("log_dir", LOG_DIR))
        pid_val = _resolve(paths_cfg.get("pid_file", PID_FILE_PATH))

        if not runtime_reload:
            BASE_APP_DIR = str(base_val)
            LOG_DIR = str(log_dir_val)
            PID_FILE_PATH = str(pid_val)

        IMAGE_SAVE_BASE_DIR = str(image_base_val)
        IMAGE_SAVE_FALLBACK_DIR = str(fallback_val) if fallback_val else None

        # --- logging ---
        logging_cfg = nested.get("logging", {}) if isinstance(nested.get("logging"), dict) else {}
        LOG_LEVEL_CONFIG = str(logging_cfg.get("level", LOG_LEVEL_CONFIG))
        tmp_name = logging_cfg.get("log_file_name")
        if isinstance(tmp_name, str) and tmp_name.strip():
            LOG_FILE_NAME = tmp_name.strip().replace(".log", "").replace("/", "_")
        LOG_ROTATE_WHEN = str(logging_cfg.get("rotate_when", LOG_ROTATE_WHEN))
        LOG_ROTATE_INTERVAL = _safe_int(logging_cfg.get("rotate_interval"), LOG_ROTATE_INTERVAL)
        LOG_ROTATE_BACKUP_COUNT = _safe_int(
            logging_cfg.get("rotate_backup_count"), LOG_ROTATE_BACKUP_COUNT
        )

        # --- camera ---
        cam_cfg = nested.get("camera", {}) if isinstance(nested.get("camera"), dict) else {}
        DEFAULT_CAMERA_DEVICE_PATH = str(
            cam_cfg.get("device", flat.get("camera_device", DEFAULT_CAMERA_DEVICE_PATH))
        )
        DEFAULT_WIDTH = max(1, _safe_int(cam_cfg.get("width", flat.get("width")), DEFAULT_WIDTH))
        DEFAULT_HEIGHT = max(
            1, _safe_int(cam_cfg.get("height", flat.get("height")), DEFAULT_HEIGHT)
        )
        REQUESTED_FOURCC = str(
            cam_cfg.get("requested_fourcc", flat.get("fourcc", REQUESTED_FOURCC))
        )
        JPEG_SAVE_QUALITY = max(
            1, min(100, _safe_int(cam_cfg.get("jpeg_quality", flat.get("jpeg_quality")), JPEG_SAVE_QUALITY))
        )
        PARAMETER_SET_RETRIES = max(
            1, _safe_int(cam_cfg.get("parameter_set_retries"), PARAMETER_SET_RETRIES)
        )
        PARAMETER_SET_DELAY_SECONDS = max(
            0.0, _safe_float(cam_cfg.get("parameter_set_delay_seconds"), PARAMETER_SET_DELAY_SECONDS)
        )
        CAMERA_INIT_FAILURE_MAX_CONSECUTIVE = max(
            1,
            _safe_int(cam_cfg.get("init_failure_max_consecutive"), CAMERA_INIT_FAILURE_MAX_CONSECUTIVE),
        )
        CAMERA_INIT_RETRY_DELAY_SECONDS = max(
            1,
            _safe_int(cam_cfg.get("init_retry_delay_seconds"), CAMERA_INIT_RETRY_DELAY_SECONDS),
        )
        CAMERA_INIT_LONG_BACKOFF_SECONDS = max(
            1,
            _safe_int(cam_cfg.get("init_long_backoff_seconds"), CAMERA_INIT_LONG_BACKOFF_SECONDS),
        )
        CAMERA_CHECK_DEV_NODE = bool(cam_cfg.get("check_dev_node", CAMERA_CHECK_DEV_NODE))
        MAX_CONSECUTIVE_READ_FAILURES = max(
            1, _safe_int(cam_cfg.get("max_consecutive_read_failures"), MAX_CONSECUTIVE_READ_FAILURES)
        )
        READ_FAILURE_LONG_BACKOFF_SECONDS = max(
            1,
            _safe_int(
                cam_cfg.get("read_failure_long_backoff_seconds"),
                READ_FAILURE_LONG_BACKOFF_SECONDS,
            ),
        )
        FRAME_READ_ERROR_RETRY_DELAY_SECONDS = max(
            0,
            _safe_int(
                cam_cfg.get("frame_read_error_retry_delay_seconds"),
                FRAME_READ_ERROR_RETRY_DELAY_SECONDS,
            ),
        )
        FRAME_FLUSH_GRABS = max(
            1, _safe_int(cam_cfg.get("frame_flush_grabs"), FRAME_FLUSH_GRABS)
        )
        CAMERA_OPEN_TIMEOUT_MSEC = max(
            0, _safe_int(cam_cfg.get("open_timeout_msec"), CAMERA_OPEN_TIMEOUT_MSEC)
        )
        CAMERA_READ_TIMEOUT_MSEC = max(
            0, _safe_int(cam_cfg.get("read_timeout_msec"), CAMERA_READ_TIMEOUT_MSEC)
        )

        # --- schedule ---
        schedule_new = []
        sched_cfg = nested.get("capture_schedule", {}) if isinstance(nested.get("capture_schedule"), dict) else {}
        rules = sched_cfg.get("schedule_rules")
        if isinstance(rules, list):
            for item in rules:
                try:
                    end_str = str(item.get("end_time_exclusive", "00:00"))
                    parts = [int(p) for p in end_str.split(":")]
                    while len(parts) < 3:
                        parts.append(0)
                    schedule_new.append(
                        {
                            "end_time_exclusive": dt_time(parts[0], parts[1], parts[2]),
                            "interval_seconds": float(item.get("interval_seconds", 2.5)),
                        }
                    )
                except Exception:
                    continue

        legacy_schedule = flat.get("schedule")
        if isinstance(legacy_schedule, list):
            for item in legacy_schedule:
                try:
                    hh, mm = str(item.get("end", "00:00")).split(":")
                    schedule_new.append(
                        {
                            "end_time_exclusive": dt_time(int(hh), int(mm)),
                            "interval_seconds": float(item.get("interval_seconds", 2.5)),
                        }
                    )
                except Exception:
                    continue

        if schedule_new:
            CAPTURE_SCHEDULE_CONFIG = schedule_new
        DEFAULT_INTERVAL_LATE_NIGHT = max(
            0.1,
            _safe_float(
                sched_cfg.get("default_interval_late_night", flat.get("default_interval_late_night")),
                DEFAULT_INTERVAL_LATE_NIGHT,
            ),
        )

        # --- image processing ---
        img_cfg = nested.get("image_processing", {}) if isinstance(nested.get("image_processing"), dict) else {}
        ENABLE_TIMESTAMP = bool(img_cfg.get("enable_timestamp", ENABLE_TIMESTAMP))
        TIMESTAMP_FORMAT = str(img_cfg.get("timestamp_format", TIMESTAMP_FORMAT))

        # --- disk management ---
        disk_cfg = nested.get("disk_management", {}) if isinstance(nested.get("disk_management"), dict) else {}
        monitor_val = _resolve(disk_cfg.get("monitor_path", IMAGE_SAVE_BASE_DIR))
        IMAGE_STORAGE_MONITOR_PATH = str(monitor_val) if monitor_val else IMAGE_SAVE_BASE_DIR
        IMAGE_STORAGE_MAX_USAGE_PERCENT = max(
            1,
            min(
                99,
                _safe_int(
                    disk_cfg.get("max_usage_percent", flat.get("disk_usage_max_percent")),
                    IMAGE_STORAGE_MAX_USAGE_PERCENT,
                ),
            ),
        )
        IMAGE_STORAGE_CLEANUP_BATCH_DAYS = max(
            1,
            _safe_int(
                disk_cfg.get("cleanup_batch_days"),
                IMAGE_STORAGE_CLEANUP_BATCH_DAYS,
            ),
        )
        DISK_CHECK_INTERVAL_SECONDS = max(
            60,
            _safe_int(
                disk_cfg.get("check_interval_seconds"),
                DISK_CHECK_INTERVAL_SECONDS,
            ),
        )
        MIN_JPEG_SAVE_SIZE_BYTES = max(
            0,
            _safe_int(
                disk_cfg.get("min_jpeg_save_size_bytes"),
                MIN_JPEG_SAVE_SIZE_BYTES,
            ),
        )
        PROTECT_RECENT_DAYS = max(
            0,
            _safe_int(
                disk_cfg.get("protect_recent_days"),
                PROTECT_RECENT_DAYS,
            ),
        )

        # --- service ---
        svc_cfg = nested.get("service", {}) if isinstance(nested.get("service"), dict) else {}
        MAX_CONSECUTIVE_IMWRITE_FAILURES = max(
            1,
            _safe_int(
                svc_cfg.get("max_consecutive_imwrite_failures"),
                MAX_CONSECUTIVE_IMWRITE_FAILURES,
            ),
        )
        CAMERA_RECYCLE_SECONDS = max(
            0,
            _safe_int(svc_cfg.get("camera_recycle_seconds"), CAMERA_RECYCLE_SECONDS),
        )
        MEMORY_WARN_MB = max(
            0, _safe_int(svc_cfg.get("memory_warn_mb"), MEMORY_WARN_MB)
        )
        MEMORY_LIMIT_MB = max(
            0, _safe_int(svc_cfg.get("memory_limit_mb"), MEMORY_LIMIT_MB)
        )
        GC_INTERVAL_SECONDS = max(
            60, _safe_int(svc_cfg.get("gc_interval_seconds"), GC_INTERVAL_SECONDS)
        )
        HEALTH_DUMP_INTERVAL_SECONDS = max(
            30,
            _safe_int(
                svc_cfg.get("health_dump_interval_seconds"),
                HEALTH_DUMP_INTERVAL_SECONDS,
            ),
        )

        # --- similarity (legacy flat key) ---
        SIMILARITY_THRESHOLD_PERCENT_INT = max(
            0,
            _safe_int(
                flat.get("similarity_threshold_percent_int"),
                SIMILARITY_THRESHOLD_PERCENT_INT,
            ),
        )

        # 运行时热重载时同步日志级别
        if logger:
            level = getattr(logging, LOG_LEVEL_CONFIG.upper(), None)
            if isinstance(level, int):
                logger.setLevel(level)
                for handler in logger.handlers:
                    handler.setLevel(level)
            logger.info("配置文件已加载: %s", config_path)

    except Exception as exc:
        if logger:
            logger.error("加载配置文件失败 %s: %s", config_path, exc)
        else:
            print(f"WARNING: Failed to load config {config_path}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# PID / signals
# ---------------------------------------------------------------------------

def signal_hup_handler(signum, frame) -> None:
    try:
        if logger:
            logger.info("接收到 SIGHUP (%s)，请求重载配置。", signum)
    finally:
        reload_event.set()


def signal_term_handler(signum, frame) -> None:
    msg = f"接收到信号 {signal.Signals(signum).name} ({signum})，开始优雅停机..."
    if logger:
        logger.info(msg)
    else:
        print(msg, file=sys.stderr)
    shutdown_event.set()


def create_pid_file() -> None:
    if not PID_FILE_PATH:
        return
    try:
        pid = os.getpid()
        os.makedirs(os.path.dirname(PID_FILE_PATH), exist_ok=True)
        with open(PID_FILE_PATH, "w", encoding="utf-8") as fh:
            fh.write(str(pid))
        if logger:
            logger.info("[PID] 创建成功: %s (PID=%s)", PID_FILE_PATH, pid)
    except IOError as exc:
        if logger:
            logger.error("Unable to create PID file %s: %s", PID_FILE_PATH, exc)
        sys.exit(1)


def remove_pid_file() -> None:
    if not PID_FILE_PATH:
        return
    try:
        if os.path.exists(PID_FILE_PATH):
            os.remove(PID_FILE_PATH)
            if logger:
                logger.info("[PID] 已移除: %s", PID_FILE_PATH)
    except IOError as exc:
        if logger:
            logger.warning("Unable to remove PID file %s: %s", PID_FILE_PATH, exc)


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

def set_camera_parameter(
    cap: cv2.VideoCapture,
    prop_id: int,
    value,
    param_name: str,
    retries: int | None = None,
    delay: float | None = None,
) -> bool:
    """带重试地设置 V4L2/OpenCV 参数，并读回校验。"""
    retries = PARAMETER_SET_RETRIES if retries is None else retries
    delay = PARAMETER_SET_DELAY_SECONDS if delay is None else delay
    if logger:
        logger.info("尝试设置摄像头参数 %s 为 %s", param_name, value)

    requested_value_for_log = value
    for attempt in range(retries):
        try:
            cap.set(prop_id, value)
        except Exception as exc:
            if logger:
                logger.warning("设置 %s 时出现异常: %s", param_name, exc)

        if shutdown_event.wait(timeout=delay):
            return False

        try:
            actual_value = cap.get(prop_id)
        except Exception as exc:
            if logger:
                logger.warning("读取 %s 当前值时出现异常: %s", param_name, exc)
            actual_value = value

        if prop_id == cv2.CAP_PROP_FOURCC:
            target_int = int(value)
            actual_int = int(actual_value)
            is_set = actual_int == target_int
            requested_value_for_log = get_fourcc_str(target_int)
            actual_value_for_log = get_fourcc_str(actual_int)
        elif isinstance(value, float):
            is_set = abs(float(actual_value) - float(value)) < 1e-9
            actual_value_for_log = actual_value
        else:
            is_set = int(actual_value) == int(value)
            actual_value_for_log = actual_value

        if logger:
            logger.debug(
                "尝试 %s/%s 设置 %s: 请求 %s, 实际 %s",
                attempt + 1,
                retries,
                param_name,
                requested_value_for_log,
                actual_value_for_log,
            )
        if is_set:
            if logger:
                logger.info("参数 %s 成功设置为 %s", param_name, requested_value_for_log)
            return True
        time.sleep(0.1)

    try:
        final_actual = cap.get(prop_id)
        if prop_id == cv2.CAP_PROP_FOURCC:
            final_actual = get_fourcc_str(int(final_actual))
    except Exception:
        final_actual = "unknown"
    if logger:
        logger.warning(
            "无法将参数 %s 设置为 %s，经过 %s 次尝试后实际值为 %s",
            param_name,
            requested_value_for_log,
            retries,
            final_actual,
        )
    return False


class CameraController:
    """负责 V4L2 设备的打开、参数设置、读帧和释放。"""

    def __init__(self, state: ServiceState) -> None:
        self.state = state
        self.cap: cv2.VideoCapture | None = None
        self.effective_fourcc = "NOT_SET"
        self.opened_at = 0.0
        self.actual_width = 0
        self.actual_height = 0

    def is_open(self) -> bool:
        return self.cap is not None and self.cap.isOpened()

    def uptime(self) -> float:
        return time.monotonic() - self.opened_at if self.opened_at else 0.0

    def open(self) -> bool:
        device_path = DEFAULT_CAMERA_DEVICE_PATH
        if CAMERA_CHECK_DEV_NODE and not os.path.exists(device_path):
            if logger:
                logger.error("摄像头设备节点 %s 不存在。", device_path)
            return False

        real_path = os.path.realpath(device_path) if os.path.exists(device_path) else device_path
        if logger:
            logger.info("[CAMERA] 打开并初始化设备: %s (real=%s, V4L2)", device_path, real_path)

        if self.cap is not None:
            self.release()

        try:
            cap = cv2.VideoCapture(device_path, cv2.CAP_V4L2)
        except Exception as exc:
            if logger:
                logger.error("创建 VideoCapture 失败: %s", exc)
            return False

        if not cap.isOpened():
            if logger:
                logger.error("无法打开摄像头 %s", device_path)
            cap.release()
            return False

        if REQUESTED_FOURCC:
            target_fourcc = cv2.VideoWriter_fourcc(*REQUESTED_FOURCC)
            set_camera_parameter(cap, cv2.CAP_PROP_FOURCC, target_fourcc, "FOURCC")

        # FPS 只是期望值：MJPG 下相机可能固定为 30fps，实际高于请求值是正常的。
        # 采集节奏由时间表控制，不依赖摄像头 FPS，因此不做严格相等校验。
        try:
            cap.set(cv2.CAP_PROP_FPS, 10)
        except Exception:
            pass

        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        # 防止 USB 读帧永久阻塞；OpenCV 4.6 若不支持则 getattr 返回 None。
        for name, value in (
            ("CAP_PROP_OPEN_TIMEOUT_MSEC", CAMERA_OPEN_TIMEOUT_MSEC),
            ("CAP_PROP_READ_TIMEOUT_MSEC", CAMERA_READ_TIMEOUT_MSEC),
        ):
            prop = getattr(cv2, name, None)
            if prop is not None and value > 0:
                try:
                    cap.set(prop, value)
                except Exception:
                    pass

        if shutdown_event.is_set():
            cap.release()
            return False

        time.sleep(0.1)
        # UVC/V4L2 对单独设置 Width 的返回可能是中间值（例如 640），
        # 必须把 Width/Height 一起设置后再统一读回，避免误报失败。
        width_height_ok = False
        for attempt in range(PARAMETER_SET_RETRIES):
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, DEFAULT_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, DEFAULT_HEIGHT)
            except Exception as exc:
                if logger:
                    logger.warning("设置分辨率时异常: %s", exc)
            if shutdown_event.wait(timeout=PARAMETER_SET_DELAY_SECONDS):
                cap.release()
                return False
            try:
                probe_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                probe_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            except Exception:
                probe_w, probe_h = 0, 0
            if probe_w == DEFAULT_WIDTH and probe_h == DEFAULT_HEIGHT:
                width_height_ok = True
                break
            time.sleep(0.1)
        if not width_height_ok and logger:
            logger.warning(
                "分辨率设置未在 %s 次尝试内确认，当前读回 %sx%s；最终仍会按配置归一化。",
                PARAMETER_SET_RETRIES,
                probe_w,
                probe_h,
            )

        time.sleep(0.2)
        try:
            current_fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
        except Exception:
            current_fourcc_int = 0
        try:
            actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = float(cap.get(cv2.CAP_PROP_FPS))
        except Exception:
            actual_width, actual_height, actual_fps = DEFAULT_WIDTH, DEFAULT_HEIGHT, 0.0

        self.effective_fourcc = get_fourcc_str(current_fourcc_int)
        self.actual_width = actual_width
        self.actual_height = actual_height
        self.opened_at = time.monotonic()
        self.cap = cap

        self.state.effective_fourcc = self.effective_fourcc
        self.state.applied_camera_device = device_path
        self.state.applied_width = DEFAULT_WIDTH
        self.state.applied_height = DEFAULT_HEIGHT
        self.state.applied_requested_fourcc = REQUESTED_FOURCC

        if logger:
            logger.info(
                "[CAMERA] 初始化完成: 请求 FOURCC=%s, %sx%s；实际 FOURCC=%s (%s), %sx%s, FPS=%.2f",
                REQUESTED_FOURCC or "N/A",
                DEFAULT_WIDTH,
                DEFAULT_HEIGHT,
                self.effective_fourcc,
                hex(current_fourcc_int),
                actual_width,
                actual_height,
                actual_fps,
            )
            if actual_width != DEFAULT_WIDTH or actual_height != DEFAULT_HEIGHT:
                logger.error(
                    "摄像头实际分辨率 %sx%s 与请求的 %sx%s 不符；将按配置尺寸归一化。",
                    actual_width,
                    actual_height,
                    DEFAULT_WIDTH,
                    DEFAULT_HEIGHT,
                )
            if REQUESTED_FOURCC and self.effective_fourcc.upper() != REQUESTED_FOURCC.upper():
                logger.warning(
                    "请求的 FOURCC %s 未能精确设置，摄像头实际为 %s",
                    REQUESTED_FOURCC,
                    self.effective_fourcc,
                )
        return True

    def read_frame(self) -> np.ndarray | None:
        """丢弃旧缓冲后读取一帧；任何异常都返回 None，由服务层重连。"""
        if not self.is_open():
            return None

        assert self.cap is not None
        try:
            # 与 v2.0.1 一致：先丢弃旧缓冲，再 read 取最新帧。
            # 不依赖 retrieve() 的后端差异，读帧路径更稳定。
            for _ in range(FRAME_FLUSH_GRABS):
                self.cap.grab()

            retrieved, frame = self.cap.read()
            if not retrieved or frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
                if logger:
                    logger.debug("[CAMERA] read 未取得有效帧。")
                return None
            return frame
        except cv2.error as exc:
            if logger:
                logger.warning("[CAMERA] OpenCV 读帧异常: %s", exc)
            return None
        except Exception as exc:
            if logger:
                logger.warning("[CAMERA] 读帧异常: %s", exc)
            return None

    def release(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            if logger:
                logger.info("[CAMERA] 已释放设备。")
        self.cap = None
        self.opened_at = 0.0


# ---------------------------------------------------------------------------
# Frame processing / similarity
# ---------------------------------------------------------------------------

def normalize_frame(
    frame: np.ndarray,
    effective_fourcc: str,
    expected_width: int,
    expected_height: int,
    state: ServiceState | None = None,
) -> np.ndarray | None:
    """把 V4L2 返回的任意常见格式统一为可写的 BGR uint8 图像。

    关键点：
    - 不再依赖 DEFAULT_WIDTH * 2 判断 YUYV packed 帧，改用实际 shape；
    - 2 通道 (h,w,2) 和 2D packed (h,w*2) 都正确处理；
    - 尺寸不符合配置时做一次明确的重采样，保证保存图坐标一致；
    - 无法识别的格式返回 None，避免保存错位图像。
    """
    if not isinstance(frame, np.ndarray) or frame.size == 0:
        return None

    if frame.dtype != np.uint8:
        try:
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        except Exception:
            return None

    fourcc = (effective_fourcc or "").upper()
    try:
        if frame.ndim == 3:
            channels = frame.shape[2]
            if channels == 3:
                bgr = frame
            elif channels == 4:
                bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            elif channels == 2:
                bgr = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_YUYV)
            else:
                if logger:
                    logger.warning("[FRAME] 未知通道数: %s", frame.shape)
                return None
        elif frame.ndim == 2:
            height, width = frame.shape
            # YUYV packed：每像素 2 字节，packed 宽度一定是像素数 * 2。
            # 如果宽度等于期望宽度（1920），按灰度图处理，避免把灰度误判成 YUYV。
            packed_like = width == expected_width * 2
            if (fourcc in ("YUYV", "YUY2") and width > expected_width) or packed_like:
                if width % 2 == 0:
                    packed = frame.reshape(height, width // 2, 2)
                    bgr = cv2.cvtColor(packed, cv2.COLOR_YUV2BGR_YUYV)
                else:
                    if logger:
                        logger.warning("[FRAME] YUYV packed 宽度为奇数: %s", width)
                    return None
            else:
                bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        else:
            return None
    except (cv2.error, ValueError) as exc:
        if logger:
            logger.warning("[FRAME] 色彩空间转换失败 shape=%s fourcc=%s: %s", frame.shape, fourcc, exc)
        return None

    if bgr.ndim != 3 or bgr.shape[2] != 3:
        if logger:
            logger.warning("[FRAME] 转换后不是 BGR: %s", bgr.shape)
        return None

    if bgr.shape[1] != expected_width or bgr.shape[0] != expected_height:
        if state is not None:
            state.frame_resizes += 1
        if logger:
            logger.warning(
                "[FRAME] 尺寸 %sx%s 与配置 %sx%s 不符，执行归一化重采样。",
                bgr.shape[1],
                bgr.shape[0],
                expected_width,
                expected_height,
            )
        interpolation = cv2.INTER_AREA if bgr.shape[1] > expected_width else cv2.INTER_LINEAR
        try:
            bgr = cv2.resize(bgr, (expected_width, expected_height), interpolation=interpolation)
        except cv2.error as exc:
            if logger:
                logger.error("[FRAME] 归一化缩放失败: %s", exc)
            return None

    if not bgr.flags.writeable:
        bgr = bgr.copy()
    return bgr


def add_timestamp_to_frame(frame_to_modify: np.ndarray, timestamp_format_str: str) -> np.ndarray:
    """在图像右下角叠加时间戳；调用方应传入副本。"""
    if not ENABLE_TIMESTAMP:
        return frame_to_modify
    if not frame_to_modify.flags.writeable:
        frame_to_modify = frame_to_modify.copy()

    timestamp_text = datetime.now().strftime(timestamp_format_str)
    font = cv2.FONT_HERSHEY_SIMPLEX
    img_h, img_w = frame_to_modify.shape[:2]
    font_scale = max(0.5, (img_h / 1080.0) * 1.0)
    thickness = max(1, int(font_scale * 2.0))
    margin = max(10, int(img_h * 0.05))

    text_size, _ = cv2.getTextSize(timestamp_text, font, font_scale, thickness)
    text_width, text_height = text_size
    org_x = img_w - text_width - margin
    org_y = img_h - margin
    cv2.putText(
        frame_to_modify,
        timestamp_text,
        (org_x, org_y),
        font,
        font_scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
        bottomLeftOrigin=False,
    )
    return frame_to_modify


def are_frames_similar(
    frame1: np.ndarray | None,
    frame2: np.ndarray | None,
    similarity_diff_rate_threshold_int: int,
) -> bool:
    """比较两帧是否足够相似（轮廓面积差异率 <= 阈值）。"""
    if not isinstance(frame1, np.ndarray) or frame1.size == 0:
        return False
    if not isinstance(frame2, np.ndarray) or frame2.size == 0:
        return False

    h1, w1 = frame1.shape[:2]
    h2, w2 = frame2.shape[:2]
    frame1_work = frame1
    frame2_work = frame2

    if w1 > SIMILARITY_MAX_WIDTH:
        scale = SIMILARITY_MAX_WIDTH / float(w1)
        try:
            frame1_work = cv2.resize(
                frame1_work,
                (max(1, int(w1 * scale)), max(1, int(h1 * scale))),
                interpolation=cv2.INTER_AREA,
            )
        except cv2.error:
            return False
        h1, w1 = frame1_work.shape[:2]

    if w2 > SIMILARITY_MAX_WIDTH:
        scale = SIMILARITY_MAX_WIDTH / float(w2)
        try:
            frame2_work = cv2.resize(
                frame2_work,
                (max(1, int(w2 * scale)), max(1, int(h2 * scale))),
                interpolation=cv2.INTER_AREA,
            )
        except cv2.error:
            return False
        h2, w2 = frame2_work.shape[:2]

    if (h1, w1) != (h2, w2):
        try:
            frame2_work = cv2.resize(frame2_work, (w1, h1), interpolation=cv2.INTER_AREA)
        except cv2.error:
            return False

    try:
        if frame1_work.ndim == 3 and frame1_work.shape[2] == 3:
            gray1 = cv2.cvtColor(frame1_work, cv2.COLOR_BGR2GRAY)
        elif frame1_work.ndim == 2:
            gray1 = frame1_work
        else:
            return False

        if frame2_work.ndim == 3 and frame2_work.shape[2] == 3:
            gray2 = cv2.cvtColor(frame2_work, cv2.COLOR_BGR2GRAY)
        elif frame2_work.ndim == 2:
            gray2 = frame2_work
        else:
            return False
    except cv2.error:
        return False

    try:
        if gray1.shape != gray2.shape:
            gray2 = cv2.resize(gray2, (gray1.shape[1], gray1.shape[0]), interpolation=cv2.INTER_AREA)
        if gray1.dtype != gray2.dtype:
            gray2 = gray2.astype(gray1.dtype, copy=False)
    except Exception:
        return False

    total_pixels = gray1.shape[0] * gray1.shape[1]
    if total_pixels <= 0:
        return False

    try:
        abs_diff = cv2.absdiff(gray1, gray2)
    except cv2.error:
        return False

    _, thresh = cv2.threshold(
        abs_diff, DEFAULT_CONTOUR_PIXEL_THRESHOLD, 255, cv2.THRESH_BINARY
    )
    dilated = cv2.dilate(
        thresh, CONTOUR_KERNEL, iterations=DEFAULT_CONTOUR_DILATION_ITERATIONS
    )
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total_area = 0.0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area > DEFAULT_CONTOUR_MIN_AREA_FILTER:
            total_area += area

    actual_percent = (total_area / total_pixels) * 100.0
    threshold_percent = similarity_diff_rate_threshold_int / 100.0
    return actual_percent <= threshold_percent


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class StorageManager:
    """帧归一化、相似度判断、JPEG 保存。"""

    def __init__(self, state: ServiceState) -> None:
        self.state = state

    def process_and_save(
        self,
        frame_data: np.ndarray | None,
        effective_fourcc: str,
        base_save_dir: str,
        jpeg_quality: int,
        timestamp_format: str,
    ) -> str | None:
        if frame_data is None:
            if logger:
                logger.error("接收到空帧，无法处理。")
            self.state.consecutive_imwrite_failures += 1
            return None

        processed = normalize_frame(
            frame_data,
            effective_fourcc,
            DEFAULT_WIDTH,
            DEFAULT_HEIGHT,
            self.state,
        )
        if processed is None:
            if logger:
                logger.error("[FRAME] 无法归一化帧，丢弃本次图像。")
            self.state.consecutive_imwrite_failures += 1
            return None

        if logger:
            logger.debug(
                "[FRAME] 归一化完成: shape=%s dtype=%s fourcc=%s",
                processed.shape,
                processed.dtype,
                effective_fourcc,
            )

        if are_frames_similar(
            self.state.last_significant_frame,
            processed,
            SIMILARITY_THRESHOLD_PERCENT_INT,
        ):
            self.state.frames_skipped += 1
            return "SIMILARITY"

        # 只有保存成功后才更新比较基准，避免写盘失败导致后续帧被误判为相似。
        if ENABLE_TIMESTAMP:
            try:
                frame_to_save = processed.copy()
                add_timestamp_to_frame(frame_to_save, timestamp_format)
            except Exception as exc:
                if logger:
                    logger.error("添加时间戳失败: %s，将保存无时间戳图像。", exc)
                frame_to_save = processed
        else:
            frame_to_save = processed

        now = datetime.now()
        save_subdir = os.path.join(base_save_dir, now.strftime("%Y-%m"), now.strftime("%d"))

        try:
            os.makedirs(save_subdir, exist_ok=True)
        except OSError as exc:
            if logger:
                logger.error("创建目录 %s 失败: %s", save_subdir, exc)
            if IMAGE_SAVE_FALLBACK_DIR:
                try:
                    fallback_subdir = os.path.join(
                        IMAGE_SAVE_FALLBACK_DIR,
                        now.strftime("%Y-%m"),
                        now.strftime("%d"),
                    )
                    os.makedirs(fallback_subdir, exist_ok=True)
                    save_subdir = fallback_subdir
                    if logger:
                        logger.warning("使用回退保存目录: %s", save_subdir)
                except OSError as fallback_exc:
                    if logger:
                        logger.error("创建回退目录失败: %s", fallback_exc)
                    self.state.consecutive_imwrite_failures += 1
                    return None
            else:
                self.state.consecutive_imwrite_failures += 1
                return None

        filename = f"capture_{now.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        filepath = os.path.join(save_subdir, filename)
        if logger:
            logger.debug("尝试保存图像: %s (quality=%s)", filepath, jpeg_quality)

        try:
            success = cv2.imwrite(
                filepath,
                frame_to_save,
                [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)],
            )
        except Exception as exc:
            if logger:
                logger.error("cv2.imwrite 异常: %s", exc)
            self.state.consecutive_imwrite_failures += 1
            return None

        if not success:
            if logger:
                logger.error("cv2.imwrite 返回 False: %s", filepath)
            self.state.consecutive_imwrite_failures += 1
            return None

        try:
            os.chmod(filepath, 0o644)
        except OSError as exc:
            if logger:
                logger.warning("设置文件权限失败 %s: %s", filepath, exc)

        if MIN_JPEG_SAVE_SIZE_BYTES > 0:
            try:
                actual_size = os.path.getsize(filepath)
            except OSError:
                actual_size = 0
            if actual_size < MIN_JPEG_SAVE_SIZE_BYTES:
                try:
                    os.remove(filepath)
                except OSError:
                    pass
                if logger:
                    logger.error(
                        "JPEG 文件过小 (%sB < %sB)，判定为失败。",
                        actual_size,
                        MIN_JPEG_SAVE_SIZE_BYTES,
                    )
                self.state.consecutive_imwrite_failures += 1
                return None

        # 成功后才更新基准帧和统计
        self.state.last_significant_frame = processed
        self.state.last_saved_filepath = filepath
        self.state.frames_saved += 1
        self.state.consecutive_imwrite_failures = 0
        return filepath


# ---------------------------------------------------------------------------
# Disk management
# ---------------------------------------------------------------------------

class DiskManager:
    """磁盘占用检查与最旧日期目录清理。"""

    def __init__(self, state: ServiceState) -> None:
        self.state = state

    def usage_percent(self) -> float:
        try:
            usage = shutil.disk_usage(IMAGE_STORAGE_MONITOR_PATH)
            percent = (usage.used / usage.total) * 100.0
            self.state.last_disk_percent = percent
            return percent
        except Exception:
            return -1.0

    def oldest_day_dir(self) -> str | None:
        base_dir = IMAGE_SAVE_BASE_DIR
        if not os.path.isdir(base_dir):
            if logger:
                logger.warning("get_oldest_day_dir: 目录不存在: %s", base_dir)
            return None

        protected: set[tuple[str, str]] = set()
        if PROTECT_RECENT_DAYS > 0:
            today = datetime.now().date()
            for offset in range(PROTECT_RECENT_DAYS):
                day = today - timedelta(days=offset)
                protected.add((day.strftime("%Y-%m"), day.strftime("%d")))

        candidates: list[str] = []
        try:
            for ym_name in sorted(os.listdir(base_dir)):
                ym_path = os.path.join(base_dir, ym_name)
                if not (os.path.isdir(ym_path) and len(ym_name) == 7 and ym_name[4] == "-"):
                    continue
                for day_name in sorted(os.listdir(ym_path)):
                    day_path = os.path.join(ym_path, day_name)
                    if not (os.path.isdir(day_path) and len(day_name) == 2):
                        continue
                    try:
                        int(day_name)
                    except ValueError:
                        continue
                    if (ym_name, day_name) in protected:
                        continue
                    candidates.append(day_path)
        except Exception as exc:
            if logger:
                logger.warning("扫描旧日期目录失败: %s", exc)
            return None

        return candidates[0] if candidates else None

    def check_and_cleanup(self) -> None:
        percent = self.usage_percent()
        try:
            usage = shutil.disk_usage(IMAGE_STORAGE_MONITOR_PATH)
            total_gb = usage.total / (1024 ** 3)
            used_gb = usage.used / (1024 ** 3)
            free_gb = usage.free / (1024 ** 3)
        except Exception:
            total_gb = used_gb = free_gb = 0.0

        if logger:
            logger.info(
                "[DISK] 监控 %s: %.1fGB/%.1fGB (%.1f%%), free=%.1fGB",
                IMAGE_STORAGE_MONITOR_PATH,
                used_gb,
                total_gb,
                percent,
                free_gb,
            )

        if percent < 0 or percent <= IMAGE_STORAGE_MAX_USAGE_PERCENT:
            return

        if logger:
            logger.warning(
                "[DISK] 使用率 %.1f%% 超过阈值 %s%%，开始清理最多 %s 个最旧日期目录（保护最近 %s 天）。",
                percent,
                IMAGE_STORAGE_MAX_USAGE_PERCENT,
                IMAGE_STORAGE_CLEANUP_BATCH_DAYS,
                PROTECT_RECENT_DAYS,
            )

        for index in range(IMAGE_STORAGE_CLEANUP_BATCH_DAYS):
            if shutdown_event.is_set():
                break
            oldest = self.oldest_day_dir()
            if not oldest:
                if logger:
                    logger.warning("[DISK] 没有可安全删除的旧日期目录。")
                break
            if logger:
                logger.warning(
                    "[DISK] 删除最旧日期目录 (%s/%s): %s",
                    index + 1,
                    IMAGE_STORAGE_CLEANUP_BATCH_DAYS,
                    oldest,
                )
            try:
                shutil.rmtree(oldest)
                self.state.total_disk_cleanup_batches += 1
                if logger:
                    logger.info("[DISK] 已删除: %s", oldest)
            except OSError as exc:
                if logger:
                    logger.error("[DISK] 删除失败 %s: %s", oldest, exc)
                break

            current = self.usage_percent()
            if current >= 0 and current <= IMAGE_STORAGE_MAX_USAGE_PERCENT:
                break


# ---------------------------------------------------------------------------
# Health / memory
# ---------------------------------------------------------------------------

class HealthMonitor:
    """内存采样、周期性 gc、心跳日志、原子 health.json。"""

    def __init__(self, state: ServiceState) -> None:
        self.state = state

    def sample_memory(self) -> float:
        rss, peak = get_rss_mb()
        self.state.last_rss_mb = rss
        self.state.peak_rss_mb = max(self.state.peak_rss_mb, peak, rss)
        return rss

    def maybe_gc(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or (GC_INTERVAL_SECONDS > 0 and now - self.state.last_gc_monotonic >= GC_INTERVAL_SECONDS):
            collected = gc.collect()
            self.state.gc_collections += 1
            self.state.last_gc_monotonic = now
            if logger:
                logger.debug("[MEM] gc.collect() -> %s", collected)

    def check_memory(self) -> bool:
        rss = self.sample_memory()
        now = time.monotonic()
        if MEMORY_LIMIT_MB > 0 and rss >= MEMORY_LIMIT_MB:
            if now - self.state.last_memory_warn_monotonic >= HEARTBEAT_INTERVAL_SECONDS:
                if logger:
                    logger.critical(
                        "[MEM] RSS %.1fMB 达到硬阈值 %sMB，触发相机回收与强制 gc。",
                        rss,
                        MEMORY_LIMIT_MB,
                    )
                self.state.last_memory_warn_monotonic = now
            self.state.memory_pressure_events += 1
            return True

        if MEMORY_WARN_MB > 0 and rss >= MEMORY_WARN_MB:
            if now - self.state.last_memory_warn_monotonic >= HEARTBEAT_INTERVAL_SECONDS:
                if logger:
                    logger.warning(
                        "[MEM] RSS %.1fMB 超过告警阈值 %sMB。",
                        rss,
                        MEMORY_WARN_MB,
                    )
                self.state.last_memory_warn_monotonic = now
        return False

    def log_heartbeat(self, current_interval_seconds: float) -> None:
        if not logger:
            return
        try:
            avg_ms = (
                sum(self.state.processing_times_ms) / len(self.state.processing_times_ms)
                if self.state.processing_times_ms
                else 0.0
            )
            uptime = time.monotonic() - self.state.started_monotonic
            logger.info(
                "Heartbeat | boot_id=%s, uptime=%.0fs, rss=%.1fMB, peak=%.1fMB, "
                "frames=%s, saved=%s, skipped=%s, resizes=%s, reopens=%s, gc=%s, "
                "read_failures=%s, imwrite_failures=%s, cleanup_batches=%s, "
                "interval=%.3fs, avg_processing=%.2fms, last_saved='%s', fourcc='%s', disk_used=%.1f%%",
                self.state.boot_id,
                uptime,
                self.state.last_rss_mb,
                self.state.peak_rss_mb,
                self.state.frames_total,
                self.state.frames_saved,
                self.state.frames_skipped,
                self.state.frame_resizes,
                self.state.camera_reopens,
                self.state.gc_collections,
                self.state.consecutive_read_failures,
                self.state.consecutive_imwrite_failures,
                self.state.total_disk_cleanup_batches,
                float(current_interval_seconds),
                avg_ms,
                self.state.last_saved_filepath or "",
                self.state.effective_fourcc,
                self.state.last_disk_percent,
            )
        except Exception:
            pass

    def write_health(self, current_interval_seconds: float) -> None:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            health = {
                "boot_id": self.state.boot_id,
                "ts": time.time(),
                "interval": current_interval_seconds,
                "read_failures": self.state.consecutive_read_failures,
                "imwrite_failures": self.state.consecutive_imwrite_failures,
                "disk_cleanup_batches": self.state.total_disk_cleanup_batches,
                "last_saved": self.state.last_saved_filepath,
                "fourcc": self.state.effective_fourcc,
                "memory_mb": round(self.state.last_rss_mb, 2),
                "memory_peak_mb": round(self.state.peak_rss_mb, 2),
                "memory_pressure_events": self.state.memory_pressure_events,
                "camera_init_failures": self.state.camera_init_failures,
                "uptime_s": int(time.monotonic() - self.state.started_monotonic),
                "frames_total": self.state.frames_total,
                "frames_saved": self.state.frames_saved,
                "frames_skipped": self.state.frames_skipped,
                "frame_resizes": self.state.frame_resizes,
                "camera_reopens": self.state.camera_reopens,
                "gc_collections": self.state.gc_collections,
                "disk_used_percent": round(self.state.last_disk_percent, 2),
            }
            health_path = os.path.join(LOG_DIR, "health.json")
            tmp_path = f"{health_path}.tmp.{os.getpid()}"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(health, fh, ensure_ascii=False)
            # Web UI 以 www-data 读取该文件，必须显式放宽到 0644。
            os.chmod(tmp_path, 0o644)
            os.replace(tmp_path, health_path)
        except Exception as exc:
            if logger:
                logger.debug("写 health.json 失败: %s", exc)

    def emit(self, current_interval_seconds: float, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self.state.last_health_dump_monotonic >= HEALTH_DUMP_INTERVAL_SECONDS:
            self.write_health(current_interval_seconds)
            self.state.last_health_dump_monotonic = now
        if force or now - self.state.last_heartbeat_monotonic >= HEARTBEAT_INTERVAL_SECONDS:
            self.log_heartbeat(current_interval_seconds)
            self.state.last_heartbeat_monotonic = now


# ---------------------------------------------------------------------------
# Capture service
# ---------------------------------------------------------------------------

def get_current_capture_interval() -> float:
    """根据本地时间返回当前拍摄间隔。"""
    now_time = datetime.now().time()
    for item in CAPTURE_SCHEDULE_CONFIG:
        if now_time < item["end_time_exclusive"]:
            return float(item["interval_seconds"])
    return float(DEFAULT_INTERVAL_LATE_NIGHT)


def format_schedule() -> str:
    parts = [
        f"<{item['end_time_exclusive'].strftime('%H:%M')} ({item['interval_seconds']}s)"
        for item in CAPTURE_SCHEDULE_CONFIG
    ]
    if CAPTURE_SCHEDULE_CONFIG:
        last = CAPTURE_SCHEDULE_CONFIG[-1]["end_time_exclusive"].strftime("%H:%M")
    else:
        last = "00:00"
    parts.append(f">={last} ({DEFAULT_INTERVAL_LATE_NIGHT}s)")
    return ", ".join(parts)


class CaptureService:
    """采集主循环；所有资源都通过组合的 manager 管理。"""

    def __init__(self) -> None:
        self.state = ServiceState()
        self.camera = CameraController(self.state)
        self.storage = StorageManager(self.state)
        self.disk = DiskManager(self.state)
        self.health = HealthMonitor(self.state)
        self.watchdog = Watchdog()

    def _reload_config(self) -> None:
        try:
            if logger:
                logger.info("执行配置热重载...")
            old_device = DEFAULT_CAMERA_DEVICE_PATH
            old_width, old_height = DEFAULT_WIDTH, DEFAULT_HEIGHT
            old_fourcc = REQUESTED_FOURCC
            load_and_apply_yaml_config(CONFIG_PATH, runtime_reload=True)

            changed = (
                DEFAULT_CAMERA_DEVICE_PATH != old_device
                or DEFAULT_WIDTH != old_width
                or DEFAULT_HEIGHT != old_height
                or REQUESTED_FOURCC.upper() != old_fourcc.upper()
            )
            if changed and self.camera.is_open():
                if logger:
                    logger.info("[CAMERA] 关键参数变化，释放设备等待下一轮重建。")
                self.camera.release()
                self.state.camera_reopens += 1
        except Exception as exc:
            if logger:
                logger.error("热重载失败: %s", exc)
        finally:
            reload_event.clear()

    def run(self) -> None:
        if logger:
            logger.info("[SERVICE] 主循环启动 (v%s)。", SCRIPT_VERSION)
            logger.info("  时间表: %s", format_schedule())
            logger.info("  目标摄像头: %s", DEFAULT_CAMERA_DEVICE_PATH)
            logger.info("  摄像头参数: %sx%s, FOURCC=%s", DEFAULT_WIDTH, DEFAULT_HEIGHT, REQUESTED_FOURCC)
            logger.info("  图片保存至: %s (JPEG quality=%s)", IMAGE_SAVE_BASE_DIR, JPEG_SAVE_QUALITY)
            logger.info(
                "  磁盘监控: %s, 阈值 %s%%, 检查间隔 %ss, 保护最近 %s 天",
                IMAGE_STORAGE_MONITOR_PATH,
                IMAGE_STORAGE_MAX_USAGE_PERCENT,
                DISK_CHECK_INTERVAL_SECONDS,
                PROTECT_RECENT_DAYS,
            )
            logger.info(
                "  长期运行: camera_recycle=%ss, memory_warn=%sMB, memory_limit=%sMB, gc=%ss",
                CAMERA_RECYCLE_SECONDS,
                MEMORY_WARN_MB,
                MEMORY_LIMIT_MB,
                GC_INTERVAL_SECONDS,
            )

        self.watchdog.ready()
        self.health.sample_memory()
        self.state.last_disk_percent = self.disk.usage_percent()
        self.health.emit(get_current_capture_interval(), force=True)

        init_failures = 0
        last_disk_check = 0.0
        last_capture_time = time.monotonic()

        while not shutdown_event.is_set():
            current_interval = get_current_capture_interval()
            now = time.monotonic()

            # 先检查磁盘，health.json 才能反映最新占用
            if now - last_disk_check >= DISK_CHECK_INTERVAL_SECONDS:
                self.disk.check_and_cleanup()
                last_disk_check = time.monotonic()

            # 健康与内存监控独立于采集成功与否
            self.health.sample_memory()
            self.health.maybe_gc()
            self.health.emit(current_interval)
            self.watchdog.ping()

            if CONFIG_ENABLED and reload_event.is_set():
                self._reload_config()
                last_capture_time = time.monotonic()

            # 定期释放相机，清理驱动/OpenCV 内部缓冲
            if (
                CAMERA_RECYCLE_SECONDS > 0
                and self.camera.is_open()
                and self.camera.uptime() >= CAMERA_RECYCLE_SECONDS
            ):
                if logger:
                    logger.info(
                        "[CAMERA] 已达到重连周期 %ss，释放设备以回收资源。",
                        CAMERA_RECYCLE_SECONDS,
                    )
                self.camera.release()
                self.state.camera_reopens += 1
                self.health.maybe_gc(force=True)
                last_capture_time = time.monotonic()

            # 内存硬阈值：先释放相机，再强制 gc，等待后重试
            if self.health.check_memory():
                if self.camera.is_open():
                    self.camera.release()
                    self.state.camera_reopens += 1
                self.health.maybe_gc(force=True)
                self.watchdog.wait(5)
                continue

            if not self.camera.is_open():
                if logger:
                    logger.info("[CAMERA] 未连接或需要重新初始化...")
                if not self.camera.open():
                    init_failures += 1
                    self.state.camera_init_failures += 1
                    if logger:
                        logger.error("摄像头初始化失败 (连续第 %s 次)。", init_failures)
                    if init_failures >= CAMERA_INIT_FAILURE_MAX_CONSECUTIVE:
                        if logger:
                            logger.critical(
                                "已连续 %s 次无法初始化摄像头，等待 %ss 后重试。",
                                init_failures,
                                CAMERA_INIT_LONG_BACKOFF_SECONDS,
                            )
                        self.watchdog.wait(CAMERA_INIT_LONG_BACKOFF_SECONDS)
                        init_failures = 0
                    else:
                        self.watchdog.wait(CAMERA_INIT_RETRY_DELAY_SECONDS)
                    continue
                init_failures = 0
                self.state.camera_init_failures = 0
                last_capture_time = time.monotonic()
                self.health.emit(current_interval, force=True)

            elapsed = time.monotonic() - last_capture_time
            wait_time = current_interval - elapsed
            if wait_time > 0:
                self.watchdog.wait(wait_time)
                if shutdown_event.is_set():
                    break

            if shutdown_event.is_set():
                break

            last_capture_time = time.monotonic()
            if logger:
                logger.debug("[CAPTURE] 尝试捕获图像帧 (interval=%ss)...", current_interval)

            t0 = time.perf_counter()
            frame = self.camera.read_frame()

            if frame is None:
                if self.state.consecutive_read_failures % LOG_EVERY_N_READ_FAILURES == 0:
                    if logger:
                        logger.error("[CAPTURE] 无法从摄像头获取图像帧，可能断开或异常。")
                self.state.consecutive_read_failures += 1
                if logger:
                    logger.info(
                        "[CAPTURE] 连续读帧失败次数: %s",
                        self.state.consecutive_read_failures,
                    )
                self.camera.release()
                self.state.camera_reopens += 1

                if self.state.consecutive_read_failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    if logger:
                        logger.critical(
                            "已连续 %s 次无法读取帧，等待 %ss 后重连。",
                            self.state.consecutive_read_failures,
                            READ_FAILURE_LONG_BACKOFF_SECONDS,
                        )
                    self.watchdog.wait(READ_FAILURE_LONG_BACKOFF_SECONDS)
                    self.state.consecutive_read_failures = 0
                else:
                    self.watchdog.wait(FRAME_READ_ERROR_RETRY_DELAY_SECONDS)
                continue

            self.state.consecutive_read_failures = 0
            self.state.frames_total += 1

            try:
                result = self.storage.process_and_save(
                    frame,
                    self.state.effective_fourcc,
                    IMAGE_SAVE_BASE_DIR,
                    JPEG_SAVE_QUALITY,
                    TIMESTAMP_FORMAT,
                )
            except cv2.error as exc:
                if logger:
                    logger.error("[SERVICE] 处理帧时 OpenCV 异常: %s", exc, exc_info=True)
                self.camera.release()
                self.state.camera_reopens += 1
                self.watchdog.wait(CAMERA_INIT_RETRY_DELAY_SECONDS)
                continue
            except Exception as exc:
                if logger:
                    logger.critical("[SERVICE] 处理帧时未预料异常: %s", exc, exc_info=True)
                self.camera.release()
                self.state.camera_reopens += 1
                self.watchdog.wait(CAMERA_INIT_LONG_BACKOFF_SECONDS)
                continue

            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.state.processing_times_ms.append(elapsed_ms)

            if result == "SIMILARITY":
                if logger:
                    logger.debug("[SAVE] 图像接近，跳过保存。")
            elif isinstance(result, str) and result.lower().endswith(".jpg"):
                if logger:
                    logger.debug("[SAVE] 成功保存: %s", result)
                if self.state.frames_saved == 1:
                    # 首次成功保存后立即刷新 health.json，避免运维面板等待 5 分钟。
                    self.health.emit(current_interval, force=True)
            else:
                if logger:
                    logger.warning("[SAVE] 本次图像未能成功保存。")
                if self.state.consecutive_imwrite_failures >= MAX_CONSECUTIVE_IMWRITE_FAILURES:
                    if logger:
                        logger.critical(
                            "[SAVE] 连续 %s 次保存失败，尝试磁盘清理并退避。",
                            self.state.consecutive_imwrite_failures,
                        )
                    self.disk.check_and_cleanup()
                    self.watchdog.wait(IMWRITE_FAILURE_BACKOFF_SECONDS)
                    self.state.consecutive_imwrite_failures = 0

        # 退出清理
        self.camera.release()
        self.health.emit(get_current_capture_interval(), force=True)
        self.watchdog.stopping()
        if logger:
            logger.info("[SERVICE] 主循环已停止。")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    global logger, PID_FILE_PATH, CONFIG_PATH, CONFIG_ENABLED
    global LOG_DIR, IMAGE_SAVE_BASE_DIR, IMAGE_STORAGE_MONITOR_PATH

    parser = argparse.ArgumentParser(
        description=f"{SCRIPT_NAME} - Image Capture Service (v{SCRIPT_VERSION})"
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["start", "stop", "status", "foreground"],
        default="foreground",
        help="Action: start, stop, status, or foreground (default, for systemd/debug).",
    )
    parser.add_argument("--pidfile", default=PID_FILE_PATH, help="Path to PID file")
    parser.add_argument("--logdir", default=LOG_DIR, help="Path to log directory")
    parser.add_argument(
        "--loglevel",
        default=LOG_LEVEL_CONFIG,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level",
    )
    parser.add_argument("--config", default=CONFIG_PATH, help="Path to YAML config file")
    parser.add_argument(
        "--use-config",
        action="store_true",
        help="Enable loading YAML config (default: disabled)",
    )
    args = parser.parse_args()

    home_dir = os.path.expanduser("~") or "/tmp"
    resolved_log_dir = args.logdir
    try:
        os.makedirs(resolved_log_dir, exist_ok=True)
    except Exception:
        resolved_log_dir = os.path.join(home_dir, "camera", "logs")
        os.makedirs(resolved_log_dir, exist_ok=True)

    resolved_image_dir = IMAGE_SAVE_BASE_DIR
    try:
        os.makedirs(resolved_image_dir, exist_ok=True)
    except Exception:
        resolved_image_dir = os.path.join(home_dir, "camera", "captures")
        os.makedirs(resolved_image_dir, exist_ok=True)

    logger = setup_logging_system(
        resolved_log_dir,
        LOG_FILE_NAME,
        args.loglevel.upper(),
        LOG_ROTATE_WHEN,
        LOG_ROTATE_INTERVAL,
        LOG_ROTATE_BACKUP_COUNT,
    )

    CONFIG_PATH = args.config
    CONFIG_ENABLED = bool(args.use_config)
    if CONFIG_ENABLED:
        load_and_apply_yaml_config(args.config)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        LOG_DIR = resolved_log_dir
    try:
        os.makedirs(IMAGE_SAVE_BASE_DIR, exist_ok=True)
    except Exception:
        IMAGE_SAVE_BASE_DIR = resolved_image_dir
    # 若 YAML 指定了独立的 disk_management.monitor_path，不要在这里覆盖它。

    pid_dir = os.path.dirname(os.path.abspath(args.pidfile))
    try:
        os.makedirs(pid_dir, exist_ok=True)
        PID_FILE_PATH = os.path.abspath(args.pidfile)
    except Exception:
        PID_FILE_PATH = os.path.join("/tmp", os.path.basename(args.pidfile))

    if logger:
        logger.info(
            "[BOOT] config_enabled=%s, config_path='%s', image_dir='%s', log_dir='%s', "
            "device='%s', size=%sx%s, fourcc='%s', jpeg_quality=%s",
            CONFIG_ENABLED,
            CONFIG_PATH,
            IMAGE_SAVE_BASE_DIR,
            LOG_DIR,
            DEFAULT_CAMERA_DEVICE_PATH,
            DEFAULT_WIDTH,
            DEFAULT_HEIGHT,
            REQUESTED_FOURCC,
            JPEG_SAVE_QUALITY,
        )

    if args.action in ("start", "foreground"):
        if args.action == "start":
            if logger:
                logger.info("Action 'start': 当前实现按前台运行，请使用 systemd 托管。")
        if logger:
            logger.info("Starting %s v%s ...", SCRIPT_NAME, SCRIPT_VERSION)

        if os.path.exists(PID_FILE_PATH):
            try:
                with open(PID_FILE_PATH, "r", encoding="utf-8") as fh:
                    existing_pid = int(fh.read().strip())
                os.kill(existing_pid, 0)
                if logger:
                    logger.warning(
                        "Service already running with PID %s (PID file %s).",
                        existing_pid,
                        PID_FILE_PATH,
                    )
                sys.exit(1)
            except (IOError, ValueError, ProcessLookupError):
                if logger:
                    logger.warning("Found stale PID file %s; removing.", PID_FILE_PATH)
                try:
                    os.remove(PID_FILE_PATH)
                except OSError:
                    pass

        create_pid_file()
        signal.signal(signal.SIGTERM, signal_term_handler)
        signal.signal(signal.SIGINT, signal_term_handler)
        try:
            signal.signal(signal.SIGHUP, signal_hup_handler)
        except Exception:
            pass

        try:
            CaptureService().run()
        except Exception as exc:
            if logger:
                logger.critical("Unhandled exception in capture service: %s", exc, exc_info=True)
            sys.exit(1)
        finally:
            remove_pid_file()
            if logger:
                logger.info("%s has shut down.", SCRIPT_NAME)
            logging.shutdown()
        sys.exit(0)

    if args.action == "stop":
        if logger:
            logger.info("Action: stop")
        if not os.path.exists(PID_FILE_PATH):
            if logger:
                logger.warning("PID file %s not found.", PID_FILE_PATH)
            sys.exit(1)

        try:
            with open(PID_FILE_PATH, "r", encoding="utf-8") as fh:
                pid = int(fh.read().strip())
        except (IOError, ValueError) as exc:
            if logger:
                logger.error("Invalid PID file %s: %s", PID_FILE_PATH, exc)
            sys.exit(1)

        terminated = False
        try:
            os.kill(pid, signal.SIGTERM)
            for attempt in range(10):
                time.sleep(1)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    terminated = True
                    if logger:
                        logger.info("Process %s terminated.", pid)
                    break
        except ProcessLookupError:
            if logger:
                logger.info("Process %s already terminated.", pid)
        except PermissionError:
            if logger:
                logger.error("No permission to signal process %s.", pid)
            sys.exit(1)
        except Exception as exc:
            if logger:
                logger.error("Error stopping service: %s", exc)
            sys.exit(1)
        finally:
            if terminated and os.path.exists(PID_FILE_PATH):
                remove_pid_file()
            elif not terminated and os.path.exists(PID_FILE_PATH) and logger:
                logger.warning("Process %s may still be running; PID file kept.", pid)
        return

    if args.action == "status":
        if not os.path.exists(PID_FILE_PATH):
            print(f"{SCRIPT_NAME} is not running (no PID file).")
            sys.exit(3)
        try:
            with open(PID_FILE_PATH, "r", encoding="utf-8") as fh:
                pid = int(fh.read().strip())
        except (IOError, ValueError):
            print(f"{SCRIPT_NAME} status unknown (invalid PID file).")
            sys.exit(4)
        try:
            os.kill(pid, 0)
            print(f"{SCRIPT_NAME} is running with PID {pid}.")
            sys.exit(0)
        except ProcessLookupError:
            print(f"{SCRIPT_NAME} is not running (stale PID {pid}).")
            remove_pid_file()
            sys.exit(3)
        except PermissionError:
            print(f"{SCRIPT_NAME} with PID {pid} exists, but permission denied.")
            sys.exit(4)
        except Exception as exc:
            print(f"Error checking status for PID {pid}: {exc}")
            sys.exit(4)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal_term_handler)
    signal.signal(signal.SIGINT, signal_term_handler)
    try:
        main()
    except SystemExit as exc:
        if logger:
            logger.info("Script explicitly exited with status %s.", exc.code)
        raise
    except Exception as exc:
        if logger:
            logger.critical("Unhandled top-level exception: %s", exc, exc_info=True)
        else:
            print(f"CRITICAL: Unhandled top-level exception: {exc}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
        sys.exit(1)
    finally:
        if logging.getLogger(SCRIPT_NAME).hasHandlers():
            logging.shutdown()
