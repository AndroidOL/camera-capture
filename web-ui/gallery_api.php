<?php
// gallery_api.php
// error_reporting(E_ALL); // 开发时建议开启，生产环境建议关闭或记录到日志
// ini_set('display_errors', 1); // 开发时建议开启

require_once 'config.php'; // 引入密码和会话设置, 会自动 session_start()

// --- 会话和认证检查 ---
if (!check_authentication()) { // 使用 config.php 中定义的函数
    // 在输出任何内容之前设置header
    if (!headers_sent()) {
        header('HTTP/1.1 401 Unauthorized'); 
        header('Content-Type: application/json'); // 确保错误也是JSON
    }
    echo json_encode(['error' => '访问未授权或会话已超时，请重新登录。']);
    exit;
}
// --- 结束会话检查 ---

// --- 配置 ---
$basePhotoDir = '/var/www/html/captures'; // 照片在文件系统中的根目录
$webPathToCaptures = '/captures';        // 对应的Web可访问路径前缀 (从Web根目录算起)

// --- 缓存配置 ---
define('CACHE_ENABLED', true);
define('CACHE_DIR', '/tmp/gallery_cache');
define('CACHE_LIFETIME', 3600); // 1小时

// --- 缓存函数 ---
function get_cache_key($action, $params) {
    return md5($action . json_encode($params));
}

function get_cached_data($cache_key) {
    if (!CACHE_ENABLED) return null;
    
    $cache_file = CACHE_DIR . '/' . $cache_key;
    if (file_exists($cache_file) && (time() - filemtime($cache_file)) < CACHE_LIFETIME) {
        return json_decode(file_get_contents($cache_file), true);
    }
    return null;
}

function set_cached_data($cache_key, $data) {
    if (!CACHE_ENABLED) return;
    
    if (!is_dir(CACHE_DIR)) {
        mkdir(CACHE_DIR, 0755, true);
    }
    
    $cache_file = CACHE_DIR . '/' . $cache_key;
    file_put_contents($cache_file, json_encode($data));
}

// --- 安全与辅助函数 ---

/**
 * 清理并验证日期字符串 (YYYY-MM-DD)
 * @param string|null $date_str 输入的日期字符串
 * @return array|null [YYYY, MM, DD] 或 null 如果无效
 */
function sanitize_date($date_str) {
    if (!is_string($date_str)) return null;
    if (preg_match('/^(\d{4})-(\d{2})-(\d{2})$/', $date_str, $matches)) {
        // checkdate 参数顺序: month, day, year
        if (checkdate((int)$matches[2], (int)$matches[3], (int)$matches[1])) {
            return [$matches[1], $matches[2], $matches[3]]; // 返回 [YYYY, MM, DD] 数组
        }
    }
    return null;
}

/**
 * 清理并验证小时字符串 (HH)
 * @param string|null $hour_str 输入的小时字符串
 * @return string|null 格式化的 HH 或 null 如果无效
 */
function sanitize_hour($hour_str) {
    if (!is_string($hour_str)) return null;
    $hour = intval($hour_str);
    if ($hour >= 0 && $hour <= 23) {
        return sprintf('%02d', $hour); // 确保返回两位数，如 "09"
    }
    return null;
}

/**
 * 清理并验证分钟字符串 (MM)
 * @param string|null $minute_str 输入的分钟字符串
 * @return string|null 格式化的 MM 或 null 如果无效
 */
function sanitize_minute($minute_str) {
    if (!is_string($minute_str)) return null;
    $minute = intval($minute_str);
    if ($minute >= 0 && $minute <= 59) {
        return sprintf('%02d', $minute); // 确保返回两位数
    }
    return null;
}

/**
 * 从glob模式匹配的文件列表中获取代表性文件
 * @param string $pattern glob模式
 * @param bool $getNewestAsRepresentative 如果为true，则返回该时段最新的文件作为代表，否则返回最早的
 * @return string|null 文件路径或null
 */
