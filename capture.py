"""
嵌入式相机采集服务（自恢复、不可中断、低资源占用）。

核心特性概述：
- 前台常驻服务：按时间表周期抓拍图像，并保存到按年月/日分层的目录中
- 自恢复：相机初始化失败、读帧失败、编码失败、磁盘满等异常不退出，按短/长退避重试
- 健康心跳：周期性输出关键指标（失败计数、磁盘使用、平均处理耗时、最近一次保存路径、FOURCC、当前间隔）
- 配置策略：默认使用内置常量；仅在 --use-config 时加载 YAML 并支持 SIGHUP 热重载（不更换日志目录）
- 资源友好：相似度判断使用降采样灰度与形态学复用，日志节流，尽量减少内存复制与磁盘I/O

目录结构与权限：
- 日志目录默认在 /opt/camera/logs，图片在 /opt/camera/captures；PID 在 /var/run/。若不可写会尝试回退到 $HOME 或 /tmp
- 在你的使用要求下：PID 创建失败将直接退出（保证 stop/status 可用）

信号与控制：
- SIGTERM/SIGINT：优雅停机（清理资源并退出）
- SIGHUP：当启用配置时触发一次热重载（不重建日志 handler）

可靠性策略（要点）：
- 相机初始化：多次重试，超过阈值采用长退避
- 读帧失败：短退避；连续失败到阈值采用长退避；日志按 N 次节流
- 保存失败：计数到阈值后尝试磁盘清理 + 退避继续运行，不退出
- OpenCV/未知异常：捕获并释放设备，按既定退避等待后重试
"""

import cv2
import numpy as np
import json
import random
import logging
import logging.handlers
import time
import os
import sys
import argparse
import signal
import shutil
import traceback
from datetime import datetime, time as dt_time
from threading import Event
from collections import deque

# Optional YAML support for external configuration
try:
    import yaml  # type: ignore
except Exception:
    yaml = None

# --- Script Information ---
SCRIPT_VERSION = "2.0.1"
SCRIPT_NAME = os.path.basename(__file__)

# --- Default Configuration ---
# 注意：这些是脚本的“内置默认值”。在未显式传入 --use-config 时始终生效。
# 若启用配置文件（--use-config），仅有明确在 YAML 中定义的键会覆盖对应默认值。
BASE_APP_DIR = "/opt/camera/"
LOG_DIR = os.path.join(BASE_APP_DIR, 'logs')
PID_FILE_PATH = f"/var/run/{SCRIPT_NAME.replace('.py', '.pid')}"
IMAGE_SAVE_BASE_DIR = "/opt/camera/captures"

LOG_LEVEL_CONFIG = "INFO"
LOG_FILE_NAME = "image_capture"
LOG_ROTATE_WHEN = "midnight"
LOG_ROTATE_INTERVAL = 1
LOG_ROTATE_BACKUP_COUNT = 30

DEFAULT_CAMERA_INDEX = 3
DEFAULT_CAMERA_DEVICE_PATH = "/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._UGREEN_Camera_2K_SN0001-video-index0"
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
REQUESTED_FOURCC = 'YUYV'
JPEG_SAVE_QUALITY = 90

CAPTURE_SCHEDULE_CONFIG = [
    {"end_time_exclusive": dt_time(5, 0), "interval_seconds": 10},
    {"end_time_exclusive": dt_time(6, 0),  "interval_seconds": 5},
    {"end_time_exclusive": dt_time(21, 30),  "interval_seconds": 2},
    {"end_time_exclusive": dt_time(22, 30),  "interval_seconds": 5},
]
DEFAULT_INTERVAL_LATE_NIGHT = 10

PARAMETER_SET_RETRIES = 3
PARAMETER_SET_DELAY_SECONDS = 0.5
CAMERA_INIT_FAILURE_MAX_CONSECUTIVE = 5
CAMERA_INIT_RETRY_DELAY_SECONDS = 15
CAMERA_INIT_LONG_BACKOFF_SECONDS = 300

# 读帧失败退避控制（短退避 + 长退避）
MAX_CONSECUTIVE_READ_FAILURES = 10 # Max consecutive cap.read() failures before longer pause
READ_FAILURE_LONG_BACKOFF_SECONDS = 60 # Longer pause after max read failures

FRAME_READ_ERROR_RETRY_DELAY_SECONDS = 5 # Short delay after a single read failure

# 写盘失败退避控制
MAX_CONSECUTIVE_IMWRITE_FAILURES = 5 # Max consecutive cv2.imwrite() failures before shutdown
IMWRITE_FAILURE_BACKOFF_SECONDS = 60  # Backoff instead of stopping the service

ENABLE_TIMESTAMP = True
TIMESTAMP_FORMAT = "%Y/%m/%d %H:%M:%S"

IMAGE_STORAGE_MONITOR_PATH = IMAGE_SAVE_BASE_DIR
IMAGE_STORAGE_MAX_USAGE_PERCENT = 85
IMAGE_STORAGE_CLEANUP_BATCH_DAYS = 1
DISK_CHECK_INTERVAL_SECONDS = 14400
HEARTBEAT_INTERVAL_SECONDS = 300

# 额外的可选配置（通过 YAML 启用）
MIN_JPEG_SAVE_SIZE_BYTES = 0  # 若>0，则保存后检查文件尺寸，小于阈值视为失败
IMAGE_SAVE_FALLBACK_DIR: str | None = None  # 备选保存目录（创建主目录失败或磁盘满时尝试）

# --- Global Variables ---
logger = None
shutdown_event = Event()
reload_event = Event()
CONFIG_PATH = '/opt/camera/config.yaml'
CONFIG_ENABLED = False
consecutive_imwrite_failures = 0 # MODIFICATION v2.0.1
consecutive_read_failures = 0    # MODIFICATION v2.0.1

# 相似度比较参数（差分 + 形态学 + 轮廓面积比例）
DEFAULT_CONTOUR_PIXEL_THRESHOLD = 25   # 用于生成初始差异图的像素强度阈值
DEFAULT_CONTOUR_KERNEL_SIZE = (5, 5)   # 形态学膨胀操作的卷积核大小
DEFAULT_CONTOUR_DILATION_ITERATIONS = 2 # 膨胀操作的迭代次数
DEFAULT_CONTOUR_MIN_AREA_FILTER = 50.0 # 过滤掉小于此面积的差异轮廓

last_significant_frame = None
SIMILARITY_THRESHOLD_PERCENT_INT = 100 # 例如0.5%
SIMILARITY_MAX_WIDTH = 640  # 相似度计算时的最大宽度（降低分辨率以节省CPU）
LOG_EVERY_N_READ_FAILURES = 5  # 读帧失败的日志节流

# 复用的形态学内核，避免频繁分配
CONTOUR_KERNEL = np.ones(DEFAULT_CONTOUR_KERNEL_SIZE, np.uint8)

