import cv2
import numpy as np
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

# --- Script Information ---
SCRIPT_VERSION = "2.0.1"
SCRIPT_NAME = os.path.basename(__file__)

# --- Default Configuration ---
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
    {"end_time_exclusive": dt_time(21, 30),  "interval_seconds": 2.5},
    {"end_time_exclusive": dt_time(22, 30),  "interval_seconds": 5},
]
DEFAULT_INTERVAL_LATE_NIGHT = 10

PARAMETER_SET_RETRIES = 3
PARAMETER_SET_DELAY_SECONDS = 0.5
CAMERA_INIT_FAILURE_MAX_CONSECUTIVE = 5
CAMERA_INIT_RETRY_DELAY_SECONDS = 15
CAMERA_INIT_LONG_BACKOFF_SECONDS = 300

# MODIFICATION v2.0.1: New config for read failures
MAX_CONSECUTIVE_READ_FAILURES = 10 # Max consecutive cap.read() failures before longer pause
READ_FAILURE_LONG_BACKOFF_SECONDS = 60 # Longer pause after max read failures

FRAME_READ_ERROR_RETRY_DELAY_SECONDS = 5 # Short delay after a single read failure

# MODIFICATION v2.0.1: New config for imwrite failures
MAX_CONSECUTIVE_IMWRITE_FAILURES = 5 # Max consecutive cv2.imwrite() failures before shutdown

ENABLE_TIMESTAMP = True
TIMESTAMP_FORMAT = "%Y/%m/%d %H:%M:%S"

IMAGE_STORAGE_MONITOR_PATH = IMAGE_SAVE_BASE_DIR
IMAGE_STORAGE_MAX_USAGE_PERCENT = 85
IMAGE_STORAGE_CLEANUP_BATCH_DAYS = 1
DISK_CHECK_INTERVAL_SECONDS = 14400

# --- Global Variables ---
logger = None
shutdown_event = Event()
consecutive_imwrite_failures = 0 # MODIFICATION v2.0.1
consecutive_read_failures = 0    # MODIFICATION v2.0.1

# 默认的轮廓比较参数 (可以根据您的实际测试调整这些值)
DEFAULT_CONTOUR_PIXEL_THRESHOLD = 25   # 用于生成初始差异图的像素强度阈值
DEFAULT_CONTOUR_KERNEL_SIZE = (5, 5)   # 形态学膨胀操作的卷积核大小
DEFAULT_CONTOUR_DILATION_ITERATIONS = 2 # 膨胀操作的迭代次数
DEFAULT_CONTOUR_MIN_AREA_FILTER = 50.0 # 过滤掉小于此面积的差异轮廓

last_significant_frame = None
SIMILARITY_THRESHOLD_PERCENT_INT = 100 # 例如0.5%

# --- Logging Setup ---
# (setup_logging_system function from v2.0.0 is unchanged)
def setup_logging_system(log_dir, log_file_prefix, level_str, when, interval, backup_count):
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
    
    ## current_date_str = datetime.now().strftime("_%Y_%m_%d") # 例如：_2023_10_27
    ## current_date_str_new = datetime.now().strftime("%Y-%m-%d")
    ## actual_log_file_name = f"{log_file_prefix}.log.{current_date_str_new}"
    log_file_basename = f"{log_file_prefix}.log" # 例如 "image_capture.log"
    log_filepath = os.path.join(log_dir, log_file_basename) # 使用这个路径

    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s [%(levelname)-7s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s')
    
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
    
    logger.info(f"Logging initialized. Level: {level_str}. File: {log_filepath}")
    return logger

# --- PID File Management ---
# (create_pid_file, remove_pid_file functions from v2.0.0 are unchanged)
def create_pid_file():
    if not PID_FILE_PATH: return
    try:
        pid = os.getpid()
        os.makedirs(os.path.dirname(PID_FILE_PATH), exist_ok=True)
        with open(PID_FILE_PATH, 'w') as f:
            f.write(str(pid))
        logger.info(f"PID file created at {PID_FILE_PATH} with PID {pid}")
    except IOError as e:
        logger.error(f"Unable to create PID file {PID_FILE_PATH}: {e}")
        sys.exit(1)

def remove_pid_file():
    if not PID_FILE_PATH: return
    try:
        if os.path.exists(PID_FILE_PATH):
            os.remove(PID_FILE_PATH)
            logger.info(f"PID file {PID_FILE_PATH} removed.")
    except IOError as e:
        logger.warning(f"Unable to remove PID file {PID_FILE_PATH}: {e}")

# --- Signal Handling ---
def signal_term_handler(signum, frame):
    msg = f"接收到信号 {signal.Signals(signum).name} ({signum})，开始优雅停机..."
    if logger: logger.info(msg)
    else: print(msg, file=sys.stderr)
    shutdown_event.set()

# --- Core Camera and Image Processing Functions ---
# (get_fourcc_str, set_camera_parameter, initialize_camera, add_timestamp_to_frame
#  from v2.0.0 are good, ensure logger is used, and set_camera_parameter uses shutdown_event.wait)
def get_fourcc_str(fourcc_int: int) -> str: # Identical to v2.0.0
    if fourcc_int == 0: return "N/A (0)"
    try:
        return "".join([chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4)]).strip()
    except Exception as e:
        logger.warning(f"转换FOURCC整数 {hex(fourcc_int)} 到字符串失败: {e}")
        return f"Unknown ({hex(fourcc_int)})"