function get_representative_file_from_glob($pattern, $getNewestAsRepresentative = false) {
    $files = glob($pattern);
    if (empty($files)) {
        return null;
    }
    if ($getNewestAsRepresentative) {
        rsort($files); 
    } else {
        sort($files);  
    }
    return $files[0]; 
}

/**
 * 获取文件相对于基础照片目录的相对路径 (用于构建Web URL)
 * @param string|null $full_fs_path 文件的完整文件系统路径
 * @param string $file_system_base_path 照片库在文件系统中的基础路径
 * @return string|null 相对路径或null
 */
function get_relative_path_for_web($full_fs_path, $file_system_base_path) {
    if ($full_fs_path && $file_system_base_path && strpos($full_fs_path, $file_system_base_path) === 0) {
        return ltrim(substr($full_fs_path, strlen($file_system_base_path)), '/\\');
    }
    error_log("Path mismatch in get_relative_path_for_web: full_fs_path '{$full_fs_path}' is not under file_system_base_path '{$file_system_base_path}'");
    return null;
}

/**
 * 获取文件大小
 * @param string $file_path 文件的完整路径
 * @return int|null 文件大小（字节）或 null（如果文件不存在或无法访问）
 */
function get_file_size($file_path) {
    if (file_exists($file_path) && is_readable($file_path)) {
        return filesize($file_path);
    }
    return null;
}

// --- 错误处理和日志记录 ---
function log_error($message, $context = []) {
    $log_entry = date('Y-m-d H:i:s') . " ERROR: " . $message;
    if (!empty($context)) {
        $log_entry .= " Context: " . json_encode($context);
    }
    error_log($log_entry);
}

function handle_error($error_message, $http_code = 500) {
    log_error($error_message);
    if (!headers_sent()) {
        http_response_code($http_code);
        header('Content-Type: application/json');
    }
    echo json_encode(['error' => $error_message]);
    exit;
}

// 设置错误处理器
set_error_handler(function($errno, $errstr, $errfile, $errline) {
    if (!(error_reporting() & $errno)) {
        return false;
    }
    log_error($errstr, [
        'file' => $errfile,
        'line' => $errline,
        'type' => $errno
    ]);
    return true;
});

// 设置异常处理器
set_exception_handler(function($e) {
    log_error($e->getMessage(), [
        'file' => $e->getFile(),
        'line' => $e->getLine(),
        'trace' => $e->getTraceAsString()
    ]);
    handle_error('服务器内部错误，请稍后重试。');
});

// --- API 路由 ---
$action = $_GET['action'] ?? '';
// 确保在所有可能的输出之前设置Content-Type
if (!headers_sent()) {
    header('Content-Type: application/json');
}

// 不需要日期参数的 actions
if ($action === 'getEarliestDate') {
    $earliestDateStr = null;
    $yearMonthDirs = glob($basePhotoDir . '/????-??', GLOB_ONLYDIR); 
    if (!empty($yearMonthDirs)) {
        sort($yearMonthDirs); 
        $earliestYearMonthPath = $yearMonthDirs[0];
        $dayDirs = glob($earliestYearMonthPath . '/[0-3][0-9]', GLOB_ONLYDIR); // 更精确匹配DD
        if (!empty($dayDirs)) {
            $dayBasenames = array_map('basename', $dayDirs);
            sort($dayBasenames, SORT_NUMERIC); 
            if (!empty($dayBasenames)) {
                 $earliestDay = $dayBasenames[0];
                 $yearMonthPart = basename($earliestYearMonthPath); 
                 $earliestDateStr = $yearMonthPart . '-' . sprintf('%02d', (int)$earliestDay);
            }
        }
    }
    echo json_encode(['earliestDate' => $earliestDateStr]);
    exit;
}