# --- Logging Setup ---
# (setup_logging_system function from v2.0.0 is unchanged)
def setup_logging_system(log_dir, log_file_prefix, level_str, when, interval, backup_count):
    """初始化日志系统。

    - 创建/复用日志记录器，设置统一的格式与轮转策略
    - 控制台与文件双通道输出
    - 保守处理，避免日志异常影响主流程
    """
    global logger
    numeric_level = getattr(logging, level_str.upper(), logging.INFO)

    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            print(f"CRITICAL: Failed to create log directory {log_dir}: {e}", file=sys.stderr)
            sys.exit(1) 

    logger = logging.getLogger(SCRIPT_NAME)
    logger.setLevel(numeric_level)
    # 避免日志写入异常导致程序抛出异常
    logging.raiseExceptions = False
    
    ## current_date_str = datetime.now().strftime("_%Y_%m_%d") # 例如：_2023_10_27
    ## current_date_str_new = datetime.now().strftime("%Y-%m-%d")
    ## actual_log_file_name = f"{log_file_prefix}.log.{current_date_str_new}"
    log_file_basename = f"{log_file_prefix}.log" # 例如 "image_capture.log"
    log_filepath = os.path.join(log_dir, log_file_basename) # 使用这个路径

    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s [%(levelname)-7s] [%(process)d] [%(threadName)s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s')
    
    ## log_filepath = os.path.join(log_dir, actual_log_file_name)
    try:
        fh = logging.handlers.TimedRotatingFileHandler(
            log_filepath, when=when, interval=interval, backupCount=backup_count, encoding='utf-8'
        )
        fh.setLevel(numeric_level)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception as e:
        print(f"WARNING: Failed to initialize file logger at {log_filepath}: {e}", file=sys.stderr)

    ch = logging.StreamHandler(sys.stdout) 
    ch.setLevel(numeric_level) 
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    logger.info(f"[LOG] 初始化完成，级别: {level_str}，文件: {log_filepath}")
    return logger


class ServiceState:
    """封装服务运行期的可变状态，便于测试与热更新。

    仅包含“动态”数据，避免与配置常量耦合，便于单元测试与重放。
    """
    def __init__(self) -> None:
        self.consecutive_imwrite_failures: int = 0
        self.consecutive_read_failures: int = 0
        self.last_significant_frame: np.ndarray | None = None
        self.total_disk_cleanup_batches: int = 0
        self.last_heartbeat_monotonic: float = 0.0
        self.last_saved_filepath: str | None = None
        self.processing_times_ms: deque[float] = deque(maxlen=120)  # 固定窗口，均摊内存与操作成本
        self.effective_fourcc: str = "NOT_SET_INITIALLY"
        self.boot_id: str = f"{int(time.time())}-{random.randint(1000,9999)}"
        self.last_health_dump_monotonic: float = 0.0
        # 已应用到相机的请求参数（用于热重载后变更检测）
        self.applied_camera_device: str | None = None
        self.applied_width: int | None = None
        self.applied_height: int | None = None
        self.applied_requested_fourcc: str | None = None


def log_heartbeat(state: 'ServiceState', current_interval_seconds: float) -> None:
    """输出健康心跳。

    内容包含：
    - 连续读帧失败次数/连续写盘失败次数
    - 已完成的磁盘清理批次数
    - 当前拍摄间隔（秒）
    - 平均处理耗时（毫秒，滑动窗口）
    - 最近一次保存的文件路径（如有）
    - 当前有效 FOURCC
    - 监控路径磁盘使用率
    """
    try:
        # 采样平均处理耗时
        avg_ms = 0.0
        if state.processing_times_ms:
            avg_ms = sum(state.processing_times_ms) / len(state.processing_times_ms)

        # 磁盘占用
        try:
            usage = shutil.disk_usage(IMAGE_STORAGE_MONITOR_PATH)
            percent_used = (usage.used / usage.total) * 100.0
        except Exception:
            percent_used = -1.0

        logger.info(
            (
                "Heartbeat | boot_id=%s, read_failures=%d, imwrite_failures=%d, disk_cleanup_batches=%d, "
                "interval=%.3fs, avg_processing=%.2fms, last_saved='%s', fourcc='%s', disk_used=%.1f%%"
            ),
            state.boot_id,
            state.consecutive_read_failures,
            state.consecutive_imwrite_failures,
            state.total_disk_cleanup_batches,
            float(current_interval_seconds),
            avg_ms,
            state.last_saved_filepath or "",
            state.effective_fourcc,
            percent_used,
        )
    except Exception:
        # 保守处理，心跳日志不能影响主流程
        pass

def load_and_apply_yaml_config(config_path: str, runtime_reload: bool = False):
    """可选：加载 YAML 配置并覆盖内置参数（未启用时跳过）。

    - runtime_reload=True 表示热重载（不改变日志目录，避免切换 handler）
    - 出错只记录，不影响主流程
    """
    global DEFAULT_CAMERA_DEVICE_PATH, DEFAULT_WIDTH, DEFAULT_HEIGHT, REQUESTED_FOURCC
    global JPEG_SAVE_QUALITY, IMAGE_SAVE_BASE_DIR, LOG_DIR, PID_FILE_PATH
    global CAPTURE_SCHEDULE_CONFIG, DEFAULT_INTERVAL_LATE_NIGHT
    global IMAGE_STORAGE_MONITOR_PATH, IMAGE_STORAGE_MAX_USAGE_PERCENT
    global DISK_CHECK_INTERVAL_SECONDS, IMAGE_STORAGE_CLEANUP_BATCH_DAYS
    global SIMILARITY_THRESHOLD_PERCENT_INT, MIN_JPEG_SAVE_SIZE_BYTES
    global IMAGE_SAVE_FALLBACK_DIR, LOG_LEVEL_CONFIG, LOG_ROTATE_WHEN, LOG_ROTATE_INTERVAL, LOG_ROTATE_BACKUP_COUNT
    global BASE_APP_DIR, LOG_FILE_NAME, MAX_CONSECUTIVE_IMWRITE_FAILURES
    global ENABLE_TIMESTAMP, TIMESTAMP_FORMAT

    if yaml is None:
        if logger:
            logger.warning("未安装 PyYAML，跳过外部配置加载。")
        return
    try:
        if not os.path.isfile(config_path):
            if logger:
                logger.info(f"未找到配置文件 {config_path}，继续使用内置配置。")
            return
        with open(config_path, "r", encoding="utf-8") as f:
            raw_cfg = yaml.safe_load(f) or {}

        # 兼容旧版（扁平结构）
        flat = raw_cfg
        nested = raw_cfg if isinstance(raw_cfg, dict) else {}

        def _resolve_placeholders(text: str) -> str:
            if not isinstance(text, str):
                return text
            try:
                base_app_dir_local = nested.get("paths", {}).get("base_app_dir", BASE_APP_DIR)
                image_base_dir_local = nested.get("paths", {}).get("image_save_base_dir", IMAGE_SAVE_BASE_DIR)
                mapping = {
                    "base_app_dir": base_app_dir_local,
                    "image_save_base_dir": image_base_dir_local,
                }
                return text.format(**mapping)
            except Exception:
                return text

        # --- paths ---
        paths_cfg = nested.get("paths", {}) if isinstance(nested.get("paths", {}), dict) else {}
        base_app_dir_val = _resolve_placeholders(paths_cfg.get("base_app_dir", BASE_APP_DIR))
        image_save_base_dir_val = _resolve_placeholders(paths_cfg.get("image_save_base_dir", IMAGE_SAVE_BASE_DIR))
        image_save_fallback_dir_val = _resolve_placeholders(paths_cfg.get("image_save_fallback_dir", IMAGE_SAVE_FALLBACK_DIR or ""))
        log_dir_val = _resolve_placeholders(paths_cfg.get("log_dir", LOG_DIR))
        pid_file_val = _resolve_placeholders(paths_cfg.get("pid_file", PID_FILE_PATH))

        # 仅在非运行时热重载时允许更改关键路径（避免切换 handler）
        if not runtime_reload:
            try:
                BASE_APP_DIR = str(base_app_dir_val)
            except Exception:
                pass
            try:
                LOG_DIR = str(log_dir_val)
            except Exception:
                pass
            try:
                PID_FILE_PATH = str(pid_file_val)
            except Exception:
                pass

        try:
            IMAGE_SAVE_BASE_DIR = str(image_save_base_dir_val)
        except Exception:
            pass
        IMAGE_STORAGE_MONITOR_PATH = IMAGE_SAVE_BASE_DIR
        if image_save_fallback_dir_val:
            try:
                IMAGE_SAVE_FALLBACK_DIR = str(image_save_fallback_dir_val)
            except Exception:
                IMAGE_SAVE_FALLBACK_DIR = None

        # --- logging ---
        logging_cfg = nested.get("logging", {}) if isinstance(nested.get("logging", {}), dict) else {}
        try:
            LOG_LEVEL_CONFIG = str(logging_cfg.get("level", LOG_LEVEL_CONFIG))
        except Exception:
            pass
        try:
            tmp_name = logging_cfg.get("log_file_name")
            if isinstance(tmp_name, str) and tmp_name.strip():
                LOG_FILE_NAME = tmp_name.strip().replace(".log", "").replace("/", "_")
        except Exception:
            pass
        LOG_ROTATE_WHEN = str(logging_cfg.get("rotate_when", LOG_ROTATE_WHEN))
        LOG_ROTATE_INTERVAL = int(logging_cfg.get("rotate_interval", LOG_ROTATE_INTERVAL))
        LOG_ROTATE_BACKUP_COUNT = int(logging_cfg.get("rotate_backup_count", LOG_ROTATE_BACKUP_COUNT))

        # --- camera ---
        cam_cfg = nested.get("camera", {}) if isinstance(nested.get("camera", {}), dict) else {}
        DEFAULT_CAMERA_DEVICE_PATH = flat.get("camera_device", DEFAULT_CAMERA_DEVICE_PATH)
        DEFAULT_WIDTH = int(cam_cfg.get("width", flat.get("width", DEFAULT_WIDTH)))
        DEFAULT_HEIGHT = int(cam_cfg.get("height", flat.get("height", DEFAULT_HEIGHT)))
        REQUESTED_FOURCC = str(cam_cfg.get("requested_fourcc", flat.get("fourcc", REQUESTED_FOURCC)))
        JPEG_SAVE_QUALITY = int(cam_cfg.get("jpeg_quality", flat.get("jpeg_quality", JPEG_SAVE_QUALITY)))

        # --- schedule ---
        schedule_new = []
        sched_cfg = nested.get("capture_schedule", {}) if isinstance(nested.get("capture_schedule", {}), dict) else {}
        rules = sched_cfg.get("schedule_rules")
        if isinstance(rules, list):
            for item in rules:
                try:
                    end_str = str(item.get("end_time_exclusive", "00:00"))
                    parts = [int(p) for p in end_str.split(":")]
                    while len(parts) < 3: parts.append(0)
                    end_t = dt_time(parts[0], parts[1], parts[2])
                    interval = float(item.get("interval_seconds", 2.5))
                    schedule_new.append({"end_time_exclusive": end_t, "interval_seconds": interval})
                except Exception:
                    continue
        legacy_schedule = flat.get("schedule")
        if isinstance(legacy_schedule, list):
            for item in legacy_schedule:
                try:
                    hh, mm = str(item.get("end", "00:00")).split(":")
                    end_t = dt_time(int(hh), int(mm))
                    interval = float(item.get("interval_seconds", 2.5))
                    schedule_new.append({"end_time_exclusive": end_t, "interval_seconds": interval})
                except Exception:
                    continue
        if schedule_new:
            CAPTURE_SCHEDULE_CONFIG = schedule_new
        DEFAULT_INTERVAL_LATE_NIGHT = float(sched_cfg.get("default_interval_late_night", flat.get("default_interval_late_night", DEFAULT_INTERVAL_LATE_NIGHT)))

        # --- image processing ---
        img_cfg = nested.get("image_processing", {}) if isinstance(nested.get("image_processing", {}), dict) else {}
        try:
            ENABLE_TIMESTAMP = bool(img_cfg.get("enable_timestamp", ENABLE_TIMESTAMP))
        except Exception:
            pass
        try:
            TIMESTAMP_FORMAT = str(img_cfg.get("timestamp_format", TIMESTAMP_FORMAT))
        except Exception:
            pass

        # --- disk management ---
        disk_cfg = nested.get("disk_management", {}) if isinstance(nested.get("disk_management", {}), dict) else {}
        monitor_path_val = _resolve_placeholders(disk_cfg.get("monitor_path", IMAGE_STORAGE_MONITOR_PATH))
        try:
            IMAGE_STORAGE_MONITOR_PATH = str(monitor_path_val) if monitor_path_val else IMAGE_SAVE_BASE_DIR
        except Exception:
            IMAGE_STORAGE_MONITOR_PATH = IMAGE_SAVE_BASE_DIR
        IMAGE_STORAGE_MAX_USAGE_PERCENT = int(disk_cfg.get("max_usage_percent", flat.get("disk_usage_max_percent", IMAGE_STORAGE_MAX_USAGE_PERCENT)))
        IMAGE_STORAGE_CLEANUP_BATCH_DAYS = int(disk_cfg.get("cleanup_batch_days", IMAGE_STORAGE_CLEANUP_BATCH_DAYS))
        DISK_CHECK_INTERVAL_SECONDS = int(disk_cfg.get("check_interval_seconds", DISK_CHECK_INTERVAL_SECONDS))
        MIN_JPEG_SAVE_SIZE_BYTES = int(disk_cfg.get("min_jpeg_save_size_bytes", MIN_JPEG_SAVE_SIZE_BYTES))

        # --- service ---
        svc_cfg = nested.get("service", {}) if isinstance(nested.get("service", {}), dict) else {}
        MAX_CONSECUTIVE_IMWRITE_FAILURES = int(svc_cfg.get("max_consecutive_imwrite_failures", MAX_CONSECUTIVE_IMWRITE_FAILURES))

        # --- similarity --- （兼容旧配置）
        SIMILARITY_THRESHOLD_PERCENT_INT = int(flat.get("similarity_threshold_percent_int", SIMILARITY_THRESHOLD_PERCENT_INT))

        if logger:
            logger.info(f"配置文件已加载: {config_path}")
    except Exception as e:
        if logger:
            logger.error(f"加载配置文件失败 {config_path}: {e}")
        else:
            print(f"WARNING: Failed to load config {config_path}: {e}", file=sys.stderr)


def signal_hup_handler(signum, frame):
    """SIGHUP 信号处理：触发配置热重载请求。"""
    try:
        if logger:
            logger.info(f"接收到 SIGHUP ({signum})，请求重载配置。")
    finally:
        reload_event.set()

# --- PID File Management ---
# (create_pid_file, remove_pid_file functions from v2.0.0 are unchanged)
def create_pid_file():
    """创建 PID 文件用于 stop/status 操作，失败则退出。"""
    if not PID_FILE_PATH: return
    try:
        pid = os.getpid()
        os.makedirs(os.path.dirname(PID_FILE_PATH), exist_ok=True)
        with open(PID_FILE_PATH, 'w') as f:
            f.write(str(pid))
        logger.info(f"[PID] 创建成功: {PID_FILE_PATH} (PID={pid})")
    except IOError as e:
        logger.error(f"Unable to create PID file {PID_FILE_PATH}: {e}")
        # 无法创建 PID 文件会影响 stop/status 的可操作性，这里按照你的要求直接退出
        sys.exit(1)

def remove_pid_file():
    """移除 PID 文件，失败仅记录警告。"""
    if not PID_FILE_PATH: return
    try:
        if os.path.exists(PID_FILE_PATH):
            os.remove(PID_FILE_PATH)
            logger.info(f"[PID] 已移除: {PID_FILE_PATH}")
    except IOError as e:
        logger.warning(f"Unable to remove PID file {PID_FILE_PATH}: {e}")

# --- Signal Handling ---
def signal_term_handler(signum, frame):
    """SIGTERM/SIGINT 处理：发出优雅停机信号。"""
    msg = f"接收到信号 {signal.Signals(signum).name} ({signum})，开始优雅停机..."
    if logger: logger.info(msg)
    else: print(msg, file=sys.stderr)
    shutdown_event.set()

# --- Core Camera and Image Processing Functions ---
# (get_fourcc_str, set_camera_parameter, initialize_camera, add_timestamp_to_frame
#  from v2.0.0 are good, ensure logger is used, and set_camera_parameter uses shutdown_event.wait)
def get_fourcc_str(fourcc_int: int) -> str: # Identical to v2.0.0
    """将四字符码整数转为字符串，用于日志展示。"""
    if fourcc_int == 0: return "N/A (0)"
    try:
        return "".join([chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4)]).strip()
    except Exception as e:
        logger.warning(f"转换FOURCC整数 {hex(fourcc_int)} 到字符串失败: {e}")
        return f"Unknown ({hex(fourcc_int)})"