def set_camera_parameter(cap: cv2.VideoCapture, prop_id: int, value, param_name: str, 
                         retries: int = PARAMETER_SET_RETRIES, delay: float = PARAMETER_SET_DELAY_SECONDS) -> bool: # Identical to v2.0.0
    logger.info(f"尝试设置摄像头参数 {param_name} 为 {value}")
    for i in range(retries):
        cap.set(prop_id, value)
        if shutdown_event.wait(timeout=delay): return False # Shutdown requested

        actual_value = cap.get(prop_id)
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
    logger.info(f"尝试打开并初始化设备 {camera_path} (使用 V4L2 后端)")
    
    device_path = camera_path
    if not os.path.exists(device_path):
        logger.error(f"摄像头设备节点 {device_path} 不存在。")
        return None, "NODE_NOT_FOUND"

    cap = cv2.VideoCapture(camera_path, cv2.CAP_V4L2)

    if not cap.isOpened():
        logger.error(f"无法打开摄像头 {camera_path}")
        return None, "OPEN_FAILED"

    effective_fourcc = "NOT_SET"
    if req_fourcc_str:
        target_fourcc_int = cv2.VideoWriter_fourcc(*req_fourcc_str)
        set_camera_parameter(cap, cv2.CAP_PROP_FOURCC, target_fourcc_int, "FOURCC")
    
    set_camera_parameter(cap, cv2.CAP_PROP_FPS, 10, "FPS")

    if shutdown_event.is_set(): cap.release(); return None, "SHUTDOWN_DURING_INIT"
    time.sleep(0.1) 
    current_fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    effective_fourcc = get_fourcc_str(current_fourcc_int)
    if req_fourcc_str and effective_fourcc.upper() != req_fourcc_str.upper():
         logger.warning(f"请求的FOURCC {req_fourcc_str} 未能精确设置，摄像头实际为 {effective_fourcc}")

    set_camera_parameter(cap, cv2.CAP_PROP_FRAME_WIDTH, width, "Width")
    if shutdown_event.is_set(): cap.release(); return None, "SHUTDOWN_DURING_INIT"
    set_camera_parameter(cap, cv2.CAP_PROP_FRAME_HEIGHT, height, "Height")
    if shutdown_event.is_set(): cap.release(); return None, "SHUTDOWN_DURING_INIT"
    
    time.sleep(0.2) 
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps_val = cap.get(cv2.CAP_PROP_FPS) 
    current_fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC)) 
    effective_fourcc = get_fourcc_str(current_fourcc_int)

    logger.info(f"摄像头 {camera_path} 初始化完成。")
    logger.info(f"  请求参数 -> FOURCC: {req_fourcc_str if req_fourcc_str else 'N/A'}, 尺寸: {width}x{height}")
    logger.info(f"  实际参数 -> FOURCC: {effective_fourcc} ({hex(current_fourcc_int)}), "
                f"尺寸: {actual_width}x{actual_height}, "
                f"报告FPS: {actual_fps_val:.2f}")
    
    if actual_width != width or actual_height != height:
        logger.error(f"摄像头实际分辨率 {actual_width}x{actual_height} 与请求的 {width}x{height} 不符！")
    
    return cap, effective_fourcc