if ($action === 'getLatestPhoto') {
    $latestPhotoData = null;
    $yearMonthDirs = glob($basePhotoDir . '/????-??', GLOB_ONLYDIR);
    if (!empty($yearMonthDirs)) {
        rsort($yearMonthDirs); 
        $latestYearMonthPath = $yearMonthDirs[0];
        $dayDirs = glob($latestYearMonthPath . '/[0-3][0-9]', GLOB_ONLYDIR);
        if (!empty($dayDirs)) {
            $dayBasenames = array_map('basename', $dayDirs);
            rsort($dayBasenames, SORT_NUMERIC); 
            if (!empty($dayBasenames)) {
                $latestDay = $dayBasenames[0];
                $latestDayPathOnFs = $latestYearMonthPath . '/' . $latestDay;
                $photoPattern = $latestDayPathOnFs . '/capture_*.jpg';
                $allPhotosInLatestDay = glob($photoPattern);
                if (!empty($allPhotosInLatestDay)) {
                    rsort($allPhotosInLatestDay); 
                    $latestPhotoFullPath = $allPhotosInLatestDay[0];
                    $relative_web_path = get_relative_path_for_web($latestPhotoFullPath, $basePhotoDir);
                    if ($relative_web_path) {
                        $latestPhotoData = [
                            'image_url' => $webPathToCaptures . '/' . $relative_web_path,
                            'filename' => basename($latestPhotoFullPath),
                            'filesize' => get_file_size($latestPhotoFullPath)
                        ];
                    }
                }
            }
        }
    }
    echo json_encode(['latest_photo' => $latestPhotoData]);
    exit;
}


// --- 对于其他需要日期参数的 action ---
$date_input_from_get = $_GET['date'] ?? null;
if ($date_input_from_get === null) {
    // 对于所有剩余的action，date参数都是必需的
    echo json_encode(['error' => "Date parameter is required for action '{$action}'."]);
    exit;
}
$date_str = trim($date_input_from_get);

$date_parts = sanitize_date($date_str);
if (!$date_parts) { 
    echo json_encode(['error' => "Invalid date format for action '{$action}'. Received: '{$date_str}'"]); 
    exit; 
}
list($year, $month, $day) = $date_parts;
$photoDayDirOnFs = "{$basePhotoDir}/{$year}-{$month}/{$day}"; 

if (!is_dir($photoDayDirOnFs)) { 
    echo json_encode([ 
        'error' => "Photo directory not found for date {$date_str}. Path: {$photoDayDirOnFs}", 
        'date' => $date_str,
        'hourly_previews' => [], 'ten_minute_previews' => [], 'minute_previews' => [], 'photos' => [] 
    ]); 
    exit; 
}


// --- 图片处理函数 ---
function generate_thumbnail($source_path, $max_width = 300, $max_height = 300) {
    $cache_key = md5($source_path . $max_width . $max_height);
    $thumbnail_path = CACHE_DIR . '/thumbnails/' . $cache_key . '.jpg';
    
    // 如果缩略图已存在且源文件未修改，直接返回
    if (file_exists($thumbnail_path) && 
        filemtime($thumbnail_path) >= filemtime($source_path)) {
        return $thumbnail_path;
    }
    
    // 确保缩略图目录存在
    if (!is_dir(dirname($thumbnail_path))) {
        mkdir(dirname($thumbnail_path), 0755, true);
    }
    
    // 创建缩略图
    list($width, $height) = getimagesize($source_path);
    $ratio = min($max_width / $width, $max_height / $height);
    $new_width = round($width * $ratio);
    $new_height = round($height * $ratio);
    
    $source = imagecreatefromjpeg($source_path);
    $thumb = imagecreatetruecolor($new_width, $new_height);
    
    imagecopyresampled($thumb, $source, 0, 0, 0, 0, 
        $new_width, $new_height, $width, $height);
    
    imagejpeg($thumb, $thumbnail_path, 80);
    imagedestroy($source);
    imagedestroy($thumb);
    
    return $thumbnail_path;
}