def set_camera_parameter(cap: cv2.VideoCapture, prop_id: int, value, param_name: str, 
                         retries: int = PARAMETER_SET_RETRIES, delay: float = PARAMETER_SET_DELAY_SECONDS) -> bool: # Identical to v2.0.0
    """带重试的相机参数设置。

    - 写入后短暂等待，再读取确认
    - 各类异常只记录日志，不中断
    """
    logger.info(f"尝试设置摄像头参数 {param_name} 为 {value}")
    for i in range(retries):
        try:
            cap.set(prop_id, value)
        except Exception as e:
            logger.warning(f"设置 {param_name} 时出现异常: {e}")
        if shutdown_event.wait(timeout=delay): return False # Shutdown requested

        try:
            actual_value = cap.get(prop_id)
        except Exception as e:
            logger.warning(f"读取 {param_name} 当前值时出现异常: {e}")
            actual_value = value
        is_set = False
        requested_value_for_log = value
        actual_value_for_log = actual_value

        if prop_id == cv2.CAP_PROP_FOURCC:
            target_int = int(value) 
            actual_int = int(actual_value)
            is_set = (actual_int == target_int)
            requested_value_for_log = get_fourcc_str(target_int)
            actual_value_for_log = get_fourcc_str(actual_int)
        elif isinstance(value, float):
            is_set = (abs(float(actual_value) - value) < 1e-9) 
        else: 
            is_set = (int(actual_value) == int(value))
        
        logger.debug(f"尝试 {i+1}/{retries} 设置 {param_name}: 请求 {requested_value_for_log}, 实际 {actual_value_for_log}")
        if is_set:
            logger.info(f"参数 {param_name} 成功设置为 {requested_value_for_log}")
            return True
        time.sleep(0.1)
            
    final_actual_value = cap.get(prop_id)
    if prop_id == cv2.CAP_PROP_FOURCC: final_actual_value = get_fourcc_str(int(final_actual_value))
    logger.warning(f"无法将参数 {param_name} 设置为 {requested_value_for_log} "
                   f"经过 {retries} 次尝试后，实际值为 {final_actual_value}")
    return False