def add_timestamp_to_frame(frame_to_modify, timestamp_format_str): # Identical to v2.0.0
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
    """
    比较两个帧的相似度，基于轮廓面积差异率。
    帧的顺序无关。

    参数:
        frame1: 第一个帧 (NumPy array) 或 None。
        frame2: 第二个帧 (NumPy array) 或 None。
        similarity_diff_rate_threshold_int (int): 相似度百分比阈值。
            这是一个整数，例如 50 代表差异率上限为 0.50%。
            如果实际差异率 <= 此阈值对应的百分比，则认为帧相似。

    返回:
        bool:
            - 如果任一帧无法解析为有效图像 (例如 None 或类型不对)，返回 False (不相似/无法比较)。
            - 如果轮廓面积差异率 <= (similarity_diff_rate_threshold_int / 100.0)%，返回 True (相似/变化小)。
            - 否则 (差异率较大)，返回 False (不相似/变化大)。
    """

    # 1. 检查输入帧的有效性
    # cap.read() 返回的 ret, frame。如果 ret 是 False，frame可能是 None 或无效数据
    if not isinstance(frame1, np.ndarray) or frame1.size == 0:
        logger.debug("are_frames_similar: frame1 无效 (非 NumPy 数组、None 或空数组)。返回 False。")
        return False
    if not isinstance(frame2, np.ndarray) or frame2.size == 0:
        logger.debug("are_frames_similar: frame2 无效 (非 NumPy 数组、None 或空数组)。返回 False。")
        return False

    # 2. 确保图像尺寸相同 (将 frame2 调整为 frame1 的尺寸)
    h1, w1 = frame1.shape[:2]
    h2, w2 = frame2.shape[:2]
    frame2_resized = frame2

    if (h1, w1) != (h2, w2):
        return False
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

    # 4. 计算轮廓面积差异率
    image_total_pixels = gray1.shape[0] * gray1.shape[1]
    if image_total_pixels == 0:
        logger.debug("are_frames_similar: 图像总像素为0。返回 False。")
        return False

    abs_diff_img = cv2.absdiff(gray1, gray2)
    _, thresh_img = cv2.threshold(abs_diff_img,
                                  DEFAULT_CONTOUR_PIXEL_THRESHOLD,
                                  255,
                                  cv2.THRESH_BINARY)

    kernel = np.ones(DEFAULT_CONTOUR_KERNEL_SIZE, np.uint8)
    dilated_thresh_img = cv2.dilate(thresh_img,
                                    kernel,
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

def process_and_save_frame(frame_data, effective_fourcc, base_save_dir, jpeg_quality_val, ts_format): # Identical to v2.0.0
    global consecutive_imwrite_failures # MODIFICATION v2.0.1
    global last_significant_frame

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
    frames_are_indeed_similar = are_frames_similar(
        last_significant_frame,
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
        last_significant_frame = processed_frame

    try:
        frame_with_timestamp = add_timestamp_to_frame(processed_frame.copy(), ts_format)
    except Exception as e:
        logger.error(f"添加时间戳失败: {e}. 将保存不带时间戳的图像。", exc_info=True)
        frame_with_timestamp = processed_frame

    now = datetime.now()
    save_subdir = os.path.join(base_save_dir, now.strftime("%Y-%m"), now.strftime("%d"))
    
    try:
        os.makedirs(save_subdir, exist_ok=True) 
    except OSError as e:
        logger.error(f"创建目录 {save_subdir} 失败: {e}. 无法保存图像。")
        consecutive_imwrite_failures +=1 # MODIFICATION v2.0.1
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
            consecutive_imwrite_failures = 0 # MODIFICATION v2.0.1: Reset on success
            try:
                os.chmod(filepath, 0o644) 
                logger.debug(f"文件权限设置为 644: {filepath}")
            except OSError as e:
                logger.warning(f"设置文件 {filepath} 权限失败: {e}")
            return filepath
        else:
            logger.error(f"cv2.imwrite 保存JPEG图像失败 (返回False): {filepath}")
            consecutive_imwrite_failures +=1 # MODIFICATION v2.0.1
            return None
    except Exception as e:
        logger.error(f"cv2.imwrite 保存图像时发生异常: {e}", exc_info=True)
        consecutive_imwrite_failures +=1 # MODIFICATION v2.0.1
        return None

# --- Disk Space Management ---
def get_oldest_day_dir(base_dir: str) -> str | None: # Identical to v2.0.0
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
    try:
        usage = shutil.disk_usage(IMAGE_STORAGE_MONITOR_PATH)
        percent_used = (usage.used / usage.total) * 100
        logger.info(f"磁盘空间监控: {IMAGE_STORAGE_MONITOR_PATH} - Total: {usage.total // (1024**3)}GB, "
                    f"Used: {usage.used // (1024**3)}GB ({percent_used:.1f}%), "
                    f"Free: {usage.free // (1024**3)}GB")

        if percent_used > IMAGE_STORAGE_MAX_USAGE_PERCENT:
            logger.warning(f"磁盘使用率 ({percent_used:.1f}%) 已超过阈值 ({IMAGE_STORAGE_MAX_USAGE_PERCENT}%). "
                           f"尝试清理 {IMAGE_STORAGE_CLEANUP_BATCH_DAYS} 个最旧的日期目录...")
            
            for i in range(IMAGE_STORAGE_CLEANUP_BATCH_DAYS):
                if shutdown_event.is_set(): 
                    logger.info("Shutdown requested during disk cleanup.")
                    break 
                
                oldest_dir_to_delete = get_oldest_day_dir(IMAGE_SAVE_BASE_DIR)
                if oldest_dir_to_delete:
                    logger.warning(f"准备删除最旧的日期目录 ({i+1}/{IMAGE_STORAGE_CLEANUP_BATCH_DAYS}): {oldest_dir_to_delete}")
                    try:
                        shutil.rmtree(oldest_dir_to_delete)
                        logger.info(f"已成功删除目录: {oldest_dir_to_delete}")
                    except OSError as e:
                        logger.error(f"删除目录 {oldest_dir_to_delete} 失败: {e}", exc_info=True)
                        break 
                else:
                    logger.warning("没有找到可以删除的旧日期目录。")
                    break 
    except FileNotFoundError:
        logger.error(f"磁盘空间监控路径 {IMAGE_STORAGE_MONITOR_PATH} 未找到。")
    except Exception as e:
        logger.error(f"检查或管理磁盘空间时发生错误: {e}", exc_info=True)

# --- Get Current Capture Interval ---
def get_current_capture_interval() -> int: # Identical to v2.0.0
    now_time = datetime.now().time()
    for schedule_item in CAPTURE_SCHEDULE_CONFIG:
        if now_time < schedule_item["end_time_exclusive"]:
            return schedule_item["interval_seconds"]
    return DEFAULT_INTERVAL_LATE_NIGHT

# --- Main Service Logic ---
def run_capture_service():
    global shutdown_event, cap, effective_fourcc # cap and effective_fourcc might be better as instance vars if this were a class
    global consecutive_imwrite_failures, consecutive_read_failures # MODIFICATION v2.0.1
    global last_significant_frame
    last_significant_frame = None # 确保服务启动时重置

    cap = None # Ensure cap is defined in this scope
    effective_fourcc = "NOT_SET_INITIALLY"
    init_failures = 0
    last_disk_check_time = 0
    consecutive_imwrite_failures = 0 # Reset counters at service start
    consecutive_read_failures = 0

    logger.debug(f"图像捕获服务主逻辑启动。")
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
                logger.info("摄像头未连接或需要重新初始化...")
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
                consecutive_read_failures = 0 # Reset read failure counter on successful init

            elapsed_since_last_capture = time.monotonic() - last_capture_time
            wait_time = current_interval - elapsed_since_last_capture

            if wait_time > 0:
                # logger.info(f"当前时间: {datetime.now().strftime('%H:%M:%S')}, 间隔: {current_interval}s. 还需 {wait_time:.2f} 秒...")
                shutdown_event.wait(timeout=wait_time) 
                if shutdown_event.is_set(): break 
            
            if shutdown_event.is_set(): break 

            last_capture_time = time.monotonic() 
            logger.debug(f"尝试捕获图像帧 (当前间隔: {current_interval}s)...")

            for _ in range(4):
                # 清空缓冲帧
                cap.grab();
            ret, frame = cap.read()

            if not ret or frame is None:
                logger.error("无法从摄像头获取图像帧。摄像头可能已断开连接或出现问题。")
                consecutive_read_failures += 1 # MODIFICATION v2.0.1
                logger.info(f"连续读帧失败次数: {consecutive_read_failures}")
                if cap: cap.release()
                cap = None 
                
                if consecutive_read_failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    logger.critical(f"已连续 {consecutive_read_failures} 次无法读取帧。将等待较长时间 ({READ_FAILURE_LONG_BACKOFF_SECONDS}s) 后尝试重连。")
                    shutdown_event.wait(READ_FAILURE_LONG_BACKOFF_SECONDS)
                    consecutive_read_failures = 0 # Reset after long backoff
                else:
                    shutdown_event.wait(FRAME_READ_ERROR_RETRY_DELAY_SECONDS) 
                continue
            
            consecutive_read_failures = 0 # Reset on successful read MODIFICATION v2.0.1

            saved_filepath = process_and_save_frame(
                frame, effective_fourcc, IMAGE_SAVE_BASE_DIR, 
                JPEG_SAVE_QUALITY, TIMESTAMP_FORMAT
            )
            if saved_filepath == "SIMILARITY":
                logger.debug("图像接近，跳过保存")
            elif isinstance(saved_filepath, str) and saved_filepath.lower().endswith(".jpg"):
                logger.debug(f"图像捕获并成功保存: {saved_filepath}")
                # consecutive_imwrite_failures is reset inside process_and_save_frame
            else:
                logger.warning("本次图像捕获未能成功保存。")
                # consecutive_imwrite_failures is incremented inside process_and_save_frame
                if consecutive_imwrite_failures >= MAX_CONSECUTIVE_IMWRITE_FAILURES:
                    logger.critical(f"已连续 {consecutive_imwrite_failures} 次无法保存图像到磁盘。服务将停止。")
                    shutdown_event.set() # Signal shutdown
                    break # Exit while loop

        except cv2.error as e: 
            logger.error(f"主循环中发生 OpenCV 特定错误: {e}", exc_info=True)
            if cap: cap.release()
            cap = None
            logger.info(f"因 OpenCV 错误，将等待 {CAMERA_INIT_RETRY_DELAY_SECONDS}s 后尝试重启摄像头。")
            shutdown_event.wait(CAMERA_INIT_RETRY_DELAY_SECONDS)
        except Exception as e: 
            logger.critical(f"主循环中发生未预料的严重错误: {e}", exc_info=True)
            if cap: cap.release() 
            cap = None
            logger.info(f"因严重错误，将等待 {CAMERA_INIT_LONG_BACKOFF_SECONDS}s 后尝试重启摄像头。")
            shutdown_event.wait(CAMERA_INIT_LONG_BACKOFF_SECONDS)
            # Consider uncommenting 'raise' for systemd to handle restart on truly unrecoverable errors
            # raise

    # Loop exited (likely due to shutdown_event)
    if cap and cap.isOpened():
        logger.info("正在释放摄像头资源...")
        cap.release()
    logger.info("图像捕获服务主逻辑已停止。")


# --- Main Application Entry Point & CLI Argument Parsing ---
def main():
    global logger, PID_FILE_PATH # Allow modification if args change them

    parser = argparse.ArgumentParser(description=f"{SCRIPT_NAME} - Image Capture Service (v{SCRIPT_VERSION})")
    parser.add_argument('action', nargs='?', choices=['start', 'stop', 'status', 'foreground'], 
                        default='foreground', 
                        help="Action: start (daemonize - for traditional init), stop, status, or foreground (default, for systemd/debug).")
    parser.add_argument('--pidfile', default=PID_FILE_PATH, 
                        help=f"Path to PID file (default: {PID_FILE_PATH})")
    parser.add_argument('--logdir', default=LOG_DIR, help=f"Path to log directory (default: {LOG_DIR})")
    parser.add_argument('--loglevel', default=LOG_LEVEL_CONFIG, choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help=f"Logging level (default: {LOG_LEVEL_CONFIG})")
    # For true daemonization with python-daemon, more args like --user, --group, --working-directory would be needed.
    # For now, 'start' is conceptual if not using systemd or a proper daemon library.

    args = parser.parse_args()
    
    PID_FILE_PATH = os.path.abspath(args.pidfile)
    # Initialize logging system (now that PID_FILE_PATH for potential log inside pid dir is known)
    try:
        os.makedirs(args.logdir, exist_ok=True)
        # Also ensure image save base dir exists before service starts trying to write into it.
        if not os.path.exists(IMAGE_SAVE_BASE_DIR): # This check should ideally use an absolute path too
            os.makedirs(IMAGE_SAVE_BASE_DIR, exist_ok=True)
    except OSError as e:
        # If using print before logger is initialized
        print(f"CRITICAL: Failed to create essential directories (Log dir: {args.logdir} or Image Base: {IMAGE_SAVE_BASE_DIR}): {e}", file=sys.stderr)
        sys.exit(1)
    logger = setup_logging_system(args.logdir, LOG_FILE_NAME, args.loglevel.upper(), 
                                  LOG_ROTATE_WHEN, LOG_ROTATE_INTERVAL, LOG_ROTATE_BACKUP_COUNT)

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