function get_image_data($full_fs_path, $for_preview = false) {
    $filename = basename($full_fs_path);
    $relative_web_path = get_relative_path_for_web($full_fs_path, $basePhotoDir);
    
    if (!$relative_web_path) {
        return null;
    }
    
    $data = [
        'filename' => $filename,
        'filesize' => get_file_size($full_fs_path)
    ];
    
    if ($for_preview) {
        $thumbnail_path = generate_thumbnail($full_fs_path);
        $data['preview_image_url'] = str_replace($basePhotoDir, $webPathToCaptures, $thumbnail_path);
    }
    
    $data['image_url'] = $webPathToCaptures . '/' . $relative_web_path;
    
    return $data;
}

switch ($action) {
    case 'getDailySummary':
        $hourly_previews = [];
        for ($h = 23; $h >= 0; $h--) { 
            $hour_str_glob = sprintf('%02d', $h);
            $pattern = "{$photoDayDirOnFs}/capture_{$year}{$month}{$day}_{$hour_str_glob}*.jpg";
            $representative_file_fs_path = get_representative_file_from_glob($pattern, false); 
            if ($representative_file_fs_path) {
                $relative_web_path = get_relative_path_for_web($representative_file_fs_path, $basePhotoDir);
                if ($relative_web_path) { 
                    $hourly_previews[] = [ 
                        'hour' => $hour_str_glob, 
                        'preview_image_url' => $webPathToCaptures . '/' . $relative_web_path, 
                        'filename' => basename($representative_file_fs_path),
                        'filesize' => get_file_size($representative_file_fs_path)
                    ]; 
                }
            }
        }
        echo json_encode(['date' => $date_str, 'hourly_previews' => $hourly_previews]);
        break;

    case 'getHourlySummary':
        $hour_str = sanitize_hour($_GET['hour'] ?? '');
        if (!$hour_str) { echo json_encode(['error' => 'Hour parameter is invalid or missing.']); exit; }
        $ten_minute_previews = [];
        for ($m_slot = 5; $m_slot >= 0; $m_slot--) { 
            $minute_prefix_for_glob = $m_slot; 
            $pattern = "{$photoDayDirOnFs}/capture_{$year}{$month}{$day}_{$hour_str}{$minute_prefix_for_glob}*.jpg";
            $representative_file_fs_path = get_representative_file_from_glob($pattern, false);
            if ($representative_file_fs_path) {
                $relative_web_path = get_relative_path_for_web($representative_file_fs_path, $basePhotoDir);
                if ($relative_web_path) {
                    $ten_minute_previews[] = [ 
                        'interval_slot' => $m_slot, 
                        'label' => sprintf('%s:%02d - %s:%02d', $hour_str, $m_slot * 10, $hour_str, $m_slot * 10 + 9), 
                        'preview_image_url' => $webPathToCaptures . '/' . $relative_web_path, 
                        'filename' => basename($representative_file_fs_path),
                        'filesize' => get_file_size($representative_file_fs_path)
                    ];
                }
            }
        }
        echo json_encode(['date' => $date_str, 'hour' => $hour_str, 'ten_minute_previews' => $ten_minute_previews]);
        break;

    case 'getTenMinuteSummary':
        $hour_str = sanitize_hour($_GET['hour'] ?? '');
        $interval_slot_str = $_GET['interval_slot'] ?? '';
        $interval_slot = filter_var($interval_slot_str, FILTER_VALIDATE_INT, ['options' => ['min_range' => 0, 'max_range' => 5]]);

        if (!$hour_str || $interval_slot === false) { 
            echo json_encode(['error' => 'Hour or 10-minute interval slot parameter is invalid.']); exit;
        }
        $minute_previews = [];
        $start_minute_value_in_slot = $interval_slot * 10;
        for ($m_offset = 9; $m_offset >= 0; $m_offset--) { 
            $current_minute_value = $start_minute_value_in_slot + $m_offset;
            $minute_str_for_glob = sprintf('%02d', $current_minute_value); 
            $hour_minute_prefix_for_glob = $hour_str . $minute_str_for_glob; 
            
            $pattern = "{$photoDayDirOnFs}/capture_{$year}{$month}{$day}_{$hour_minute_prefix_for_glob}*.jpg";
            $representative_file_fs_path = get_representative_file_from_glob($pattern, false);
            if ($representative_file_fs_path) {
                $relative_web_path = get_relative_path_for_web($representative_file_fs_path, $basePhotoDir);
                if ($relative_web_path){
                    $minute_previews[] = [ 
                        'minute' => $minute_str_for_glob, 
                        'preview_image_url' => $webPathToCaptures . '/' . $relative_web_path, 
                        'filename' => basename($representative_file_fs_path),
                        'filesize' => get_file_size($representative_file_fs_path)
                    ];
                }
            }
        }
        echo json_encode([ 'date' => $date_str, 'hour' => $hour_str, 'interval_slot' => $interval_slot, 'minute_previews' => $minute_previews ]);
        break;

    case 'getMinutePhotos': // 用于层级4网格显示，最新的在前
        $hour_str = sanitize_hour($_GET['hour'] ?? '');
        $minute_str_param = sanitize_minute($_GET['minute'] ?? '');

        if (!$hour_str || $minute_str_param === null) { 
            echo json_encode(['error' => 'Hour or minute parameter is invalid.']); exit;
        }
        $hour_minute_prefix_for_glob = $hour_str . $minute_str_param; 
        $pattern = "{$photoDayDirOnFs}/capture_{$year}{$month}{$day}_{$hour_minute_prefix_for_glob}*.jpg";
        
        $all_photos_fs_paths = glob($pattern);
        if ($all_photos_fs_paths === false) { 
             error_log("glob pattern failed: " . $pattern);
             $all_photos_fs_paths = [];
        }
        rsort($all_photos_fs_paths); // L4网格显示，最新的在前

        $photos_data = [];
        foreach ($all_photos_fs_paths as $full_fs_path) {
            $filename = basename($full_fs_path);
            $relative_web_path = get_relative_path_for_web($full_fs_path, $basePhotoDir);
            if ($relative_web_path) { 
                $photos_data[] = [ 
                    'image_url' => $webPathToCaptures . '/' . $relative_web_path, 
                    'filename' => $filename,
                    'filesize' => get_file_size($full_fs_path)
                ]; 
            }
        }
        echo json_encode([ 'date' => $date_str, 'hour' => $hour_str, 'minute' => $minute_str_param, 'photos' => $photos_data ]);
        break;

    case 'getPhotoListForRange': // 用于全局轮播，最早的在前
        // $date_str, $year, $month, $day, $photoDayDirOnFs 已在前面验证和设置
        
        $hour_param = sanitize_hour($_GET['hour'] ?? null); // 允许为空或null
        $interval_slot_param_str = $_GET['interval_slot'] ?? null; // 允许为空或null
        $minute_param = sanitize_minute($_GET['minute'] ?? null);

        // 添加调试日志，请在生产环境中移除或注释掉
        // error_log("getPhotoListForRange: date={$date_str}, hour=" . ($hour_param ?? 'NULL') . ", interval_slot=" . ($interval_slot_param_str ?? 'NULL') . ", minute=" . ($minute_param ?? 'NULL'));

        $all_photos_fs_paths_for_range = [];
        $pattern_base_for_range = "{$photoDayDirOnFs}/capture_{$year}{$month}{$day}";

        if ($hour_param !== null) { 
            $pattern_base_for_range .= "_{$hour_param}"; 

            if ($minute_param !== null) { // Level 4 context: Specific minute
                $pattern_for_glob = "{$pattern_base_for_range}{$minute_param}*.jpg";
                $files = glob($pattern_for_glob);
                if ($files) $all_photos_fs_paths_for_range = $files;
                // error_log("Pattern (minute): " . $pattern_for_glob . " Found: " . count($all_photos_fs_paths_for_range));
            } elseif ($interval_slot_param_str !== null && $interval_slot_param_str !== '') { // Level 3 context: Specific 10-minute interval
                $slot = filter_var($interval_slot_param_str, FILTER_VALIDATE_INT, ['options' => ['min_range' => 0, 'max_range' => 5]]);
                if ($slot !== false) {
                    $start_minute_val = $slot * 10;
                    for ($m_offset = 0; $m_offset < 10; $m_offset++) {
                        $current_minute_val = $start_minute_val + $m_offset;
                        $minute_prefix_for_glob = sprintf('%02d', $current_minute_val); 
                        $pattern_for_glob = "{$pattern_base_for_range}{$minute_prefix_for_glob}*.jpg";
                        $files_in_minute = glob($pattern_for_glob);
                        if ($files_in_minute) {
                            $all_photos_fs_paths_for_range = array_merge($all_photos_fs_paths_for_range, $files_in_minute);
                        }
                    }
                    // error_log("Pattern (10-min slot {$slot}): Multiple globs. Found total: " . count($all_photos_fs_paths_for_range));
                } else { 
                    $pattern_for_glob = "{$pattern_base_for_range}*.jpg"; 
                    $files = glob($pattern_for_glob);
                    if ($files) $all_photos_fs_paths_for_range = $files;
                    // error_log("Pattern (hour, due to invalid slot): " . $pattern_for_glob . " Found: " . count($all_photos_fs_paths_for_range));
                }
            } else { // Level 2 context: Only hour is specified
                $pattern_for_glob = "{$pattern_base_for_range}*.jpg"; 
                $files = glob($pattern_for_glob);
                if ($files) $all_photos_fs_paths_for_range = $files;
                // error_log("Pattern (hour only): " . $pattern_for_glob . " Found: " . count($all_photos_fs_paths_for_range));
            }
        } else { // Level 1 context: Only date is specified, get all photos for the day
            $pattern_for_glob = "{$pattern_base_for_range}_*.jpg"; 
            $files = glob($pattern_for_glob);
            if ($files) $all_photos_fs_paths_for_range = $files;
            // error_log("Pattern (day only): " . $pattern_for_glob . " Found: " . count($all_photos_fs_paths_for_range));
        }
        
        if ($all_photos_fs_paths_for_range === false) $all_photos_fs_paths_for_range = [];
        sort($all_photos_fs_paths_for_range); // 全局轮播，按时间正序（文件名升序）

        $photos_data_for_range = [];
        foreach ($all_photos_fs_paths_for_range as $full_fs_path) {
            $filename = basename($full_fs_path);
            $relative_web_path = get_relative_path_for_web($full_fs_path, $basePhotoDir);
            if ($relative_web_path) {
                $photos_data_for_range[] = [
                    'image_url' => $webPathToCaptures . '/' . $relative_web_path,
                    'filename' => $filename,
                    'filesize' => get_file_size($full_fs_path)
                ];
            }
        }
        echo json_encode([
            'date' => $date_str, 
            'hour' => ($hour_param !== null && $hour_param !== '') ? $hour_param : null, 
            'interval_slot' => ($interval_slot_param_str !== null && $interval_slot_param_str !== '' && isset($slot) && $slot !== false) ? $slot : null, 
            'minute' => ($minute_param !== null && $minute_param !== '') ? $minute_param : null, 
            'photos' => $photos_data_for_range,
            'total_photos_in_range' => count($photos_data_for_range)
        ]);
        break;

    default:
        echo json_encode(['error' => '无效的操作指令。']);
        break;
}
?>