def initialize_camera(camera_path: str, width: int, height: int, req_fourcc_str: str): # Identical to v2.0.0
    """打开并初始化摄像头，设置 FOURCC/FPS/分辨率，返回 (cap, 实际FOURCC)。"""
    logger.info(f"[CAMERA] 打开并初始化设备: {camera_path} (V4L2)")
    
    device_path = camera_path
    if not os.path.exists(device_path):
        logger.error(f"摄像头设备节点 {device_path} 不存在。")
        return None, "NODE_NOT_FOUND"

    try:
        cap = cv2.VideoCapture(camera_path, cv2.CAP_V4L2)
    except Exception as e:
        logger.error(f"创建 VideoCapture 失败: {e}")
        return None, "OPEN_FAILED_EXCEPTION"

    if not cap.isOpened():
        logger.error(f"无法打开摄像头 {camera_path}")
        return None, "OPEN_FAILED"

    effective_fourcc = "NOT_SET"
    if req_fourcc_str:
        target_fourcc_int = cv2.VideoWriter_fourcc(*req_fourcc_str)
        set_camera_parameter(cap, cv2.CAP_PROP_FOURCC, target_fourcc_int, "FOURCC")
    
    set_camera_parameter(cap, cv2.CAP_PROP_FPS, 10, "FPS")
    # Try to reduce internal buffering/latency where supported
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    if shutdown_event.is_set(): cap.release(); return None, "SHUTDOWN_DURING_INIT"
    time.sleep(0.1) 
    try:
        current_fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    except Exception as e:
        logger.warning(f"读取 FOURCC 失败: {e}")
        current_fourcc_int = 0
    effective_fourcc = get_fourcc_str(current_fourcc_int)
    if req_fourcc_str and effective_fourcc.upper() != req_fourcc_str.upper():
         logger.warning(f"请求的FOURCC {req_fourcc_str} 未能精确设置，摄像头实际为 {effective_fourcc}")

    set_camera_parameter(cap, cv2.CAP_PROP_FRAME_WIDTH, width, "Width")
    if shutdown_event.is_set(): cap.release(); return None, "SHUTDOWN_DURING_INIT"
    set_camera_parameter(cap, cv2.CAP_PROP_FRAME_HEIGHT, height, "Height")
    if shutdown_event.is_set(): cap.release(); return None, "SHUTDOWN_DURING_INIT"
    
    time.sleep(0.2) 
    try:
        actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps_val = cap.get(cv2.CAP_PROP_FPS) 
        current_fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC)) 
    except Exception as e:
        logger.warning(f"读取相机属性失败: {e}")
        actual_width, actual_height, actual_fps_val, current_fourcc_int = width, height, 0.0, 0
    effective_fourcc = get_fourcc_str(current_fourcc_int)

    logger.info(f"[CAMERA] 初始化完成: {camera_path}")
    logger.info(f"[CAMERA] 请求参数 -> FOURCC: {req_fourcc_str if req_fourcc_str else 'N/A'}, 尺寸: {width}x{height}")
    logger.info(f"[CAMERA] 实际参数 -> FOURCC: {effective_fourcc} ({hex(current_fourcc_int)}), "
                f"尺寸: {actual_width}x{actual_height}, "
                f"报告FPS: {actual_fps_val:.2f}")
    
    if actual_width != width or actual_height != height:
        logger.error(f"摄像头实际分辨率 {actual_width}x{actual_height} 与请求的 {width}x{height} 不符！")
    
    return cap, effective_fourcc

def add_timestamp_to_frame(frame_to_modify, timestamp_format_str): # Identical to v2.0.0
    """在图像右下角叠加时间戳，返回新图像。"""
    if not ENABLE_TIMESTAMP:
        return frame_to_modify
    timestamp_text = datetime.now().strftime(timestamp_format_str)
    font = cv2.FONT_HERSHEY_SIMPLEX
    img_h, img_w = frame_to_modify.shape[:2]
    font_scale = (img_h / 1080.0) * 1.0
    if font_scale < 0.5: font_scale = 0.5
    thickness = max(1, int(font_scale * 2.0)) 
    margin = max(10, int(img_h * 0.05)) 

    text_size, baseline = cv2.getTextSize(timestamp_text, font, font_scale, thickness)
    text_width, text_height = text_size
    org_x = img_w - text_width - margin
    org_y = img_h - margin 
    
    cv2.putText(frame_to_modify, timestamp_text, (org_x, org_y), font, font_scale, 
                (255, 255, 255), thickness, cv2.LINE_AA, bottomLeftOrigin=False)
    return frame_to_modify

def are_frames_similar(frame1: np.ndarray | None,
                       frame2: np.ndarray | None,
                       similarity_diff_rate_threshold_int: int) -> bool:
    """比较两帧图像是否“足够相似”（变化很小）。

    方法：
    1) 必要时降采样到较小宽度以节省 CPU
    2) 转灰度，做绝对差阈值化
    3) 形态学膨胀，再提取轮廓，累计有效轮廓面积占比
    4) 若面积差异率 <= 阈值（单位：百分比×1/100），视为相似

    返回 False 的情况：
    - 任一帧不是有效的 numpy 图像
    - 尺寸对齐失败或颜色转换失败
    - 实际差异率超阈值
    """

    # 1. 检查输入帧的有效性
    # cap.read() 返回的 ret, frame。如果 ret 是 False，frame可能是 None 或无效数据
    if not isinstance(frame1, np.ndarray) or frame1.size == 0:
        logger.debug("are_frames_similar: frame1 无效 (非 NumPy 数组、None 或空数组)。返回 False。")
        return False
    if not isinstance(frame2, np.ndarray) or frame2.size == 0:
        logger.debug("are_frames_similar: frame2 无效 (非 NumPy 数组、None 或空数组)。返回 False。")
        return False

    # 2. 如有必要先下采样以降低分辨率（节省CPU），再确保尺寸相同
    h1, w1 = frame1.shape[:2]
    h2, w2 = frame2.shape[:2]
    frame2_resized = frame2

    # 下采样比例（按宽度上限等比缩小）
    if w1 > SIMILARITY_MAX_WIDTH:
        scale1 = SIMILARITY_MAX_WIDTH / float(w1)
        new_w1, new_h1 = int(w1 * scale1), int(h1 * scale1)
        try:
            frame1 = cv2.resize(frame1, (new_w1, new_h1), interpolation=cv2.INTER_AREA)
        except cv2.error:
            return False
        h1, w1 = frame1.shape[:2]
    if w2 > SIMILARITY_MAX_WIDTH:
        scale2 = SIMILARITY_MAX_WIDTH / float(w2)
        new_w2, new_h2 = int(w2 * scale2), int(h2 * scale2)
        try:
            frame2 = cv2.resize(frame2, (new_w2, new_h2), interpolation=cv2.INTER_AREA)
        except cv2.error:
            return False
        h2, w2 = frame2.shape[:2]

    if (h1, w1) != (h2, w2):
        logger.debug(f"are_frames_similar: 帧尺寸不同。将 frame2 从 ({w2}x{h2}) 调整为 ({w1}x{h1})。")
        try:
            frame2_resized = cv2.resize(frame2, (w1, h1), interpolation=cv2.INTER_AREA)
        except cv2.error as e:
            logger.error(f"are_frames_similar: 调整 frame2 尺寸失败: {e}。返回 False。")
            return False # 调整尺寸失败，无法比较

    # 3. 转换为灰度图进行比较
    #    确保处理单通道和三通道输入，最终得到单通道灰度图
    try:
        if frame1.ndim == 3 and frame1.shape[2] == 3: # BGR
            gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        elif frame1.ndim == 2: # Already grayscale
            gray1 = frame1
        else:
            logger.warning(f"are_frames_similar: frame1 格式未知 (shape: {frame1.shape})。返回 False。")
            return False

        if frame2_resized.ndim == 3 and frame2_resized.shape[2] == 3: # BGR
            gray2 = cv2.cvtColor(frame2_resized, cv2.COLOR_BGR2GRAY)
        elif frame2_resized.ndim == 2: # Already grayscale
            gray2 = frame2_resized
        else:
            logger.warning(f"are_frames_similar: frame2_resized 格式未知 (shape: {frame2_resized.shape})。返回 False。")
            return False
    except cv2.error as e:
        logger.error(f"are_frames_similar: 转换为灰度图失败: {e}。返回 False。")
        return False

    # 3.5 再次确保尺寸与 dtype 一致
    try:
        if gray1.shape != gray2.shape:
            logger.debug(f"are_frames_similar: 灰度尺寸不一致 {gray1.shape} vs {gray2.shape}，调整 gray2 以匹配 gray1。")
            gray2 = cv2.resize(gray2, (gray1.shape[1], gray1.shape[0]), interpolation=cv2.INTER_AREA)
        if gray1.dtype != gray2.dtype:
            logger.debug(f"are_frames_similar: 灰度 dtype 不一致 {gray1.dtype} vs {gray2.dtype}，转换 gray2 dtype。")
            gray2 = gray2.astype(gray1.dtype, copy=False)
    except Exception as e:
        logger.error(f"are_frames_similar: 对齐尺寸/dtype 时异常: {e}。返回 False。")
        return False

    # 4. 计算轮廓面积差异率
    image_total_pixels = gray1.shape[0] * gray1.shape[1]
    if image_total_pixels == 0:
        logger.debug("are_frames_similar: 图像总像素为0。返回 False。")
        return False

    try:
        abs_diff_img = cv2.absdiff(gray1, gray2)
    except cv2.error as e:
        logger.error(f"are_frames_similar: absdiff 失败: {e}。返回 False。")
        return False
    _, thresh_img = cv2.threshold(abs_diff_img,
                                  DEFAULT_CONTOUR_PIXEL_THRESHOLD,
                                  255,
                                  cv2.THRESH_BINARY)

    dilated_thresh_img = cv2.dilate(thresh_img,
                                    CONTOUR_KERNEL,
                                    iterations=DEFAULT_CONTOUR_DILATION_ITERATIONS)

    contours, _ = cv2.findContours(dilated_thresh_img,
                                   cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    total_significant_contour_area = 0.0
    for contour in contours:
        current_contour_area = cv2.contourArea(contour)
        if current_contour_area > DEFAULT_CONTOUR_MIN_AREA_FILTER:
            total_significant_contour_area += current_contour_area

    contour_area_actual_diff_rate_percent = (total_significant_contour_area / image_total_pixels) * 100.0

    # 5. 根据阈值判断是否相似
    # 将传入的整数阈值转换为实际百分比上限
    similarity_threshold_as_percentage = similarity_diff_rate_threshold_int / 100.0

    logger.debug(f"are_frames_similar: 实际轮廓差异率: {contour_area_actual_diff_rate_percent:.4f}%, " +
                 f"设定的相似度差异上限: {similarity_threshold_as_percentage:.4f}% " +
                 f"(传入整数: {similarity_diff_rate_threshold_int})")

    if contour_area_actual_diff_rate_percent <= similarity_threshold_as_percentage:
        # 差异小或等于阈值，认为相似 (变化小)
        # logger.info(f"are_frames_similar: 差异率达标{contour_area_actual_diff_rate_percent:.4f}%，判定为相似 (True)。")
        return True
    else:
        # 差异大，认为不相似 (变化大)
        # logger.info(f"are_frames_similar: 差异率超标{contour_area_actual_diff_rate_percent:.4f}%，判定为不相似 (False)。")
        return False

def process_and_save_frame(state: 'ServiceState', frame_data, effective_fourcc, base_save_dir, jpeg_quality_val, ts_format):
    """处理一帧图像并尝试保存。

    - 必要时做色彩空间转换/灰度转 BGR
    - 与上一显著帧比较，相似则跳过保存
    - 添加时间戳，按照年月/日分目录保存
    - 失败计数进入 state，不抛异常
    """

    if frame_data is None:
        logger.error("接收到空帧，无法处理。")
        return None

    logger.debug(f"接收到帧。原始 - 尺寸: {frame_data.shape}, dtype: {frame_data.dtype}, FOURCC上下文: {effective_fourcc}")
    processed_frame = frame_data

    # try:
    #    target_size = (1920, 1080)
    #    if frame_data.shape[1] != target_size[0] or frame_data.shape[0] != target_size[1]:
    #        processed_frame = cv2.resize(frame_data, target_size, interpolation=cv2.INTER_LANCZOS4)
    #        logger.info(f"图像缩放完成（高精度），目标尺寸: {target_size}")
    #except Exception as e:
    #    logger.error(f"图像缩放失败: {e}", exc_info=True)

    if effective_fourcc.upper() in ['YUYV', 'YUY2'] and \
       not (processed_frame.ndim == 3 and processed_frame.shape[2] == 3):
        logger.info(f"帧的FOURCC上下文为 {effective_fourcc} 且非BGR，尝试YUV->BGR转换。帧Shape: {processed_frame.shape}")
        try:
            if processed_frame.shape[1] == DEFAULT_WIDTH * 2 and processed_frame.ndim == 2: 
                 processed_frame = cv2.cvtColor(processed_frame, cv2.COLOR_YUV2BGR_YUYV) 
            elif processed_frame.ndim == 3 and processed_frame.shape[2] == 2: 
                 processed_frame = cv2.cvtColor(processed_frame, cv2.COLOR_YUV2BGR_YUYV)
            else:
                logger.warning(f"未知的YUYV帧结构: {processed_frame.shape}，无法自动转换。")
            
            if processed_frame.ndim == 3 and processed_frame.shape[2] == 3:
                 logger.info(f"YUV 转换为 BGR 成功. 新图像尺寸: {processed_frame.shape}")
            else: 
                 logger.error(f"YUV 转换为 BGR 后尺寸/通道数不正确: {processed_frame.shape}. 保留原始帧。")
                 processed_frame = frame_data 
        except cv2.error as e:
            logger.error(f"YUV 转换为 BGR 失败: {e}. 将使用原始帧。", exc_info=True)
            processed_frame = frame_data
    elif processed_frame.ndim == 2: 
        logger.info(f"图像是单通道灰度图 (shape: {processed_frame.shape})，转换为BGR。")
        processed_frame = cv2.cvtColor(processed_frame, cv2.COLOR_GRAY2BGR)
    elif not (processed_frame.ndim == 3 and processed_frame.shape[2] == 3):
        logger.warning(f"图像格式未知或非预期 (shape: {processed_frame.shape}). 尝试直接处理。")

    # 判断是否接近，如果和上一次成功保存类似则直接跳过
    # 使用上一显著帧的副本，避免被后续时间戳叠加修改
    prev_sig_frame = None
    try:
        if isinstance(state.last_significant_frame, np.ndarray):
            prev_sig_frame = state.last_significant_frame.copy()
    except Exception:
        prev_sig_frame = state.last_significant_frame

    frames_are_indeed_similar = are_frames_similar(
        prev_sig_frame,
        processed_frame,
        SIMILARITY_THRESHOLD_PERCENT_INT
    )
    if frames_are_indeed_similar:
        #if logger: # logger.info(f"当前帧与上一显著帧相似 (差异 <= {SIMILARITY_THRESHOLD_PERCENT_INT/100.0:.2f}%)，不保存。")
        perform_save_this_frame = False
        return "SIMILARITY"
    else:
        # if logger: logger.info(f"当前帧与上一显著帧不相似 (差异 > {SIMILARITY_THRESHOLD_PERCENT_INT/100.0:.2f}%)，将保存。")
        perform_save_this_frame = True
        # 保存未加时间戳前的帧，以避免时间戳影响相似度判断
        try:
            state.last_significant_frame = processed_frame.copy() if isinstance(processed_frame, np.ndarray) else processed_frame
        except Exception:
            state.last_significant_frame = processed_frame

    try:
        frame_with_timestamp = add_timestamp_to_frame(processed_frame, ts_format)
    except Exception as e:
        logger.error(f"添加时间戳失败: {e}. 将保存不带时间戳的图像。", exc_info=True)
        frame_with_timestamp = processed_frame

    now = datetime.now()
    save_subdir = os.path.join(base_save_dir, now.strftime("%Y-%m"), now.strftime("%d"))
    
    try:
        if not os.path.isdir(save_subdir):
            os.makedirs(save_subdir, exist_ok=True)
    except OSError as e:
        logger.error(f"创建目录 {save_subdir} 失败: {e}。")
        # 尝试回退目录
        if IMAGE_SAVE_FALLBACK_DIR:
            try:
                fallback_subdir = os.path.join(IMAGE_SAVE_FALLBACK_DIR, now.strftime("%Y-%m"), now.strftime("%d"))
                os.makedirs(fallback_subdir, exist_ok=True)
                save_subdir = fallback_subdir
                logger.warning(f"使用回退保存目录: {save_subdir}")
            except OSError as e_fb:
                logger.error(f"创建回退目录失败: {e_fb}。无法保存图像。")
                state.consecutive_imwrite_failures += 1
                return None
        else:
            state.consecutive_imwrite_failures += 1
            return None

    #time_str = now.strftime("%H%M%S_%f") 
    #filename = f"{time_str}.jpg" 
    #filepath = os.path.join(save_subdir, filename)
    file_timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
    filename = f"capture_{file_timestamp}.jpg"
    filepath = os.path.join(save_subdir, filename) # 保存到年月子目录中

    logger.debug(f"尝试将图像保存到: {filepath} (质量: {jpeg_quality_val})")
    try:
        save_success = cv2.imwrite(filepath, frame_with_timestamp, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality_val])
        if save_success:
            logger.debug(f"图像成功保存为JPEG: {filepath}")
            state.consecutive_imwrite_failures = 0
            try:
                os.chmod(filepath, 0o644) 
                logger.debug(f"文件权限设置为 644: {filepath}")
            except OSError as e:
                logger.warning(f"设置文件 {filepath} 权限失败: {e}")
            # 可选：最小 JPEG 文件大小检查
            if MIN_JPEG_SAVE_SIZE_BYTES and MIN_JPEG_SAVE_SIZE_BYTES > 0:
                try:
                    actual_size = os.path.getsize(filepath)
                except OSError as e_sz:
                    logger.error(f"读取文件大小失败: {e_sz}")
                    actual_size = 0
                if actual_size < MIN_JPEG_SAVE_SIZE_BYTES:
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
                    logger.error(
                        f"JPEG 文件过小({actual_size}B < {MIN_JPEG_SAVE_SIZE_BYTES}B)，判定为失败。"
                    )
                    state.consecutive_imwrite_failures += 1
                    return None
            return filepath
        else:
            logger.error(f"cv2.imwrite 保存JPEG图像失败 (返回False): {filepath}")
            state.consecutive_imwrite_failures += 1
            return None
    except Exception as e:
        logger.error(f"cv2.imwrite 保存图像时发生异常: {e}", exc_info=True)
        state.consecutive_imwrite_failures += 1
        return None

# --- Disk Space Management ---
def get_oldest_day_dir(base_dir: str) -> str | None: # Identical to v2.0.0
    """在以 YYYY-MM/DD 组织的目录结构下，找到最老的日期目录路径。"""
    all_day_paths = []
    if not os.path.isdir(base_dir):
        logger.warning(f"get_oldest_day_dir: Base directory '{base_dir}' not found or not a directory.")
        return None
    for ym_dir_name in sorted(os.listdir(base_dir)):
        ym_path = os.path.join(base_dir, ym_dir_name)
        if os.path.isdir(ym_path) and len(ym_dir_name) == 7 and ym_dir_name[4] == '-': # Valid YYYY-MM
            for d_dir_name in sorted(os.listdir(ym_path)):
                d_path = os.path.join(ym_path, d_dir_name)
                if os.path.isdir(d_path) and len(d_dir_name) == 2: # Valid DD
                    try: # Ensure DD is integer, further validating format
                        int(d_dir_name) 
                        all_day_paths.append(d_path)
                    except ValueError:
                        logger.debug(f"Skipping non-day directory: {d_path}")
                        continue
    if all_day_paths:
        return all_day_paths[0] # Lexicographical sort of YYYY-MM/DD is chronological
    return None

def check_and_manage_disk_space(): # Identical to v2.0.0 logic
    """检查磁盘占用并在超过阈值时删除最旧日期目录（批量）。"""
    try:
        usage = shutil.disk_usage(IMAGE_STORAGE_MONITOR_PATH)
        percent_used = (usage.used / usage.total) * 100
        logger.info(f"[DISK] 监控: {IMAGE_STORAGE_MONITOR_PATH} - Total: {usage.total // (1024**3)}GB, "
                    f"Used: {usage.used // (1024**3)}GB ({percent_used:.1f}%), "
                    f"Free: {usage.free // (1024**3)}GB")

        if percent_used > IMAGE_STORAGE_MAX_USAGE_PERCENT:
            logger.warning(f"[DISK] 使用率 ({percent_used:.1f}%) 超阈值 ({IMAGE_STORAGE_MAX_USAGE_PERCENT}%). "
                           f"尝试清理 {IMAGE_STORAGE_CLEANUP_BATCH_DAYS} 个最旧的日期目录...")
            
            for i in range(IMAGE_STORAGE_CLEANUP_BATCH_DAYS):
                if shutdown_event.is_set(): 
                    logger.info("Shutdown requested during disk cleanup.")
                    break 
                
                oldest_dir_to_delete = get_oldest_day_dir(IMAGE_SAVE_BASE_DIR)
                if oldest_dir_to_delete:
                    logger.warning(f"[DISK] 准备删除最旧日期目录 ({i+1}/{IMAGE_STORAGE_CLEANUP_BATCH_DAYS}): {oldest_dir_to_delete}")
                    try:
                        shutil.rmtree(oldest_dir_to_delete)
                        logger.info(f"[DISK] 已删除目录: {oldest_dir_to_delete}")
                    except OSError as e:
                        logger.error(f"删除目录 {oldest_dir_to_delete} 失败: {e}", exc_info=True)
                        break 
                else:
                    logger.warning("[DISK] 无可删除的旧日期目录。")
                    break 
    except FileNotFoundError:
        logger.error(f"[DISK] 监控路径不存在: {IMAGE_STORAGE_MONITOR_PATH}")
    except Exception as e:
        logger.error(f"[DISK] 检查/清理异常: {e}", exc_info=True)

# --- Get Current Capture Interval ---
def get_current_capture_interval() -> float: # support sub-second intervals like 2.5s
    """根据时间表返回当前拍摄间隔（秒，float）。"""
    now_time = datetime.now().time()
    for schedule_item in CAPTURE_SCHEDULE_CONFIG:
        if now_time < schedule_item["end_time_exclusive"]:
            return schedule_item["interval_seconds"]
    return DEFAULT_INTERVAL_LATE_NIGHT

# --- Main Service Logic ---
def run_capture_service():
    """图像采集主循环：自恢复，不退出。

    - 按时间表控制间隔
    - 设备失联/读帧失败/写盘失败均有退避与重试
    - 周期性心跳输出健康指标
    """
    global shutdown_event

    state = ServiceState()
    cap = None
    effective_fourcc = "NOT_SET_INITIALLY"
    init_failures = 0
    last_disk_check_time = 0.0

    logger.debug(f"[SERVICE] 主循环启动。")
    # ... (logging of schedule, camera target etc. from v2.0.0)
    logger.info(f"  时间表: " + ", ".join([f"<{s['end_time_exclusive'].strftime('%H:%M')} ({s['interval_seconds']}s)" for s in CAPTURE_SCHEDULE_CONFIG]) + 
                f", >=22:00 ({DEFAULT_INTERVAL_LATE_NIGHT}s)")
    logger.info(f"  目标摄像头: {DEFAULT_CAMERA_DEVICE_PATH}")
    logger.info(f"  摄像头参数：{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}, FOURCC: {REQUESTED_FOURCC}")
    logger.info(f"  图片保存至: {IMAGE_SAVE_BASE_DIR} (JPEG质量: {JPEG_SAVE_QUALITY})")
    logger.info(f"  磁盘监控: 路径 '{IMAGE_STORAGE_MONITOR_PATH}', 阈值 {IMAGE_STORAGE_MAX_USAGE_PERCENT}%")


    last_capture_time = time.monotonic() 

    while not shutdown_event.is_set():
        current_interval = get_current_capture_interval()
        try:
            current_monotonic_time = time.monotonic()
            if current_monotonic_time - last_disk_check_time > DISK_CHECK_INTERVAL_SECONDS:
                check_and_manage_disk_space()
                last_disk_check_time = current_monotonic_time

            if cap is None or not cap.isOpened():
                logger.info("[CAMERA] 未连接或需要重新初始化...")
                if cap: cap.release() 
                
                cap, effective_fourcc = initialize_camera(
                    DEFAULT_CAMERA_DEVICE_PATH, DEFAULT_WIDTH, DEFAULT_HEIGHT, REQUESTED_FOURCC
                )
                if not cap:
                    init_failures += 1
                    logger.error(f"摄像头初始化失败 (连续第 {init_failures} 次)。")
                    if init_failures >= CAMERA_INIT_FAILURE_MAX_CONSECUTIVE:
                        logger.critical(f"已连续 {init_failures} 次无法初始化摄像头。将等待较长时间 ({CAMERA_INIT_LONG_BACKOFF_SECONDS}s) 后重试。")
                        shutdown_event.wait(CAMERA_INIT_LONG_BACKOFF_SECONDS)
                        init_failures = 0 
                    else:
                        shutdown_event.wait(CAMERA_INIT_RETRY_DELAY_SECONDS)
                    continue 
                
                init_failures = 0 
                last_capture_time = time.monotonic() 
                state.consecutive_read_failures = 0
                state.effective_fourcc = effective_fourcc
                # 记录当次应用的相机请求参数，用于后续热重载是否需要重建
                state.applied_camera_device = DEFAULT_CAMERA_DEVICE_PATH
                state.applied_width = DEFAULT_WIDTH
                state.applied_height = DEFAULT_HEIGHT
                state.applied_requested_fourcc = REQUESTED_FOURCC

            elapsed_since_last_capture = time.monotonic() - last_capture_time
            wait_time = current_interval - elapsed_since_last_capture

            if wait_time > 0:
                # logger.info(f"当前时间: {datetime.now().strftime('%H:%M:%S')}, 间隔: {current_interval}s. 还需 {wait_time:.2f} 秒...")
                shutdown_event.wait(timeout=wait_time) 
                if shutdown_event.is_set(): break 
            
            if shutdown_event.is_set(): break 

            last_capture_time = time.monotonic() 
            logger.debug(f"[CAPTURE] 尝试捕获图像帧 (间隔: {current_interval}s)...")

            for _ in range(4):
                # 清空缓冲帧
                cap.grab();
            t0 = time.perf_counter()
            try:
                ret, frame = cap.read()
            except Exception as e:
                logger.error(f"读取图像帧异常: {e}")
                ret, frame = False, None

            if not ret or frame is None:
                # 节流日志，减少重复 I/O
                if state.consecutive_read_failures % LOG_EVERY_N_READ_FAILURES == 0:
                    logger.error("[CAPTURE] 无法从摄像头获取图像帧，可能断开或异常。")
                state.consecutive_read_failures += 1
                if state.consecutive_read_failures % LOG_EVERY_N_READ_FAILURES == 0:
                    logger.info(f"[CAPTURE] 连续读帧失败次数: {state.consecutive_read_failures}")
                if cap: cap.release()
                cap = None 
                
                if state.consecutive_read_failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    logger.critical(f"已连续 {state.consecutive_read_failures} 次无法读取帧。将等待较长时间 ({READ_FAILURE_LONG_BACKOFF_SECONDS}s) 后尝试重连。")
                    shutdown_event.wait(READ_FAILURE_LONG_BACKOFF_SECONDS)
                    state.consecutive_read_failures = 0
                else:
                    shutdown_event.wait(FRAME_READ_ERROR_RETRY_DELAY_SECONDS) 
                continue
            
            state.consecutive_read_failures = 0

            try:
                saved_filepath = process_and_save_frame(
                    state, frame, effective_fourcc, IMAGE_SAVE_BASE_DIR, 
                    JPEG_SAVE_QUALITY, TIMESTAMP_FORMAT
                )
            except Exception as e:
                logger.error(f"处理与保存帧异常: {e}", exc_info=True)
                saved_filepath = None
            if saved_filepath == "SIMILARITY":
                logger.debug("[SAVE] 图像接近，跳过保存")
            elif isinstance(saved_filepath, str) and saved_filepath.lower().endswith(".jpg"):
                logger.debug(f"[SAVE] 成功保存: {saved_filepath}")
                # consecutive_imwrite_failures is reset inside process_and_save_frame
                state.last_saved_filepath = saved_filepath
            else:
                logger.warning("[SAVE] 本次图像未能成功保存。")
                # consecutive_imwrite_failures is incremented inside process_and_save_frame
                if state.consecutive_imwrite_failures >= MAX_CONSECUTIVE_IMWRITE_FAILURES:
                    logger.critical(f"[SAVE] 连续 {state.consecutive_imwrite_failures} 次保存失败，尝试磁盘清理并退避后继续。")
                    try:
                        check_and_manage_disk_space()
                        state.total_disk_cleanup_batches += IMAGE_STORAGE_CLEANUP_BATCH_DAYS
                    except Exception as e_clean:
                        logger.error(f"执行磁盘清理时异常: {e_clean}")
                    shutdown_event.wait(IMWRITE_FAILURE_BACKOFF_SECONDS)
                    state.consecutive_imwrite_failures = 0
                    continue

            # 记录耗时
            t1 = time.perf_counter()
            elapsed_ms = (t1 - t0) * 1000.0
            # 控制滑动窗口规模，避免无限增长
            state.processing_times_ms.append(elapsed_ms)

            # 心跳日志：定期打印运行健康信息
            now_mono = time.monotonic()
            if now_mono - state.last_heartbeat_monotonic >= HEARTBEAT_INTERVAL_SECONDS:
                log_heartbeat(state, current_interval)
                state.last_heartbeat_monotonic = now_mono

            # 健康快照：周期性输出 JSON 文件，供外部探针读取
            try:
                if now_mono - state.last_health_dump_monotonic >= HEARTBEAT_INTERVAL_SECONDS:
                    health = {
                        "boot_id": state.boot_id,
                        "ts": time.time(),
                        "interval": current_interval,
                        "read_failures": state.consecutive_read_failures,
                        "imwrite_failures": state.consecutive_imwrite_failures,
                        "disk_cleanup_batches": state.total_disk_cleanup_batches,
                        "last_saved": state.last_saved_filepath,
                        "fourcc": state.effective_fourcc,
                    }
                    health_path = os.path.join(LOG_DIR, "health.json")
                    with open(health_path, "w", encoding="utf-8") as hf:
                        json.dump(health, hf, ensure_ascii=False)
                    state.last_health_dump_monotonic = now_mono
            except Exception:
                # 健康文件输出失败不影响主流程
                pass

            # 配置热重载：若关键相机参数发生变化，则触发安全重建
            if CONFIG_ENABLED and reload_event.is_set():
                try:
                    logger.info("执行配置热重载...")
                    prev_device = DEFAULT_CAMERA_DEVICE_PATH
                    prev_w, prev_h = DEFAULT_WIDTH, DEFAULT_HEIGHT
                    prev_fourcc = REQUESTED_FOURCC
                    load_and_apply_yaml_config(CONFIG_PATH, runtime_reload=True)
                    logger.info("配置热重载完成。")

                    # 检查是否需要重建相机：设备路径、分辨率或 FOURCC 发生变化
                    need_reopen = False
                    if (state.applied_camera_device and DEFAULT_CAMERA_DEVICE_PATH != state.applied_camera_device) or \
                       (state.applied_width and DEFAULT_WIDTH != state.applied_width) or \
                       (state.applied_height and DEFAULT_HEIGHT != state.applied_height) or \
                       (state.applied_requested_fourcc and REQUESTED_FOURCC.upper() != state.applied_requested_fourcc.upper()):
                        need_reopen = True

                    if need_reopen:
                        logger.info("[CAMERA] 检测到关键参数变化，安全重建摄像头 (device/size/fourcc)")
                        try:
                            if cap:
                                cap.release()
                        except Exception:
                            pass
                        cap = None
                        # 立即重新初始化（不等待下一轮）
                        cap, effective_fourcc = initialize_camera(
                            DEFAULT_CAMERA_DEVICE_PATH, DEFAULT_WIDTH, DEFAULT_HEIGHT, REQUESTED_FOURCC
                        )
                        if cap:
                            state.effective_fourcc = effective_fourcc
                            state.applied_camera_device = DEFAULT_CAMERA_DEVICE_PATH
                            state.applied_width = DEFAULT_WIDTH
                            state.applied_height = DEFAULT_HEIGHT
                            state.applied_requested_fourcc = REQUESTED_FOURCC
                            last_capture_time = time.monotonic()
                            logger.info("[CAMERA] 重建完成，新的有效 FOURCC: %s", effective_fourcc)
                        else:
                            logger.error("[CAMERA] 重建失败，将进入正常重试路径")
                except Exception as e:
                    logger.error(f"热重载失败: {e}")
                finally:
                    reload_event.clear()

        except cv2.error as e: 
            # 不退出，自恢复
            logger.error(f"[SERVICE] OpenCV 异常: {e}", exc_info=True)
            try:
                if cap: cap.release()
            except Exception:
                pass
            cap = None
            logger.info(f"[SERVICE] 因 OpenCV 错误，等待 {CAMERA_INIT_RETRY_DELAY_SECONDS}s 后重试。")
            shutdown_event.wait(CAMERA_INIT_RETRY_DELAY_SECONDS)
        except Exception as e: 
            # 不退出，自恢复
            logger.critical(f"[SERVICE] 未预料的严重错误: {e}", exc_info=True)
            try:
                if cap: cap.release() 
            except Exception:
                pass
            cap = None
            logger.info(f"[SERVICE] 因严重错误，等待 {CAMERA_INIT_LONG_BACKOFF_SECONDS}s 后重试。")
            shutdown_event.wait(CAMERA_INIT_LONG_BACKOFF_SECONDS)

    # Loop exited (likely due to shutdown_event)
    if cap and cap.isOpened():
        logger.info("[CAMERA] 正在释放资源...")
        cap.release()
    logger.info("[SERVICE] 主循环已停止。")


# --- Main Application Entry Point & CLI Argument Parsing ---
def main():
    """命令行入口：解析参数、初始化日志、可选加载配置并运行服务。"""
    global logger, PID_FILE_PATH, CONFIG_PATH, CONFIG_ENABLED # Allow modification if args change them
    global LOG_DIR, IMAGE_SAVE_BASE_DIR, IMAGE_STORAGE_MONITOR_PATH

    parser = argparse.ArgumentParser(description=f"{SCRIPT_NAME} - Image Capture Service (v{SCRIPT_VERSION})")
    parser.add_argument('action', nargs='?', choices=['start', 'stop', 'status', 'foreground'], 
                        default='foreground', 
                        help="Action: start (daemonize - for traditional init), stop, status, or foreground (default, for systemd/debug).")
    parser.add_argument('--pidfile', default=PID_FILE_PATH, 
                        help=f"Path to PID file (default: {PID_FILE_PATH})")
    parser.add_argument('--logdir', default=LOG_DIR, help=f"Path to log directory (default: {LOG_DIR})")
    parser.add_argument('--loglevel', default=LOG_LEVEL_CONFIG, choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help=f"Logging level (default: {LOG_LEVEL_CONFIG})")
    parser.add_argument('--config', default=CONFIG_PATH, help="Path to YAML config file (optional)")
    parser.add_argument('--use-config', action='store_true', help="Enable loading YAML config (default: disabled)")
    # For true daemonization with python-daemon, more args like --user, --group, --working-directory would be needed.
    # For now, 'start' is conceptual if not using systemd or a proper daemon library.

    args = parser.parse_args()
    
    # Resolve writable directories with fallbacks (do not crash on permission issues)
    home_dir = os.path.expanduser('~') or '/tmp'
    resolved_log_dir = args.logdir
    try:
        os.makedirs(resolved_log_dir, exist_ok=True)
    except Exception:
        resolved_log_dir = os.path.join(home_dir, 'camera', 'logs')
        os.makedirs(resolved_log_dir, exist_ok=True)

    # Image save dir may be overridden later by YAML; init with current value
    resolved_image_dir = IMAGE_SAVE_BASE_DIR
    try:
        os.makedirs(resolved_image_dir, exist_ok=True)
    except Exception:
        resolved_image_dir = os.path.join(home_dir, 'camera', 'captures')
        os.makedirs(resolved_image_dir, exist_ok=True)

    logger = setup_logging_system(resolved_log_dir, LOG_FILE_NAME, args.loglevel.upper(), 
                                  LOG_ROTATE_WHEN, LOG_ROTATE_INTERVAL, LOG_ROTATE_BACKUP_COUNT)

    # Apply YAML config overrides only when explicitly enabled
    # 更新全局配置路径与开关（用于热重载）
    CONFIG_PATH = args.config
    CONFIG_ENABLED = bool(args.use_config)
    if CONFIG_ENABLED:
        load_and_apply_yaml_config(args.config)

    # After YAML overrides, re-ensure dirs
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        LOG_DIR = resolved_log_dir
    try:
        os.makedirs(IMAGE_SAVE_BASE_DIR, exist_ok=True)
    except Exception:
        IMAGE_SAVE_BASE_DIR = resolved_image_dir
    global IMAGE_STORAGE_MONITOR_PATH
    IMAGE_STORAGE_MONITOR_PATH = IMAGE_SAVE_BASE_DIR

    # Resolve PID file path with fallback if not writable
    pid_dir = os.path.dirname(os.path.abspath(args.pidfile))
    try:
        os.makedirs(pid_dir, exist_ok=True)
        PID_FILE_PATH = os.path.abspath(args.pidfile)
    except Exception:
        PID_FILE_PATH = os.path.join('/tmp', os.path.basename(args.pidfile))

    # 统一输出一次运行配置概览（方便问题定位）
    try:
        logger.info(
            "[BOOT] config_enabled=%s, config_path='%s', image_dir='%s', log_dir='%s', device='%s', size=%dx%d, fourcc='%s', jpeg_quality=%d",
            str(CONFIG_ENABLED), CONFIG_PATH, IMAGE_SAVE_BASE_DIR, LOG_DIR, DEFAULT_CAMERA_DEVICE_PATH, DEFAULT_WIDTH, DEFAULT_HEIGHT, REQUESTED_FOURCC, JPEG_SAVE_QUALITY
        )
    except Exception:
        pass

    # Handle actions
    if args.action == 'start' or args.action == 'foreground':
        if args.action == 'start': # For 'start', implies daemonization is desired if not under systemd
            logger.info("Action 'start': Daemonization not yet fully implemented in this script for non-systemd. Running in foreground.")
            logger.info("For systemd, use Type=simple and run script directly (which defaults to foreground).")
            # If using python-daemon, daemonization context would be entered here.
            # For now, 'start' and 'foreground' behave similarly.
        
        logger.info(f"Starting {SCRIPT_NAME} v{SCRIPT_VERSION} in foreground mode...")
        
        # Check PID file before creating a new one
        if os.path.exists(PID_FILE_PATH):
            try:
                with open(PID_FILE_PATH, 'r') as f_pid_check:
                    existing_pid = int(f_pid_check.read().strip())
                os.kill(existing_pid, 0) # Check if process with this PID is running
                logger.warning(f"Service already running with PID {existing_pid} (found in {PID_FILE_PATH}). If this is wrong, remove PID file and restart.")
                sys.exit(1) 
            except (IOError, ValueError, ProcessLookupError): 
                logger.warning(f"Found stale PID file {PID_FILE_PATH}. Removing it.")
                try: os.remove(PID_FILE_PATH)
                except OSError as e_rm: logger.error(f"Error removing stale PID file {PID_FILE_PATH}: {e_rm}")
        
        create_pid_file()
        signal.signal(signal.SIGTERM, signal_term_handler)
        signal.signal(signal.SIGINT, signal_term_handler) 
        # 支持 SIGHUP 触发配置热重载
        try:
            signal.signal(signal.SIGHUP, signal_hup_handler)
        except Exception:
            # Windows 或不支持 SIGHUP 的平台忽略
            pass

        try:
            run_capture_service() 
        except Exception as e: 
            logger.critical(f"Unhandled exception in run_capture_service: {e}", exc_info=True)
            logger.critical(traceback.format_exc()) # Ensure full traceback is logged
            sys.exit(1) 
        finally:
            remove_pid_file() 
            logger.info(f"{SCRIPT_NAME} has shut down.")
            logging.shutdown() 
        sys.exit(0) 

    elif args.action == 'stop':
        logger.info("Action: stop")
        if not os.path.exists(PID_FILE_PATH):
            logger.warning(f"PID file {PID_FILE_PATH} not found. Service may not be running.")
            sys.exit(1) # Changed to 1 as "not running" is often a failure for "stop"
        terminated_successfully = False
        try:
            with open(PID_FILE_PATH, 'r') as f:
                pid = int(f.read().strip())
        except (IOError, ValueError) as e:
            logger.error(f"Invalid PID file {PID_FILE_PATH}: {e}. Remove it manually if service is stuck.")
            sys.exit(1)

        try:
            logger.info(f"Sending SIGTERM to process {pid}...")
            os.kill(pid, signal.SIGTERM)

            terminated_successfully = False
            logger.info(f"Waiting up to 10 seconds for process {pid} to terminate...")
            for i in range(10): # Wait up to 10 seconds
                time.sleep(1) # 等待1秒
                try:
                    os.kill(pid, 0) # 检查进程是否仍然存在
                    logger.debug(f"Process {pid} is still alive (attempt {i+1}/10).")
                except ProcessLookupError:
                    logger.info(f"Process {pid} terminated successfully within {i+1} second(s).")
                    terminated_successfully = True
                    break # 进程已终止，退出等待循环
                except Exception as e_check: # 其他检查时发生的错误
                    logger.error(f"Error checking status for PID {pid}: {e_check}")
                    # 发生错误，可能无法确认状态，也退出循环
                    break 

            if not terminated_successfully:
                # 如果10秒后循环正常结束，但进程未被确认终止（通常意味着os.kill(pid,0)没报错）
                logger.error(f"Process {pid} did not terminate after 10 seconds. Consider manual check or SIGKILL.")
                # 您原始代码中在这之后还有一个try/except ProcessLookupError来做最后确认，
                # 如果这里的逻辑是，即使循环完了，还想再确认一次，是可以保留的。
                # 但如果上面的循环因为ProcessLookupError退出了，terminated_successfully会是true。

        except ProcessLookupError: # 这个捕获的是 os.kill(pid, signal.SIGTERM) 时，进程就已经不存在的情况
            logger.info(f"Process {pid} was already terminated or PID was invalid when SIGTERM was attempted.")
        except PermissionError:
            logger.error(f"No permission to send signal to process {pid}. Are you root?")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error stopping service: {e}", exc_info=True)
            sys.exit(1)
        finally:
            if terminated_successfully and os.path.exists(PID_FILE_PATH):
                # 服务进程已被此 'stop' 命令确认终止，
                # 但其 PID 文件仍然存在（服务可能未能自行删除）。
                # 可以安全地将其作为陈旧 PID 文件移除。
                logger.warning(f"Process {pid} terminated, but its PID file {PID_FILE_PATH} still exists. Removing stale PID file.")
                remove_pid_file()
            elif not terminated_successfully and os.path.exists(PID_FILE_PATH):
                # 服务进程未被此 'stop' 命令确认终止，且 PID 文件仍然存在。
                # 此时不应自动删除 PID 文件，因为它可能仍然代表一个正在运行（但可能卡住）的进程。
                logger.warning(f"Process {pid} may still be running after stop attempt. PID file {PID_FILE_PATH} will not be removed by this 'stop' action.")
                # 如果 os.path.exists(PID_FILE_PATH) 为 False，说明PID文件已经被服务进程自己清掉了，或者一开始就没有，这里不需要额外操作。
    elif args.action == 'status':
        logger.info("Action: status")
        if not os.path.exists(PID_FILE_PATH):
            print(f"{SCRIPT_NAME} is not running (no PID file).")
            logger.info(f"{SCRIPT_NAME} is not running (no PID file).")
            sys.exit(3) 
        try:
            with open(PID_FILE_PATH, 'r') as f:
                pid = int(f.read().strip())
        except (IOError, ValueError):
            print(f"{SCRIPT_NAME} status unknown (invalid PID file: {PID_FILE_PATH}).")
            logger.warning(f"Invalid PID file: {PID_FILE_PATH}")
            sys.exit(4) 
        
        try:
            os.kill(pid, 0) 
            print(f"{SCRIPT_NAME} is running with PID {pid}.")
            logger.info(f"{SCRIPT_NAME} is running with PID {pid}.")
            sys.exit(0) 
        except ProcessLookupError:
            print(f"{SCRIPT_NAME} is not running (PID {pid} from stale PID file {PID_FILE_PATH} not found).")
            logger.warning(f"Stale PID file: process {pid} not found. Removing PID file.")
            remove_pid_file()
            sys.exit(3) 
        except PermissionError:
            print(f"{SCRIPT_NAME} with PID {pid} seems to be running, but no permission to check fully.")
            logger.warning(f"Running with PID {pid}, but no permission to check fully.")
            sys.exit(4) 
        except Exception as e:
            print(f"Error checking status for PID {pid}: {e}")
            logger.error(f"Error checking status for PID {pid}: {e}", exc_info=True)
            sys.exit(4) 

if __name__ == "__main__":
    # Basic signal handling for the main entry point itself, before run_capture_service sets its own
    signal.signal(signal.SIGTERM, signal_term_handler) 
    signal.signal(signal.SIGINT, signal_term_handler) 
    try:
        main()
    except SystemExit as e:
        # sys.exit() was called, possibly by argparse or our own logic.
        # The exit code is in e.code. Logging already done or not needed.
        # Simply re-raise to ensure the script exits with the correct code.
        if logger: logger.info(f"Script explicitly exited with status {e.code}.")
        else: print(f"Script explicitly exited with status {e.code}.", file=sys.stderr)
        raise
    except Exception as e:
        # Catch any other unexpected top-level exceptions
        if logger: # If logger was initialized
            logger.critical(f"Unhandled top-level exception caused script termination: {e}", exc_info=True)
            logger.critical(traceback.format_exc())
        else: # Logger not even initialized, print to stderr
            print(f"CRITICAL: Unhandled top-level exception: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
        sys.exit(1) # General error
    finally:
        if logger and not shutdown_event.is_set(): # If not already shutting down via signal
            logger.info("Script __main__ scope is finishing.")
        # Ensure logging handlers are flushed and closed if script exits this way
        # However, if run_capture_service exited cleanly, it would call logging.shutdown()
        # This is a final failsafe.
        if logging.getLogger(SCRIPT_NAME).hasHandlers(): # Check if logger was indeed set up
            logging.shutdown()
